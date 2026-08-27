"""Audit / provenance routes (P3-S1)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from umd.api.deps import AppContext, enforce_rate_limit, get_context, get_principal
from umd.api.errors import NotFoundError
from umd.api.schemas import AuditResponse

router = APIRouter(prefix="/v1/audit", tags=["audit"], dependencies=[Depends(enforce_rate_limit)])


@router.get("/{subject}", response_model=AuditResponse)
def audit_subject(
    subject: str,
    as_of: datetime | None = Query(default=None),
    causation: int | None = Query(default=None, ge=0),
    correlation: str | None = Query(default=None),
    ctx: AppContext = Depends(get_context),
    _p: object = Depends(get_principal),
) -> AuditResponse:
    try:
        exp = ctx.audit.explain(subject, as_of=as_of, causation=causation, correlation=correlation)
    except Exception as exc:  # noqa: BLE001
        raise NotFoundError(f"no audit trail for {subject}") from exc
    return AuditResponse(subject=subject, explanation=exp.to_dict())
