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
    multi_chapter_epub_bytes,
    pdf_image_only_bytes,
    pdf_text_bytes,
    txt_bytes,
)
from umd.extractors.dispatch import TextDispatch, TextDispatchResult, dispatch_text
from umd.extractors.epub import EpubDocument, EpubParseError, extract_epub
from umd.extractors.markdown import MarkdownDocument, parse_markdown
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


class TestTextDispatch:
    """Plan L P3-S1: the shared production text-dispatch result.

    ``dispatch_text`` selects the format-appropriate parser (TXT→``normalize_txt``,
    Markdown→``parse_markdown``, EPUB→``extract_epub``, PDF→the existing PDF path),
    records provenance/status, and never surfaces raw binary as normalized text.
    """

    def test_result_shape_records_format_route_versions(self) -> None:
        res = dispatch_text(txt_bytes(), format="txt", source_sha512="s" * 128)
        assert isinstance(res, TextDispatchResult)
        assert res.format == "txt"
        assert res.parser == "txt"
        assert res.route == "text"
        assert not res.non_text and not res.degraded
        assert res.text
        assert res.parser_version == "umd-txt@1"
        assert res.decoder_version == "umd-stdlib-decode@1"
        assert res.config_digest == "umd-dispatch@1"
        assert res.source_sha512 == "s" * 128

    def test_txt_selects_normalize_txt(self) -> None:
        res = dispatch_text(txt_bytes(), format="txt")
        assert res.parser == "txt" and res.route == "text"
        assert res.text.startswith("Chapter 1")

    def test_markdown_selects_parse_markdown(self) -> None:
        res = dispatch_text(markdown_bytes(), format="markdown")
        assert res.parser == "markdown" and res.route == "text"
        assert isinstance(res.document, MarkdownDocument)
        assert any(b.kind == "heading" for b in res.document.blocks)
        assert res.text  # flattened normalized prose

    def test_epub_selects_extract_epub(self) -> None:
        res = dispatch_text(epub_bytes(), format="epub")
        assert res.parser == "epub" and res.route == "text"
        assert isinstance(res.document, EpubDocument)
        assert len(res.document.spine) == 1
        assert res.text  # flattened spine paragraphs

    def test_multi_chapter_epub_has_two_chapters(self) -> None:
        res = dispatch_text(multi_chapter_epub_bytes(), format="epub")
        assert res.parser == "epub" and res.route == "text"
        assert len(res.document.spine) == 2
        # each spine chapter carries paragraph segments
        assert all(sp.paragraphs for sp in res.document.spine)

    def test_pdf_text_uses_existing_pdf_path(self) -> None:
        res = dispatch_text(pdf_text_bytes(), format="pdf")
        assert res.parser == "pdf" and res.route == "text"
        assert "Hello from the text layer" in res.text

    def test_image_only_pdf_routes_to_raster_not_text(self) -> None:
        res = dispatch_text(pdf_image_only_bytes(), format="pdf")
        assert res.route == "image_raster"
        assert res.non_text is True
        assert res.text == ""  # binary page bytes never normalized as text

    def test_malformed_epub_is_degraded_and_safe(self) -> None:
        res = dispatch_text(malformed_epub_bytes(), format="epub")
        assert res.route == "degraded"
        assert res.degraded is True and res.non_text is True
        assert res.text == ""
        assert res.document is None
        assert any("epub parse failed" in w for w in res.warnings)

    def test_unknown_format_keeps_plain_text_baseline_with_warning(self) -> None:
        res = dispatch_text(txt_bytes(), format="bogus")
        assert res.parser == "txt" and res.route == "text"
        assert any("unsupported/unknown text format" in w for w in res.warnings)

    def test_deterministic_rerun_same_result(self) -> None:
        raw = markdown_bytes()
        a = dispatch_text(raw, format="markdown", source_sha512="d" * 128)
        b = dispatch_text(raw, format="markdown", source_sha512="d" * 128)
        assert (
            a.format,
            a.parser,
            a.route,
            a.text,
            a.parser_version,
            a.decoder_version,
            a.config_digest,
            a.source_sha512,
        ) == (
            b.format,
            b.parser,
            b.route,
            b.text,
            b.parser_version,
            b.decoder_version,
            b.config_digest,
            b.source_sha512,
        )
        assert a.document.to_dict() == b.document.to_dict()

    def test_text_dispatch_contract_adapter(self) -> None:
        # CONTRACTS.md:74 TextDispatch.dispatch(source, raw_or_native) adapter.
        res = TextDispatch.dispatch({"format": "txt", "sha512": "s" * 128}, txt_bytes())
        assert isinstance(res, TextDispatchResult)
        assert res.parser == "txt" and res.route == "text"
        assert res.source_sha512 == "s" * 128
