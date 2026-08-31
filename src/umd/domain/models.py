"""Typed domain models and validators (Phase 2 / P2-S1).

These types implement the DD's *typed relational core*: typed core concepts
(work, continuity, source, edition, translation, adaptation, release, segment,
evidence, entity, entity-mention, temporal/spatial, confidence) plus an
*extensible predicate vocabulary* validated via :data:`PREDICATE_VOCABULARY`
rather than a closed ontology.

Design rules carried forward from Phase 1:
  * a user filename is never a key (``original_name`` is metadata only);
  * confidence states match the semantic_assertion column exactly
    (``UNKNOWN|AMBIGUOUS|CONFLICTING|PROBABLE|CONFIRMED|USER_CONFIRMED``);
  * evidence kinds are the enumerated modality-native kinds;
  * new predicates are data (a vocabulary entry), not a schema migration.

Models here are pure Pydantic v2 value types — no I/O, no persistence. They map
1:1 onto the canonical schema in ``umd.storage.postgres.tables``.
"""

from __future__ import annotations

import re
import uuid
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enums (closed where the DD closes them)
# ---------------------------------------------------------------------------


class ConfidenceState(StrEnum):
    """Semantic confidence states (DD §Typed relational core / Task §14)."""

    UNKNOWN = "UNKNOWN"
    AMBIGUOUS = "AMBIGUOUS"
    CONFLICTING = "CONFLICTING"
    PROBABLE = "PROBABLE"
    CONFIRMED = "CONFIRMED"
    USER_CONFIRMED = "USER_CONFIRMED"


class EvidenceKind(StrEnum):
    """Modality-native evidence kinds (P2-S1 requirement list)."""

    TEXT_SPAN = "text_span"
    SUBTITLE_EVENT = "subtitle_event"
    AUDIO_INTERVAL = "audio_interval"
    VIDEO_INTERVAL = "video_interval"
    FRAME = "frame"
    PANEL = "panel"
    PAGE_REGION = "page_region"
    OCR_REGION = "ocr_region"
    SPEAKER_OBSERVATION = "speaker_observation"
    FACE_OBSERVATION = "face_observation"
    OBJECT_OBSERVATION = "object_observation"
    MUSIC = "music"
    SOUND_EVENT = "sound_event"
    SCENE_BOUNDARY = "scene_boundary"
    LAYOUT = "layout"
    VISUAL_RELATIONSHIP = "visual_relationship"
    TIMING = "timing"
    METADATA = "metadata"


class EditionKind(StrEnum):
    """Edition variant kinds (edition.kind column: original|translation|adaptation|release)."""

    ORIGINAL = "original"
    TRANSLATION = "translation"
    ADAPTATION = "adaptation"
    RELEASE = "release"


class MembershipRole(StrEnum):
    """Source<->work membership roles (source_membership.role column)."""

    PRIMARY = "primary"
    DERIVATION = "derivation"
    ALIAS = "alias"
    RELATED = "related"


class EntityType(StrEnum):
    """Typed entity/mention kinds (DD typed vocabulary; not a closed ontology)."""

    WORK = "work"
    CONTINUITY = "continuity"
    SOURCE = "source"
    EDITION = "edition"
    ADAPTATION = "adaptation"
    TRANSLATION = "translation"
    CHARACTER = "character"
    PERSON = "person"
    ORGANIZATION = "organization"
    LOCATION = "location"
    OBJECT = "object"
    CONCEPT = "concept"
    SCENE = "scene"
    EVENT = "event"
    ACTION = "action"
    UTTERANCE = "utterance"
    RELATIONSHIP = "relationship"
    STATE = "state"
    EMOTION = "emotion"
    GOAL = "goal"
    BELIEF = "belief"
    TIMELINE = "timeline"
    PRESENCE = "presence"
    SPEAKER_IDENTITY = "speaker_identity"
    ALIAS = "alias"
    VISUAL_APPEARANCE = "visual_appearance"
    ENVIRONMENT = "environment"
    MUSIC = "music"
    SOUND = "sound"
    CORRESPONDENCE = "correspondence"
    CONTRADICTION = "contradiction"


# ---------------------------------------------------------------------------
# Extensible predicate vocabulary (validated entries, not a closed ontology)
# ---------------------------------------------------------------------------

#: High-value relationships named by the DD as validated vocabulary entries.
#: The dictionary is open — new predicates are added as data below without a
#: schema migration (they must be registered before use in an assertion).
PREDICATE_VOCABULARY: dict[str, str] = {
    "SPEAKS": "A subject entity speaks an utterance/span.",
    "PRESENT_IN": "An entity is present in a scene/location.",
    "CORRESPONDS_TO": "Cross-source semantic correspondence between refs.",
    "TRANSLATION_OF": "This realization is a translation of another.",
    "ADAPTATION_OF": "This realization is an adaptation of another.",
    "DERIVED_FROM": "This object/ref is derived from a source.",
    "CONTRADICTS": "This assertion contradicts another.",
    "ALIAS_OF": "This entity is an alias of a canonical entity.",
    "EXPANDS": "A source expands/elaborates a canonical structure.",
    "OMITS": "A source omits content present in the canonical structure.",
    "REORDERS": "A source reorders narrative vs. source chronology.",
    "ALTERNATE_REALIZATION": "Alternate realization of the same semantic intent.",
}

#: Convenience additional vocabulary grounded in the DD typed kinds.
EXTENDED_PREDICATES: dict[str, str] = {
    "MENTIONS": "A source/mention references an entity.",
    "OCCURS_AT": "An event/action occurs at a temporal or spatial reference.",
    "KNOWN_AS": "An entity is known by an alias/transliteration.",
    "SPEAKER_OF": "An entity is the candidate speaker of an utterance.",
    "APPEARS_AS": "A visual appearance observation.",
    "PART_OF": "A segment is part of a parent segment.",
    "SET_IN": "An event is set at a location/environment.",
}


def register_predicate(code: str, description: str) -> None:
    """Register a new predicate into the open vocabulary (data, not migration)."""
    code = code.strip().upper()
    if not code:
        raise ValueError("predicate code must be non-empty")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code):
        raise ValueError(f"invalid predicate code {code!r}")
    PREDICATE_VOCABULARY[code] = description


def is_known_predicate(code: str) -> bool:
    """True if ``code`` is a registered vocabulary entry."""
    return code in PREDICATE_VOCABULARY


# Reconciliation-era additions (Plan O P1-S1). These are data entries registered
# eagerly so the generic vocabulary covers the reconciled observation surface
# (identity/alias, mentions, utterance membership, traits, relationships,
# emotion/state/context and scene structure) without a schema migration. They are
# plain vocabulary rows — not consumer-specific schemas — and feed the predicate
# table via the idempotent materialization seed on first use.
register_predicate("MENTIONED_IN", "An entity is mentioned in a segment.")
register_predicate("UTTERED_IN", "An utterance is spoken within a scene/segment.")
register_predicate("HAS_TRAIT", "An entity has a descriptive trait.")
register_predicate("CO_OCCURS", "Two entities co-occur in a shared segment/context.")
register_predicate("HAS_EMOTION", "An entity exhibits an emotion.")
register_predicate("IN_STATE", "An entity is in a narrative state.")
register_predicate("HAS_CONTEXT", "A scene/segment has a context/environment observation.")
register_predicate("STARTS_AT", "A scene starts at a source segment.")
# Plan S Phase 4 (P4-S1): the Lantern Keeper sibling predicate is a controlled,
# validated-vocabulary relationship. It is admitted ONLY through register_predicate
# (syntax gate: ^[A-Z][A-Z0-9_]{0,63}$ + registration into PREDICATE_VOCABULARY),
# exactly like every other relationship predicate. Malformed/arbitrary model strings
# are still rejected by is_known_predicate in the reconciler (never fabricated).
register_predicate("SIBLING_OF", "An entity is a sibling of another entity.")


class Predicate(BaseModel):
    """A predicate-dictionary entry (predicate table row)."""

    code: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=512)

    @field_validator("code")
    @classmethod
    def _normalize_code(cls, v: str) -> str:
        code = v.strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code):
            raise ValueError(f"invalid predicate code {v!r}")
        return code

    @model_validator(mode="after")
    def _admit_only_known(self) -> Predicate:
        # New predicates must first be registered so downstream consumers never
        # silently invent ontology; unknown codes are a validation error.
        if self.code not in PREDICATE_VOCABULARY:
            raise ValueError(
                f"predicate {self.code!r} is not registered; call register_predicate() first"
            )
        return self


# ---------------------------------------------------------------------------
# Temporal / spatial fields
# ---------------------------------------------------------------------------


class SourceTime(BaseModel):
    """Source-local time reference (Task §30). Timestamps in integer units (e.g. ms)."""

    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    timecode: str | None = None  # e.g. "01:23:45.678"

    @model_validator(mode="after")
    def _range_sane(self) -> SourceTime:
        if self.start_ms is not None and self.end_ms is not None and self.end_ms < self.start_ms:
            raise ValueError("end_ms must be >= start_ms")
        return self


class NarrativeTime(BaseModel):
    """Narrative-sequence/chronology representation (Task §30).

    ``sequence`` is the in-story order index; ``is_flashback`` and
    ``ordering_unknown`` make explicit that narrative order is not assumed to
    equal story chronology.
    """

    sequence: int | None = None
    is_flashback: bool = False
    ordering_unknown: bool = False
    simultaneous_with: list[str] = Field(default_factory=list)


class SpatialReference(BaseModel):
    """Spatial/environmental reference (Task §31)."""

    location: str | None = None
    sub_location: str | None = None
    environment: str | None = None
    participants: list[str] = Field(default_factory=list)
    objects_present: list[str] = Field(default_factory=list)
    weather: str | None = None
    lighting: str | None = None
    relative_position: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Source descriptors, work membership, editions, translations, adaptations
# ---------------------------------------------------------------------------


class SourceDescriptor(BaseModel):
    """Descriptor for a source object (source.descriptor JSONB + typed columns).

    ``original_name`` is metadata only — never a storage key or path.
    """

    media_kind: str = Field(default="unknown", max_length=64)
    format: str | None = Field(default=None, max_length=64)
    language: str | None = Field(default=None, max_length=16)
    original_name: str | None = Field(default=None, max_length=1024)
    kind: Literal["source", "derived", "artifact"] = "source"
    extra: dict[str, Any] = Field(default_factory=dict)


class Work(BaseModel):
    """A work (work table row)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    title: str = Field(min_length=1, max_length=512)
    work_type: str = Field(max_length=64)
    metadata_: dict[str, Any] = Field(default_factory=dict)


class Continuity(BaseModel):
    """A continuity bound to a work (continuity table row)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    work_id: uuid.UUID
    name: str = Field(min_length=1, max_length=256)


class Edition(BaseModel):
    """An edition of a work (edition table row; kind distinguishes variants)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    work_id: uuid.UUID
    continuity_id: uuid.UUID | None = None
    language: str | None = Field(default=None, max_length=16)
    kind: EditionKind = EditionKind.ORIGINAL
    label: str | None = Field(default=None, max_length=256)


class Translation(Edition):
    """A translation edition (kind=translation).

    ``source_edition_id`` is a cross-phase value type: it has no backing
    ``edition`` column yet and is not persisted in the current relational core
    (it is exercised by later phases B–F).
    """

    kind: EditionKind = EditionKind.TRANSLATION
    source_edition_id: uuid.UUID | None = None


class Adaptation(Edition):
    """An adaptation edition (kind=adaptation).

    ``source_work_id`` is a cross-phase value type: it has no backing
    ``edition`` column yet and is not persisted in the current relational core
    (it is exercised by later phases B–F).
    """

    kind: EditionKind = EditionKind.ADAPTATION
    source_work_id: uuid.UUID | None = None


class Release(Edition):
    """A release edition (kind=release)."""

    kind: EditionKind = EditionKind.RELEASE


class SourceMembership(BaseModel):
    """Source<->work membership (source_membership table row)."""

    source_id: uuid.UUID
    work_id: uuid.UUID
    role: MembershipRole = MembershipRole.PRIMARY


# ---------------------------------------------------------------------------
# Segments, evidence, entities / mentions
# ---------------------------------------------------------------------------


class SegmentSpec(BaseModel):
    """Input to segment registration (deterministic id computed in Phase 2)."""

    source_id: uuid.UUID
    segment_type: str = Field(max_length=64)
    parent_key: str | None = Field(default=None, max_length=512)
    ordinal: int | None = None
    structural_path: str = Field(default="", max_length=512)
    metadata_: dict[str, Any] = Field(default_factory=dict)


class Evidence(BaseModel):
    """An evidence record (evidence table row)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    source_id: uuid.UUID
    segment_id: uuid.UUID | None = None
    evidence_kind: EvidenceKind = EvidenceKind.TEXT_SPAN
    locator: str | None = None
    language: str | None = None
    track: str | None = None
    raw_ref: str | None = None
    normalized_ref: str | None = None
    artifact_ref: str | None = None
    extraction_stage: str | None = None
    tool_versions: dict[str, str] = Field(default_factory=dict)
    config_digest: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    quality: dict[str, Any] = Field(default_factory=dict)


class Entity(BaseModel):
    """An entity (entity table row)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    entity_type: EntityType | str = EntityType.SOURCE
    label: str | None = Field(default=None, max_length=512)
    metadata_: dict[str, Any] = Field(default_factory=dict)


class EntityMention(BaseModel):
    """An entity mention pinned to source evidence (entity_mention table row)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    entity_id: uuid.UUID | None = None
    source_id: uuid.UUID
    segment_id: uuid.UUID | None = None
    mention_text: str = Field(min_length=1)
    normalized_forms: list[str] = Field(default_factory=list)
    speaker_label: str | None = None
    face_cluster: str | None = None


class SemanticAssertion(BaseModel):
    """A semantic assertion (semantic_assertion table row).

    ``predicate_code`` is validated against the open predicate vocabulary.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    predicate_code: str = Field(max_length=64)
    subject_entity_id: uuid.UUID | None = None
    subject_ref: str | None = Field(default=None, max_length=512)
    object_entity_id: uuid.UUID | None = None
    object_ref: str | None = Field(default=None, max_length=512)
    authority: str | None = Field(default=None, max_length=64)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    state: ConfidenceState = ConfidenceState.UNKNOWN
    continuity_id: uuid.UUID | None = None
    narrative_time: NarrativeTime | None = None
    spatial: SpatialReference | None = None
    support_refs: list[str] = Field(default_factory=list)
    contradiction_refs: list[str] = Field(default_factory=list)
    derived_from: list[str] = Field(default_factory=list)
    generated_by: dict[str, Any] = Field(default_factory=dict)

    @field_validator("predicate_code")
    @classmethod
    def _validate_predicate(cls, v: str) -> str:
        code = v.strip().upper()
        if not is_known_predicate(code):
            raise ValueError(f"predicate {v!r} is not registered; register_predicate() first")
        return code
