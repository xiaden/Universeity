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
    data = getattr(h, "data", None) or {}
    return EntityResponse(
        ref=h.ref,
        label=h.label,
        kind=h.kind,
        predicate=h.predicate,
        value=h.value,
        canonical_type=data.get("canonical_type"),
        display_label=data.get("display_label") or h.label,
        aliases=list(data.get("aliases") or []),
        state=data.get("state"),
        confidence=data.get("confidence"),
        support_refs=list(data.get("support_refs") or []),
        memberships=dict(data.get("memberships") or {}),
        # Plan T (P2-S1): surface the exact support/provenance metadata already
        # computed by QueryService._entity_hit on canonical identity hits (list,
        # by-ref, and structured ENTITY reads). Legacy CANONICAL_ENTITY fallback
        # hits carry empty dicts, preserving prior behavior.
        provenance=h.provenance,
        generated_by=h.generated_by,
        capabilities=h.capabilities,
    )


@router.get("", response_model=EntityListResponse)
def list_entities(
    limit: int = Query(default=20, ge=1, le=200),
    cursor: str | None = Query(default=None),
    name: str | None = Query(default=None, description="exact active display-label filter"),
    name_fuzzy: str | None = Query(default=None, description="case-insensitive label substring"),
    alias: str | None = Query(default=None, description="alias surface resolves its canonical"),
    work_id: str | None = Query(default=None, description="bounded work-membership filter"),
    source_id: str | None = Query(default=None, description="bounded source-membership filter"),
    continuity_id: str | None = Query(
        default=None, description="bounded continuity-membership filter"
    ),
    ctx: AppContext = Depends(get_context),
    _p: Any = Depends(get_principal),
) -> EntityListResponse:
    offset = offset_from(cursor)
    filters: dict[str, Any] = {}
    if name:
        filters["name"] = name
    if name_fuzzy:
        filters["name_fuzzy"] = name_fuzzy
    if alias:
        filters["alias"] = alias
    # Plan T (P2-S1): bounded replay-derived membership filters. A malformed
    # work_id/continuity_id surfaces as RFC 7807 ``422 unmappable_scope``.
    if work_id:
        filters["work_id"] = work_id
    if source_id:
        filters["source_id"] = source_id
    if continuity_id:
        filters["continuity_id"] = continuity_id
    page = _entities_page(ctx, filters, limit, offset)
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
    work_id: str | None = Query(default=None, description="bounded work-membership filter"),
    source_id: str | None = Query(default=None, description="bounded source-membership filter"),
    continuity_id: str | None = Query(
        default=None, description="bounded continuity-membership filter"
    ),
    ctx: AppContext = Depends(get_context),
    _p: Any = Depends(get_principal),
) -> EntityResponse:
    filters: dict[str, Any] = {"ref": ref}
    if work_id:
        filters["work_id"] = work_id
    if source_id:
        filters["source_id"] = source_id
    if continuity_id:
        filters["continuity_id"] = continuity_id
    page = _entities_page(ctx, filters, 10, 0)
    if not page.results:
        raise NotFoundError(f"unknown entity {ref} in the requested scope")
    return _entity(page.results[0])


def _entities_page(ctx: AppContext, filters: dict[str, Any], limit: int, offset: int) -> Any:
    """Run a bounded ENTITY read, mapping unmappable scope to RFC 7807 ``422``."""
    from umd.projections.query import ScopeUnmappableError

    try:
        return ctx.query.structured(
            StructuredQuery(kind="ENTITY", filters=filters, limit=limit, offset=offset)
        )
    except ScopeUnmappableError as exc:
        raise ApiError(str(exc), status=422, code="unmappable_scope") from exc


@router.post("", response_model=EntityActionResponse, status_code=201)
def create_entity(
    body: EntityCreateRequest,
    ctx: AppContext = Depends(get_context),
    _p: Any = Depends(get_write_principal),
) -> EntityActionResponse:
    """Establish a canonical via the SAME authority as resolution (Plan T P2-S3/R6).

    Routes through :class:`Resolver.establish` — the single resolution authority —
    which appends an idempotent ``EntityResolved ESTABLISH`` event (a machine rerun or
    a repeated operator call converges, never creating a duplicate canonical topology).
    The payload's display label, canonical type, aliases, memberships, support refs,
    state, authority and confidence become the canonical's identity metadata. No SQL
    ``entity`` row is fabricated (Plan N Option B); a non-UUID ref keeps ``entity_id``
    NULL on any mention rows. Locks/overrides and ``USER_OVERRIDE`` precedence are
    enforced by the shared reducer. ``authority`` must be ``operator`` or ``human``.
    """
    if body.authority not in ("operator", "human"):
        raise ApiError(
            "authority must be 'operator' or 'human'", status=422, code="invalid_authority"
        )
    display_label = body.display_label or body.label or body.ref
    metadata: dict[str, Any] = {
        "canonical_type": body.canonical_type,
        "display_label": display_label,
        "aliases": list(body.aliases),
        "support_refs": list(body.support_refs),
        "memberships": dict(body.memberships),
        "state": body.state or "CONFIRMED",
        "confidence": body.confidence if body.confidence is not None else 1.0,
        "classification": "ACCEPTED",
    }
    commit = ctx.resolver.establish(
        canonical=body.ref,
        metadata=metadata,
        reason=body.reason or "operator entity establishment",
        authority=body.authority,
        created_by=body.actor or _p.key,
    )
    return EntityActionResponse(
        entity_ref=body.ref,
        action="create",
        seq=commit.seq,
        consistency_token=commit.read_your_writes_token,
        detail={"authority": body.authority, "display_label": display_label},
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
