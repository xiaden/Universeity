"""Pure deterministic Markdown parser (Phase B, P2-S1).

Produces a normalized block structure (headings -> sections, paragraphs,
images, code/fences as opaque blocks) without any subprocess dependency. The
parser is deliberately small and deterministic: given the same normalized text
it always yields the same block sequence, which is what deterministic segment
IDs require. It is NOT a full CommonMark implementation — it covers the v1
text/allowed-art needs (headings, paragraphs, blockquotes, images, fenced
code) and normalizes the rest into paragraph blocks.

Fenced-code/image-only behaviour follows the deterministic baseline; unknown
syntax is treated as a paragraph so segmentation never drops text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Heading regex: 1-6 '#' followed by space.
_HEADING = "#{1,6} "

#: Inline image ``![alt](src "title")`` — captured for sequential-art structure.
_IMAGE = "!["


@dataclass
class MarkdownBlock:
    """One normalized block in a Markdown document."""

    kind: str  # heading | paragraph | image | blockquote | code | list
    text: str = ""
    level: int | None = None  # heading level 1..6
    image_src: str | None = None  # for image blocks
    image_alt: str | None = None
    ordinal: int = 0


@dataclass
class MarkdownDocument:
    """Parsed, normalized Markdown document."""

    blocks: list[MarkdownBlock] = field(default_factory=list)
    title: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "blocks": [
                {
                    "kind": b.kind,
                    "text": b.text,
                    "level": b.level,
                    "image_src": b.image_src,
                    "image_alt": b.image_alt,
                    "ordinal": b.ordinal,
                }
                for b in self.blocks
            ],
        }


def _parse_inline_image(text: str) -> tuple[str | None, str | None, str]:
    """Return ``(image_src, image_alt, rest)`` if ``text`` is an image-only line."""
    if not text.startswith(_IMAGE):
        return None, None, text
    end = text.find(")")
    if end == -1:
        return None, None, text
    inner = text[2:end]
    # split alt from src: 'alt](src' inside the bracket would break the naive
    # split, but for the image-only baseline we split on the LAST '](' .
    last = inner.rfind("](")
    if last == -1:
        return None, None, text
    alt = inner[:last]
    src = inner[last + 2 :]
    if '"' in src:
        src = src.split(' "')[0].split(' "')[0]  # strip optional title
    return (src or None, alt or None, text)


def parse_markdown(normalized: str) -> MarkdownDocument:
    """Parse normalized Markdown text into a :class:`MarkdownDocument`."""
    doc = MarkdownDocument()
    lines = normalized.split("\n")
    blocks: list[MarkdownBlock] = []
    i = 0
    ordinal = 0
    while i < len(lines):
        line = lines[i].rstrip()

        # Heading (ATX: 1-6 ``#`` then space/EOL)
        if line.startswith("#") and (len(line) == 1 or line[1] in "# "):
            level = len(line) - len(line.lstrip("#"))
            level = max(1, min(6, level))
            text = line[level:].lstrip()
            if blocks and blocks[-1].kind == "heading" and doc.title is None and level == 1:
                doc.title = text
            blocks.append(MarkdownBlock(kind="heading", text=text, level=level, ordinal=ordinal))
            ordinal += 1
            i += 1
            continue

        # Fenced code (opaque — not segmented into prose)
        if line.startswith("```") or line.startswith("~~~"):
            fence = line[0]
            # Advance past the opening fence line itself (which always matches the
            # fence marker) so the skip-loop consumes the interior up to the
            # closing fence — the fence body must never leak as prose.
            i += 1
            while i < len(lines) and not lines[i].startswith(fence * 3):
                i += 1
            blocks.append(MarkdownBlock(kind="code", text="<fenced>", ordinal=ordinal))
            ordinal += 1
            i += 1
            continue

        # Blank line -> paragraph boundary
        if line == "":
            i += 1
            continue

        # Blockquote
        if line.startswith(">"):
            text = line.lstrip(">").lstrip()
            blocks.append(MarkdownBlock(kind="blockquote", text=text, ordinal=ordinal))
            ordinal += 1
            i += 1
            continue

        # Image-only line (sequential-art composition)
        src, alt, _rest = _parse_inline_image(line.strip())
        if src is not None:
            blocks.append(
                MarkdownBlock(kind="image", image_src=src, image_alt=alt, ordinal=ordinal)
            )
            ordinal += 1
            i += 1
            continue

        # List item
        stripped = line.lstrip()
        if line.startswith(("-", "*", "+")) or (stripped[:2] in ("1.", "- ", "* ")):
            text = line.lstrip("-*+0123456789. ").strip()
            blocks.append(MarkdownBlock(kind="list", text=text, ordinal=ordinal))
            ordinal += 1
            i += 1
            continue

        # Paragraph: accumulate consecutive non-blank lines.
        para_lines = [line]
        while i + 1 < len(lines) and lines[i + 1].strip() != "":
            i += 1
            para_lines.append(lines[i].rstrip())
        blocks.append(MarkdownBlock(kind="paragraph", text=" ".join(para_lines), ordinal=ordinal))
        ordinal += 1
        i += 1

    doc.blocks = blocks
    return doc
