"""SegmentRegistry unit/property tests (P2-S2)."""

from __future__ import annotations

import pytest

from umd.domain.locators import ByteOffsetSelector, PipelineVersion
from umd.segmentation.registry import (
    InMemorySegmentStore,
    SegmentInput,
    SegmentRegistry,
)

_SHA = "a" * 128


def _reg(store: InMemorySegmentStore) -> SegmentRegistry:
    return SegmentRegistry(store)


def test_register_is_deterministic_and_idempotent() -> None:
    store = InMemorySegmentStore()
    reg = _reg(store)
    inp = SegmentInput(
        source_id="src1",
        source_sha512=_SHA,
        modality="text",
        structural_path="chapter/4/paragraph/18",
        segment_type="paragraph",
        version=PipelineVersion("text", "pandoc22", "epub3", version=2),
    )
    first = reg.register([inp])
    second = reg.register([inp])
    assert first.total == second.total == 1
    assert len(first.created) == 1 and len(first.existing) == 0
    assert len(second.created) == 0 and len(second.existing) == 1
    assert first.created[0].deterministic_key == second.existing[0].deterministic_key


def test_reupload_same_path_different_bytes_is_not_deduped() -> None:
    store = InMemorySegmentStore()
    reg = _reg(store)
    a = SegmentInput(
        source_id="sA",
        source_sha512="a" * 128,
        modality="text",
        structural_path="page/1",
        segment_type="page",
        version=PipelineVersion("text", "x", "y", version=1),
    )
    b = SegmentInput(  # same logical path, byte-different source
        source_id="sB",
        source_sha512="b" * 128,
        modality="text",
        structural_path="page/1",
        segment_type="page",
        version=PipelineVersion("text", "x", "y", version=1),
    )
    batch = reg.register([a, b])
    # both created (no dedup); distinct deterministic keys because content differs
    assert len(batch.created) == 2
    assert batch.created[0].deterministic_key != batch.created[1].deterministic_key


def test_register_rejects_byte_offset_only() -> None:
    store = InMemorySegmentStore()
    reg = _reg(store)
    inp = SegmentInput(
        source_id="src1",
        source_sha512=_SHA,
        modality="text",
        structural_path="",  # no anchor
        segment_type="byte_range",
        version=PipelineVersion("t", "d", "r", version=1),
        frag=ByteOffsetSelector(start=0, end=100),
    )
    with pytest.raises(Exception, match="byte-offset-only"):
        reg.register([inp])


def test_locator_is_versioned_and_segment_anchored() -> None:
    store = InMemorySegmentStore()
    reg = _reg(store)
    inp = SegmentInput(
        source_id="src1",
        source_sha512=_SHA,
        modality="text",
        structural_path="paragraph/3",
        segment_type="paragraph",
        version=PipelineVersion("text", "pandoc22", "epub3", version=2),
    )
    seg = reg.register([inp]).created[0]
    assert "@vtext.pandoc22.epub3" in seg.locator
    assert seg.locator.startswith("source://src1/text/")
    assert seg.deterministic_key.startswith(f"source:{_SHA}#text#paragraph/3")
