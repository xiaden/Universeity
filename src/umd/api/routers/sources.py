"""Source / locator / evidence / report routes (P3-S1).

Ingest stores immutable bytes to the OCFL source store (content-addressed by
sha512), records the ``SOURCE_INGESTED`` ledger event, and returns the resulting
read-your-writes token. Media pipelines are delegated (a job is submitted); no
shell interpolation, no projection writes from this boundary.
"""

from __future__ import annotations

import base64
import io
import uuid
from contextlib import suppress
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query

from umd.api.deps import (
    AppContext,
    enforce_rate_limit,
    get_context,
    get_principal,
    get_write_principal,
)
from umd.api.errors import NotFoundError
from umd.api.pagination import offset_from, page_cursors
from umd.api.schemas import (
    EvidenceListResponse,
    EvidenceResponse,
    LocatorRangeResponse,
    SegmentListResponse,
    SegmentResponse,
    SourceDescriptorResponse,
    SourceDetailResponse,
    SourceIngestRequest,
)
from umd.storage.ocfl.store import SourceDescriptor

router = APIRouter(prefix="/v1", tags=["sources"], dependencies=[Depends(enforce_rate_limit)])


@router.post("/sources", response_model=SourceDescriptorResponse, status_code=201)
@router.post("/sources/{media_kind}", response_model=SourceDescriptorResponse, status_code=201)
def ingest_source(
    media_kind: str | None = None,
    body: SourceIngestRequest | None = None,
    _p: Any = Depends(get_write_principal),
    ctx: AppContext = Depends(get_context),
) -> SourceDescriptorResponse:
    media = body.media_kind if body is not None else (media_kind or "txt")
    original = body.original_name if body is not None else None
    work_id = body.work_id if body is not None else None
    content = (body.content if body is not None else None) or ""
    content_type = (body.content_type if body is not None else None) or "text/plain"
    source_id = (body.source_id if body is not None else None) or uuid.uuid4().hex

    stream = io.BytesIO(content.encode("utf-8"))
    manifest = ctx.source_store.put_immutable(
        stream,
        SourceDescriptor(
            logical_name=original or f"{source_id}.txt",
            media_kind=media,
            kind="source",
            content_type=content_type,
        ),
    )

    ctx.memberships.ensure_source(
        source_id=source_id,
        ocfl_ref=manifest.store_path,
        sha512=manifest.sha512,
        size_bytes=manifest.size_bytes,
        media_kind=media,
        original_name=original,
        work_id=work_id,
    )
    commit = ctx.commands.record_source_ingested(
        source_id=source_id,
        sha512=manifest.sha512,
        ocfl_ref=manifest.store_path,
        size_bytes=manifest.size_bytes,
        media_kind=media,
        work_id=work_id,
        original_name=original,
        # The ledger requires idempotency keys to be valid UUIDs; derive a stable
        # one from the source id so a retried ingest of the same source is idempotent.
        idempotency_key=uuid.uuid5(uuid.NAMESPACE_URL, f"ingest:{source_id}"),
        created_by=_p.key,
    )

    # Delegate the decomposition pipeline: submit a job (runs synchronously in-process).
    job_id = f"job-{source_id[:12]}"
    try:
        ctx.jobs.submit(
            job_id=job_id,
            source_id=source_id,
            dag_universe="base",
            work_registry={},
            request={"source_id": source_id, "media_kind": media},
        )
    except Exception:  # noqa: BLE001 - pipeline submission must not fail the ingest
        ctx.log and ctx.log.warning("job submission failed after ingest", source_id=source_id)

    return SourceDescriptorResponse(
        source_id=source_id,
        work_id=work_id,
        ocfl_ref=manifest.store_path,
        sha512=manifest.sha512,
        size_bytes=manifest.size_bytes,
        media_kind=media,
        original_name=original,
        seq=commit.seq,
        consistency_token=commit.seq,
    )


@router.get("/sources/{source_id}", response_model=SourceDetailResponse)
def get_source(
    source_id: str,
    ctx: AppContext = Depends(get_context),
    _p: Any = Depends(get_principal),
) -> SourceDetailResponse:
    try:
        rec = ctx.sources.get(source_id)
    except (ValueError, TypeError, sa.exc.DataError):  # non-UUID source id: cannot exist
        raise NotFoundError(f"unknown source {source_id}") from None
    if rec is None:
        raise NotFoundError(f"unknown source {source_id}")
    return SourceDetailResponse(
        source_id=rec.source_id,
        ocfl_ref=rec.ocfl_ref,
        sha512=rec.sha512,
        size_bytes=rec.size_bytes,
        media_kind=rec.media_kind,
        work_id=rec.work_id,
        continuity_id=getattr(rec, "continuity_id", None),
        edition_id=getattr(rec, "edition_id", None),
    )


@router.get("/sources/{source_id}/segments", response_model=SegmentListResponse)
def list_segments(
    source_id: str,
    limit: int = Query(default=20, ge=1, le=200),
    cursor: str | None = Query(default=None),
    ctx: AppContext = Depends(get_context),
    _p: Any = Depends(get_principal),
) -> SegmentListResponse:
    offset = offset_from(cursor)
    segs = ctx.segments.segments_for_source(source_id)
    total = len(segs)
    items = [
        SegmentResponse(
            segment_id=s.segment_id,
            source_id=s.source_id,
            kind=s.segment_type,
            start=getattr(s, "ordinal", None),
            locator=s.locator,
            ref=s.deterministic_key,
        )
        for s in segs[offset : offset + limit]
    ]
    next_cursor, prev_cursor = page_cursors(offset, limit, total)
    return SegmentListResponse(
        items=items, total=total, next_cursor=next_cursor, prev_cursor=prev_cursor
    )


@router.get("/segments/{segment_id}/evidence", response_model=EvidenceListResponse)
def list_segment_evidence(
    segment_id: str,
    limit: int = Query(default=20, ge=1, le=200),
    cursor: str | None = Query(default=None),
    ctx: AppContext = Depends(get_context),
    _p: Any = Depends(get_principal),
) -> EvidenceListResponse:
    offset = offset_from(cursor)
    # Resolve the segment id to its authoritative source/locator (404 when unknown),
    # then retrieve ONLY that segment's evidence via a segment-scoped indexed query —
    # never another segment's/source's evidence, never empty due to an id mismatch.
    seg = ctx.segments.resolve_segment(segment_id)
    if seg is None:
        raise NotFoundError(f"unknown segment {segment_id}")
    all_ev = ctx.evidence.get_by_segment(segment_id)
    total = len(all_ev)
    items = [
        EvidenceResponse(
            ref=str(e.id),
            locator=e.locator,
            source_id=str(e.source_id) if e.source_id else None,
            segment_id=str(e.segment_id) if e.segment_id else None,
            predicate=e.evidence_kind,
            object_ref=e.locator,
            confidence=e.confidence,
        )
        for e in all_ev[offset : offset + limit]
    ]
    next_cursor, prev_cursor = page_cursors(offset, limit, total)
    return EvidenceListResponse(
        items=items, total=total, next_cursor=next_cursor, prev_cursor=prev_cursor
    )


@router.get("/locators/{source_ref}", response_model=LocatorRangeResponse)
def get_locator_range(
    source_ref: str,
    start: int = Query(default=0, ge=0),
    length: int | None = Query(default=None, ge=1),
    ctx: AppContext = Depends(get_context),
    _p: Any = Depends(get_principal),
) -> LocatorRangeResponse:
    try:
        rep = ctx.source_store.get_range(source_ref, start, length if length else None)
    except Exception as exc:  # noqa: BLE001
        raise NotFoundError(f"locator/object not found: {source_ref}") from exc
    return LocatorRangeResponse(
        object_id=rep.object_id,
        logical_name=rep.logical_name,
        sha512=rep.sha512,
        size_bytes=rep.size_bytes,
        start=rep.start,
        end=rep.end,
        truncated=rep.truncated,
        data_b64=base64.b64encode(rep.data).decode("ascii"),
    )


@router.post("/sources/{source_id}/rerun", status_code=202)
def rerun_source(
    source_id: str,
    ctx: AppContext = Depends(get_context),
    _p: Any = Depends(get_write_principal),
) -> dict[str, Any]:
    job_id = f"job-{source_id[:12]}"
    events = ctx.jobs.events(job_id)
    ctx.jobs.rerun_source(
        source_id=source_id,
        scope="SOURCE",
        causation="api:rerun",
        dag_universe="base",
        work_registry={},
        job_id=job_id,
    )
    return {"job_id": job_id, "action": "rerun", "targets": list(events)}


@router.get("/sources/{source_id}/report")
def source_report(
    source_id: str,
    ctx: AppContext = Depends(get_context),
    _p: Any = Depends(get_principal),
) -> dict[str, Any]:
    """Per-source decomposition report (P1-S2): stages, timing, retries, versions,
    quarantines, incomplete branches and rerun causation from the operational tables. Read-only."""
    from umd.operations.reports import SourceReportBuilder

    report = SourceReportBuilder(ctx.engine).build(source_id)
    return report.to_dict()


@router.get("/sources/{source_id}/analysis")
def source_analysis(
    source_id: str,
    ctx: AppContext = Depends(get_context),
    _p: Any = Depends(get_principal),
) -> dict[str, Any]:
    job_id = f"job-{source_id[:12]}"
    status = "unknown"
    events: list[Any] = []
    with suppress(Exception):
        status = ctx.jobs.status(job_id)
        events = ctx.jobs.events(job_id)
    return {"source_id": source_id, "job_id": job_id, "status": status, "events": events}
