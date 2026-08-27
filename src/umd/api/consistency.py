"""Read-your-writes consistency tokens and bounded Tier-1 waiter (Phase 3).

Implements the CONTRACTS/DD consistency semantics:

* Token-bearing Tier-1 reads (``/query/*``, ``/search``) carry an opaque
  ``consistency_token`` (== the ledger seq a committed write returned). The guard
  waits, bounded by ``lag_budget * lag_wait_multiplier`` (default ~<=2x the <=1s
  budget) behind a bounded semaphore (:attr:`ConsistencyGuard`), for the projection
  to catch up to the token — then services the read.
* If it still cannot catch up inside the budget: a 503 with ``Retry-After`` and an
  ``x-consistency`` header of ``transient-lag`` (projection behind) or
  ``rebuild-in-progress`` (projection paused for a post-correction rebuild;
  ``Retry-After >= 30s`` plus ``x-rebuild-estimate``). Never returns stale
  post-correction.
* Untokened reads are served immediately but the response embeds ``freshness``
  metadata (applied sequence, ledger tail, lag, status).

All DB reads use context-managed connections so test session teardown (DROP
DATABASE) is never blocked by leaked read-locks.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa

from umd.api.errors import ConsistencyLagError
from umd.config import Settings
from umd.observability.records import (
    record_503,
    record_stale_response,
    set_projection_lag,
)
from umd.storage.postgres.tables import metadata as db_meta


@dataclass
class FreshnessSnapshot:
    """Freshness/lag state of one Tier-1 projection at a moment in time."""

    projection_name: str
    applied_seq: int
    ledger_tail: int
    paused: bool
    pause_reason: str | None = None

    @property
    def lag(self) -> int:
        return self.ledger_tail - self.applied_seq

    @property
    def status(self) -> str:
        if self.paused:
            return "rebuild-in-progress"
        if self.applied_seq >= self.ledger_tail:
            return "fresh"
        return "transient-lag"

    def to_meta(self) -> dict[str, Any]:
        return {
            "projection": self.projection_name,
            "applied_seq": self.applied_seq,
            "ledger_tail": self.ledger_tail,
            "lag": self.lag,
            "status": self.status,
            "paused": self.paused,
            "pause_reason": self.pause_reason,
        }


class ProjectionFreshness:
    """Reads a projection's applied sequence vs the ledger tail (Tier-0 truth)."""

    def __init__(self, engine: sa.Engine, projection_name: str) -> None:
        self._engine = engine
        self._name = projection_name
        self._ledger = db_meta.tables["semantic_event"]
        self._checkpoints = db_meta.tables["projection_checkpoint"]

    @property
    def name(self) -> str:
        return self._name

    def snapshot(self) -> FreshnessSnapshot:
        with self._engine.connect() as conn:
            tail = conn.execute(sa.select(sa.func.max(self._ledger.c.seq))).scalar_one()
            row = conn.execute(
                sa.select(self._checkpoints.c.applied_seq, self._checkpoints.c.checkpoint).where(
                    self._checkpoints.c.projection_name == self._name
                )
            ).first()
        applied = int(row[0]) if row and row[0] is not None else 0
        payload = dict(row[1] or {}) if row else {}
        pause_reason = payload.get("_pause_reason")
        return FreshnessSnapshot(
            projection_name=self._name,
            applied_seq=applied,
            ledger_tail=int(tail or 0),
            paused=bool(pause_reason),
            pause_reason=pause_reason,
        )


class ConsistencyGuard:
    """Bounded wait-then-503 read-your-writes guard for Tier-1 projections."""

    def __init__(self, freshness: ProjectionFreshness, settings: Settings) -> None:
        self._freshness = freshness
        self._settings = settings
        self._semaphore = threading.BoundedSemaphore(settings.consistency.max_waiters)

    @property
    def freshness(self) -> ProjectionFreshness:
        return self._freshness

    def ensure_read(self, token: int | None) -> FreshnessSnapshot:
        """Service a read for ``token``; returns the post-wait freshness snapshot.

        Untokened (``token is None``): return current snapshot immediately.
        Tokened: wait bounded behind the semaphore, then 503 unless caught up.
        """
        if token is None:
            snap = self._freshness.snapshot()
            set_projection_lag(snap.projection_name, snap.lag)
            return snap

        budget = self._settings.lag_budget_seconds * self._settings.consistency.lag_wait_multiplier
        deadline = time.monotonic() + max(budget, 0.05)
        with self._semaphore:
            snap = self._freshness.snapshot()
            while time.monotonic() < deadline and snap.paused:
                time.sleep(min(0.05, budget))
                snap = self._freshness.snapshot()
            if snap.paused:
                # Rebuild in progress: never serve (possibly stale) pre-rebuild state.
                record_503(origin="rebuild-in-progress")
                record_stale_response(snap.projection_name)
                raise ConsistencyLagError(
                    "projection is being rebuilt; retry after rebuild completes",
                    code="consistency_rebuild",
                    retryable=True,
                    extra={
                        "x-consistency": "rebuild-in-progress",
                        "x-rebuild-estimate": self._settings.consistency.rebuild_retry_after,
                        "retry_after": self._settings.consistency.rebuild_retry_after,
                    },
                )
            while time.monotonic() < deadline and snap.applied_seq < token:
                time.sleep(min(0.05, budget))
                snap = self._freshness.snapshot()
            if snap.applied_seq < token:
                record_503(origin="transient-lag")
                raise ConsistencyLagError(
                    "projection has not caught up to the consistency token within the "
                    "lag budget; retry shortly",
                    code="consistency_transient_lag",
                    retryable=True,
                    extra={
                        "x-consistency": "transient-lag",
                        "retry_after": self._settings.consistency.transient_retry_after,
                    },
                )
            set_projection_lag(snap.projection_name, snap.lag)
            return snap


__all__ = [
    "FreshnessSnapshot",
    "ProjectionFreshness",
    "ConsistencyGuard",
]
