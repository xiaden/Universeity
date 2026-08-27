"""Tier-1 current-state projection builder (P2-S1 / wipe-and-replay equivalence).

Rebuilds the full ``current_state`` table from the immutable semantic ledger by folding
every semantic event through the ONE shared :class:`CurrentStateReducer` — the exact same
code path the inline Tier-0 append uses. This is the "Tier-1 current projection": it is a
disposable, single-writer, checkpointed, wipe-and-replay rebuild whose canonical rows must
be equivalent to Tier-0. The driver always folds from empty (see :meth:`ReplayDriver.run`),
so a wipe-and-replay run derives the identical canonical state by construction.

``checksum()`` is a deterministic digest over the sorted canonical rows; cross-tier
equivalence is asserted as ``tier1.checksum() == tier0_checksum``.
"""

from __future__ import annotations

import hashlib
from typing import Any

import sqlalchemy as sa

from umd.projections.base import ReplayDriver
from umd.storage.postgres.reducer import LOCK_PREDICATE, STATE_UNLOCKED, CurrentStateReducer
from umd.storage.postgres.tables import metadata as db_meta

_state_t = db_meta.tables["current_state"]

pg_insert = sa.dialects.postgresql.insert


class CurrentTierOneBuilder:
    """Single-writer wipe-and-replay builder for the ``current_state`` projection."""

    projection_name = "current_tier1"

    # The current-state projection MUST equal Tier-0, so it folds every semantic event and
    # never pauses/skips on poison (authority events are part of the canonical state).
    poison_enabled = False

    def __init__(self, reducer: CurrentStateReducer | None = None) -> None:
        self._reducer = reducer or _REDUCER

    # -- ProjectionBuilder protocol ---------------------------------------

    def prepare(self, conn: sa.Connection, driver: ReplayDriver) -> None:
        return None

    def wipe(self, conn: sa.Connection, driver: ReplayDriver) -> None:
        conn.execute(_state_t.delete())

    def apply(self, conn: sa.Connection, driver: ReplayDriver, event: Any) -> None:
        # Canonical state is folded by the driver; nothing extra to write per event.
        return None

    def on_skip(self, conn: sa.Connection, driver: ReplayDriver, event: Any) -> None:
        return None

    def on_pause(self, conn: sa.Connection, driver: ReplayDriver, event: Any) -> None:
        return None

    def finalize(self, conn: sa.Connection, driver: ReplayDriver) -> None:
        self._persist(conn, driver.state)

    # -- helpers -----------------------------------------------------------

    def _persist(self, conn: sa.Connection, state: Any) -> None:
        for _key, row in state.rows.items():
            if row.predicate == LOCK_PREDICATE and row.state == STATE_UNLOCKED:
                # An unlocked marker is a no-op row; drop it (absence => unlocked),
                # mirroring the inline Tier-0 append path.
                continue
            cols = row.scalar()
            stmt = pg_insert(_state_t).values(**cols)
            stmt = stmt.on_conflict_do_update(
                constraint="pk_current_state_tier0",
                set_={
                    "object_ref": cols["object_ref"],
                    "confidence": cols["confidence"],
                    "authority": cols["authority"],
                    "state": cols["state"],
                    "seq": cols["seq"],
                },
            )
            conn.execute(stmt)

    def checksum(self, engine: sa.Engine) -> str:
        """Deterministic digest of the canonical Tier-1 current-state rows.

        The digest is produced purely from the ``current_state`` table (this projection's
        store) so a wipe-and-replay rebuild yields the identical value iff the rebuilt
        state equals the pre-wipe (inline Tier-0) state.
        """
        with engine.connect() as conn:
            rows = conn.execute(
                sa.select(
                    _state_t.c.entity_ref,
                    _state_t.c.predicate,
                    _state_t.c.object_ref,
                    _state_t.c.confidence,
                    _state_t.c.authority,
                    _state_t.c.state,
                    _state_t.c.seq,
                ).order_by(_state_t.c.entity_ref, _state_t.c.predicate)
            ).fetchall()
        h = hashlib.sha256()
        for r in rows:
            h.update(
                "|".join(
                    [
                        str(r.entity_ref),
                        str(r.predicate),
                        str(r.object_ref or ""),
                        str(r.confidence if r.confidence is not None else ""),
                        str(r.authority or ""),
                        str(r.state or ""),
                        str(int(r.seq or 0)),
                    ]
                ).encode()
            )
            h.update(b"\n")
        return h.hexdigest()


_REDUCER = CurrentStateReducer()


def tier0_checksum(engine: sa.Engine) -> str:
    """Checksum of the inline Tier-0 ``current_state`` (for cross-tier equivalence)."""
    return CurrentTierOneBuilder().checksum(engine)


__all__ = ["CurrentTierOneBuilder", "tier0_checksum"]
