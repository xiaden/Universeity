"""Active relationship-edge projection store (Phase O, P2-S1).

Adds ``active_semantic_edge`` — the replay-built, single-writer active multi-edge read
side. Each row is one content-addressed fact (``fact_id`` == ``semantic_assertion.id``
for ``SemanticAsserted`` events), retaining confidence, authority, state, support /
contradiction refs, generated-by metadata, scope, source/segment refs, active/superseded
status, and the ledger sequence that last touched it.

The table is written ONLY by :class:`ActiveSemanticEdgeProjectionBuilder` (via
:class:`ReplayDriver`); no API/worker path writes it. Supersession (overrides,
corrections, invalidations) flips ``active`` to ``false`` and records
``superseded_by_seq`` — historical assertions are retained, never deleted.

Additive and idempotent (``IF NOT EXISTS``) so ``upgrade head`` is a no-op on a
re-upgrade; Alembic records the revision after the first successful apply.

Revision ID: 0008_active_semantic_edge
Revises: 0007_stage_run_evidence_refs
Create Date: 2026-08-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_active_semantic_edge"
down_revision: str | None = "0007_stage_run_evidence_refs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES = (
    "ix_active_semantic_edge_subject",
    "ix_active_semantic_edge_predicate",
    "ix_active_semantic_edge_active",
    "ix_active_semantic_edge_scope",
    "ix_active_semantic_edge_state",
    "ix_active_semantic_edge_subject_pred",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS active_semantic_edge (
            fact_id UUID,
            event_type VARCHAR(32) NOT NULL,
            predicate VARCHAR(64) NOT NULL,
            subject_ref VARCHAR(512) NOT NULL,
            object_ref VARCHAR(512),
            authority VARCHAR(64),
            confidence DOUBLE PRECISION,
            state VARCHAR(24) NOT NULL DEFAULT 'UNKNOWN',
            scope VARCHAR(16),
            support_refs JSONB NOT NULL DEFAULT '{}'::jsonb,
            contradiction_refs JSONB NOT NULL DEFAULT '{}'::jsonb,
            derivation JSONB NOT NULL DEFAULT '{}'::jsonb,
            active BOOLEAN NOT NULL DEFAULT true,
            superseded_by_seq BIGINT,
            superseded_by_fact UUID,
            ledger_seq BIGINT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_active_semantic_edge PRIMARY KEY (fact_id)
        )
        """
    )
    # subject/predicate/active is the primary multi-edge read index.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_active_semantic_edge_subject_pred "
        "ON active_semantic_edge (subject_ref, predicate, active)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_active_semantic_edge_subject "
        "ON active_semantic_edge (subject_ref)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_active_semantic_edge_predicate "
        "ON active_semantic_edge (predicate)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_active_semantic_edge_active ON active_semantic_edge (active)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_active_semantic_edge_scope ON active_semantic_edge (scope)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_active_semantic_edge_state ON active_semantic_edge (state)"
    )


def downgrade() -> None:
    for index in _INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {index}")
    op.drop_table("active_semantic_edge")
