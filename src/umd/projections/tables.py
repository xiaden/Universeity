"""Private projection-store tables (Tier-1, replay-only, single-writer).

These tables are deliberately NOT part of the canonical ``umd.storage.postgres.tables``
metadata so that ``0001_initial_core``'s ``metadata.create_all`` does not create them
(as incomplete shapes) before ``0004_projections`` adds the native full-text wiring.
Instead they live here, are created by migration ``0004_projections`` (or, for
blue/green generation schemas, by :func:`ensure_search_table_in`), and are read/written
only by projection builders.

Ownership invariants (CONTRACTS §Core / §Query):
  * ``search_document`` and ``projection_generation`` are written ONLY by projection
    builders (single-writer). No API/worker path writes them.
  * ``search_document`` is disposable and rebuildable from the ledger; the full-text
    ``search_tsv`` column is a GENERATED STORED tsvector plus GIN index, added by
    :func:`add_fulltext_columns` (see the migration) so it can never drift from
    ``text``.
  * ``projection_generation`` is the blue/green registry (which generation schema is
    BUILDING / PUBLISHED / RETIRED / REAPED and when a retired schema's grace period ends).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

#: A private metadata namespace for projection tables (never created by 0001).
_proj_meta = sa.MetaData()


def search_document_in(schema: str) -> sa.Table:
    """A ``search_document`` Table definition rooted at an arbitrary schema.

    Used for the public base table (migration 0004) and for each blue/green generation
    schema (``proj_<name>_<generation>``) so the builder can apply the exact same shape
    wherever it writes.
    """
    return sa.Table(
        "search_document",
        sa.MetaData(),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ref", sa.String(512), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("source_id", sa.String(64), nullable=True),
        sa.Column("segment_id", sa.String(64), nullable=True),
        sa.Column("entity_ref", sa.String(512), nullable=True),
        sa.Column("predicate", sa.String(64), nullable=True),
        sa.Column("locator", sa.Text(), nullable=True),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column(
            "search_tsv", sa.Text(), nullable=True
        ),  # GENERATED STORED tsvector (read-only; never inserted)
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_search_document"),
        sa.UniqueConstraint("kind", "ref", name="uq_search_document_kind_ref"),
        schema=schema,
    )


#: Public (default-schema) search-document table used by the normal (non-blue/green)
#: search projector.
search_document = search_document_in("public")


def add_fulltext_columns(conn: sa.Connection, schema: str = "public") -> None:
    """Add the native generated tsvector column + full-text/fuzzy indexes.

    Idempotent (``IF NOT EXISTS`` / guarded) so it can be applied to the public base
    table by the migration and to each blue/green generation schema at build time.
    Requires the ``pg_trgm`` extension (installed by migration 0004).
    """
    table = search_document_in(schema)
    name = table.name
    q = sa.quoted_name(schema, False)
    conn.exec_driver_sql(
        f"ALTER TABLE {q}.{name} ADD COLUMN IF NOT EXISTS search_tsv tsvector "
        f"GENERATED ALWAYS AS (to_tsvector('simple', coalesce(text, ''))) STORED"
    )
    _try_create_index(conn, f"ix_{q}{name}_tsv", f"{q}.{name}", "USING GIN (search_tsv)")
    _try_create_index(conn, f"ix_{q}{name}_trgm", f"{q}.{name}", "USING GIN (text gin_trgm_ops)")
    _try_create_index(conn, f"ix_{q}{name}_kindref", f"{q}.{name}", "(kind, ref)")
    _try_create_index(conn, f"ix_{q}{name}_seq", f"{q}.{name}", "(seq)")


def ensure_search_table_created(conn: sa.Connection, schema: str = "public") -> None:
    """Create the search-document store in ``schema`` for a generation/blue-green build.

    Creates the base table WITHOUT the ``search_tsv`` column (it is a GENERATED STORED
    tsvector added by :func:`add_fulltext_columns`) so it cannot be created as plain TEXT.
    Idempotent and identical in shape to the migration's public ``search_document``.
    """
    q = sa.quoted_name(schema, False)
    conn.exec_driver_sql(
        f"""CREATE TABLE IF NOT EXISTS {q}.search_document (
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
        )"""
    )
    add_fulltext_columns(conn, schema)


def _try_create_index(conn: sa.Connection, name: str, table: str, body: str) -> None:
    # ``to_regclass`` guard keeps this idempotent if migration 0004 already ran and a
    # rebuild (blue/green) adds indexes to a freshly created copy.
    conn.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS {name} ON {table} {body}")


# ---------------------------------------------------------------------------
# Blue/green generation registry (single-writer via builders / publish manager)
# ---------------------------------------------------------------------------

projection_generation = sa.Table(
    "projection_generation",
    _proj_meta,
    sa.Column("projection_name", sa.String(128), nullable=False),
    sa.Column("generation", sa.Integer(), nullable=False),
    sa.Column("schema_name", sa.String(200), nullable=False),
    sa.Column("state", sa.String(24), nullable=False),  # BUILDING|PUBLISHED|RETIRED|REAPED
    sa.Column("published_at", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("grace_deadline", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("checkpoint_seq", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    sa.PrimaryKeyConstraint("projection_name", "generation", name="pk_projection_generation"),
    schema="public",
)


#: Active relationship-edge store (P2-S1 / rich multi-edge read side).
#: Replay-built ONLY by :class:`ActiveSemanticEdgeProjectionBuilder` (single-writer).
#: One row per content-addressed fact (``fact_id`` == ``semantic_assertion.id`` for
#: assertions); distinct facts sharing ``(subject_ref, predicate)`` with different
#: ``object_ref`` coexist as separate active edges (multi-edge). Supersession marks
#: ``active=false`` (history retained, never deleted). Created by migration 0008.
active_semantic_edge = sa.Table(
    "active_semantic_edge",
    _proj_meta,
    sa.Column("fact_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("event_type", sa.String(32), nullable=False),
    sa.Column("predicate", sa.String(64), nullable=False),
    sa.Column("subject_ref", sa.String(512), nullable=False),
    sa.Column("object_ref", sa.String(512), nullable=True),
    sa.Column("authority", sa.String(64), nullable=True),
    sa.Column("confidence", sa.Float(), nullable=True),
    sa.Column("state", sa.String(24), nullable=False, server_default=sa.text("'UNKNOWN'")),
    sa.Column("scope", sa.String(16), nullable=True),
    sa.Column(
        "support_refs",
        postgresql.JSONB(),
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    ),
    sa.Column(
        "contradiction_refs",
        postgresql.JSONB(),
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    ),
    sa.Column(
        "derivation",
        postgresql.JSONB(),
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    ),
    sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    sa.Column("superseded_by_seq", sa.BigInteger(), nullable=True),
    sa.Column("superseded_by_fact", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("ledger_seq", sa.BigInteger(), nullable=False),
    sa.Column(
        "updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.PrimaryKeyConstraint("fact_id", name="pk_active_semantic_edge"),
    schema="public",
)


#: Kind labels for search/query results (DD §API: result kind).
RESULT_KIND_SOURCE_EVIDENCE = "SOURCE_EVIDENCE"
RESULT_KIND_INTERPRETATION = "INTERPRETATION"
RESULT_KIND_CANONICAL_ENTITY = "CANONICAL_ENTITY"
RESULT_KINDS = frozenset(
    {RESULT_KIND_SOURCE_EVIDENCE, RESULT_KIND_INTERPRETATION, RESULT_KIND_CANONICAL_ENTITY}
)


__all__ = [
    "search_document",
    "search_document_in",
    "projection_generation",
    "active_semantic_edge",
    "add_fulltext_columns",
    "RESULT_KIND_SOURCE_EVIDENCE",
    "RESULT_KIND_INTERPRETATION",
    "RESULT_KIND_CANONICAL_ENTITY",
    "RESULT_KINDS",
]
