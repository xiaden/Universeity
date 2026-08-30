"""Job command facade: submit/status/events/cancel/retry/rerun/invalidate (P1-S3).

Orchestrates durable jobs over the in-repository stage DAG. This is a *command
handler* — it composes the (pure) invalidation planner, the runner (Hatchet or
the durable runner behind the seam), and the job store, and records the
authority-projection pause behavior. It performs no stage work itself and writes
no projections.

Semantics guaranteed here:

* descendant-only selective rerun — ``rerun_stage``/``rerun_source``/``invalidate``
  compute targets via :class:`InvalidationPlanner` over the SAME lineage the
  runner consumes, so only dependent descendants are re-scheduled (never
  unrelated/upstream stages);
* bounded, explicit lifecycle — submit/cancel/retry are idempotent on the job
  aggregate; a cancel immediately stops further scheduling;
* authority-projection pause — an authority-relevant invalidation/correction
  returns a pause reason so disposable Tier-1 projections are not rebuilt from
  stale reconciled state (the actual projection write is Plan D's job).
"""

from __future__ import annotations

from typing import Any

from umd.application.commands import SemanticCommandService
from umd.jobs.dag import STAGE_DEPENDENTS, STAGE_ORDER
from umd.jobs.invalidation import StageTargets
from umd.jobs.job import JobRecord, JobStatus, JobStore, StageState
from umd.jobs.runner import DAGRunner, StageRunEvent, StageWorkRegistry

#: Authority-relevant predicates that must pause authority-built Tier-1 projections.
_AUTHORITY_PREDICATES = frozenset(
    {"speaker", "entity", "character", "canonical_entity", "pronunciation"}
)


def projection_pause_reason(
    *,
    event_type: str,
    subject_ref: str,
    predicate: str | None = None,
    refs: list[str] | None = None,
) -> str | None:
    """Return a pause reason when an authority-relevant semantic change occurs.

    Pure policy: decides whether disposable authority projections must be paused
    (not rebuilt) until reconciled state settles, instead of being eagerly
    refreshed from possibly-stale inferred semantics. Returns ``None`` (no pause)
    for semantic changes that do not touch authority-built state.

    :param event_type: OverrideApplied | CorrectionApplied | EntityResolved |
        Invalidated | ...
    :param subject_ref: the affected subject/entity reference.
    :param predicate: optional predicate of the change.
    :param refs: optional affected references.
    :return: a human pause reason, or ``None`` when no pause is warranted.
    """
    authority_events = {"OverrideApplied", "CorrectionApplied", "EntityResolved", "Invalidated"}
    if event_type in authority_events and (
        predicate is None or predicate.lower() in _AUTHORITY_PREDICATES
    ):
        subject = subject_ref or (refs[0] if refs else "?")
        return f"authority change on {subject}; projections paused until reconciled state settles"
    return None


class JobService:
    """Durable job command facade over the stage lineage."""

    def __init__(
        self,
        *,
        store: JobStore,
        runner: DAGRunner,
        planner: Any | None = None,
        lineage: dict[str, list[str]] | None = None,
        commands: SemanticCommandService | None = None,
    ) -> None:
        self._store = store
        self._runner = runner
        from umd.jobs.invalidation import InvalidationPlanner as _Planner

        self._planner = planner or _Planner()
        self._lineage = lineage or STAGE_DEPENDENTS
        self._commands = commands

    # -- lifecycle ---------------------------------------------------------

    def submit(
        self,
        *,
        job_id: str,
        source_id: str | None,
        dag_universe: str,
        work_registry: StageWorkRegistry,
        request: dict[str, Any] | None = None,
    ) -> JobRecord:
        """Submit a source decomposition: create the (idempotent) job and schedule."""
        job = self._store.create(
            job_id=job_id,
            source_id=source_id,
            dag_universe=dag_universe,
            request=request,
        )
        if job.status == JobStatus.PENDING:
            self._store.update_status(job.id, JobStatus.RUNNING)
            self._store.set_execution(job.id, set(STAGE_ORDER))
            try:
                events = self._runner.run_graph(
                    job_id=job.id,
                    source_id=source_id,
                    dag_universe=dag_universe,
                    work_registry=work_registry,
                    stages=list(STAGE_ORDER),
                )
            except Exception:
                # A submission failure is surfaced honestly and durably: the job is
                # marked FAILED (persisted) so it can never masquerade as queued or
                # complete, then the exception propagates to the RFC 7807 handler.
                self._store.update_status(job.id, JobStatus.FAILED, error="submission failed")
                raise
            # Persist queued stage state BEFORE reconciliation so an async submission
            # (queued, callbacks pending) is never reconciled back to PENDING.
            self._persist_queued(job.id, events)
            self._refresh_status(job.id)
        return self._store.get(job.id) or job

    def status(self, job_id: str) -> str:
        """Derived job status (explicit aggregate status + stage-run folding)."""
        rec = self._store.get(job_id)
        if rec is None:
            raise KeyError(f"unknown job {job_id}")
        return _derive_status(rec, self._store.stage_states(job_id))

    def events(self, job_id: str) -> list[Any]:
        """Operational audit stream (job_run_audit records, never semantic replay)."""
        return self._store.audit_records(job_id)

    def cancel(
        self, *, job_id: str, stage: str | None = None, reason: str | None = None
    ) -> JobRecord:
        """Cancel a job (whole) or a single stage (partial, descendant closure).

        A whole-job cancel flips the aggregate to CANCELLED, which the runner
        checks before scheduling any further stage (a durable ``break``). A single
        stage cancel marks the stage *and its transitive descendants* cancelled
        (a parent cannot run without its ancestors), so the runner skips them.
        Reasoning is preserved in the audit/error fields.
        """
        rec = self._store.get(job_id)
        if rec is None:
            raise KeyError(f"unknown job {job_id}")
        if stage is None:
            # A completed job is terminal and cannot be cancelled. This matters for
            # content-addressed duplicate uploads: they can resolve to the same
            # canonical job after it has already completed.
            if self.status(job_id) == JobStatus.COMPLETE:
                return self._store.get(job_id) or rec
            self._store.update_status(job_id, JobStatus.CANCELLED, error=reason)
        else:
            cancelled = set(rec.cancelled_stages) | set(self._closure(stage))
            self._store.set_cancelled_stages(job_id, cancelled)
        return self._store.get(job_id) or rec

    def retry(
        self,
        *,
        job_id: str,
        work_registry: StageWorkRegistry,
        dag_universe: str,
        stage: str | None = None,
    ) -> JobRecord:
        """Retry previously-failed/cancelled work.

        ``stage=None`` retries every non-complete stage (a whole-job rerun);
        ``stage=...`` retries just that stage. In both cases only stages that did
        NOT already succeed are scheduled, so a failed late stage never repeats
        expensive successful early extraction.
        """
        rec = self._store.get(job_id)
        if rec is None:
            raise KeyError(f"unknown job {job_id}")
        states = {s.stage_name: s.status for s in self._store.stage_states(job_id)}
        self._store.update_status(job_id, JobStatus.RUNNING, error=None)
        if stage is not None:
            closure = set(self._closure(stage))
            cancelled = set(rec.cancelled_stages) - closure
            self._store.set_cancelled_stages(job_id, cancelled)
            targets = [s for s in closure if states.get(s, "pending") != "complete"] or list(
                closure
            )
        else:
            self._store.set_cancelled_stages(job_id, set())
            targets = [s for s in STAGE_ORDER if states.get(s, "pending") != "complete"]
        if targets:
            events = self._runner.run_graph(
                job_id=job_id,
                source_id=rec.source_id,
                dag_universe=dag_universe,
                work_registry=work_registry,
                stages=targets,
            )
            self._persist_queued(job_id, events)
        self._refresh_status(job_id)
        return self._store.get(job_id) or rec

    # -- selective rerun & invalidation ------------------------------------

    def rerun_stage(
        self,
        *,
        source_id: str,
        stage: str,
        scope: str,
        causation: str,
        dag_universe: str,
        work_registry: StageWorkRegistry,
        job_id: str,
    ) -> Any:
        """Re-run a stage's dependent descendants only (never the stage itself).

        Uses :class:`InvalidationPlanner.plan` over the canonical lineage so only
        transitive descendants are scheduled; ancestors and unrelated branches are
        untouched. Returns the planned :class:`StageTargets`.
        """
        targets = self._planner.plan(causation, scope, stage, self._lineage)
        descendant_stages = [t.stage for t in targets.targets]
        if descendant_stages:
            self._store.set_execution(job_id, set(descendant_stages), causation)
            events = self._runner.run_graph(
                job_id=job_id,
                source_id=source_id,
                dag_universe=dag_universe,
                work_registry=work_registry,
                stages=descendant_stages,
                rerun_causation=causation,
            )
            self._persist_queued(job_id, events)
        self._refresh_status(job_id)
        return targets

    def rerun_source(
        self,
        *,
        source_id: str,
        scope: str,
        causation: str,
        dag_universe: str,
        work_registry: StageWorkRegistry,
        job_id: str,
    ) -> Any:
        """Re-run from the root — the whole downstream closure of INGEST.

        ``INGEST`` itself carries no prior stage, so a source rerun schedules the
        full downstream graph (all stages after INGEST), matching the DD's
        selective-rerun semantic.
        """
        via_ingest = self._planner.plan(causation, scope, None, self._lineage)
        descendant_stages = [s for s in STAGE_ORDER if s != "INGEST"]
        self._store.set_execution(job_id, set(descendant_stages), causation)
        events = self._runner.run_graph(
            job_id=job_id,
            source_id=source_id,
            dag_universe=dag_universe,
            work_registry=work_registry,
            stages=descendant_stages,
            rerun_causation=causation,
        )
        self._persist_queued(job_id, events)
        return StageTargets(
            causation=causation,
            scope=scope,
            root_stage=via_ingest.root_stage,
            targets=via_ingest.targets,
            unaffected=via_ingest.unaffected,
        )

    def invalidate(
        self,
        *,
        subject_ref: str,
        predicate: str | None,
        cause: str,
        scope: str,
        stage: str,
        source_id: str,
        dag_universe: str,
        work_registry: StageWorkRegistry,
        job_id: str,
        refs: list[str] | None = None,
    ) -> tuple[Any, str | None]:
        """Invalidate a claim: record the event, plan descendants, pause projections.

        Records the ``Invalidated`` semantic event (append-only authority), plans
        the dependent stage closure, schedules it, and returns
        ``(targets, pause_reason)`` — the pause reason is non-``None`` when the
        authority projection pause policy applies.
        """
        targets = self._planner.plan(f"invalidate:{cause}", scope, stage, self._lineage)
        descendant_stages = [t.stage for t in targets.targets]
        if self._commands is not None:
            self._commands.invalidate(
                subject_ref=subject_ref,
                predicate=predicate,
                cause=cause,
                scope=scope,
                stage=stage,
                refs=refs or [],
                correlation_id=job_id,
            )
        if descendant_stages:
            self._store.set_execution(job_id, set(descendant_stages), f"invalidate:{cause}")
            events = self._runner.run_graph(
                job_id=job_id,
                source_id=source_id,
                dag_universe=dag_universe,
                work_registry=work_registry,
                stages=descendant_stages,
                rerun_causation=f"invalidate:{cause}",
            )
            self._persist_queued(job_id, events)
        pause = projection_pause_reason(
            event_type="Invalidated", subject_ref=subject_ref, predicate=predicate, refs=refs
        )
        return targets, pause

    def _closure(self, stage: str) -> list[str]:
        """The stage plus its transitive descendants (the operator-invalidation set)."""
        targets = self._planner.plan(f"cancel:{stage}", "SOURCE", stage, self._lineage)
        return [stage] + [t.stage for t in targets.targets]

    def _persist_queued(self, job_id: str, events: list[StageRunEvent]) -> None:
        """Durably record queued stage state before status reconciliation (P1-S4).

        A submission through an asynchronous runner (:class:`ProductionDAGRunner`)
        returns ``queued`` events with no committed stage output yet. Recording them
        here (before ``_refresh_status``) means the store reflects that the job was
        genuinely submitted-and-queued, so it can never be reconciled back to
        ``PENDING`` (RUNNING->PENDING regression). Stores that persist per-stage
        state durably do so; the durable aggregate ``RUNNING`` status in the job
        table is the authority that survives restart for backends that fold stage
        status from executor-owned ``stage_run`` rows.
        """
        for ev in events:
            if ev.status == "queued":
                self._store.record_stage(job_id, StageState(stage_name=ev.stage, status="queued"))

    def _refresh_status(self, job_id: str) -> None:
        self._store.update_status(job_id, self.status(job_id))


def _derive_status(rec: JobRecord, states: list[Any]) -> str:
    if rec.status in (JobStatus.CANCELLED, JobStatus.PAUSED, JobStatus.FAILED):
        return rec.status
    expected = set(rec.request.get("expected_stages", STAGE_ORDER))
    if not expected:
        return rec.status
    if not states:
        # No per-stage outcome yet: a job that was submitted (aggregate RUNNING) is
        # queued/in-flight, NOT pending. Returning the durable aggregate status here
        # prevents a RUNNING->PENDING regression for asynchronous submissions.
        return rec.status
    by_stage = {s.stage_name: s.status for s in states}
    if not expected.issubset(by_stage):
        return JobStatus.RUNNING
    statuses = {by_stage[stage] for stage in expected}
    if "quarantined" in statuses or "failed" in statuses:
        return JobStatus.FAILED
    if all(st == "complete" for st in statuses):
        return JobStatus.COMPLETE
    return JobStatus.RUNNING


__all__ = [
    "JobService",
    "projection_pause_reason",
]
