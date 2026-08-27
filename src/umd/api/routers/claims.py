"""Claim routes (P3-S1): create / override / invalidate / provenance.

Mutations record semantic ledger events and return read-your-writes tokens;
provenance is served from the query-only audit service (never a projection write).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from umd.api.deps import (
    AppContext,
    enforce_rate_limit,
    get_context,
    get_principal,
    get_write_principal,
)
from umd.api.errors import NotFoundError
from umd.api.schemas import (
    ClaimCreateRequest,
    ClaimMutationRequest,
    ClaimResponse,
    ProvenanceResponse,
)

router = APIRouter(prefix="/v1/claims", tags=["claims"], dependencies=[Depends(enforce_rate_limit)])


@router.post("", response_model=ClaimResponse, status_code=201)
def create_claim(
    body: ClaimCreateRequest,
    ctx: AppContext = Depends(get_context),
    _p: Any = Depends(get_write_principal),
) -> ClaimResponse:
    commit = ctx.commands.assert_semantic(
        predicate_code=body.predicate_code,
        subject_ref=body.subject_ref,
        object_ref=body.object_ref,
        confidence=body.confidence,
        scope=body.scope,
        support_refs=body.support_refs,
        authority="operator",
        actor=_p.key,
    )
    return ClaimResponse(
        ref=body.subject_ref,
        predicate=body.predicate_code,
        subject=body.subject_ref,
        object=body.object_ref,
        confidence=body.confidence,
        seq=commit.seq,
        consistency_token=commit.seq,
    )


@router.post("/{ref}/override", response_model=ClaimResponse)
def override_claim(
    ref: str,
    body: ClaimMutationRequest,
    ctx: AppContext = Depends(get_context),
    _p: Any = Depends(get_write_principal),
) -> ClaimResponse:
    commit = ctx.commands.record_override(
        subject_ref=ref,
        predicate="CANONICAL_ENTITY",
        object_ref=None,
        actor=_p.key,
        evidence=body.refs,
        reason=body.reason or body.cause,
    )
    return ClaimResponse(ref=ref, seq=commit.seq, consistency_token=commit.seq)


@router.post("/{ref}/invalidate", response_model=ClaimResponse)
def invalidate_claim(
    ref: str,
    body: ClaimMutationRequest,
    ctx: AppContext = Depends(get_context),
    _p: Any = Depends(get_write_principal),
) -> ClaimResponse:
    commit = ctx.commands.invalidate(
        subject_ref=ref,
        predicate="CANONICAL_ENTITY",
        cause=body.cause,
        scope=body.scope or "GLOBAL",
        stage=body.stage,
        refs=body.refs,
    )
    return ClaimResponse(ref=ref, seq=commit.seq, consistency_token=commit.seq)


@router.get("/{ref}/provenance", response_model=ProvenanceResponse)
def claim_provenance(
    ref: str,
    ctx: AppContext = Depends(get_context),
    _p: Any = Depends(get_principal),
) -> ProvenanceResponse:
    try:
        exp = ctx.audit.explain(ref)
    except Exception as exc:  # noqa: BLE001
        raise NotFoundError(f"no provenance for {ref}") from exc
    return ProvenanceResponse(
        subject=ref,
        current=getattr(exp, "current", None),
        prior=getattr(exp, "prior", None),
        actor=getattr(exp, "actor", None),
        change_cause=getattr(exp, "change_cause", None),
        history=[h for h in (getattr(exp, "history", None) or [])],
    )
