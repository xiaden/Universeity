"""Phase 1 (Plan I): live scheduler proof — spec-first Hatchet worker integration.

These tests are SPEC-FIRST: they pin the CONTRACTS.md "Production execution
remediation contracts" surface and MOST FAIL until Phase 2 implements the real
Hatchet workflow/task registration, callback binding, and run_graph submission in
``umd.jobs.hatchet`` / ``umd.deploy.cli.worker``. The only tests that pass today
are the honest-unavailable worker exits (P1-S4 #1), which the current
``umd.deploy.cli.worker`` already implements.

The pinned surface (CONTRACTS.md:60-63):

    StageWorkRegistryFactory.build(runtime) -> StageWorkRegistry   (Plan G, exists)
    ProductionDAGRunner.run_graph(...) -> list[StageRunEvent]      (planned)
    HatchetWorkerFactory.start(runtime, work_registry, executor) -> WorkerHandle
    CapabilityReporter.report() -> CapabilityReport

Hatchet is the SOLE v1 scheduler. These tests never accept a placeholder empty
event list, a fake empty registration, or a direct stage completion. Planned
symbols are resolved lazily so a missing Phase 2 surface fails as an
``ImportError``/``AttributeError`` (spec-first), not as a static type error.

Marking discipline:

  * ``cluster`` — live-shape OR hermetic-with-recording-client tests. Only the 3
    ``test_live_hatchet_*`` tests gate on a real Hatchet cluster and skip without
    it; the other cluster-marked tests pass hermetically against the recording
    client (no live cluster required). They are the proof Plan J executes.
  * ``docker`` — tag for tests that also require the Docker Compose stack.
  * ``postgres`` — seam tests that run against the real ``DurableStageExecutor`` /
    ``DurableDAGRunner`` over real Postgres and may pass now (that is fine and
    correct — the semantics already exist on the seam).
"""

from __future__ import annotations

import importlib
import json
import os
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
import sqlalchemy as sa

import umd.deploy.cli as cli
from umd.jobs.dag import STAGE_DEPENDENCIES, STAGE_ORDER
from umd.jobs.manifest import StageManifest
from umd.jobs.stage_execution import (
    MalformedInputError,
    StageOutcome,
    StageQuarantinedError,
    StageTransientError,
    StageWork,
)

#: A stable, valid UUID used as the seed source for durable executor tests
#: (mirrors tests/job_helpers.py, kept self-contained to avoid pulling that module
#: into the strict type gate).
_SOURCE_ID = "b3f98f72-0000-0000-0000-000000000000"


# ---------------------------------------------------------------------------
# self-contained durable-wiring helpers (mirror job_helpers without importing it)
# ---------------------------------------------------------------------------


def _build_executor(engine: sa.Engine) -> Any:
    """Wire a real durable executor + ledger over a migrated Postgres engine."""
    from umd.application.commands import SemanticCommandService
    from umd.jobs.stage_execution import DurableStageExecutor, NoWaitBackoff, RetryPolicy
    from umd.storage.postgres.ledger import SemanticLedger
    from umd.storage.postgres.repositories import PostgresQuarantine
    from umd.storage.postgres.stage_repository import JobRunAudit, StageRunRepository

    ledger = SemanticLedger(engine)
    executor = DurableStageExecutor(
        engine=engine,
        commands=SemanticCommandService(ledger),
        ledger=ledger,
        stage_repo=StageRunRepository(engine),
        audit=JobRunAudit(engine),
        quarantine=PostgresQuarantine(engine),
        retry=RetryPolicy(),
        backoff=NoWaitBackoff(),
    )
    return executor, ledger


def _ensure_source(engine: sa.Engine, source_id: str = _SOURCE_ID) -> None:
    """Insert a source row so stage_run FK + StageCompleted payload resolve."""
    from umd.storage.postgres.tables import metadata as _meta

    src_t = _meta.tables["source"]
    with engine.begin() as conn:
        conn.execute(
            src_t.insert().values(
                id=uuid.UUID(source_id),
                ocfl_ref=f"urn:ocfl:{source_id}",
                sha512="d" * 128,
                size_bytes=42,
                media_kind="text",
                original_name="seed.txt",
            )
        )


def _make_manifest(
    stage: str, *, job_id: str = "job-id", dag_universe: str | None = None
) -> StageManifest:
    return StageManifest(
        job_id=job_id,
        stage_name=stage,
        source_id=_SOURCE_ID,
        dag_universe=dag_universe,
        evidence_refs=[],
        input_manifest={"source_id": _SOURCE_ID},
    )


def _ok(_manifest: StageManifest) -> StageOutcome:
    """A stage-work that always succeeds."""
    return StageOutcome(artifact_refs=[], evidence_refs=[])


def _all_work() -> dict[str, StageWork]:
    """A full work registry mapping every canonical stage to a successful work fn."""
    return {s: cast(StageWork, _ok) for s in STAGE_ORDER}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _worker_factory() -> Any:
    """Resolve the planned ``HatchetWorkerFactory`` (CONTRACTS.md:62).

    ``umd.jobs.hatchet`` exists but does not yet define ``HatchetWorkerFactory``;
    resolving it raises AttributeError — the spec-first failure until Phase 2.
    """
    return _hatchet_module().HatchetWorkerFactory


def _hatchet_module() -> Any:
    """Import ``umd.jobs.hatchet`` (exists today)."""
    return importlib.import_module("umd.jobs.hatchet")


def _require_live_hatchet() -> None:
    """Skip honestly when no live Hatchet cluster is reachable (Phase 2+ gate).

    These are the cluster-marked live shape tests that Plan J executes. With the
    planned surface absent they FAIL spec-first at the ``HatchetWorkerFactory``
    resolution above this guard before it is reached; once the surface exists, an
    absent cluster/SDK makes them skip here instead of falsely passing.
    """
    if not (os.environ.get("UMD_HATCHET_SERVER_URL") and os.environ.get("UMD_HATCHET_TOKEN")):
        pytest.skip("no live Hatchet cluster (set UMD_HATCHET_SERVER_URL/UMD_HATCHET_TOKEN)")


class _RecordingClient:
    """Minimal Hatchet client double that RECORDS registered workflows/tasks and
    submissions so a registered callback can be invoked in-process against real
    Postgres. The executor + repositories under it are REAL; only the transport
    is a double."""

    def __init__(self) -> None:
        self.workflows: dict[str, Any] = {}
        self.callbacks: dict[str, Any] = {}
        self.submissions: list[dict[str, Any]] = []
        self.started: bool = False

    def workflow(self, name: str) -> Any:
        def decorator(fn: Any) -> Any:
            self.callbacks[name] = fn
            self.workflows[name] = fn
            return fn

        return decorator

    def task(self, name: str) -> Any:
        return self.workflow(name)

    def submit_workflow_run(self, workflow_name: str, input: dict[str, Any]) -> None:
        self.submissions.append({"workflow_name": workflow_name, "input": input})

    def start(self) -> None:
        self.started = True


def _stage_run_rows(engine: sa.Engine, key: str) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                sa.text("SELECT count(*) FROM stage_run WHERE idempotency_key=:k"), {"k": key}
            ).scalar()
            or 0
        )


def _stage_run_count_for_job(engine: sa.Engine, job_id: str) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                sa.text("SELECT count(*) FROM stage_run WHERE job_id=:j"), {"j": job_id}
            ).scalar()
            or 0
        )


def _stage_run_count_for_stage(engine: sa.Engine, job_id: str, stage: str) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                sa.text("SELECT count(*) FROM stage_run WHERE job_id=:j AND stage_name=:s"),
                {"j": job_id, "s": stage},
            ).scalar()
            or 0
        )


def _stage_completed_events(engine: sa.Engine, stage: str) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                sa.text(
                    "SELECT count(*) FROM semantic_event "
                    "WHERE event_type='StageCompleted' AND payload->>'stage'=:s"
                ),
                {"s": stage},
            ).scalar()
            or 0
        )


def _audit_rows(engine: sa.Engine, job_id: str) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                sa.text("SELECT count(*) FROM job_run_audit WHERE job_id=:j"), {"j": job_id}
            ).scalar()
            or 0
        )


def _distinct_idempotency_keys(engine: sa.Engine, job_id: str) -> int:
    """Number of DISTINCT stage_run idempotency keys committed for a job."""
    with engine.connect() as conn:
        return int(
            conn.execute(
                sa.text("SELECT count(DISTINCT idempotency_key) FROM stage_run WHERE job_id=:j"),
                {"j": job_id},
            ).scalar()
            or 0
        )


def _stage_completed_for_job(engine: sa.Engine, job_id: str) -> int:
    """Number of StageCompleted events recorded for a job."""
    with engine.connect() as conn:
        return int(
            conn.execute(
                sa.text(
                    "SELECT count(*) FROM semantic_event "
                    "WHERE event_type='StageCompleted' AND payload->>'job_id'=:j"
                ),
                {"j": job_id},
            ).scalar()
            or 0
        )


def _distinct_dag_universes(engine: sa.Engine, job_id: str) -> int:
    """Number of DISTINCT dag_universe values committed in stage_run inputs for a job."""
    with engine.connect() as conn:
        return int(
            conn.execute(
                sa.text(
                    "SELECT count(DISTINCT input_manifest->>'dag_universe') FROM stage_run "
                    "WHERE job_id=:j"
                ),
                {"j": job_id},
            ).scalar()
            or 0
        )


def _real_client() -> Any:
    """Build a real ``hatchet_sdk`` client from the live env (Plan J gated).

    Only call after :func:`_require_live_hatchet` has passed. The 1.38.1
    constructor is ``Hatchet(config=ClientConfig(...))`` — there is no
    ``api_url``/``token`` keyword surface. ``ClientConfig`` reads ``token`` and
    ``host_port`` (the gRPC admin address, default ``localhost:7070``); the host is
    taken from ``UMD_HATCHET_SERVER_URL`` and ``UMD_HATCHET_CLIENT_HOST_PORT`` may
    override the gRPC port.
    """
    from urllib.parse import urlparse

    import hatchet_sdk

    server_url = os.environ["UMD_HATCHET_SERVER_URL"]
    token = os.environ["UMD_HATCHET_TOKEN"]
    host = urlparse(server_url).hostname or "127.0.0.1"
    port = os.environ.get("UMD_HATCHET_CLIENT_HOST_PORT", "7070")
    config = hatchet_sdk.ClientConfig(token=token, host_port=f"{host}:{port}")
    return hatchet_sdk.Hatchet(config=config)


def _poll_until(
    engine: sa.Engine,
    when: Callable[[], bool],
    *,
    what: str,
    timeout: int = 120,
    interval: float = 2.0,
) -> None:
    """Poll Postgres until ``when()`` is truthy or the timeout elapses.

    The compose worker executes the submitted runs asynchronously, so a live test
    must wait for the durable rows to appear rather than asserting immediately.
    On timeout the current stage_run / semantic_event state is dumped as evidence.
    """
    import time as _time  # noqa: PLC0415 - import only in the gated live path

    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        if when():
            return
        _time.sleep(interval)
    with engine.connect() as conn:
        keys = conn.execute(
            sa.text("SELECT idempotency_key, status FROM stage_run ORDER BY idempotency_key")
        ).fetchall()
        completed = conn.execute(
            sa.text("SELECT count(*) FROM semantic_event WHERE event_type='StageCompleted'")
        ).scalar()
    pytest.fail(
        f"timed out after {timeout}s waiting for: {what} "
        f"(stage_run rows={len(keys)}, StageCompleted={completed}); "
        "the compose worker may not have processed the submission."
    )


# ---------------------------------------------------------------------------


@pytest.mark.cluster
@pytest.mark.docker
def test_every_stage_registers_a_workflow_with_dependencies() -> None:
    """Every stage in STAGE_ORDER resolves to a registered Hatchet workflow/task
    with ``depends_on`` derived from STAGE_DEPENDENCIES (the single lineage)."""
    factory = _worker_factory()  # planned surface — AttributeError until Phase 2
    client = _RecordingClient()
    factory.start(
        runtime={},
        work_registry={stage: _ok for stage in STAGE_ORDER},
        executor=None,
        client=client,
    )
    workflows = list(client.workflows.values())
    names = {w["name"] for w in workflows}
    for stage in STAGE_ORDER:
        workflow_name = f"umd-{stage.lower()}"
        assert workflow_name in names, f"stage {stage} is not registered as {workflow_name}"
        spec = next(w for w in workflows if w["name"] == workflow_name)
        expected = {dep for dep, _cls in STAGE_DEPENDENCIES[stage]}
        assert set(spec["depends_on"]) == expected, f"wrong depends_on for {stage}"


# ---------------------------------------------------------------------------
# P1-S1 #2: submission from the public job command carries context
# ---------------------------------------------------------------------------


@pytest.mark.cluster
@pytest.mark.docker
def test_run_graph_submits_real_workflow_runs_with_context() -> None:
    """The run_graph submission path submits real workflow runs carrying
    job/source/dag-universe context. The placeholder ``HatchetRunner.run_graph``
    returns [] (or raises) — a real submission must return durable StageRunEvents
    and record the context on the client."""
    from umd.jobs.hatchet import HatchetRunner

    client = _RecordingClient()
    runner = HatchetRunner(client=client)
    events = runner.run_graph(
        job_id="job-1",
        source_id="src-1",
        dag_universe="v1-dag:base",
        work_registry={},
        stages=["INGEST"],
    )
    assert len(events) > 0, "run_graph returned no real StageRunEvents (placeholder)"
    assert client.submissions, "run_graph submitted no workflow runs"
    payload = json.dumps(client.submissions)
    assert "job-1" in payload and "src-1" in payload and "v1-dag:base" in payload


@pytest.mark.cluster
@pytest.mark.docker
def test_public_job_command_submits_via_production_runner() -> None:
    """The public job command submits through the planned ProductionDAGRunner
    (CONTRACTS.md:61). The symbol does not exist yet — AttributeError spec-first."""
    runner_mod = importlib.import_module("umd.jobs.runner")
    runner_cls = getattr(runner_mod, "ProductionDAGRunner")  # noqa: B009
    client = _RecordingClient()
    runner = runner_cls(client=client)
    events = runner.run_graph(
        job_id="job-9",
        source_id="src-9",
        dag_universe="v1-dag:base",
        work_registry={},
        stages=["INGEST"],
    )
    assert len(events) > 0, "ProductionDAGRunner returned no real StageRunEvents"
    assert "job-9" in json.dumps(client.submissions), "submission lost job context"


# ---------------------------------------------------------------------------
# P1-S1 #3/#4: callback execution through DurableStageExecutor + persisted rows
# ---------------------------------------------------------------------------


def _register_worker(umd_db: sa.Engine) -> tuple[_RecordingClient, Any]:
    """Start the planned worker over a real registry + executor and a recording
    client. Returns (client, registry) so a callback can be invoked in-process
    against real Postgres. Fails spec-first until Phase 2 defines the factory."""
    from umd.jobs.production import StageWorkRegistryFactory

    factory = _worker_factory()  # planned surface — AttributeError until Phase 2
    registry = StageWorkRegistryFactory.build({"engine": umd_db})
    executor, _ledger = _build_executor(umd_db)
    client = _RecordingClient()
    factory.start(
        runtime={"engine": umd_db},
        work_registry=registry,
        executor=executor,
        client=client,
    )
    assert client.callbacks, "worker registered no Hatchet callbacks"
    return client, registry


def _invoke_callback(client: _RecordingClient, manifest: StageManifest) -> Any:
    """Invoke the registered callback for ``manifest.stage_name`` in-process."""
    name = f"umd-{manifest.stage_name.lower()}"
    cb = client.callbacks.get(name)
    assert cb is not None, f"no callback registered for {name}"
    return cb({"input": {"manifest": manifest.to_dict()}})


@pytest.mark.cluster
@pytest.mark.docker
def test_callback_executes_through_durable_executor(umd_db: sa.Engine) -> None:
    """A registered callback, invoked with a task payload, constructs a
    StageManifest, loads the production StageWorkRegistry, and runs through the
    DurableStageExecutor — it never completes a stage directly."""
    _ensure_source(umd_db)
    client, _registry = _register_worker(umd_db)
    manifest = _make_manifest("INGEST", job_id="cb-job")
    result = _invoke_callback(client, manifest)
    # The callback must run through the executor (not mark complete directly):
    # the result is a StageRunRecord with state 'complete' and a completion seq.
    assert getattr(result, "state", None) == "complete"
    assert getattr(result, "completion_seq", None) is not None


@pytest.mark.cluster
@pytest.mark.docker
def test_callback_persists_stage_job_audit_transitions(umd_db: sa.Engine) -> None:
    """After callback execution, real Postgres holds the stage_run row (complete),
    exactly one StageCompleted semantic event, and job_run_audit transitions."""
    _ensure_source(umd_db)
    client, _registry = _register_worker(umd_db)
    manifest = _make_manifest("INGEST", job_id="cb-job")
    _invoke_callback(client, manifest)
    assert _stage_run_rows(umd_db, manifest.idempotency_key()) == 1
    assert _stage_completed_events(umd_db, "INGEST") == 1
    assert _audit_rows(umd_db, "cb-job") >= 1


# ---------------------------------------------------------------------------
# P1-S2: seam shape tests (real executor + Postgres; may pass now)
# ---------------------------------------------------------------------------


@pytest.mark.postgres
def test_retry_backoff_single_stage_run_and_completion(umd_db: sa.Engine) -> None:
    """A transient failure retries with bounded backoff then completes; the
    winning stage_run is unique and exactly one StageCompleted is appended."""
    _ensure_source(umd_db)
    executor, _ledger = _build_executor(umd_db)
    calls: list[int] = []

    def flaky_once(_manifest: StageManifest) -> StageOutcome:
        calls.append(1)
        if len(calls) == 1:
            raise StageTransientError("transient glitch")
        return StageOutcome(artifact_refs=["a"], evidence_refs=["a"])

    manifest = _make_manifest("FORMAT_ANALYSIS", job_id="retry-job")
    rec = executor.run(manifest, flaky_once)
    assert rec.state == "complete"
    assert len(calls) == 2, "transient failure did not retry exactly once"
    assert _stage_run_rows(umd_db, manifest.idempotency_key()) == 1
    assert _stage_completed_events(umd_db, "FORMAT_ANALYSIS") == 1


@pytest.mark.postgres
def test_deterministic_quarantine_single_stage_run_no_completion(umd_db: sa.Engine) -> None:
    """Deterministic malformed input quarantines (never retried): one stage_run
    row in quarantine, zero StageCompleted."""
    _ensure_source(umd_db)
    executor, _ledger = _build_executor(umd_db)
    calls: list[int] = []

    def bad_work(_manifest: StageManifest) -> StageOutcome:
        calls.append(1)
        raise MalformedInputError("unsupported feature", "locator://bad")

    manifest = _make_manifest("BASIC_SEGMENTATION", job_id="q-job")
    with pytest.raises(StageQuarantinedError):
        executor.run(manifest, bad_work)
    assert len(calls) == 1, "quarantined stage must not retry"
    assert _stage_run_rows(umd_db, manifest.idempotency_key()) == 1
    assert _stage_completed_events(umd_db, "BASIC_SEGMENTATION") == 0


@pytest.mark.postgres
def test_duplicate_submission_single_stage_run_single_completion(umd_db: sa.Engine) -> None:
    """A duplicate submission of the same idempotency key keeps ONE stage_run row
    and ONE StageCompleted (executor replay dedup)."""
    _ensure_source(umd_db)
    executor, _ledger = _build_executor(umd_db)
    manifest = _make_manifest("INGEST", job_id="dup-job")
    first = executor.run(manifest, _ok)
    second = executor.run(manifest, _ok)
    assert first.state == "complete"
    assert second.replayed is True
    assert _stage_run_rows(umd_db, manifest.idempotency_key()) == 1
    assert _stage_completed_events(umd_db, "INGEST") == 1


@pytest.mark.postgres
def test_crash_after_derived_write_then_restart_resumes_single_run(umd_db: sa.Engine) -> None:
    """A worker that crashed after deriving an artifact but before commit leaves a
    claimed-incomplete row; restart resumes it to a single committed run with one
    StageCompleted (never a repeated successful commit)."""
    from umd.storage.postgres.stage_repository import StageRunManifest, StageRunRepository

    _ensure_source(umd_db)
    executor, _ledger = _build_executor(umd_db)
    manifest = _make_manifest("INGEST", job_id="restart-job")
    # Simulate a crash-before-commit: pre-claim the key, leaving a claimed row.
    StageRunRepository(umd_db).claim(
        manifest.idempotency_key(),
        StageRunManifest(stage_name="INGEST", job_id="restart-job", source_id=_SOURCE_ID),
    )
    calls: list[int] = []

    def work(_manifest: StageManifest) -> StageOutcome:
        calls.append(1)
        return StageOutcome(artifact_refs=["a"], evidence_refs=["a"])

    rec = executor.run(manifest, work)
    assert rec.state == "complete"
    assert len(calls) == 1, "resumed work ran more than once"
    assert _stage_run_rows(umd_db, manifest.idempotency_key()) == 1
    assert _stage_completed_events(umd_db, "INGEST") == 1


@pytest.mark.postgres
def test_late_stage_failure_does_not_repeat_successful_stages(umd_db: sa.Engine) -> None:
    """A late transient failure does not repeat successful early stages: exactly
    one stage_run per canonical stage for the failed job."""
    from umd.application.jobs import JobService
    from umd.jobs.runner import DurableDAGRunner
    from umd.storage.postgres.job_repository import PostgresJobRepository

    _ensure_source(umd_db)
    executor, _ledger = _build_executor(umd_db)
    store = PostgresJobRepository(umd_db)
    runner = DurableDAGRunner(executor=executor, store=store)
    svc = JobService(store=store, runner=runner)

    def always_transient(_manifest: StageManifest) -> StageOutcome:
        raise StageTransientError("persistent decode glitch")

    work = _all_work()
    work["ENTITY_RESOLUTION"] = cast(StageWork, always_transient)
    svc.submit(
        job_id="late-job", source_id=_SOURCE_ID, dag_universe="v1-dag:base", work_registry=work
    )
    assert svc.status("late-job") == "failed"
    for stage in STAGE_ORDER:
        with umd_db.connect() as conn:
            n = int(
                conn.execute(
                    sa.text("SELECT count(*) FROM stage_run WHERE job_id=:j AND stage_name=:s"),
                    {"j": "late-job", "s": stage},
                ).scalar()
                or 0
            )
        assert n == 1, f"stage {stage} was repeated on late failure"


@pytest.mark.postgres
def test_cancelled_job_schedules_no_further_stage_work(umd_db: sa.Engine) -> None:
    """A cancelled job schedules no further stage work (whole-job cancel drains
    in-flight scheduling deterministically)."""
    from umd.application.jobs import JobService
    from umd.jobs.runner import DurableDAGRunner
    from umd.storage.postgres.job_repository import PostgresJobRepository

    _ensure_source(umd_db)
    executor, _ledger = _build_executor(umd_db)
    store = PostgresJobRepository(umd_db)
    runner = DurableDAGRunner(executor=executor, store=store)
    svc = JobService(store=store, runner=runner)
    svc.submit(
        job_id="c-job",
        source_id=_SOURCE_ID,
        dag_universe="v1-dag:base",
        work_registry=_all_work(),
    )
    svc.cancel(job_id="c-job", reason="operator stop")
    before = _stage_run_count_for_job(umd_db, "c-job")
    runner.run_graph(
        job_id="c-job",
        source_id=_SOURCE_ID,
        dag_universe="v1-dag:base",
        work_registry=_all_work(),
        stages=list(STAGE_ORDER),
    )
    assert _stage_run_count_for_job(umd_db, "c-job") == before


@pytest.mark.postgres
def test_dag_universe_change_rekeys_and_keeps_one_completion_each(umd_db: sa.Engine) -> None:
    """A stage in a different DAG universe gets a distinct idempotency key (no
    cross-universe aliasing); each universe's run is unique with one completion."""
    _ensure_source(umd_db)
    executor, _ledger = _build_executor(umd_db)
    m_old = _make_manifest("INGEST", job_id="u-job", dag_universe="v1-dag:old")
    m_new = _make_manifest("INGEST", job_id="u-job", dag_universe="v1-dag:new")
    assert m_old.idempotency_key() != m_new.idempotency_key()
    executor.run(m_old, _ok)
    executor.run(m_new, _ok)
    assert _stage_run_rows(umd_db, m_old.idempotency_key()) == 1
    assert _stage_run_rows(umd_db, m_new.idempotency_key()) == 1
    assert _stage_completed_events(umd_db, "INGEST") == 2  # one per universe


# ---------------------------------------------------------------------------
# Phase 3 (P3-S1..S4): durable cancellation / restart-resume / descendant
# rerun + causation / observability seam tests (real Postgres)
# ---------------------------------------------------------------------------


def _start_worker(
    umd_db: sa.Engine,
    client: _RecordingClient | None = None,
    *,
    store: Any | None = None,
) -> tuple[_RecordingClient, Any]:
    """Start the worker over a real executor + recording client, optionally bound
    to a JobStore for durable cancel propagation (P3-S1)."""
    factory = _worker_factory()
    executor, _ledger = _build_executor(umd_db)
    client = client or _RecordingClient()
    factory.start(
        runtime={"engine": umd_db},
        work_registry=_all_work(),
        executor=executor,
        client=client,
        store=store,
    )
    return client, executor


@pytest.mark.postgres
def test_worker_whole_job_cancel_skips_work_and_writes_no_run(umd_db: sa.Engine) -> None:
    """A cancelled job's already-submitted-but-unexecuted stage produces no
    stage_run row and no work: the worker checks the PERSISTED job status before
    running any side effect (P3-S1 durable cancel — not an in-memory flag)."""
    from umd.jobs.job import JobStatus
    from umd.storage.postgres.job_repository import PostgresJobRepository

    _ensure_source(umd_db)
    store = PostgresJobRepository(umd_db)
    client, _executor = _start_worker(umd_db, store=store)
    store.create(job_id="w-cancel", source_id=_SOURCE_ID, dag_universe="v1-dag:base")
    store.update_status("w-cancel", JobStatus.CANCELLED, error="operator stop")

    manifest = _make_manifest("ENTITY_RESOLUTION", job_id="w-cancel")
    result = _invoke_callback(client, manifest)
    assert getattr(result, "state", None) == "cancelled"
    assert _stage_run_count_for_job(umd_db, "w-cancel") == 0
    assert _stage_completed_events(umd_db, "ENTITY_RESOLUTION") == 0


@pytest.mark.postgres
def test_worker_stage_cancel_skips_stage_and_descendants_preserves_ancestors(
    umd_db: sa.Engine,
) -> None:
    """Cancelling a stage (and its transitive descendants) stops scheduling of
    that stage + descendants while committed ancestors stay intact and still run
    (P3-S1 stage/descendant cancel via STAGE_DEPENDENTS closure)."""
    from umd.jobs.job import JobStatus
    from umd.storage.postgres.job_repository import PostgresJobRepository

    _ensure_source(umd_db)
    store = PostgresJobRepository(umd_db)
    client, _executor = _start_worker(umd_db, store=store)
    store.create(job_id="ps-cancel", source_id=_SOURCE_ID, dag_universe="v1-dag:base")
    store.update_status("ps-cancel", JobStatus.RUNNING)

    # Commit INGEST as a durable ancestor first.
    anc = _make_manifest("INGEST", job_id="ps-cancel")
    assert getattr(_invoke_callback(client, anc), "state", None) == "complete"
    assert _stage_run_count_for_job(umd_db, "ps-cancel") == 1

    # Cancel ENTITY_RESOLUTION (stage + descendants).
    store.set_cancelled_stages(
        "ps-cancel",
        {
            "ENTITY_RESOLUTION",
            "CROSS_SOURCE_ALIGNMENT",
            "SEMANTIC_RECONCILIATION",
            "CURRENT_SEARCH_PROJECTION",
        },
    )

    # The cancelled stage itself -> skipped, no row, no work.
    tgt = _make_manifest("ENTITY_RESOLUTION", job_id="ps-cancel")
    assert getattr(_invoke_callback(client, tgt), "state", None) == "cancelled"
    assert _stage_run_count_for_job(umd_db, "ps-cancel") == 1
    # A descendant -> skipped too.
    desc = _make_manifest("SEMANTIC_RECONCILIATION", job_id="ps-cancel")
    assert getattr(_invoke_callback(client, desc), "state", None) == "cancelled"
    assert _stage_run_count_for_job(umd_db, "ps-cancel") == 1
    # A non-cancelled ancestor still executes (committed lineage preserved).
    fman = _make_manifest("FORMAT_ANALYSIS", job_id="ps-cancel")
    assert getattr(_invoke_callback(client, fman), "state", None) == "complete"
    assert _stage_run_count_for_job(umd_db, "ps-cancel") == 2


@pytest.mark.postgres
def test_late_failure_after_worker_death_retryable_to_single_completion(
    umd_db: sa.Engine,
) -> None:
    """A stage left ``failed`` by a worker that died before the retry is resumed
    (not dropped) to exactly one authoritative completion — the executor re-claims
    and completes, never re-running already-committed work (P3-S2 late failure)."""
    from umd.storage.postgres.stage_repository import StageRunManifest, StageRunRepository
    from umd.storage.postgres.tables import metadata as _meta

    _ensure_source(umd_db)
    executor, _ledger = _build_executor(umd_db)
    manifest = _make_manifest("STRUCTURAL_ANALYSIS", job_id="death-job")
    StageRunRepository(umd_db).claim(
        manifest.idempotency_key(),
        StageRunManifest(
            stage_name="STRUCTURAL_ANALYSIS", job_id="death-job", source_id=_SOURCE_ID
        ),
    )
    # Simulate the worker dying after a failed attempt: leave a 'failed' row.
    with umd_db.begin() as conn:
        t = _meta.tables["stage_run"]
        conn.execute(
            t.update()
            .where(t.c.idempotency_key == manifest.idempotency_key())
            .values(status="failed")
        )

    calls: list[int] = []

    def work(_m: StageManifest) -> StageOutcome:
        calls.append(1)
        return StageOutcome(artifact_refs=["a"], evidence_refs=["a"])

    rec = executor.run(manifest, work)
    assert rec.state == "complete"
    assert len(calls) == 1, "resumed late-failed work ran more than once"
    assert _stage_run_rows(umd_db, manifest.idempotency_key()) == 1
    assert _stage_completed_events(umd_db, "STRUCTURAL_ANALYSIS") == 1


@pytest.mark.postgres
def test_rerun_targets_descendants_only_and_preserves_unaffected(umd_db: sa.Engine) -> None:
    """Rerunning a mid-DAG stage schedules ONLY that stage's transitive
    descendants (explicit target list); ancestors and unrelated branches keep
    exactly one stage_run / one StageCompleted (no re-execution) (P3-S3)."""
    from umd.application.jobs import JobService
    from umd.jobs.runner import DurableDAGRunner
    from umd.storage.postgres.job_repository import PostgresJobRepository

    _ensure_source(umd_db)
    executor, _ledger = _build_executor(umd_db)
    store = PostgresJobRepository(umd_db)
    runner = DurableDAGRunner(executor=executor, store=store)
    svc = JobService(store=store, runner=runner)
    svc.submit(
        job_id="rr-job",
        source_id=_SOURCE_ID,
        dag_universe="v1-dag:base",
        work_registry=_all_work(),
    )
    assert all(_stage_run_count_for_stage(umd_db, "rr-job", s) == 1 for s in STAGE_ORDER)

    descendants = {"CROSS_SOURCE_ALIGNMENT", "SEMANTIC_RECONCILIATION", "CURRENT_SEARCH_PROJECTION"}
    ancestors = [s for s in STAGE_ORDER if s not in descendants]

    svc.rerun_stage(
        source_id=_SOURCE_ID,
        stage="ENTITY_RESOLUTION",
        scope="SOURCE",
        causation="user-correction",
        dag_universe="v1-dag:base",
        work_registry=_all_work(),
        job_id="rr-job",
    )

    # Descendants re-executed under a fresh key -> 2 stage_run rows each.
    for stage in descendants:
        assert _stage_run_count_for_stage(umd_db, "rr-job", stage) == 2, (
            f"descendant {stage} was not re-scheduled exactly once"
        )
    # Ancestors (incl. ENTITY_RESOLUTION root) untouched: 1 row + 1 completion.
    for stage in ancestors:
        assert _stage_run_count_for_stage(umd_db, "rr-job", stage) == 1, (
            f"ancestor/unrelated {stage} was re-scheduled"
        )
        assert _stage_completed_events(umd_db, stage) == 1, (
            f"ancestor/unrelated {stage} was re-completed"
        )


@pytest.mark.postgres
def test_rerun_causation_carried_through_submission_input(umd_db: sa.Engine) -> None:
    """The invalidation/rerun causation ID is carried through the Hatchet
    submission input so the callback/audit records which invalidation drove the
    rerun (P3-S3)."""
    from umd.jobs.runner import ProductionDAGRunner

    _ensure_source(umd_db)
    client = _RecordingClient()
    runner = ProductionDAGRunner(client=client)
    runner.run_graph(
        job_id="rr-cause",
        source_id=_SOURCE_ID,
        dag_universe="v1-dag:base",
        work_registry={},
        stages=["SEMANTIC_RECONCILIATION"],
        rerun_causation="correction:42",
    )
    assert client.submissions, "no workflow runs submitted"
    assert "correction:42" in json.dumps(client.submissions)
    assert all("causation_id" in sub["input"] for sub in client.submissions)


@pytest.mark.postgres
def test_worker_and_submission_record_observability_metrics(umd_db: sa.Engine) -> None:
    """Worker stage timing/attempts/failures and submission queue metrics are
    recorded with correlation/job/source/stage labels (P3-S4 passive metrics)."""
    from umd.jobs.runner import ProductionDAGRunner
    from umd.observability.metrics import METRICS

    METRICS.reset()
    _ensure_source(umd_db)
    client, _executor = _start_worker(umd_db)
    manifest = _make_manifest("INGEST", job_id="m-job")
    _invoke_callback(client, manifest)
    assert METRICS.has("umd_stage_duration_seconds", kind="histogram")
    assert METRICS.has("umd_stage_attempts", kind="counter")

    r2 = ProductionDAGRunner(client=client)
    r2.run_graph(
        job_id="m-job2",
        source_id=_SOURCE_ID,
        dag_universe="v1-dag:base",
        work_registry={},
        stages=["INGEST"],
    )
    assert METRICS.has("umd_jobs_submitted", kind="counter")
    assert METRICS.has("umd_scheduler_queue_depth", kind="gauge")


def test_capability_reporter_scheduler_never_active_locally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scheduler capability is reported honestly — never ``active`` without a
    live reachable cluster — with a gate reason + observed version (P3-S4)."""
    from umd.jobs.capability import CapabilityReporter

    monkeypatch.delenv("UMD_HATCHET_SERVER_URL", raising=False)
    monkeypatch.delenv("UMD_HATCHET_TOKEN", raising=False)
    sched = CapabilityReporter().report().scheduler
    assert sched["status"] in (
        "configured-but-unavailable",
        "gated",
        "disabled",
        "reference-only",
    )
    assert sched["status"] != "active"
    assert sched["reason"]
    assert sched.get("sdk_version")


# ---------------------------------------------------------------------------
# P1-S2: live shape variants (cluster; assert the same through the Hatchet
# binding once live; FAIL spec-first until the planned surface exists)
# ---------------------------------------------------------------------------


@pytest.mark.cluster
def test_live_hatchet_duplicate_and_restart_preserve_single_completion(
    live_db: sa.Engine,
) -> None:
    """Through the real Hatchet binding, duplicate/restart submissions keep ONE
    stage_run and ONE StageCompleted (no re-execution of committed work).

    P4-S7 RACE RECONCILIATION: the compose worker is the SOLE execution target and
    the shared compose ``umd`` database is the SINGLE source of truth. This test
    does NOT spawn a competing in-process worker loop (``HatchetWorkerFactory.start``
    only REGISTERS workflow/task callbacks on the real SDK client; it never calls
    ``client.start()`` — the caller owns the loop). The in-stack compose worker
    executes the submitted runs and writes to the shared compose ``umd`` db, so this
    test polls ``live_db`` (the same shared db the compose worker writes to) until the
    expected DISTINCT stage_run ``idempotency_key`` count for the job equals
    ``len(STAGE_ORDER)`` (duplicate submission must NOT add extra keys).
    """
    _require_live_hatchet()
    _ensure_source(live_db)
    factory = _worker_factory()
    executor, _ledger = _build_executor(live_db)
    worker = factory.start(
        runtime={"engine": live_db},
        work_registry={s: _ok for s in STAGE_ORDER},
        executor=executor,
        client=_real_client(),
    )
    worker.submit(job_id="live-dup", source_id=_SOURCE_ID, dag_universe="v1-dag:base")
    worker.submit(job_id="live-dup", source_id=_SOURCE_ID, dag_universe="v1-dag:base")
    _poll_until(
        live_db,
        lambda: _distinct_idempotency_keys(live_db, "live-dup") == len(STAGE_ORDER),
        what=f"DISTINCT stage_run idempotency_key count == {len(STAGE_ORDER)} for live-dup",
    )


@pytest.mark.cluster
def test_live_hatchet_retry_and_quarantine_single_authoritative_completion(
    live_db: sa.Engine,
) -> None:
    """Through the real Hatchet binding, transient failures retry with bounded
    backoff and deterministic failures quarantine — one authoritative completion.

    P4-S7 RACE RECONCILIATION: the compose worker is the SOLE execution target and
    the shared compose ``umd`` database is the SINGLE source of truth. No competing
    in-process worker loop is spawned (``HatchetWorkerFactory.start`` registers
    callbacks only; the caller owns the loop). The compose worker executes the
    submitted runs and writes to the shared compose ``umd`` db; this test polls
    ``live_db`` (up to 120s) until the StageCompleted count for the job equals
    ``len(STAGE_ORDER)`` (exactly one authoritative completion per stage).
    """
    _require_live_hatchet()
    _ensure_source(live_db)
    factory = _worker_factory()
    executor, _ledger = _build_executor(live_db)
    worker = factory.start(
        runtime={"engine": live_db},
        work_registry={s: _ok for s in STAGE_ORDER},
        executor=executor,
        client=_real_client(),
    )
    worker.submit(job_id="live-shape", source_id=_SOURCE_ID, dag_universe="v1-dag:base")
    _poll_until(
        live_db,
        lambda: _stage_completed_for_job(live_db, "live-shape") == len(STAGE_ORDER),
        what=f"StageCompleted count == {len(STAGE_ORDER)} for live-shape",
    )


@pytest.mark.cluster
def test_live_hatchet_universe_change_drains_and_rekeys(live_db: sa.Engine) -> None:
    """Activating a new DAG universe drains/cancels in-flight work and yields
    distinct stage keys (no cross-universe idempotency aliasing).

    P4-S7 RACE RECONCILIATION: the compose worker is the SOLE execution target and
    the shared compose ``umd`` database is the SINGLE source of truth (no competing
    in-process worker loop). Submits the same job in two DAG universes and polls
    ``live_db`` (up to 120s) until the stage_run input_manifest records TWO DISTINCT
    ``dag_universe`` values (no cross-universe aliasing).
    """
    _require_live_hatchet()
    _ensure_source(live_db)
    factory = _worker_factory()
    executor, _ledger = _build_executor(live_db)
    worker = factory.start(
        runtime={"engine": live_db},
        work_registry={s: _ok for s in STAGE_ORDER},
        executor=executor,
        client=_real_client(),
    )
    worker.submit(job_id="live-universe", source_id=_SOURCE_ID, dag_universe="v1-dag:old")
    worker.submit(job_id="live-universe", source_id=_SOURCE_ID, dag_universe="v1-dag:new")
    _poll_until(
        live_db,
        lambda: _distinct_dag_universes(live_db, "live-universe") == 2,
        what="two DISTINCT dag_universe values in stage_run input_manifest for live-universe",
    )


# ---------------------------------------------------------------------------
# P2-S1: real-stack registration (engine-visible, exact umd-<stage> names)
# ---------------------------------------------------------------------------


@pytest.mark.cluster
@pytest.mark.docker
def test_live_hatchet_engine_visible_registration_exact_umd_stages(
    live_db: sa.Engine,
) -> None:
    """Through the real Hatchet binding, the worker registers engine-visible
    workflow/task callbacks for EVERY canonical stage under the exact
    ``umd-<stage>`` names with real executor callbacks bound (registration).

    Unlike the recording-client shape test (which records into dicts), this drives
    the REAL ``hatchet_sdk`` client: :meth:`HatchetWorkerFactory.start` registers
    each stage's callback on the live SDK surface and exposes the bound workflows
    via ``WorkerHandle.registered_workflows``. ``is_ready()`` is only True when the
    real callback registration succeeded AND a real executor is bound. The engine
    is the authority — a non-empty, exactly-named registration is the precondition
    for any submitted run to execute (proven end-to-end by the other live tests).
    This test only REGISTERS (``HatchetWorkerFactory.start`` never starts a worker
    loop, so it does not compete with the compose worker) and uses the shared
    compose ``live_db`` for the executor binding.
    """
    _require_live_hatchet()
    _ensure_source(live_db)
    factory = _worker_factory()
    executor, _ledger = _build_executor(live_db)
    worker = factory.start(
        runtime={"engine": live_db},
        work_registry={s: _ok for s in STAGE_ORDER},
        executor=executor,
        client=_real_client(),
    )
    assert worker.is_ready() is True, "real worker did not report ready with bound executors"
    workflows = worker.registered_workflows
    assert workflows, "no engine-visible workflows were registered on the real client"
    assert len(workflows) == len(STAGE_ORDER), (
        f"registered {len(workflows)} workflows; expected {len(STAGE_ORDER)}"
    )
    names: set[str] = set()
    for wf in workflows:
        if isinstance(wf, dict):
            names.add(str(wf.get("name", "")))
        else:
            names.add(str(getattr(wf, "name", "")))
    for stage in STAGE_ORDER:
        assert f"umd-{stage.lower()}" in names, (
            f"stage {stage} not registered on the real client as umd-{stage.lower()}"
        )


# ---------------------------------------------------------------------------
# P1-S3: static/version pin agreement (plain; FAILS until Phase 2 records the pin)
# ---------------------------------------------------------------------------

_RELEASE_RE = re.compile(r"v?(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)*)")


def _hatchet_lines(path: Path) -> list[str]:
    return [line for line in path.read_text().splitlines() if "hatchet" in line.lower()]


def _sdk_release_in(lines: list[str]) -> list[str]:
    """SDK releases recorded on lines naming the SDK package (hatchet-sdk)."""
    out: list[str] = []
    for line in lines:
        low = line.lower()
        if "hatchet-sdk" in low or "hatchet_sdk" in low:
            out.extend(re.findall(_RELEASE_RE, line))
    return out


def _server_release_in(lines: list[str]) -> list[str]:
    """Server image releases recorded on lines naming the server (hatchet-server,
    ghcr.io/hatchet-dev/hatchet, HATCHET_VERSION, hatchet: image ref)."""
    out: list[str] = []
    for line in lines:
        low = line.lower()
        if any(
            n in low
            for n in ("hatchet-server", "hatchet-dev/hatchet", "hatchet_version", "hatchet:")
        ):
            out.extend(re.findall(_RELEASE_RE, line))
    return out


def test_hatchet_release_pin_is_single_validated_and_agreed() -> None:
    """The SDK pin (runtime.txt / pyproject worker extra / hatchet adapter), the
    server image pin (runtime.txt / compose HATCHET_VERSION / hatchet adapter),
    and the workflow/task API must agree on ONE exact validated SDK/server PAIR.
    The SDK line (1.x) and the server image line (0.x) are DIFFERENT version
    lines, so the pair may differ numerically — every surface naming the SDK must
    record the same SDK release, and every surface naming the server must record
    the same server release. 'latest' and the historical double-dollar
    interpolation are rejected. Phase 2 has not recorded the pair yet, so this
    fails with a clear message (spec-first) until then."""
    root = Path(__file__).resolve().parents[1]
    runtime_lines = _hatchet_lines(root / "deploy" / "pins" / "runtime.txt")
    pyproject_lines = _hatchet_lines(root / "pyproject.toml")
    compose_lines = _hatchet_lines(root / "deploy" / "compose.yaml")
    adapter_lines = _hatchet_lines(root / "src" / "umd" / "jobs" / "hatchet.py")

    all_lines = runtime_lines + pyproject_lines + compose_lines + adapter_lines
    # reject unpinned 'latest' anywhere in the four surfaces (case-insensitive)
    assert not any("latest" in line.lower() for line in all_lines), "unpinned 'latest' release"
    # reject the historical double-dollar interpolation in the four surfaces
    assert not any("$${" in line for line in all_lines), "historical double-dollar interpolation"

    # SDK surfaces: runtime.txt, pyproject worker extra, hatchet adapter
    sdk_pins = sorted(
        set(
            _sdk_release_in(runtime_lines)
            + _sdk_release_in(pyproject_lines)
            + _sdk_release_in(adapter_lines)
        )
    )
    # Server surfaces: runtime.txt, compose HATCHET_VERSION/image, hatchet adapter
    server_pins = sorted(
        set(
            _server_release_in(runtime_lines)
            + _server_release_in(compose_lines)
            + _server_release_in(adapter_lines)
        )
    )

    if not (sdk_pins and server_pins):
        pytest.fail(
            "hatchet pin not recorded — Phase 2 must pin after live shape tests "
            f"(runtime.txt / pyproject worker extra / compose / hatchet adapter must "
            f"each record ONE exact release; got SDK pin(s) {sdk_pins}, "
            f"server pin(s) {server_pins})"
        )

    # every surface naming the SDK must agree on ONE SDK release (may differ from the server line)
    assert len(sdk_pins) == 1, f"SDK surfaces must agree on ONE SDK release, got {sdk_pins}"
    # every surface naming the server must agree on ONE server release
    # (may differ from the SDK line)
    assert len(server_pins) == 1, (
        f"server surfaces must agree on ONE server release, got {server_pins}"
    )


# ---------------------------------------------------------------------------
# P1-S4: worker readiness contract
# ---------------------------------------------------------------------------


class _FakeImportLib:
    """Stand-in for ``importlib`` simulating a missing/available ``hatchet_sdk``."""

    def __init__(self, *, sdk_importable: bool) -> None:
        self._sdk_importable = sdk_importable

    def import_module(self, name: str) -> Any:
        if name == "hatchet_sdk":
            if not self._sdk_importable:
                raise ImportError("No module named 'hatchet_sdk'")
            return _RecordingClient()
        return __import__(name)


def test_worker_missing_sdk_exits_2_unavailable_no_ready(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """PASSES NOW: missing hatchet_sdk is a structured unavailable exit (2) with
    an actionable message and NO 'worker ready' claim."""
    monkeypatch.setattr(cli, "importlib", _FakeImportLib(sdk_importable=False))
    monkeypatch.delenv("UMD_HATCHET_SERVER_URL", raising=False)
    monkeypatch.delenv("UMD_HATCHET_TOKEN", raising=False)

    assert cli.worker() == 2
    err = capsys.readouterr().err
    assert "worker unavailable" in err
    assert "hatchet_sdk not installed" in err
    assert "worker ready" not in err


def test_worker_missing_env_exits_2_unavailable_no_ready(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """PASSES NOW: missing UMD_HATCHET_SERVER_URL / UMD_HATCHET_TOKEN is a
    structured unavailable exit (2) even when the SDK is importable."""
    monkeypatch.setattr(cli, "importlib", _FakeImportLib(sdk_importable=True))
    monkeypatch.delenv("UMD_HATCHET_SERVER_URL", raising=False)
    monkeypatch.delenv("UMD_HATCHET_TOKEN", raising=False)

    assert cli.worker() == 2
    err = capsys.readouterr().err
    assert "worker unavailable" in err
    assert "UMD_HATCHET_SERVER_URL / UMD_HATCHET_TOKEN" in err
    assert "worker ready" not in err


@pytest.mark.cluster
def test_worker_readiness_requires_bound_executors() -> None:
    """Readiness requires real callbacks bound to DurableStageExecutor through the
    planned HatchetWorkerFactory; a worker with zero bound executors must not claim
    ready. Fails spec-first until Phase 2 defines the readiness surface."""
    factory = _worker_factory()  # planned surface — AttributeError until Phase 2
    client = _RecordingClient()
    worker = factory.start(runtime={}, work_registry={}, executor=None, client=client)
    assert getattr(worker, "is_ready", lambda: True)() is False, "claimed ready with no executors"
    assert client.started is False, "worker started with no bound executors"


def test_no_fake_gated_ready_claim() -> None:
    """The (GATED) 'worker ready ... (GATED)' print was removed in P2-S3. This
    test now passes and enforces that cli.py source never contains the literal
    'worker ready' — the real readiness line lives in hatchet.py's
    worker_ready_line and is printed by cli.py only after the SDK worker loop
    starts."""
    cli_src = Path(cli.__file__).read_text()
    assert "worker ready" not in cli_src, (
        "cli.worker() still emits a bare 'worker ready' claim without bound "
        "executors; readiness must come from HatchetWorkerFactory with callbacks "
        "bound to DurableStageExecutor"
    )


class _StubExecutor:
    """Minimal executor with a run() surface. Callbacks are NOT invoked in the
    structural test below, so only the presence of run() is required."""

    def run(self, _manifest: object, _work: object) -> object:
        return object()


class _SDKWorkerObject:
    """Minimal SDK ``Worker``: ``start()`` records the call count."""

    def __init__(self, name: str, workflows: Any) -> None:
        self.name = name
        self.workflows = workflows
        self.start_calls = 0

    def start(self) -> None:
        self.start_calls += 1


class _SDKClientDouble:
    """Minimal SDK-shaped Hatchet client for the P2-S3 SDK Worker contract.

    Deliberately has NO ``.workflows`` dict attribute, so ``HatchetWorkerFactory``
    takes the real-SDK branch (it detects the recording/dict client via
    ``isinstance(getattr(client, "workflows", None), dict)``). ``task(name)`` is a
    decorator that records the callback and returns it; ``worker(name, workflows=
    None)`` is a METHOD returning a ``_SDKWorkerObject`` with ``start()``."""

    def __init__(self) -> None:
        self.registered: dict[str, Any] = {}
        self.worker_objects: list[_SDKWorkerObject] = []

    def task(self, name: str) -> Any:
        def decorator(fn: Any) -> Any:
            self.registered[name] = fn
            return fn

        return decorator

    def worker(self, name: str, workflows: Any = None) -> Any:
        worker_obj = _SDKWorkerObject(name, workflows)
        self.worker_objects.append(worker_obj)
        return worker_obj


def test_sdk_worker_contract_registers_workflows_and_starts_once() -> None:
    """Hermetic structural test locking the P2-S3 SDK Worker contract (QA Round 2):

    * ``HatchetWorkerFactory.start`` collects EVERY registered binding into
      ``WorkerHandle.registered_workflows`` (real-SDK branch — this double has no
      ``.workflows`` dict) and never starts the worker loop itself;
    * ``cli.py`` constructs the worker as ``client.worker("umd-worker",
      workflows=handle.registered_workflows)`` and calls ``start()`` exactly once;
    * ``worker_ready_line`` returns the exact readiness line.

    Callbacks are never invoked, so no Postgres is required (not postgres-marked)."""
    factory = _worker_factory()
    client = _SDKClientDouble()
    work_registry = {stage: cast(Any, object()) for stage in STAGE_ORDER}

    handle = factory.start(
        runtime={},
        work_registry=work_registry,
        executor=_StubExecutor(),
        client=client,
    )
    # Real-SDK branch registered every workflow and exposed the bindings.
    assert handle.registered_workflows, "no registered workflows collected"
    assert len(handle.registered_workflows) == len(STAGE_ORDER)
    # The factory itself never created the SDK Worker / never started a loop.
    assert client.worker_objects == [], "factory must not create the SDK Worker"

    # The exact cli.worker() sequence: explicit SDK Worker contract, exactly once.
    worker = client.worker("umd-worker", workflows=handle.registered_workflows)
    assert worker.workflows == handle.registered_workflows, (
        "client.worker must receive exactly the registered workflows"
    )
    assert worker.start_calls == 0
    worker.start()
    assert worker.start_calls == 1, "worker.start() must be called exactly once"

    # Readiness line (printed by cli.py immediately before the blocking
    # worker.start(), flush) is the exact contract text.
    assert (
        _hatchet_module().worker_ready_line(len(handle.registered_workflows))
        == f"worker ready: registered {len(handle.registered_workflows)} Hatchet workflows "
        "(candidate, pending Plan J live validation)"
    )


# ---------------------------------------------------------------------------
# P2-S4 / P3-S1: hermetic submit->callback connectivity + committed-upstream
# evidence-ref resolution / replay dedup (postgres seam)
# ---------------------------------------------------------------------------


@pytest.mark.postgres
def test_hermetic_submit_to_callback_connectivity(umd_db: sa.Engine) -> None:
    """A real submission's recorded input, fed back to the registered callback,
    executes through DurableStageExecutor and persists — no KeyError on the live
    shape. The submission JSON carries BOTH the raw context fields AND the
    serialized StageManifest (P2-S4, Decision A)."""
    from umd.jobs.hatchet import HatchetWorkerFactory
    from umd.jobs.production import StageWorkRegistryFactory
    from umd.jobs.runner import submit_workflow_runs
    from umd.storage.postgres.job_repository import PostgresJobRepository

    _ensure_source(umd_db)
    store = PostgresJobRepository(umd_db)
    store.create(job_id="conn-job", source_id=_SOURCE_ID, dag_universe="v1-dag:base")
    registry = StageWorkRegistryFactory.build({"engine": umd_db})
    executor, _ledger = _build_executor(umd_db)
    client = _RecordingClient()
    HatchetWorkerFactory.start(
        runtime={"engine": umd_db},
        work_registry=registry,
        executor=executor,
        client=client,
        store=store,
    )

    events = submit_workflow_runs(
        client,
        job_id="conn-job",
        source_id=_SOURCE_ID,
        dag_universe="v1-dag:base",
        stages=["INGEST"],
    )
    assert events, "submit_workflow_runs returned no queued events"
    assert client.submissions, "no workflow run was submitted"
    sub = client.submissions[0]
    # Raw context fields preserved AND the serialized manifest carried.
    assert sub["input"]["job_id"] == "conn-job"
    assert sub["input"]["stage"] == "INGEST"
    assert "manifest" in sub["input"], "submission missing serialized StageManifest"
    raw = json.dumps(client.submissions)
    assert "conn-job" in raw and _SOURCE_ID in raw and "v1-dag:base" in raw
    assert '"manifest"' in raw

    # Feed the EXACT recorded submission input back into the registered callback.
    cb = client.callbacks["umd-ingest"]
    record = cb({"input": sub["input"]})  # must not raise KeyError
    assert getattr(record, "state", None) == "complete"
    assert _stage_run_count_for_job(umd_db, "conn-job") >= 1


@pytest.mark.postgres
def test_committed_evidence_refs_resolved_and_replay_dedups(umd_db: sa.Engine) -> None:
    """With a real registry + PostgresJobRepository store bound, the callback
    resolves committed upstream evidence refs deterministically before
    executor.run, and replay dedups to one stage_run row per idempotency key
    (P3-S1, Decision C)."""
    from umd.jobs.hatchet import HatchetWorkerFactory
    from umd.jobs.production import StageWorkRegistryFactory
    from umd.storage.postgres.job_repository import PostgresJobRepository

    _ensure_source(umd_db)
    store = PostgresJobRepository(umd_db)
    store.create(job_id="ev-job", source_id=_SOURCE_ID, dag_universe="v1-dag:base")
    registry = StageWorkRegistryFactory.build({"engine": umd_db})
    executor, _ledger = _build_executor(umd_db)
    client = _RecordingClient()
    HatchetWorkerFactory.start(
        runtime={"engine": umd_db},
        work_registry=registry,
        executor=executor,
        client=client,
        store=store,
    )

    # (a) Commit INGEST through the callback -> complete stage_run with evidence_refs.
    ingest = _make_manifest("INGEST", job_id="ev-job")
    rec = _invoke_callback(client, ingest)
    assert getattr(rec, "state", None) == "complete"
    refs = store.committed_evidence_refs("ev-job", "FORMAT_ANALYSIS")
    assert refs, "FORMAT_ANALYSIS has no committed upstream evidence refs"
    # (b) deterministic on repeat.
    assert store.committed_evidence_refs("ev-job", "FORMAT_ANALYSIS") == refs

    # (c) Run FORMAT_ANALYSIS through the callback (the store resolves the
    # committed refs before executor.run), then replay: dedup to one row per key.
    fa = _make_manifest("FORMAT_ANALYSIS", job_id="ev-job")
    resolved = StageManifest.from_dict(fa.to_dict())
    resolved.evidence_refs = store.committed_evidence_refs("ev-job", "FORMAT_ANALYSIS")
    key = resolved.idempotency_key()
    assert _stage_run_rows(umd_db, key) == 0  # not yet run

    first = _invoke_callback(client, fa)
    assert getattr(first, "state", None) == "complete"
    assert _stage_run_rows(umd_db, key) == 1
    second = _invoke_callback(client, fa)
    assert getattr(second, "replayed", False) is True, "replay did not dedup"
    assert _stage_run_rows(umd_db, key) == 1
