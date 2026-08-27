"""Durable Postgres job repository (P1-S3).

Implements the :class:`JobStore` contract against the merged ``job`` +
``stage_run`` + ``job_run_audit`` tables. Job aggregate status, cancelled
stages and error live in the ``job`` table; per-stage observability derives from
``stage_run``; the event/audit stream derives from ``job_run_audit``.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from umd.jobs.job import JobRecord, JobStatus, StageState
from umd.storage.postgres.stage_repository import JobAuditRecord
from umd.storage.postgres.tables import metadata as db_meta

_job_t = db_meta.tables["job"]
_run_t = db_meta.tables["stage_run"]
_audit_t = db_meta.tables["job_run_audit"]

#: PostgreSQL-dialect insert so ``on_conflict_do_nothing`` type-checks cleanly.
pg_insert = sa.dialects.postgresql.insert


class PostgresJobRepository:
    """JobStore backed by the Postgres ``job``/``stage_run``/``job_run_audit``."""

    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    # -- JobStore ----------------------------------------------------------

    def create(
        self,
        *,
        job_id: str,
        source_id: str | None,
        dag_universe: str,
        request: dict[str, Any] | None = None,
    ) -> JobRecord:
        with self._engine.begin() as conn:
            conn.execute(
                pg_insert(_job_t)
                .values(
                    id=job_id,
                    source_id=source_id,
                    dag_universe=dag_universe,
                    status=JobStatus.PENDING,
                    request=request or {},
                )
                .on_conflict_do_nothing()
            )
        rec = self.get(job_id)
        if rec is None:  # pragma: no cover - defensive
            raise RuntimeError(f"job {job_id} could not be created")
        return rec

    def update_status(self, job_id: str, status: str, error: str | None = None) -> JobRecord:
        vals = {"status": status}
        if error is not None:
            vals["error"] = error
        with self._engine.begin() as conn:
            conn.execute(_job_t.update().where(_job_t.c.id == job_id).values(**vals))
        return self.get(job_id) or JobRecord(job_id, None, "", status)

    def set_cancelled_stages(self, job_id: str, stages: set[str]) -> JobRecord:
        with self._engine.begin() as conn:
            conn.execute(
                _job_t.update().where(_job_t.c.id == job_id).values(cancelled_stages=list(stages))
            )
        return self.get(job_id) or JobRecord(job_id, None, "", JobStatus.CANCELLED)

    def get(self, job_id: str) -> JobRecord | None:
        with self._engine.connect() as conn:
            row = conn.execute(sa.select(_job_t).where(_job_t.c.id == job_id)).first()
        if row is None:
            return None
        return JobRecord(
            id=row.id,
            # Canonical dashed form: round-trips the source_id exactly as
            # submitted, so rerun/retry rebuild the SAME stage idempotency key
            # (a hex form here would change the key and duplicate stage_run rows).
            source_id=str(row.source_id) if row.source_id else None,
            dag_universe=row.dag_universe,
            status=row.status,
            request=row.request or {},
            cancelled_stages=set(row.cancelled_stages or []),
            error=row.error,
        )

    def stage_states(self, job_id: str) -> list[StageState]:
        with self._engine.connect() as conn:
            run_rows = conn.execute(
                sa.select(
                    _run_t.c.stage_name,
                    _run_t.c.status,
                    _run_t.c.idempotency_key,
                ).where(_run_t.c.job_id == job_id)
            ).fetchall()
            attempt_rows = conn.execute(
                sa.select(_audit_t.c.stage_name, sa.func.count())
                .where((_audit_t.c.job_id == job_id) & (_audit_t.c.action.in_(["start", "retry"])))
                .group_by(_audit_t.c.stage_name)
            ).fetchall()
        attempts = {r[0]: int(r[1]) for r in attempt_rows}
        return [
            StageState(
                stage_name=r.stage_name,
                status=r.status,
                idempotency_key=str(r.idempotency_key),
                attempts=attempts.get(r.stage_name, 1),
            )
            for r in run_rows
        ]

    def audit_records(self, job_id: str) -> list[Any]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.select(_audit_t)
                .where(_audit_t.c.job_id == job_id)
                .order_by(_audit_t.c.created_at)
            ).fetchall()
        return [
            JobAuditRecord(
                id=r.id.hex,
                job_id=r.job_id,
                stage_name=r.stage_name,
                action=r.action,
                attempt=r.attempt,
                status=r.status,
                created_at=r.created_at,
            )
            for r in rows
        ]

    def record_stage(self, _job_id: str, _state: StageState) -> None:
        # stage status is authoritative in the ``stage_run`` table written by the
        # executor; this is a no-op so the durable runner's observation hook stays
        # uniform across backends.
        return None


__all__ = ["PostgresJobRepository"]
