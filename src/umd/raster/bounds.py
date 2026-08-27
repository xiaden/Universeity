"""Bounded Pillow decode, metadata, and IIIF crop math (Phase B, P3-S1).

Implements the DD raster contract's *bounded* obligations:

  * **pixel budget** — a decoded image may not exceed an explicit pixel and
    per-dimension budget (``RasterLimits``), on top of Pillow's own
    decompression-bomb guard (``Image.MAX_IMAGE_PIXELS``). An oversized image is
    rejected deterministically -> quarantine, never decoded into memory.
  * **metadata** — format/mode/dimensions/ICCP/Exif are extracted via a bounded,
    allowlisted subset (no unbounded metadata parsing).
  * **IIIF-compatible crops** — a crop region is expressed as an ``xywh`` (pixel)
    or ``pct`` (percentage) IIIF selector and applied as a bounded crop.

Oversized/malformed inputs raise :class:`RasterError` subclasses; the caller
(quarantine) decides they are deterministic failures and never retried.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

from PIL import (
    ExifTags,  # noqa: F401  (re-exported for metadata key names)
    Image,
    ImageFile,
)

from umd.domain.locators import IIIFSelector, Selector


class RasterError(RuntimeError):
    """Base error for all bounded-raster failures (decode / limits / crop)."""


class RasterDecodeError(RasterError):
    """The byte stream is not a decodable/supported image (deterministic)."""


class RasterLimitsExceeded(RasterError):  # noqa: N818 - stable public name used widely
    """The image dimensions/pixels exceed the bounded decode budget.

    Raised *before* any large in-memory allocation: the header is inspected and
    the budget checked first (decompression-bomb guard).
    """


class CropOutOfBoundsError(RasterError):
    """A crop selector lies outside the decoded image bounds."""


MAX_PIXEL_FALLBACK = 20 * 1024 * 1024  # 20M px default bomb guard


@dataclass(frozen=True)
class RasterLimits:
    """Pixel/dimension/decode budget applied to every raster decode."""

    #: Hard cap on total decoded pixels (w*h) — decompression-bomb guard.
    max_pixels: int = 40_000_000
    #: Hard cap on a single dimension (w or h) in pixels.
    max_dimension: int = 20_000
    #: Cap on the header-declared pixel count Pillow itself refuses past.
    bomb_warning_pixels: int = 178_956_970  # Pillow default (2**29 pixels)

    def check(self, width: int, height: int) -> None:
        """Validate dimensions against the budget; raise if exceeded."""
        if width <= 0 or height <= 0:
            raise RasterDecodeError(f"invalid image dimensions {width}x{height}")
        if width > self.max_dimension or height > self.max_dimension:
            raise RasterLimitsExceeded(
                f"image dimension {width}x{height} exceeds {self.max_dimension} px/axis"
            )
        if width * height > self.max_pixels:
            raise RasterLimitsExceeded(
                f"image has {width * height} pixels, exceeds budget {self.max_pixels}"
            )


@dataclass
class RasterImage:
    """A bounded decoded raster image and its immutable-derived metadata."""

    img: Image.Image
    width: int
    height: int
    mode: str
    format: str | None
    raw_sha512: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def close(self) -> None:
        self.img.close()

    def __enter__(self) -> RasterImage:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def decode_bounded(raw: bytes, limits: RasterLimits | None = None) -> RasterImage:
    """Bounded-decode ``raw`` image bytes into a :class:`RasterImage`.

    The Pillow decompression-bomb guard is armed to the configured budget, then
    the header dimensions are validated against :class:`RasterLimits` BEFORE the
    pixel data is materialized, so an oversized/bomb image raises without a large
    allocation. Images are normalized to RGB.
    """
    limits = limits or RasterLimits()
    if not raw:
        raise RasterDecodeError("empty image bytes")

    previous_bomb = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = limits.bomb_warning_pixels  # noqa: S300 - explicit budget
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    try:
        try:
            img = Image.open(io.BytesIO(raw))
        except Exception as exc:  # noqa: BLE001 - decode errors are heterogeneous
            raise RasterDecodeError(f"cannot decode image: {exc}") from exc
        try:
            w, h = img.size
            limits.check(w, h)
            try:
                rgb = img.convert("RGB")
            except Exception as exc:  # noqa: BLE001
                raise RasterDecodeError(f"cannot convert image to RGB: {exc}") from exc
            fmt = img.format
            return RasterImage(
                img=rgb,
                width=w,
                height=h,
                mode=rgb.mode,
                format=fmt,
                metadata=_bounded_metadata(img, w, h),
            )
        finally:
            img.close()
    finally:
        Image.MAX_IMAGE_PIXELS = previous_bomb


def _bounded_metadata(img: Image.Image, width: int, height: int) -> dict[str, Any]:
    """Bounded, allowlisted metadata subset from a decoded Pillow image.

    Only a fixed set of well-understood keys is carried; arbitrary Exif free-form
    values are not copied verbatim (bounded, no unbounded metadata parsing).
    """
    meta: dict[str, Any] = {
        "format": img.format,
        "mode": img.mode,
        "width": width,
        "height": height,
        "dpi": img.info.get("dpi"),
        "icc_profile_present": bool(img.info.get("icc_profile")),
    }
    exif = img.getexif()
    bounded_exif: dict[str, Any] = {}
    if exif:
        for tag_id, label in _EXIF_ALLOWLIST.items():
            try:
                val = exif.get(tag_id)
            except Exception:  # noqa: BLE001, S112 - malformed exif value, skip deterministically
                continue
            if val is not None:
                bounded_exif[label] = _scalar(val)
    meta["exif"] = bounded_exif
    return meta


def _scalar(value: Any) -> Any:
    if isinstance(value, tuple):
        return list(value)
    if hasattr(value, "hex") and not isinstance(value, str):
        return value.hex()
    return value


#: Exif tags we carry (by integer tag id -> stable label). Bounded allowlist: only
#: orientation and related basic tags; everything else stays in the raw OCFL bytes.
_EXIF_ALLOWLIST: dict[int, str] = {
    getattr(ExifTags.Base, "Orientation", 0x0112): "orientation",
    getattr(ExifTags.Base, "ResolutionUnit", 0x0128): "resolution_unit",
    getattr(ExifTags.Base, "XResolution", 0x011A): "x_resolution",
    getattr(ExifTags.Base, "YResolution", 0x011B): "y_resolution",
}


def iiif_region_for(box: tuple[int, int, int, int]) -> str:
    """IIIF ``xywh`` region string for an integer pixel box ``(x, y, w, h)``."""
    x, y, w, h = box
    if w < 0 or h < 0 or x < 0 or y < 0:
        raise CropOutOfBoundsError(f"negative crop box {box}")
    return f"{x},{y},{w},{h}"


def crop_bounded(image: RasterImage, selector: Selector) -> Image.Image:
    """Apply an IIIF ``xywh``/``pct`` selector to produce a bounded crop image.

    The returned crop is fully within the decoded image bounds (an out-of-bounds
    region raises :class:`CropOutOfBoundsError`).
    """
    if not isinstance(selector, IIIFSelector):
        raise CropOutOfBoundsError(f"crop requires an IIIFSelector, got {type(selector).__name__}")
    region = selector.region
    if region.lower().startswith("pct:"):
        xr, yr, wr, hr = (float(p) for p in region[4:].split(","))
        box = _pct_to_box(xr, yr, wr, hr, image.width, image.height)
    else:
        x, y, w, h = (int(p) for p in region.split(","))
        box = (x, y, w, h)
    x, y, w, h = box
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > image.width or y + h > image.height:
        raise CropOutOfBoundsError(f"crop {region} outside {image.width}x{image.height}")
    return image.img.crop((x, y, x + w, y + h))


def _pct_to_box(
    xr: float, yr: float, wr: float, hr: float, width: int, height: int
) -> tuple[int, int, int, int]:
    if wr <= 0 or hr <= 0:
        raise CropOutOfBoundsError("pct crop with non-positive width/height")
    x = round(xr / 100.0 * width)
    y = round(yr / 100.0 * height)
    w = round(wr / 100.0 * width)
    h = round(hr / 100.0 * height)
    return (x, y, w, h)
