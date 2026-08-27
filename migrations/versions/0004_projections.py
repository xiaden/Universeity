"""Tier-1 projection storage: search documents + blue/green generation registry (Phase 2).

Adds the search/vector/query projection stores:
  * ``search_document`` — the exact/full-text search store: one row per indexed unit with
    a native GENERATED STORED ``tsvector`` column (GIN indexed) and a pg_trgm fuzzy index.
  * ``projection_generation`` — the blue/green registry (which generation schema is
    BUILDING / PUBLISHED / RETIRED / REAPED and when a retired schema's grace period ends).

These tables are written ONLY by projection builders (single-writer); the blue/green
schema-swap is the only substitute path. The migration is additive and idempotent for the
final-dry-run re-upgrade (Alembic records its revision, so ``upgrade head`` is a no-op).

Revision ID: 0004_projections
Revises: 0003_evidence_identity_unique
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_projections"
down_revision: str | None = "0003_evidence_identity_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pg_trgm provides the similarity operators and GIN opclass for fuzzy search.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS search_document (
            id VARCHAR(36) PRIMARY KEY,
            ref VARCHAR(512) NOT NULL,
            kind VARCHAR(32) NOT NULL,
            text TEXT NOT NULL,
            language VARCHAR(16),
            source_id VARCHAR(64),
            segment_id VARCHAR(64),
            entity_ref VARCHAR(512),
            predicate VARCHAR(64),
            locator TEXT,
            seq BIGINT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_search_document_kind_ref UNIQUE (kind, ref)
        )
        """
    )
    # Native full-text + fuzzy (trigram) wiring, GENERATED so it cannot drift from ``text``.
    op.execute(
        "ALTER TABLE search_document ADD COLUMN IF NOT EXISTS search_tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', coalesce(text, ''))) STORED"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_search_document_tsv ON search_document "
        "USING GIN (search_tsv)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_search_document_trgm ON search_document "
        "USING GIN (text gin_trgm_ops)"
    )
    op.create_index("ix_search_document_kind_ref", "search_document", ["kind", "ref"])
    op.create_index("ix_search_document_seq", "search_document", ["seq"])
    op.create_index("ix_search_document_entity", "search_document", ["entity_ref"])

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS projection_generation (
            projection_name VARCHAR(128) NOT NULL,
            generation INTEGER NOT NULL,
            schema_name VARCHAR(200) NOT NULL,
            state VARCHAR(24) NOT NULL,
            published_at TIMESTAMPTZ,
            grace_deadline TIMESTAMPTZ,
            checkpoint_seq BIGINT NOT NULL DEFAULT 0,
            CONSTRAINT pk_projection_generation PRIMARY KEY (projection_name, generation)
        )
        """
    )
    op.create_index("ix_projection_generation_state", "projection_generation", ["state"])


def downgrade() -> None:
    op.drop_index("ix_search_document_entity", table_name="search_document")
    op.drop_index("ix_search_document_seq", table_name="search_document")
    op.drop_index("ix_search_document_kind_ref", table_name="search_document")
    op.execute("DROP INDEX IF EXISTS ix_search_document_trgm")
    op.execute("DROP INDEX IF EXISTS ix_search_document_tsv")
    op.drop_index("ix_projection_generation_state", table_name="projection_generation")
    op.drop_table("projection_generation")
    op.drop_table("search_document")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
