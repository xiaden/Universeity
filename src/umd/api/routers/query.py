"""Typed structured + semantic query boundaries (P3-S2 / P3-S3).

``POST /v1/query/structured`` compiles a typed, bounded query to
:class:`QueryService.structured` (result-kind labelled, provenance-bearing, bounded
depth). ``POST /v1/query/semantic`` compiles a natural-language question to typed
operations via :class:`QuestionService` and NEVER falls back to unstructured-only
RAG. Both honour read-your-writes consistency tokens (bounded waiter -> 503 with
``Retry-After`` + ``x-consistency``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from umd.api.deps import (
    AppContext,
    enforce_rate_limit,
    get_context,
    get_principal,
)
from umd.api.errors import ApiError
from umd.api.schemas import (
    FreshnessMeta,
    SemanticQueryRequest,
    SemanticQueryResponse,
    StructuredQueryRequest,
    StructuredQueryResponse,
)
from umd.projections.query import QueryResultHit, ScopeUnmappableError, StructuredQuery

router = APIRouter(prefix="/v1/query", tags=["query"], dependencies=[Depends(enforce_rate_limit)])


def _bounded(body: StructuredQueryRequest, ctx: AppContext) -> tuple[int, int, int]:
    """Apply bounded query-cost limits, returning ``(depth, limit, offset)``."""
    qc = ctx.settings.query_cost
    depth = min(body.max_depth if body.max_depth is not None else qc.max_depth, qc.max_depth)
    limit = min(body.limit if body.limit is not None else qc.default_limit, qc.max_limit)
    offset = body.offset if body.offset is not None else 0
    return depth, limit, offset


def _freshness_guard(ctx: AppContext, edge_derived: bool) -> Any:
    """Select the consistency guard for a read.

    Edge-derived reads (``RELATIONSHIP_EDGES`` structured queries and relationship
    semantic questions) read the ``active_semantic_edge`` store, so their token-bearing
    bounded-freshness wait and 503 behavior must be gated on the ``semantic_edges``
    ``edge_guard`` rather than only the scalar ``current_tier1`` ``query_guard``
    (P4-S1). Non-edge reads keep the scalar ``query_guard``.
    """
    if edge_derived:
        eg = ctx.extra.get("edge_guard")
        if eg is not None:
            return eg
    return ctx.consistency


def _hit(h: QueryResultHit) -> dict[str, Any]:
    return {
        "ref": h.ref,
        "kind": h.kind,
        "label": h.label,
        "predicate": h.predicate,
        "value": h.value,
        "score": h.score,
        "confidence": h.confidence,
        "source_id": h.source_id,
        "segment_id": h.segment_id,
        "provenance": h.provenance,
        "generated_by": h.generated_by,
        "capabilities": h.capabilities,
        "data": h.data,
    }


@router.post("/structured", response_model=StructuredQueryResponse)
def structured_query(
    body: StructuredQueryRequest,
    ctx: AppContext = Depends(get_context),
    _p: Any = Depends(get_principal),
) -> StructuredQueryResponse:
    depth, limit, offset = _bounded(body, ctx)
    guard = _freshness_guard(ctx, edge_derived=body.kind == "RELATIONSHIP_EDGES")
    snap = guard.ensure_read(body.consistency_token)
    try:
        page = ctx.query.structured(
            StructuredQuery(
                kind=body.kind,
                ref=body.ref,
                filters=body.filters,
                confidence_min=body.confidence_min,
                continuity_id=body.continuity_id,
                temporal_from=body.temporal_from,
                temporal_to=body.temporal_to,
                spatial=body.spatial,
                result_kind=body.result_kind,
                max_depth=depth,
                limit=limit,
                offset=offset,
            )
        )
    except ScopeUnmappableError as exc:
        # Unmappable continuity/temporal/spatial scope -> explicit RFC 7807 422
        # (never silently return unfiltered results).
        raise ApiError(str(exc), status=422, code="unmappable_scope") from exc
    except ValueError as exc:
        raise ApiError(str(exc), code="invalid_query") from exc
    return StructuredQueryResponse(
        query=page.query,
        results=[_hit(h) for h in page.results],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        result_kinds=page.result_kinds,
        provenance=page.provenance,
        bound_report=page.bound_report.model_dump(),
        freshness=FreshnessMeta(**snap.to_meta()),
    )


@router.post("/semantic", response_model=SemanticQueryResponse)
def semantic_query(
    body: SemanticQueryRequest,
    ctx: AppContext = Depends(get_context),
    _p: Any = Depends(get_principal),
) -> SemanticQueryResponse:
    guard = _freshness_guard(ctx, edge_derived=ctx.question.requires_edge_guard(body.question))
    snap = guard.ensure_read(body.consistency_token)
    answer = ctx.question.answer(body.question, body.constraints)
    return SemanticQueryResponse(
        question=answer.question,
        compiled_ops=answer.compiled_ops,
        answer=answer.answer,
        interpretation=answer.interpretation,
        confidence=answer.confidence,
        support=answer.support,
        alternatives=answer.alternatives,
        unresolved=answer.unresolved,
        contradictory=answer.contradictory,
        result_kind_labels=answer.result_kind_labels,
        provenance=answer.provenance,
        bound_report=answer.bound_report,
        freshness=FreshnessMeta(**snap.to_meta()),
    )
