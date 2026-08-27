"""Deterministic pixel-font text rendering for raster fixtures + ref OCR (P3-S2).

Both the fixture generator and the reference OCR provider use the SAME
deterministic renderer: a small 7-pixel-tall bitmap font whose letters within a
word are overlapped by one column so each *word* is ONE connected ink component
(and blank ``_WORD_GAP`` columns keep separate words distinct). Because the
provider and the fixture share the exact renderer and scale,
``ReferenceOcrProvider`` genuinely decodes the image's pixels and
template-matches them — it never fabricates OCR text for an image it did not
actually process.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, cast

from PIL import Image

#: Pixel font glyphs (7 rows tall; '#'=ink). Each row string's length is the glyph width.
_FONT: Final[dict[str, tuple[str, ...]]] = {
    "H": ("#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "L": ("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "P": ("####.", "#...#", "#...#", "####.", "#....", "#....", "#...."),
    "A": (".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "N": ("#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"),
    "T": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "W": ("#.....#", "#.....#", "#.....#", "#.#.#.#", "#.#.#.#", "#.#.#.#", ".#.#.#."),
    "F": ("#####", "#....", "#....", "####.", "#....", "#....", "#...."),
    "C": (".####", "#....", "#....", "#....", "#....", "#....", ".####"),
    "S": (".####", "#....", "#....", ".###.", "....#", "....#", "####."),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "D": ("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
}

#: The fixed vocabulary the reference provider recognizes (the fixture corpus).
REFERENCE_WORDS: Final[tuple[str, ...]] = (
    "HELLO",
    "WORLD",
    "PANEL",
    "ONE",
    "TWO",
    "FACES",
)

#: Integer scale of the pixel font (renders each glyph pixel as ``scale`` px).
FONT_SCALE = 2

_GLYPH_H = 7

#: Horizontal overlap (columns) between consecutive letters so each whole word is
#: a single connected dark component (no letter fragmentation).
_OVERLAP = 1

#: Blank columns inserted between words so word components stay distinct.
_WORD_GAP = 3


def _word_rows(word: str) -> list[str]:
    """Raw (unscaled) 7-row word bitmap; letters overlapped, words gap-separated.

    Consecutive letters are placed with a ``_OVERLAP`` column overlap (the next
    letter's leftmost column shares a cell with the previous letter's rightmost
    column), so a whole word forms one connected ink component; a space advances
    the cursor by ``_WORD_GAP`` blank columns so words stay distinct components.
    """
    rows: list[str] = [""] * _GLYPH_H
    col = 0
    for ch in word:
        if ch == " ":
            col += _WORD_GAP
            continue
        glyph = _FONT[ch]
        gw = len(glyph[0])
        need = col + gw
        for r in range(_GLYPH_H):
            if len(rows[r]) < need:
                rows[r] += "." * (need - len(rows[r]))
            seg = list(rows[r])
            g = glyph[r]
            for i in range(gw):
                if g[i] == "#":
                    seg[col + i] = "#"
            rows[r] = "".join(seg)
        col += gw - _OVERLAP
    for r in range(_GLYPH_H):
        if len(rows[r]) == 0:
            rows[r] = "."
    return rows


def _word_width(word: str) -> int:
    return len(_word_rows(word)[0])


@dataclass(frozen=True)
class WordPattern:
    """A deterministic rendered word pattern (image + dims) used for matching."""

    text: str
    image: Image.Image
    width: int
    height: int


def render_word(text: str, scale: int = FONT_SCALE) -> WordPattern:
    """Render ``text`` as a connected monochrome word; return its scaled image."""
    rows = _word_rows(text)
    w = len(rows[0]) * scale
    h = _GLYPH_H * scale
    img = Image.new("L", (w, h), 255)
    px = img.load()
    assert px is not None  # noqa: S101 - mypy narrowing on open PIL image
    for ry, row in enumerate(rows):
        for cx, ch in enumerate(row):
            if ch != "#":
                continue
            for dy in range(scale):
                for dx in range(scale):
                    px[cx * scale + dx, ry * scale + dy] = 0
    return WordPattern(text=text, image=img, width=w, height=h)


def draw_text_line(
    image: Image.Image, text: str, xy: tuple[int, int], scale: int = FONT_SCALE
) -> None:
    """Draw a single line of connected pixel text onto ``image`` at pixel ``xy``.

    ``image`` must be a light mode image (the word's dark ink is composited onto
    the existing pixels without clearing — words assume a light background).
    """
    pattern = render_word(text, scale=scale)
    x0, y0 = xy
    target = image.convert("RGB")
    target.paste(pattern.image, (x0, y0))
    image.paste(target, (0, 0))


def binarize_pattern(img: Image.Image) -> list[list[bool]]:
    """Convert a grayscale image to a boolean dark/light mask (row-major)."""
    grays = img.convert("L")
    w, h = img.size
    px = grays.load()
    assert px is not None  # noqa: S101 - mypy narrowing on open PIL image
    return [[bool(cast(int, px[x, y]) < 128) for x in range(w)] for y in range(h)]
