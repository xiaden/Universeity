"""IIIF crop selectors -> bounded OCFL derived artifact bytes (Phase B, P3-S1).

Every region/panel/crop is addressable by an IIIF ``xywh``/``pct`` selector. The
crop bytes are stored as OCFL **derived** objects (content-addressed, kind
``derived``) and referenced by a Postgres ``artifact`` row — the graph never holds
the only copy. Retrieval returns bounded crop bytes via the store's bounded
``get_range``.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Protocol

from PIL import Image

from umd.domain.locators import IIIFSelector
from umd.raster.bounds import RasterImage, crop_bounded
from umd.storage.ocfl import SourceDescriptor, SourceStore


class ArtifactRecorder(Protocol):
    """Records a content-addressed artifact reference row."""

    def record(
        self,
        ocfl_ref: str,
        sha512: str,
        size_bytes: int,
        kind: str = "derived",
        source_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Any: ...


@dataclass(frozen=True)
class CropRecord:
    """A stored crop: OCFL derived ref + its IIIF provenance + bounds."""

    ocfl_ref: str
    selector: str
    sha512: str
    size_bytes: int
    width: int
    height: int
    generated_by: dict[str, Any]
    is_new: bool


def _serialize_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def store_crop(
    store: SourceStore,
    artifacts: ArtifactRecorder,
    *,
    source_id: str,
    raster: RasterImage,
    selector: IIIFSelector,
    generated_by: dict[str, Any],
    logical_name: str | None = None,
) -> CropRecord:
    """Bounded-crop from an IIIF selector and store the derived bytes.

    Crop bounds are validated against the decoded image; the crop is serialized
    deterministically (PNG) and stored as an OCFL derived object + artifact row.
    """
    crop = crop_bounded(raster, selector)
    png = _serialize_png(crop)
    name = logical_name or f"crop_{selector.region.replace('/', '_').replace(':', '_')}.png"
    descriptor = SourceDescriptor(
        logical_name=name,
        media_kind="image",
        format="png",
        kind="derived",
        content_type="image/png",
    )
    manifest = store.put_immutable(io.BytesIO(png), descriptor)
    ref = artifacts.record(
        ocfl_ref=manifest.object_id,
        sha512=manifest.sha512,
        size_bytes=manifest.size_bytes,
        kind="derived",
        source_id=source_id,
        meta={"selector": selector.region},
    )
    return CropRecord(
        ocfl_ref=manifest.object_id,
        selector=selector.region,
        sha512=manifest.sha512,
        size_bytes=manifest.size_bytes,
        width=crop.width,
        height=crop.height,
        generated_by=generated_by,
        is_new=ref.is_new,
    )


def retrieve_crop(store: SourceStore, ocfl_ref: str) -> bytes:
    """Return the bounded crop bytes for a stored derived-artifact ref."""
    native = store.get_range(ocfl_ref, 0, None)
    return bytes(native.data)
