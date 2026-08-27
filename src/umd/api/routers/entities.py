"""Entity routes (P3-S1): descriptors, merge/split/lock/unlock.

All mutations go through the semantic command handler (SemanticLedger.append) and
return read-your-writes tokens; no route writes any projection store.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from umd.api.deps import (
    AppContext,
    enforce_rate_limit,
    get_context,
    get_principal,
    get_write_principal,
)
from umd.api.errors import ApiError, NotFoundError
from umd.api.pagination import offset_from, page_cursors
from umd.api.schemas import (
    EntityActionResponse,
    EntityCreateRequest,
    EntityListResponse,
    EntityResponse,
)
from umd.projections.query import StructuredQuery
from umd.resolution.resolution import ResolutionRejected

router = APIRouter(
    prefix="/v1/entities", tags=["entities"], dependencies=[Depends(enforce_rate_limit)]
)


def _entity(h: Any) -> EntityResponse:
    return EntityResponse(
        ref=h.ref,
        label=h.label,
        kind=h.kind,
        predicate=h.predicate,
        value=h.value,
    )


@router.get("", response_model=EntityListResponse)
def list_entities(
    limit: int = Query(default=20, ge=1, le=200),
    cursor: str | None = Query(default=None),
    ctx: AppContext = Depends(get_context),
    _p: Any = Depends(get_principal),
) -> EntityListResponse:
    offset = offset_from(cursor)
    page = ctx.query.structured(StructuredQuery(kind="ENTITY", limit=limit, offset=offset))
    next_cursor, prev_cursor = page_cursors(offset, limit, page.total)
    return EntityListResponse(
        items=[_entity(h) for h in page.results],
        total=page.total,
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
    )


@router.get("/{ref}", response_model=EntityResponse)
def get_entity(
    ref: str,
    ctx: AppContext = Depends(get_context),
    _p: Any = Depends(get_principal),
) -> EntityResponse:
    page = ctx.query.structured(StructuredQuery(kind="ENTITY", filters={"ref": ref}, limit=10))
    if not page.results:
        raise NotFoundError(f"unknown entity {ref}")
    return _entity(page.results[0])


@router.post("", response_model=EntityActionResponse, status_code=201)
def create_entity(
    body: EntityCreateRequest,
    ctx: AppContext = Depends(get_context),
    _p: Any = Depends(get_write_principal),
) -> EntityActionResponse:
    commit = ctx.commands.assert_semantic(
        predicate_code="CANONICAL_ENTITY",
        subject_ref=body.ref,
        object_ref=body.label or body.ref,
        authority="operator",
        actor=_p.key,
    )
    return EntityActionResponse(
        entity_ref=body.ref, action="create", seq=commit.seq, consistency_token=commit.seq
    )


@router.post("/{ref}/lock", response_model=EntityActionResponse)
def lock_entity(
    ref: str,
    ctx: AppContext = Depends(get_context),
    _p: Any = Depends(get_write_principal),
) -> EntityActionResponse:
    commit = ctx.commands.lock(entity_ref=ref, predicate="LOCK", actor=_p.key, reason="api lock")
    return EntityActionResponse(
        entity_ref=ref, action="lock", seq=commit.seq, consistency_token=commit.seq
    )


@router.post("/{ref}/unlock", response_model=EntityActionResponse)
def unlock_entity(
    ref: str,
    ctx: AppContext = Depends(get_context),
    _p: Any = Depends(get_write_principal),
) -> EntityActionResponse:
    commit = ctx.commands.unlock(
        entity_ref=ref, predicate="LOCK", actor=_p.key, reason="api unlock"
    )
    return EntityActionResponse(
        entity_ref=ref, action="unlock", seq=commit.seq, consistency_token=commit.seq
    )


@router.post("/{ref}/merge", response_model=EntityActionResponse)
def merge_entity(
    ref: str,
    target_entity_ref: str,
    ctx: AppContext = Depends(get_context),
    _p: Any = Depends(get_write_principal),
) -> EntityActionResponse:
    # Route v1 MERGE through the full Phase-1 Resolver (ledger EntityResolved event
    # append + mention rebind). This is the SAME resolution authority as the service
    # layer — never a second semantic authority, never a projection write.
    try:
        commit = ctx.resolver.merge(
            target_entity=target_entity_ref,
            merged_refs=[ref],
            assignments={ref: target_entity_ref},
            reason="api merge",
        )
    except ResolutionRejected as exc:
        raise ApiError(str(exc), status=422, code="invalid_merge") from exc
    return EntityActionResponse(
        entity_ref=ref,
        action="merge",
        seq=commit.seq,
        consistency_token=commit.seq,
        detail={"target_entity_ref": target_entity_ref},
    )


@router.post("/{ref}/split", response_model=EntityActionResponse)
def split_entity(
    ref: str,
    targets: list[str] = Query(default=[]),
    ctx: AppContext = Depends(get_context),
    _p: Any = Depends(get_write_principal),
) -> EntityActionResponse:
    if not targets:
        raise ApiError(
            "split requires at least one target entity ref", status=422, code="invalid_split"
        )
    # Route v1 SPLIT through the full Phase-1 Resolver: deterministic split-time
    # enumeration -> ReferenceRebound emission + mention rebinding + ambiguity
    # quarantine. SPLIT never deletes; history stays append-only.
    try:
        outcome = ctx.resolver.split(entity=ref, targets=targets, reason="api split")
    except ResolutionRejected as exc:
        raise ApiError(str(exc), status=422, code="invalid_split") from exc
    commit = outcome.commit
    return EntityActionResponse(
        entity_ref=ref,
        action="split",
        seq=commit.seq,
        consistency_token=commit.seq,
        detail={
            "targets": targets,
            "assignments": outcome.plan.assignments,
            "quarantined_refs": outcome.plan.quarantined_refs,
        },
    )
