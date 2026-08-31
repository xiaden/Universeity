"""Pydantic v2 request/response schemas for the versioned REST API (Phase 3).

Models mirror the existing Tier-1/Tier-0 service shapes (``QueryService``,
``SearchService``, ledger commits, job records) so the routers can round-trip
without inventing new semantics. All collections paginate with opaque cursors.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from umd.projections.question import QuestionConstraints, StructuredAnswer

# ---------------------------------------------------------------------------
# Consistency / freshness
# ---------------------------------------------------------------------------


class FreshnessMeta(BaseModel):
    projection: str
    applied_seq: int
    ledger_tail: int
    lag: int
    status: str  # fresh | transient-lag | rebuild-in-progress
    paused: bool = False
    pause_reason: str | None = None


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


class SourceIngestRequest(BaseModel):
    media_kind: str = "txt"
    work_id: str | None = None
    original_name: str | None = None
    source_id: str | None = None
    content_type: str = "text/plain"
    #: Optional inline text content (used by tests); when provided, upload is optional.
    content: str | None = None


class SourceDescriptorResponse(BaseModel):
    source_id: str
    work_id: str | None = None
    ocfl_ref: str
    sha512: str
    size_bytes: int
    media_kind: str
    original_name: str | None = None
    seq: int
    consistency_token: int


class SourceDetailResponse(BaseModel):
    source_id: str
    ocfl_ref: str
    sha512: str
    size_bytes: int
    media_kind: str
    work_id: str | None = None
    continuity_id: str | None = None
    edition_id: str | None = None


class SegmentResponse(BaseModel):
    segment_id: str
    source_id: str
    kind: str
    start: int | None = None
    end: int | None = None
    locator: str | None = None
    ref: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class SegmentListResponse(BaseModel):
    items: list[SegmentResponse]
    total: int
    next_cursor: str | None = None
    prev_cursor: str | None = None


class LocatorRangeResponse(BaseModel):
    object_id: str
    logical_name: str
    sha512: str | None = None
    size_bytes: int
    start: int
    end: int
    truncated: bool
    #: bytes base64-encoded
    data_b64: str


class EvidenceResponse(BaseModel):
    ref: str
    locator: str | None = None
    source_id: str | None = None
    segment_id: str | None = None
    predicate: str | None = None
    object_ref: str | None = None
    confidence: float | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    generated_by: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)


class EvidenceListResponse(BaseModel):
    items: list[EvidenceResponse]
    total: int
    next_cursor: str | None = None
    prev_cursor: str | None = None


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


class EntityResponse(BaseModel):
    """Canonical-entity read result: identity metadata plus exact support/provenance."""

    ref: str
    label: str
    kind: str
    predicate: str | None = None
    value: str | None = None
    # Plan S (P2-S2): canonical-identity metadata surfaced through the ENTITY read.
    # Populated only for canonical identities read from the reducer CANONICAL_IDENTITY
    # row; always None/empty for legacy CANONICAL_ENTITY fallback hits.
    canonical_type: str | None = None
    display_label: str | None = None
    aliases: list[str] = Field(default_factory=list)
    state: str | None = None
    confidence: float | None = None
    support_refs: list[str] = Field(default_factory=list)
    memberships: dict[str, Any] = Field(default_factory=dict)
    # Plan T (P2-S1 / R4/R5/R9): exact support/provenance metadata already
    # computed by ``QueryService._entity_hit`` for canonical identity hits, surfaced
    # on list, by-ref, and structured ENTITY reads. Always present (empty dicts for
    # legacy CANONICAL_ENTITY fallback hits) so the metadata contract holds.
    provenance: dict[str, Any] = Field(default_factory=dict)
    generated_by: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)


class EntityListResponse(BaseModel):
    items: list[EntityResponse]
    total: int
    next_cursor: str | None = None
    prev_cursor: str | None = None


class EntityCreateRequest(BaseModel):
    """POST /v1/entities payload (Plan T P2-S3 / R6).

    Routed through the SAME canonical authority as resolution
    (:class:`Resolver.establish`): the payload becomes an ``EntityResolved``
    ``ESTABLISH`` event carrying display label, canonical type, aliases,
    replay-derived memberships, support/evidence refs, state and authority. It
    never fabricates an SQL ``entity`` row and never mutates the predicate
    vocabulary. ``ref`` is the opaque canonical ref (Plan N Option B: a non-UUID
    ref keeps ``entity_id`` NULL on any mention rows).
    """

    ref: str = Field(min_length=1)
    display_label: str | None = Field(default=None, description="active display label")
    # Legacy alias: the pre-Plan-T create payload used ``label`` for the display
    # label. Kept for backward compatibility; ``display_label`` wins when both set.
    label: str | None = None
    canonical_type: str | None = Field(default=None, description="canonical type (e.g. character)")
    aliases: list[str] = Field(default_factory=list, description="active alias surfaces")
    memberships: dict[str, list[str]] = Field(
        default_factory=dict, description="replay-derived source/work/continuity memberships"
    )
    support_refs: list[str] = Field(default_factory=list, description="evidence/segment support")
    state: str | None = Field(default=None, description="identity state (defaults to CONFIRMED)")
    authority: str = Field(default="operator", description="operator | human")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reason: str | None = None
    actor: str | None = None


class EntityActionResponse(BaseModel):
    entity_ref: str
    action: str
    seq: int
    consistency_token: int
    detail: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


class ClaimCreateRequest(BaseModel):
    predicate_code: str
    subject_ref: str
    object_ref: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    scope: str = "GLOBAL"
    support_refs: list[str] = Field(default_factory=list)


class ClaimResponse(BaseModel):
    ref: str
    predicate: str | None = None
    subject: str | None = None
    object: str | None = None
    confidence: float | None = None
    seq: int
    consistency_token: int


class ClaimMutationRequest(BaseModel):
    cause: str | None = None
    reason: str | None = None
    object_ref: str | None = None
    predicate_code: str | None = None
    scope: str | None = None
    stage: str | None = None
    refs: list[str] = Field(default_factory=list)


class ProvenanceResponse(BaseModel):
    subject: str
    current: dict[str, Any] | None = None
    prior: dict[str, Any] | None = None
    actor: str | None = None
    change_cause: dict[str, Any] | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


class StructuredQueryRequest(BaseModel):
    kind: Literal[
        "ENTITY",
        "UTTERANCE",
        "SCENE",
        "EVIDENCE",
        "CORRESPONDENCE",
        "CONTRADICTIONS",
        "UNRESOLVED_ALIASES",
        "TRAVERSAL",
        "RELATIONSHIP_EDGES",
    ]
    ref: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    confidence_min: float | None = None
    continuity_id: str | None = None
    # Plan T (P2-S1): bounded replay-derived membership filters on ENTITY reads, merged
    # into ``filters`` by the router. They are distinct from the top-level
    # ``continuity_id`` (the source-declared continuity seam). Membership continuity on
    # an ENTITY read may also be expressed directly as ``filters.continuity_id``.
    work_id: str | None = None
    source_id: str | None = None
    temporal_from: str | None = None
    temporal_to: str | None = None
    spatial: dict[str, Any] | None = None
    result_kind: str | None = None
    max_depth: int | None = Field(default=None, ge=0, le=8)
    limit: int | None = Field(default=None, ge=1)
    offset: int | None = Field(default=None, ge=0)
    consistency_token: int | None = None


class StructuredQueryResponse(BaseModel):
    query: str
    results: list[dict[str, Any]]
    total: int
    limit: int
    offset: int
    result_kinds: list[str]
    provenance: dict[str, Any] = Field(default_factory=dict)
    bound_report: dict[str, Any] = Field(default_factory=dict)
    freshness: FreshnessMeta | None = None


class SemanticQueryRequest(BaseModel):
    question: str
    consistency_token: int | None = None
    constraints: QuestionConstraints | None = None


class SemanticQueryResponse(StructuredAnswer):
    freshness: FreshnessMeta | None = None


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class SearchRequest(BaseModel):
    query: str
    mode: Literal["exact", "fuzzy", "hybrid"] = "hybrid"
    source_id: str | None = None
    work_id: str | None = None
    continuity_id: str | None = None
    segment_id: str | None = None
    entity_ref: str | None = None
    kind: str | None = None
    language: str | None = None
    locator_prefix: str | None = None
    limit: int | None = Field(default=None, ge=1)
    offset: int | None = Field(default=None, ge=0)
    consistency_token: int | None = None


class SearchHit(BaseModel):
    ref: str
    kind: str
    text: str
    source_id: str | None = None
    segment_id: str | None = None
    entity_ref: str | None = None
    score: float
    exact_score: float | None = None
    vector_score: float | None = None
    label: str


class SearchResponse(BaseModel):
    engine: str
    vector_backend: str
    hits: list[SearchHit]
    total: int
    limit: int
    offset: int
    next_cursor: str | None = None
    prev_cursor: str | None = None
    freshness: FreshnessMeta | None = None


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


class JobResponse(BaseModel):
    id: str
    source_id: str | None = None
    dag_universe: str
    status: str
    request: dict[str, Any] = Field(default_factory=dict)
    cancelled_stages: list[str] = Field(default_factory=list)
    error: str | None = None


class JobActionResponse(BaseModel):
    job_id: str
    action: str
    targets: list[str] = Field(default_factory=list)
    pause_reason: str | None = None


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class AuditResponse(BaseModel):
    subject: str
    explanation: dict[str, Any]


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------


class HealthComponent(BaseModel):
    name: str
    status: str  # ok | degraded | down
    detail: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str  # ok | degraded
    components: list[HealthComponent]


class CapabilitiesResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    capabilities: dict[str, Any]


class VersionResponse(BaseModel):
    service: str
    api_version: str
    contract_version: str
    dag_universe: str | None = None
    schema_version: int | None = None


__all__ = [
    "FreshnessMeta",
    "SourceIngestRequest",
    "SourceDescriptorResponse",
    "SourceDetailResponse",
    "SegmentResponse",
    "SegmentListResponse",
    "LocatorRangeResponse",
    "EvidenceResponse",
    "EvidenceListResponse",
    "EntityResponse",
    "EntityListResponse",
    "EntityCreateRequest",
    "EntityActionResponse",
    "ClaimCreateRequest",
    "ClaimResponse",
    "ClaimMutationRequest",
    "ProvenanceResponse",
    "StructuredQueryRequest",
    "StructuredQueryResponse",
    "SemanticQueryRequest",
    "SemanticQueryResponse",
    "SearchRequest",
    "SearchHit",
    "SearchResponse",
    "JobResponse",
    "JobActionResponse",
    "AuditResponse",
    "HealthComponent",
    "HealthResponse",
    "CapabilitiesResponse",
    "VersionResponse",
]
