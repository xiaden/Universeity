"""In-process synchronous DAG runner for the API jobs facade (Phase 3).

The API boundary does not schedule the extraction pipeline itself — durable stage
execution is out of the API's remit. This runner satisfies the :class:`DAGRunner`
protocol by marking each requested stage complete on the store, so API-driven jobs
are deterministic and pollable (submit -> complete) for the contract tests. Real
production execution plugs in behind the same ``DAGRunner`` seam.
"""

from __future__ import annotations

from umd.jobs.job import JobStore, StageState
from umd.jobs.runner import StageRunEvent, StageWorkRegistry


class SynchronousRunner:
    """A :class:`DAGRunner` that folds each requested stage to complete synchronously."""

    def __init__(self, store: JobStore) -> None:
        self._store = store

    def run_graph(  # noqa: ARG002 - implements DAGRunner protocol; some params unused by design
        self,
        *,
        job_id: str,
        source_id: str | None,  # noqa: ARG002 - protocol param unused
        dag_universe: str,  # noqa: ARG002 - protocol param unused
        work_registry: StageWorkRegistry,  # noqa: ARG002 - protocol param unused
        stages: list[str],
    ) -> list[StageRunEvent]:
        events: list[StageRunEvent] = []
        for stage in stages:
            self._store.record_stage(job_id, StageState(stage_name=stage, status="complete"))
            events.append(StageRunEvent(stage=stage, status="complete"))
        return events


__all__ = ["SynchronousRunner"]
