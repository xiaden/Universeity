"""Sequential-art composition tests (Phase B, P2-S3).

Verifies page/panel/caption structure where the source (Markdown/EPUB images)
supports it, keeps the sequential-art hierarchy source-specific, and composes it
with text extraction rather than flattening modalities.
"""

from __future__ import annotations

from fixtures import FIXTURE_MARKDOWN
from umd.extractors.markdown import parse_markdown
from umd.extractors.txt import normalize_txt
from umd.segmentation.registry import InMemorySegmentStore, SegmentRegistry
from umd.segmentation.segmenters import TEXT_PIPELINE_VERSION
from umd.segmentation.sequential_art import build_sequential_art

SHA = "a" * 128
SID = "00000000-0000-4000-8000-000000000002"


def _doc():
    return parse_markdown(normalize_txt(FIXTURE_MARKDOWN.encode("utf-8")).text)


def test_markdown_image_becomes_page_and_caption() -> None:
    store = InMemorySegmentStore()
    reg = SegmentRegistry(store)
    res = build_sequential_art(
        reg,
        source_id=SID,
        source_sha512=SHA,
        work_id=None,
        doc=_doc(),
        version=TEXT_PIPELINE_VERSION,
        tool_versions={"text": "umd-1"},
        config_digest="cfg",
    )
    page_types = {s.segment_type for s in res.batch.created}
    assert "page" in page_types
    # caption derived from the image alt text
    captions = [s for s in res.batch.created if s.segment_type == "caption"]
    assert captions and captions[0].structural_path.endswith("caption")


def test_text_and_image_kept_separate() -> None:
    store = InMemorySegmentStore()
    reg = SegmentRegistry(store)
    res = build_sequential_art(
        reg,
        source_id=SID,
        source_sha512=SHA,
        work_id=None,
        doc=_doc(),
        version=TEXT_PIPELINE_VERSION,
        tool_versions={},
        config_digest="cfg",
    )
    modalities = {s.modality for s in res.batch.created}
    assert modalities == {"image", "text"}
    # composition evidence records that text and image modalities are keepse separate
    compose = [e for e in res.evidence if e.evidence_kind.value == "layout"]
    assert compose and compose[0].quality.get("modalities_kept_separate") is True
