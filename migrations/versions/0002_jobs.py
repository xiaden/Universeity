"""durable job aggregate (phase-b, P1-S3)

Adds the operational ``job`` table (aggregate status / cancelled stages / error)
alongside the existing ``stage_run`` and ``job_run_audit`` tables. Job state is
purely operational — it never feeds semantic Tier-0 replay.

Revision ID: 0002_jobs
Revises: 0001_initial_core
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_jobs"
down_revision: str | None = "0001_initial_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ``0001_initial_core`` uses ``metadata.create_all`` against the live
    # metadata, which already emits the ``job`` table + its indexes on a fresh
    # bootstrap. Guard (online only — offline SQL generation has no real
    # inspector) so this migration is idempotent for both fresh bootstraps and
    # databases migrated before ``job`` existed.
    if not op.get_context().as_sql:
        if "job" in sa.inspect(op.get_bind()).get_table_names():
            return
    op.create_table(
        "job",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("source.id", ondelete="SET NULL")),
        sa.Column("dag_universe", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("request", sa.JSON(), server_default=sa.text("'{}'::jsonb")),
        sa.Column("cancelled_stages", sa.JSON(), server_default=sa.text("'[]'::jsonb")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_job_source_id", "job", ["source_id"])
    op.create_index("ix_job_status", "job", ["status"])


def downgrade() -> None:
    if not op.get_context().as_sql:
        if "job" not in sa.inspect(op.get_bind()).get_table_names():
            return
    op.drop_index("ix_job_status", table_name="job")
    op.drop_index("ix_job_source_id", table_name="job")
    op.drop_table("job")
