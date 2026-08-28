"""P1-S5: durable JobService scenarios over live Postgres
(duplicate submissions, cancel/retry, replay-after-cancel, descendant-only
invalidation, no repeated successful work, DAG drain/cancel)."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from job_helpers import SOURCE_ID, build_executor, ensure_source, ok
from umd.application.jobs import JobService
from umd.jobs.dag import STAGE_ORDER
from umd.jobs.job import JobStatus
from umd.storage.postgres.job_repository import PostgresJobRepository

pytestmark = pytest.mark.postgres

ALL_WORK = {s: ok for s in STAGE_ORDER}


class RecordingRunner:
    """Durable runner that also records which stages were scheduled."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.scheduled: list[str] = []

    def run_graph(self, **kwargs) -> list:
        stages = list(kwargs["stages"])
        self.scheduled.extend(stages)
        return self._inner.run_graph(**kwargs)


def _service(umd_db: sa.Engine) -> tuple[JobService, RecordingRunner]:
    executor, _ledger = build_executor(umd_db)
    store = PostgresJobRepository(umd_db)
    inner = RecordingRunner(_make_runner(executor, store))
    svc = JobService(store=store, runner=inner)
    return svc, inner


def _make_runner(executor, store):
    from umd.jobs.runner import DurableDAGRunner

    return DurableDAGRunner(executor=executor, store=store)


def _stage_run_count(umd_db: sa.Engine, stage: str, job_id: str) -> int:
    with umd_db.connect() as conn:
        return int(
            conn.execute(
                sa.text("SELECT count(*) FROM stage_run WHERE stage_name=:s AND job_id=:j"),
                {"s": stage, "j": job_id},
            ).scalar()
        )


def test_duplicate_submission_is_single_run(umd_db: sa.Engine) -> None:
    ensure_source(umd_db)
    svc, runner = _service(umd_db)
    svc.submit(
        job_id="dup-job", source_id=SOURCE_ID, dag_universe="v1-dag:base", work_registry=ALL_WORK
    )
    assert svc.status("dup-job") == "complete"
    scheduled_first = len(runner.scheduled)

    duplicate = svc.submit(
        job_id="dup-job", source_id=SOURCE_ID, dag_universe="v1-dag:base", work_registry=ALL_WORK
    )
    assert duplicate.id == "dup-job"
    # No new stage scheduling on duplicate submission.
    assert len(runner.scheduled) == scheduled_first
    # Exactly one stage_run per canonical stage -> no duplicate run rows.
    for stage in STAGE_ORDER:
        assert _stage_run_count(umd_db, stage, "dup-job") == 1


def test_retry_resumes_failed_stage_without_repeating_successes(umd_db: sa.Engine) -> None:
    ensure_source(umd_db)
    executor, _ledger = build_executor(umd_db)
    store = PostgresJobRepository(umd_db)
    svc = JobService(
        store=store,
        runner=RecordingRunner(_make_runner(executor, store)),
    )

    def fail_once(_m):
        from umd.jobs.stage_execution import StageTransientError

        raise StageTransientError("decode glitch")

    work = dict(ALL_WORK)
    work["ENTITY_RESOLUTION"] = fail_once
    svc.submit(
        job_id="retry-job", source_id=SOURCE_ID, dag_universe="v1-dag:base", work_registry=work
    )
    assert svc.status("retry-job") == "failed"

    # Retry the whole job with a working ENTITY stage.
    svc.retry(job_id="retry-job", work_registry=ALL_WORK, dag_universe="v1-dag:base")
    assert svc.status("retry-job") == "complete"
    # Still one stage_run per stage: retry never creates duplicate rows.
    for stage in STAGE_ORDER:
        assert _stage_run_count(umd_db, stage, "retry-job") == 1, stage


def test_replay_after_cancel_does_not_repeat_committed_work(umd_db: sa.Engine) -> None:
    ensure_source(umd_db)
    svc, runner = _service(umd_db)
    svc.submit(
        job_id="cancel-job", source_id=SOURCE_ID, dag_universe="v1-dag:base", work_registry=ALL_WORK
    )
    svc.cancel(job_id="cancel-job", reason="operator stop")
    scheduled_before = len(runner.scheduled)

    # Whole-job retry after a completed run schedules nothing (all stages complete).
    svc.retry(job_id="cancel-job", work_registry=ALL_WORK, dag_universe="v1-dag:base")
    assert len(runner.scheduled) == scheduled_before
    assert svc.status("cancel-job") == "complete"


def test_cancel_parent_then_retry_drives_closure_without_upstream_repeat(umd_db: sa.Engine) -> None:
    ensure_source(umd_db)
    svc, runner = _service(umd_db)
    svc.submit(
        job_id="cp-job", source_id=SOURCE_ID, dag_universe="v1-dag:base", work_registry=ALL_WORK
    )
    # Cancel a mid-DAG parent -> its descendant closure joins cancelled_stages.
    svc.cancel(job_id="cp-job", stage="ENTITY_RESOLUTION")
    rec = PostgresJobRepository(umd_db).get("cp-job")
    assert "ENTITY_RESOLUTION" in rec.cancelled_stages
    assert "SEMANTIC_RECONCILIATION" in rec.cancelled_stages

    # Retrying the parent re-schedules its closure (entity..projection).
    runner.scheduled.clear()
    svc.retry(
        job_id="cp-job",
        work_registry=ALL_WORK,
        dag_universe="v1-dag:base",
        stage="ENTITY_RESOLUTION",
    )
    # The durable executor re-uses committed completions: still one row per stage.
    for stage in STAGE_ORDER:
        assert _stage_run_count(umd_db, stage, "cp-job") == 1, stage


def test_descendant_only_invalidation_schedules_only_descendants(umd_db: sa.Engine) -> None:
    ensure_source(umd_db)
    svc, runner = _service(umd_db)
    svc.submit(
        job_id="inv-job", source_id=SOURCE_ID, dag_universe="v1-dag:base", work_registry=ALL_WORK
    )
    runner.scheduled.clear()

    targets = svc.rerun_stage(
        source_id=SOURCE_ID,
        stage="ENTITY_RESOLUTION",
        scope="SOURCE",
        causation="user-correction",
        dag_universe="v1-dag:base",
        work_registry=ALL_WORK,
        job_id="inv-job",
    )
    scheduled = set(runner.scheduled)
    planned = {t.stage for t in targets.targets}
    # Descendant-only: nothing upstream, and the planned closure equals scheduled.
    assert "INGEST" not in scheduled
    assert "LOW_LEVEL_EXTRACTION" not in scheduled
    assert (
        scheduled
        == planned
        == {
            "CROSS_SOURCE_ALIGNMENT",
            "SEMANTIC_RECONCILIATION",
            "CURRENT_SEARCH_PROJECTION",
        }
    )


def test_dag_version_drain_cancels_in_flight_old_universe(umd_db: sa.Engine) -> None:
    ensure_source(umd_db)
    svc, _ = _service(umd_db)
    svc.submit(
        job_id="drain-job",
        source_id=SOURCE_ID,
        dag_universe="v1-dag:ocr",
        work_registry=ALL_WORK,
    )
    from umd.jobs.drain import SimpleUniverseGate

    store = PostgresJobRepository(umd_db)
    # Simulate an IN-FLIGHT job still running under the old DAG release.
    store.update_status("drain-job", JobStatus.RUNNING)
    snapshot = store.get("drain-job")
    gate = SimpleUniverseGate(store, snapshot=[snapshot] if snapshot else [])
    result = gate.activate_new_universe("v1-dag:base")
    assert result.drained_jobs == 1
    assert "drain-job" in result.cancelled_job_ids


def test_dag_gate_keeps_completed_drains_only_other_universe_inflight(
    umd_db: sa.Engine,
) -> None:
    """P2-S6 migration/drain contract: activating a new DAG universe cancels ONLY
    in-flight (PENDING/RUNNING/PAUSED) jobs under a DIFFERENT universe and leaves
    already-completed jobs intact (their results stay readable). Draining never
    re-keys completed work and never aliases stage idempotency across universes."""
    from umd.jobs.drain import SimpleUniverseGate

    ensure_source(umd_db)
    store = PostgresJobRepository(umd_db)
    store.create(job_id="gate-finished", source_id=SOURCE_ID, dag_universe="v1-dag:old")
    store.update_status("gate-finished", JobStatus.COMPLETE)
    store.create(job_id="gate-inflight", source_id=SOURCE_ID, dag_universe="v1-dag:old")
    store.update_status("gate-inflight", JobStatus.RUNNING)
    store.create(job_id="gate-new", source_id=SOURCE_ID, dag_universe="v1-dag:new")
    store.update_status("gate-new", JobStatus.RUNNING)

    finished = store.get("gate-finished")
    inflight = store.get("gate-inflight")
    new_universe = store.get("gate-new")
    snapshot = [j for j in (finished, inflight, new_universe) if j is not None]
    gate = SimpleUniverseGate(store, snapshot=snapshot)
    result = gate.activate_new_universe("v1-dag:new")

    # Only the old-universe in-flight job is drained; completed and new-universe
    # jobs are untouched (their results / lineage remain readable).
    assert result.drained_jobs == 1
    assert result.cancelled_job_ids == ("gate-inflight",)
    assert store.get("gate-finished").status == JobStatus.COMPLETE
    assert store.get("gate-inflight").status == JobStatus.CANCELLED
    assert store.get("gate-new").status == JobStatus.RUNNING


def test_dag_gate_universe_distinct_keys_no_cross_universe_aliasing(
    umd_db: sa.Engine,
) -> None:
    """P2-S6 idempotency contract: the same stage under two DAG universes yields
    DISTINCT idempotency keys (the universe folds into the key), so draining a
    universe can never collide with or re-derive a committed run from another
    universe — no cross-universe aliasing."""
    ensure_source(umd_db)
    from umd.jobs.manifest import StageManifest

    m_old = StageManifest(
        job_id="no-alias",
        stage_name="INGEST",
        source_id=SOURCE_ID,
        dag_universe="v1-dag:old",
        evidence_refs=[],
        input_manifest={"source_id": SOURCE_ID},
    )
    m_new = StageManifest(
        job_id="no-alias",
        stage_name="INGEST",
        source_id=SOURCE_ID,
        dag_universe="v1-dag:new",
        evidence_refs=[],
        input_manifest={"source_id": SOURCE_ID},
    )
    assert m_old.idempotency_key() != m_new.idempotency_key()
