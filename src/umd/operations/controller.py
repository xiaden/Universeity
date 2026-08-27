"""Projection controller: checkpoint / rebuild / budget / pause-alerts / promotion (P1-S3).

The DD packaging-and-persistence and operational sections require operator-facing
operations that report and control Tier-1 projections *without* ever writing them
directly — every write still goes through a projection builder via
:class:`ReplayDriver` (single-writer, authority preserved). This controller adds:

* checkpoint read/write + fresh/stale reporting (against the live ledger tail)
* rebuild scheduling under a coordinated cadence (concurrent cap + min interval)
* rebuild-budget enforcement (max events / seconds) reported, never silently exceeded
* authority-poison pause alerts (surfaced from alive paused checkpoints)
* vector count / recall / HNSW monitoring + measured 5M/10M/50M promotion reviews
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any

import sqlalchemy as sa

from umd.config import RebuildSettings, Settings
from umd.observability.records import set_projection_lag
from umd.operations.vector_ops import VectorMonitor
from umd.projections.base import ProjectionBuilder, ReplayDriver
from umd.projections.checkpoint import ProjectionCheckpoint, ProjectionCheckpointStore
from umd.projections.vector import VectorIndex

_BUILD_MARK = re.compile(r"^[a-z0-9_]+$")


@dataclass
class PromotionReview:
    """Measured promotion-review record behind ``VectorIndex`` (P1-S3).

    Produced from the live embedding row count across the 5M/10M/50M growth
    thresholds. Purely advisory: it records where the store stands and which
    DD-named promotion candidate(s) would warrant review.
    """

    measured_count: int
    growth_tier: int | None
    promotion_candidates: list[str]
    thresholds: tuple[int, ...] = tuple([5_000_000, 10_000_000, 50_000_000])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReindexCoordinator:
    """Coordinates concurrent reindex cadence (DD: bounded overlapping rebuilds)."""

    def __init__(self, settings: RebuildSettings | None = None) -> None:
        self._settings = settings or RebuildSettings()
        self._lock = threading.Lock()
        self._active: dict[str, float] = {}
        self._last_started: dict[str, float] = {}

    def acquire(self, projection_name: str, *, scheduled: bool = False) -> bool:
        """Try to acquire the right to start a rebuild of ``projection_name``.

        Honest cadence gate: no more than ``concurrent_rebuilds`` projections
        rebuilding at once. For *scheduled* reindexing (``scheduled=True``) a
        projection may not restart within ``min_interval_seconds`` of its last
        start. An explicit operator-initiated rebuild is not scheduled churn, so
        it passes through the concurrency cap but is not throttled by the
        min-interval (there is genuinely pending work to apply).
        """
        now = time.monotonic()
        with self._lock:
            if len(self._active) >= self._settings.concurrent_rebuilds:
                return False
            if len(self._active) > 0 and self._active.get(projection_name) is not None:
                return False
            last = self._last_started.get(projection_name)
            if scheduled and last is not None and now - last < self._settings.min_interval_seconds:
                return False
            self._active[projection_name] = now
            self._last_started[projection_name] = now
            return True

    def release(self, projection_name: str) -> None:
        with self._lock:
            self._active.pop(projection_name, None)

    def active_rebuilds(self) -> list[str]:
        with self._lock:
            return sorted(self._active.keys())

    @property
    def concurrent_cap(self) -> int:
        return self._settings.concurrent_rebuilds


class ProjectionController:
    """Operator operations over the single-writer Tier-1 projection surface."""

    def __init__(
        self,
        engine: sa.Engine,
        store: ProjectionCheckpointStore | None = None,
        settings: Settings | None = None,
        ledger_tail_fn: Any | None = None,
    ) -> None:
        self._engine = engine
        self._store = store or ProjectionCheckpointStore(engine)
        self._settings = settings or Settings()
        self._coordinator = ReindexCoordinator(self._settings.rebuild)
        #: Callable ``rebase(projection_name) -> int`` returning the ledger tail; used
        #: for fresh/stale reporting without reaching into the ledger internals.
        self._ledger_tail_fn = ledger_tail_fn

    # -- checkpoint / freshness --------------------------------------------

    def checkpoint(self, projection_name: str) -> dict[str, Any]:
        """Read the durable checkpoint + fresh/stale status vs the live ledger tail."""
        cp = self._store.get(projection_name) or ProjectionCheckpoint(projection_name)
        tail = self._ledger_tail()
        lag = max(0, tail - cp.applied_seq)
        set_projection_lag(projection_name, lag)
        return {
            "projection": projection_name,
            "applied_seq": cp.applied_seq,
            "ledger_tail": tail,
            "lag": lag,
            "status": "fresh" if lag == 0 else ("stale" if lag > 0 else "no-op"),
            "paused": cp.pause_reason is not None,
            "pause_reason": cp.pause_reason,
        }

    def _ledger_tail(self) -> int:
        if self._ledger_tail_fn is not None:
            return int(self._ledger_tail_fn())
        with self._engine.connect() as conn:
            from umd.storage.postgres.tables import metadata as db_meta

            t = db_meta.tables["semantic_event"]
            tail = conn.execute(sa.select(sa.func.coalesce(sa.func.max(t.c.seq), 0))).scalar()
        return int(tail or 0)

    def set_checkpoint(self, projection_name: str, applied_seq: int) -> dict[str, Any]:
        """Single-writer checkpoint write (via the store) for one projection."""
        cp = self._store.get(projection_name) or ProjectionCheckpoint(projection_name)
        self._store.save(cp.with_applied(applied_seq))
        return self.checkpoint(projection_name)

    # -- rebuild -----------------------------------------------------------

    def rebuild(
        self,
        builder: ProjectionBuilder,
        *,
        wipe: bool = True,
        force_resume: bool = False,
    ) -> dict[str, Any]:
        """Schedule and run a rebuild through the canonical ReplayDriver path.

        Returns the :class:`BuildReport`-derived outcome plus budget check and
        coordinator metadata. Writes nothing directly — the builder owns the
        projection store.
        """
        name = builder.projection_name
        cp = self._store.get(name)
        # A paused projection NEVER auto-resumes: a non-force rebuild reports its
        # paused status without scheduling (and without touching the builder).
        if cp is not None and cp.pause_reason is not None and not force_resume:
            tail = self._ledger_tail()
            return {
                "projection": name,
                "started": True,
                "report": {
                    "projection": name,
                    "applied_seq": cp.applied_seq,
                    "ledger_tail": tail,
                    "skipped": 0,
                    "paused": True,
                    "pause_reason": cp.pause_reason,
                    "wipe": wipe,
                    "events_seen": 0,
                },
                "budget": self._evaluate_budget(0, 0.0),
                "duration_seconds": 0.0,
            }
        if not self._coordinator.acquire(name):
            return {
                "projection": name,
                "started": False,
                "reason": "reindex-cadence-busy",
                "active": self._coordinator.active_rebuilds(),
            }
        try:
            driver = ReplayDriver(self._engine, self._store)
            started = time.monotonic()
            report = driver.run(builder, wipe=wipe, force_resume=force_resume)
            duration = time.monotonic() - started
            budget = self._evaluate_budget(report.events_seen, duration)
            return {
                "projection": name,
                "started": True,
                "report": {
                    "projection": report.projection_name,
                    "applied_seq": report.applied_seq,
                    "ledger_tail": report.ledger_tail,
                    "skipped": report.skipped,
                    "paused": report.paused,
                    "pause_reason": report.pause_reason,
                    "wipe": report.wipe,
                    "events_seen": report.events_seen,
                },
                "budget": budget,
                "duration_seconds": round(duration, 3),
            }
        finally:
            self._coordinator.release(name)

    def _evaluate_budget(self, events_seen: int, duration: float) -> dict[str, Any]:
        over = []
        if events_seen > self._settings.rebuild.max_events:
            over.append(f"events {events_seen} > max {self._settings.rebuild.max_events}")
        if duration > self._settings.rebuild.max_seconds:
            over.append(f"seconds {duration:.1f} > max {self._settings.rebuild.max_seconds}")
        return {
            "within_budget": not over,
            "violations": over,
            "max_events": self._settings.rebuild.max_events,
            "max_seconds": self._settings.rebuild.max_seconds,
        }

    # -- pause alerts -------------------------------------------------------

    def pause_alerts(self) -> list[dict[str, Any]]:
        """Surface authority-poison pause alerts from alive paused checkpoints."""
        alerts: list[dict[str, Any]] = []
        with self._engine.connect() as conn:
            from umd.storage.postgres.tables import metadata as db_meta

            t = db_meta.tables["projection_checkpoint"]
            rows = (
                conn.execute(sa.select(t.c.projection_name, t.c.applied_seq, t.c.checkpoint))
                .mappings()
                .fetchall()
            )
        for r in rows:
            payload = dict(r["checkpoint"] or {})
            reason = payload.get("_pause_reason")
            if reason:
                alerts.append(
                    {
                        "projection": r["projection_name"],
                        "pause_reason": reason,
                        "pause_seq": int(payload.get("_pause_seq", 0)),
                        "applied_seq": int(r["applied_seq"]),
                    }
                )
        return alerts

    # -- promotion review ---------------------------------------------------

    def promotion_review(self, count: int | None = None) -> PromotionReview:
        """Measured promotion review behind ``VectorIndex`` at 5M/10M/50M."""
        from umd.operations.vector_ops import PROMOTION_THRESHOLDS

        n = self._monitor_count() if count is None else count
        crossed = [t for t in PROMOTION_THRESHOLDS if n >= t]
        candidates: list[str] = []
        if crossed:
            if n >= 50_000_000:
                candidates.append("dedicated-vector-store")
            if n >= 10_000_000:
                candidates.append("pgvectorscale")
            if n >= 5_000_000:
                candidates.append("halfvec")
        return PromotionReview(
            measured_count=n,
            growth_tier=crossed[-1] if crossed else None,
            promotion_candidates=candidates,
        )

    def _monitor_count(self) -> int:
        from umd.storage.postgres.tables import metadata as db_meta

        with self._engine.connect() as conn:
            t = db_meta.tables["embedding"]
            n = conn.execute(sa.select(sa.func.count(t.c.id))).scalar()
        return int(n or 0)

    def vector_capability(self, index: VectorIndex) -> dict[str, Any]:
        from umd.operations.vector_ops import VectorMonitor

        monitor = VectorMonitor(self._engine, index)
        return {
            "count": monitor.count(),
            "model_counts": monitor.model_counts(),
            "hnsw": monitor.hnsw_status(),
            "promotion": monitor.promote_eligibility(),
        }


__all__ = [
    "ProjectionController",
    "PromotionReview",
    "ReindexCoordinator",
    "VectorMonitor",
]
