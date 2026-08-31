"""Projections: disposable, replay-only single-writer Tier-1 builders (Phase 2).

Ownership contract (CONTRACTS §Core / DD §Tier-1):
  * builders replay the immutable semantic ledger from checkpoints; they are the ONLY
    writers to their projection stores, and no API/worker path writes projection tables;
  * every Tier-1 projection derives the same canonical state as Tier-0 from the ONE
    shared :class:`CurrentStateReducer` (wipe-and-replay equivalence);
  * blue/green publish is the only schema-swap path (grace period + per-connection
    ``search_path``);
  * exact/full-text search uses native PostgreSQL ``tsvector``/``pg_trgm``; vectors are
    append-only immutable rows behind a ``VectorIndex`` whose exact fallback is active by
    default and whose pgvector HNSW backend is honestly gated;
  * v1 graph-like queries are bounded typed relational traversal (no arbitrary depth).
"""

from umd.projections.base import BuildReport, ReplayDriver
from umd.projections.checkpoint import (
    ProjectionCheckpoint,
    ProjectionCheckpointStore,
)
from umd.projections.current import CurrentTierOneBuilder, tier0_checksum
from umd.projections.edges import EDGE_PROJECTION_NAME, ActiveSemanticEdgeProjectionBuilder
from umd.projections.embedder import embed_text
from umd.projections.poison import PoisonDecision, PoisonOutcome, classify
from umd.projections.publish import ProjectionGeneration, ProjectionPublishManager
from umd.projections.query import (
    BoundedReport,
    ProvenanceBearingPage,
    QueryResultHit,
    QueryService,
    StructuredQuery,
)
from umd.projections.search import (
    KindTaggedSearchHit,
    KindTaggedSearchPage,
    SearchFilters,
    SearchProjectionBuilder,
    SearchService,
)
from umd.projections.vector import (
    EmbeddingProjectionBuilder,
    ExactVectorIndex,
    PgHNSWIndex,
    VectorIndex,
    VectorIndexUnavailable,
    VectorSearchService,
)

__all__ = [
    "BuildReport",
    "ReplayDriver",
    "ProjectionCheckpoint",
    "ProjectionCheckpointStore",
    "CurrentTierOneBuilder",
    "tier0_checksum",
    "ActiveSemanticEdgeProjectionBuilder",
    "EDGE_PROJECTION_NAME",
    "embed_text",
    "PoisonDecision",
    "PoisonOutcome",
    "classify",
    "ProjectionGeneration",
    "ProjectionPublishManager",
    "BoundedReport",
    "ProvenanceBearingPage",
    "QueryResultHit",
    "QueryService",
    "StructuredQuery",
    "KindTaggedSearchHit",
    "KindTaggedSearchPage",
    "SearchFilters",
    "SearchProjectionBuilder",
    "SearchService",
    "EmbeddingProjectionBuilder",
    "ExactVectorIndex",
    "PgHNSWIndex",
    "VectorIndex",
    "VectorIndexUnavailable",
    "VectorSearchService",
]
