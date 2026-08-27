"""Text/book parser tests (Phase B, P2-S1): TXT, Markdown, EPUB, PDF.

Covers deterministic decoding/normalization, the pure Markdown parser, stdlib
EPUB extraction with the AGPL-avoidance gate, and pypdf text-layer detection with
image-only routing.
"""

from __future__ import annotations

import pathlib

import pytest

from fixtures import (
    epub_bytes,
    malformed_epub_bytes,
    markdown_bytes,
    pdf_image_only_bytes,
    pdf_text_bytes,
    txt_bytes,
)
from umd.extractors.epub import EpubParseError, extract_epub
from umd.extractors.markdown import parse_markdown
from umd.extractors.pdf import detect_pdf_text
from umd.extractors.txt import normalize_txt


class TestTxt:
    def test_bom_handled_and_normalizes(self) -> None:
        n = normalize_txt(txt_bytes(bom=True))
        assert n.bom_stripped is True
        assert n.encoding == "utf-8"
        # BOM prefix (EF BB BF) removed; line endings normalized to \n.
        assert not n.text.startswith("\ufeff")
        assert "\r" not in n.text

    def test_strips_utf8_bom_by_prefix(self) -> None:
        n = normalize_txt(b"\xef\xbb\xbfhello")
        assert n.text == "hello"

    def test_raw_bytes_retained_authoritative(self) -> None:
        raw = txt_bytes()
        n = normalize_txt(raw)
        assert n.raw_sha512 is not None  # digest of raw bytes retained


class TestMarkdown:
    def test_parses_headings_paragraphs_image(self) -> None:
        doc = parse_markdown(normalize_txt(markdown_bytes()).text)
        kinds = [b.kind for b in doc.blocks]
        assert "heading" in kinds
        assert "paragraph" in kinds
        img = next(b for b in doc.blocks if b.kind == "image")
        assert img.image_src == "img/panel1.png"
        assert img.image_alt

    def test_deterministic_same_input(self) -> None:
        text = normalize_txt(markdown_bytes()).text
        a = parse_markdown(text)
        b = parse_markdown(text)
        assert a.to_dict() == b.to_dict()

    def test_fenced_code_is_opaque(self) -> None:
        # A fenced-code region must be consumed as ONE opaque code block; its
        # interior (and the closing fence) must never leak as prose paragraphs.
        text = "before\n\n```python\nx=1\ny=2\n```\n\nafter\n"
        doc = parse_markdown(text)
        kinds = [b.kind for b in doc.blocks]
        assert kinds == ["paragraph", "code", "paragraph"]
        code = next(b for b in doc.blocks if b.kind == "code")
        assert code.text == "<fenced>"
        prose = [b.text for b in doc.blocks if b.kind == "paragraph"]
        assert prose == ["before", "after"]
        assert all("x=1" not in t and "y=2" not in t and "```" not in t for t in prose)


class TestEpub:
    def test_stdlib_extraction_no_ebooklib(self) -> None:
        # AGPL-avoidance gate: extraction uses stdlib zipfile + xml, never ebooklib.

        src = pathlib.Path(__file__).parent.parent / "src" / "umd" / "extractors" / "epub.py"
        source = src.read_text()
        assert "import ebooklib" not in source and "from ebooklib" not in source
        assert "zipfile" in source

    def test_extracts_title_spine_paragraphs_cfi(self, tmp_path) -> None:
        p = tmp_path / "b.epub"
        p.write_bytes(epub_bytes())
        e = extract_epub(p)
        assert e.title == "The Garden"
        assert len(e.spine) == 1
        paras = e.spine[0].paragraphs
        assert ["Hello," in x.text for x in paras]
        # CFI locators are valid epubcfi(...) selectors
        assert paras[0].cfi.startswith("epubcfi(") and paras[0].cfi.endswith(")")

    def test_malformed_archive_rejected(self, tmp_path) -> None:
        p = tmp_path / "bad.epub"
        p.write_bytes(malformed_epub_bytes())
        with pytest.raises(EpubParseError):
            extract_epub(p)


class TestPdf:
    def test_viable_text_pdf_detected(self, tmp_path) -> None:
        p = tmp_path / "t.pdf"
        p.write_bytes(pdf_text_bytes())
        r = detect_pdf_text(p)
        assert r.has_any_text
        assert not r.pages[0].image_only
        assert r.pages[0].text.strip() == "Hello from the text layer"

    def test_image_only_pdf_routes_to_raster(self, tmp_path) -> None:
        p = tmp_path / "i.pdf"
        p.write_bytes(pdf_image_only_bytes())
        r = detect_pdf_text(p)
        assert r.pages[0].image_only
        assert not r.has_any_text

    def test_embedded_image_in_text_pdf_not_flattened(self, tmp_path) -> None:
        # A text PDF is not treated as image-only just because it has an image.
        p = tmp_path / "t.pdf"
        p.write_bytes(pdf_text_bytes())
        r = detect_pdf_text(p)
        assert r.has_any_text
