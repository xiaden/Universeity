"""Strict parser for provider-backed semantic-analysis output (Plan M P1-S3).

The model is never authority (Task §14, DD §Provider/plugin): provider output is
opaque JSON until it is validated here. This parser **rejects** unknown or
malformed structures, **validates** ranges/enums/references (confidence bounds,
semantic state enums, exact segment evidence), and **records warnings** for any
field that cannot be promoted — so malformed or weak provider output degrades
honestly to the deterministic/reference baseline instead of being promoted as
fact.

Only observations that validate into the typed contract (CONTRACTS.md:75) are
returned; every rejected item increments ``rejected`` and adds a warning.
:class:`SemanticParseError` is raised only when the top-level output is not a
parseable object (no partial promotion from garbage).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from umd.analysis.semantic import (
    ContextObservation,
    DescriptiveTrait,
    EmotionObservation,
    EntityMention,
    GeneratedBy,
    NormalizedAlias,
    Presence,
    RelationshipCandidate,
    SceneBoundary,
    SegmentEvidenceRef,
    SemanticAnalysisResult,
    SemanticCandidate,
    SpeakerCandidate,
    StateObservation,
    Utterance,
)


class SemanticParseError(ValueError):
    """Provider semantic output could not be parsed into the typed contract at all."""


class SemanticProviderParse(BaseModel):
    """The result of strict-parsing + validating provider output (P1-S3).

    ``result`` holds only validated, evidence-tied observations (empty lists when
    nothing promoted); ``rejected`` counts malformed/unknown/unsupported items
    and ``warnings`` explains every rejection so the caller can report honestly.
    """

    result: SemanticAnalysisResult
    rejected: int = 0
    warnings: list[str] = Field(default_factory=list)


#: Top-level category keys the typed contract accepts. Anything else is unknown
#: and rejected (strict: no silent promotion of unexpected structures).
_KNOWN_KEYS = {
    "scenes",
    "entities",
    "aliases",
    "presence",
    "utterances",
    "speakers",
    "traits",
    "relationships",
    "emotions",
    "states",
    "context",
}


def _parse_candidates[Candidate: SemanticCandidate](
    cls: type[Candidate],
    raw_items: Any,
    *,
    generated_by: GeneratedBy,
    default_segment: SegmentEvidenceRef | None,
    label: str,
) -> tuple[list[Candidate], int, list[str]]:
    """Validate ``raw_items`` (a list of dicts) into ``cls`` observations.

    Returns ``(valid, rejected, warnings)``. An entry is rejected when it is not
    an object, when it lacks an exact ``segment`` evidence reference (and no
    ``default_segment`` is supplied), or when it fails typed validation
    (confidence out of range, invalid state enum, malformed refs). Rejections
    never fabricate a fallback value — they are counted and warned.
    """
    if raw_items is None:
        return [], 0, []
    if not isinstance(raw_items, list):
        return (
            [],
            1,
            [f"{label}: expected a list, got {type(raw_items).__name__}; rejected"],
        )
    valid: list[Candidate] = []
    rejected = 0
    warnings: list[str] = []
    for i, item in enumerate(raw_items):
        if not isinstance(item, dict):
            rejected += 1
            warnings.append(f"{label}[{i}]: rejected non-object entry")
            continue
        seg_raw = item.get("segment")
        if not isinstance(seg_raw, dict) or not seg_raw.get("locator"):
            if default_segment is None:
                rejected += 1
                warnings.append(f"{label}[{i}]: missing exact segment evidence reference; rejected")
                continue
            seg = default_segment
        else:
            try:
                seg = SegmentEvidenceRef.model_validate(seg_raw)
            except ValidationError as exc:
                rejected += 1
                warnings.append(f"{label}[{i}]: invalid segment evidence: {exc}")
                continue
        try:
            valid.append(cls.model_validate({**item, "segment": seg, "generated_by": generated_by}))
        except ValidationError as exc:
            rejected += 1
            warnings.append(f"{label}[{i}]: invalid {label} observation: {exc}")
    return valid, rejected, warnings


def parse_semantic_output(
    output: Any,
    *,
    source_id: str,
    generated_by: GeneratedBy,
    default_segment: SegmentEvidenceRef | None = None,
    warnings: list[str] | None = None,
) -> SemanticProviderParse:
    """Strict-parse raw provider ``output`` into a :class:`SemanticProviderParse`.

    :raises SemanticParseError: ``output`` is not a JSON object (nothing to
        validate), or the provider result lacks the required typed shape.
    """
    if not isinstance(output, dict):
        raise SemanticParseError(
            f"provider semantic output must be an object, got {type(output).__name__}"
        )
    unknown = sorted(set(output) - _KNOWN_KEYS)
    all_warnings = list(warnings or [])
    total_rejected = 0
    if unknown:
        all_warnings.append(f"rejected unknown top-level keys: {', '.join(unknown)}")
        total_rejected += len(unknown)

    result = SemanticAnalysisResult(
        source_id=source_id,
        generated_by=generated_by,
        warnings=list(all_warnings),
    )

    def _apply[Candidate: SemanticCandidate](attr: str, cls: type[Candidate], raw: Any) -> None:
        nonlocal total_rejected
        values, rejected, extra = _parse_candidates(
            cls,
            raw,
            generated_by=generated_by,
            default_segment=default_segment,
            label=attr,
        )
        setattr(result, attr, values)
        total_rejected += rejected
        all_warnings.extend(extra)

    _apply("scene_boundaries", SceneBoundary, output.get("scenes"))
    _apply("entity_mentions", EntityMention, output.get("entities"))
    _apply("aliases", NormalizedAlias, output.get("aliases"))
    _apply("presence", Presence, output.get("presence"))
    _apply("utterances", Utterance, output.get("utterances"))
    _apply("speaker_candidates", SpeakerCandidate, output.get("speakers"))
    _apply("traits", DescriptiveTrait, output.get("traits"))
    _apply("relationships", RelationshipCandidate, output.get("relationships"))
    _apply("emotions", EmotionObservation, output.get("emotions"))
    _apply("states", StateObservation, output.get("states"))
    _apply("context", ContextObservation, output.get("context"))

    result.warnings = all_warnings
    return SemanticProviderParse(
        result=result,
        rejected=total_rejected,
        warnings=all_warnings,
    )


__all__ = [
    "SemanticParseError",
    "SemanticProviderParse",
    "parse_semantic_output",
]
