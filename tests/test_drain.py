"""P1-S4/P1-S5: DAG-version drain/cancel policy (unit + postgres)."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from job_helpers import SOURCE_ID, ensure_source
from umd.jobs.drain import SimpleUniverseGate
from umd.jobs.job import InMemoryJobStore, JobRecord, JobStatus
from umd.storage.postgres.job_repository import PostgresJobRepository


def _rec(job_id: str, universe: str, status: str) -> JobRecord:
    return JobRecord(id=job_id, source_id="s-x", dag_universe=universe, status=status)


def test_unit_drain_cancels_only_active_old_universe_jobs() -> None:
    store = InMemoryJobStore()
    for jid, st in [("a", JobStatus.RUNNING), ("b", JobStatus.PENDING), ("c", JobStatus.COMPLETE)]:
        store.update_status(
            store.create(job_id=jid, source_id="s-x", dag_universe="old-universe").id, st
        )
    gate = SimpleUniverseGate(store, snapshot=[store.get("a"), store.get("b"), store.get("c")])
    result = gate.activate_new_universe("new-universe")
    # Drains the two in-flight jobs on the old universe.
    assert result.drained_jobs == 2
    assert set(result.cancelled_job_ids) == {"a", "b"}
    # A completed job is left untouched.
    assert store.get("c").status == JobStatus.COMPLETE
    assert store.get("a").status == JobStatus.CANCELLED


def test_restart_policy_documented() -> None:
    from umd.jobs.drain import restart_policy

    policy = restart_policy()
    assert "resume" in policy and "drain" in policy


@pytest.mark.postgres
def test_postgres_drain_durable(umd_db: sa.Engine) -> None:
    ensure_source(umd_db)
    store = PostgresJobRepository(umd_db)
    store.create(job_id="pg-old-1", source_id=SOURCE_ID, dag_universe="v1-dag:base")
    store.create(job_id="pg-old-2", source_id=SOURCE_ID, dag_universe="v1-dag:ocr")
    store.create(job_id="pg-new-3", source_id=SOURCE_ID, dag_universe="v1-dag:next")
    store.update_status("pg-old-1", JobStatus.RUNNING)
    store.update_status("pg-new-3", JobStatus.RUNNING)

    snapshot = [store.get(j) for j in ("pg-old-1", "pg-old-2", "pg-new-3")]
    gate = SimpleUniverseGate(store, snapshot=[s for s in snapshot if s])  # type: ignore[list-item]
    result = gate.activate_new_universe("v1-dag:next")

    # Drains only the old-universe in-flight job; the same-universe one survives.
    assert "pg-old-1" in result.cancelled_job_ids
    assert "pg-new-3" not in result.cancelled_job_ids
    assert store.get("pg-old-1").status == JobStatus.CANCELLED  # type: ignore[union-attr]
    assert store.get("pg-new-3").status == JobStatus.RUNNING
