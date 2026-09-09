"""Widen ``current_state.object_ref`` to TEXT (Plan U, P3-S3).

Active canonical-identity reads now retain complete provenance — ``generated_by``
(machine provider/config or human override), ``created_by``/actor,
correspondence/derivation refs, identity classification, confidence/state and
support refs — all folded into the ``current_state.object_ref`` metadata JSON on
the canonical-identity Tier-0 row. With full provenance the serialized metadata
can exceed the previous ``VARCHAR(512)``, so this additive migration widens the
column to ``TEXT``. ``TEXT`` and ``VARCHAR`` share the same underlying storage in
PostgreSQL, so this is a metadata-only widening; no existing data is rewritten.

Additive and idempotent ``ALTER`` (a re-upgrade is a no-op since the target type
is already ``TEXT``).

Revision ID: 0010_object_ref_text
Revises: 0009_search_scope
Create Date: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010_object_ref_text"
down_revision: str | None = "0009_search_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE current_state ALTER COLUMN object_ref TYPE TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE current_state ALTER COLUMN object_ref TYPE VARCHAR(512)")
