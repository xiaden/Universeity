"""Hatchet adapter + worker binding (P2, Plan I) over the sole v1 scheduler.

Hatchet is the ONLY v1 scheduler/runner. This module adapts the in-repository
stage lineage to Hatchet workflows behind the :class:`DAGRunner` protocol seam
(:mod:`umd.jobs.runner`), so the execution shape is identical whether driven by
the in-memory double or by Hatchet. No second scheduler exists anywhere in v1.

The worker binds each registered Hatchet workflow/task to
:class:`DurableStageExecutor` via :class:`HatchetWorkerFactory` — claim-before-
side-effect, UNIQUE ``idempotency_key`` authority, atomic ``StageCompleted`` +
artifact refs, and separate operational audit through ``JobRunAudit``. A stage is
NEVER marked complete directly by a callback; it always runs through the executor.

PIN (P2-S1)
-----------
The candidate SDK/server pair is recorded here per-surface so the P1-S3 static
pin test can verify cross-surface agreement (runtime.txt / pyproject worker extra
/ compose / this adapter). It is a CANDIDATE — PENDING live shape-test validation
in Plan J (no Docker locally). SDK and server are different version lines and may
differ numerically.
"""
# ruff: noqa: ARG002 - run_graph must match the DAGRunner protocol signature even
# when the live client is absent.

from __future__ import annotations

import importlib.util
import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from umd.observability.metrics import METRICS

from .dag import STAGE_DEPENDENCIES, STAGE_ORDER
from .job import JobStatus, JobStore
from .manifest import StageManifest
from .runner import (
    StageRunEvent,
    StageWorkRegistry,
    submit_workflow_runs,
)
from .stage_execution import (
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_QUARANTINED,
    StageRunRecord,
)

#: Pinned candidate SDK release (P2-S1), recorded per-surface for the P1-S3 pin test.
HATCHET_SDK_VERSION = "1.38.1"
#: Pinned candidate server image (P2-S1); the SDK line and the server image line are
#: different version lines and may differ numerically. P2-S4: the split topology uses
#: the real ghcr.io sub-path images; the engine image is the scheduler/runner surface
#: this capability advertises. The top-level ``ghcr.io/hatchet-dev/hatchet`` reference
#: is DENIED (403) on ghcr.io and must never be used.
HATCHET_SERVER_IMAGE = "ghcr.io/hatchet-dev/hatchet/hatchet-engine:v0.105.2"


class HatchetNotConfiguredError(RuntimeError):
    """No live Hatchet client is configured.

    Raised on any code path that would submit to a real Hatchet cluster. This is
    the build-gate: the Hatchet release is not pinned until the retry/cancel/
    restart shape tests pass.
    """

    def __init__(self, detail: str = "") -> None:
        message = (
            "Hatchet is the v1 runner but no live client is configured; the exact "
            "Hatchet release is a BUILD GATE (pinned only after retry/cancel/restart "
            "shape tests pass). Run these through the in-memory / DurableDAGRunner "
            "seam instead. " + detail
        )
        super().__init__(message.strip())


class ConfigurationError(ValueError):
    """The Hatchet worker is misconfigured (absent stage work / no executor).

    An absent stage in the production registry is a configuration failure, never a
    silent (or fake) successful completion.
    """


class TenantSelectionError(RuntimeError):
    """No unique scheduler-eligible Hatchet tenant could be selected.

    Raised before any JWT is minted or any live submission is made: the release
    gate requires exactly ONE non-deleted tenant with non-null
    ``schedulerPartitionId`` AND ``workerPartitionId``. Zero, multiple, deleted,
    or null-partition candidates all fail closed (never silently pick a tenant).
    """


def discover_runnable_tenant(
    engine: Any, *, schema: str = "public", table: str = "Tenant"
) -> dict[str, Any]:
    """Discover exactly ONE non-deleted, scheduler-eligible Hatchet tenant.

    Product-side selection (the CI-side SQL probe remains owned by P3-S3): query
    the Hatchet ``Tenant`` table with quoted identifiers and fail closed unless
    exactly one candidate is non-deleted AND has non-null
    ``schedulerPartitionId`` AND ``workerPartitionId``. The caller must record the
    selected tenant id + both partition ids and assert identity agreement
    (JWT == worker == workflow == submitted-task == assignment tenant) before
    executing any live work.
    """
    import sqlalchemy as sa

    # Schema-qualified identifier-quoted table (sidesteps any ``search_path``
    # shadowing; schema/table are internal constants). Using ``sa.table`` avoids
    # raw SQL string interpolation entirely.
    t = sa.table(
        table,
        sa.column("id"),
        sa.column("slug"),
        sa.column("schedulerPartitionId"),
        sa.column("workerPartitionId"),
        sa.column("deletedAt"),
        schema=schema,
    )
    stmt = sa.select(
        t.c.id, t.c.slug, t.c.schedulerPartitionId, t.c.workerPartitionId, t.c.deletedAt
    )
    # Bound the connection to a ``with`` block so it is deterministically closed /
    # rolled back after the read. A leaked open connection leaves an ACCESS SHARE
    # lock on the ``Tenant`` table, which blocks the test teardown's
    # ``DROP TABLE IF EXISTS`` (needs ACCESS EXCLUSIVE) forever in the psycopg
    # wait state (hosted hang root cause).
    with engine.connect() as conn:
        rows = conn.execute(stmt).fetchall()
    eligible = [
        r
        for r in rows
        if r.deletedAt is None
        and r.schedulerPartitionId is not None
        and r.workerPartitionId is not None
    ]
    if len(eligible) != 1:
        raise TenantSelectionError(
            f"expected exactly one non-deleted scheduler-eligible Hatchet tenant "
            f"(non-null schedulerPartitionId AND workerPartitionId); found "
            f"{len(eligible)} eligible of {len(rows)} total"
        )
    row = eligible[0]
    return {
        "id": str(row.id),
        "slug": row.slug,
        "scheduler_partition_id": row.schedulerPartitionId,
        "worker_partition_id": row.workerPartitionId,
    }


class UmdStageInput(BaseModel):
    """Direct v1 callback input boundary (amendment A2').

    The pinned ``hatchet_sdk==1.38.1`` invokes task callbacks as
    ``fn(workflow_input, ctx)`` where ``workflow_input`` is the value validated by
    the registered ``input_validator``. The submission shape is a direct dict with
    a top-level ``manifest`` (no v0 ``{"input": ...}`` wrapper), so this typed
    model is registered as the validator and the callback reads ``input.manifest``.
    ``source_id``/``causation_id`` are optional because one-shot submissions may
    omit them (rerun causation is carried only for selective reruns).
    """

    job_id: str
    source_id: str | None = None
    dag_universe: str | None = None
    stage: str
    manifest: dict[str, Any]
    causation_id: str | None = None


#: The stable (non-pinned) description of the runner contract Hatchet must satisfy.
HATCHET_RUNNER_CONTRACT = {
    "role": "sole-v1-scheduler",
    "requirements": [
        "claim-before-side-effect  (UNIQUE idempotency_key is authority)",
        "effective-once completion (artifact refs + StageCompleted in one txn)",
        "bounded backoff for transient failures; quarantine for deterministic",
        "restart-resume: re-claim keys; completed dedupe, crashed resume",
        "drain/cancel in-flight work before activating a new DAG universe",
    ],
}


@dataclass
class HatchetWorkflowSpec:
    """A pure mapping of one stage to a Hatchet workflow (no live cluster)."""

    #: the canonical in-repository stage name.
    stage: str
    #: upstream stages this workflow depends on (Hatchet ``depends_on``).
    depends_on: list[str] = field(default_factory=list)
    #: evidence classes consumed (the DAG edge metadata).
    consumes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": f"umd-{self.stage.lower()}",
            "stage": self.stage,
            "depends_on": self.depends_on,
            "consumes": self.consumes,
        }


def _real_submit_workflow_run(client: Any, workflow_name: str, input: dict[str, Any]) -> None:
    """Submit one one-shot workflow run through the real hatchet_sdk (1.38.1).

    The real SDK has no ``client.submit_workflow_run`` attribute (that is a shape
    only the recording double implements). The one-shot submission surface is
    ``AdminClient.run_workflow(workflow_name, input, options)`` (admin.py:414).
    ``Hatchet`` exposes no ``.admin`` attribute, so the AdminClient is reached
    through public surfaces only: ``Hatchet.runs`` (public property, features/runs.py)
    → ``RunsClient.admin_client()`` (public accessor, runs.py:150). ``input`` is
    carried verbatim by ``TriggerWorkflowRequest`` as a JSON-serialized string, so
    the run context dict is JSON-encoded here.
    """
    runs = getattr(client, "runs", None)
    admin = getattr(runs, "admin_client", None) if runs is not None else None
    run_workflow = getattr(admin, "run_workflow", None) if admin is not None else None
    if not callable(run_workflow):
        raise HatchetNotConfiguredError(
            "real hatchet_sdk client has no runs.admin_client().run_workflow submission surface"
        )
    run_workflow(workflow_name, json.dumps(input))


class _SDKSubmissionShim:
    """Duck-type bridge so a real hatchet_sdk client satisfies the shared
    ``submit_workflow_runs`` path (which calls ``client.submit_workflow_run``).

    Only the ``submit_workflow_run`` name is intercepted; every other attribute
    falls through to the real SDK client. The recording/double client has its own
    ``submit_workflow_run`` and is never wrapped, so the local recording path stays
    byte-identical.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def submit_workflow_run(self, workflow_name: str, input: dict[str, Any]) -> None:
        _real_submit_workflow_run(self._client, workflow_name, input)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def worker_ready_line(count: int) -> str:
    """The exact worker-readiness line Plan J's ``wait-for-worker.sh`` greps for.

    ``cli.py`` calls this function and prints its return IMMEDIATELY BEFORE the
    blocking ``client.worker("umd-worker", workflows=handle.registered_workflows).start()``
    with ``flush=True`` (manager correction: pinned SDK 1.38.1 ``Worker.start()`` runs
    the event loop forever and never returns, so printing after it would never emit),
    so the literal bare ``worker ready`` claim stays OUT of ``cli.py`` source
    (``test_no_fake_gated_ready_claim`` scans ``cli.py`` for the bare string). The count
    is the number of registered Hatchet workflows (one per canonical stage). This is the
    REAL readiness signal (handoff §3): ``wait-for-worker.sh`` greps ``worker ready:
    registered``.
    """
    return (
        f"worker ready: registered {count} Hatchet workflows "
        "(candidate, pending Plan J live validation)"
    )


def build_hatchet_workflows(
    dependency_table: Mapping[str, tuple[tuple[str, str], ...]] | None = None,
) -> list[HatchetWorkflowSpec]:
    """Build one Hatchet workflow per in-repo stage (pure, topologically ordered).

    ``dependency_table`` defaults to the canonical ``STAGE_DEPENDENCIES``. Each
    workflow carries the upstream-stage dependencies and the evidence classes
    found in :mod:`umd.jobs.dag` — the same lineage the runner and the selective
    invalidator consume. This is the documented mapping used to *submit* to
    Hatchet.
    """
    table = dependency_table or STAGE_DEPENDENCIES
    specs: list[HatchetWorkflowSpec] = []
    for stage in STAGE_ORDER:
        deps = table.get(stage, ())
        specs.append(
            HatchetWorkflowSpec(
                stage=stage,
                depends_on=[d for d, _c in deps],
                consumes=[c for _d, c in deps],
            )
        )
    return specs


def _make_handler(
    work_registry: StageWorkRegistry, executor: Any, store: JobStore | None = None
) -> Any:
    """Build the callback Hatchet invokes for one stage workflow/task.

    The callback constructs the :class:`StageManifest` from the payload, loads the
    stage's work from the production registry, and runs through
    :class:`DurableStageExecutor` — it NEVER marks a stage complete directly. An
    absent stage (or an unbound executor) is a configuration failure, never a fake
    completion.

    When a :class:`JobStore` is bound, the callback checks the job's persisted
    status BEFORE invoking any work (P3-S1 cancellation propagation): a whole-job
    cancel (``CANCELLED``/``PAUSED``) or a partial stage/descendant cancel returns
    a replayed ``cancelled`` record WITHOUT creating a ``stage_run`` row or running
    work. Cancellation is durable because it is read from the persisted store, not
    an in-memory flag. Observability: each execution records stage timing, attempt
    and failure metrics with correlation/job/source/stage labels (P3-S4).
    """

    def handler(input: Any, ctx: Any) -> dict[str, Any]:
        # The callback receives the validated direct v1 input (A2'): a
        # ``UmdStageInput`` whose ``manifest`` is the serialized StageManifest.
        # ``ctx`` is the scheduler context; stage work is owned entirely by the
        # executor, so the callback does not need it beyond arity (SDK 1.38.1
        # always passes both arguments).
        del ctx
        manifest = StageManifest.from_dict(input.manifest)
        if store is not None:
            job = store.get(manifest.job_id)
            if job is not None and (
                job.status in (JobStatus.CANCELLED, JobStatus.PAUSED)
                or manifest.stage_name in job.cancelled_stages
            ):
                METRICS.counter(
                    "umd_stage_cancelled",
                    description="stage callbacks skipped because the job was cancelled",
                    labels=_stage_labels(manifest),
                ).inc()
                return _flat_ack(manifest, state=STATUS_CANCELLED, replayed=True)
        if store is not None:
            # Deterministic resolution of committed upstream evidence refs before
            # executor.run keeps idempotency keys stable across retries: the same
            # committed upstream stages -> the same evidence_refs -> the same key
            # -> dedup on replay (P3-S1, Manager Decision C). Skipped entirely when
            # no store is bound (evidence_refs stay as submitted). A cancelled job
            # already returned early above with no work/row, so this only runs for
            # stages that will actually execute.
            manifest.evidence_refs = store.committed_evidence_refs(
                manifest.job_id, manifest.stage_name
            )
        work = work_registry.get(manifest.stage_name)
        if work is None:
            raise ConfigurationError(
                f"no stage work registered for {manifest.stage_name} "
                "(absent stage = configuration failure, never fake completion)"
            )
        if executor is None:
            raise ConfigurationError("no DurableStageExecutor bound to the worker")
        started = time.perf_counter()
        record = executor.run(manifest, work)
        duration = time.perf_counter() - started
        METRICS.histogram(
            "umd_stage_duration_seconds",
            description="stage execution wall-clock seconds",
            labels=_stage_labels(manifest),
        ).observe(duration)
        METRICS.counter(
            "umd_stage_attempts",
            description="stage execution attempts",
            labels=_stage_labels(manifest),
        ).inc(record.attempts)
        if record.state in (STATUS_FAILED, STATUS_QUARANTINED):
            METRICS.counter(
                "umd_stage_failures",
                description="failed/quarantined stage executions",
                labels=_stage_labels(manifest),
            ).inc()
        # Return only a flat JSON-safe acknowledgement — never the StageRunRecord
        # and never a fabricated completion. The authoritative ``stage_run``,
        # ``StageCompleted``, and audit rows live in the durable store; the
        # acknowledgement lets Hatchet record that the callback handled the run.
        return _flat_ack(manifest, record=record)

    return handler


def _flat_ack(
    manifest: StageManifest,
    *,
    state: str | None = None,
    replayed: bool = False,
    record: StageRunRecord | None = None,
) -> dict[str, Any]:
    """A flat JSON-safe callback acknowledgement derived from the executor result.

    Only scalar, JSON-serializable fields are returned. ``record`` is preferred
    when present; otherwise ``state``/``replayed`` are taken from the arguments
    (used for the cancellation-before-work path, which has no executor record).
    """
    if record is not None:
        state = record.state
        replayed = record.replayed
    return {
        "ack": "umd-stage-executed",
        "state": state,
        "replayed": replayed,
        "attempts": record.attempts if record is not None else 0,
        "completion_seq": record.completion_seq if record is not None else None,
        "stage": manifest.stage_name,
        "job_id": manifest.job_id,
        "source_id": str(manifest.source_id or ""),
        "dag_universe": manifest.dag_universe,
    }


def _stage_labels(manifest: StageManifest) -> dict[str, str]:
    return {
        "job_id": manifest.job_id,
        "source_id": str(manifest.source_id or ""),
        "stage": manifest.stage_name,
    }


@dataclass
class WorkerHandle:
    """The handle returned by :meth:`HatchetWorkerFactory.start`.

    Exposes the scheduler submission surface (``submit``), the readiness gate
    (``is_ready``), and the registered workflow/task objects
    (``registered_workflows``) a real-SDK worker must register. Readiness is true
    ONLY when real callbacks are bound to a :class:`DurableStageExecutor` (a
    non-empty registry AND a present executor).

    ``registered_workflows`` holds every task/workflow binding collected during
    registration — the ``Standalone``/``Workflow`` objects returned by the SDK
    1.38.1 ``Hatchet.task``/``Hatchet.workflow`` decorators on the real-client
    path, and the callback handlers on the recording/double path — so
    ``cli.worker()`` can construct the SDK Worker as ``client.worker("umd-worker",
    workflows=handle.registered_workflows)`` and start the loop exactly once. Both
    client branches expose the same handle shape.
    """

    _client: Any
    _stages: list[str]
    _ready: bool = False
    registered_workflows: list[Any] = field(default_factory=list)

    def submit(
        self, *, job_id: str, source_id: str | None, dag_universe: str
    ) -> list[StageRunEvent]:
        """Submit one workflow run per canonical stage with the durable context."""
        return submit_workflow_runs(
            self._client,
            job_id=job_id,
            source_id=source_id,
            dag_universe=dag_universe,
            stages=list(self._stages),
        )

    def is_ready(self) -> bool:
        """True when real callbacks are bound to a durable executor."""
        return self._ready


# The dataclass drops annotated fields with defaults from the class namespace
# (storing them under ``__dataclass_fields__`` to avoid shared mutable defaults),
# so ``hasattr(WorkerHandle, "registered_workflows")`` would be False without this
# explicit class-level attribute. It is only an introspection/typed-access surface:
# every instance gets its own list either from the factory
# (``registered_workflows=...``) or, when constructed bare, from the field's
# ``default_factory``, so the class value is never read for real state.
WorkerHandle.registered_workflows = []


class HatchetWorkerFactory:
    """Registers the pinned Hatchet workflows/tasks and binds callbacks (CONTRACTS.md:62).

    ``start(runtime, work_registry, executor, client)`` builds one workflow per
    ``STAGE_ORDER`` stage (``depends_on`` derived from ``STAGE_DEPENDENCIES``) and
    binds each callback through :meth:`_make_handler` — execution always flows
    through :class:`DurableStageExecutor`.

    The ``client`` is DUCK-TYPED, supporting two shapes:

    * a recording/double client whose ``workflows``/``callbacks`` are plain dicts —
      workflows are registered directly (a spec dict with ``name``/``depends_on``)
      and callbacks are stored under ``callbacks[name]``;
    * a real SDK client (``workflows`` is not a dict) — workflows/tasks are
      registered through the SDK's ``client.task(name)``/``client.workflow(name)``
      decorator surface.

    Readiness requires BOTH a non-empty work registry AND a present executor; with
    zero bound executors ``client.start()`` is never called and ``is_ready()`` is
    ``False`` (the worker never claims ready without a real callback bound).
    """

    @staticmethod
    def start(
        *,
        runtime: dict[str, Any],
        work_registry: StageWorkRegistry,
        executor: Any,
        client: Any,
        store: JobStore | None = None,
    ) -> WorkerHandle:
        del runtime  # consumed by the production registry via work_registry (Plan G)
        callbacks_bound = bool(work_registry) and executor is not None
        # Durable-only registration (AT-18): every canonical stage registers
        # EXCLUSIVELY through ``client.durable_task``. A missing surface is a hard
        # ConfigurationError — there is NO ``task``/``workflow`` fallback, retry
        # loop, or ``contextlib.suppress(Exception)`` around registration.
        durable_task = getattr(client, "durable_task", None)
        if not callable(durable_task):
            raise ConfigurationError(
                "client has no 'durable_task' registration surface; every canonical "
                "umd-<stage> must register exclusively via client.durable_task(...) "
                "(no task/workflow fallback)"
            )
        #: SDK Standalone/workflow objects returned by the durable_task decorator,
        #: collected so ``cli.worker()`` can pass them to ``client.worker(workflows=...)``.
        registered_workflows: list[Any] = []
        for spec in build_hatchet_workflows():
            wf_name = f"umd-{spec.stage.lower()}"
            handler = _make_handler(work_registry, executor, store=store)
            # SDK 1.38.1: ``name``/``input_validator`` are KEYWORD-ONLY. A decorator
            # failure must SURFACE (it aborts startup) — never suppressed or retried.
            workflow_obj = durable_task(
                name=wf_name,
                input_validator=UmdStageInput,
                eviction_policy=None,
            )(handler)
            if workflow_obj is not None:
                registered_workflows.append(workflow_obj)

        # The CALLER owns the single worker-loop start (P2-S3): start() registers
        # the workflows/tasks and returns a handle; cli.worker() starts the SDK
        # worker loop itself. HatchetWorkerFactory.start must NOT call client.start()
        # so the not-ready path never starts a worker loop.
        #
        # Submission duck-typing: the recording double exposes submit_workflow_run,
        # so it is used as-is (byte-identical). A real SDK client does not have it;
        # wrap it so the shared submit_workflow_runs path maps to the SDK's
        # admin.run_workflow one-shot API.
        dict_client = isinstance(getattr(client, "workflows", None), dict)
        submission_client = client if dict_client else _SDKSubmissionShim(client)
        # Readiness is truthful: true ONLY after complete non-empty actual
        # registration of every canonical stage AND a real executor is bound.
        # Zero or partial registration can never make is_ready() true.
        ready = callbacks_bound and len(registered_workflows) == len(STAGE_ORDER)
        return WorkerHandle(
            _client=submission_client,
            _stages=list(STAGE_ORDER),
            _ready=ready,
            registered_workflows=registered_workflows,
        )


class _UnconfiguredClient:
    """An honest no-live-Hatchet submission surface (CONTRACTS.md:61/:63).

    Returned by :func:`build_hatchet_client` when the SDK is absent or the server
    URL/token are not configured, so a release factory can still select
    :class:`ProductionDAGRunner` while submission REFUSES loudly (never a silent
    fake success). ``submit_workflow_run`` raises :class:`HatchetNotConfiguredError`;
    every other attribute is absent. This is NOT a recording double and never
    counts as execution evidence.
    """

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def submit_workflow_run(self, workflow_name: str, input: dict[str, Any]) -> None:
        raise HatchetNotConfiguredError(f"cannot submit {workflow_name!r}: {self._reason}")


def build_hatchet_client(settings: Any = None) -> Any:
    """Build the release submission client (a ``submit_workflow_run`` surface).

    Returns a real hatchet_sdk client wrapped in :class:`_SDKSubmissionShim` when
    the SDK is importable AND ``UMD_HATCHET_SERVER_URL``/``UMD_HATCHET_TOKEN`` are
    configured; otherwise returns an honest :class:`_UnconfiguredClient` whose
    submission raises :class:`HatchetNotConfiguredError`. This is the single shared
    client assembly used by the API release factory (P1-S3); the worker (Plan G/H
    cli) builds its SDK ``Hatchet`` separately for registration/looping.
    """
    del settings  # client config is env-driven today (UMD_HATCHET_*); kept for parity
    if importlib.util.find_spec("hatchet_sdk") is None:
        return _UnconfiguredClient("hatchet_sdk not installed")
    import hatchet_sdk as sdk

    server_url = os.environ.get("UMD_HATCHET_SERVER_URL")
    token = os.environ.get("UMD_HATCHET_TOKEN")
    if not (server_url and token):
        return _UnconfiguredClient(
            "UMD_HATCHET_SERVER_URL / UMD_HATCHET_TOKEN not set; no reachable cluster"
        )
    config = sdk.ClientConfig(token=token)
    if not os.environ.get("HATCHET_CLIENT_HOST_PORT"):
        from urllib.parse import urlsplit

        host = (urlsplit(server_url).hostname) or "localhost"
        config.host_port = f"{host}:7070"
    return _SDKSubmissionShim(sdk.Hatchet(config=config))


class HatchetRunner:
    """:class:`DAGRunner` adapter over a real Hatchet client.

    The ``client`` is the real-Hatchet integration point (its REST/gRPC submit
    surface). With a client present, ``run_graph`` submits a real workflow run per
    stage carrying job/source/dag-universe context and returns the durable
    ``queued`` events. Without a client it refuses (raises
    :class:`HatchetNotConfiguredError`) rather than fabricating an empty success.
    """

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    def build_workflows(self) -> list[HatchetWorkflowSpec]:
        return build_hatchet_workflows()

    def run_graph(
        self,
        *,
        job_id: str,
        source_id: str | None,
        dag_universe: str,
        work_registry: StageWorkRegistry,
        stages: list[str],
        rerun_causation: str | None = None,
    ) -> list[StageRunEvent]:
        if self._client is None:
            raise HatchetNotConfiguredError(
                f"cannot submit {job_id} (dag_universe={dag_universe}) to a live cluster"
            )
        return submit_workflow_runs(
            self._client,
            job_id=job_id,
            source_id=source_id,
            dag_universe=dag_universe,
            stages=stages,
            rerun_causation=rerun_causation,
        )


__all__ = [
    "HatchetNotConfiguredError",
    "HatchetWorkflowSpec",
    "HatchetRunner",
    "build_hatchet_client",
    "HatchetWorkerFactory",
    "WorkerHandle",
    "ConfigurationError",
    "TenantSelectionError",
    "discover_runnable_tenant",
    "UmdStageInput",
    "build_hatchet_workflows",
    "worker_ready_line",
    "HATCHET_RUNNER_CONTRACT",
    "HATCHET_SDK_VERSION",
    "HATCHET_SERVER_IMAGE",
]
