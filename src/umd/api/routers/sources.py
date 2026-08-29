"""Source / locator / evidence / report routes (P3-S1..P3-S4).

Ingest stores immutable bytes to the OCFL source store (content-addressed by
sha512), records the ``SOURCE_INGESTED`` ledger event, and returns the resulting
read-your-writes token. Two ingestion forms are supported (P3-S2):

* the retained **small inline-text JSON** form (``SourceIngestRequest`` with
  ``content``) for compatibility;
* a bounded **multipart streamed upload** (``file`` + descriptor form fields)
  covering text/image/audio/video/subtitle source kinds.

Bytes are stored immutably via :meth:`SourceStore.put_immutable` BEFORE dispatch.
Decomposition is delegated through :class:`JobService` with the *production*
stage registry (``ctx.work_registry``, never ``{}``). Dispatch/submission failures
are surfaced as structured RFC 7807 errors or durable failed jobs — never
swallowed (P3-S3). No projection writes and no shell interpolation happen here.
"""

from __future__ import annotations

import base64
import io
import uuid
from contextlib import suppress
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query, Request
from pydantic import ValidationError

from umd.api.deps import (
    AppContext,
    enforce_rate_limit,
    get_context,
    get_principal,
    get_write_principal,
    serialize_audits,
)
from umd.api.errors import ApiError, NotFoundError
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
from umd.storage.postgres.tables import segment as _segment_table

router = APIRouter(prefix="/v1", tags=["sources"], dependencies=[Depends(enforce_rate_limit)])


def _segment_ids_by_key(engine: sa.Engine, source_id: str) -> dict[str, str]:
    """Map ``deterministic_key -> DB segment row id`` for a committed source.

    The public segment list must expose the DB row id so the id round-trips
    through :meth:`PostgresSegmentStore.resolve_segment` and the DB-id-keyed
    evidence store (P3-S4), rather than the derived deterministic id.
    """
    with engine.connect() as conn:
        rows = conn.execute(
            sa.select(_segment_table.c.deterministic_key, _segment_table.c.id).where(
                _segment_table.c.source_id == source_id
            )
        ).fetchall()
    return {str(r.deterministic_key): str(r.id) for r in rows}


def _form_str(value: Any) -> str | None:
    """Coerce a multipart form value to ``str`` (or ``None``)."""
    return str(value) if value is not None else None


def _max_upload_bytes(ctx: AppContext) -> int:
    """The configured max_upload_bytes (0/absent disables the bound)."""
    return int(getattr(ctx.settings.limits, "max_upload_bytes", 0))


def _upload_too_large_error(max_upload: int) -> ApiError:
    """The RFC 7807 413 error shape used for every oversize-upload rejection."""
    return ApiError(
        f"upload exceeds max_upload_bytes={max_upload}",
        status=413,
        code="upload_too_large",
        retryable=False,
    )


async def _read_bounded(file: Any, max_upload: int, chunk_size: int = 1 << 16) -> bytes:
    """Stream ``file`` into memory, aborting as soon as the accumulated size
    exceeds ``max_upload`` (so an oversize upload never buffers the whole body).

    When ``max_upload`` is 0/None the bound is disabled and the whole body is read
    (legacy behaviour). Otherwise we read in chunks and raise the RFC 7807 413
    error the moment the count passes the bound, discarding the stream.
    """
    if not max_upload:
        return bytes(await file.read())
    total = 0
    chunks: list[bytes] = []
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_upload:
            raise _upload_too_large_error(max_upload)
        chunks.append(chunk)
    return b"".join(chunks)


def _coerce_body(raw: Any) -> SourceIngestRequest | None:
    """Validate the inline-JSON body (RFC 7807 422 on a malformed payload)."""
    if raw is None:
        return None
    try:
        return SourceIngestRequest.model_validate(raw)
    except ValidationError as exc:  # noqa: PERF203
        raise ApiError(
            "request validation failed",
            status=422,
            code="validation_error",
            extra={"errors": exc.errors()},
        ) from exc


def _dispatch(ctx: AppContext, *, job_id: str, source_id: str, media_kind: str) -> None:
    """Submit the real production DAG; surface dispatch failures (P3-S3).

    Submission always carries the production stage registry (never ``{}``). A
    deterministic quarantine is surfaced as a structured 422; any other dispatch
    backend failure is a structured, retryable 500 — never swallowed.
    """
    from umd.jobs.stage_execution import StageQuarantinedError

    try:
        ctx.jobs.submit(
            job_id=job_id,
            source_id=source_id,
            dag_universe="base",
            work_registry=ctx.work_registry,
            request={"source_id": source_id, "media_kind": media_kind},
        )
    except StageQuarantinedError as exc:
        raise ApiError(
            str(exc),
            status=422,
            code="stage_quarantined",
            retryable=False,
        ) from exc
    except Exception as exc:  # noqa: BLE001 - never swallow dispatch failures
        raise ApiError(
            f"job dispatch failed: {exc}",
            status=500,
            code="dispatch_failed",
            retryable=True,
        ) from exc


def _submit_source(
    ctx: AppContext,
    *,
    media_kind: str,
    original_name: str | None,
    work_id: str | None,
    content: bytes,
    content_type: str,
    source_id: str,
    key: str,
) -> SourceDescriptorResponse:
    """Store bytes immutably, record the source, and dispatch the production DAG."""
    # Bounded upload enforcement (P3-S2): reject oversize payloads up-front with a
    # structured RFC 7807 error before any storage side effect. For the inline-JSON
    # / any already-buffered path this is a final backstop — the multipart path
    # already pre-checks Content-Length and aborts the streaming read early.
    max_upload = _max_upload_bytes(ctx)
    if content and max_upload and len(content) > max_upload:
        raise _upload_too_large_error(max_upload)

    stream = io.BytesIO(content or b"")
    manifest = ctx.source_store.put_immutable(
        stream,
        SourceDescriptor(
            logical_name=original_name or f"{source_id}.txt",
            media_kind=media_kind,
            kind="source",
            content_type=content_type,
        ),
    )

    # An omitted work_id starts a new work, matching the application ingestion
    # contract. Explicit IDs remain strict references to an existing work.
    effective_work_id = work_id if work_id is not None else uuid.uuid4().hex
    if work_id is None:
        ctx.memberships.ensure_work(
            work_id=effective_work_id,
            title=original_name or f"{source_id}.txt",
            work_type=media_kind,
        )

    ctx.memberships.ensure_source(
        source_id=source_id,
        ocfl_ref=manifest.object_id,
        sha512=manifest.sha512,
        size_bytes=manifest.size_bytes,
        media_kind=media_kind,
        original_name=original_name,
        work_id=effective_work_id,
    )
    commit = ctx.commands.record_source_ingested(
        source_id=source_id,
        sha512=manifest.sha512,
        ocfl_ref=manifest.object_id,
        size_bytes=manifest.size_bytes,
        media_kind=media_kind,
        work_id=effective_work_id,
        original_name=original_name,
        # The ledger requires idempotency keys to be valid UUIDs; derive a stable
        # one from the source id so a retried ingest of the same source is idempotent.
        idempotency_key=uuid.uuid5(uuid.NAMESPACE_URL, f"ingest:{source_id}"),
        created_by=key,
    )

    # Delegate the decomposition pipeline: submit the real ordered DAG.
    job_id = f"job-{source_id[:12]}"
    _dispatch(ctx, job_id=job_id, source_id=source_id, media_kind=media_kind)

    return SourceDescriptorResponse(
        source_id=source_id,
        work_id=effective_work_id,
        ocfl_ref=manifest.object_id,
        sha512=manifest.sha512,
        size_bytes=manifest.size_bytes,
        media_kind=media_kind,
        original_name=original_name,
        seq=commit.seq,
        consistency_token=commit.seq,
    )


@router.post("/sources", response_model=SourceDescriptorResponse, status_code=201)
@router.post("/sources/{media_kind}", response_model=SourceDescriptorResponse, status_code=201)
async def ingest_source(
    request: Request,
    media_kind: str | None = None,
    _p: Any = Depends(get_write_principal),
    ctx: AppContext = Depends(get_context),
) -> SourceDescriptorResponse:
    """Ingest a source via inline JSON (compat) or a bounded multipart upload."""
    ctype = (request.headers.get("content-type") or "").lower()
    if ctype.startswith("multipart/form-data"):
        # Reject oversize uploads up-front from the declared Content-Length, BEFORE
        # parsing the multipart body. The header covers the whole request (incl.
        # multipart framing overhead), so it is a conservative early rejection; the
        # exact file-size bound is enforced again by the bounded streamed read below.
        max_upload = _max_upload_bytes(ctx)
        declared = request.headers.get("content-length")
        if max_upload and declared:
            try:
                declared_size = int(declared)
            except ValueError:  # non-numeric length -> no reliable early signal
                declared_size = -1
            if declared_size > max_upload:
                raise _upload_too_large_error(max_upload)
        form = await request.form()
        file: Any = form.get("file")
        if file is None or not hasattr(file, "read"):
            raise ApiError(
                "multipart upload requires a 'file' part", status=422, code="missing_file"
            )
        data = await _read_bounded(file, max_upload)
        return _submit_source(
            ctx,
            media_kind=_form_str(form.get("media_kind")) or media_kind or "txt",
            original_name=_form_str(form.get("original_name")),
            work_id=_form_str(form.get("work_id")),
            content=data,
            content_type=_form_str(form.get("content_type"))
            or getattr(file, "content_type", None)
            or "application/octet-stream",
            source_id=_form_str(form.get("source_id")) or uuid.uuid4().hex,
            key=_p.key,
        )

    body = _coerce_body(await request.json())
    media = body.media_kind if body is not None else (media_kind or "txt")
    original = body.original_name if body is not None else None
    work_id = body.work_id if body is not None else None
    content = (body.content if body is not None else None) or ""
    content_type = (body.content_type if body is not None else None) or "text/plain"
    source_id = (body.source_id if body is not None else None) or uuid.uuid4().hex
    return _submit_source(
        ctx,
        media_kind=media,
        original_name=original,
        work_id=work_id,
        content=content.encode("utf-8"),
        content_type=content_type,
        source_id=source_id,
        key=_p.key,
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
    ids_by_key = _segment_ids_by_key(ctx.engine, source_id)
    items = [
        SegmentResponse(
            segment_id=ids_by_key.get(s.deterministic_key, s.segment_id),
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
    ctx.jobs.rerun_source(
        source_id=source_id,
        scope="SOURCE",
        causation="api:rerun",
        dag_universe="base",
        work_registry=ctx.work_registry,
        job_id=job_id,
    )
    return {
        "job_id": job_id,
        "action": "rerun",
        "targets": serialize_audits(ctx.jobs.events(job_id)),
    }


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
    """Expose REAL durable stage state (P3-S4): status, operational events, and
    per-stage attempts/states from the durable job store — never fake completion."""
    job_id = f"job-{source_id[:12]}"
    status = "unknown"
    events: list[Any] = []
    stages: list[dict[str, Any]] = []
    with suppress(Exception):
        status = ctx.jobs.status(job_id)
        events = ctx.jobs.events(job_id)
        store = ctx.extra["job_store"]
        stages = [
            {
                "stage": s.stage_name,
                "status": s.status,
                "attempts": s.attempts,
            }
            for s in store.stage_states(job_id)
        ]
    return {
        "source_id": source_id,
        "job_id": job_id,
        "status": status,
        "events": serialize_audits(events),
        "stages": stages,
    }
