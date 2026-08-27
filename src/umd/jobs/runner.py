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
from typing import Protocol

from .dag import STAGE_DEPENDENTS, STAGE_ORDER
from .job import JobStatus, JobStore, StageState
from .manifest import StageManifest
from .stage_execution import DurableStageExecutor, StageWork

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
    ) -> list[StageRunEvent]:
        events: list[StageRunEvent] = []
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
            manifest = _manifest_for(job_id, source_id, dag_universe, stage)
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
        return events

    def _observe(
        self, job_id: str, stage: str, status: str, key: str | None, attempts: int
    ) -> None:
        self._store.record_stage(job_id, StageState(stage, status, key, attempts))


def _manifest_for(
    job_id: str, source_id: str | None, dag_universe: str, stage: str
) -> StageManifest:
    return StageManifest(
        job_id=job_id,
        stage_name=stage,
        source_id=source_id,
        dag_universe=dag_universe,
        evidence_refs=[],
        input_manifest={"source_id": source_id or ""},
    )


#: Default scheduling order for a fresh source decomposition.
def initial_stages() -> list[str]:
    return list(STAGE_ORDER)


#: Dependents map consumed by the selective invalidation planner.
lineage_map = STAGE_DEPENDENTS

__all__ = [
    "DAGRunner",
    "DurableDAGRunner",
    "StageRunEvent",
    "StageWorkRegistry",
    "initial_stages",
    "lineage_map",
]
