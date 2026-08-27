"""DB-authoritative evidence idempotency (phase-b, P2-S2 round-1)

Adds a UNIQUE index on ``(source_id, locator, evidence_kind, config_digest)`` so
that re-recording identical extraction output (same source + locator + kind +
config digest) is a DB-asserted no-op rather than a silent duplicate row. The
evidence repository inserts with ``ON CONFLICT DO NOTHING`` against this index,
so cross-call re-runs are idempotent (journaled as ``existing``, never
re-inserted as a fresh row).

Revision ID: 0003_evidence_identity_unique
Revises: 0002_jobs
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_evidence_identity_unique"
down_revision: str | None = "0002_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Unique index/constraint name, shared with the ``evidence`` table definition in
#: :mod:`umd.storage.postgres.tables` (so ``metadata.create_all`` in
#: ``0001_initial_core`` emits it on fresh bootstraps too).
_INDEX = "uq_evidence_identity"
_COLUMNS = ["source_id", "locator", "evidence_kind", "config_digest"]


def upgrade() -> None:
    # ``0001_initial_core`` uses ``metadata.create_all`` against the live
    # metadata, which already emits the unique index on a fresh bootstrap.
    # Guard (online only — offline SQL generation has no real inspector) so this
    # migration is idempotent for both fresh bootstraps and databases migrated
    # before the index existed.
    if not op.get_context().as_sql:
        indexes = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("evidence")}
        if _INDEX in indexes:
            return
    op.create_index(_INDEX, "evidence", _COLUMNS, unique=True)


def downgrade() -> None:
    if not op.get_context().as_sql:
        indexes = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("evidence")}
        if _INDEX not in indexes:
            return
    op.drop_index(_INDEX, table_name="evidence")
