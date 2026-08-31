"""Deterministic/reference structural text analysis (Plan M P1-S2).

Builds a typed :class:`SemanticAnalysisResult` (CONTRACTS.md:75) from the
deterministic baseline, consuming Plan L's **chapter-aware segment records**
(paragraph segment text + structural path + canonical locator + registered
segment id) so evidence is tied to exact segments — never reconstructed from
OCFL bytes.

The deterministic path:

  * **dialogue / narration** — a paragraph is classified as *dialogue* when it
    contains a quoted span or a speaker-directive dash; otherwise *narration*.
    This structural finding is recorded as evidence with the paragraph's exact
    segment ref and exposed as a typed :class:`Utterance` + optional
    :class:`SpeakerCandidate`.
  * **candidate mentions** — deterministic, low-confidence candidate
    observations for entities (capitalized repeating runs) and relationships
    (co-occurring entities), each pinned to its exact segment ref and marked as
    a candidate (:class:`EntityMention` / :class:`Presence` /
    :class:`RelationshipCandidate`), NOT promoted to semantic truth.
  * **scene boundaries** — deterministic structural approximations derived from
    chapter transitions in the segment records (a chapter start is a low-
    confidence :class:`SceneBoundary` tied to the exact chapter segment).

Observations the deterministic path cannot honestly support (aliases, traits,
emotions, states, context) are left **ABSENT** — never inferred/fabricated. The
same typed shape is what the optional provider path (Phase 2) returns, so both
paths degrade to one validated contract.

Everything here is *evidence* (:class:`EvidenceRepository` records), not
semantic assertions; the source/evidence/interpretation separation is preserved.
Stage name ``STRUCTURAL_ANALYSIS`` aligns with :mod:`umd.jobs.dag`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from umd.analysis.semantic import (
    DialogueSpan,
    EntityMention,
    GeneratedBy,
    Presence,
    RelationshipCandidate,
    SceneBoundary,
    SegmentEvidenceRef,
    SemanticAnalysisResult,
    SemanticPath,
    SpeakerCandidate,
    Utterance,
)
from umd.domain.models import ConfidenceState, Evidence, EvidenceKind

#: A quoted span — dialogue marker.
_QUOTE_RE = re.compile(r'"[^"]*"|\u201c[^\u201d]*\u201d|\'[^\']*\'|\u2018[^\u2019]*\u2019')
#: Speaker-directive dash at line/paragraph start.
_DASH_RE = re.compile(r"^\s*[\u2014\u2013-]\s")
#: Documented speaker labels such as ``Alice:`` used as dialogue attribution.
_ATTRIB_RE = re.compile(r"^\s*([A-Z][A-Za-z']+):\s*(.+)")
#: Capitalized run used as a candidate named-entity mention.
_CAP_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b")

#: Deterministic analyzer provenance tag.
_ANALYZER = "umd-text-structural@2"


@dataclass(frozen=True)
class ParagraphSegment:
    """A chapter-aware paragraph segment record (Plan L) for deterministic analysis.

    ``segments`` in :func:`analyze_segments` carry the exact structural path,
    canonical locator and registered segment id so evidence is pinned to the
    actual registered segment — never a hard-coded ``chapter/1`` path.
    """

    text: str
    paragraph_index: int
    chapter: int
    locator: str
    structural_path: str = ""
    segment_id: str | None = None


def classify_dialogue(paragraph: str) -> bool:
    """True if a paragraph is dialogue (quoted span or speaker-directive dash)."""
    if _DASH_RE.match(paragraph):
        return True
    return bool(_QUOTE_RE.search(paragraph))


def extract_quotes(paragraph: str) -> list[str]:
    return [strip_quotes(m) for m in _QUOTE_RE.findall(paragraph) if strip_quotes(m)]


def strip_quotes(match: str) -> str:
    return match.strip("\"'“”‘’ ")


def candidate_speaker(paragraph: str) -> str | None:
    """Deterministic speaker-candidate from a dialogue paragraph."""
    quotes = extract_quotes(paragraph)
    if not quotes:
        return None
    # Attribution like ``Alice said, ...`` preceding the first quote.
    first_q = quotes[0]
    idx = paragraph.find(first_q)
    prefix = paragraph[:idx] if idx != -1 else ""
    attribution = re.sub(r"[^A-Za-z' ]+", " ", prefix).strip()
    words = [w for w in attribution.split() if w and w[0].isupper()]
    return words[-1] if words else None


def _locator_for(chapter: int, para: int) -> str:
    return f"chapter/{chapter}/paragraph/{para}"


def analyze_text(
    *,
    source_id: str,
    paragraphs: list[str],
    tool_versions: dict[str, str] | None = None,
    language: str | None = None,
    extraction_stage: str = "STRUCTURAL_ANALYSIS",
    config_digest: str | None = None,
) -> SemanticAnalysisResult:
    """Run deterministic analysis over a flat paragraph list (reference baseline).

    Backward-compatible entry point: ``paragraphs`` are treated as one chapter
    (chapter 1) with deterministic ``chapter/1/paragraph/N`` locators, matching
    the historical baseline. Callers with Plan L chapter-aware segment records
    should use :func:`analyze_segments` instead for exact segment evidence.
    """
    segments = [
        ParagraphSegment(
            text=para,
            paragraph_index=idx,
            chapter=1,
            locator=_locator_for(1, idx),
            structural_path=f"chapter/1/paragraph/{idx}",
        )
        for idx, para in enumerate(paragraphs, start=1)
    ]
    return analyze_segments(
        source_id=source_id,
        segments=segments,
        tool_versions=tool_versions,
        language=language,
        extraction_stage=extraction_stage,
        config_digest=config_digest,
    )


def analyze_segments(
    *,
    source_id: str,
    segments: list[ParagraphSegment],
    tool_versions: dict[str, str] | None = None,
    language: str | None = None,
    extraction_stage: str = "STRUCTURAL_ANALYSIS",
    config_digest: str | None = None,
) -> SemanticAnalysisResult:
    """Run deterministic analysis over Plan L chapter-aware segment records.

    ``segments`` are paragraph records carrying their exact structural path,
    canonical locator and registered segment id (Plan L). Each paragraph is
    classified for dialogue/narration and emits evidence + typed observations
    tied to its exact segment. Scene boundaries are derived from chapter
    transitions (deterministic structural approximation). Unsupported categories
    (aliases/traits/emotions/states/context) are left ABSENT.
    """
    tools = {
        "segmenter": "umd-text",
        "decoder": "umd-stdlib",
        "analyzer": _ANALYZER,
        **(tool_versions or {}),
    }
    generated_by = GeneratedBy(
        path=SemanticPath.DETERMINISTIC,
        analyzer=tools["analyzer"],
        config_digest=config_digest,
    )
    result = SemanticAnalysisResult(source_id=source_id, generated_by=generated_by)
    prev_chapter: int | None = None

    for seg in segments:
        para = seg.text
        locator = seg.locator
        is_dialogue = classify_dialogue(para)
        quotes = extract_quotes(para)
        speaker = candidate_speaker(para) if is_dialogue else None
        result.dialogue_spans.append(
            DialogueSpan(
                paragraph_index=seg.paragraph_index,
                locator=locator,
                text=para,
                is_dialogue=is_dialogue,
                quotes=quotes,
                speaker_candidate=speaker,
            )
        )

        # Dialogue/narration structural finding (evidence row, not semantic).
        ev = _ev(
            source_id=source_id,
            locator=locator,
            segment_id=seg.segment_id,
            kind=EvidenceKind.TEXT_SPAN,
            stage=extraction_stage,
            tools=tools,
            config_digest=config_digest,
            language=language,
            confidence=0.9,
            quality={
                "finding": "dialogue" if is_dialogue else "narration",
                "quotes": quotes,
                "speaker_candidate": speaker,
            },
        )
        result.evidence.append(ev)
        seg_ref = SegmentEvidenceRef(
            locator=locator,
            segment_id=seg.segment_id,
            evidence_ref=str(ev.id),
            chapter=seg.chapter,
            paragraph=seg.paragraph_index,
        )

        # Scene boundary at a chapter start (deterministic structural
        # approximation from Plan L chapter-aware segments, low confidence).
        if prev_chapter is None or seg.chapter != prev_chapter:
            result.scene_boundaries.append(
                SceneBoundary(
                    scene_ref=f"scene/{seg.chapter}",
                    boundary="start",
                    label=f"chapter {seg.chapter}",
                    confidence=0.5,
                    state=ConfidenceState.PROBABLE,
                    segment=seg_ref,
                    generated_by=generated_by,
                )
            )
        prev_chapter = seg.chapter

        if is_dialogue:
            result.utterances.append(
                Utterance(
                    utterance_text=para,
                    speaker=speaker,
                    confidence=0.9,
                    state=ConfidenceState.PROBABLE,
                    segment=seg_ref,
                    generated_by=generated_by,
                )
            )
            if speaker:
                result.speaker_candidates.append(
                    SpeakerCandidate(
                        speaker_label=speaker,
                        utterance_ref=seg_ref.evidence_ref,
                        confidence=0.5,
                        state=ConfidenceState.PROBABLE,
                        segment=seg_ref,
                        generated_by=generated_by,
                    )
                )

        _record_candidates(result, para, seg_ref, generated_by, tools, config_digest, language)

    return result


def _record_candidates(
    result: SemanticAnalysisResult,
    paragraph: str,
    seg_ref: SegmentEvidenceRef,
    generated_by: GeneratedBy,
    tools: dict[str, str],
    config_digest: str | None,
    language: str | None,
) -> None:
    """Deterministic low-confidence candidate observations for named mentions.

    Emits entity-mention + presence + relationship candidates (and their
    evidence rows) tied to the exact ``seg_ref``. Unsupported observations are
    left absent — no fabricated claims.
    """
    seen: set[tuple[str, str]] = set()
    # candidate person/place entities from capitalized runs
    for m in _CAP_RE.finditer(paragraph):
        run = m.group(0)
        # Real token offset: the whitespace-separated token index on which this
        # capitalized run begins (not the enumerate index of the regex results).
        token_offset = len(paragraph[: m.start()].split())
        # skip a run that is the first word (sentence-start capitalization is
        # ambiguous/deterministic-noise); keep runs that repeat or are mid-list.
        key = ("entity", run)
        if key in seen:
            continue
        seen.add(key)
        if _CAP_RE.fullmatch(run) and run.split() and _repeats(paragraph, run):
            ev = _ev(
                source_id=result.source_id,
                locator=seg_ref.locator,
                segment_id=seg_ref.segment_id,
                kind=EvidenceKind.TEXT_SPAN,
                stage="STRUCTURAL_ANALYSIS",
                tools=tools,
                config_digest=config_digest,
                language=language,
                confidence=0.3,
                quality={
                    "candidate_kind": "entity",
                    "mention_text": run,
                    "sentence_offset": token_offset,
                    # Plan T (P3-S1): carry the full surrounding paragraph so the
                    # production resolution anchor can include a content digest
                    # (ctx:) that separates coincident-structural same-name
                    # mentions (John A/B) instead of merging by name/work/locator.
                    "context_text": paragraph,
                },
            )
            result.evidence.append(ev)
            candidate_ref = seg_ref.model_copy(update={"evidence_ref": str(ev.id)})
            result.entity_mentions.append(
                EntityMention(
                    mention=run,
                    entity_type="character",
                    confidence=0.3,
                    state=ConfidenceState.PROBABLE,
                    segment=candidate_ref,
                    generated_by=generated_by,
                    context_text=paragraph,
                )
            )
            result.presence.append(
                Presence(
                    entity=run,
                    present_in=seg_ref.locator,
                    confidence=0.3,
                    state=ConfidenceState.PROBABLE,
                    segment=candidate_ref,
                    generated_by=generated_by,
                )
            )
    # relationships: co-occurring capitalized entities in one paragraph
    entities = [m for m in seen if m[0] == "entity"]
    if len(entities) >= 2:
        ev = _ev(
            source_id=result.source_id,
            locator=seg_ref.locator,
            segment_id=seg_ref.segment_id,
            kind=EvidenceKind.TEXT_SPAN,
            stage="STRUCTURAL_ANALYSIS",
            tools=tools,
            config_digest=config_digest,
            language=language,
            confidence=0.2,
            quality={
                "candidate_kind": "relationship",
                "co_occurring": [m[1] for m in entities],
            },
        )
        result.evidence.append(ev)
        candidate_ref = seg_ref.model_copy(update={"evidence_ref": str(ev.id)})
        result.relationships.append(
            RelationshipCandidate(
                subject_ref=entities[0][1],
                predicate="CO_OCCURS",
                object_ref=entities[1][1],
                confidence=0.2,
                state=ConfidenceState.PROBABLE,
                segment=candidate_ref,
                generated_by=generated_by,
            )
        )


def _repeats(paragraph: str, run: str) -> bool:
    """True when a capitalized run appears more than once (a likely entity)."""
    return paragraph.count(run) > 1


def _ev(
    *,
    source_id: str,
    locator: str,
    segment_id: str | None,
    kind: EvidenceKind,
    stage: str,
    tools: dict[str, str],
    config_digest: str | None,
    language: str | None,
    confidence: float,
    quality: dict[str, object],
) -> Evidence:
    return Evidence(
        source_id=source_id,
        segment_id=segment_id,
        evidence_kind=kind,
        locator=locator,
        language=language,
        extraction_stage=stage,
        tool_versions=tools,
        config_digest=config_digest,
        confidence=confidence,
        quality=quality,
    )


__all__ = [
    "DialogueSpan",
    "ParagraphSegment",
    "SemanticAnalysisResult",
    "analyze_segments",
    "analyze_text",
    "candidate_speaker",
    "classify_dialogue",
    "extract_quotes",
    "strip_quotes",
]
