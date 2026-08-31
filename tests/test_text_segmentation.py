"""Deterministic text segmentation + dialogue/narration tests (Phase B, P2-S2)."""

from __future__ import annotations

from fixtures import FIXTURE_TXT, markdown_bytes, multi_chapter_epub_bytes, pdf_image_only_bytes
from umd.analysis.text_structural import analyze_text, classify_dialogue
from umd.extractors.dispatch import dispatch_text
from umd.extractors.txt import normalize_txt
from umd.segmentation.registry import InMemorySegmentStore, SegmentRegistry
from umd.segmentation.segmenters import (
    TEXT_PIPELINE_VERSION,
    segment_markdown,
    segment_txt,
)

SHA = "a" * 128
SID = "00000000-0000-4000-8000-000000000001"


def _reg() -> tuple[SegmentRegistry, InMemorySegmentStore]:
    store = InMemorySegmentStore()
    return SegmentRegistry(store), store


def test_deterministic_segmentation_same_input() -> None:
    reg1, _ = _reg()
    reg2, _ = _reg()
    text = normalize_txt(FIXTURE_TXT.encode("utf-8")).text
    r1 = segment_txt(
        reg1,
        source_id=SID,
        source_sha512=SHA,
        work_id=None,
        text=text,
        version=TEXT_PIPELINE_VERSION,
    )
    r2 = segment_txt(
        reg2,
        source_id=SID,
        source_sha512=SHA,
        work_id=None,
        text=text,
        version=TEXT_PIPELINE_VERSION,
    )
    keys1 = sorted(s.deterministic_key for s in r1.batch.created)
    keys2 = sorted(s.deterministic_key for s in r2.batch.created)
    assert keys1 == keys2 and keys1  # identical deterministic keys across runs


def test_document_chapter_paragraph_sentence_token_spans() -> None:
    reg, store = _reg()
    text = normalize_txt(FIXTURE_TXT.encode("utf-8")).text
    r = segment_txt(
        reg,
        source_id=SID,
        source_sha512=SHA,
        work_id=None,
        text=text,
        version=TEXT_PIPELINE_VERSION,
    )
    types = {s.segment_type for s in r.batch.created}
    assert {"document", "chapter", "section", "paragraph", "sentence", "token"} <= types
    # every structural path is emitted as a Location-safe selector and registered
    assert all(s.structural_path for s in r.batch.created)
    # locators are canonical source:// with structural frags
    assert all(s.locator.startswith("source://") for s in r.batch.created)


def test_byte_different_input_distinct_keys() -> None:
    reg, _ = _reg()
    r1 = segment_txt(
        reg,
        source_id=SID,
        source_sha512=SHA,
        work_id=None,
        text="One two three.",
        version=TEXT_PIPELINE_VERSION,
    )
    r2 = segment_txt(
        reg,
        source_id=SID,
        source_sha512=SHA,
        work_id=None,
        text="Different text.",
        version=TEXT_PIPELINE_VERSION,
    )
    k1 = {s.deterministic_key for s in r1.batch.created}
    k2 = {s.deterministic_key for s in r2.batch.created}
    assert k1.isdisjoint(k2)


def test_markdown_segmentation_uses_headings() -> None:
    from umd.extractors.markdown import parse_markdown

    reg, _ = _reg()
    text = normalize_txt(markdown_bytes()).text
    doc = parse_markdown(text)
    r = segment_markdown(
        reg,
        source_id=SID,
        source_sha512=SHA,
        work_id=None,
        doc=doc,
        version=TEXT_PIPELINE_VERSION,
    )
    types = {s.segment_type for s in r.batch.created}
    assert "chapter" in types and "section" in types


def test_markdown_fenced_code_never_leaks_as_prose_segments() -> None:
    # A fenced-code region is opaque at the parser level; its interior must NOT
    # surface as a paragraph/sentence/token prose segment (regression for the
    # opening-fence bug where ``lines[i]`` never advanced past the fence line).
    from umd.extractors.markdown import parse_markdown

    reg, _ = _reg()
    text = "before\n\n```python\nx=1\ny=2\n```\n\nafter\n"
    doc = parse_markdown(text)
    r = segment_markdown(
        reg,
        source_id=SID,
        source_sha512=SHA,
        work_id=None,
        doc=doc,
        version=TEXT_PIPELINE_VERSION,
    )
    # Only the surrounding prose paragraphs are segmented; the fence interior is
    # not among them (and no sentence/token segments exist for leaked code).
    assert r.paragraphs == ["before", "after"]
    assert all("x=1" not in p and "y=2" not in p and "```" not in p for p in r.paragraphs)
    assert not any(
        "sentence" in s.structural_path or "token" in s.structural_path for s in r.batch.created
    )


class TestDispatchSegmentation:
    """Plan L P3-S1: ``TextDispatchResult.segment`` runs the format-appropriate
    segmenter and records canonical structural locators / deterministic segment
    IDs (TXT→``segment_txt``, Markdown→``segment_markdown``, EPUB→``segment_epub``,
    text PDF→the extracted text via ``segment_txt``).
    """

    def test_txt_dispatch_segments_full_hierarchy(self) -> None:
        reg, _store = _reg()
        raw = normalize_txt(FIXTURE_TXT.encode("utf-8")).text.encode("utf-8")
        res = dispatch_text(raw, format="txt")
        seg = res.segment(reg, source_id=SID, source_sha512=SHA)
        types = {s.segment_type for s in seg.batch.created}
        assert {"document", "chapter", "section", "paragraph", "sentence", "token"} <= types
        # structural locators + segment ids recorded on the dispatch result
        assert res.locators and res.segment_ids
        assert all(loc.startswith("source://") for loc in res.locators.values())
        assert "document/1" in res.locators
        assert "chapter/1" in res.locators
        assert "chapter/1/section/1" in res.locators
        assert any(p.startswith("chapter/1/section/1/paragraph/") for p in res.locators)

    def test_markdown_dispatch_segments_use_headings(self) -> None:
        reg, _store = _reg()
        res = dispatch_text(markdown_bytes(), format="markdown")
        seg = res.segment(reg, source_id=SID, source_sha512=SHA)
        types = {s.segment_type for s in seg.batch.created}
        assert {"chapter", "section", "paragraph"} <= types
        # FIXTURE_MARKDOWN has one H1 (# The Garden) + two H2 sections.
        assert "chapter/1" in res.locators
        assert "chapter/1/section/1" in res.locators
        assert "chapter/1/section/2" in res.locators

    def test_epub_dispatch_segments_per_chapter_paragraph(self) -> None:
        reg, _store = _reg()
        res = dispatch_text(multi_chapter_epub_bytes(), format="epub")
        seg = res.segment(reg, source_id=SID, source_sha512=SHA)
        types = {s.segment_type for s in seg.batch.created}
        assert {"chapter", "paragraph"} <= types
        # two spine chapters, each with paragraph segments
        assert "chapter/1" in res.locators and "chapter/2" in res.locators
        for path in (
            "chapter/1/paragraph/1",
            "chapter/1/paragraph/2",
            "chapter/2/paragraph/1",
            "chapter/2/paragraph/2",
        ):
            assert path in res.locators, f"missing paragraph locator {path}"

    def test_text_pdf_dispatch_segments_extracted_text(self) -> None:
        from fixtures import pdf_text_bytes

        reg, _store = _reg()
        res = dispatch_text(pdf_text_bytes(), format="pdf")
        seg = res.segment(reg, source_id=SID, source_sha512=SHA)
        types = {s.segment_type for s in seg.batch.created}
        # the extracted PDF text is segmented as plain text (never raw bytes)
        assert "paragraph" in types
        assert "document/1" in res.locators

    def test_dispatch_segment_ids_deterministic_across_runs(self) -> None:
        raw = multi_chapter_epub_bytes()
        reg1, _store1 = _reg()
        reg2, _store2 = _reg()
        r1 = dispatch_text(raw, format="epub").segment(reg1, source_id=SID, source_sha512=SHA)
        r2 = dispatch_text(raw, format="epub").segment(reg2, source_id=SID, source_sha512=SHA)
        keys1 = sorted(s.deterministic_key for s in r1.batch.created)
        keys2 = sorted(s.deterministic_key for s in r2.batch.created)
        assert keys1 == keys2 and keys1  # identical deterministic keys across runs

    def test_non_text_dispatch_segment_returns_none(self) -> None:
        # An image-only PDF never segments binary bytes as plain text.
        reg, _store = _reg()
        res = dispatch_text(pdf_image_only_bytes(), format="pdf")
        assert res.non_text
        assert res.segment(reg, source_id=SID, source_sha512=SHA) is None


class TestDialogueNarration:
    def test_quoted_dialogue_classified(self) -> None:
        assert classify_dialogue('"Hello," said Alice.') is True
        assert classify_dialogue("The mat was woven from reeds.") is False

    def test_speaker_attribute_candidate(self) -> None:
        text = 'Alice said, "Where is the garden?" The White Rabbit hurried past.'
        res = analyze_text(source_id=SID, paragraphs=[text], language=None)
        dialogue = [s for s in res.dialogue_spans if s.is_dialogue]
        assert dialogue
        # evidence rows link dialogue and candidate speaker attributions
        assert res.evidence
        kinds = {e.evidence_kind.value for e in res.evidence}
        assert "text_span" in kinds
