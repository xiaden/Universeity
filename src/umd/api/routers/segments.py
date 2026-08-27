"""Segment edit routes (P3-S1): edit / split / merge / rerun.

Edits to segments are recorded as semantic ledger events (append-only authority)
returning a read-your-writes token; performing the underlying re-extraction is a
job-rerun delegated to the job facade (never a projection write).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from umd.api.deps import AppContext, enforce_rate_limit, get_context, get_write_principal
from umd.api.errors import ApiError
from umd.api.schemas import EntityActionResponse

router = APIRouter(
    prefix="/v1/segments", tags=["segments"], dependencies=[Depends(enforce_rate_limit)]
)


def _commit_to_action(ref: str, action: str, commit: object) -> EntityActionResponse:
    return EntityActionResponse(
        entity_ref=ref,
        action=action,
        seq=int(getattr(commit, "seq", 0)),
        consistency_token=int(getattr(commit, "read_your_writes_token", getattr(commit, "seq", 0))),
    )


@router.post("/{segment_id}/edit", response_model=EntityActionResponse)
def edit_segment(
    segment_id: str,
    ref: str | None = None,
    ctx: AppContext = Depends(get_context),
    _p: object = Depends(get_write_principal),
) -> EntityActionResponse:
    commit = ctx.commands.record_correction(
        subject_ref=segment_id,
        predicate="SEGMENT",
        object_ref=ref,
        actor=getattr(_p, "key", "anon"),
        reason="api segment edit",
    )
    return _commit_to_action(segment_id, "edit", commit)


@router.post("/{segment_id}/split", response_model=EntityActionResponse)
def split_segment(
    segment_id: str,
    ctx: AppContext = Depends(get_context),
    _p: object = Depends(get_write_principal),
) -> EntityActionResponse:
    commit = ctx.commands.assert_semantic(
        predicate_code="SEGMENT_SPLIT",
        subject_ref=segment_id,
        object_ref=None,
        authority="operator",
        created_by=getattr(_p, "key", "anon"),
    )
    return _commit_to_action(segment_id, "split", commit)


@router.post("/{segment_id}/merge", response_model=EntityActionResponse)
def merge_segment(
    segment_id: str,
    ctx: AppContext = Depends(get_context),
    _p: object = Depends(get_write_principal),
) -> EntityActionResponse:
    commit = ctx.commands.assert_semantic(
        predicate_code="SEGMENT_MERGE",
        subject_ref=segment_id,
        object_ref=None,
        authority="operator",
        created_by=getattr(_p, "key", "anon"),
    )
    return _commit_to_action(segment_id, "merge", commit)


@router.post("/{segment_id}/rerun", status_code=202)
def rerun_segment(
    segment_id: str,
    ctx: AppContext = Depends(get_context),
    _p: object = Depends(get_write_principal),
) -> dict[str, object]:
    try:
        ctx.jobs.rerun_stage(
            source_id=segment_id,
            stage="LOW_LEVEL_EXTRACTION",
            scope="SOURCE",
            causation="api:segment-rerun",
            dag_universe="base",
            work_registry={},
            job_id=f"job-{segment_id[:12]}",
        )
    except Exception as exc:  # noqa: BLE001
        raise ApiError(f"segment rerun failed: {exc}", code="rerun_failed", status=409) from exc
    return {"segment_id": segment_id, "action": "rerun", "job_id": f"job-{segment_id[:12]}"}
