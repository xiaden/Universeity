"""PDF text-layer detection (Phase B, P2-S1).

Uses permissive, typed ``pypdf`` (BSD-3-Clause) for **text-layer detection only**.
For every page we extract the text layer; a page with no usable text (no
non-whitespace characters) is flagged ``image_only = True`` and **routed to the
raster/OCR path** (a Plan-C stage name ``RASTER_OCR``) — OCR is NOT implemented
in this phase; we only emit the routing signal/segment.

Raw PDF bytes remain authoritative; page/count detection never rewrites them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pypdf import PdfReader


@dataclass
class PdfPageText:
    """Text layer of one PDF page."""

    page_index: int
    text: str
    image_only: bool = False
    char_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_index": self.page_index,
            "image_only": self.image_only,
            "char_count": self.char_count,
            "text": self.text,
        }


@dataclass
class PdfTextResult:
    """Result of PDF text-layer detection."""

    path: str
    page_count: int = 0
    pages: list[PdfPageText] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_any_text(self) -> bool:
        return any(not p.image_only for p in self.pages)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_count": self.page_count,
            "has_any_text": self.has_any_text,
            "warnings": self.warnings,
            "pages": [p.to_dict() for p in self.pages],
        }


class PdfParseError(ValueError):
    """Deterministic PDF parse failure (unreadable/unsupported)."""


def detect_pdf_text(pdf_path: Path) -> PdfTextResult:
    """Detect the usable text layer per page for a PDF file.

    :param pdf_path: path to the PDF (staged in the read-only spool).
    :raises PdfParseError: the file cannot be read as a PDF.
    """
    try:
        reader = PdfReader(str(pdf_path))
        pages = reader.pages
    except Exception as exc:  # noqa: BLE001 - pypdf raises broadly; classify below
        raise PdfParseError(f"cannot read PDF: {exc}") from exc

    result = PdfTextResult(path=str(pdf_path), page_count=len(pages))
    for idx, page in enumerate(pages):
        try:
            text = (page.extract_text() or "").strip()
        except Exception as exc:  # noqa: BLE001 - per-page extraction failure
            result.warnings.append(f"page {idx} text extraction failed: {exc}")
            text = ""
        chars = len(text)
        image_only = chars == 0
        result.pages.append(
            PdfPageText(
                page_index=idx,
                text=text,
                image_only=image_only,
                char_count=chars,
            )
        )
    return result
