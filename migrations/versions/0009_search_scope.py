"""Search-document membership scope columns (Plan T P2-S2).

Adds ``work_id`` and ``continuity_id`` to ``search_document`` so the search
projection can derive canonical label/alias source/work/continuity scope from
replay-backed memberships (the canonical identity metadata's ``memberships``
dict). The ``source_id`` column already exists and now carries a canonical's
per-source membership visibility. Forward-only, additive, and idempotent for
the final-dry-run re-upgrade (``upgrade head`` after head is a no-op).

Revision ID: 0009_search_scope
Revises: 0008_active_semantic_edge
Create Date: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_search_scope"
down_revision: str | None = "0008_active_semantic_edge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE search_document ADD COLUMN IF NOT EXISTS work_id VARCHAR(64)")
    op.execute("ALTER TABLE search_document ADD COLUMN IF NOT EXISTS continuity_id VARCHAR(64)")


def downgrade() -> None:
    op.execute("ALTER TABLE search_document DROP COLUMN IF EXISTS continuity_id")
    op.execute("ALTER TABLE search_document DROP COLUMN IF EXISTS work_id")
