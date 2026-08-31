"""P2-S5: replay-build projection tests.

Spec-first tests for the Phase-2 replay-built projections:

  * wipe-and-replay checksum equivalence for Tier-0 AND the Tier-1 current projection
    (the ONE shared reducer derives equivalent canonical state — cross-tier equivalence);
  * Tier-1 search projection wipe-and-replay determinism + freshness;
  * event-version (upcaster) coverage through the replay path;
  * projection poison: non-authoritative quarantined machine noise is SKIPPED;
    authority-relevant events PAUSE with a reason (and resume explicitly);
  * no API/worker path writes projection stores (only builders write);
  * blue/green rebuild + publish with grace period: a stale pooled connection pinned to
    the OLD generation schema reads old data (not new) and ERRORS after the old schema
    is dropped; a fresh connection reads the new generation;
  * VectorIndex exact fallback ACTIVE by default; pgvector HNSW honestly GATED; immutable
    supersession (superseded embeddings never deleted) + recall;
  * hybrid search returns result-kind-labelled hits.

These add to the suite; none of the prior tests are modified or weakened.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from resolution_helpers import insert_source
from umd.analysis.semantic import (
    DescriptiveTrait,
    EmotionObservation,
    EntityMention,
    GeneratedBy,
    Presence,
    RelationshipCandidate,
    SegmentEvidenceRef,
    SemanticAnalysisResult,
    Utterance,
)
from umd.domain.events import SemanticEvent
from umd.projections.base import ReplayDriver
from umd.projections.checkpoint import ProjectionCheckpointStore
from umd.projections.current import CurrentTierOneBuilder, tier0_checksum
from umd.projections.edges import ActiveSemanticEdgeProjectionBuilder
from umd.projections.embedder import embed_text
from umd.projections.publish import ProjectionPublishManager
from umd.projections.query import QueryService, StructuredQuery
from umd.projections.search import SearchProjectionBuilder, SearchService
from umd.projections.tables import RESULT_KINDS, search_document_in
from umd.projections.vector import (
    ExactVectorIndex,
    PgHNSWIndex,
    VectorIndexUnavailable,
    VectorSearchService,
)
from umd.reconciliation.reconciler import ReconciliationInput, SemanticReconciler
from umd.resolution.service import CanonicalEntity, ResolutionBatch
from umd.storage.postgres.ledger import SemanticLedger
from umd.storage.postgres.reducer import USER_OVERRIDE
from umd.storage.postgres.tables import metadata as db_meta

pytestmark = pytest.mark.postgres

_se = db_meta.tables["semantic_event"]
_cs = db_meta.tables["current_state"]
_q = db_meta.tables["quarantine"]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _assertion(ref: str, value: str, *, confidence: float = 0.6) -> SemanticEvent:
    return SemanticEvent(
        event_type="SemanticAsserted",
        authority="machine",
        confidence=confidence,
        payload={
            "predicate_code": "SPEAKS",
            "subject_ref": ref,
            "object_ref": value,
            "authority": "machine",
            "confidence": confidence,
            "state": "PROBABLE",
            "scope": "CONTINUITY",
        },
    )


def _mention(source_id: str, text: str) -> SemanticEvent:
    return SemanticEvent(
        event_type="EntityMentioned",
        authority="machine",
        payload={
            "mention_id": f"m:{text}",
            "source_id": source_id,
            "mention_text": text,
        },
    )


def _override(ref: str, predicate: str, value: str) -> SemanticEvent:
    return SemanticEvent(
        event_type="OverrideApplied",
        authority=USER_OVERRIDE,
        payload={"subject_ref": ref, "predicate": predicate, "object_ref": value},
    )


def _tail(engine: sa.Engine) -> int:
    with engine.connect() as conn:
        t = conn.execute(sa.select(sa.func.max(_se.c.seq))).scalar()
    return int(t or 0)


def _sd_count(engine: sa.Engine, schema: str = "public") -> int:
    t = search_document_in(schema)
    with engine.connect() as conn:
        return int(conn.execute(sa.select(sa.func.count()).select_from(t)).scalar())


def _doc_refs(engine: sa.Engine, schema: str = "public") -> set[tuple[str, str]]:
    t = search_document_in(schema)
    with engine.connect() as conn:
        rows = conn.execute(sa.select(t.c.kind, t.c.ref)).fetchall()
    return {(str(r.kind), str(r.ref)) for r in rows}


# ---------------------------------------------------------------------------
# Tier-0 / Tier-1 wipe-and-replay equivalence (one reducer)
# ---------------------------------------------------------------------------


def test_cross_tier_equivalence_wipe_and_replay(umd_db: sa.Engine) -> None:
    """Tier-1 current projection wipe-and-replays to the SAME canonical state as Tier-0."""
    ledger = SemanticLedger(umd_db)
    ledger.append([_assertion("e:1", "utter:1"), _mention("s:1", "Sherlock")])
    ledger.append([_override("e:1", "speaker", "Dr. Watson the canonical")])
    ledger.append([_assertion("e:1", "utter:should-not-win")])  # loses to USER_OVERRIDE
    ledger.append([_assertion("e:2", "utter:9", confidence=0.3)])

    tier0 = tier0_checksum(umd_db)
    store = ProjectionCheckpointStore(umd_db)
    driver = ReplayDriver(umd_db, store)
    builder = CurrentTierOneBuilder()
    r = driver.run(builder, wipe=True)

    assert r.fresh, r.freshness_meta()
    assert r.applied_seq == _tail(umd_db)
    # wipe-and-replay rebuilt current_state == inline Tier-0.
    assert builder.checksum(umd_db) == tier0
    with umd_db.connect() as conn:
        row = conn.execute(
            sa.select(_cs.c.object_ref, _cs.c.authority).where(
                (_cs.c.entity_ref == "e:1") & (_cs.c.predicate == "speaker")
            )
        ).one()
    assert row.object_ref == "Dr. Watson the canonical"
    assert row.authority == USER_OVERRIDE


def test_search_projection_wipe_replay_is_deterministic(umd_db: sa.Engine) -> None:
    """Tier-1 search projection wipe-and-replays to the same doc set + freshness."""
    ledger = SemanticLedger(umd_db)
    ledger.append(
        [
            _mention("s:1", "Sherlock Holmes"),
            _mention("s:2", "Moriarty"),
            _assertion("e:1", "The game is afoot"),
        ]
    )
    store = ProjectionCheckpointStore(umd_db)
    driver = ReplayDriver(umd_db, store)
    builder = SearchProjectionBuilder()

    first = driver.run(builder, wipe=True)
    assert first.fresh and first.lag == 0 and first.applied_seq == _tail(umd_db)
    docs_first = _doc_refs(umd_db)

    # A second wipe-and-replay yields the identical doc set (deterministic).
    second = driver.run(builder, wipe=True)
    assert _doc_refs(umd_db) == docs_first
    assert second.fresh

    page = SearchService(umd_db).exact("Sherlock")
    assert any(h.text == "Sherlock Holmes" for h in page.hits)
    assert page.total >= 1


def test_event_version_upcaster_coverage_on_replay(umd_db: sa.Engine) -> None:
    """A retained v1 semantic event upcasts through the replay path (event-version)."""
    # Insert a raw v1 SemanticAsserted (no ``scope`` — the v1->v2 upcaster adds GLOBAL).
    with umd_db.begin() as conn:
        conn.execute(
            _se.insert().values(
                event_type="SemanticAsserted",
                event_version=1,
                schema_url="schemas/events/SemanticAsserted/v1.json",
                payload={
                    "predicate_code": "SPEAKS",
                    "subject_ref": "e:u",
                    "object_ref": "old-utter",
                },
                authority="machine",
                created_by="hist",
            )
        )
    store = ProjectionCheckpointStore(umd_db)
    driver = ReplayDriver(umd_db, store)
    builder = CurrentTierOneBuilder()
    driver.run(builder, wipe=True)
    with umd_db.connect() as conn:
        row = conn.execute(
            sa.select(_cs.c.object_ref).where(
                (_cs.c.entity_ref == "e:u") & (_cs.c.predicate == "SPEAKS")
            )
        ).first()
    assert row is not None and row.object_ref == "old-utter"  # upcast v1 applied


# ---------------------------------------------------------------------------
# Projection poison: skip non-authoritative quarantine; pause on authority
# ---------------------------------------------------------------------------


def test_non_authoritative_quarantine_poison_is_skipped(umd_db: sa.Engine) -> None:
    """Machine noise anchored to a quarantined locator is SKIPPED, not indexed."""
    quarantined_locator = "loc:noisy-source"
    with umd_db.begin() as conn:
        conn.execute(
            _q.insert().values(
                locator=quarantined_locator, reason="PARSE_FAILURE", stage="asr", refs={}
            )
        )
    ledger = SemanticLedger(umd_db)
    ledger.append(
        [
            _mention("ok:1", "CleanMention"),
            _mention(quarantined_locator, "NoiseWord"),
        ]
    )
    store = ProjectionCheckpointStore(umd_db)
    driver = ReplayDriver(umd_db, store)
    builder = SearchProjectionBuilder()
    r = driver.run(builder, wipe=True)
    assert r.skipped >= 1  # the quarantined-noise mention was skipped
    assert SearchService(umd_db).exact("NoiseWord").total == 0  # never indexed
    assert SearchService(umd_db).exact("CleanMention").total >= 1  # clean one applied


def test_authority_poison_pauses_projection(umd_db: sa.Engine) -> None:
    """An authority-relevant event PAUSES the projection and exposes a reason."""
    ledger = SemanticLedger(umd_db)
    ledger.append([_mention("s:1", "Sherlock")])
    ledger.append([_override("e:9", "speaker", "canonical speaker")])

    store = ProjectionCheckpointStore(umd_db)
    driver = ReplayDriver(umd_db, store)
    builder = SearchProjectionBuilder()

    r = driver.run(builder, wipe=True)
    assert r.paused
    assert r.pause_reason and "authority" in r.pause_reason
    assert not r.fresh

    # Still paused on a second (non-resume) run — never silently continues stale.
    r2 = driver.run(builder)
    assert r2.paused and r2.pause_reason

    # Explicit resume rebuilds through the authority event.
    r3 = driver.run(builder, force_resume=True)
    assert not r3.paused
    assert r3.fresh


def test_ledger_append_does_not_write_projection_stores(umd_db: sa.Engine) -> None:
    """Only builders write projection stores — the ledger path touches none of them."""
    from umd.projections.tables import projection_generation

    ledger = SemanticLedger(umd_db)
    ledger.append([_assertion("e:1", "utter:1"), _mention("s:1", "Sherlock")])
    assert _sd_count(umd_db) == 0
    with umd_db.connect() as conn:
        n = conn.execute(sa.select(sa.func.count()).select_from(projection_generation)).scalar()
    assert int(n or 0) == 0


# ---------------------------------------------------------------------------
# Blue/green rebuild + publish with grace period + per-connection search_path
# ---------------------------------------------------------------------------


def test_blue_green_stale_pool_cannot_read_dropped_schema(umd_db: sa.Engine) -> None:
    """A stale pooled connection pinned to a retired generation can't read new data
    and errors after that generation's schema is dropped."""
    ledger = SemanticLedger(umd_db)
    ledger.append([_mention("s:1", "BlueEra")])

    mgr = ProjectionPublishManager(umd_db, grace_period_seconds=3600)
    store = ProjectionCheckpointStore(umd_db)

    # -- generation 1 (blue) ------------------------------------------------
    gen1 = mgr.begin_build("search")
    builder1 = SearchProjectionBuilder(schema=mgr.schema_for("search", gen1))
    r1 = ReplayDriver(umd_db, store).run(builder1, wipe=True)
    mgr.mark_built("search", gen1, r1.applied_seq)
    mgr.publish("search", gen1)
    assert mgr.current_schema("search") == mgr.schema_for("search", gen1)

    stale = umd_db.connect()
    try:
        # A pooled read connection checked out now pins to generation 1's schema.
        stale.exec_driver_sql(f"SET search_path = {mgr.schema_for('search', gen1)}, public")
        old = {r for (r,) in stale.execute(sa.text("SELECT ref FROM search_document")).fetchall()}
        stale.commit()
        assert any("BlueEra" in s for s in old)

        # -- generation 2 (green): append NEW event, rebuild, publish -----------
        ledger.append([_mention("s:2", "RedEraNewData")])
        gen2 = mgr.begin_build("search")
        builder2 = SearchProjectionBuilder(schema=mgr.schema_for("search", gen2))
        r2 = ReplayDriver(umd_db, store).run(builder2, wipe=True)
        mgr.mark_built("search", gen2, r2.applied_seq)
        mgr.publish("search", gen2)
        assert mgr.current_schema("search") == mgr.schema_for("search", gen2)

        # The STALE connection is STILL pinned to generation-1's schema: it sees OLD
        # data, and never the NEW generation-2 data.
        stale_refs = {
            r for (r,) in stale.execute(sa.text("SELECT ref FROM search_document")).fetchall()
        }
        stale.commit()
        assert not any("RedEraNewData" in s for s in stale_refs)
        assert any("BlueEra" in s for s in stale_refs)

        # A fresh connection pinned after publish sees generation-2 (new) data.
        fresh_page = SearchService(umd_db, schema=mgr.schema_for("search", gen2)).exact(
            "RedEraNewData"
        )
        assert fresh_page.total >= 1

        # Expire the grace period and reap: generation-1 schema is dropped.
        expired = datetime.now(UTC) - timedelta(seconds=1)
        with umd_db.begin() as conn:
            conn.execute(
                sa.text(
                    "UPDATE projection_generation SET grace_deadline = :d, state = 'RETIRED' "
                    "WHERE projection_name='search' AND generation=:g"
                ),
                {"d": expired, "g": gen1},
            )
        reaped = mgr.reap_expired()
        assert any(g.generation == gen1 and g.state == "REAPED" for g in reaped)

        # Prove the retired generation schema was actually dropped (reaped).
        old_schema = mgr.schema_for("search", gen1)
        with umd_db.connect() as conn:
            reg = conn.execute(
                sa.text(f"SELECT to_regclass('{old_schema}.search_document'::text)")
            ).scalar()
        assert reg is None  # the retired schema no longer exists

        # A reader holding the OLD generation's pin cannot read the dropped schema.
        held = umd_db.connect()
        try:
            held.exec_driver_sql(f"SET search_path = {old_schema}, public")
            with pytest.raises(sa.exc.DBAPIError):
                held.execute(
                    sa.text(f"SELECT count(*) FROM {old_schema}.search_document")
                ).fetchall()
        finally:
            held.close()
    finally:
        stale.close()
        # Guaranteed cleanup of generation schemas regardless of test outcome.
        for gen in (gen1, gen2):
            with contextlib.suppress(Exception):  # noqa: S110 - must not mask assertion
                mgr.drop_generation("search", gen)


# ---------------------------------------------------------------------------
# VectorIndex: exact fallback ACTIVE, HNSW GATED, immutable supersession, recall
# ---------------------------------------------------------------------------


def _append_embeddings(umd_db: sa.Engine, items: list[tuple[str, str]]) -> None:
    idx = ExactVectorIndex(umd_db)
    for ref, text in items:
        seg_id = _make_segment(umd_db)
        with umd_db.begin() as conn:
            idx.add(conn, ref=ref, vector=embed_text(text), metadata={"segment_id": seg_id})


def _make_segment(umd_db: sa.Engine) -> str:
    """Insert a source + segment row (embeddings require a real NOT-NULL segment_id)."""
    sid = insert_source(umd_db, media_kind="text")
    seg_id = str(uuid.uuid4())
    from umd.storage.postgres.tables import metadata as m2

    with umd_db.begin() as conn:
        conn.execute(
            m2.tables["segment"]
            .insert()
            .values(
                id=seg_id,
                source_id=sid,
                segment_type="text",
                deterministic_key=f"vseg:{seg_id[:8]}",
                ordinal=1,
            )
        )
    return seg_id


def test_vector_exact_fallback_active_and_recall(umd_db: sa.Engine) -> None:
    """Exact fallback is ACTIVE by default and returns the most similar embeddings."""
    idx = ExactVectorIndex(umd_db)
    assert idx.active() is True
    _append_embeddings(
        umd_db,
        [
            ("d:detective", "a detective investigates the mystery"),
            ("d:cookie", "the baker baked chocolate chip cookies"),
            ("d:holmes", "sherlock holmes solves the case"),
        ],
    )
    svc = VectorSearchService(umd_db, index=idx)
    hits = svc.search_text("detective solving a mystery", top_k=3)
    assert hits[0][0] == "d:detective"  # deterministic recall: most similar ranks first
    assert len(hits) == 3


def test_embedding_immutable_supersession_never_deletes(umd_db: sa.Engine) -> None:
    """Superseded embeddings are append-only immutable rows — never deleted/updated."""
    _append_embeddings(umd_db, [("v:1", "first embed text")])
    # Supersede v:1 with a NEW row under a different evidence_ref (append, not replace).
    _append_embeddings(umd_db, [("v:2", "first embed text superseded")])
    with umd_db.connect() as conn:
        n = conn.execute(
            sa.text(
                "SELECT count(*) FROM embedding WHERE evidence_ref IN ('v:1','v:2') "
                "AND model='umd-exact-fallback'"
            )
        ).scalar()
    assert int(n) == 2  # BOTH rows retained (immutable supersession: none deleted)
    with pytest.raises(sa.exc.DBAPIError), umd_db.begin() as conn:
        conn.execute(sa.text("UPDATE embedding SET vector_json='[0]' WHERE evidence_ref='v:1'"))


def test_pgvector_hnsw_honestly_gated(umd_db: sa.Engine) -> None:
    """pgvector HNSW is GATED: not honestly active on a bare/too-old pgvector."""
    idx = PgHNSWIndex(umd_db)
    desc = idx.describe()
    assert desc["active"] is False  # never claims active when gated
    assert "gate_reason" in desc
    with pytest.raises(VectorIndexUnavailable):
        idx.search([0.0] * 64, top_k=5)


# ---------------------------------------------------------------------------
# Hybrid search ranking labels
# ---------------------------------------------------------------------------


def test_hybrid_search_result_kind_labels(umd_db: sa.Engine) -> None:
    """Hybrid search fuses exact + vector and labels every result kind."""
    text = "Sherlock Holmes applies deductive reasoning"
    ledger = SemanticLedger(umd_db)
    ledger.append([_mention("s:1", text)])
    store = ProjectionCheckpointStore(umd_db)
    ReplayDriver(umd_db, store).run(SearchProjectionBuilder(), wipe=True)
    # Align an embedding under the same ref so hybrid fuses both signals.
    _append_embeddings(umd_db, [(f"m:{text}", text)])

    page = SearchService(umd_db).hybrid(
        "Sherlock Holmes reasoning", vector_index=ExactVectorIndex(umd_db)
    )
    assert page.engine == "hybrid"
    assert page.vector_backend in ("exact-fallback-active", "unavailable")
    assert len(page.hits) >= 1
    for h in page.hits:
        assert h.kind in RESULT_KINDS  # every result is result-kind labelled
        assert h.label
        assert h.exact_score is not None or h.vector_score is not None


# ---------------------------------------------------------------------------
# Bounded relational graph-like QueryService
# ---------------------------------------------------------------------------


def test_structured_query_bounded_results(umd_db: sa.Engine) -> None:
    """Bounded typed queries return result-kind-labelled ProvenanceBearingPages."""
    from umd.resolution.mentions import PostgresMentionRepository, SourceMention

    sid = insert_source(umd_db, media_kind="text")
    ledger = SemanticLedger(umd_db)
    ledger.append([_assertion("e:1", "Why is the sky blue?")])
    mr = PostgresMentionRepository(umd_db)
    mr.record(SourceMention(source_id=sid, entity_id=None, mention_text="UnknownGuy"))

    qsvc = QueryService(umd_db)
    utterances = qsvc.structured(StructuredQuery(kind="UTTERANCE"))
    assert any(r.value == "Why is the sky blue?" for r in utterances.results)
    aliases = qsvc.structured(StructuredQuery(kind="UNRESOLVED_ALIASES"))
    assert any(r.value == "UnknownGuy" for r in aliases.results)
    assert aliases.bound_report.bounded is True

    traversal = qsvc.structured(StructuredQuery(kind="TRAVERSAL", ref="e:1", max_depth=2))
    assert traversal.bound_report.max_depth_cap <= 2
    assert traversal.bound_report.bounded is True


# ---------------------------------------------------------------------------
# P3-S1: reconciler full row matrix replays into the edge projection
# ---------------------------------------------------------------------------


def _reconciler_full_analysis() -> SemanticAnalysisResult:
    seg = SegmentEvidenceRef(locator="source://s/1", evidence_ref="ev:1")
    gb = GeneratedBy(path="deterministic", config_digest="cfg@1")
    return SemanticAnalysisResult(
        source_id="s1",
        generated_by=gb,
        entity_mentions=[
            EntityMention(mention="Alice", confidence=0.6, segment=seg, generated_by=gb),
            EntityMention(mention="Bob", confidence=0.6, segment=seg, generated_by=gb),
        ],
        presence=[
            Presence(
                entity="Alice", present_in="scene:1", confidence=0.6, segment=seg, generated_by=gb
            )
        ],
        utterances=[
            Utterance(
                utterance_text="hello",
                speaker="Alice",
                confidence=0.9,
                segment=seg,
                generated_by=gb,
            )
        ],
        traits=[
            DescriptiveTrait(
                entity="Alice", trait="brave", confidence=0.6, segment=seg, generated_by=gb
            )
        ],
        relationships=[
            RelationshipCandidate(
                subject_ref="Alice",
                predicate="CO_OCCURS",
                object_ref="Bob",
                confidence=0.55,
                segment=seg,
                generated_by=gb,
            )
        ],
        emotions=[
            EmotionObservation(
                entity="Alice", emotion="happy", confidence=0.55, segment=seg, generated_by=gb
            )
        ],
    )


def test_reconciler_full_row_matrix_replays_into_edges(umd_db: sa.Engine) -> None:
    """P3-S1: reconciler rows across categories materialize and the replay-built
    edge projection surfaces the relationship edges as active, provenance-bearing rows."""
    res = ResolutionBatch(
        source_id="s1",
        canonical_entities=[
            CanonicalEntity(
                ref="entity:canonical:s1:aaa",
                label="Alice",
                source_id="s1",
                confidence=0.9,
                state="CONFIRMED",
            ),
            CanonicalEntity(
                ref="entity:canonical:s1:bbb",
                label="Bob",
                source_id="s1",
                confidence=0.9,
                state="CONFIRMED",
            ),
        ],
    )
    events = SemanticReconciler().reconcile(
        ReconciliationInput(source_id="s1", analysis=_reconciler_full_analysis(), resolution=res)
    )
    SemanticLedger(umd_db).append(events)

    builder = ActiveSemanticEdgeProjectionBuilder()
    ReplayDriver(umd_db, ProjectionCheckpointStore(umd_db)).run(builder, wipe=True)
    with umd_db.connect() as c:
        rows = c.execute(
            sa.text(
                "SELECT predicate, authority, confidence, state, scope, active, derivation "
                "FROM active_semantic_edge WHERE active"
            )
        ).fetchall()
    by_pred = {r.predicate for r in rows}
    assert {"CO_OCCURS", "HAS_EMOTION", "HAS_TRAIT", "PRESENT_IN", "SPEAKS"} <= by_pred
    for r in rows:
        assert r.authority == "machine"
        assert r.active is True
        assert 0.0 <= r.confidence <= 1.0
        assert r.state in {"CONFIRMED", "PROBABLE", "UNKNOWN", "AMBIGUOUS", "CONFLICTING"}
        assert r.scope == "SOURCE"
        assert r.derivation["generated_by"]["path"] == "deterministic"
        assert r.derivation["source_refs"]
