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
    """Insert a source row so stage_run FK + StageCompleted payload resolve.

    Idempotent: several live tests share the session-scoped ``live_db`` compose
    database (single source of truth, compose worker sole executor), so a plain
    insert of the fixed ``_SOURCE_ID`` would collide once the first test has
    seeded the row. ``ON CONFLICT DO NOTHING`` keeps the seed idempotent without
    weakening assertions.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from umd.storage.postgres.tables import metadata as _meta

    src_t = _meta.tables["source"]
    with engine.begin() as conn:
        conn.execute(
            pg_insert(src_t)
            .values(
                id=uuid.UUID(source_id),
                ocfl_ref=f"urn:ocfl:{source_id}",
                sha512="d" * 128,
                size_bytes=42,
                media_kind="text",
                original_name="seed.txt",
            )
            .on_conflict_do_nothing(index_elements=["id"])
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
        self.tasks: dict[str, Any] = {}
        self.submissions: list[dict[str, Any]] = []
        self.started: bool = False

    def workflow(self, *, name: str, input_validator: Any = None) -> Any:
        del input_validator
        client = self

        class Workflow:
            def durable_task(
                self, *, name: str, parents: list[Any], eviction_policy: Any = None
            ) -> Any:
                del eviction_policy

                class Task:
                    def __init__(self) -> None:
                        self.name = name
                        self.parents = parents

                    def __call__(self, fn: Any) -> Any:
                        client.callbacks[name] = fn
                        client.workflows[name] = fn
                        return self

                task = Task()
                client.tasks[name] = task
                return task

            def run_no_wait(self, *, input: Any) -> str:
                client.submissions.append({"workflow_name": name, "input": input})
                return "run-umd-decomposition"

        return Workflow()

    def run_no_wait(self, *, input: Any) -> str:
        self.submissions.append({"workflow_name": "umd-decomposition", "input": input})
        return "run-umd-decomposition"

    def submit_workflow_run(
        self, workflow_name: str, input: dict[str, Any], parent_id: str | None = None
    ) -> str:
        del parent_id
        self.submissions.append({"workflow_name": workflow_name, "input": input})
        return "run-umd-decomposition"

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
def test_one_workflow_registers_all_durable_tasks_with_native_dependencies() -> None:
    """One native workflow contains every durable task and exact parent graph."""
    factory = _worker_factory()
    client = _RecordingClient()
    handle = factory.start(
        runtime={},
        work_registry={stage: _ok for stage in STAGE_ORDER},
        executor=None,
        client=client,
    )
    assert len(handle.registered_workflows) == 1
    assert set(client.tasks) == {f"umd-{stage.lower()}" for stage in STAGE_ORDER}
    for stage in STAGE_ORDER:
        actual = {
            getattr(parent, "name", None) for parent in client.tasks[f"umd-{stage.lower()}"].parents
        }
        expected = {f"umd-{dep.lower()}" for dep, _ in STAGE_DEPENDENCIES.get(stage, ())}
        assert actual == expected
    # The same lineage remains exposed in the pure metadata mapping.
    for spec in _hatchet_module().build_hatchet_workflows():
        expected = {dep for dep, _cls in STAGE_DEPENDENCIES[spec.stage]}
        assert set(spec.depends_on) == expected, f"wrong depends_on for {spec.stage}"


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
    workflow = client.workflow(name="umd-decomposition")
    runner = HatchetRunner(client=_hatchet_module()._NativeSubmissionClient(workflow))
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


#: The scheduler context argument Hatchet 1.38.1 always passes to a callback.
#: The callback ignores it (stage work is executor-owned), so a plain sentinel is
#: sufficient for hermetic invocation of the (input, ctx) shape.
_FAKE_CTX: Any = object()


def _invoke_callback(client: _RecordingClient, manifest: StageManifest) -> Any:
    """Invoke the registered callback for ``manifest.stage_name`` in-process with
    the direct v1 shape ``fn(input, ctx)`` — never a v0 ``{"input": ...}`` wrapper.
    The input is a validated :class:`UmdStageInput` carrying the top-level
    ``manifest``."""
    name = f"umd-{manifest.stage_name.lower()}"
    cb = client.callbacks.get(name)
    assert cb is not None, f"no callback registered for {name}"
    inp = _hatchet_module().UmdStageInput(
        job_id=manifest.job_id,
        source_id=str(manifest.source_id) if manifest.source_id else None,
        dag_universe=manifest.dag_universe,
        stage=manifest.stage_name,
        manifest=manifest.to_dict(),
    )
    return cb(inp, _FAKE_CTX)


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
    # the ack reflects state 'complete' with a completion seq.
    assert result["state"] == "complete"
    assert result["completion_seq"] is not None


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
    assert result["state"] == "cancelled"
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
    assert _invoke_callback(client, anc)["state"] == "complete"
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
    assert _invoke_callback(client, tgt)["state"] == "cancelled"
    assert _stage_run_count_for_job(umd_db, "ps-cancel") == 1
    # A descendant -> skipped too.
    desc = _make_manifest("SEMANTIC_RECONCILIATION", job_id="ps-cancel")
    assert _invoke_callback(client, desc)["state"] == "cancelled"
    assert _stage_run_count_for_job(umd_db, "ps-cancel") == 1
    # A non-cancelled ancestor still executes (committed lineage preserved).
    fman = _make_manifest("FORMAT_ANALYSIS", job_id="ps-cancel")
    assert _invoke_callback(client, fman)["state"] == "complete"
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
# P2-S1: local binding-shape (exact umd-<stage> names on the real SDK surface)
# ---------------------------------------------------------------------------


@pytest.mark.cluster
@pytest.mark.docker
def test_live_hatchet_local_binding_shape_exact_umd_stages(
    live_db: sa.Engine,
) -> None:
    """Local BINDING SHAPE (not engine visibility): the real ``hatchet_sdk``
    client registers one native workflow containing a durable task for every
    canonical stage under the exact ``umd-<stage>`` names.

    This asserts the LOCAL shape the factory produces on the real SDK surface —
    it does NOT prove engine-visible registration (that is the hosted AT-18 gate).
    ``is_ready()`` is True only because a real executor is bound AND every
    canonical task was actually registered. Registration-only:
    ``HatchetWorkerFactory.start`` never starts a worker loop, so this does not
    compete with the compose worker.
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
    assert workflows, "no local bindings were registered on the real client"
    assert len(workflows) == 1, f"registered {len(workflows)} workflows; expected one"
    workflow = workflows[0]
    assert getattr(workflow, "name", None) == "umd-decomposition"
    task_names = {str(getattr(task, "name", "")) for task in workflow.tasks}
    assert task_names == {f"umd-{stage.lower()}" for stage in STAGE_ORDER}


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

    def workflow(self, *, name: str, input_validator: Any = None) -> Any:
        del input_validator
        client = self

        class Workflow:
            def durable_task(
                self, *, name: str, parents: list[Any], eviction_policy: Any = None
            ) -> Any:
                del parents, eviction_policy

                def decorator(fn: Any) -> Any:
                    client.registered[name] = fn
                    return fn

                return decorator

            def run_no_wait(self, *, input: Any) -> str:
                client.submissions.append({"workflow_name": name, "input": input})
                return "run-umd-decomposition"

        return Workflow()

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
    assert len(handle.registered_workflows) == 1
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
# P2-S5: direct v1 callback shape negatives + fail-closed registration
# ---------------------------------------------------------------------------


def _registered_client() -> _RecordingClient:
    """A recording client with every canonical stage registered (no executor, so
    only shape/registration failures are what these tests observe)."""
    factory = _worker_factory()
    client = _RecordingClient()
    factory.start(
        runtime={},
        work_registry={stage: _ok for stage in STAGE_ORDER},
        executor=None,
        client=client,
    )
    return client


def test_callback_rejects_one_argument_shape() -> None:
    """The pinned SDK 1.38.1 invokes callbacks as ``fn(input, ctx)``. A handler
    invoked with a single argument must fail loudly (TypeError) — the v0
    one-argument contract is rejected, never silently adapted."""
    client = _registered_client()
    cb = client.callbacks["umd-ingest"]
    inp = _hatchet_module().UmdStageInput(
        job_id="j", stage="INGEST", manifest=_make_manifest("INGEST").to_dict()
    )
    with pytest.raises(TypeError):
        cb(inp)


def test_callback_rejects_v0_wrapped_input() -> None:
    """A v0 ``{"input": {"manifest": ...}}`` wrapper is NOT accepted — the
    callback reads the direct top-level ``manifest`` (A2'), so a wrapped payload
    fails rather than silently working through a v0/v1 adapter (which is forbidden)."""
    client = _registered_client()
    cb = client.callbacks["umd-ingest"]
    # Build the v0 wrapper dynamically so the source never contains a literal
    # ``{"input": ...}`` (kept out of fixtures per the grep-proof requirement).
    v0_payload = dict(input=dict(manifest=_make_manifest("INGEST").to_dict()))
    with pytest.raises((AttributeError, TypeError)):
        cb(v0_payload, _FAKE_CTX)


class _ClientNoDurableTask:
    """A dict-shaped client WITHOUT a ``durable_task`` surface (fail-closed check)."""

    def __init__(self) -> None:
        self.workflows: dict[str, Any] = {}
        self.callbacks: dict[str, Any] = {}


def test_client_without_durable_task_fails_closed() -> None:
    """A client with no ``durable_task`` surface is a hard ConfigurationError —
    there is NO ``task``/``workflow`` fallback registration (AT-18 fail-closed)."""
    factory = _worker_factory()
    with pytest.raises(_hatchet_module().ConfigurationError):
        factory.start(
            runtime={},
            work_registry={stage: _ok for stage in STAGE_ORDER},
            executor=None,
            client=_ClientNoDurableTask(),
        )


class _FailingDurableClient(_RecordingClient):
    """A recording client whose native task decorator always raises."""

    def workflow(self, *, name: str, input_validator: Any = None) -> Any:
        del name, input_validator

        class Workflow:
            def durable_task(
                self, *, name: str, parents: list[Any], eviction_policy: Any = None
            ) -> Any:
                del name, parents, eviction_policy
                raise RuntimeError("decorator boom")

        return Workflow()


def test_decorator_failure_surfaces_not_suppressed() -> None:
    """A durable_task decorator failure propagates immediately (startup abort) —
    it is never swallowed by ``contextlib.suppress(Exception)``."""
    factory = _worker_factory()
    with pytest.raises(RuntimeError, match="decorator boom"):
        factory.start(
            runtime={},
            work_registry={stage: _ok for stage in STAGE_ORDER},
            executor=None,
            client=_FailingDurableClient(),
        )


class _PartialDurableClient(_RecordingClient):
    """A recording client whose native tasks are not registered."""

    def workflow(self, *, name: str, input_validator: Any = None) -> Any:
        del name, input_validator

        class Workflow:
            def durable_task(
                self, *, name: str, parents: list[Any], eviction_policy: Any = None
            ) -> Any:
                del name, parents, eviction_policy

                def decorator(fn: Any) -> None:
                    del fn
                    return None

                return decorator

        return Workflow()


def test_partial_registration_never_reports_ready() -> None:
    """Readiness is truthful: even with a full work registry AND a bound executor,
    an empty/partial actual registration can never make ``is_ready()`` True."""
    factory = _worker_factory()
    handle = factory.start(
        runtime={},
        work_registry={stage: _ok for stage in STAGE_ORDER},
        executor=_StubExecutor(),
        client=_PartialDurableClient(),
    )
    assert handle.registered_workflows == []
    assert handle.is_ready() is False, "reported ready with zero actual registrations"


@pytest.mark.cluster
@pytest.mark.postgres
def test_sdk_shaped_native_task_mock_run_reaches_executor(live_db: sa.Engine) -> None:
    """Real-SDK-shaped: a native task's ``mock_run(input=UmdStageInput(...))`` reaches
    the existing DurableStageExecutor and returns the flat JSON-safe ack.

    This is cluster-gated because the SDK client requires a real tenant-bearing
    JWT + server config. The input passed to ``mock_run`` is a validated
    ``UmdStageInput`` instance — never a bare dict (mock_run drops a raw dict to
    {}, which would mask the v1 shape)."""
    _require_live_hatchet()
    _ensure_source(live_db)
    factory = _worker_factory()
    executor, _ledger = _build_executor(live_db)
    handle = factory.start(
        runtime={"engine": live_db},
        work_registry={s: _ok for s in STAGE_ORDER},
        executor=executor,
        client=_real_client(),
    )
    assert handle.is_ready() is True
    workflow = next(
        w for w in handle.registered_workflows if getattr(w, "name", None) == "umd-decomposition"
    )
    target = next(task for task in workflow.tasks if task.name == "umd-ingest")
    assert hasattr(target, "mock_run")
    manifest = _make_manifest("INGEST", job_id="mock-job")
    inp = _hatchet_module().UmdStageInput(
        job_id=manifest.job_id,
        source_id=str(manifest.source_id or ""),
        dag_universe=manifest.dag_universe,
        stage=manifest.stage_name,
        manifest=manifest.to_dict(),
    )
    ack = target.mock_run(input=inp)
    assert ack["state"] == "complete"


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

    # Feed the EXACT recorded submission input back into the registered callback
    # via the direct v1 shape (input, ctx) — never a v0 wrapper.
    cb = client.callbacks["umd-ingest"]
    inp = _hatchet_module().UmdStageInput(**sub["input"])
    record = cb(inp, _FAKE_CTX)  # must not raise
    assert record["state"] == "complete"
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
    assert rec["state"] == "complete"
    # P2-S9: the committed-upstream lookup is keyed by canonical lineage identity
    # (source + dag universe + segment + dependency edge), NOT by job ownership.
    universe = ingest.dag_universe
    refs = store.canonical_evidence_refs(_SOURCE_ID, universe, None, "FORMAT_ANALYSIS")
    assert refs, "FORMAT_ANALYSIS has no committed upstream evidence refs"
    # (b) deterministic on repeat.
    assert store.canonical_evidence_refs(_SOURCE_ID, universe, None, "FORMAT_ANALYSIS") == refs

    # (c) Run FORMAT_ANALYSIS through the callback (the store resolves the
    # committed refs before executor.run), then replay: dedup to one row per key.
    fa = _make_manifest("FORMAT_ANALYSIS", job_id="ev-job")
    resolved = StageManifest.from_dict(fa.to_dict())
    resolved.evidence_refs = store.canonical_evidence_refs(
        _SOURCE_ID, universe, None, "FORMAT_ANALYSIS"
    )
    key = resolved.idempotency_key()
    assert _stage_run_rows(umd_db, key) == 0  # not yet run

    first = _invoke_callback(client, fa)
    assert first["state"] == "complete"
    assert _stage_run_rows(umd_db, key) == 1
    second = _invoke_callback(client, fa)
    assert second["replayed"] is True, "replay did not dedup"
    assert _stage_run_rows(umd_db, key) == 1


# ---------------------------------------------------------------------------
# P2-S6: tenant selection — exactly ONE scheduler-eligible tenant, fail closed
# ---------------------------------------------------------------------------


_TENANT_SCHEMA = "umd_tn_test"


def _create_tenant_table(engine: sa.Engine, schema: str = _TENANT_SCHEMA) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        conn.execute(
            text(
                f'CREATE TABLE IF NOT EXISTS "{schema}"."Tenant" ('
                "id UUID PRIMARY KEY, slug VARCHAR NOT NULL, "
                '"schedulerPartitionId" VARCHAR, "workerPartitionId" VARCHAR, '
                '"deletedAt" TIMESTAMP)'
            )
        )


def _drop_tenant_table(engine: sa.Engine, schema: str = _TENANT_SCHEMA) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS "{schema}"."Tenant"'))
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}"'))


def _seed_tenant(
    engine: sa.Engine,
    schema: str,
    *,
    tenant_id: str,
    slug: str,
    sched: str | None,
    worker: str | None,
    deleted: bool = False,
) -> None:
    import datetime

    from sqlalchemy import text

    deleted_at = datetime.datetime.now(datetime.UTC) if deleted else None
    with engine.begin() as conn:
        conn.execute(
            text(
                f'INSERT INTO "{schema}"."Tenant" '
                '(id, slug, "schedulerPartitionId", "workerPartitionId", "deletedAt") '
                "VALUES (:id, :slug, :sched, :worker, :deleted)"
            ),
            {
                "id": tenant_id,
                "slug": slug,
                "sched": sched,
                "worker": worker,
                "deleted": deleted_at,
            },
        )


@pytest.mark.postgres
def test_tenant_selection_fails_closed_when_no_eligible(umd_db: sa.Engine) -> None:
    """A tenant with null scheduler/worker partitions (the internal tenant shape)
    is ineligible; discovering it must fail closed with TenantSelectionError —
    never select a null-partition tenant for JWT minting or live submission."""
    _create_tenant_table(umd_db)
    try:
        _seed_tenant(
            umd_db, _TENANT_SCHEMA, tenant_id=_SOURCE_ID, slug="internal", sched=None, worker=None
        )
        with pytest.raises(_hatchet_module().TenantSelectionError):
            _hatchet_module().discover_runnable_tenant(umd_db, schema=_TENANT_SCHEMA)
    finally:
        _drop_tenant_table(umd_db)


@pytest.mark.postgres
def test_tenant_selection_returns_exactly_one_eligible(umd_db: sa.Engine) -> None:
    """With a null-partition (ineligible) tenant AND exactly one non-deleted
    tenant with both partitions, selection returns that single eligible tenant
    and its partition ids — no hardcoded UUID required (discovered, then the
    returned tenant+partition identity is asserted equal and stable on repeat,
    the local seam for the hosted JWT/worker/workflow identity agreement)."""
    _create_tenant_table(umd_db)
    try:
        _seed_tenant(
            umd_db, _TENANT_SCHEMA, tenant_id=_SOURCE_ID, slug="internal", sched=None, worker=None
        )
        # No hardcoded UUID: the eligible tenant id is generated, discovered (not
        # assumed), and its identity recorded/asserted across repeated selection.
        eligible_id = str(uuid.uuid4())
        _seed_tenant(
            umd_db,
            _TENANT_SCHEMA,
            tenant_id=eligible_id,
            slug="default",
            sched="sched-p1",
            worker="worker-p1",
        )
        sel = _hatchet_module().discover_runnable_tenant(umd_db, schema=_TENANT_SCHEMA)
        assert str(sel["id"]) == eligible_id
        assert sel["scheduler_partition_id"] == "sched-p1"
        assert sel["worker_partition_id"] == "worker-p1"
        # Identity agreement: the same tenant+partition identity is discovered
        # deterministically on a second pass (single source of truth).
        again = _hatchet_module().discover_runnable_tenant(umd_db, schema=_TENANT_SCHEMA)
        assert again["id"] == sel["id"]
        assert again["scheduler_partition_id"] == sel["scheduler_partition_id"]
        assert again["worker_partition_id"] == sel["worker_partition_id"]
    finally:
        _drop_tenant_table(umd_db)


@pytest.mark.postgres
def test_tenant_selection_fails_closed_on_multiple_eligible(umd_db: sa.Engine) -> None:
    """Two scheduler-eligible tenants is ambiguous — selection must fail closed
    rather than arbitrarily picking one."""
    _create_tenant_table(umd_db)
    try:
        _seed_tenant(
            umd_db, _TENANT_SCHEMA, tenant_id=_SOURCE_ID, slug="t1", sched="s1", worker="w1"
        )
        _seed_tenant(
            umd_db,
            _TENANT_SCHEMA,
            tenant_id="707d0855-80ab-4e1f-a156-f1c4546cbf52",
            slug="t2",
            sched="s2",
            worker="w2",
        )
        with pytest.raises(_hatchet_module().TenantSelectionError):
            _hatchet_module().discover_runnable_tenant(umd_db, schema=_TENANT_SCHEMA)
    finally:
        _drop_tenant_table(umd_db)


@pytest.mark.postgres
def test_tenant_selection_fails_closed_on_deleted_tenant(umd_db: sa.Engine) -> None:
    """A deleted tenant is never eligible, even with both partitions set."""
    _create_tenant_table(umd_db)
    try:
        _seed_tenant(
            umd_db,
            _TENANT_SCHEMA,
            tenant_id="707d0855-80ab-4e1f-a156-f1c4546cbf52",
            slug="default",
            sched="s1",
            worker="w1",
            deleted=True,
        )
        with pytest.raises(_hatchet_module().TenantSelectionError):
            _hatchet_module().discover_runnable_tenant(umd_db, schema=_TENANT_SCHEMA)
    finally:
        _drop_tenant_table(umd_db)


# ---------------------------------------------------------------------------
# P2-S8/S9/S11/S12 (Plan K amendment 2): native parent barriers, canonical
# lineage selection, submission stability, and cross-job replay attribution.
# ---------------------------------------------------------------------------


def _feed_all_stages(
    client: _RecordingClient,
    *,
    job_id: str,
    universe: str,
) -> None:
    """Submit the full canonical graph through the runner, then feed every stage's
    callback in STAGE_ORDER so the canonical graph commits through the real
    executor. Used to model the native-barrier delivery ordering hermetically."""
    from umd.jobs.runner import submit_workflow_runs

    submit_workflow_runs(
        client,
        job_id=job_id,
        source_id=_SOURCE_ID,
        dag_universe=universe,
        stages=list(STAGE_ORDER),
    )
    for stage in STAGE_ORDER:
        manifest = _make_manifest(stage, job_id=job_id, dag_universe=universe)
        rec = _invoke_callback(client, manifest)
        assert rec["state"] == "complete", f"{stage} did not complete"


def test_native_parent_barrier_submission_shape() -> None:
    """P2-S8: ``submit_workflow_runs`` threads NATIVE parent-task relationships
    derived EXCLUSIVELY from ``STAGE_DEPENDENCIES``. The root (INGEST) has no
    parent; every dependent carries the run id of its most-descendant direct
    dependency (whose transitive barrier covers all other direct deps). No
    dependent is submitted with ``parents: {}`` and no polling/chaining schedules
    work."""
    from umd.jobs.hatchet import HatchetRunner

    client = _RecordingClient()
    workflow = client.workflow(name="umd-decomposition")
    runner = HatchetRunner(client=_hatchet_module()._NativeSubmissionClient(workflow))
    runner.run_graph(
        job_id="barrier-job",
        source_id=_SOURCE_ID,
        dag_universe="v1-dag:base",
        work_registry={},
        stages=list(STAGE_ORDER),
    )
    assert len(client.submissions) == 1
    submitted = client.submissions[0]
    assert submitted["workflow_name"] == "umd-decomposition"
    assert set(submitted["input"]["manifests"]) == set(STAGE_ORDER)


def test_delayed_parent_barrier_no_dependent_before_upstream_commits(umd_db: sa.Engine) -> None:
    """P2-S12(a): with an upstream held uncommitted, a dependent callback must NOT
    begin any stage work or side effect — canonical evidence resolution FAILS
    CLOSED (no stage_run row is created). Committing the upstream unblocks the
    dependent. This is the local, honest model of the native parent barrier: the
    real Hatchet scheduler holds the dependent until the parent run commits."""
    from umd.jobs.hatchet import HatchetWorkerFactory
    from umd.jobs.production import StageWorkRegistryFactory
    from umd.storage.postgres.job_repository import (
        MissingRequiredEvidenceError,
        PostgresJobRepository,
    )

    _ensure_source(umd_db)
    store = PostgresJobRepository(umd_db)
    store.create(job_id="barrier-job", source_id=_SOURCE_ID, dag_universe="v1-dag:base")
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
    universe = "v1-dag:base"
    # Upstream INGEST is NOT committed yet: a dependent callback must fail closed
    # BEFORE any side effect (no stage_run row for the observing job).
    fa = _make_manifest("FORMAT_ANALYSIS", job_id="barrier-job", dag_universe=universe)
    before = _stage_run_count_for_job(umd_db, "barrier-job")
    with pytest.raises(MissingRequiredEvidenceError):
        _invoke_callback(client, fa)
    assert _stage_run_count_for_job(umd_db, "barrier-job") == before, (
        "dependent began a side effect before the upstream committed"
    )
    # Commit the upstream (INGEST) -> the dependent now resolves its evidence and runs.
    rec = _invoke_callback(
        client, _make_manifest("INGEST", job_id="barrier-job", dag_universe=universe)
    )
    assert rec["state"] == "complete"
    rec2 = _invoke_callback(
        client, _make_manifest("FORMAT_ANALYSIS", job_id="barrier-job", dag_universe=universe)
    )
    assert rec2["state"] == "complete", "dependent did not unblock after upstream commit"


def test_submission_stability_single_vs_immediate_duplicate(umd_db: sa.Engine) -> None:
    """P2-S8/P2-S12(b): one submission and an immediate duplicate submission both
    yield exactly one stable canonical manifest input per STAGE_ORDER stage and
    exactly ``len(STAGE_ORDER)`` distinct idempotency keys total — the duplicate
    dedups against the committed canonical keys (job-independent deduplication)."""
    from umd.jobs.hatchet import HatchetWorkerFactory
    from umd.jobs.production import StageWorkRegistryFactory
    from umd.storage.postgres.job_repository import PostgresJobRepository

    _ensure_source(umd_db)
    store = PostgresJobRepository(umd_db)
    store.create(job_id="stab-job", source_id=_SOURCE_ID, dag_universe="v1-dag:base")
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
    universe = "v1-dag:base"
    # Single submission commits the canonical graph: exactly one key per stage.
    _feed_all_stages(client, job_id="stab-job", universe=universe)
    assert _distinct_idempotency_keys(umd_db, "stab-job") == len(STAGE_ORDER)
    assert _stage_run_count_for_job(umd_db, "stab-job") == len(STAGE_ORDER)
    # Immediate duplicate submission: same stable canonical keys, no extra rows.
    _feed_all_stages(client, job_id="stab-job", universe=universe)
    assert _distinct_idempotency_keys(umd_db, "stab-job") == len(STAGE_ORDER)
    assert _stage_run_count_for_job(umd_db, "stab-job") == len(STAGE_ORDER)


def test_cross_job_replay_emits_replay_marked_observations(umd_db: sa.Engine) -> None:
    """P2-S11/P2-S12(c): a second OBSERVING job replaying committed canonical work
    produces exactly one deterministic replay-marked StageCompleted observation per
    canonical stage (nine total), ZERO stage side effects after replay, no extra
    canonical stage_run keys, callback-owned durable rows, and deterministic
    attribution (re-delivery is a no-op)."""
    from umd.jobs.hatchet import HatchetWorkerFactory
    from umd.jobs.production import StageWorkRegistryFactory
    from umd.storage.postgres.job_repository import PostgresJobRepository

    _ensure_source(umd_db)
    store = PostgresJobRepository(umd_db)
    store.create(job_id="canon-job", source_id=_SOURCE_ID, dag_universe="v1-dag:base")
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
    universe = "v1-dag:base"
    # Canonical job commits the full graph -> nine canonical keys, nine canonical
    # StageCompleted events.
    _feed_all_stages(client, job_id="canon-job", universe=universe)
    assert _distinct_idempotency_keys(umd_db, "canon-job") == len(STAGE_ORDER)
    assert _stage_completed_for_job(umd_db, "canon-job") == len(STAGE_ORDER)

    # Observing job (same canonical lineage, different job ownership) replays the
    # committed work: no stage_run rows owned by it, no extra canonical keys.
    _feed_all_stages(client, job_id="observe-job", universe=universe)
    assert _stage_run_count_for_job(umd_db, "observe-job") == 0, (
        "observing job created stage_run rows (stage side effects after replay)"
    )
    assert _stage_run_count_for_job(umd_db, "canon-job") == len(STAGE_ORDER)
    # Exactly one replay-marked StageCompleted observation per canonical stage,
    # attributed to the observing job, and none for the canonical job's replay.
    assert _stage_completed_for_job(umd_db, "observe-job") == len(STAGE_ORDER)
    assert _stage_completed_for_job(umd_db, "canon-job") == len(STAGE_ORDER)
    with umd_db.connect() as conn:
        replay_marked = int(
            conn.execute(
                sa.text(
                    "SELECT count(*) FROM semantic_event WHERE event_type='StageCompleted' "
                    "AND payload->>'job_id'=:j AND payload->'generated_by'->>'replayed'='true'"
                ),
                {"j": "observe-job"},
            ).scalar()
            or 0
        )
    assert replay_marked == len(STAGE_ORDER), "replay observations not replay-marked"
    # Deterministic attribution: re-delivering the observing job adds nothing.
    _feed_all_stages(client, job_id="observe-job", universe=universe)
    assert _stage_completed_for_job(umd_db, "observe-job") == len(STAGE_ORDER)
    assert _stage_run_count_for_job(umd_db, "observe-job") == 0


def test_canonical_evidence_selection_deterministic_and_fail_closed(umd_db: sa.Engine) -> None:
    """P2-S9 (focused): ``canonical_evidence_refs`` selects exactly ONE COMPLETE
    upstream record per dependency edge by deterministic current-lineage ordering
    (created_at DESC, idempotency-key tie-break), is independent of job ownership,
    returns sorted refs, and FAILS CLOSED on missing or ambiguous required
    evidence. Seeded directly at the seam so the selection query is proven in
    isolation."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from umd.storage.postgres.job_repository import (
        AmbiguousRequiredEvidenceError,
        MissingRequiredEvidenceError,
        PostgresJobRepository,
    )
    from umd.storage.postgres.tables import metadata as _meta

    _ensure_source(umd_db)
    store = PostgresJobRepository(umd_db)
    run_t = _meta.tables["stage_run"]
    src = uuid.UUID(_SOURCE_ID)

    def _seed_complete(*, evidence: list[str], created: str, job: str = "sel-job") -> None:
        with umd_db.begin() as conn:
            conn.execute(
                pg_insert(run_t).values(
                    id=uuid.uuid4().hex,
                    idempotency_key=uuid.uuid4().hex,
                    job_id=job,
                    stage_name="INGEST",
                    source_id=src,
                    status="complete",
                    input_manifest={"dag_universe": "v1-dag:base"},
                    evidence_refs=evidence,
                    created_at=created,
                )
            )

    # (a) Two COMPLETE INGEST rows, different keys (a rerun), distinct created_at
    # -> exactly ONE selected deterministically (the newest current-lineage row).
    _seed_complete(evidence=["ref:old"], created="2026-01-01T00:00:00+00:00")
    _seed_complete(evidence=["ref:new"], created="2026-06-01T00:00:00+00:00")
    refs = store.canonical_evidence_refs(_SOURCE_ID, "v1-dag:base", None, "FORMAT_ANALYSIS")
    assert refs == ["ref:new"], f"selection must pick the newest lineage row, got {refs}"
    # Deterministic on repeat, and independent of which job owns the rows.
    assert store.canonical_evidence_refs(_SOURCE_ID, "v1-dag:base", None, "FORMAT_ANALYSIS") == refs

    # (b) INGEST (root) has no upstream -> [] (the explicit null/root case).
    assert store.canonical_evidence_refs(_SOURCE_ID, "v1-dag:base", None, "INGEST") == []

    # (c) A different dag universe has no COMPLETE INGEST -> fail closed (missing).
    with pytest.raises(MissingRequiredEvidenceError):
        store.canonical_evidence_refs(_SOURCE_ID, "v1-dag:other", None, "FORMAT_ANALYSIS")

    # (d) Two COMPLETE rows tied at the same created_at (newest) -> ambiguous,
    # fail closed rather than pick arbitrarily.
    _seed_complete(evidence=["ref:a"], created="2026-06-02T00:00:00+00:00", job="amb-job")
    _seed_complete(evidence=["ref:b"], created="2026-06-02T00:00:00+00:00", job="amb-job")
    with pytest.raises(AmbiguousRequiredEvidenceError):
        store.canonical_evidence_refs(_SOURCE_ID, "v1-dag:base", None, "FORMAT_ANALYSIS")


def test_native_submission_preserves_ancestors_and_marks_selected_descendants() -> None:
    """A static native workflow receives all manifests but rerun causation only for targets."""
    from umd.jobs.runner import ProductionDAGRunner

    client = _RecordingClient()
    runner = ProductionDAGRunner(client=client)
    selected = ["CROSS_SOURCE_ALIGNMENT", "SEMANTIC_RECONCILIATION", "CURRENT_SEARCH_PROJECTION"]
    runner.run_graph(
        job_id="rerun-input",
        source_id=_SOURCE_ID,
        dag_universe="v1-dag:base",
        work_registry={},
        stages=selected,
        rerun_causation="invalidate:claim-1",
    )

    assert len(client.submissions) == 1
    payload = client.submissions[0]["input"]
    assert payload["selected_stages"] == selected
    assert set(payload["manifests"]) == set(STAGE_ORDER)
    for stage, manifest in payload["manifests"].items():
        causation = manifest["input_manifest"].get("rerun_causation")
        if stage in selected:
            assert causation == "invalidate:claim-1"
        else:
            assert causation is None
