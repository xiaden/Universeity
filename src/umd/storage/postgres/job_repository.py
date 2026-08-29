"""Durable Postgres job repository (P1-S3).

Implements the :class:`JobStore` contract against the merged ``job`` +
``stage_run`` + ``job_run_audit`` tables. Job aggregate status, cancelled
stages and error live in the ``job`` table; per-stage observability derives from
``stage_run``; the event/audit stream derives from ``job_run_audit``.
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa

from umd.jobs.dag import STAGE_DEPENDENCIES
from umd.jobs.job import JobRecord, JobStatus, StageState
from umd.storage.postgres.stage_repository import JobAuditRecord
from umd.storage.postgres.tables import metadata as db_meta

_job_t = db_meta.tables["job"]
_run_t = db_meta.tables["stage_run"]
_audit_t = db_meta.tables["job_run_audit"]

#: PostgreSQL-dialect insert so ``on_conflict_do_nothing`` type-checks cleanly.
pg_insert = sa.dialects.postgresql.insert


class CanonicalEvidenceError(Exception):
    """Base for deterministic canonical-evidence selection failures (P2-S9)."""


class MissingRequiredEvidenceError(CanonicalEvidenceError):
    """A required upstream stage has no COMPLETE record in the current lineage."""


class AmbiguousRequiredEvidenceError(CanonicalEvidenceError):
    """The current-lineage upstream record is not uniquely determinable."""


#: Precedence for folding multiple ``stage_run`` rows of the same stage into ONE
#: effective status. A superseded failed row (a stale failed attempt left behind
#: by a retry/rerun/crash-resume) must not poison the aggregate job status:
#: ``complete`` (completed retry) supersedes ``failed``; ``quarantined`` is
#: terminal and supersedes ``failed``; an in-flight ``claimed``/``running`` retry
#: supersedes ``failed`` (the job is still RUNNING).
_STATUS_RANK = {
    "complete": 5,
    "quarantined": 4,
    "claimed": 3,
    "running": 3,
    "cancelled": 2,
    "pending": 1,
    "failed": 0,
}


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
        # Fold multiple rows per stage_name to ONE effective status with explicit
        # winning-status precedence, so a superseded failed row cannot poison the
        # aggregate: a completed retry supersedes a failed attempt; quarantined is
        # terminal and supersedes failed; an in-flight (claimed/running) retry
        # supersedes failed (the job is still RUNNING). Ties keep the first row.
        winning_status: dict[str, str] = {}
        winning_key: dict[str, str] = {}
        for r in run_rows:
            current = winning_status.get(r.stage_name)
            if current is None or _STATUS_RANK.get(r.status, 0) > _STATUS_RANK.get(current, 0):
                winning_status[r.stage_name] = r.status
                winning_key[r.stage_name] = str(r.idempotency_key)
        return [
            StageState(
                stage_name=stage,
                status=status,
                idempotency_key=winning_key.get(stage),
                attempts=attempts.get(stage, 1),
            )
            for stage, status in winning_status.items()
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

    def canonical_evidence_refs(
        self,
        source_id: str | None,
        dag_universe: str | None,
        segment_id: str | None,
        stage_name: str,
    ) -> list[str]:
        """Deterministically select ONE COMPLETE upstream record per dependency edge.

        P2-S9: replaces the former job-scoped ``committed_evidence_refs`` timing-
        dependent UNION (which raced when a dependent claimed before its upstream
        committed, yielding multiple keys for one stage). The lookup is keyed
        EXCLUSIVELY by the manifest's durable lineage identity — canonical source +
        DAG universe + segment (explicit null/root case) + dependency edge — and is
        therefore independent of ``job_id`` and of job ownership entirely.

        For each upstream stage in ``STAGE_DEPENDENCIES`` exactly ONE COMPLETE
        ``stage_run`` row is selected by deterministic current-lineage ordering
        (``created_at`` DESC, idempotency-key tie-break), and its ``evidence_refs``
        are returned sorted. ``[]`` is returned ONLY when the stage has no upstream
        dependencies (e.g. ``INGEST`` — the null/root case).

        FAILS CLOSED (never silently degrades to ``[]``):

        * :class:`MissingRequiredEvidenceError` when a required upstream stage has
          no COMPLETE record in this lineage — a structural violation (the native
          parent barrier must have held the upstream committed before the dependent
          resolves evidence).
        * :class:`AmbiguousRequiredEvidenceError` when two COMPLETE records for the
          same edge share the maximum ``created_at`` (a genuine same-timestamp race
          residue the current-lineage ordering cannot disambiguate).

        Selecting exactly one canonical upstream preserves evidence-sensitive
        rekeying after InvalidationPlanner descendant reruns and DAG-universe
        changes: a rerun descendant carries its lineage identity, selects the
        current upstream row, and derives a fresh key deterministically.
        """
        upstream = [dep for dep, _cls in STAGE_DEPENDENCIES.get(stage_name, ())]
        if not upstream:
            return []
        src = uuid.UUID(source_id) if source_id is not None else None
        seg = uuid.UUID(segment_id) if segment_id is not None else None
        # ``dag_universe`` may be null in the manifest (explicit null/root case):
        # ``_to_run_manifest`` stores it verbatim into
        # ``input_manifest['dag_universe']``, so a null universe is a JSON null and
        # must be matched with ``IS NULL``, not ``== None``. A real lineage always
        # carries a non-null universe (equality).
        dag_universe_col = _run_t.c.input_manifest["dag_universe"].astext
        dag_filter = (
            dag_universe_col.is_(None) if dag_universe is None else dag_universe_col == dag_universe
        )
        merged: list[str] = []
        with self._engine.connect() as conn:
            for dep in upstream:
                rows = conn.execute(
                    sa.select(_run_t.c.evidence_refs, _run_t.c.created_at)
                    .where(
                        sa.and_(
                            _run_t.c.source_id.is_(None)
                            if src is None
                            else _run_t.c.source_id == src,
                            dag_filter,
                            _run_t.c.segment_id.is_(None)
                            if seg is None
                            else _run_t.c.segment_id == seg,
                            _run_t.c.stage_name == dep,
                            _run_t.c.status == "complete",
                        )
                    )
                    .order_by(_run_t.c.created_at.desc(), _run_t.c.idempotency_key.desc())
                    .limit(2)
                ).fetchall()
                if not rows:
                    raise MissingRequiredEvidenceError(
                        f"stage {stage_name} requires upstream {dep} but no COMPLETE "
                        "record exists for the current lineage"
                    )
                if len(rows) == 2 and rows[0].created_at == rows[1].created_at:
                    raise AmbiguousRequiredEvidenceError(
                        f"stage {stage_name} upstream {dep} has two COMPLETE records "
                        "tied at the current-lineage timestamp; cannot select uniquely"
                    )
                for ref in rows[0].evidence_refs or []:
                    if ref and str(ref) not in merged:
                        merged.append(str(ref))
        return sorted(merged)

    def record_stage(self, _job_id: str, _state: StageState) -> None:
        # stage status is authoritative in the ``stage_run`` table written by the
        # executor; this is a no-op so the durable runner's observation hook stays
        # uniform across backends.
        return None


__all__ = ["PostgresJobRepository"]
