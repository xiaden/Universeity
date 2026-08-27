"""P1-S3/P1-S5: JobService orchestration over the runner seam (in-memory, unit)."""

from __future__ import annotations

from types import SimpleNamespace

from job_helpers import FakeExecutor, ok
from umd.application.jobs import JobService, projection_pause_reason
from umd.jobs.dag import STAGE_ORDER
from umd.jobs.job import InMemoryJobStore
from umd.jobs.runner import DurableDAGRunner

ALL_WORK = {stage: ok for stage in STAGE_ORDER}


def _service(fake: FakeExecutor) -> tuple[JobService, InMemoryJobStore, FakeExecutor]:
    store = InMemoryJobStore()
    runner = DurableDAGRunner(executor=fake, store=store)  # type: ignore[arg-type]
    svc = JobService(store=store, runner=runner)
    return svc, store, fake


def _submit(svc: JobService, fake: FakeExecutor) -> str:
    job = svc.submit(
        job_id="job-b1",
        source_id="s-b3f98f72",
        dag_universe="v1-dag:base",
        work_registry=ALL_WORK,
    )
    assert job.id == "job-b1"
    assert svc.status("job-b1") == "complete"
    assert fake.calls == list(STAGE_ORDER)
    return job.id


def test_submit_covers_full_lineage_and_status_derives_complete() -> None:
    fake = FakeExecutor()
    svc, store, _ = _service(fake)
    job_id = _submit(svc, fake)
    assert len(store.stage_states(job_id)) == len(STAGE_ORDER)


def test_duplicate_submit_is_idempotent() -> None:
    fake = FakeExecutor()
    svc, store, _ = _service(fake)
    _submit(svc, fake)
    calls_after_first = len(fake.calls)
    duplicate = svc.submit(
        job_id="job-b1",
        source_id="s-b3f98f72",
        dag_universe="v1-dag:base",
        work_registry=ALL_WORK,
    )
    assert duplicate.id == "job-b1"
    # No additional work: the second submission deduped on the job aggregate.
    assert len(fake.calls) == calls_after_first


def test_rerun_source_drives_full_downstream_no_upstream_repeat() -> None:
    fake = FakeExecutor()
    svc, store, _ = _service(fake)
    _submit(svc, fake)
    fake.calls.clear()

    svc.rerun_source(
        source_id="s-b3f98f72",
        scope="SOURCE",
        causation="source-updated",
        dag_universe="v1-dag:base",
        work_registry=ALL_WORK,
        job_id="job-b1",
    )
    ran = set(fake.calls)
    # Full downstream re-drive (everything after the INGEST root), descendants
    # only, and never the INGEST root itself (no upstream repeat).
    assert ran == set(STAGE_ORDER) - {"INGEST"}
    assert "INGEST" not in ran


def test_events_returns_ordered_audit_stream() -> None:
    fake = FakeExecutor()
    svc, store, _ = _service(fake)
    _submit(svc, fake)
    # Seed an operational audit stream: start -> retry(failed) -> complete for one
    # stage. events() must surface it verbatim, in stream order.
    transitions = [
        ("ENTITY_RESOLUTION", "start", "claimed", 1),
        ("ENTITY_RESOLUTION", "retry", "failed", 2),
        ("ENTITY_RESOLUTION", "complete", "complete", 3),
    ]
    for stage, action, status, attempt in transitions:
        store.record_audit(
            "job-b1",
            SimpleNamespace(
                job_id="job-b1",
                stage_name=stage,
                action=action,
                status=status,
                attempt=attempt,
            ),
        )
    events = svc.events("job-b1")
    assert [e.action for e in events] == ["start", "retry", "complete"]
    assert [e.status for e in events] == ["claimed", "failed", "complete"]
    assert [e.attempt for e in events] == [1, 2, 3]
    assert all(e.job_id == "job-b1" for e in events)


def test_child_cancel_parent_fail_retry_redrives_only_noncomplete() -> None:
    fake = FakeExecutor()
    store = InMemoryJobStore()
    runner = DurableDAGRunner(executor=fake, store=store)  # type: ignore[arg-type]
    svc = JobService(store=store, runner=runner)

    def fail(_m):
        return SimpleNamespace(state="failed")

    # Parent ENTITY_RESOLUTION and child CROSS_SOURCE_ALIGNMENT both fail during
    # submit; every other stage commits. Then cancel the child explicitly.
    work = {
        s: (ok if s not in {"ENTITY_RESOLUTION", "CROSS_SOURCE_ALIGNMENT"} else fail)
        for s in STAGE_ORDER
    }
    svc.submit(
        job_id="ccpf", source_id="s-b3f98f72", dag_universe="v1-dag:base", work_registry=work
    )
    assert svc.status("ccpf") == "failed"
    svc.cancel(job_id="ccpf", stage="CROSS_SOURCE_ALIGNMENT")

    # Retry with all-ok work re-drives ONLY the non-complete stages: the failed
    # parent plus the cancelled child; descendants and upstream successes are not
    # repeated.
    fake.calls.clear()
    svc.retry(job_id="ccpf", work_registry=ALL_WORK, dag_universe="v1-dag:base")
    re_driven = set(fake.calls)
    assert re_driven == {"ENTITY_RESOLUTION", "CROSS_SOURCE_ALIGNMENT"}
    for up in (
        "INGEST",
        "FORMAT_ANALYSIS",
        "BASIC_SEGMENTATION",
        "LOW_LEVEL_EXTRACTION",
        "STRUCTURAL_ANALYSIS",
    ):
        assert up not in re_driven, up
    assert svc.status("ccpf") == "complete"


def test_rerun_stage_is_descendant_only() -> None:
    fake = FakeExecutor()
    svc, store, _ = _service(fake)
    _submit(svc, fake)
    fake.calls.clear()

    targets = svc.rerun_stage(
        source_id="s-b3f98f72",
        stage="ENTITY_RESOLUTION",
        scope="SOURCE",
        causation="user-correction",
        dag_universe="v1-dag:base",
        work_registry=ALL_WORK,
        job_id="job-b1",
    )
    rerun = set(fake.calls)
    planned = {t.stage for t in targets.targets}
    # Descendant-only: the rerun root itself is excluded, only its transitive
    # downstream closure is scheduled, and never anything upstream.
    assert "ENTITY_RESOLUTION" not in planned
    assert "INGEST" not in planned
    assert "LOW_LEVEL_EXTRACTION" not in planned
    assert planned == {
        "CROSS_SOURCE_ALIGNMENT",
        "SEMANTIC_RECONCILIATION",
        "CURRENT_SEARCH_PROJECTION",
    }
    assert rerun == planned


def test_invalidate_returns_targets_and_pause_reason() -> None:
    fake = FakeExecutor()
    svc, store, _ = _service(fake)
    _submit(svc, fake)
    fake.calls.clear()

    targets, pause = svc.invalidate(
        subject_ref="e:1",
        predicate="speaker",
        cause="wrong speaker",
        scope="CONTINUITY",
        stage="ENTITY_RESOLUTION",
        source_id="s-b3f98f72",
        dag_universe="v1-dag:base",
        work_registry=ALL_WORK,
        job_id="job-b1",
    )
    # authority predicate -> projections paused
    assert pause is not None
    assert "paused" in pause
    assert {t.stage for t in targets.targets} == set(fake.calls)


def test_cancel_then_retry_does_not_repeat_successful_work() -> None:
    fake = FakeExecutor()
    svc, _, _ = _service(fake)
    _submit(svc, fake)
    # Whole-job cancel stops further scheduling.
    svc.cancel(job_id="job-b1", reason="operator stop")
    assert svc.status("job-b1") == "cancelled"

    # Retry: only NON-complete stages are scheduled. All stages succeeded, so
    # nothing is re-scheduled -> no repeated successful stage work.
    calls_before = len(fake.calls)
    svc.retry(job_id="job-b1", work_registry=ALL_WORK, dag_universe="v1-dag:base")
    assert len(fake.calls) == calls_before
    assert svc.status("job-b1") == "complete"


def test_single_stage_cancel_is_partial() -> None:
    fake = FakeExecutor()
    svc, store, _ = _service(fake)
    _submit(svc, fake)
    fake.calls.clear()

    svc.cancel(job_id="job-b1", stage="ENTITY_RESOLUTION")
    targets = svc.rerun_stage(
        source_id="s-b3f98f72",
        stage="FORMAT_ANALYSIS",
        scope="SOURCE",
        causation="tweak",
        dag_universe="v1-dag:base",
        work_registry=ALL_WORK,
        job_id="job-b1",
    )
    # FORMAT_ANALYSIS is not under the cancelled stage's closure -> its whole
    # downstream closure is planned, but the cancelled ENTITY closure is NOT
    # re-executed (partial-cancel persists on rerun).
    planned = {t.stage for t in targets.targets}
    assert "FORMAT_ANALYSIS" not in planned
    assert "BASIC_SEGMENTATION" in planned
    executed = set(fake.calls)
    assert executed == {
        "BASIC_SEGMENTATION",
        "LOW_LEVEL_EXTRACTION",
        "STRUCTURAL_ANALYSIS",
    }
    assert "ENTITY_RESOLUTION" not in executed
    assert "CROSS_SOURCE_ALIGNMENT" not in executed


def test_projection_pause_policy_pure() -> None:
    assert projection_pause_reason(event_type="Invalidated", subject_ref="e:1", predicate="speaker")
    # Non-authority predicate -> no pause.
    assert (
        projection_pause_reason(event_type="Invalidated", subject_ref="e:1", predicate="scene")
        is None
    )
    # Non-authority event type -> no pause.
    assert projection_pause_reason(event_type="SemanticAsserted", subject_ref="e:1") is None


def test_job_status_failed_when_a_stage_fails() -> None:
    def fail(_m):
        return SimpleNamespace(state="failed")

    fake = FakeExecutor()
    store = InMemoryJobStore()
    runner = DurableDAGRunner(executor=fake, store=store)  # type: ignore[arg-type]
    svc = JobService(store=store, runner=runner)
    work = {s: (ok if s != "BASIC_SEGMENTATION" else fail) for s in STAGE_ORDER}
    svc.submit(
        job_id="job-fail",
        source_id="s-b3f98f72",
        dag_universe="v1-dag:base",
        work_registry=work,
    )
    assert svc.status("job-fail") == "failed"
