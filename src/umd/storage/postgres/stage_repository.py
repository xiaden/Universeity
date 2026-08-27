"""Stage-run claim + job-run audit (P3-S3).

Implements two binding contracts:

* ``StageRunRepository.claim(idempotency_key, manifest) -> StageRunClaim`` —
  PostgreSQL ``UNIQUE(idempotency_key)`` is the authoritative dedup gate; a
  handler checks the claim BEFORE any side effects, and a duplicate key returns
  ``already_exists`` instead of a second authoritative completion.
* ``JobRunAudit.record(attempt) -> JobAuditRecord`` — a separate operational
  audit stream (``job_run_audit`` table) that is NOT semantic replay input
  (excluded from Tier-0 per the DD's projector policy).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa

from umd.storage.postgres.tables import metadata as db_meta

_run_t = db_meta.tables["stage_run"]
_audit_t = db_meta.tables["job_run_audit"]

#: PostgreSQL-dialect insert so ``on_conflict_do_nothing`` type-checks cleanly.
pg_insert = sa.dialects.postgresql.insert

CLAIMED = "claimed"
ALREADY_EXISTS = "already_exists"


class StageRunManifest:
    """Input manifest for a stage run claim."""

    __slots__ = (
        "job_id",
        "stage_name",
        "source_id",
        "segment_id",
        "input_manifest",
        "config_digest",
    )

    def __init__(
        self,
        *,
        stage_name: str,
        job_id: str | None = None,
        source_id: str | None = None,
        segment_id: str | None = None,
        input_manifest: dict[str, Any] | None = None,
        config_digest: str | None = None,
    ) -> None:
        self.stage_name = stage_name
        self.job_id = job_id
        self.source_id = source_id
        self.segment_id = segment_id
        self.input_manifest = input_manifest or {}
        self.config_digest = config_digest


class StageRunClaim:
    """Outcome of :meth:`StageRunRepository.claim`."""

    __slots__ = ("status", "id", "idempotency_key", "stage_name", "job_id")

    def __init__(
        self,
        *,
        status: str,
        idempotency_key: str,
        id: str | None = None,
        stage_name: str | None = None,
        job_id: str | None = None,
    ) -> None:
        self.status = status
        self.id = id
        self.idempotency_key = idempotency_key
        self.stage_name = stage_name
        self.job_id = job_id

    @property
    def won(self) -> bool:
        return self.status == CLAIMED

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"StageRunClaim(status={self.status!r}, idempotency_key={self.idempotency_key!r})"


class StageRunRepository:
    """Claims stage runs; ``UNIQUE(idempotency_key)`` is authoritative."""

    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    def claim(self, idempotency_key: str, manifest: StageRunManifest) -> StageRunClaim:
        """Claim a stage run atomically; ``UNIQUE(idempotency_key)`` is authority.

        A handler checks the claim before any side effects: the first caller wins
        (``status=claimed``, ``won=True``) and any later submission of the same
        key returns the pre-existing claim (``status=already_exists``, same id)
        rather than a second authoritative completion. A concurrent same-key
        claim is deduplicated via ``ON CONFLICT DO NOTHING``.

        :param idempotency_key: opaque idempotency key for the stage run.
        :param manifest: input manifest describing the run to claim.
        :return: a :class:`StageRunClaim` with ``status``/``won`` and the id.
        """
        key = str(idempotency_key)
        with self._engine.begin() as conn:
            rid = uuid.uuid4().hex
            inserted = conn.execute(
                pg_insert(_run_t)
                .values(
                    id=rid,
                    idempotency_key=key,
                    job_id=manifest.job_id,
                    stage_name=manifest.stage_name,
                    source_id=manifest.source_id,
                    segment_id=manifest.segment_id,
                    status="claimed",
                    input_manifest=manifest.input_manifest,
                    artifact_refs=[],
                    config_digest=manifest.config_digest,
                )
                .on_conflict_do_nothing()
                .returning(_run_t.c.id)
            )
            if inserted.scalar() is None:
                # Lost the dedup race to a concurrent same-key claim: return the
                # pre-existing claim (same id) instead of surfacing an
                # IntegrityError from UNIQUE(idempotency_key). The winning row
                # must exist (a DO-NOTHING conflict implies it was committed).
                existing = conn.execute(
                    sa.select(_run_t).where(_run_t.c.idempotency_key == key)
                ).first()
                if existing is None:  # pragma: no cover - defensive
                    raise RuntimeError(
                        f"idempotency key {key} conflicted but has no committed stage run"
                    )
                return StageRunClaim(
                    status=ALREADY_EXISTS,
                    idempotency_key=key,
                    id=existing.id.hex,
                    stage_name=existing.stage_name,
                    job_id=existing.job_id,
                )
            return StageRunClaim(
                status=CLAIMED,
                idempotency_key=key,
                id=rid,
                stage_name=manifest.stage_name,
                job_id=manifest.job_id,
            )


class JobAuditAttempt:
    """An operational job-run audit placement (independent of semantic replay)."""

    __slots__ = (
        "job_id",
        "stage_name",
        "action",
        "attempt",
        "status",
        "details",
        "started_at",
        "finished_at",
    )

    def __init__(
        self,
        *,
        job_id: str,
        stage_name: str,
        action: str,
        attempt: int = 1,
        status: str | None = None,
        details: dict[str, Any] | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        self.job_id = job_id
        self.stage_name = stage_name
        self.action = action
        self.attempt = attempt
        self.status = status
        self.details = details or {}
        self.started_at = started_at
        self.finished_at = finished_at


class JobAuditRecord:
    """A recorded job-run audit row."""

    __slots__ = ("id", "job_id", "stage_name", "action", "attempt", "status", "created_at")

    def __init__(
        self,
        *,
        id: str,
        job_id: str,
        stage_name: str,
        action: str,
        attempt: int,
        status: str | None,
        created_at: datetime,
    ) -> None:
        self.id = id
        self.job_id = job_id
        self.stage_name = stage_name
        self.action = action
        self.attempt = attempt
        self.status = status
        self.created_at = created_at


class JobRunAudit:
    """Operational audit stream — separate table, not semantic replay input."""

    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    def record(self, attempt: JobAuditAttempt) -> JobAuditRecord:
        """Write an operational job-run audit row (separate from semantic replay).

        Appends to the ``job_run_audit`` table (NOT ``semantic_event``), so job
        audit never inflates or feeds semantic Tier-0 replay. Ids are normalized
        to hex strings.

        :param attempt: the :class:`JobAuditAttempt` to record.
        :return: the persisted :class:`JobAuditRecord` with generated id and
            server ``created_at``.
        """
        with self._engine.begin() as conn:
            rid = uuid.uuid4().hex
            res = conn.execute(
                _audit_t.insert()
                .values(
                    id=rid,
                    job_id=attempt.job_id,
                    stage_name=attempt.stage_name,
                    action=attempt.action,
                    attempt=attempt.attempt,
                    status=attempt.status,
                    details=attempt.details,
                    started_at=attempt.started_at,
                    finished_at=attempt.finished_at,
                )
                .returning(_audit_t.c.created_at)
            )
            created_at = res.scalar() or datetime.now()
            return JobAuditRecord(
                id=rid,
                job_id=attempt.job_id,
                stage_name=attempt.stage_name,
                action=attempt.action,
                attempt=attempt.attempt,
                status=attempt.status,
                created_at=created_at,
            )
