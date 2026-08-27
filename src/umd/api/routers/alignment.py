"""Alignment routes (P3-S1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from umd.api.deps import AppContext, enforce_rate_limit, get_context, get_write_principal
from umd.api.schemas import EntityActionResponse

router = APIRouter(
    prefix="/v1/alignment", tags=["alignment"], dependencies=[Depends(enforce_rate_limit)]
)


@router.post("", response_model=EntityActionResponse, status_code=201)
def record_alignment(
    left_ref: str = Query(..., description="left entity/segment ref"),
    right_ref: str = Query(..., description="right entity/segment ref"),
    alignment_type: str = Query(default="EQUIVALENT"),
    ctx: AppContext = Depends(get_context),
    _p: object = Depends(get_write_principal),
) -> EntityActionResponse:
    try:
        commit = ctx.commands.record_alignment(
            left_ref=left_ref,
            right_ref=right_ref,
            alignment_type=alignment_type,
            method="api",
            confidence=1.0,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=409, detail=f"alignment failed: {exc}") from exc
    return EntityActionResponse(
        entity_ref=f"{left_ref}~{right_ref}",
        action=alignment_type,
        seq=int(getattr(commit, "seq", 0)),
        consistency_token=int(getattr(commit, "read_your_writes_token", getattr(commit, "seq", 0))),
    )
