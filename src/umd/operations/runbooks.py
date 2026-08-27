"""Operational runbooks: cancel / retry / restart + failure-mode procedures (P1-S4).

The DD operational SLOs and the operational section require honest runbooks for
operating the decomposer under failure: worker/sandbox crashes, late-stage
resume, duplicate stage submissions, projection rebuild, poison pause, queue
bursts, and token-wait backoff. This module ships those procedures as structured
cards. They are documented procedures mapped to real services — not fabricated
automation. The matching operational *tests* live in tests/test_operational_phaseE.py
and exercise the underlying services (JobService, DurableStageExecutor,
ProjectionController, ConsistencyGuard) directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RunbookCard:
    """One operational runbook procedure."""

    id: str
    title: str
    trigger: str
    service: str
    steps: list[str] = field(default_factory=list)


class RunbookCatalog:
    """The set of operational runbooks for the decomposer (P1-S4)."""

    def __init__(self) -> None:
        self._cards: dict[str, RunbookCard] = {card.id: card for card in _CARDS}

    def get(self, card_id: str) -> RunbookCard | None:
        return self._cards.get(card_id)

    def ids(self) -> list[str]:
        return sorted(self._cards)

    def list(self) -> list[RunbookCard]:
        return [self._cards[i] for i in self.ids()]


_CANCEL = RunbookCard(
    id="cancel-job",
    title="Cancel a job",
    trigger="A job is stuck, wrong, or no longer needed.",
    service="JobService.cancel(job_id, stage=None, reason=...)",
    steps=[
        "Call JobService.cancel to mark the whole job (or a specific stage) cancelled.",
        "cancelled_stages are persisted on the job so cancelled work is never re-run.",
        "The DAG runner checks cancelled status/cancelled_stages before starting each stage.",
    ],
)

_RETRY = RunbookCard(
    id="retry-failed-stage",
    title="Retry a failed stage",
    trigger="A stage failed transiently and committed stages must not repeat.",
    service="JobService.retry(job_id, work_registry=..., dag_universe=...)",
    steps=[
        "Call JobService.retry; it derives status and schedules only unfinished (failed) stages.",
        "Successful stages are skipped — retry never repeats committed work.",
        "Transient stage failures take bounded backoff (RealBackoff) before the next attempt.",
    ],
)

_RESTART = RunbookCard(
    id="restart-resume",
    title="Restart and resume after a worker/sandbox crash",
    trigger="A worker or sandbox crashed mid-run; resume without replaying commits.",
    service="DurableStageExecutor.claim + SemanticLedger.complete_and_append (effective-once)",
    steps=[
        "On restart, re-submit the same job with deterministic idempotency keys.",
        "claim() dedupes via UNIQUE(idempotency_key); a crash cannot double-claim.",
        "complete_and_append commits StageCompleted atomically; resume skips.",
        "Resume continues at the last committed stage; successful stages are not repeated.",
    ],
)

_DUPLICATE = RunbookCard(
    id="duplicate-stage-submission",
    title="Handle duplicate stage submissions",
    trigger="The same stage is submitted more than once (retry storm, at-least-once network).",
    service="StageRunRepository.claim (ON CONFLICT DO NOTHING) + effective-once completion",
    steps=[
        "Deterministic idempotency keys are the claim key; UNIQUE(idempotency_key) wins one claim.",
        "Duplicate claims lose the race — they see the committed StageCompleted and are skipped.",
        "The winning stage_run is a single row; completion is atomic with the ledger append.",
    ],
)

_REBUILD = RunbookCard(
    id="projection-rebuild",
    title="Rebuild a Tier-1 projection",
    trigger="A projection must be rebuilt (e.g. after a schema/version bump or corruption).",
    service="ProjectionController.rebuild(builder, wipe=True) via ReplayDriver",
    steps=[
        "Rebuilds ALWAYS go through the projection builder (ReplayDriver) — never a direct write.",
        "The ReindexCoordinator caps concurrent rebuilds and enforces the min interval cadence.",
        "The rebuild budget (max events/seconds) is reported; bl/green publish + grace applies.",
        "Reads wait bounded then 503 (rebuild-in-progress) until publish is fresh.",
    ],
)

_POISON = RunbookCard(
    id="poison-pause",
    title="Authority-poison projection pause",
    trigger="A projection hits an authority-relevant poison event and pauses.",
    service="poison.classify -> on_pause + paused() checkpoint + pause_alerts()",
    steps=[
        "The projection pauses (checkpoint reason), alerting pause_alerts().",
        "It stays paused on subsequent runs until force_resume — it never auto-applies poison.",
        "Operator reviews the poison predicate/entity before resuming the projection.",
    ],
)

_BURST = RunbookCard(
    id="queue-burst",
    title="Absorb a queue burst",
    trigger="Many jobs/submissions arrive at once and queue depth spikes.",
    service="queue.depth gauge + ReindexCoordinator concurrency cap",
    steps=[
        "queue.depth is recorded as a gauge; the scheduler absorbs spikes without dropping work.",
        "Rebuild concurrency is capped (single-writer), so bursts serialize safely.",
        "Transient 503s with Retry-After communicate bounded waits to token-bearing readers.",
    ],
)

_TOKEN = RunbookCard(
    id="token-wait-backoff",
    title="Token-wait backoff without retry amplification",
    trigger="Token-bearing Tier-1 reads lag the token and back off without amplification.",
    service="ConsistencyGuard.ensure_read + bounded RetryPolicy backoff (no amplification)",
    steps=[
        "Reads wait bounded behind the waiter semaphore, then 503 with Retry-After (never stale).",
        "Stage retries use bounded backoff; each retry increments the count once.",
        "No client/waiter retry re-executes committed stages — idempotency keeps retries safe.",
    ],
)


_CARDS: list[RunbookCard] = [
    _CANCEL,
    _RETRY,
    _RESTART,
    _DUPLICATE,
    _REBUILD,
    _POISON,
    _BURST,
    _TOKEN,
]

#: The canonical runbook catalog for the service.
CATALOG = RunbookCatalog()


__all__ = ["RunbookCatalog", "RunbookCard", "CATALOG"]
