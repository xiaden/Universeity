"""Deterministic text segmentation + dialogue/narration tests (Phase B, P2-S2)."""

from __future__ import annotations

from fixtures import FIXTURE_TXT, markdown_bytes
from umd.analysis.text_structural import analyze_text, classify_dialogue
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
