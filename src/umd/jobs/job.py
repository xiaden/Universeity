"""Job models and the job store contract (P1-S3).

A *job* is the durable orchestrating aggregate for one source decomposition run:
it carries the source/dag-universe identity, its lifecycle status, which stages
were explicitly cancelled (for partial cancellation), and any error. Job state is
operational (not semantic) — it lives in the ``job`` table next to ``stage_run``
and ``job_run_audit`` and never feeds Tier-0 replay.

The status of a job is *derived* from its stage_run rows (see
:meth:`JobStore.stage_states`) plus the aggregate status field set by explicit
lifecycle commands (cancel / pause / drain). ``JobStore`` is a small protocol so
the service is unit-testable with an in-memory backend and durable with the
Postgres backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class JobStatus(StrEnum):
    """Lifecycle states of a job aggregate."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


@dataclass
class StageState:
    """Observable status of one stage within a job (derived from stage_run)."""

    stage_name: str
    #: one of the durable stage_execution statuses (claimed/complete/failed/...)
    status: str
    idempotency_key: str | None = None
    attempts: int = 0


@dataclass
class JobRecord:
    """Durable job aggregate record."""

    id: str
    source_id: str | None
    dag_universe: str
    status: str
    request: dict[str, Any] = field(default_factory=dict)
    #: Stages explicitly cancelled by the user (partial cancel); whole-job cancel
    #: is expressed as ``status == CANCELLED``.
    cancelled_stages: set[str] = field(default_factory=set)
    error: str | None = None


class JobStore(Protocol):
    """Persistent job-store contract (in-memory in unit tests, Postgres in prod)."""

    def create(
        self,
        *,
        job_id: str,
        source_id: str | None,
        dag_universe: str,
        request: dict[str, Any] | None = None,
    ) -> JobRecord: ...

    def update_status(self, job_id: str, status: str, error: str | None = None) -> JobRecord: ...

    def set_cancelled_stages(self, job_id: str, stages: set[str]) -> JobRecord: ...

    def get(self, job_id: str) -> JobRecord | None: ...

    def stage_states(self, job_id: str) -> list[StageState]: ...

    def audit_records(self, job_id: str) -> list[Any]: ...

    def record_stage(self, job_id: str, state: StageState) -> None: ...

    def canonical_evidence_refs(
        self,
        source_id: str | None,
        dag_universe: str | None,
        segment_id: str | None,
        stage_name: str,
    ) -> list[str]: ...


class InMemoryJobStore:
    """JobStore backed by plain dicts (unit-test doubles, no DB needed)."""

    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._stages: dict[str, list[StageState]] = {}
        self._audits: dict[str, list[Any]] = {}

    def _ensure_job(self, job_id: str) -> JobRecord:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"unknown job {job_id}")
        return job

    # -- JobStore ----------------------------------------------------------

    def create(
        self,
        *,
        job_id: str,
        source_id: str | None,
        dag_universe: str,
        request: dict[str, Any] | None = None,
    ) -> JobRecord:
        job = JobRecord(
            id=job_id,
            source_id=source_id,
            dag_universe=dag_universe,
            status=JobStatus.PENDING,
            request=request or {},
        )
        if job.id in self._jobs:
            existing = self._jobs[job.id]
            if existing.source_id == source_id and existing.dag_universe == dag_universe:
                return existing  # duplicate submission -> same job (idempotent)
            raise ValueError(f"job {job.id} already exists for a different source/universe")
        self._jobs[job.id] = job
        self._stages[job.id] = []
        self._audits[job.id] = []
        return job

    def update_status(self, job_id: str, status: str, error: str | None = None) -> JobRecord:
        job = self._ensure_job(job_id)
        job.status = status
        if error is not None:
            job.error = error
        return job

    def set_cancelled_stages(self, job_id: str, stages: set[str]) -> JobRecord:
        job = self._ensure_job(job_id)
        job.cancelled_stages = set(stages)
        return job

    def get(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    def stage_states(self, job_id: str) -> list[StageState]:
        return list(self._stages.get(job_id, []))

    def audit_records(self, job_id: str) -> list[Any]:
        return list(self._audits.get(job_id, []))

    # -- in-memory dual recording (mirrors the Postgres backend) ----------

    def record_stage(self, job_id: str, state: StageState) -> None:
        self._stages.setdefault(job_id, [])
        self._stages[job_id] = [s for s in self._stages[job_id] if s.stage_name != state.stage_name]
        self._stages[job_id].append(state)

    def canonical_evidence_refs(
        self,
        source_id: str | None,
        dag_universe: str | None,
        segment_id: str | None,
        stage_name: str,
    ) -> list[str]:
        """Documented no-op: the in-memory store keeps no durable ``stage_run`` rows
        with evidence_refs, so committed-upstream evidence resolution is impossible
        here. Durable seam tests use the Postgres backend (P2-S9)."""
        del source_id, dag_universe, segment_id, stage_name  # no-op: no stage_run rows
        return []

    def record_audit(self, job_id: str, record: Any) -> None:
        self._audits.setdefault(job_id, []).append(record)


__all__ = [
    "JobStatus",
    "StageState",
    "JobRecord",
    "JobStore",
    "InMemoryJobStore",
]
