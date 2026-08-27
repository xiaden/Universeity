"""Locator grammar + deterministic segment id tests (P2-S2)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from umd.domain.ids import (
    canonical_identity,
    deterministic_key,
    deterministic_segment_id,
    is_url_safe,
)
from umd.domain.locators import (
    ByteOffsetSelector,
    CfiSelector,
    IIIFSelector,
    Locator,
    MediaFragmentSelector,
    PipelineVersion,
    StructuralSelector,
    build_locator,
    parse_locator,
)


def test_canonical_round_trip() -> None:
    raw = "source://novel-123/text/AbCdEfG_123@vtext.pandoc22.epub3?frag=paragraph/4"
    loc = parse_locator(raw)
    assert loc.canonical() == raw


def test_media_fragments_selector_round_trip() -> None:
    loc = parse_locator(
        "source://anime-s01e05/video/segX@vffmpeg7.yolo.decoder2?frag=t=842310,845120&track=1"
    )
    assert isinstance(loc.frag, MediaFragmentSelector)
    assert loc.frag.t == "842310,845120"
    assert loc.frag.track == "1"
    assert "frag=t=842310,845120&track=1" in loc.canonical()


def test_iiif_selector() -> None:
    loc = parse_locator("source://manga-22/image/segY@vseg.ocr.detect?frag=10,20,30,40")
    assert isinstance(loc.frag, IIIFSelector)
    assert loc.frag.region == "10,20,30,40"
    pct = parse_locator("source://manga-22/image/segZ?frag=pct:1.5,2,30,40")
    assert isinstance(pct.frag, IIIFSelector) and pct.frag.region.startswith("pct:")


def test_epub_cfi_selector() -> None:
    cfi = "epubcfi(/6/4[chap01ref]!/4[body01]/10[para05]/2:0)"
    loc = parse_locator(f"source://book/xml/segW?frag={cfi}")
    assert isinstance(loc.frag, CfiSelector)
    assert loc.frag.cfi == cfi


def test_structural_selector() -> None:
    loc = parse_locator("source://novel-123/text/segV@vseg.p2.e3?frag=paragraph/18/sentence/3")
    assert isinstance(loc.frag, StructuralSelector)
    assert loc.frag.path == "paragraph/18/sentence/3"


def test_invalid_iiif_rejected() -> None:
    with pytest.raises(ValidationError):
        IIIFSelector(region="bananas")


def test_empty_media_fragment_rejected() -> None:
    with pytest.raises(ValidationError):
        MediaFragmentSelector(t=None, track=None, spatial=None)


# ---------------------------------------------------------------------------
# Byte-offset-only rejection (carry-forward invariant)
# ---------------------------------------------------------------------------


def test_byte_offset_selector_alone_is_rejected() -> None:
    with pytest.raises(ValidationError, match="byte-offset-only locator rejected"):
        Locator(
            source_id="src1",
            modality="text",
            segment="segmentA",
            frag=ByteOffsetSelector(start=0, end=512),
        )


def test_byte_offset_only_locator_rejected_even_when_anchored_token() -> None:
    # A byte range is never a sufficient locator: byte-offset-only is forbidden.
    with pytest.raises(ValidationError, match="byte-offset-only locator rejected"):
        Locator(
            source_id="src1",
            modality="text",
            segment="abcd1234",
            frag=ByteOffsetSelector(start=0, end=128),
        )


def test_byte_offset_augmenting_structural_is_not_a_distinct_selector() -> None:
    # The parser carries byte ranges as metadata, never as the sole locator
    # selector, so a ByteOffsetSelector frag is always rejected.
    with pytest.raises(ValidationError, match="byte-offset-only locator rejected"):
        Locator(
            source_id="src1",
            modality="text",
            segment="chapter_4_paragraph_18",
            frag=ByteOffsetSelector(start=0, end=128),
        )


def test_parse_rejects_bad_scheme_and_short() -> None:
    with pytest.raises(ValueError):
        parse_locator("https://example.com/x")
    from umd.domain.locators import LocatorError

    with pytest.raises(LocatorError):
        parse_locator("source://id/modality")


# ---------------------------------------------------------------------------
# Deterministic segment identity
# ---------------------------------------------------------------------------


def test_deterministic_segment_id_is_stable_and_urlsafe() -> None:
    identity = canonical_identity("a" * 128)
    a = deterministic_segment_id(identity, "text", "chapter/4/paragraph/18")
    b = deterministic_segment_id(identity, "text", "chapter/4/paragraph/18")
    assert a == b  # stable across calls
    assert is_url_safe(a)


def test_deterministic_id_changes_with_path_and_modality() -> None:
    identity = canonical_identity("a" * 128)
    p1 = deterministic_segment_id(identity, "text", "chapter/1/paragraph/2")
    p2 = deterministic_segment_id(identity, "text", "chapter/2/paragraph/2")
    m2 = deterministic_segment_id(identity, "audio", "chapter/1/paragraph/2")
    assert len({p1, p2, m2}) == 3


def test_deterministic_id_differs_for_byte_different_reupload() -> None:
    # Two byte-different reuploads of the same logical work => distinct content
    # identity => distinct segment ids + keys (no dedup of the alias sources).
    id_a = deterministic_segment_id(canonical_identity("a" * 128), "text", "page/1")
    id_b = deterministic_segment_id(canonical_identity("b" * 128), "text", "page/1")
    assert id_a != id_b
    assert deterministic_key(canonical_identity("a" * 128), "text", "page/1") != deterministic_key(
        canonical_identity("b" * 128), "text", "page/1"
    )


def test_canonical_identity_never_accepts_filename() -> None:
    with pytest.raises(ValueError):
        canonical_identity("not-a-sha512-hex")
    # even a USER-FILENAME-like payload can't become an identity without a real digest
    with pytest.raises(ValueError):
        canonical_identity("..%2f..%2fsecret.txt")


def test_build_locator_embeds_version() -> None:
    identity = canonical_identity("a" * 128)
    loc = build_locator(
        source_id="src1",
        modality="text",
        structural_path="chapter/1",
        canonical_identity=identity,
        version=PipelineVersion("text", "pandoc22", "epub3", version=2),
    )
    assert loc.version is not None and loc.version.tag == "vtext.pandoc22.epub3"
    assert "@vtext.pandoc22.epub3" in loc.canonical()
