"""Single-writer projection checkpoints (P2-S1).

Backs the binding contract ``ProjectionBuilder.replay(event_batch, checkpoint) ->
ProjectionCheckpoint`` with a durable checkpoint row in ``projection_checkpoint`` whose
``projection_name`` is the PRIMARY KEY — so each projection has exactly one checkpoint
and exactly one writer. The replay drivers fold their applied sequence, durability
payload and (blue/green) generation hints here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa

from umd.storage.postgres.tables import metadata as db_meta

_checkpoint_t = db_meta.tables["projection_checkpoint"]

pg_insert = sa.dialects.postgresql.insert


@dataclass
class ProjectionCheckpoint:
    """Durable writer checkpoint for one single-writer projection."""

    projection_name: str
    applied_seq: int = 0
    checkpoint: dict[str, Any] = field(default_factory=dict)
    #: Non-empty when the projection is paused on an authority-relevant poison event.
    pause_reason: str | None = None
    #: The seq at which the pause was recorded (replays resume from here).
    pause_seq: int = 0

    def with_applied(self, applied_seq: int, **extra: Any) -> ProjectionCheckpoint:
        return ProjectionCheckpoint(
            projection_name=self.projection_name,
            applied_seq=applied_seq,
            checkpoint={**self.checkpoint, **extra},
            pause_reason=self.pause_reason,
            pause_seq=self.pause_seq,
        )

    def paused(self, reason: str, at_seq: int) -> ProjectionCheckpoint:
        return ProjectionCheckpoint(
            projection_name=self.projection_name,
            applied_seq=self.applied_seq,
            checkpoint=self.checkpoint,
            pause_reason=reason,
            pause_seq=at_seq,
        )

    def resumed(self) -> ProjectionCheckpoint:
        return ProjectionCheckpoint(
            projection_name=self.projection_name,
            applied_seq=self.applied_seq,
            checkpoint=self.checkpoint,
            pause_reason=None,
            pause_seq=0,
        )


class ProjectionCheckpointStore:
    """Reads/writes ``projection_checkpoint`` (the single-writer durable checkpoint)."""

    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    def get(
        self, projection_name: str, *, conn: sa.Connection | None = None
    ) -> ProjectionCheckpoint | None:
        if conn is None:
            with self._engine.connect() as owned_conn:
                return self.get(projection_name, conn=owned_conn)
        row = conn.execute(
            sa.select(_checkpoint_t).where(_checkpoint_t.c.projection_name == projection_name)
        ).first()
        if row is None:
            return None
        payload = dict(row.checkpoint or {})
        return ProjectionCheckpoint(
            projection_name=projection_name,
            applied_seq=int(row.applied_seq),
            checkpoint=payload,
            pause_reason=payload.get("_pause_reason"),
            pause_seq=int(payload.get("_pause_seq", 0)),
        )

    def save(self, cp: ProjectionCheckpoint, *, conn: sa.Connection | None = None) -> None:
        """Atomic single-writer upsert (unique ``projection_name``)."""
        payload = dict(cp.checkpoint)
        if cp.pause_reason is not None:
            payload["_pause_reason"] = cp.pause_reason
            payload["_pause_seq"] = cp.pause_seq
        else:
            payload.pop("_pause_reason", None)
            payload.pop("_pause_seq", None)
        values = {
            "projection_name": cp.projection_name,
            "applied_seq": cp.applied_seq,
            "checkpoint": payload,
        }
        stmt = pg_insert(_checkpoint_t).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[_checkpoint_t.c.projection_name],
            set_={"applied_seq": cp.applied_seq, "checkpoint": payload},
        )
        if conn is not None:
            conn.execute(stmt)
            return
        with self._engine.begin() as c:
            c.execute(stmt)


def make_projection_id() -> str:
    """A stable unique id for a projection row (blue/green generation suffix)."""
    return uuid.uuid4().hex


__all__ = [
    "ProjectionCheckpoint",
    "ProjectionCheckpointStore",
    "make_projection_id",
]
