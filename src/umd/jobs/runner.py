"""Durable DAG runner + the runner protocol seam (P1-S4).

The runner is the *only* place that schedules stages in the lineage. For v1 it is
deliberately thin: it iterates the in-repository DAG in dependency order and
delegates each stage to the :class:`DurableStageExecutor` (claim-before-side-
effect + effective-once completion). Restart/drain semantics are inherited from
the executor + the drain gate — there is no scheduler state to reconcile.

The :class:`DAGRunner` protocol is the **Hatchet seam**: the in-repository
execution shape is identical whether driven by the in-memory double here or by
the Hatchet adapter (:mod:`umd.jobs.hatchet`). Hatchet is the ONLY v1 scheduler;
this file adds no second scheduler.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from umd.observability.metrics import METRICS

from .dag import STAGE_DEPENDENCIES, STAGE_DEPENDENTS, STAGE_ORDER
from .job import JobStatus, JobStore, StageState
from .manifest import StageManifest
from .stage_execution import (
    STATUS_COMPLETE,
    DurableStageExecutor,
    StageRunRecord,
    StageWork,
)

#: ``stage_name -> StageWork`` (Phase 2/3 stages plug in here; tests inject doubles).
StageWorkRegistry = Mapping[str, StageWork]


@dataclass
class StageRunEvent:
    """Observable outcome of running one stage through the runner."""

    stage: str
    status: str
    replayed: bool = False


class DAGRunner(Protocol):
    """Runner protocol — the Hatchet adapter implements this same shape.

    ``run_graph`` schedules exactly the given ``stages`` (a dependency-ordered
    subset of the lineage, e.g. all stages for a fresh submit, or a descendant
    closure for a selective rerun).
    """

    def run_graph(
        self,
        *,
        job_id: str,
        source_id: str | None,
        dag_universe: str,
        work_registry: StageWorkRegistry,
        stages: list[str],
        rerun_causation: str | None = None,
    ) -> list[StageRunEvent]: ...


class DurableDAGRunner:
    """Runner that drives :class:`DurableStageExecutor` over the lineage.

    Reads the job's cancelled status from the store before each stage so a
    whole-job cancel (or a single-stage cancel) stops scheduling deterministically.
    """

    def __init__(self, *, executor: DurableStageExecutor, store: JobStore) -> None:
        self._executor = executor
        self._store = store

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
        events: list[StageRunEvent] = []
        #: Dependency-gated evidence flow: each stage's manifest carries the prior
        #: committed outputs as evidence_refs/input (child_manifests semantics), so
        #: evidence classes flow INGEST -> FORMAT_ANALYSIS -> ... -> PROJECTION.
        #: Seed from the job's committed upstream outputs so a retry/rerun/
        #: crash-resume reproduces the first-uncommitted stage's ORIGINAL
        #: idempotency key (evidence_refs are idempotency material) instead of
        #: re-seeding ``[]`` and duplicating stage_run rows.
        prior_refs = self._seed_prior_refs(job_id, stages[0] if stages else None)
        for stage in stages:
            job = self._store.get(job_id)
            if job is None:
                break
            if job.status in (JobStatus.CANCELLED, JobStatus.PAUSED):
                break  # whole-job cancel/pause -> stop scheduling descendents
            if stage in job.cancelled_stages:
                self._observe(job_id, stage, "cancelled", None, 0)
                events.append(StageRunEvent(stage, "cancelled", replayed=True))
                continue
            manifest = _manifest_for(
                job_id,
                source_id,
                dag_universe,
                stage,
                evidence_refs=prior_refs,
                rerun_causation=rerun_causation,
            )
            work = work_registry.get(stage)
            if work is None:
                self._observe(job_id, stage, "pending", None, 0)
                events.append(StageRunEvent(stage, "pending"))
                continue
            record = self._executor.run(manifest, work)
            self._observe(
                job_id,
                stage,
                record.state,
                record.claim.idempotency_key,
                record.attempts,
            )
            events.append(StageRunEvent(stage, record.state, replayed=record.replayed))
            if record.state == STATUS_COMPLETE:
                prior_refs = _committed_refs(record, prior_refs)
        return events

    def _seed_prior_refs(self, job_id: str, first: str | None) -> list[str]:
        """Seed ``prior_refs`` from the job's committed upstream stage outputs.

        Reads the COMPLETE ``stage_run`` rows that precede the first requested
        stage (via the executor) so a retry/rerun/crash-resume reproduces the
        original first-uncommitted idempotency key — no duplicate ``stage_run``
        rows, no lost committed evidence chain. Falls back to ``[]`` for test
        doubles (e.g. ``FakeExecutor``) that expose no DB read, preserving the
        existing empty-refs behavior.
        """
        reader = getattr(self._executor, "committed_prior_refs", None)
        if reader is None:
            return []
        return list(reader(job_id, first))

    def _observe(
        self, job_id: str, stage: str, status: str, key: str | None, attempts: int
    ) -> None:
        self._store.record_stage(job_id, StageState(stage, status, key, attempts))


def _manifest_for(
    job_id: str,
    source_id: str | None,
    dag_universe: str,
    stage: str,
    *,
    evidence_refs: list[str] | None = None,
    rerun_causation: str | None = None,
) -> StageManifest:
    """Build a stage manifest carrying the prior committed outputs as evidence_refs.

    ``job_id`` remains excluded from idempotency material (job-independent
    dedup), and the DAG universe is carried through unchanged.
    """
    input_manifest: dict[str, Any] = {"source_id": source_id or ""}
    if rerun_causation is not None:
        # Carry the invalidation/rerun causation through the stage input so the
        # durable stage_run.input_manifest records WHICH invalidation caused the
        # rerun (P3-S3). Folding it into the digest yields a fresh idempotency
        # key, so an invalidated descendant actually re-executes instead of
        # replaying against its prior committed key.
        input_manifest["rerun_causation"] = rerun_causation
    return StageManifest(
        job_id=job_id,
        stage_name=stage,
        source_id=source_id,
        dag_universe=dag_universe,
        evidence_refs=list(evidence_refs or []),
        input_manifest=input_manifest,
    )


def _committed_refs(record: StageRunRecord, prior: list[str]) -> list[str]:
    """Merge a just-completed stage's artifact refs into the downstream evidence.

    Works with both real :class:`StageRunRecord` results and test doubles that
    carry no ``outcome`` (returns ``prior`` unchanged).
    """
    outcome = getattr(record, "outcome", None)
    refs = getattr(outcome, "artifact_refs", None)
    if refs:
        merged = list(prior)
        for ref in refs:
            if ref not in merged:
                merged.append(ref)
        return merged
    return prior


def submit_workflow_runs(
    client: Any,
    *,
    job_id: str,
    source_id: str | None,
    dag_universe: str,
    stages: list[str],
    rerun_causation: str | None = None,
) -> list[StageRunEvent]:
    """Submit one Hatchet workflow run per stage, carrying the durable context.

    Submission is asynchronous: each stage executes later in the worker's callback
    (through :class:`DurableStageExecutor`, see :mod:`umd.jobs.hatchet`). The
    returned events are therefore ``queued`` — never a fabricated ``complete``.
    This is the shared submission shape for both :class:`HatchetRunner` and
    :class:`ProductionDAGRunner` (CONTRACTS.md:61).
    """
    events: list[StageRunEvent] = []
    # Native parent-task barriers (P2-S8). Each stage's submission carries the run id
    # of its LATEST direct dependency in the STAGE_DEPENDENCIES DAG as ``parent_id``,
    # threading a topologically-ordered chain. Because the graph is transitively
    # closed (STAGE_DEPENDENTS), the most-descendant direct dependency itself waits on
    # every other direct dependency, so a single native parent edge gives a FULL
    # barrier for multi-parent stages (e.g. ENTITY_RESOLUTION's two upstreams are
    # transitively ordered). INGEST is the root (no deps) and is submitted with no
    # parent. No dependent is ever submitted with ``parents: {}`` and no polling /
    # chaining loop schedules work — this is a pure native Hatchet relationship.
    run_ids: dict[str, str] = {}
    for stage in stages:
        workflow_name = f"umd-{stage.lower()}"
        # The serialized StageManifest is the durable correlation unit the worker
        # callback consumes via StageManifest.from_dict (idempotency-key material).
        # It starts with evidence_refs=[]; the callback resolves committed upstream
        # refs from the bound JobStore before executor.run (P2-S4, Decision A) —
        # never at submission time. Folding rerun_causation into input_manifest
        # mirrors DurableDAGRunner._manifest_for so an invalidated descendant
        # rekeys and actually re-executes (P3-S3).
        manifest = _manifest_for(
            job_id, source_id, dag_universe, stage, rerun_causation=rerun_causation
        )
        run_input: dict[str, Any] = {
            # Raw context fields are preserved for submission-context consumers.
            "job_id": job_id,
            "source_id": source_id,
            "dag_universe": dag_universe,
            "stage": stage,
            "manifest": manifest.to_dict(),
        }
        if rerun_causation is not None:
            # Explicit descendant-rerun causation carried to the worker callback
            # so the audit/stage_run records which invalidation drove this submit
            # (P3-S3).
            run_input["causation_id"] = rerun_causation
        deps = [dep for dep, _cls in STAGE_DEPENDENCIES.get(stage, ())]
        parent_stage = max(deps, key=STAGE_ORDER.index) if deps else None
        parent_id = run_ids.get(parent_stage) if parent_stage is not None else None
        run_id = client.submit_workflow_run(workflow_name, input=run_input, parent_id=parent_id)
        if isinstance(run_id, str) and run_id:
            run_ids[stage] = run_id
        events.append(StageRunEvent(stage, "queued"))
    # Passive observability (P3-S4): a queued submission per stage + the queue
    # depth for this job. No second scheduler/process loop — just honest gauges.
    labels = {"job_id": job_id, "source_id": str(source_id or "")}
    METRICS.counter(
        "umd_jobs_submitted",
        description="stage workflow runs submitted to the scheduler",
        labels=labels,
    ).inc(len(stages))
    METRICS.gauge(
        "umd_scheduler_queue_depth",
        description="stage workflow runs queued for the job",
        labels=labels,
    ).set(float(len(stages)))
    return events


class ProductionDAGRunner:
    """Production :class:`DAGRunner` over the sole Hatchet scheduler.

    CONTRACTS.md:61 — the production implementation of the runner seam. It
    dispatches each stage to a real Hatchet workflow run (the worker's callback
    executes through :class:`DurableStageExecutor`) and reports the durable
    ``queued`` state. It never fabricates completion. Test-only synchronous doubles
    are excluded from production factories.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

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
        # Submission is asynchronous (worker callback runs the executor), so the
        # registry is not consumed here — retained for protocol signature parity.
        del work_registry
        return submit_workflow_runs(
            self._client,
            job_id=job_id,
            source_id=source_id,
            dag_universe=dag_universe,
            stages=stages,
            rerun_causation=rerun_causation,
        )


#: Default scheduling order for a fresh source decomposition.
def initial_stages() -> list[str]:
    return list(STAGE_ORDER)


#: Dependents map consumed by the selective invalidation planner.
lineage_map = STAGE_DEPENDENTS

__all__ = [
    "DAGRunner",
    "DurableDAGRunner",
    "ProductionDAGRunner",
    "StageRunEvent",
    "StageWorkRegistry",
    "initial_stages",
    "lineage_map",
    "submit_workflow_runs",
]
