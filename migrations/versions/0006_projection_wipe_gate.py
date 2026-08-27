"""Projection wipe gate: allow the single-writer builder to reset its store (Phase F/P2-S1).

The ``embedding`` table is an immutable, append-only Tier-1 projection store guarded by
``block_embedding_mutate()`` (migration 0001): every UPDATE/DELETE is refused so only the
building path appends rows and no accidental/direct mutation ever occurs.

That guard also blocked the projection BUILDER's own ``wipe()`` (EmbeddingProjectionBuilder
wipes its store before a wipe-and-replay rebuild) once the store was non-empty, because a
``BEFORE DELETE ... FOR EACH ROW`` trigger fires per-row. This was invisible to earlier
tests because they only ever wiped an *empty* embedding table. DD/REPLAY requires *every*
Tier-1 projection to wipe-and-replay from ``seq=0``, so the builder must be able to reset its
own disposable store.

This migration preserves the immutability guarantee (all non-builder UPDATE/DELETE stays
blocked) while honouring an explicit, transaction-scoped opt-in: when the single-writer
builder sets the GUC ``umd.projection_wipe = 'vector'`` via ``set_config(..., is_local := true)``
immediately before its wipe DELETE, the per-row guard permits it. ``is_local := true`` scopes
the GUC to the current transaction only, so on a pooled connection it never leaks past the
wipe transaction into later statements on that session. No other code path sets that GUC, so
the authority/immutability boundary is unchanged.

Revision ID: 0006_projection_wipe_gate
Revises: 0005_scope_filters
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_projection_wipe_gate"
down_revision: str | None = "0005_scope_filters"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The builder opts in with ``set_config('umd.projection_wipe','vector',true)``
    # (is_local=true, transaction-scoped) immediately before its wipe; the guard then
    # permits the DELETE for that one builder. Everything else is still refused.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION block_embedding_mutate()
        RETURNS TRIGGER AS $$
        BEGIN
            IF current_setting('umd.projection_wipe', true) = 'vector' THEN
                RETURN COALESCE(NEW, OLD);
            END IF;
            RAISE EXCEPTION 'immutable rows: UPDATE/DELETE forbidden on embedding (% %)', TG_OP, TG_TABLE_NAME USING ERRCODE = '55000';
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    # Restore the strict (no opt-in) immutable guard from migration 0001.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION block_embedding_mutate()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'immutable rows: UPDATE/DELETE forbidden on embedding (% %)', TG_OP, TG_TABLE_NAME USING ERRCODE = '55000';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
