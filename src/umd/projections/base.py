"""Single-writer Tier-1 projection replay driver (P2-S1).

Implements the binding contract
``ProjectionBuilder.replay(event_batch, checkpoint) -> ProjectionCheckpoint`` as a
durable driver that:

  * loads retained semantic events after the projection's checkpoint in canonical
    (seq) order and upcasts each through the pure upcaster chain (so every event
    version replays identically);
  * folds EVERY semantic event through the ONE shared :class:`CurrentStateReducer`
    so a Tier-1 projection derives the exact same canonical state as Tier-0
    (cross-tier equivalence is guaranteed by construction);
  * applies the poison policy: SKIP non-authoritative machine noise anchored to a
    quarantined locator; PAUSE (and stop) on authority-relevant events, exposing the
    pause reason through the checkpoint;
  * persists the checkpoint atomically with the projection's writes in ONE
    transaction (single-writer: the projection row's applied_seq is owned by its
    one builder).

Builders subclass :class:`ProjectionBuilder` and implement ``apply`` (and optional
``wipe`` / ``finalize``); the driver owns checkpointing, ordering, upcasting and the
canonical-state fold.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import sqlalchemy as sa

from umd.domain.events import SemanticEvent, upcast_payload
from umd.observability.records import (
    observe_stage_duration,
    record_projection_checkpoint,
    record_projection_pause,
    set_projection_lag,
)
from umd.projections.checkpoint import ProjectionCheckpoint, ProjectionCheckpointStore
from umd.projections.poison import PoisonDecision, classify
from umd.storage.postgres.reducer import CurrentReducedState, CurrentStateReducer
from umd.storage.postgres.tables import metadata as db_meta

_event_t = db_meta.tables["semantic_event"]
_quarantine_t = db_meta.tables["quarantine"]


@dataclass
class BuildReport:
    """Result of one projection build run."""

    projection_name: str
    applied_seq: int
    ledger_tail: int
    skipped: int = 0
    paused: bool = False
    pause_reason: str | None = None
    events_seen: int = 0
    wipe: bool = False

    @property
    def lag(self) -> int:
        return max(0, self.ledger_tail - self.applied_seq)

    @property
    def fresh(self) -> bool:
        return not self.paused and self.lag == 0

    def freshness_meta(self) -> dict[str, Any]:
        return {
            "applied_seq": self.applied_seq,
            "ledger_tail": self.ledger_tail,
            "lag": self.lag,
            "fresh": self.fresh,
            "paused": self.paused,
            "pause_reason": self.pause_reason,
        }


class ProjectionBuilder(Protocol):
    """A single-writer Tier-1 projection builder (contract-shaped protocol)."""

    projection_name: str

    def prepare(
        self, conn: sa.Connection, driver: ReplayDriver
    ) -> None:  # pragma: no cover - protocol
        """Hook before event replay (e.g. create per-schema table)."""

    def wipe(self, conn: sa.Connection, driver: ReplayDriver) -> None:  # pragma: no cover
        """Clear the projection store (wipe-and-rebuild)."""

    def apply(
        self, conn: sa.Connection, driver: ReplayDriver, event: SemanticEvent
    ) -> None:  # pragma: no cover
        """Apply one upcast semantic event to the projection store."""

    def on_skip(
        self, conn: sa.Connection, driver: ReplayDriver, event: SemanticEvent
    ) -> None:  # pragma: no cover
        """Called when a non-authoritative poison event is skipped (may no-op)."""

    def on_pause(
        self, conn: sa.Connection, driver: ReplayDriver, event: SemanticEvent
    ) -> None:  # pragma: no cover
        """Called when the driver pauses on an authority-relevant event."""

    def finalize(self, conn: sa.Connection, driver: ReplayDriver) -> None:  # pragma: no cover
        """Hook after event replay (e.g. refresh canonical-entity docs from state)."""


@dataclass
class ReplayDriver:
    """Owns checkpointing, ordering, upcasting, poison policy and the canonical fold."""

    engine: sa.Engine
    store: ProjectionCheckpointStore
    quarantine_loader: Any | None = None  # -> set[str]
    pause_policy: bool = True

    #: Canonical state folded from EVERY semantic event (equivalence with Tier-0).
    state: CurrentReducedState = field(default_factory=CurrentReducedState)
    #: Applied-seq counter / build-report accumulator for the current run.
    applied_seq: int = 0
    events_seen: int = 0
    skipped: int = 0
    pause_reason: str | None = None
    paused: bool = False
    _run_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @property
    def reducer(self) -> CurrentStateReducer:
        return _REDUCER

    def run(
        self,
        builder: ProjectionBuilder,
        *,
        wipe: bool = False,
        force_resume: bool = False,
    ) -> BuildReport:
        """Run one projection rebuild at a time per process."""
        with self._run_lock:
            return self._run_locked(builder, wipe=wipe, force_resume=force_resume)

    def _run_locked(
        self,
        builder: ProjectionBuilder,
        *,
        wipe: bool = False,
        force_resume: bool = False,
    ) -> BuildReport:
        started = time.monotonic()
        cp = self.store.get(builder.projection_name) or ProjectionCheckpoint(
            builder.projection_name
        )

        # A paused projection stays paused until explicitly resumed.
        if cp.pause_reason is not None and not force_resume:
            self.paused = True
            self.pause_reason = cp.pause_reason
            self.applied_seq = cp.applied_seq
            tail = self._ledger_tail()
            report = self._report(builder.projection_name, tail, wipe=False, events_seen=0)
            self._record_metrics(report, time.monotonic() - started)
            return report

        start_seq = 0 if wipe else cp.applied_seq
        if force_resume:
            cp = cp.resumed()

        self.paused = False
        self.pause_reason = None
        self.events_seen = 0
        self.skipped = 0
        # Canonical fold always rebuilds from EMPTY so a Tier-1 projection derives the
        # complete canonical state (cross-tier equivalence). ``wipe``/``force_resume``
        # also rebuild the index from scratch (apply from seq 0); otherwise the index
        # applies only not-yet-applied events while still folding everything.
        self.state = CurrentReducedState()
        fold_from = 0
        apply_from = 0 if (wipe or force_resume) else start_seq

        with self.engine.begin() as conn:
            # Serialize shared projection rebuilds before reading the event tail;
            # otherwise an older rebuild may finish later and regress the checkpoint.
            if self.engine.dialect.name == "postgresql":
                conn.execute(
                    sa.select(
                        sa.func.pg_advisory_xact_lock(sa.func.hashtext(builder.projection_name))
                    )
                )
            # The lock is acquired in this transaction, so read the checkpoint from
            # the same snapshot. This prevents a concurrent rebuild from causing a
            # stale start sequence after the lock is released.
            cp = self.store.get(builder.projection_name, conn=conn) or ProjectionCheckpoint(
                builder.projection_name
            )
            start_seq = 0 if wipe else cp.applied_seq
            if force_resume:
                cp = cp.resumed()
            if wipe or force_resume:
                builder.wipe(conn, self)
            builder.prepare(conn, self)
            quarantined = self._load_quarantine(conn)

            all_events = self._load_events(conn, after=fold_from)
            # A forced resume re-reconciles THROUGH the authority event that paused the
            # projection (the pause reason is resolved), so poison is disabled for the run.
            poison_enabled = getattr(builder, "poison_enabled", True) and not force_resume
            for row in all_events:
                sem = self._upcast(row)
                seq = sem.seq or 0
                # Canonical fold: EVERY semantic event folds (equivalence with Tier-0).
                if sem.is_semantic:
                    self.reducer.reduce(self.state, sem)
                if seq <= apply_from:
                    # already applied to the index in a prior run.
                    continue
                self.events_seen += 1
                outcome = classify(sem, quarantined=quarantined)
                if (
                    outcome.decision == PoisonDecision.PAUSE
                    and self.pause_policy
                    and poison_enabled
                ):
                    self.paused = True
                    self.pause_reason = outcome.reason
                    self.applied_seq = seq
                    builder.on_pause(conn, self, sem)
                    break
                if outcome.decision == PoisonDecision.SKIP and self.pause_policy and poison_enabled:
                    self.skipped += 1
                    self.applied_seq = seq
                    builder.on_skip(conn, self, sem)
                    continue
                self.applied_seq = seq
                builder.apply(conn, self, sem)
            builder.finalize(conn, self)

            new_cp = cp.with_applied(self.applied_seq)
            if self.paused:
                new_cp = new_cp.paused(self.pause_reason or "", self.applied_seq)
            self.store.save(new_cp, conn=conn)

        report = self._report(
            builder.projection_name, self._ledger_tail(), wipe=wipe, events_seen=self.events_seen
        )
        # Observability (P1-S1): lag gauge + checkpoint counter + pause counter +
        # build duration histogram, correlated to the projection under rebuild.
        self._record_metrics(report, time.monotonic() - started)
        return report

    def _record_metrics(self, report: BuildReport, duration_seconds: float) -> None:
        """Record projection observability metrics (P1-S1)."""
        set_projection_lag(report.projection_name, report.lag)
        record_projection_checkpoint(report.projection_name, report.applied_seq)
        if report.paused:
            record_projection_pause(report.projection_name)
        observe_stage_duration(report.projection_name, duration_seconds)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _report(
        self,
        name: str,
        tail: int,
        *,
        wipe: bool,
        events_seen: int,
    ) -> BuildReport:
        return BuildReport(
            projection_name=name,
            applied_seq=self.applied_seq,
            ledger_tail=tail,
            skipped=self.skipped,
            paused=self.paused,
            pause_reason=self.pause_reason,
            events_seen=events_seen,
            wipe=wipe,
        )

    def _load_events(self, conn: sa.Connection, after: int) -> list[sa.Row[Any]]:
        rows = conn.execute(
            sa.select(
                _event_t.c.seq,
                _event_t.c.event_type,
                _event_t.c.event_version,
                _event_t.c.payload,
                _event_t.c.authority,
                _event_t.c.confidence,
            )
            .where(_event_t.c.seq > after)
            .order_by(_event_t.c.seq)
        ).fetchall()
        return list(rows)

    def _upcast(self, row: sa.Row[Any]) -> SemanticEvent:
        raw = dict(row.payload or {})
        version, payload = upcast_payload(row.event_type, int(row.event_version or 1), raw)
        return SemanticEvent(
            event_type=row.event_type,
            payload=payload,
            authority=row.authority,
            confidence=row.confidence,
            seq=int(row.seq),
        )

    def _load_quarantine(self, conn: sa.Connection) -> set[str]:
        if self.quarantine_loader is not None:
            q = self.quarantine_loader(self.engine)
            return set(q)
        rows = conn.execute(sa.select(_quarantine_t.c.locator, _quarantine_t.c.refs)).fetchall()
        out: set[str] = set()
        for r in rows:
            if r.locator:
                out.add(str(r.locator))
            refs = r.refs
            if isinstance(refs, dict):
                out.update(str(v) for v in refs.values() if isinstance(v, str))
            elif isinstance(refs, list):
                out.update(str(v) for v in refs if isinstance(v, str))
        return out

    def _ledger_tail(self) -> int:
        with self.engine.connect() as conn:
            tail = conn.execute(sa.select(sa.func.max(_event_t.c.seq))).scalar()
        return int(tail) if tail is not None else 0


_REDUCER = CurrentStateReducer()


__all__ = [
    "ReplayDriver",
    "ProjectionBuilder",
    "BuildReport",
]
