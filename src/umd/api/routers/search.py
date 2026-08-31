"""Exact/fuzzy/hybrid search boundary (P3-S2/S3).

Wires :class:`SearchService` (exact/fuzzy/hybrid) behind a typed REST schema. Each
result carries its result-kind label; hybrid fuses exact + vector when a vector
backend is available and degrades honestly otherwise. Honours read-your-writes
consistency tokens over the ``search`` projection.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from umd.api.deps import AppContext, enforce_rate_limit, get_context
from umd.api.pagination import page_cursors
from umd.api.schemas import FreshnessMeta, SearchHit, SearchRequest, SearchResponse
from umd.projections.search import SearchFilters

router = APIRouter(prefix="/v1/search", tags=["search"], dependencies=[Depends(enforce_rate_limit)])


@router.post("", response_model=SearchResponse)
def search(body: SearchRequest, ctx: AppContext = Depends(get_context)) -> SearchResponse:
    qc = ctx.settings.query_cost
    limit = min(body.limit if body.limit is not None else qc.default_limit, qc.max_limit)
    offset = body.offset if body.offset is not None else 0
    filters = SearchFilters(
        source_id=body.source_id,
        work_id=body.work_id,
        continuity_id=body.continuity_id,
        segment_id=body.segment_id,
        entity_ref=body.entity_ref,
        kind=body.kind,
        language=body.language,
        locator_prefix=body.locator_prefix,
    )
    snap = ctx.extra["search_guard"].ensure_read(body.consistency_token)
    if body.mode == "exact":
        page = ctx.search.exact(body.query, filters, limit=limit, offset=offset)
    elif body.mode == "fuzzy":
        page = ctx.search.fuzzy(body.query, filters, limit=limit, offset=offset)
    else:
        page = ctx.search.hybrid(body.query, filters, limit=limit, offset=offset)
    hits = [
        SearchHit(
            ref=h.ref,
            kind=h.kind,
            text=h.text,
            source_id=h.source_id,
            segment_id=h.segment_id,
            entity_ref=h.entity_ref,
            score=h.score,
            exact_score=h.exact_score,
            vector_score=h.vector_score,
            label=h.label,
        )
        for h in page.hits
    ]
    next_cursor, prev_cursor = page_cursors(offset, limit, page.total)
    return SearchResponse(
        engine=page.engine,
        vector_backend=page.vector_backend,
        hits=hits,
        total=page.total,
        limit=limit,
        offset=offset,
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
        freshness=FreshnessMeta(**snap.to_meta()),
    )
