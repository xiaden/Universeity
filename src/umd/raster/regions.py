"""Deterministic spatial region/panel extraction with reading order (P3-S1/S3).

A custom, deterministic extractor over Pillow (no OpenCV required):

  * **ink regions** — dark (text/line) connected components, found with a
    deterministic row-major flood fill, bounding-boxed, and ordered top-to-bottom
    then left-to-right (a deterministic *reading order*).
  * **panels/regions** — solid-color connected components distinct from the page
    background (comic-style panels), likewise deterministically ordered and
    boxed IIIF-compatible.

Everything here is deterministic: identical input pixels produce identical
regions/boxes/order. Regions are emitted as IIIF ``xywh`` selectors so they are
directly addressable and crop-retrievable. OpenCV is an optional enhanced path
(gated); this module is the bounded baseline the DD pre-approves.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import cast

from umd.raster.bounds import RasterImage


@dataclass(frozen=True)
class Box:
    """An integer pixel box (x, y, width, height)."""

    x: int
    y: int
    w: int
    h: int

    @property
    def area(self) -> int:
        return self.w * self.h

    @property
    def xywh(self) -> str:
        return f"{self.x},{self.y},{self.w},{self.h}"

    @property
    def center_row_col(self) -> tuple[int, int]:
        return (self.y + self.h // 2, self.x + self.w // 2)


@dataclass(frozen=True)
class Region:
    """A detected spatial region with its deterministic ordering index."""

    box: Box
    kind: str  # "panel" | "region"
    color: tuple[int, int, int] | None
    reading_order: int  # 1-based, deterministic top-to-bottom then left-to-right


def _dark_threshold() -> int:
    return 128


def _binarize(image: RasterImage) -> tuple[list[list[bool]], int, int]:
    """Convert the RGB image to a boolean dark/light mask (row-major)."""
    gray = image.img.convert("L")
    threshold = _dark_threshold()
    w, h = image.width, image.height
    pixels = gray.load()
    assert pixels is not None  # noqa: S101 - mypy narrowing on open PIL image
    mask: list[list[bool]] = []
    for y in range(h):
        row: list[bool] = []
        for x in range(w):
            row.append(bool(cast(int, pixels[x, y]) < threshold))
        mask.append(row)
    return mask, w, h


def _components(mask: list[list[bool]], w: int, h: int, *, dark: bool) -> list[Box]:
    """Deterministic connected components of ``dark`` (True) cells.

    Row-major scan + BFS flood fill; ties break by (row, col) so the output box
    order is fully determined by the input pixels alone.
    """
    visited: list[list[bool]] = [[False] * w for _ in range(h)]
    boxes: list[Box] = []
    for y0 in range(h):
        for x0 in range(w):
            if visited[y0][x0] or mask[y0][x0] != dark:
                continue
            min_x = max_x = x0
            min_y = max_y = y0
            q: deque[tuple[int, int]] = deque([(y0, x0)])
            visited[y0][x0] = True
            while q:
                y, x = q.popleft()
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y
                for ny, nx in (
                    (y - 1, x),
                    (y + 1, x),
                    (y, x - 1),
                    (y, x + 1),
                ):
                    if 0 <= ny < h and 0 <= nx < w and not visited[ny][nx] and mask[ny][nx] == dark:
                        visited[ny][nx] = True
                        q.append((ny, nx))
            boxes.append(Box(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1))
    return boxes


def _reading_order(boxes: list[Box]) -> list[Box]:
    """Order boxes top-to-bottom, then left-to-right (deterministic reading order)."""
    return sorted(boxes, key=lambda b: (b.center_row_col[0], b.center_row_col[1]))


def _runs(cols: list[bool]) -> list[tuple[int, int]]:
    """Maximal runs of ``True`` as inclusive (start, end) index pairs."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for i, v in enumerate(cols):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(cols) - 1))
    return runs


def find_ink_regions(image: RasterImage, *, min_area: int = 4) -> list[Region]:
    """Detect dark ink (text) as whole-word boxes in deterministic reading order.

    Rather than relying on 4-connected components (which fragment glyphs whose
    vertical strokes are joined to the letter body only diagonally, e.g. ``O``),
    text is split deterministically by *projection*: first into horizontal line
    bands (rows containing ink), then into word strips within each band (columns
    containing ink). Each resulting box is a whole word, ordered top-to-bottom
    then left-to-right.
    """
    mask, w, h = _binarize(image)
    ink_row = [any(row) for row in mask]
    regions: list[Region] = []
    order = 1
    for ly0, ly1 in _runs(ink_row):
        col_ink = [any(mask[y][x] for y in range(ly0, ly1 + 1)) for x in range(w)]
        for lx0, lx1 in _runs(col_ink):
            ys = [y for y in range(ly0, ly1 + 1) if any(mask[y][x] for x in range(lx0, lx1 + 1))]
            if not ys:
                continue
            box = Box(lx0, min(ys), lx1 - lx0 + 1, max(ys) - min(ys) + 1)
            if box.area < min_area:
                continue
            regions.append(Region(box=box, kind="region", color=None, reading_order=order))
            order += 1
    return regions


def _quantize_color(c: tuple[int, int, int]) -> tuple[int, int, int]:
    """Coarse color quantization so near-identical colors merge deterministically."""
    return (c[0] & 0xF8, c[1] & 0xF8, c[2] & 0xF8)


def detect_panels(
    image: RasterImage,
    *,
    min_fill: int = 1200,
    background: tuple[int, int, int] | None = None,
) -> list[Region]:
    """Detect solid-color panels distinct from the page background.

    A panel is a connected region whose dominant quantized color differs from the
    page background and whose fill area exceeds ``min_fill``. Panels are ordered
    in deterministic reading order.
    """
    if background is None:
        _px = image.img.getpixel((0, 0))
        assert isinstance(_px, tuple) and len(_px) >= 3  # noqa: S101 - RGB pixel tuple is fixed
        background = (_px[0], _px[1], _px[2])
    bg_q = _quantize_color(background)
    w, h = image.width, image.height
    pixels = image.img.load()
    assert pixels is not None  # noqa: S101 - mypy narrowing on open PIL image
    mask: list[list[bool]] = []
    for y in range(h):
        row: list[bool] = []
        for x in range(w):
            px = cast(tuple[int, int, int], pixels[x, y])
            row.append(_quantize_color((px[0], px[1], px[2])) != bg_q)
        mask.append(row)

    comps = [b for b in _components(mask, w, h, dark=True) if b.area >= min_fill]
    ordered = _reading_order(comps)
    regions: list[Region] = []
    for i, b in enumerate(ordered, start=1):
        # Representative color at the region's center (deterministic).
        cx, cy = b.x + b.w // 2, b.y + b.h // 2
        c = cast(tuple[int, int, int], pixels[cx, cy])
        regions.append(Region(box=b, kind="panel", color=(c[0], c[1], c[2]), reading_order=i))
    return regions
