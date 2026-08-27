"""Domain model unit tests (P2-S1)."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from umd.domain.models import (
    ConfidenceState,
    Edition,
    EditionKind,
    EntityType,
    Evidence,
    EvidenceKind,
    MembershipRole,
    NarrativeTime,
    Predicate,
    SemanticAssertion,
    SourceDescriptor,
    SourceMembership,
    SpatialReference,
    Translation,
    register_predicate,
)


def test_confidence_states_exact_enum() -> None:
    assert [c.value for c in ConfidenceState] == [
        "UNKNOWN",
        "AMBIGUOUS",
        "CONFLICTING",
        "PROBABLE",
        "CONFIRMED",
        "USER_CONFIRMED",
    ]


def test_evidence_kinds_cover_extraction_surface() -> None:
    kinds = {e.value for e in EvidenceKind}
    expected = {
        "text_span",
        "subtitle_event",
        "audio_interval",
        "video_interval",
        "frame",
        "panel",
        "page_region",
        "ocr_region",
        "speaker_observation",
        "face_observation",
        "object_observation",
        "music",
        "sound_event",
        "scene_boundary",
        "layout",
        "visual_relationship",
        "timing",
        "metadata",
    }
    assert kinds == expected


def test_source_descriptor_filename_is_metadata_only() -> None:
    d = SourceDescriptor(
        media_kind="text",
        format="epub",
        language="en",
        original_name="../../etc/passwd",
    )
    # original_name must never be used as a storage key; it is carried as metadata.
    assert d.original_name == "../../etc/passwd"
    assert "original_name" not in d.model_dump(exclude={"original_name"})


def test_evidence_confidence_bounds() -> None:
    Evidence(source_id=uuid.uuid4(), evidence_kind=EvidenceKind.FRAME, confidence=0.5)
    with pytest.raises(ValidationError):
        Evidence(source_id=uuid.uuid4(), evidence_kind=EvidenceKind.FRAME, confidence=1.5)


def test_edition_kind_variants() -> None:
    wid = uuid.uuid4()
    assert Edition(work_id=wid, kind=EditionKind.RELEASE).kind is EditionKind.RELEASE
    assert Translation(work_id=wid, language="es").kind is EditionKind.TRANSLATION


def test_membership_roles() -> None:
    m = SourceMembership(source_id=uuid.uuid4(), work_id=uuid.uuid4(), role=MembershipRole.ALIAS)
    assert m.role is MembershipRole.ALIAS


def test_narrative_time_defaults() -> None:
    nt = NarrativeTime()
    assert nt.is_flashback is False and nt.ordering_unknown is False


def test_spatial_reference_round_trip() -> None:
    s = SpatialReference(location="Room 101", lighting="dim", participants=["guy"])
    assert s.lighting == "dim" and s.participants == ["guy"]


def test_predicate_open_vocabulary_and_validation() -> None:
    assert Predicate(code="SPEAKS").code == "SPEAKS"
    # Unknown predicate -> validation error (downstream never invents ontology).
    with pytest.raises(ValidationError, match="not registered"):
        Predicate(code="BOGUS_RELATION")
    register_predicate("HAS_COLOR", "A visual appearance has a color.")
    assert Predicate(code="HAS_COLOR").code == "HAS_COLOR"


def test_predicate_normalization_uppercases() -> None:
    assert Predicate(code="speaks").code == "SPEAKS"


def test_semantic_assertion_validates_predicate() -> None:
    assert SemanticAssertion(predicate_code="SPEAKS").state is ConfidenceState.UNKNOWN
    with pytest.raises(ValidationError):
        SemanticAssertion(predicate_code="invented_relation")


def test_typed_entity_kinds_include_media_and_cross_source() -> None:
    vals = {e.value for e in EntityType}
    for k in ("character", "person", "speaker_identity", "music", "correspondence", "environment"):
        assert k in vals
