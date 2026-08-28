"""P1-S3 / P1-S4: production runner wiring + durable failure-path specs.

Two kinds of spec here:

* **P1-S3 regression (FAILS until Phase 3)** — the production ``build_context()`` /
  app factory must use ``PostgresJobRepository`` plus the production runner /
  dispatch seam, while ``InMemoryJobStore`` and ``SynchronousRunner`` are
  test-support doubles that the production factory can never select.

* **P1-S4 durable failure paths (PASS now)** — malformed input quarantines
  (deterministic, never retried) surfaced as failed job state; a late transient
  failure retries then fails WITHOUT repeating successful early stages; a cancel
  persists cancelled state and stops further scheduling; a selective rerun
  re-schedules only descendants via ``STAGE_DEPENDENTS``. These reuse the existing
  ``DurableStageExecutor`` / ``JobService`` / ``PostgresJobRepository`` wiring from
  ``tests/test_jobs_postgres.py`` — they already hold against the current durable
  layer. The API-visible submission-failure reporting spec lives in
  ``tests/test_api_contract.py`` and fails until Phase 3.
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa

from job_helpers import SOURCE_ID, build_executor, ensure_source, make_manifest, ok
from umd.application.jobs import JobService
from umd.jobs.dag import STAGE_ORDER
from umd.jobs.job import JobStatus

pytestmark = pytest.mark.postgres

ALL_WORK = {s: ok for s in STAGE_ORDER}


class _RecordingRunner:
    """Durable runner that also records which stages were scheduled."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.scheduled: list[str] = []

    def run_graph(self, **kwargs: Any) -> list[Any]:
        stages = list(kwargs["stages"])
        self.scheduled.extend(stages)
        return self._inner.run_graph(**kwargs)


def _service(umd_db: sa.Engine) -> tuple[JobService, _RecordingRunner]:
    from umd.jobs.runner import DurableDAGRunner
    from umd.storage.postgres.job_repository import PostgresJobRepository

    executor, _ledger = build_executor(umd_db)
    store = PostgresJobRepository(umd_db)
    runner = _RecordingRunner(DurableDAGRunner(executor=executor, store=store))
    return JobService(store=store, runner=runner), runner


def _stage_run_count(umd_db: sa.Engine, stage: str, job_id: str) -> int:
    with umd_db.connect() as conn:
        return int(
            conn.execute(
                sa.text("SELECT count(*) FROM stage_run WHERE stage_name=:s AND job_id=:j"),
                {"s": stage, "j": job_id},
            ).scalar()
        )


def _stage_run_status(umd_db: sa.Engine, key: str) -> str | None:
    with umd_db.connect() as conn:
        return conn.execute(
            sa.text("SELECT status FROM stage_run WHERE idempotency_key=:k"), {"k": key}
        ).scalar()


# ---------------------------------------------------------------------------
# P1-S3: production context wiring (FAILS until Phase 3)
# ---------------------------------------------------------------------------


def test_production_context_uses_durable_postgres_backends(
    umd_db: sa.Engine, source_store: Any
) -> None:
    """Production ``build_context()`` must wire PostgresJobRepository + the
    durable runner seam, never InMemoryJobStore or SynchronousRunner."""
    from umd.api.app import build_context
    from umd.api.runner import SynchronousRunner
    from umd.config import AuthSettings, ConsistencySettings, RateLimitSettings, Settings
    from umd.jobs.job import InMemoryJobStore
    from umd.jobs.runner import DurableDAGRunner
    from umd.storage.postgres.job_repository import PostgresJobRepository

    settings = Settings(
        auth=AuthSettings(api_keys=[], write_keys=[]),
        rate_limit=RateLimitSettings(
            enabled=False, requests_per_window=0, window_seconds=60.0, burst=0
        ),
        consistency=ConsistencySettings(lag_wait_multiplier=1, max_waiters=16),
        lag_budget_seconds=0.05,
    )
    ctx = build_context(settings=settings, engine=umd_db, source_store=source_store)
    store = ctx.extra["job_store"]
    runner = ctx.jobs._runner  # noqa: SLF001 - deliberate: inspect the injected seam

    # Production job state is durable Postgres-backed, never an in-memory double.
    assert isinstance(store, PostgresJobRepository)
    assert not isinstance(store, InMemoryJobStore)
    # The production dispatch seam is the durable runner, never the test-only double.
    assert isinstance(runner, DurableDAGRunner)
    assert not isinstance(runner, SynchronousRunner)


# ---------------------------------------------------------------------------
# P1-S4: durable failure-path specs (pass against the current durable layer)
# ---------------------------------------------------------------------------


def test_malformed_stage_input_is_quarantined_not_retried(umd_db: sa.Engine) -> None:
    """Deterministic malformed stage input quarantines (never retried) — the durable
    executor pattern from ``test_stage_execution.py``."""
    from umd.jobs.stage_execution import MalformedInputError, StageQuarantinedError

    ensure_source(umd_db)
    executor, _ledger = build_executor(umd_db)
    calls: list[int] = []

    def bad_work(_manifest: Any) -> Any:
        calls.append(1)
        raise MalformedInputError("corrupt structure", "locator://bad")

    manifest = make_manifest("BASIC_SEGMENTATION")
    with pytest.raises(StageQuarantinedError):
        executor.run(manifest, bad_work)
    assert len(calls) == 1, "quarantined stage must not retry"
    assert _stage_run_status(umd_db, manifest.idempotency_key()) == "quarantined"
    with umd_db.connect() as conn:
        n = conn.execute(sa.text("SELECT count(*) FROM quarantine")).scalar()
    assert n == 1


def test_late_transient_failure_retries_then_fails_without_repeating_early(
    umd_db: sa.Engine,
) -> None:
    """A late transient stage failure retries then lands the job in failed state;
    successful early stages are NOT repeated (one stage_run each)."""
    ensure_source(umd_db)
    svc, _runner = _service(umd_db)

    def always_transient(_manifest: Any) -> Any:
        from umd.jobs.stage_execution import StageTransientError

        raise StageTransientError("persistent decode glitch")

    work = dict(ALL_WORK)
    work["ENTITY_RESOLUTION"] = always_transient
    svc.submit(job_id="t-job", source_id=SOURCE_ID, dag_universe="v1-dag:base", work_registry=work)
    assert svc.status("t-job") == "failed"

    audits = svc.events("t-job")
    assert "retry" in {a.action for a in audits}, "transient failure did not retry"
    # Successful early stages were not repeated.
    for stage in STAGE_ORDER:
        assert _stage_run_count(umd_db, stage, "t-job") == 1, stage


def test_cancel_persists_cancelled_state_and_stops_further_scheduling(umd_db: sa.Engine) -> None:
    """A cancel persists cancelled state and stops any further stage scheduling."""
    ensure_source(umd_db)
    svc, runner = _service(umd_db)
    svc.submit(
        job_id="cancel2-job",
        source_id=SOURCE_ID,
        dag_universe="v1-dag:base",
        work_registry=ALL_WORK,
    )
    svc.cancel(job_id="cancel2-job", reason="operator stop")
    assert svc.status("cancel2-job") == JobStatus.CANCELLED  # persisted cancelled state
    scheduled_before = len(runner.scheduled)
    # Whole-job retry after cancellation schedules nothing further.
    svc.retry(job_id="cancel2-job", work_registry=ALL_WORK, dag_universe="v1-dag:base")
    assert len(runner.scheduled) == scheduled_before


def test_selective_rerun_schedules_only_descendants(umd_db: sa.Engine) -> None:
    """A selective rerun re-schedules ONLY the STAGE_DEPENDENTS descendant closure;
    unaffected/upstream stages are untouched."""
    ensure_source(umd_db)
    svc, runner = _service(umd_db)
    svc.submit(
        job_id="sel-job", source_id=SOURCE_ID, dag_universe="v1-dag:base", work_registry=ALL_WORK
    )
    runner.scheduled.clear()

    targets = svc.rerun_stage(
        source_id=SOURCE_ID,
        stage="ENTITY_RESOLUTION",
        scope="SOURCE",
        causation="user-correction",
        dag_universe="v1-dag:base",
        work_registry=ALL_WORK,
        job_id="sel-job",
    )
    scheduled = set(runner.scheduled)
    planned = {t.stage for t in targets.targets}
    assert "INGEST" not in scheduled and "LOW_LEVEL_EXTRACTION" not in scheduled
    assert (
        scheduled
        == planned
        == {
            "CROSS_SOURCE_ALIGNMENT",
            "SEMANTIC_RECONCILIATION",
            "CURRENT_SEARCH_PROJECTION",
        }
    )


def test_late_transient_retry_does_not_repeat_committed_stage_run_rows(umd_db: sa.Engine) -> None:
    """Retrying after a transient failure keeps exactly one stage_run per stage
    (executor claim-before-side-effect dedup), even for the failed stage."""
    ensure_source(umd_db)
    svc, _runner = _service(umd_db)

    def flaky(_manifest: Any) -> Any:
        from umd.jobs.stage_execution import StageTransientError

        raise StageTransientError("transient network hiccup")

    work = dict(ALL_WORK)
    work["STRUCTURAL_ANALYSIS"] = flaky
    svc.submit(job_id="rt-job", source_id=SOURCE_ID, dag_universe="v1-dag:base", work_registry=work)
    assert svc.status("rt-job") == "failed"
    svc.retry(job_id="rt-job", work_registry=ALL_WORK, dag_universe="v1-dag:base")
    assert svc.status("rt-job") == "complete"
    for stage in STAGE_ORDER:
        assert _stage_run_count(umd_db, stage, "rt-job") == 1, stage


def test_quarantined_stage_is_never_re_run_on_restart(umd_db: sa.Engine) -> None:
    """A deterministically quarantined stage is never re-executed on restart: a
    duplicate submission of the same failure returns a replayed quarantined record
    without invoking the work again (deterministic, never retried)."""
    from umd.jobs.stage_execution import MalformedInputError, StageQuarantinedError

    ensure_source(umd_db)
    executor, _ledger = build_executor(umd_db)
    calls: list[int] = []

    def bad_work(_manifest: Any) -> Any:
        calls.append(1)
        raise MalformedInputError("unsupported feature", "locator://x")

    manifest = make_manifest("FORMAT_ANALYSIS", job_id="mq-job")
    with pytest.raises(StageQuarantinedError):
        executor.run(manifest, bad_work)
    assert _stage_run_status(umd_db, manifest.idempotency_key()) == "quarantined"
    # Restart re-drives the same manifest: replayed quarantine, work NOT re-run.
    rec = executor.run(manifest, bad_work)
    assert rec.replayed is True and rec.state == "quarantined"
    assert calls == [1], "quarantined stage work ran more than once"


def test_real_registry_retry_deduplicates_and_threads_evidence(umd_db: sa.Engine) -> None:
    """Fix-cycle acceptance: a durable real-registry retry must (a) reach
    ``complete``, (b) keep exactly ONE ``stage_run`` row per stage, and (c) carry
    the committed upstream evidence refs onto the resumed stage's manifest so the
    original idempotency key is reproduced (no duplicate insert, no lost chain).

    Uses the REAL production registry (real non-empty outputs), not ``ok``/counting
    doubles. A late stage (STRUCTURAL_ANALYSIS) fails transiently on the first
    submit, then delegates to the real work on ``JobService.retry``.
    """
    import importlib

    from umd.application.commands import SemanticCommandService
    from umd.application.jobs import JobService
    from umd.jobs.dag import STAGE_DEPENDENTS, STAGE_ORDER
    from umd.jobs.invalidation import InvalidationPlanner
    from umd.jobs.runner import DurableDAGRunner
    from umd.jobs.stage_execution import RetryPolicy, StageTransientError
    from umd.storage.postgres.job_repository import PostgresJobRepository
    from umd.storage.postgres.ledger import SemanticLedger

    ensure_source(umd_db)
    ledger = SemanticLedger(umd_db)
    commands = SemanticCommandService(ledger)
    executor, _ledger2 = build_executor(umd_db, retry=RetryPolicy(max_attempts=1))
    store = PostgresJobRepository(umd_db)
    svc = JobService(
        store=store,
        runner=DurableDAGRunner(executor=executor, store=store),
        planner=InvalidationPlanner(),
        lineage=STAGE_DEPENDENTS,
        commands=commands,
    )

    production = importlib.import_module("umd.jobs.production")
    registry = production.StageWorkRegistryFactory.build({"engine": umd_db, "commands": commands})

    # Wrap a late stage so it fails transiently on the first submit, then delegates
    # to the REAL work (real, non-empty outputs). Capture the manifests it sees.
    captured: list[Any] = []
    original = registry["STRUCTURAL_ANALYSIS"]

    def flaky(manifest: Any) -> Any:
        captured.append(manifest)
        if len(captured) == 1:  # first submit: transient failure
            raise StageTransientError("transient decode glitch")
        return original(manifest)  # retry: delegate to the real production work

    work = dict(registry)
    work["STRUCTURAL_ANALYSIS"] = flaky

    svc.submit(
        job_id="prod-retry",
        source_id=SOURCE_ID,
        dag_universe="v1-dag:base",
        work_registry=work,
    )
    assert svc.status("prod-retry") == "failed"

    svc.retry(job_id="prod-retry", work_registry=work, dag_universe="v1-dag:base")

    # (a) the retried job reaches complete.
    assert svc.status("prod-retry") == "complete"

    # (b) exactly ONE stage_run row per stage — the retry resumed the original row
    # (same idempotency key), never inserting a duplicate.
    with umd_db.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT stage_name, count(*) AS n FROM stage_run "
                "WHERE job_id=:j GROUP BY stage_name"
            ),
            {"j": "prod-retry"},
        ).fetchall()
    counts = {str(r.stage_name): int(r.n) for r in rows}
    assert set(counts) == set(STAGE_ORDER), counts
    assert all(n == 1 for n in counts.values()), f"duplicate stage_run rows: {counts}"

    # (c) the resumed stage reproduced its ORIGINAL manifest: the retried
    # STRUCTURAL manifest carries the same committed upstream evidence refs and
    # therefore the same idempotency key (the first manifest already carried
    # non-empty committed upstream refs, proving evidence was threaded).
    m1, m2 = captured[0], captured[1]
    assert m1.evidence_refs, "STRUCTURAL manifest must carry committed upstream evidence_refs"
    assert m2.evidence_refs == m1.evidence_refs
    assert m2.idempotency_key() == m1.idempotency_key()

    # The resumed stage's durable row retains committed (non-empty) evidence_refs.
    with umd_db.connect() as conn:
        ev = conn.execute(
            sa.text(
                "SELECT evidence_refs FROM stage_run "
                "WHERE job_id=:j AND stage_name='STRUCTURAL_ANALYSIS'"
            ),
            {"j": "prod-retry"},
        ).scalar()
    assert ev, "resumed stage_run row must retain committed evidence_refs"
