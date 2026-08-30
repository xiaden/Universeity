"""Bounded semantic-question compiler (P3-S2).

Implements the binding contract ``QuestionService.answer(question, constraints) ->
StructuredAnswer``.

The rule here is the CONTRACTS/DD hard constraint: a natural-language question is
NEVER answered from an unstructured-only corpus. Every supported question compiles
to ONE OR MORE *typed* operations — ``QueryService.structured(...)`` (bounded
relational) and/or ``SearchService.hybrid(...)`` (exact+vector, result-kind
labelled) — and the answer is assembled only from those typed, provenance-bearing,
result-kind-labelled hits.

v1 has no LLM behind this compiler: parsing is deterministic and rule-based so the
answer is reproducible and bounded (no provider, no opaque RAG). The consequence is
honest: unsupported questions compile to nothing and return an ``unresolved`` result
rather than inventing an answer. Query cost is bounded via ``QueryCostConstraints``
(``max_depth``, ``limit``, ``confidence_min``), never arbitrary traversal.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from umd.projections.query import (
    BoundedReport,
    ProvenanceBearingPage,
    QueryResultHit,
    QueryService,
    StructuredQuery,
)

#: Supported question intents mapped to a typed structured-query kind.
_UTTERANCE_PATTERNS = (
    re.compile(r"what does .*? say", re.I),
    re.compile(r"what does .*? (?:utter|pronounce)", re.I),
    re.compile(r"say[s]? by .*", re.I),
    re.compile(r"(?:utterance|speech|words) of .*", re.I),
)


class QuestionConstraints(BaseModel):
    """Bounds applied to every compiled semantic question (query cost limit)."""

    confidence_min: float | None = None
    continuity_id: str | None = None
    result_kind: str | None = None
    max_depth: int = 2
    limit: int = 20
    max_compiled_ops: int = 8


class AnswerItem(BaseModel):
    """One provenance-bearing, result-kind-labelled answer element."""

    ref: str
    kind: str  # SOURCE_EVIDENCE | INTERPRETATION | CANONICAL_ENTITY
    label: str
    predicate: str | None = None
    value: str | None = None
    confidence: float | None = None
    locator: str | None = None
    source_id: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    generated_by: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)


class StructuredAnswer(BaseModel):
    """Compiled, evidence-bearing answer to a natural-language question."""

    question: str
    #: The typed operations the question compiled to (never unstructured-only RAG).
    compiled_ops: list[str]
    answer: list[AnswerItem]
    interpretation: str
    confidence: float
    support: list[str]
    alternatives: list[AnswerItem]
    unresolved: list[AnswerItem]
    contradictory: list[AnswerItem]
    result_kind_labels: list[str]
    provenance: dict[str, Any] = Field(default_factory=dict)
    bound_report: BoundedReport = Field(default_factory=BoundedReport)


def _locator_of(hit: QueryResultHit) -> str | None:
    if hit.value and hit.value.startswith("source://"):
        return hit.value
    return None


class QuestionService:
    """Compiles supported questions to typed operations and returns a StructuredAnswer."""

    def __init__(self, query: QueryService, search: Any | None = None) -> None:
        self._query = query
        self._search = search  # optional SearchService for alias/exact alternatives

    # -- entry ------------------------------------------------------------

    def answer(
        self, question: str, constraints: QuestionConstraints | dict[str, Any] | None = None
    ) -> StructuredAnswer:
        c = (
            constraints
            if isinstance(constraints, QuestionConstraints)
            else QuestionConstraints(**(constraints or {}))
        )
        compiled_ops: list[str] = []
        pages: list[ProvenanceBearingPage] = []
        alternatives: list[AnswerItem] = []

        entity = self._extract_entity(question)

        # -- typed operation dispatch (each returns result-kind-labelled hits) ----
        if _is_utterance(question) and entity:
            compiled_ops.append("UTTERANCE")
            pages.append(
                self._query.structured(
                    StructuredQuery(
                        kind="UTTERANCE",
                        filters={"speaker": entity},
                        confidence_min=c.confidence_min,
                        limit=c.limit,
                    )
                )
            )
        elif "contradiction" in question.lower() and entity:
            compiled_ops.append("CONTRADICTIONS")
            pages.append(
                self._query.structured(
                    StructuredQuery(
                        kind="CONTRADICTIONS", limit=c.limit, confidence_min=c.confidence_min
                    )
                )
            )
        elif "unresolved" in question.lower():
            compiled_ops.append("UNRESOLVED_ALIASES")
            pages.append(
                self._query.structured(StructuredQuery(kind="UNRESOLVED_ALIASES", limit=c.limit))
            )
        elif "evidence" in question.lower():
            compiled_ops.append("EVIDENCE")
            pages.append(
                self._query.structured(
                    StructuredQuery(
                        kind="EVIDENCE",
                        filters={"source_id": entity} if entity else {},
                        limit=c.limit,
                    )
                )
            )
        elif entity is not None:
            # who/what/describe/where + entity -> bounded ENTITY lookup.
            compiled_ops.append("ENTITY")
            pages.append(
                self._query.structured(
                    StructuredQuery(
                        kind="ENTITY",
                        filters={"ref": entity},
                        confidence_min=c.confidence_min,
                        limit=c.limit,
                    )
                )
            )
            # Alternatives: resolve the entity name through hybrid search so the
            # answer can point at matching source evidence / interpretations too.
            if self._search is not None:
                compiled_ops.append("SEARCH_HYBRID")
                alt_page = self._search.hybrid(query=entity, limit=c.limit)
                for h in getattr(alt_page, "hits", []):
                    alternatives.append(
                        AnswerItem(
                            ref=h.ref,
                            kind=h.kind,
                            label=h.label,
                            value=h.text,
                            locator=h.source_id,
                            source_id=h.source_id,
                            confidence=h.score,
                        )
                    )

        # -- assemble the answer (typed hits only) ----------------------------
        answer: list[AnswerItem] = []
        support: list[str] = []
        unresolved: list[AnswerItem] = []
        contradictory: list[AnswerItem] = []
        kind_labels: set[str] = set()
        for page in pages:
            kind_labels.update(page.result_kinds)
            for h in page.results:
                if h.kind == "INTERPRETATION" and page.query == "CONTRADICTIONS":
                    contradictory.append(self._to_item(h))
                    continue
                if page.query == "UNRESOLVED_ALIASES":
                    unresolved.append(self._to_item(h))
                    continue
                answer.append(self._to_item(h))
                if h.value:
                    support.append(h.value)
        if not pages:
            unresolved.append(
                AnswerItem(
                    ref="",
                    kind="INTERPRETATION",
                    label="unresolved",
                    value=f"no typed operation matched question: {question}",
                )
            )

        conf = _aggregate_confidence(answer, contradictory)
        return StructuredAnswer(
            question=question,
            compiled_ops=list(dict.fromkeys(compiled_ops)),
            answer=answer,
            interpretation=_interpretation(answer, unresolved),
            confidence=conf,
            support=list(dict.fromkeys(support)),
            alternatives=alternatives,
            unresolved=unresolved,
            contradictory=contradictory,
            result_kind_labels=sorted(kind_labels),
            provenance={
                "authority": "typed relational projection (never unstructured-only RAG)",
                "compiled": list(dict.fromkeys(compiled_ops)),
            },
            bound_report=BoundedReport(max_depth_cap=c.max_depth),
        )

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _to_item(h: QueryResultHit) -> AnswerItem:
        return AnswerItem(
            ref=h.ref,
            kind=h.kind,
            label=h.label,
            predicate=h.predicate,
            value=h.value,
            confidence=h.confidence,
            locator=_locator_of(h),
            source_id=h.source_id,
            provenance={
                "ref": h.ref,
                "source_id": h.source_id,
                "segment_id": h.segment_id,
                "locator": _locator_of(h),
            },
            generated_by=dict(h.data.get("generated_by", {})),
            capabilities=dict(h.data.get("capabilities", {})),
            data=h.data,
        )

    @staticmethod
    def _extract_entity(question: str) -> str | None:
        """A best-effort, reused entity ref from a known prefix; else None.

        Deterministic rule: ``who/what/where/describe/when + trailing tokens`` is
        taken as the entity name; a bare token or nothing yields ``None`` so the
        compiler does not guess wildly.
        """
        m = re.match(
            r"^(?:who|what|where|when|describe|tell me about)\s+?"
            r"(?:is|are|was|were|does|did)?\s*(.+)$",
            question.strip(),
            flags=re.I,
        )
        if not m:
            return None
        name = m.group(1).strip().strip("?.,!;:")
        # A trailing utterance verb is the question's verb, not part of the entity:
        # "what does e:hero say" -> entity "e:hero" (not "e:hero say").
        name = re.sub(
            r"\s+(?:say|says|said|utter|utters|uttered|pronounce|pronounces)$",
            "",
            name,
            flags=re.I,
        ).strip()
        if not name or len(name.split()) > 6:
            return None
        return name


def _is_utterance(question: str) -> bool:
    return any(p.search(question) for p in _UTTERANCE_PATTERNS)


def _aggregate_confidence(answer: list[AnswerItem], contradictions: list[AnswerItem]) -> float:
    confs = [a.confidence for a in answer if a.confidence is not None]
    if contradictions:
        return 0.0  # contradictory evidence => no confident answer
    if not confs:
        return 0.0
    return round(sum(confs) / len(confs), 3)


def _interpretation(answer: list[AnswerItem], unresolved: list[AnswerItem]) -> str:
    if unresolved or not answer:
        return "unresolved: no confident typed answer; nothing inferred"
    values = "; ".join(a.value for a in answer[:5] if a.value)
    return (
        f"compiled from {len(answer)} typed result(s): {values}"
        if values
        else "compiled from typed results"
    )


__all__ = [
    "QuestionService",
    "StructuredAnswer",
    "AnswerItem",
    "QuestionConstraints",
]
