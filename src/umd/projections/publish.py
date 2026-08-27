"""Blue/green projection rebuild + publish with grace period (P2-S2).

Disposable Tier-1 projections are rebuilt into a *generation* schema
(``proj_<name>_<generation>``), then PUBLISHED. The previously-published generation is
RETIRED and retained for ``grace_period_seconds`` before being dropped (reaped). Read
connections pin ``search_path`` to the CURRENT published generation's schema at checkout,
so:

  * a stale pooled connection checked out before the swap is pinned to the OLD schema —
    during grace it reads OLD data (never prematurely-new), and after the old schema is
    dropped it ERRORS (relation does not exist) rather than silently seeing new data;
  * a connection checked out after the swap reads the NEW schema.

This proves (a) old pooled connections cannot read a dropped schema, and that the only
schema-swap path is publish (builders never mutate the published schema in place; the
builder is the sole writer of its store and only ever writes its BUILDING generation).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as _pg_dialect

from umd.projections.tables import ensure_search_table_created, projection_generation

pg_insert = _pg_dialect.insert

_pg = projection_generation


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class ProjectionGeneration:
    projection_name: str
    generation: int
    schema_name: str
    state: str
    published_at: datetime | None
    grace_deadline: datetime | None
    checkpoint_seq: int

    @property
    def is_building(self) -> bool:
        return self.state == "BUILDING"

    @property
    def is_published(self) -> bool:
        return self.state == "PUBLISHED"


class ProjectionPublishManager:
    """Owns generation lifecycles: BUILDING -> PUBLISHED -> RETIRED -> REAPED."""

    STATE_BUILDING = "BUILDING"
    STATE_PUBLISHED = "PUBLISHED"
    STATE_RETIRED = "RETIRED"
    STATE_REAPED = "REAPED"

    def __init__(self, engine: sa.Engine, *, grace_period_seconds: float = 300.0) -> None:
        self._engine = engine
        self.grace_period_seconds = grace_period_seconds

    # -- generation helpers -------------------------------------------------

    def schema_for(self, projection_name: str, generation: int) -> str:
        return f"proj_{projection_name}_{generation}"

    # -- build --------------------------------------------------------------

    def begin_build(self, projection_name: str) -> int:
        """Start building a new generation: CREATE the generation schema + store tables.

        The builder is the ONLY writer to the generation store; nothing else touches it
        until :meth:`publish` swaps it in.
        """
        generation = self._next_generation(projection_name)
        schema = self.schema_for(projection_name, generation)
        with self._engine.begin() as conn:
            conn.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            ensure_search_table_created(conn, schema)
            self._upsert_row(
                conn,
                ProjectionGeneration(
                    projection_name, generation, schema, self.STATE_BUILDING, None, None, 0
                ),
            )
        return generation

    def mark_built(self, projection_name: str, generation: int, checkpoint_seq: int) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                _pg.update()
                .where(
                    (_pg.c.projection_name == projection_name) & (_pg.c.generation == generation)
                )
                .values(checkpoint_seq=checkpoint_seq)
            )

    # -- publish / retire / reap ---------------------------------------------

    def publish(self, projection_name: str, generation: int) -> None:
        """Publish a built generation; retire the prior published one with a grace window."""
        now = _now()
        deadline = now + timedelta(seconds=self.grace_period_seconds)
        with self._engine.begin() as conn:
            # Retire any currently-published generation.
            prior = conn.execute(
                sa.select(_pg.c.generation, _pg.c.schema_name).where(
                    (_pg.c.projection_name == projection_name)
                    & (_pg.c.state == self.STATE_PUBLISHED)
                )
            ).fetchall()
            for r in prior:
                conn.execute(
                    _pg.update()
                    .where(
                        (_pg.c.projection_name == projection_name)
                        & (_pg.c.generation == r.generation)
                    )
                    .values(state=self.STATE_RETIRED, grace_deadline=deadline)
                )
            # Mark this generation published.
            conn.execute(
                _pg.update()
                .where(
                    (_pg.c.projection_name == projection_name) & (_pg.c.generation == generation)
                )
                .values(state=self.STATE_PUBLISHED, published_at=now, grace_deadline=None)
            )

    def retire(self, projection_name: str, generation: int) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                _pg.update()
                .where(
                    (_pg.c.projection_name == projection_name) & (_pg.c.generation == generation)
                )
                .values(
                    state=self.STATE_RETIRED,
                    grace_deadline=_now() + timedelta(seconds=self.grace_period_seconds),
                )
            )

    def reap_expired(self, now: datetime | None = None) -> list[ProjectionGeneration]:
        """Drop retired generation schemas whose grace period has expired (RETIRED -> REAPED)."""
        now = now or _now()
        reaped: list[ProjectionGeneration] = []
        with self._engine.begin() as conn:
            rows = conn.execute(
                sa.select(_pg).where(
                    (_pg.c.state == self.STATE_RETIRED)
                    & (_pg.c.grace_deadline.is_not(None))
                    & (_pg.c.grace_deadline <= now)
                )
            ).fetchall()
            for r in rows:
                self._drop_schema(conn, r.schema_name)
                conn.execute(
                    _pg.update()
                    .where(
                        (_pg.c.projection_name == r.projection_name)
                        & (_pg.c.generation == r.generation)
                    )
                    .values(state=self.STATE_REAPED, grace_deadline=None)
                )
                reaped.append(
                    ProjectionGeneration(
                        r.projection_name,
                        r.generation,
                        r.schema_name,
                        self.STATE_REAPED,
                        r.published_at,
                        None,
                        int(r.checkpoint_seq or 0),
                    )
                )
        return reaped

    def drop_generation(self, projection_name: str, generation: int) -> None:
        schema = self.schema_for(projection_name, generation)
        with self._engine.begin() as conn:
            self._drop_schema(conn, schema)
            conn.execute(
                _pg.delete().where(
                    (_pg.c.projection_name == projection_name) & (_pg.c.generation == generation)
                )
            )

    def _drop_schema(self, conn: sa.Connection, schema: str) -> None:
        conn.exec_driver_sql(f"DROP SCHEMA IF EXISTS {schema} CASCADE")

    # -- read-path helpers -----------------------------------------------------

    def current_generation(self, projection_name: str) -> int | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.select(_pg.c.generation)
                .where(
                    (_pg.c.projection_name == projection_name)
                    & (_pg.c.state == self.STATE_PUBLISHED)
                )
                .order_by(sa.desc(_pg.c.generation))
                .limit(1)
            ).first()
        return int(row.generation) if row else None

    def current_schema(self, projection_name: str) -> str | None:
        gen = self.current_generation(projection_name)
        if gen is None:
            return None
        return self.schema_for(projection_name, gen)

    def generations(self, projection_name: str | None = None) -> list[ProjectionGeneration]:
        stmt = sa.select(_pg)
        if projection_name is not None:
            stmt = stmt.where(_pg.c.projection_name == projection_name)
        stmt = stmt.order_by(_pg.c.projection_name, _pg.c.generation)
        with self._engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return [
            ProjectionGeneration(
                r.projection_name,
                r.generation,
                r.schema_name,
                r.state,
                r.published_at,
                r.grace_deadline,
                int(r.checkpoint_seq or 0),
            )
            for r in rows
        ]

    def pin_search_path(self, conn: sa.Connection, projection_name: str) -> str | None:
        """Pin a (pooled) read connection's ``search_path`` to the current generation.

        Returns the pinned schema name, or ``None`` if no generation is published yet.
        A connection pinned before a later :meth:`publish` keeps the OLD schema until its
        pool re-checks out — the exact stale-connection property blue/green is designed to
        prove.
        """
        schema = self.current_schema(projection_name)
        if schema is None:
            return None
        conn.exec_driver_sql(f"SET search_path = {schema}, public")
        return schema

    # -- internals --------------------------------------------------------------

    def _next_generation(self, projection_name: str) -> int:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.select(sa.func.coalesce(sa.func.max(_pg.c.generation), 0)).where(
                    _pg.c.projection_name == projection_name
                )
            ).scalar()
        return int(row or 0) + 1

    def _upsert_row(self, conn: sa.Connection, gen: ProjectionGeneration) -> None:
        stmt = pg_insert(_pg).values(
            projection_name=gen.projection_name,
            generation=gen.generation,
            schema_name=gen.schema_name,
            state=gen.state,
            published_at=gen.published_at,
            grace_deadline=gen.grace_deadline,
            checkpoint_seq=gen.checkpoint_seq,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[_pg.c.projection_name, _pg.c.generation],
            set_={"state": gen.state, "schema_name": gen.schema_name},
        )
        conn.execute(stmt)


__all__ = ["ProjectionPublishManager", "ProjectionGeneration"]
