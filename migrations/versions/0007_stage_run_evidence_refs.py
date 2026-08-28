"""Persist evidence references on stage_run for atomic completion (Phase G, P2-S4).

The durable stage-completion invariant (DD "Durable stage execution") commits the
authoritative artifact references AND the ``StageCompleted`` semantic event in one
``stage_run``-row update + one ledger append, so a crash cannot commit a completion
without its evidence. Until now the authoritative *evidence* references the stage
produced lived only inside the ``StageCompleted`` event payload, not on the
``stage_run`` row itself. The Phase-2 production registry contract
(CONTRACTS.md:60) and its spec-first registry tests require both ``artifact_refs``
and ``evidence_refs`` to be queryable on the ``stage_run`` row.

This migration adds the ``evidence_refs`` JSONB column to ``stage_run`` and makes
it non-null (default ``'{}'``). It is written idempotently (``ADD COLUMN IF NOT
EXISTS``) because ``0001_initial_core`` renders the live metadata via
``metadata.create_all``, which already emits the column on a freshly-migrated
database; this migration only needs to alter databases that were migrated before
the column existed. The executor's completion side-effect writes the column in the
same UPDATE that marks the run ``complete``, keeping artifact + evidence +
StageCompleted atomic.

Revision ID: 0007_stage_run_evidence_refs
Revises: 0006_projection_wipe_gate
Create Date: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_stage_run_evidence_refs"
down_revision: str | None = "0006_projection_wipe_gate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE stage_run ADD COLUMN IF NOT EXISTS evidence_refs JSONB")
    # Backfill committed rows so the non-null invariant holds.
    op.execute("UPDATE stage_run SET evidence_refs = '[]'::jsonb WHERE evidence_refs IS NULL")
    op.execute("ALTER TABLE stage_run ALTER COLUMN evidence_refs SET DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE stage_run ALTER COLUMN evidence_refs SET NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE stage_run DROP COLUMN IF EXISTS evidence_refs")
