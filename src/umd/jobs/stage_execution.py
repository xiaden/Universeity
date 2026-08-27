"""Durable stage execution: claim-before-side-effect, atomic completion, retry (P1-S2).

This is the disciplined stage-execution path shared by the in-memory runner
double and (through the :class:`DAGRunner` seam) the Hatchet adapter. It
enforces the DD's "durable stage execution" invariants:

* **claim-before-side-effect** — the executor claims the run idempotency key via
  :meth:`StageRunRepository.claim` BEFORE invoking any stage work; a losing
  duplicate never runs work.
* **effective-once completion** — a stage completes only by committing its
  authoritative artifact references and its ``StageCompleted`` semantic event in
  ONE ``stage_run``-row update and one ledger append (see
  :meth:`SemanticLedger.complete_and_append`), so a crash cannot commit a
  completion without its evidence, and a repeated submission never repeats
  successful work.
* **deterministic malformed input -> quarantine, not retry storms** — a stage
  whose failure is identified as deterministic (malformed/unsupported input)
  lands in the ``quarantine`` sink and is never retried; only transient failures
  are retried with bounded exponential backoff.
* **separate operational audit** — every attempt/retry/failure/completion/cancel
  is recorded to ``job_run_audit`` (operational), never to the semantic ledger.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import sqlalchemy as sa

from umd.domain.events import SemanticEvent
from umd.storage.postgres.ledger import SemanticLedger
from umd.storage.postgres.stage_repository import (
    JobAuditAttempt,
    JobRunAudit,
    StageRunClaim,
    StageRunManifest,
    StageRunRepository,
)
from umd.storage.postgres.tables import metadata as db_meta

from .manifest import StageManifest, deterministic_uuid

_run_t = db_meta.tables["stage_run"]

#: stage_run.status values this executor manages.
STATUS_COMPLETE = "complete"
STATUS_FAILED = "failed"
STATUS_QUARANTINED = "quarantined"
STATUS_CLAIMED = "claimed"
STATUS_CANCELLED = "cancelled"


class StageQuarantinedError(RuntimeError):
    """A stage failed deterministically (malformed input) and was quarantined.

    Raised after the quarantine sink has recorded the failure. Never retried.
    """

    def __init__(self, stage: str, reason: str, locator: str) -> None:
        super().__init__(f"stage {stage} quarantined at {locator}: {reason}")
        self.stage = stage
        self.reason = reason
        self.locator = locator


class StageTransientError(RuntimeError):
    """A stage failed for a transient reason and may be retried with backoff."""


class MalformedInputError(RuntimeError):
    """A stage failed because its input is structurally invalid/unsupported.

    Distinct from :class:`StageTransientError`: this is *deterministic* and must
    quarantine, never retry (prevents retry storms).
    """

    def __init__(self, reason: str, locator: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.locator = locator


@dataclass
class StageOutcome:
    """Result of running one stage's work function."""

    artifact_refs: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


class StageWork(Protocol):
    """A stage's work function: ``work(manifest) -> StageOutcome``.

    Implementations perform the stage's actual processing (Phase 2/3 stages plug
    in here) and return the evidence/artifact references they produced — they do
    NOT write projections or append semantic events (that is the executor's
    exclusive job).
    """

    def __call__(self, manifest: StageManifest) -> StageOutcome: ...


class QuarantineSink(Protocol):
    """Records a deterministic failure so it is never retried."""

    def record(self, locator: str, reason: str, refs: list[str] | None = None) -> None: ...


class BackoffPolicy(Protocol):
    """Bounded backoff between retries."""

    def sleep(self, attempt: int) -> None: ...


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded retry shape for transient failures."""

    max_attempts: int = 3
    base_delay_ms: int = 50
    max_delay_ms: int = 2000
    #: Exponent for ``delay = base * multiplier ** (attempt-1)``.
    multiplier: float = 2.0

    def delay_seconds(self, attempt: int) -> float:
        raw = self.base_delay_ms * (self.multiplier ** (attempt - 1))
        return min(raw, self.max_delay_ms) / 1000.0


class RealBackoff:
    """BackoffPolicy that actually sleeps (used by the durable runner)."""

    def __init__(self, policy: RetryPolicy) -> None:
        self._policy = policy

    def sleep(self, attempt: int) -> None:
        time.sleep(self._policy.delay_seconds(attempt))


class NoWaitBackoff:
    """BackoffPolicy that never sleeps (fast shape tests / doubles)."""

    def sleep(self, _attempt: int) -> None:  # pragma: no cover - trivial
        return None


@dataclass
class StageRunRecord:
    """Structured result of one :meth:`DurableStageExecutor.run` call."""

    claim: StageRunClaim
    outcome: StageOutcome | None = None
    state: str = STATUS_CLAIMED
    attempts: int = 1
    error: str | None = None
    completion_seq: int | None = None
    #: True when the run was already committed by a prior execution (duplicate /
    #: resumed-after-crash replay). No side effects ran.
    replayed: bool = False


class DurableStageExecutor:
    """Runs one stage with claim-before-side-effect + effective-once completion.

    :param engine: the Postgres engine for stage_run updates and ledger appends.
    :param commands: semantic command authority (for StageCompleted construction).
    :param ledger: the semantic ledger; used through :meth:`complete_and_append`
        so artifact refs and the StageCompleted event commit atomically.
    :param stage_repo: claims stage runs (UNIQUE idempotency_key is authority).
    :param audit: operational job-run audit stream.
    :param quarantine: deterministic-failure sink (never-retried).
    :param retry: retry policy for transient failures (bounded backoff).
    :param backoff: the backoff mechanism (inject ``NoWaitBackoff`` in tests).
    """

    def __init__(
        self,
        *,
        engine: sa.Engine,
        commands: Any,
        ledger: SemanticLedger,
        stage_repo: StageRunRepository,
        audit: JobRunAudit,
        quarantine: QuarantineSink,
        retry: RetryPolicy | None = None,
        backoff: BackoffPolicy | None = None,
    ) -> None:
        self._engine = engine
        self._commands = commands  # SemanticCommandService (StageCompleted author)
        self._ledger = ledger
        self._stage_repo = stage_repo
        self._audit = audit
        self._quarantine_sink = quarantine
        self._retry = retry or RetryPolicy()
        self._backoff = backoff or NoWaitBackoff()

    # ------------------------------------------------------------------ run
    def run(self, manifest: StageManifest, work: StageWork) -> StageRunRecord:
        """Claim, run, and (on success) atomically complete a stage.

        Claim-before-side-effect: the idempotency key is claimed first. A losing
        duplicate or an already-committed run returns a ``replayed`` record with
        NO side effects. Deterministic failures are quarantined (never retried);
        transient failures use bounded backoff up to ``retry.max_attempts``.

        :param manifest: the stage manifest (deterministic idempotency key).
        :param work: the stage's work function.
        :return: the :class:`StageRunRecord` describing what happened.
        :raises StageQuarantinedError: deterministic input failure (already sunk).
        :raises StageTransientError: transient failure exhausted all retries.
        """
        key = manifest.idempotency_key()
        claim = self._stage_repo.claim(key, self._to_run_manifest(manifest))

        if not claim.won:
            # Duplicate / resumed submission for an already-claimed key. Check the
            # committed status: an already-complete run is NOT re-executed (no
            # repeated successful stage work); a claimed-but-incomplete row means a
            # prior run crashed before commit -> resume (re-run) it. Side effects
            # never ran while the key was unclaimed, so this is safe.
            existing = self._existing_run(key)
            if existing == STATUS_COMPLETE:
                return StageRunRecord(claim=claim, state=STATUS_COMPLETE, replayed=True)
            if existing in (STATUS_CANCELLED, STATUS_QUARANTINED):
                return StageRunRecord(claim=claim, state=existing, replayed=True)
            # in-flight or failed -> resume below (re-claim is a no-op on the key).

        self._audit.record(
            JobAuditAttempt(
                job_id=manifest.job_id,
                stage_name=manifest.stage_name,
                action="start",
                attempt=1,
                status=STATUS_CLAIMED,
                started_at=_now(),
            )
        )

        attempts = 1
        while True:
            try:
                outcome = work(manifest)
            except MalformedInputError as exc:
                return self._quarantine(manifest, claim, exc)
            except Exception as exc:  # noqa: BLE001 - classify then decide
                if attempts < self._retry.max_attempts:
                    self._audit.record(
                        JobAuditAttempt(
                            job_id=manifest.job_id,
                            stage_name=manifest.stage_name,
                            action="retry",
                            attempt=attempts + 1,
                            status=STATUS_FAILED,
                            details={"error": str(exc)},
                            finished_at=_now(),
                        )
                    )
                    attempts += 1
                    self._backoff.sleep(attempts)
                    continue
                return self._fail(manifest, claim, attempts, exc, quarantined=False)

            return self._complete(manifest, claim, outcome, attempts=attempts)

    # -- marking helpers ---------------------------------------------------

    def _complete(
        self, manifest: StageManifest, claim: StageRunClaim, outcome: StageOutcome, *, attempts: int
    ) -> StageRunRecord:
        """Commit artifact refs + StageCompleted atomically, then audit complete."""
        # The completion's idempotency key is itself a deterministic UUID derived
        # from the stage run key, so a re-driven completion is deduplicated too.
        completion_key = deterministic_uuid(f"stage-complete:{claim.idempotency_key}")
        event = SemanticEvent(
            event_type="StageCompleted",
            payload={
                "source_id": manifest.source_id,
                "stage": manifest.stage_name,
                "status": STATUS_COMPLETE,
                "artifact_refs": outcome.artifact_refs,
                "evidence_refs": outcome.evidence_refs,
                "generated_by": {
                    **manifest.tool_versions,
                    "idempotency_key": claim.idempotency_key,
                    "dag_universe": manifest.dag_universe,
                },
                "job_id": manifest.job_id,
            },
            generated_by={
                **manifest.tool_versions,
                "idempotency_key": claim.idempotency_key,
            },
        )

        def side_effects(conn: sa.Connection) -> None:
            conn.execute(
                _run_t.update()
                .where(_run_t.c.id == claim.id)
                .values(
                    status=STATUS_COMPLETE,
                    artifact_refs=outcome.artifact_refs,
                    updated_at=_now(),
                )
            )

        result = self._ledger.complete_and_append(
            events=[event], idempotency_key=completion_key, side_effects=side_effects
        )
        self._audit.record(
            JobAuditAttempt(
                job_id=manifest.job_id,
                stage_name=manifest.stage_name,
                action="complete",
                attempt=attempts,
                status=STATUS_COMPLETE,
                details={"seq": result.seq, "artifact_refs": outcome.artifact_refs},
                finished_at=_now(),
            )
        )
        return StageRunRecord(
            claim=claim,
            outcome=outcome,
            state=STATUS_COMPLETE,
            attempts=attempts,
            completion_seq=result.seq,
        )

    def _quarantine(
        self, manifest: StageManifest, claim: StageRunClaim, exc: MalformedInputError
    ) -> StageRunRecord:
        self._quarantine_sink.record(
            locator=exc.locator or _locator_of(manifest),
            reason=exc.reason,
            refs=manifest.evidence_refs,
        )
        self._mark_run(claim, STATUS_QUARANTINED)
        self._audit.record(
            JobAuditAttempt(
                job_id=manifest.job_id,
                stage_name=manifest.stage_name,
                action="fail",
                attempt=1,
                status=STATUS_QUARANTINED,
                details={"deterministic": True, "reason": exc.reason},
                finished_at=_now(),
            )
        )
        raise StageQuarantinedError(
            manifest.stage_name, exc.reason, exc.locator or _locator_of(manifest)
        )

    def _fail(
        self,
        manifest: StageManifest,
        claim: StageRunClaim,
        attempts: int,
        exc: Exception,
        *,
        quarantined: bool,
    ) -> StageRunRecord:
        status = STATUS_QUARANTINED if quarantined else STATUS_FAILED
        self._mark_run(claim, status)
        self._audit.record(
            JobAuditAttempt(
                job_id=manifest.job_id,
                stage_name=manifest.stage_name,
                action="fail",
                attempt=attempts,
                status=status,
                details={"error": str(exc)},
                finished_at=_now(),
            )
        )
        return StageRunRecord(claim=claim, state=status, attempts=attempts, error=str(exc))

    # -- internals ---------------------------------------------------------

    def _mark_run(self, claim: StageRunClaim, status: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                _run_t.update()
                .where(_run_t.c.id == claim.id)
                .values(status=status, updated_at=_now())
            )

    def _existing_run(self, key: str) -> str | None:
        with self._engine.connect() as conn:
            return conn.execute(
                sa.select(_run_t.c.status).where(_run_t.c.idempotency_key == key)
            ).scalar()

    @staticmethod
    def _to_run_manifest(manifest: StageManifest) -> StageRunManifest:
        return StageRunManifest(
            job_id=manifest.job_id,
            stage_name=manifest.stage_name,
            source_id=manifest.source_id,
            segment_id=manifest.segment_id,
            input_manifest={**manifest.input_manifest, "dag_universe": manifest.dag_universe},
            config_digest=manifest.config_digest,
        )


def _now() -> datetime:
    return datetime.now(UTC)


def _locator_of(manifest: StageManifest) -> str:
    seg = manifest.segment_id or "root"
    return f"source:{manifest.source_id or '?'}#segment:{seg}#stage:{manifest.stage_name}"


# Re-export statuses for the job layer.
__all__ = [
    "DurableStageExecutor",
    "StageWork",
    "StageOutcome",
    "StageRunRecord",
    "QuarantineSink",
    "BackoffPolicy",
    "RetryPolicy",
    "RealBackoff",
    "NoWaitBackoff",
    "StageQuarantinedError",
    "StageTransientError",
    "MalformedInputError",
    "STATUS_COMPLETE",
    "STATUS_FAILED",
    "STATUS_QUARANTINED",
    "STATUS_CLAIMED",
    "STATUS_CANCELLED",
]
