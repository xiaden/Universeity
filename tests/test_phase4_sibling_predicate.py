"""Plan S Phase 4 (P4-S1..S4): validated relationship predicates (SIBLING_OF).

Proves the Lantern Keeper sibling predicate ``SIBLING_OF`` is:

  * P4-S1  admitted ONLY through the controlled, syntax+registration-validated
           vocabulary (``register_predicate`` gate; malformed / arbitrary model
           predicate strings rejected before semantic assertion);
  * P4-S2  reconciled with both endpoints resolved through canonical
           labels/aliases, direction preserved, and only validated relationship
           events emitted (unsupported/malformed stay evidence-only);
  * P4-S3  retained across replay / correction / invalidation / scope with full
           metadata (predicate, canonical refs, confidence/state, support refs,
           generated-by, scope, fact_id) and deterministic multi-edge replay;
  * P4-S4  visible through the public query path ``relationship_edges`` after
           replay, and indexed through the search projection (edge_guard gate).

These are additive; the pre-existing strict rejection of malformed arbitrary
model predicates is preserved (never weakened).
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa
from pydantic import ValidationError

from umd.analysis.semantic import (
    GeneratedBy,
    RelationshipCandidate,
    SegmentEvidenceRef,
    SemanticAnalysisResult,
)
from umd.application.commands import SemanticCommandService
from umd.domain.models import (
    PREDICATE_VOCABULARY,
    Predicate,
    SemanticAssertion,
    is_known_predicate,
    register_predicate,
)
from umd.projections.base import ReplayDriver
from umd.projections.checkpoint import ProjectionCheckpointStore
from umd.projections.edges import ActiveSemanticEdgeProjectionBuilder
from umd.projections.query import QueryService, StructuredQuery
from umd.projections.search import SearchProjectionBuilder, SearchService
from umd.projections.tables import active_semantic_edge as _edge
from umd.reconciliation.reconciler import ReconciliationInput, SemanticReconciler
from umd.resolution.service import CanonicalEntity, ResolutionBatch
from umd.storage.postgres.ledger import SemanticLedger

pytestmark = pytest.mark.postgres

MARA = "entity:canonical:s1:mara"
ELLIS = "entity:canonical:s1:ellis"
ORIN = "entity:canonical:s1:orin"


# ---------------------------------------------------------------------------
# P4-S1 — controlled-vocabulary admission of SIBLING_OF
# ---------------------------------------------------------------------------


def test_sibling_of_is_registered_controlled_vocabulary() -> None:
    """SIBLING_OF is present in the validated vocabulary after import."""
    assert "SIBLING_OF" in PREDICATE_VOCABULARY
    assert is_known_predicate("SIBLING_OF")


def test_register_predicate_admits_well_formed_rejects_malformed() -> None:
    """The admission gate validates syntax + registration for any predicate."""
    # A well-formed, non-clashing code is admitted (open vocabulary, no migration).
    register_predicate("KINSHIP_OF", "A kinship relationship between entities.")
    try:
        assert is_known_predicate("KINSHIP_OF")
        # Malformed arbitrary model predicate strings are rejected by the gate.
        with pytest.raises(ValueError):
            register_predicate("sibling-of", "hyphen not allowed")
        with pytest.raises(ValueError):
            register_predicate("1SIBLING", "must start with a letter")
        with pytest.raises(ValueError):
            register_predicate("REL 2 @", "spaces/symbols not allowed")
    finally:
        PREDICATE_VOCABULARY.pop("KINSHIP_OF", None)


def test_predicate_and_assertion_validate_against_controlled_vocabulary() -> None:
    """Predicate / SemanticAssertion admit only registered codes."""
    assert Predicate(code="SIBLING_OF").code == "SIBLING_OF"
    with pytest.raises(ValidationError):
        Predicate(code="TRANSMUTATION_OF")  # well-formed but unregistered
    with pytest.raises(ValidationError):
        Predicate(code="sibling-of")  # malformed arbitrary string

    assert SemanticAssertion(predicate_code="SIBLING_OF").predicate_code == "SIBLING_OF"
    with pytest.raises(ValidationError):
        SemanticAssertion(predicate_code="invented_relation")


# ---------------------------------------------------------------------------
# P4-S2 — reconciler: endpoints through canonical labels, direction preserved,
# only validated predicates emitted
# ---------------------------------------------------------------------------


def _canonical_resolution() -> ResolutionBatch:
    return ResolutionBatch(
        source_id="s1",
        canonical_entities=[
            CanonicalEntity(
                ref=MARA, label="Mara", source_id="s1", confidence=0.9, state="CONFIRMED"
            ),
            CanonicalEntity(
                ref=ELLIS, label="Ellis", source_id="s1", confidence=0.9, state="CONFIRMED"
            ),
            CanonicalEntity(
                ref=ORIN, label="Orin", source_id="s1", confidence=0.9, state="CONFIRMED"
            ),
        ],
    )


def _relationship(rel_predicate: str, *, conf: float = 0.7) -> SemanticAnalysisResult:
    seg = SegmentEvidenceRef(locator="source://s/1", evidence_ref="ev:1")
    gb = GeneratedBy(
        path="provider", provider="lantern_semantic", model="lantern-qwen", config_digest="cfg@1"
    )
    return SemanticAnalysisResult(
        source_id="s1",
        generated_by=gb,
        relationships=[
            RelationshipCandidate(
                subject_ref="Mara",
                predicate=rel_predicate,
                object_ref="Ellis",
                confidence=conf,
                segment=seg,
                generated_by=gb,
            )
        ],
    )


def test_sibling_of_reconciles_endpoints_through_canonical_labels() -> None:
    """SIBLING_OF resolves subject/object to canonical refs; direction preserved."""
    events = SemanticReconciler().reconcile(
        ReconciliationInput(
            source_id="s1",
            analysis=_relationship("SIBLING_OF"),
            resolution=_canonical_resolution(),
        )
    )
    sibling = [e for e in events if e.payload.get("predicate_code") == "SIBLING_OF"]
    assert len(sibling) == 1
    p = sibling[0].payload
    assert p["subject_ref"] == MARA, "subject must resolve through the canonical label 'Mara'"
    assert p["object_ref"] == ELLIS, "object must resolve through the canonical label 'Ellis'"
    assert p["confidence"] == 0.7
    assert p["state"] == "PROBABLE"  # RelationshipCandidate default state preserved
    assert p["generated_by"]["path"] == "provider"


def test_sibling_of_malformed_and_unregistered_stay_evidence_only() -> None:
    """Malformed / unregistered arbitrary model predicates never fabricate edges."""
    seg = SegmentEvidenceRef(locator="source://s/1", evidence_ref="ev:1")
    gb = GeneratedBy(path="provider", provider="lantern_semantic", model="lantern-qwen")
    analysis = SemanticAnalysisResult(
        source_id="s1",
        generated_by=gb,
        relationships=[
            RelationshipCandidate(
                subject_ref="Mara",
                predicate="sibling-of",  # malformed arbitrary string (hyphen)
                object_ref="Ellis",
                confidence=0.7,
                segment=seg,
                generated_by=gb,
            ),
            RelationshipCandidate(
                subject_ref="Mara",
                predicate="TRANSMUTATION_OF",  # well-formed but unregistered
                object_ref="Ellis",
                confidence=0.7,
                segment=seg,
                generated_by=gb,
            ),
        ],
    )
    events = SemanticReconciler().reconcile(
        ReconciliationInput(source_id="s1", analysis=analysis, resolution=_canonical_resolution())
    )
    preds = {e.payload.get("predicate_code") for e in events}
    assert "SIBLING-OF" not in preds, "malformed predicate must stay evidence-only"
    assert "TRANSMUTATION_OF" not in preds, "unregistered predicate must stay evidence-only"


# ---------------------------------------------------------------------------
# P4-S3/S4 — active-edge replay, metadata retention, correction/invalidation,
# scope, multi-edge determinism, and the public query + search paths
# ---------------------------------------------------------------------------


def _svc(umd_db: sa.Engine) -> SemanticCommandService:
    return SemanticCommandService(SemanticLedger(umd_db))


def _sibling_hits(umd_db: sa.Engine, *, subject: str = MARA) -> list[Any]:
    page = QueryService(umd_db).structured(
        StructuredQuery(kind="RELATIONSHIP_EDGES", filters={"predicate": "SIBLING_OF"}, limit=100)
    )
    return [h for h in page.results if h.predicate == "SIBLING_OF" and h.ref == subject]


def test_sibling_of_edge_replay_query_correction_scope(umd_db: sa.Engine) -> None:
    """SIBLING_OF edge is visible via relationship_edges, survives replay with full
    metadata, and is correctly superseded by correction then invalidation."""
    svc = _svc(umd_db)
    svc.assert_semantic(
        predicate_code="SIBLING_OF",
        subject_ref=MARA,
        object_ref=ELLIS,
        confidence=0.7,
        state="PROBABLE",
        scope="CONTINUITY",
        support_refs=["ev:1", "ev:2"],
        generated_by={"path": "provider", "provider": "lantern_semantic"},
    )
    driver = ReplayDriver(umd_db, ProjectionCheckpointStore(umd_db))
    driver.run(ActiveSemanticEdgeProjectionBuilder(), wipe=True)

    # Public query path: the SIBLING_OF edge is visible with direction + metadata.
    hits = _sibling_hits(umd_db)
    assert len(hits) == 1
    h = hits[0]
    assert h.ref == MARA and h.value == ELLIS, "direction preserved through the public read"
    assert h.kind == "SOURCE_EVIDENCE", "machine assertion is source-evidence kind"
    assert h.provenance["state"] == "PROBABLE"
    assert h.provenance["scope"] == "CONTINUITY"
    assert h.data["authority"] == "machine"
    assert h.data["scope"] == "CONTINUITY"
    fact1 = h.provenance["fact_id"]

    # Edge record retains support refs + generated-by provenance (P4-S3).
    with umd_db.connect() as c:
        row = c.execute(
            sa.select(_edge.c.support_refs, _edge.c.derivation).where(_edge.c.fact_id == fact1)
        ).one()
    assert row.support_refs == ["ev:1", "ev:2"]
    assert row.derivation["generated_by"]["provider"] == "lantern_semantic"
    assert row.derivation["source_refs"] == ["ev:1", "ev:2"]

    # Deterministic wipe/replay: same fact, single active edge (idempotent).
    driver.run(ActiveSemanticEdgeProjectionBuilder(), wipe=True)
    hits2 = _sibling_hits(umd_db)
    assert len(hits2) == 1
    assert hits2[0].provenance["fact_id"] == fact1

    # Correction (USER_OVERRIDE) supersedes the machine edge, preserving direction
    # but pointing to a new object with override authority.
    svc.record_correction(
        subject_ref=MARA,
        predicate="SIBLING_OF",
        object_ref=ORIN,
        prior_ref=fact1,
        actor="tester",
        reason="correction",
    )
    driver.run(ActiveSemanticEdgeProjectionBuilder(), wipe=True)
    hits3 = _sibling_hits(umd_db)
    assert len(hits3) == 1, "superseded machine edge must not surface as active"
    assert hits3[0].value == ORIN
    assert hits3[0].kind == "INTERPRETATION", "user override is interpretation kind"
    assert hits3[0].data["authority"] == "USER_OVERRIDE"
    assert hits3[0].provenance["fact_id"] != fact1

    # Invalidation removes the edge from active reads.
    svc.invalidate(subject_ref=MARA, predicate="SIBLING_OF", cause="superseded")
    driver.run(ActiveSemanticEdgeProjectionBuilder(), wipe=True)
    assert _sibling_hits(umd_db) == []


def test_sibling_of_multi_edge_replay_is_deterministic(umd_db: sa.Engine) -> None:
    """Two simultaneous SIBLING_OF edges (different object/scope) both survive
    deterministic wipe-and-replay."""
    svc = _svc(umd_db)
    svc.assert_semantic(
        predicate_code="SIBLING_OF",
        subject_ref=MARA,
        object_ref=ELLIS,
        confidence=0.7,
        state="PROBABLE",
        scope="CONTINUITY",
        generated_by={"path": "provider", "provider": "lantern_semantic"},
    )
    svc.assert_semantic(
        predicate_code="SIBLING_OF",
        subject_ref=MARA,
        object_ref=ORIN,
        confidence=0.5,
        state="UNKNOWN",
        scope="SOURCE",
        generated_by={"path": "provider", "provider": "lantern_semantic"},
    )
    driver = ReplayDriver(umd_db, ProjectionCheckpointStore(umd_db))
    driver.run(ActiveSemanticEdgeProjectionBuilder(), wipe=True)

    def _facts() -> set[tuple[str, str, str]]:
        return {
            (h.value, h.provenance["scope"], h.provenance["state"]) for h in _sibling_hits(umd_db)
        }

    first = _facts()
    assert first == {(ELLIS, "CONTINUITY", "PROBABLE"), (ORIN, "SOURCE", "UNKNOWN")}

    driver.run(ActiveSemanticEdgeProjectionBuilder(), wipe=True)
    assert _facts() == first, "multi-edge replay must be deterministic"


def test_sibling_of_edge_indexed_through_search_projection(umd_db: sa.Engine) -> None:
    """SIBLING_OF flows into the search projection (edge_guard freshness gate)."""
    svc = _svc(umd_db)
    svc.assert_semantic(
        predicate_code="SIBLING_OF",
        subject_ref=MARA,
        object_ref=ELLIS,
        confidence=0.7,
        scope="CONTINUITY",
        generated_by={"path": "provider", "provider": "lantern_semantic"},
    )
    driver = ReplayDriver(umd_db, ProjectionCheckpointStore(umd_db))
    # Search finalize requires the edge checkpoint to be caught up first.
    driver.run(ActiveSemanticEdgeProjectionBuilder(), wipe=True)
    driver.run(SearchProjectionBuilder(), wipe=True)

    with umd_db.connect() as c:
        rows = c.execute(
            sa.text("SELECT ref, text FROM search_document WHERE ref LIKE 'edge:%'")
        ).fetchall()
    edge_docs = {str(r[0]): str(r[1]) for r in rows}
    assert edge_docs, "SIBLING_OF edge must be indexed as an edge:% search doc"
    assert ELLIS in edge_docs.values(), "edge doc text is the canonical object ref"

    page = SearchService(umd_db).exact(ELLIS)
    assert any(h.ref.startswith("edge:") for h in page.hits), (
        "SIBLING_OF edge must be retrievable through the public search path"
    )
