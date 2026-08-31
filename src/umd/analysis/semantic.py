"""Typed semantic text-analysis result contract (Plan M P1-S1).

The single provider-neutral, validated result shape returned by BOTH the
deterministic/reference path and the optional provider-backed path
(``SemanticTextAnalyzer.analyze(input) -> SemanticAnalysisResult``,
CONTRACTS.md:75). It is deliberately *generic* — no audiobook/TTS/Alexandria-
specific schemas — and covers the requested observation categories: scene
boundaries, entity/character mentions, normalized aliases, scene/segment
presence, utterance boundaries, speaker candidates, descriptive traits,
relationship candidates, and emotion/state/context.

Design rules:

* every candidate is **confidence-scoped** (``confidence`` 0..1) and tied to an
  exact segment/evidence reference (:class:`SegmentEvidenceRef`);
* every candidate carries a semantic :class:`ConfidenceState` (the ledger's
  typed state vocabulary) and :class:`GeneratedBy` provenance (path +
  analyzer/provider/model/config/prompt/version);
* the model is **never authority** — ``SemanticAnalysisResult`` is a validated
  observation contract; the deterministic path leaves unsupported categories
  ABSENT rather than fabricating them, and the strict provider parser
  (``umd.analysis.semantic_parser``) rejects malformed/unknown structures
  before anything is promoted.

The deterministic/reference path additionally emits the durable evidence rows
it records (``evidence``) and the dialogue/narration spans (``dialogue_spans``),
preserving the historical ``umd.analysis.text_structural`` behavior while
exposing the same typed shape the provider path returns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from umd.domain.models import ConfidenceState, Evidence


class SemanticPath(StrEnum):
    """Which pipeline produced an observation (deterministic or provider)."""

    DETERMINISTIC = "deterministic"
    PROVIDER = "provider"


class SegmentEvidenceRef(BaseModel):
    """Exact segment/evidence reference for one observation (CONTRACTS.md:75).

    ``locator`` is the canonical ``source://`` locator (or a deterministic
    structural path on the reference baseline); ``segment_id`` is the registered
    segment row id (Plan L) when available and ``evidence_ref`` the durable
    evidence row id the observation is tied to. ``chapter``/``paragraph`` are
    the 1-based structural coordinates when derivable.
    """

    locator: str = Field(min_length=1)
    segment_id: str | None = None
    evidence_ref: str | None = None
    chapter: int | None = Field(default=None, ge=1)
    paragraph: int | None = Field(default=None, ge=1)


class GeneratedBy(BaseModel):
    """``generated-by`` provenance metadata (deterministic or provider).

    For the deterministic path only ``path``/``analyzer``/``config_digest`` are
    populated; for a provider path ``provider``/``model``/``model_version``/
    ``prompt_version``/``config_digest`` are recorded from the model call so no
    observation loses its provenance (Task §13, DD §Provider/plugin).
    """

    path: SemanticPath = SemanticPath.DETERMINISTIC
    analyzer: str = Field(default="umd-text-structural@2", min_length=1)
    provider: str | None = None
    model: str | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    config_digest: str | None = None


@dataclass
class DialogueSpan:
    """A dialogue/narration span and optional deterministic speaker candidate.

    Preserved from the historical structural baseline so the deterministic path
    keeps its dialogue/narration behavior while exposing the typed result.
    """

    paragraph_index: int
    locator: str
    text: str
    is_dialogue: bool
    quotes: list[str] = field(default_factory=list)
    speaker_candidate: str | None = None


class SemanticCandidate(BaseModel):
    """Common confidence-scoped, evidence-tied fields for every observation.

    ``confidence`` is required (every candidate carries one, 0..1); ``state`` is
    the ledger semantic state; ``segment`` is the exact segment/evidence ref and
    ``generated_by`` the provenance.
    """

    confidence: float = Field(ge=0.0, le=1.0)
    state: ConfidenceState = ConfidenceState.PROBABLE
    segment: SegmentEvidenceRef
    generated_by: GeneratedBy


class SceneBoundary(SemanticCandidate):
    """A scene-boundary observation (start/end) at an exact segment."""

    scene_ref: str = Field(min_length=1)
    boundary: Literal["start", "end"] = "start"
    label: str | None = None


class EntityMention(SemanticCandidate):
    """An entity/character mention candidate tied to its segment."""

    mention: str = Field(min_length=1)
    entity_type: str = Field(default="character", min_length=1)


class NormalizedAlias(SemanticCandidate):
    """A normalized alias candidate mapping a surface form to a canonical name."""

    canonical_name: str = Field(min_length=1)
    alias: str = Field(min_length=1)
    entity_ref: str | None = None


class Presence(SemanticCandidate):
    """An entity's presence in a scene/segment."""

    entity: str = Field(min_length=1)
    present_in: str = Field(min_length=1)


class Utterance(SemanticCandidate):
    """An utterance boundary/observation (dialogue) tied to its segment."""

    utterance_text: str = Field(min_length=1)
    speaker: str | None = None


class SpeakerCandidate(SemanticCandidate):
    """A speaker candidate for an utterance."""

    speaker_label: str = Field(min_length=1)
    utterance_ref: str | None = None


class DescriptiveTrait(SemanticCandidate):
    """A descriptive trait observation about an entity."""

    entity: str = Field(min_length=1)
    trait: str = Field(min_length=1)


class RelationshipCandidate(SemanticCandidate):
    """A relationship candidate between two entities."""

    subject_ref: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object_ref: str = Field(min_length=1)


class EmotionObservation(SemanticCandidate):
    """An emotion/state observation where the provider/deterministic path supports it."""

    entity: str = Field(min_length=1)
    emotion: str = Field(min_length=1)


class StateObservation(SemanticCandidate):
    """A state observation for an entity where supported.

    ``observed_state`` is the observed narrative state (e.g. "asleep"), distinct
    from the candidate's ``ConfidenceState`` on :class:`SemanticCandidate`.
    """

    entity: str = Field(min_length=1)
    observed_state: str = Field(min_length=1)


class ContextObservation(SemanticCandidate):
    """A context/environment observation (scene/segment context) where supported."""

    context_type: str = Field(min_length=1)
    value: str = Field(min_length=1)


class SemanticAnalysisResult(BaseModel):
    """The single validated typed result contract (CONTRACTS.md:75).

    ``generated_by`` identifies the producing path and its provenance. Each
    observation list is provider-neutral; the deterministic path fills only the
    categories it honestly supports and leaves the rest ABSENT. ``evidence`` and
    ``dialogue_spans`` carry the deterministic path's durable evidence rows and
    dialogue/narration spans (the provider path leaves ``evidence`` empty).
    """

    source_id: str
    generated_by: GeneratedBy
    scene_boundaries: list[SceneBoundary] = Field(default_factory=list)
    entity_mentions: list[EntityMention] = Field(default_factory=list)
    aliases: list[NormalizedAlias] = Field(default_factory=list)
    presence: list[Presence] = Field(default_factory=list)
    utterances: list[Utterance] = Field(default_factory=list)
    speaker_candidates: list[SpeakerCandidate] = Field(default_factory=list)
    traits: list[DescriptiveTrait] = Field(default_factory=list)
    relationships: list[RelationshipCandidate] = Field(default_factory=list)
    emotions: list[EmotionObservation] = Field(default_factory=list)
    states: list[StateObservation] = Field(default_factory=list)
    context: list[ContextObservation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    dialogue_spans: list[DialogueSpan] = Field(default_factory=list)


__all__ = [
    "ConfidenceState",
    "ContextObservation",
    "DescriptiveTrait",
    "DialogueSpan",
    "EmotionObservation",
    "EntityMention",
    "GeneratedBy",
    "NormalizedAlias",
    "Presence",
    "RelationshipCandidate",
    "SceneBoundary",
    "SegmentEvidenceRef",
    "SemanticAnalysisResult",
    "SemanticCandidate",
    "SemanticPath",
    "SpeakerCandidate",
    "StateObservation",
    "Utterance",
]
