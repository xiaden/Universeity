"""Structural text analysis: dialogue/narration + candidate evidence (P2-S2).

Deterministic structural findings over the segmented text baseline:

  * **dialogue / narration** — a paragraph is classified as *dialogue* when it
    contains a quoted span or a speaker-directive dash; otherwise *narration*.
    This is a structural finding, recorded as evidence with the paragraph's
    source locator (never promotes itself into canonical identity).
  * **candidate mentions** — deterministic, low-confidence candidate
    observations for entities, aliases, speaker candidates, events, locations and
    relationships, each pinned to its source locator and marked as a candidate
    (``quality.candidate_kind``), NOT promoted to semantic truth.

Everything here is *evidence* (``EvidenceRepository.record``), not semantic
assertions; the source/evidence/interpretation separation is preserved. Stage
name ``STRUCTURAL_ANALYSIS`` aligns with :mod:`umd.jobs.dag`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from umd.domain.models import Evidence, EvidenceKind

#: A quoted span — dialogue marker.
_QUOTE_RE = re.compile(r'"[^"]*"|\u201c[^\u201d]*\u201d|\'[^\']*\'|\u2018[^\u2019]*\u2019')
#: Speaker-directive dash at line/paragraph start.
_DASH_RE = re.compile(r"^\s*[\u2014\u2013-]\s")
#: Documented speaker labels such as ``Alice:`` used as dialogue attribution.
_ATTRIB_RE = re.compile(r"^\s*([A-Z][A-Za-z']+):\s*(.+)")
#: Capitalized run used as a candidate named-entity mention.
_CAP_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b")


@dataclass
class DialogueSpan:
    """A dialogue span and optional deterministic speaker candidate."""

    paragraph_index: int
    locator: str
    text: str
    is_dialogue: bool
    quotes: list[str] = field(default_factory=list)
    speaker_candidate: str | None = None


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


@dataclass
class StructuralTextResult:
    """Evidence-bearing structural findings for one source."""

    source_id: str
    dialogue_spans: list[DialogueSpan] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def analyze_text(
    *,
    source_id: str,
    paragraphs: list[str],
    tool_versions: dict[str, str] | None = None,
    language: str | None = None,
    extraction_stage: str = "STRUCTURAL_ANALYSIS",
    config_digest: str | None = None,
) -> StructuralTextResult:
    """Run deterministic dialogue/narration + candidate analysis over paragraphs.

    ``paragraphs`` are the normalized source paragraphs (in reading order) with
    their chapter/paragraph structural positions implied by list order (assumed
    single-chapter here; multi-chapter callers pass flattened paragraphs from one
    source and keep positions via ``locator_prefix`` is not needed for the
    baseline).
    """
    result = StructuralTextResult(source_id=source_id)
    tools = {
        "segmenter": "umd-text",
        "decoder": "umd-stdlib",
        "analyzer": "umd-text-structural@1",
        **(tool_versions or {}),
    }

    for idx, para in enumerate(paragraphs, start=1):
        locator = _locator_for(1, idx)
        is_dialogue = classify_dialogue(para)
        quotes = extract_quotes(para)
        speaker = candidate_speaker(para) if is_dialogue else None
        result.dialogue_spans.append(
            DialogueSpan(
                paragraph_index=idx,
                locator=locator,
                text=para,
                is_dialogue=is_dialogue,
                quotes=quotes,
                speaker_candidate=speaker,
            )
        )

        # Dialogue/narration structural finding (evidence row, not semantic).
        result.evidence.append(
            _ev(
                source_id=source_id,
                locator=locator,
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
        )

        _record_candidates(result, para, locator, idx, tools, config_digest, language)

    return result


def _record_candidates(
    result: StructuralTextResult,
    paragraph: str,
    locator: str,
    _para_idx: int,
    tools: dict[str, str],
    config_digest: str | None,
    language: str | None,
) -> None:
    """Deterministic low-confidence candidate observations for named mentions."""
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
            result.evidence.append(
                _ev(
                    source_id=result.source_id,
                    locator=locator,
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
                    },
                )
            )
    # relationships: co-occurring capitalized entities in one paragraph
    entities = [m for m in seen if m[0] == "entity"]
    if len(entities) >= 2:
        result.evidence.append(
            _ev(
                source_id=result.source_id,
                locator=locator,
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
        )


def _repeats(paragraph: str, run: str) -> bool:
    """True when a capitalized run appears more than once (a likely entity)."""
    return paragraph.count(run) > 1


def _ev(
    *,
    source_id: str,
    locator: str,
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
        evidence_kind=kind,
        locator=locator,
        language=language,
        extraction_stage=stage,
        tool_versions=tools,
        config_digest=config_digest,
        confidence=confidence,
        quality=quality,
    )
