"""initial typed relational core (works/continuity/sources, segments, evidence,
entities/predicates/assertions, semantic-event ledger, Tier-0 projections,
embeddings, stage/job, quarantine, locator rebase, projection checkpoints)

This single structural migration renders the canonical metadata defined in
:mod:`umd.storage.postgres.tables` and installs the append-only guard trigger on
the ``semantic_event`` ledger (no in-place UPDATE) and the immutable-op guard on
``embedding``.

Revision ID: 0001_initial_core
Revises:
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from umd.storage.postgres.tables import metadata

# revision identifiers, used by Alembic.
revision: str = "0001_initial_core"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    metadata.create_all(bind=op.get_bind(), checkfirst=True)

    # Install append-only NO-UPDATE/DELETE guards on the immutable ledger rows.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION block_semantic_event_mutate()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'append-only ledger: UPDATE/DELETE forbidden on semantic_event (% %)', TG_OP, TG_TABLE_NAME USING ERRCODE = '55000';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_semantic_event_append_only
        BEFORE UPDATE OR DELETE ON semantic_event
        FOR EACH ROW EXECUTE FUNCTION block_semantic_event_mutate();
        """
    )
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
    op.execute(
        """
        CREATE TRIGGER trg_embedding_append_only
        BEFORE UPDATE OR DELETE ON embedding
        FOR EACH ROW EXECUTE FUNCTION block_embedding_mutate();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_semantic_event_append_only ON semantic_event;")
    op.execute("DROP FUNCTION IF EXISTS block_semantic_event_mutate();")
    op.execute("DROP TRIGGER IF EXISTS trg_embedding_append_only ON embedding;")
    op.execute("DROP FUNCTION IF EXISTS block_embedding_mutate();")
    metadata.drop_all(bind=op.get_bind())
