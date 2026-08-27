"""Segments carry a valid-time range + spatial-capable JSONB for query scope (Phase 4).

Adds the columns the bounded structured-query scope filters compile against:

  * ``segment.start_time`` / ``segment.end_time`` (TIMESTAMPTZ, indexed) — the
    "segment time-range" used by temporal scope with correct open-ended bounds.
  * a GIN index on ``segment.metadata_`` so the JSONB-containment spatial predicate
    is index-backed rather than a full scan.

These are additive and idempotent for the final-dry-run re-upgrade (Alembic records
its revision, so ``upgrade head`` is a no-op). Existing rows keep NULL time-range
values; only segments with a recorded time range participate in temporal filtering.

Revision ID: 0005_scope_filters
Revises: 0004_projections
Create Date: 2026-08-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_scope_filters"
down_revision: str | None = "0004_projections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE segment ADD COLUMN IF NOT EXISTS start_time TIMESTAMPTZ")
    op.execute("ALTER TABLE segment ADD COLUMN IF NOT EXISTS end_time TIMESTAMPTZ")
    # IF NOT EXISTS: 0001's metadata.create_all does not declare these, but guard
    # against any re-upgrade / pre-created index so `upgrade head` is a no-op.
    op.execute("CREATE INDEX IF NOT EXISTS ix_segment_start_time ON segment (start_time)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_segment_end_time ON segment (end_time)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_segment_metadata_gin ON segment USING GIN (metadata_)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_segment_start_time")
    op.execute("DROP INDEX IF EXISTS ix_segment_end_time")
    op.execute("DROP INDEX IF EXISTS ix_segment_metadata_gin")
    op.execute("ALTER TABLE segment DROP COLUMN IF EXISTS start_time")
    op.execute("ALTER TABLE segment DROP COLUMN IF EXISTS end_time")
