"""Canonical typed relational core (transactional authority in PostgreSQL).

This is the single source of truth for the structural schema that the Alembic
migration renders and that repository code reads. It implements the DD's typed
relational core: 23 typed tables with indexes and foreign keys, JSONB extension
fields, an append-only semantic-event ledger, an open predicate dictionary that
allows new predicates without a migration, and disposable Tier-0 projections.

The 23 tables: work, continuity, source, source_membership, edition, segment,
evidence, artifact, entity, entity_mention, predicate, semantic_assertion,
semantic_event, current_state, current_entity_map, alignment, stage_run, job,
job_run_audit, embedding, projection_checkpoint, quarantine, locator_rebase.

Stable IDs (UUIDv7/ULID-compatible) are an encoding decision deferred to Phase 2;
Phase 1 uses ``uuid.uuid4`` defaults for structure. The exact production ID form
is a later-phase concern — the columns are ``Uuid`` throughout.

Ownership/immutability notes enforced structurally here:
  * ``semantic_event`` is append-only; an UPDATE/DELETE blocking trigger is
    created by the migration (ledger with no in-place UPDATE).
  * ``embedding`` rows are immutable (one row per segment/model/evidence_ref).
  * ``source`` is content-addressed: ``sha512`` unique; a user filename is
    recorded only as metadata (``original_name``) and never used as a key.
  * ``projection_checkpoint`` is single-writer (unique ``projection_name``).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.sqltypes import Uuid as SAUuid

metadata = sa.MetaData()

# ---------------------------------------------------------------------------
# Typed core concepts
# ---------------------------------------------------------------------------

work = sa.Table(
    "work",
    metadata,
    sa.Column(
        "id",
        SAUuid(),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    ),
    sa.Column("title", sa.String(512), nullable=False),
    sa.Column("work_type", sa.String(64), nullable=False),
    sa.Column("metadata_", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "updated_at",
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    ),
)

continuity = sa.Table(
    "continuity",
    metadata,
    sa.Column(
        "id",
        SAUuid(),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    ),
    sa.Column(
        "work_id",
        SAUuid(),
        sa.ForeignKey("work.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    sa.Column("name", sa.String(256), nullable=False),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)

edition = sa.Table(
    "edition",
    metadata,
    sa.Column(
        "id",
        SAUuid(),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    ),
    sa.Column(
        "work_id",
        SAUuid(),
        sa.ForeignKey("work.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    sa.Column(
        "continuity_id",
        SAUuid(),
        sa.ForeignKey("continuity.id", ondelete="SET NULL"),
        nullable=True,
    ),
    sa.Column("language", sa.String(16), nullable=True),
    sa.Column(
        "kind", sa.String(32), nullable=False, index=True
    ),  # original|translation|adaptation|release
    sa.Column("label", sa.String(256), nullable=True),
    sa.Column("metadata_", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)

source = sa.Table(
    "source",
    metadata,
    sa.Column(
        "id",
        SAUuid(),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    ),
    # Content-addressed OCFL reference; sole authority for raw bytes is OCFL.
    sa.Column("ocfl_ref", sa.String(512), nullable=False, unique=True),
    # sha512 digest of the immutable bytes; content-addressed uniqueness.
    sa.Column("sha512", sa.CHAR(128), nullable=False, unique=True),
    sa.Column("size_bytes", sa.BigInteger(), nullable=False),
    sa.Column("media_kind", sa.String(64), nullable=False, index=True),
    sa.Column("format", sa.String(64), nullable=True),
    sa.Column("language", sa.String(16), nullable=True),
    # A user-provided filename recorded as *metadata only*; never a key/path.
    sa.Column("original_name", sa.String(1024), nullable=True),
    sa.Column(
        "work_id",
        SAUuid(),
        sa.ForeignKey("work.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    ),
    sa.Column(
        "continuity_id",
        SAUuid(),
        sa.ForeignKey("continuity.id", ondelete="SET NULL"),
        nullable=True,
    ),
    sa.Column(
        "edition_id", SAUuid(), sa.ForeignKey("edition.id", ondelete="SET NULL"), nullable=True
    ),
    sa.Column("descriptor", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)

source_membership = sa.Table(
    "source_membership",
    metadata,
    sa.Column(
        "id",
        SAUuid(),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    ),
    sa.Column(
        "source_id",
        SAUuid(),
        sa.ForeignKey("source.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    sa.Column(
        "work_id",
        SAUuid(),
        sa.ForeignKey("work.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    sa.Column("role", sa.String(32), nullable=False),  # primary|derivation|alias|related
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.UniqueConstraint("source_id", "work_id", "role", name="uq_source_membership_unique"),
)

# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------

segment = sa.Table(
    "segment",
    metadata,
    sa.Column(
        "id",
        SAUuid(),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    ),
    sa.Column(
        "source_id",
        SAUuid(),
        sa.ForeignKey("source.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    sa.Column(
        "parent_id",
        SAUuid(),
        sa.ForeignKey("segment.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    ),
    sa.Column("segment_type", sa.String(64), nullable=False, index=True),
    # Deterministic stable segment key from content identity + modality + structural path.
    sa.Column("deterministic_key", sa.String(512), nullable=False),
    # Canonical locator (source://...) filled by Phase 2; scaffold now.
    sa.Column("locator", sa.Text(), nullable=True),
    sa.Column("ordinal", sa.Integer(), nullable=True),
    sa.Column("seq_no", sa.Integer(), nullable=True),
    # Valid-time range for temporal query scope (open-ended; NULL = not recorded).
    # Indexes are created by migration 0005 (not declared here, so 0001's
    # metadata.create_all does not pre-create them out of migration order).
    sa.Column("start_time", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("end_time", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("metadata_", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.UniqueConstraint("source_id", "deterministic_key", name="uq_segment_deterministic"),
)


# ---------------------------------------------------------------------------
# Evidence / artifacts
# ---------------------------------------------------------------------------

artifact = sa.Table(
    "artifact",
    metadata,
    sa.Column(
        "id",
        SAUuid(),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    ),
    # Content-addressed OCFL reference for a derived artifact (bytes owned by OCFL).
    sa.Column("ocfl_ref", sa.String(512), nullable=False, unique=True),
    sa.Column("sha512", sa.CHAR(128), nullable=False),
    sa.Column("size_bytes", sa.BigInteger(), nullable=False),
    sa.Column("kind", sa.String(64), nullable=False, index=True),  # raw|derived|tool_manifest
    sa.Column(
        "source_id", SAUuid(), sa.ForeignKey("source.id", ondelete="SET NULL"), nullable=True
    ),
    sa.Column("metadata_", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)

evidence = sa.Table(
    "evidence",
    metadata,
    sa.Column(
        "id",
        SAUuid(),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    ),
    sa.Column(
        "source_id",
        SAUuid(),
        sa.ForeignKey("source.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    sa.Column(
        "segment_id",
        SAUuid(),
        sa.ForeignKey("segment.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    ),
    sa.Column("evidence_kind", sa.String(64), nullable=False, index=True),
    sa.Column("locator", sa.Text(), nullable=True),
    sa.Column("language", sa.String(16), nullable=True),
    sa.Column("track", sa.String(64), nullable=True),
    sa.Column("raw_ref", sa.String(512), nullable=True),
    sa.Column("normalized_ref", sa.String(512), nullable=True),
    # Derived-evidence bytes reference (OCFL derived object); graph never the only copy.
    sa.Column("artifact_ref", sa.String(512), nullable=True),
    sa.Column("extraction_stage", sa.String(64), nullable=True),
    sa.Column("tool_versions", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("config_digest", sa.String(128), nullable=True),
    sa.Column("confidence", sa.Float(), nullable=True),
    sa.Column("quality", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    # DB-authoritative idempotency: a re-record of identical extraction output
    # (same source + locator + kind + config digest) is a no-op, not a duplicate
    # row. ``record()`` inserts with ON CONFLICT DO NOTHING against this index.
    sa.UniqueConstraint(
        "source_id",
        "locator",
        "evidence_kind",
        "config_digest",
        name="uq_evidence_identity",
    ),
)

# ---------------------------------------------------------------------------
# Entities / mentions / predicates
# ---------------------------------------------------------------------------

entity = sa.Table(
    "entity",
    metadata,
    sa.Column(
        "id",
        SAUuid(),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    ),
    sa.Column("entity_type", sa.String(64), nullable=False, index=True),
    sa.Column("label", sa.String(512), nullable=True),
    sa.Column("metadata_", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)

entity_mention = sa.Table(
    "entity_mention",
    metadata,
    sa.Column(
        "id",
        SAUuid(),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    ),
    sa.Column(
        "entity_id",
        SAUuid(),
        sa.ForeignKey("entity.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    ),
    sa.Column(
        "source_id",
        SAUuid(),
        sa.ForeignKey("source.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    sa.Column(
        "segment_id",
        SAUuid(),
        sa.ForeignKey("segment.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    ),
    sa.Column("mention_text", sa.Text(), nullable=False),
    sa.Column("normalized_forms", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("speaker_label", sa.String(128), nullable=True),
    sa.Column("face_cluster", sa.String(128), nullable=True),
    sa.Column("metadata_", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)

# Predicate dictionary: open vocabulary — new predicates are data, not migrations.
predicate = sa.Table(
    "predicate",
    metadata,
    sa.Column("code", sa.String(64), primary_key=True),
    sa.Column("description", sa.String(512), nullable=True),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)

semantic_assertion = sa.Table(
    "semantic_assertion",
    metadata,
    sa.Column(
        "id",
        SAUuid(),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    ),
    sa.Column(
        "predicate_code",
        sa.String(64),
        sa.ForeignKey("predicate.code", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    sa.Column(
        "subject_entity_id",
        SAUuid(),
        sa.ForeignKey("entity.id", ondelete="SET NULL"),
        nullable=True,
    ),
    sa.Column("subject_ref", sa.String(512), nullable=True),
    sa.Column(
        "object_entity_id", SAUuid(), sa.ForeignKey("entity.id", ondelete="SET NULL"), nullable=True
    ),
    sa.Column("object_ref", sa.String(512), nullable=True),
    sa.Column("authority", sa.String(64), nullable=True, index=True),
    sa.Column("confidence", sa.Float(), nullable=True),
    sa.Column("state", sa.String(24), nullable=False, server_default="UNKNOWN", index=True),
    # UNKNOWN|AMBIGUOUS|CONFLICTING|PROBABLE|CONFIRMED|USER_CONFIRMED
    sa.Column(
        "continuity_id",
        SAUuid(),
        sa.ForeignKey("continuity.id", ondelete="SET NULL"),
        nullable=True,
    ),
    sa.Column("valid_time", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("support_refs", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("contradiction_refs", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("schema_ref", sa.String(512), nullable=True),
    sa.Column("derivation", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)

# ---------------------------------------------------------------------------
# Append-only semantic-event ledger (envelope per the DD)
# ---------------------------------------------------------------------------

semantic_event = sa.Table(
    "semantic_event",
    metadata,
    sa.Column("seq", sa.BigInteger(), primary_key=True, autoincrement=True),  # BIGSERIAL
    sa.Column("event_type", sa.String(64), nullable=False, index=True),
    sa.Column("event_version", sa.Integer(), nullable=False),
    sa.Column("schema_url", sa.String(256), nullable=True),
    sa.Column("tx_time", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("valid_time", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("authority", sa.String(64), nullable=True),
    sa.Column("confidence", sa.Float(), nullable=True),
    sa.Column("generated_by", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("correlation_id", SAUuid(), nullable=True, index=True),
    sa.Column(
        "causation_id",
        sa.BigInteger(),
        sa.ForeignKey("semantic_event.seq", ondelete="RESTRICT"),
        nullable=True,
    ),
    sa.Column("payload", JSONB, nullable=False),
    sa.Column("idempotency_key", SAUuid(), nullable=True, unique=True),
    sa.Column("created_by", sa.String(128), nullable=True),
)

# ---------------------------------------------------------------------------
# Tier-0 projections (disposable, replay-only; never written directly)
# ---------------------------------------------------------------------------

current_state = sa.Table(
    "current_state",
    metadata,
    sa.Column("entity_ref", sa.String(512), nullable=False),
    sa.Column("predicate", sa.String(64), nullable=False),
    sa.Column("object_ref", sa.String(512), nullable=True),
    sa.Column("confidence", sa.Float(), nullable=True),
    sa.Column("authority", sa.String(64), nullable=True),
    sa.Column("state", sa.String(24), nullable=False, server_default="UNKNOWN"),
    sa.Column("seq", sa.BigInteger(), nullable=False),  # last-applied event seq
    sa.Column(
        "updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.PrimaryKeyConstraint("entity_ref", "predicate", name="pk_current_state_tier0"),
)

current_entity_map = sa.Table(
    "current_entity_map",
    metadata,
    sa.Column(
        "entity_id", SAUuid(), sa.ForeignKey("entity.id", ondelete="CASCADE"), nullable=False
    ),
    sa.Column("alias", sa.String(512), nullable=False),
    sa.Column(
        "canonical_entity_id",
        SAUuid(),
        sa.ForeignKey("entity.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("origin_seq", sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint(
        "entity_id", "alias", "canonical_entity_id", name="pk_current_entity_map"
    ),
)

# ---------------------------------------------------------------------------
# Alignment / stage / job (operational)
# ---------------------------------------------------------------------------

alignment = sa.Table(
    "alignment",
    metadata,
    sa.Column(
        "id",
        SAUuid(),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    ),
    sa.Column("left_ref", sa.Text(), nullable=False, index=True),
    sa.Column("right_ref", sa.Text(), nullable=False, index=True),
    sa.Column("alignment_type", sa.String(64), nullable=False, index=True),
    sa.Column("method", sa.String(64), nullable=True),
    sa.Column("assumptions", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("source_events", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("confidence", sa.Float(), nullable=True),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)

stage_run = sa.Table(
    "stage_run",
    metadata,
    sa.Column(
        "id",
        SAUuid(),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    ),
    sa.Column("idempotency_key", SAUuid(), nullable=False, unique=True),
    sa.Column("job_id", sa.String(128), nullable=True, index=True),
    sa.Column("stage_name", sa.String(64), nullable=False, index=True),
    sa.Column(
        "source_id",
        SAUuid(),
        sa.ForeignKey("source.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    ),
    sa.Column(
        "segment_id", SAUuid(), sa.ForeignKey("segment.id", ondelete="SET NULL"), nullable=True
    ),
    sa.Column("status", sa.String(24), nullable=False, index=True),
    sa.Column("input_manifest", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("artifact_refs", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("config_digest", sa.String(128), nullable=True),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "updated_at",
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    ),
)

# Job aggregate: durable orchestrating record for one source decomposition run.
# Operational state only (status / cancelled stages / error) — never Tier-0.
job = sa.Table(
    "job",
    metadata,
    sa.Column(
        "id",
        sa.String(128),
        primary_key=True,
    ),
    sa.Column(
        "source_id",
        SAUuid(),
        sa.ForeignKey("source.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    ),
    sa.Column("dag_universe", sa.String(64), nullable=False),
    sa.Column("status", sa.String(24), nullable=False, index=True),
    sa.Column("request", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("cancelled_stages", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    sa.Column("error", sa.Text(), nullable=True),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "updated_at",
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    ),
)

# Job-run audit: committed as an auditable event but EXCLUDED from semantic-state
# replay (handled explicitly by projector policy, per the DD).
job_run_audit = sa.Table(
    "job_run_audit",
    metadata,
    sa.Column(
        "id",
        SAUuid(),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    ),
    sa.Column("job_id", sa.String(128), nullable=False, index=True),
    sa.Column("stage_name", sa.String(64), nullable=False),
    sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("1")),
    sa.Column(
        "action", sa.String(32), nullable=False, index=True
    ),  # start|retry|fail|complete|cancel
    sa.Column("status", sa.String(24), nullable=True),
    sa.Column("details", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)


# ---------------------------------------------------------------------------
# Embedding (append-only, immutable per evidence version/model)
# ---------------------------------------------------------------------------

# NOTE: the production vector column is a build gate (pgvector 0.8.x HNSW behind
# VectorIndex, per the DD). Phase 1 keeps the vector payload as JSONB so the
# migration runs on a bare PostgreSQL; the embedding projection phase swaps in
# the real `vector(N)` column + extension behind its own feature toggle.
embedding = sa.Table(
    "embedding",
    metadata,
    sa.Column(
        "id",
        SAUuid(),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    ),
    sa.Column(
        "segment_id",
        SAUuid(),
        sa.ForeignKey("segment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    sa.Column("model", sa.String(64), nullable=False),
    sa.Column("model_version", sa.String(64), nullable=False),
    sa.Column("evidence_ref", sa.String(512), nullable=False),
    sa.Column("sequence_no", sa.BigInteger(), nullable=False, autoincrement=True),  # append order
    sa.Column("vector_json", JSONB, nullable=True),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.UniqueConstraint("segment_id", "model", "evidence_ref", name="uq_embedding_immutable"),
    sa.CheckConstraint("sequence_no > 0", name="ck_embedding_seq_positive"),
)


# ---------------------------------------------------------------------------
# Quarantine / locator rebase (append-only operators)
# ---------------------------------------------------------------------------

quarantine = sa.Table(
    "quarantine",
    metadata,
    sa.Column(
        "id",
        SAUuid(),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    ),
    sa.Column("locator", sa.Text(), nullable=False, index=True),
    sa.Column(
        "reason", sa.String(64), nullable=False, index=True
    ),  # PATH_UNRESOLVED|PARSE_FAILURE|...
    sa.Column("stage", sa.String(64), nullable=True),
    sa.Column("refs", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)

locator_rebase = sa.Table(
    "locator_rebase",
    metadata,
    sa.Column(
        "id",
        SAUuid(),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    ),
    sa.Column("old_locator", sa.Text(), nullable=False),
    sa.Column("new_locator", sa.Text(), nullable=False),
    sa.Column("reason", sa.String(64), nullable=True),
    sa.Column("affected_refs", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Index("ix_locator_rebase_old", "old_locator"),
)


# ---------------------------------------------------------------------------
# Projection checkpoints (single-writer, disposable, replay-only)
# ---------------------------------------------------------------------------

projection_checkpoint = sa.Table(
    "projection_checkpoint",
    metadata,
    sa.Column("projection_name", sa.String(128), primary_key=True),
    sa.Column("applied_seq", sa.BigInteger(), nullable=False),
    sa.Column("checkpoint", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column(
        "updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)
