"""DAG-version drain/restart policy (P1-S4).

Encapsulates the restart/drain discipline from the DD ("Deployment/migrations/
fixtures" rollout): when a NEW DAG universe activates, in-flight work from the
*old* universe must be drained (cancelled) before the new universe is considered
live. The idempotency key folds in the DAG universe (see :mod:`umd.jobs.manifest`),
so a stage run never aliases across two DAG definitions — a drained old run is
simply not re-derivable under the new universe.

This module is the *policy*; the actual cancellation writes go through the job
store (``JobStore``) as ordinary lifecycle cancellations.
"""

from __future__ import annotations

from dataclasses import dataclass

from .job import JobRecord, JobStatus, JobStore


@dataclass(frozen=True)
class DrainResult:
    """Outcome of draining jobs for a universe activation."""

    old_universe: str
    new_universe: str
    drained_jobs: int
    #: ids of jobs that were running/pending on the old universe and cancelled.
    cancelled_job_ids: tuple[str, ...] = ()


class DagUniverseGate:
    """Drains in-flight work before activating a new DAG universe.

    :param store: the durable job store (Postgres in production, in-memory in
        unit tests). The store owns the ``job`` rows this gate mutates.
    """

    def __init__(self, store: JobStore) -> None:
        self._store = store

    def list_jobs(self) -> list[JobRecord]:
        raise NotImplementedError("subclass provides the active-universe scan")

    def activate_new_universe(self, new_universe: str) -> DrainResult:
        """Cancel all active jobs not already running under ``new_universe``.

        Drains PENDING/RUNNING/PAUSED jobs that operate under a *different*
        universe than ``new_universe`` (in-flight work from a previous DAG
        release). ALREADY-completed jobs are left untouched (their stage results
        remain readable; only future reruns run under the new universe).

        :param new_universe: the DAG universe being activated (see
            :func:`umd.jobs.manifest.build_dag_universe`).
        :return: a :class:`DrainResult` describing the drain.
        """
        active = [j for j in self._all() if j.dag_universe != new_universe and _alive(j.status)]
        for job in active:
            self._store.update_status(
                job.id, JobStatus.CANCELLED, error=f"drained by {new_universe}"
            )
        return DrainResult(
            old_universe=",".join(sorted({j.dag_universe for j in active})) or new_universe,
            new_universe=new_universe,
            drained_jobs=len(active),
            cancelled_job_ids=tuple(j.id for j in active),
        )

    def _all(self) -> list[JobRecord]:
        raise NotImplementedError


class SimpleUniverseGate(DagUniverseGate):
    """Gate over an explicit snapshot of jobs (sufficient for tests and the
    durable runner, which enumerates active jobs from the store)."""

    def __init__(self, store: JobStore, snapshot: list[JobRecord] | None = None) -> None:
        super().__init__(store)
        self._snapshot = snapshot

    def list_jobs(self) -> list[JobRecord]:
        return list(self._snapshot or [])

    def _all(self) -> list[JobRecord]:
        return self.list_jobs()


def _alive(status: str) -> bool:
    return status not in (JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELLED)


__all__ = ["DrainResult", "DagUniverseGate", "SimpleUniverseGate", "restart_policy"]


def restart_policy() -> dict[str, str]:
    """The restart/resume policy (documented contract for the runner/Hatchet).

    Restart resume is *idempotent by construction*: re-driving the DAG re-claims
    each stage's deterministic idempotency key; an already-committed stage is
    deduplicated (not re-executed) while a crashed/incomplete stage resumes. No
    stage work is repeated and no successful completion is lost.
    """
    return {
        "resume": "re-claim deterministic stage keys; completed stages dedupe, crashed resumes",
        "no_repeat": "UNIQUE(idempotency_key) + effective-once completion prevent rework",
        "drain": "activate a new DAG universe only after cancelling in-flight old-universe jobs",
    }
