"""Job routes (P3-S1): status / events / cancel / retry."""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Depends

from umd.api.deps import (
    AppContext,
    enforce_rate_limit,
    get_context,
    get_principal,
    get_write_principal,
    serialize_audits,
)
from umd.api.errors import ApiError, NotFoundError
from umd.api.schemas import JobActionResponse, JobResponse

router = APIRouter(prefix="/v1/jobs", tags=["jobs"], dependencies=[Depends(enforce_rate_limit)])


def _job_response(rec: object, job_id: str, *, status: str | None = None) -> JobResponse:
    return JobResponse(
        id=job_id,
        source_id=getattr(rec, "source_id", None),
        dag_universe=getattr(rec, "dag_universe", "base"),
        status=status or getattr(rec, "status", "unknown"),
        request=dict(getattr(rec, "request", {}) or {}),
        cancelled_stages=list(getattr(rec, "cancelled_stages", []) or []),
        error=getattr(rec, "error", None),
    )


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    ctx: AppContext = Depends(get_context),
    _p: object = Depends(get_principal),
) -> JobResponse:
    rec = ctx.extra["job_store"].get(job_id)
    if rec is None:
        raise NotFoundError(f"unknown job {job_id}")
    # Production callbacks commit stage_run rows asynchronously. Derive the
    # externally visible aggregate status from those authoritative rows rather
    # than returning the submission-time RUNNING snapshot from the job table.
    return _job_response(rec, job_id, status=ctx.jobs.status(job_id))


@router.get("/{job_id}/events")
def job_events(
    job_id: str,
    ctx: AppContext = Depends(get_context),
    _p: object = Depends(get_principal),
) -> list[Any]:
    try:
        return cast(list[Any], serialize_audits(ctx.jobs.events(job_id)))
    except Exception as exc:  # noqa: BLE001
        raise NotFoundError(f"unknown job {job_id}") from exc


@router.post("/{job_id}/cancel", response_model=JobActionResponse)
def cancel_job(
    job_id: str,
    ctx: AppContext = Depends(get_context),
    _p: object = Depends(get_write_principal),
) -> JobActionResponse:
    try:
        ctx.jobs.cancel(job_id=job_id, stage=None, reason="api cancel")
    except KeyError as exc:
        raise NotFoundError(f"unknown job {job_id}") from exc
    return JobActionResponse(job_id=job_id, action="cancel", targets=[])


@router.post("/{job_id}/retry", response_model=JobActionResponse)
def retry_job(
    job_id: str,
    ctx: AppContext = Depends(get_context),
    _p: object = Depends(get_write_principal),
) -> JobActionResponse:
    try:
        ctx.jobs.retry(job_id=job_id, work_registry=ctx.work_registry, dag_universe="base")
    except KeyError as exc:
        raise NotFoundError(f"unknown job {job_id}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ApiError(f"job retry failed: {exc}", code="retry_failed", status=409) from exc
    return JobActionResponse(job_id=job_id, action="retry", targets=[])
