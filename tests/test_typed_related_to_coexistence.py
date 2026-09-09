"""Plan U Phase 2 (P2-S1..S6): typed RELATED_TO identity + open syntax-gated admission.

Spec-first coverage proving that two RELATED_TO facts with the same predicate,
subject, object and scope but different relationship_type (MENTOR_OF vs RIVAL_OF)
coexist and independently correct / invalidate / override / contradict / replay /
search / query, while the previously hardcoded recognized-type set is replaced by
the bounded syntax gate ``^[A-Z][A-Z0-9_]{0,63}$`` with semantic-field provenance
and the immutable predicate registry is never mutated by payloads.

Scope mapping to the plan:
  * P2-S1  dual typed facts coexist (mirrors, active edges, query filters, search)
           + exact reruns deduplicate;
  * P2-S2  generic well-formed types promote to typed RELATED_TO; malformed /
           missing types stay evidence-only; SIBLING_OF stays independent; the
           registry is never mutated;
  * P2-S3  fact identity includes predicate/subject/object/normalized
           relationship_type/scope/continuity fields; historical v1/v2 rows replay
           unchanged (no silent rewrite);
  * P2-S4  typed correction / override / invalidation leaves the sibling edge active;
  * P2-S5  wipe/replay equality + structured filters expose both types;
  * P2-S6  focused assertion matrix across the above.
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa

from umd.analysis.semantic import (
    GeneratedBy,
    RelationshipCandidate,
    SegmentEvidenceRef,
    SemanticAnalysisResult,
)
from umd.application.commands import SemanticCommandService
from umd.domain.models import is_known_predicate
from umd.projections.base import ReplayDriver
from umd.projections.checkpoint import ProjectionCheckpointStore
from umd.projections.current import CurrentTierOneBuilder
from umd.projections.edges import ActiveSemanticEdgeProjectionBuilder
from umd.projections.query import QueryService, StructuredQuery
from umd.projections.search import SearchProjectionBuilder
from umd.reconciliation.reconciler import ReconciliationInput, SemanticReconciler
from umd.storage.postgres.ledger import SemanticLedger
from umd.storage.postgres.tables import semantic_event as semantic_event_table

pytestmark = pytest.mark.postgres

_RELATED_TO = "RELATED_TO"


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------


def _commands(umd_db: sa.Engine) -> SemanticCommandService:
    return SemanticCommandService(SemanticLedger(umd_db))


def _tail(engine: sa.Engine) -> int:
    with engine.connect() as c:
        return int(
            c.execute(sa.text("SELECT coalesce(max(seq),0) FROM semantic_event")).scalar() or 0
        )


def _build_edges(umd_db: sa.Engine, builder: ActiveSemanticEdgeProjectionBuilder) -> None:
    store = ProjectionCheckpointStore(umd_db)
    report = ReplayDriver(umd_db, store).run(builder, wipe=True)
    assert report.events_seen == _tail(umd_db)
    assert report.skipped == 0


def _assert_typed(umd_db: sa.Engine, subject: str, obj: str, rel_type: str) -> None:
    _commands(umd_db).assert_semantic(
        predicate_code=_RELATED_TO,
        subject_ref=subject,
        object_ref=obj,
        confidence=0.9,
        state="PROBABLE",
        scope="CONTINUITY",
        support_refs=[f"source://s/{rel_type.lower()}"],
        generated_by={"provider": "plan-u-spec"},
        relationship_type=rel_type,
        actor="worker-plan-u",
    )


def _active_edge_fact_ids(umd_db: sa.Engine, subject: str, predicate: str) -> set[str]:
    with umd_db.connect() as c:
        rows = c.execute(
            sa.text(
                "SELECT fact_id FROM active_semantic_edge "
                "WHERE subject_ref=:s AND predicate=:p AND active ORDER BY ledger_seq"
            ),
            {"s": subject, "p": predicate},
        ).fetchall()
    return {str(r[0]) for r in rows}


def _edge_derivations(umd_db: sa.Engine, subject: str, predicate: str) -> list[dict[str, Any]]:
    with umd_db.connect() as c:
        rows = c.execute(
            sa.text(
                "SELECT derivation FROM active_semantic_edge "
                "WHERE subject_ref=:s AND predicate=:p AND active ORDER BY ledger_seq"
            ),
            {"s": subject, "p": predicate},
        ).fetchall()
    return [dict(r[0]) for r in rows]


def _assertion_ids(umd_db: sa.Engine, subject: str, predicate: str) -> set[str]:
    with umd_db.connect() as c:
        rows = c.execute(
            sa.text("SELECT id FROM semantic_assertion WHERE subject_ref=:s AND predicate_code=:p"),
            {"s": subject, "p": predicate},
        ).fetchall()
    return {str(r[0]) for r in rows}


def _search_edge_refs(umd_db: sa.Engine, subject: str, predicate: str) -> set[str]:
    with umd_db.connect() as c:
        rows = c.execute(
            sa.text("SELECT ref FROM search_document WHERE entity_ref=:s AND predicate=:p"),
            {"s": subject, "p": predicate},
        ).fetchall()
    return {str(r[0]) for r in rows}


def _build_search(umd_db: sa.Engine) -> None:
    store = ProjectionCheckpointStore(umd_db)
    ReplayDriver(umd_db, store).run(CurrentTierOneBuilder(), wipe=True)
    ReplayDriver(umd_db, store).run(SearchProjectionBuilder(), wipe=True, force_resume=True)


# ---------------------------------------------------------------------------
# P2-S1 / P2-S6 — dual typed facts coexist; exact reruns deduplicate
# ---------------------------------------------------------------------------


def test_typed_related_to_dual_facts_coexist_in_mirror_edges_query_search(
    umd_db: sa.Engine,
) -> None:
    _assert_typed(umd_db, "e:alice", "e:carol", "MENTOR_OF")
    _assert_typed(umd_db, "e:alice", "e:carol", "RIVAL_OF")

    builder = ActiveSemanticEdgeProjectionBuilder()
    _build_edges(umd_db, builder)

    # Mirror: two DISTINCT content-addressable assertions (relationship_type is part
    # of the fact identity -> both facts materialize as separate rows, both retained).
    mirror_ids = _assertion_ids(umd_db, "e:alice", _RELATED_TO)
    assert len(mirror_ids) == 2

    # Active edges: both coexist, distinct fact_ids, distinct derivations.
    edge_ids = _active_edge_fact_ids(umd_db, "e:alice", _RELATED_TO)
    assert edge_ids == mirror_ids  # content-addressable identity reuse across mirror + edge
    edge_types = {
        str(d.get("relationship_type")) for d in _edge_derivations(umd_db, "e:alice", _RELATED_TO)
    }
    assert edge_types == {"MENTOR_OF", "RIVAL_OF"}

    # Query: structured filters isolate each type independently and no-filter returns both.
    q = QueryService(umd_db)
    mentor = q.relationship_edges(
        StructuredQuery(kind="RELATIONSHIP_EDGES", filters={"relationship_type": "MENTOR_OF"})
    )
    rival = q.relationship_edges(
        StructuredQuery(kind="RELATIONSHIP_EDGES", filters={"relationship_type": "RIVAL_OF"})
    )
    both = q.relationship_edges(
        StructuredQuery(kind="RELATIONSHIP_EDGES", filters={"subject": "e:alice"})
    )
    assert len(mentor.results) == 1
    assert mentor.results[0].data.get("relationship_type") == "MENTOR_OF"
    assert mentor.results[0].value == "e:carol"
    assert len(rival.results) == 1
    assert rival.results[0].data.get("relationship_type") == "RIVAL_OF"
    assert {h.data.get("relationship_type") for h in both.results} == {"MENTOR_OF", "RIVAL_OF"}

    # Search: both edge documents retained (distinct fact_id refs).
    _build_search(umd_db)
    refs = _search_edge_refs(umd_db, "e:alice", _RELATED_TO)
    assert len(refs) == 2
    assert all(ref.startswith("edge:") for ref in refs)


def test_typed_related_to_rerun_deduplicates(umd_db: sa.Engine) -> None:
    _assert_typed(umd_db, "e:alice", "e:carol", "MENTOR_OF")
    _assert_typed(umd_db, "e:alice", "e:carol", "MENTOR_OF")  # exact rerun

    with umd_db.connect() as c:
        ev_count = int(c.execute(sa.text("SELECT count(*) FROM semantic_event")).scalar() or 0)
        mir_count = int(
            c.execute(
                sa.text("SELECT count(*) FROM semantic_assertion WHERE predicate_code=:p"),
                {"p": _RELATED_TO},
            ).scalar()
            or 0
        )
    assert ev_count == 2  # append-only ledger: both assertions recorded
    assert mir_count == 1  # mirror is idempotent over the SAME fact identity

    _build_edges(umd_db, ActiveSemanticEdgeProjectionBuilder())
    assert _active_edge_fact_ids(umd_db, "e:alice", _RELATED_TO) == _assertion_ids(
        umd_db, "e:alice", _RELATED_TO
    )


# ---------------------------------------------------------------------------
# P2-S2 — open syntax-gated admission replaces the hardcoded recognized set
# ---------------------------------------------------------------------------


def _rel_input(relationships: list[RelationshipCandidate]) -> ReconciliationInput:
    gb = GeneratedBy(path="deterministic", config_digest="cfg@plan-u")
    return ReconciliationInput(
        source_id="s1",
        analysis=SemanticAnalysisResult(
            source_id="s1", generated_by=gb, relationships=relationships
        ),
        generated_by={"path": "deterministic", "config_digest": "cfg@plan-u"},
    )


def _rel(predicate: str, relationship_type: str | None = None) -> RelationshipCandidate:
    seg = SegmentEvidenceRef(locator="source://s/rel/1", evidence_ref="ev:rel:1")
    return RelationshipCandidate(
        subject_ref="e:alice",
        predicate=predicate,
        object_ref="e:carol",
        confidence=0.9,
        segment=seg,
        relationship_type=relationship_type,
        generated_by=GeneratedBy(path="deterministic", config_digest="cfg@plan-u"),
    )


def _typed_events(relationships: list[RelationshipCandidate]) -> list[dict[str, Any]]:
    return [
        e.payload
        for e in SemanticReconciler().reconcile(_rel_input(relationships))
        if e.payload["predicate_code"] == _RELATED_TO
    ]


def test_reconciler_wellformed_types_become_typed_related_to() -> None:
    # The five generic data-driven types from the plan (plus MENTOR_OF/RIVAL_OF pair).
    types = ["MENTOR_OF", "RIVAL_OF", "PARENT_OF", "MARRIED_TO", "COMMANDS"]
    events = _typed_events([_rel(t) for t in types])
    assert len(events) == len(types)
    assert {e["relationship_type"] for e in events} == set(types)
    # Same subject/object surface resolve to ONE deterministic ref for all types.
    assert len({e["object_ref"] for e in events}) == 1
    assert len({e["subject_ref"] for e in events}) == 1


def test_reconciler_wellformed_unregistered_predicate_becomes_typed_related_to() -> None:
    # QUX_LINK is well-formed but unregistered: under the syntax gate it is promoted
    # to a typed RELATED_TO (its own predicate as the relationship type), never
    # invented as a registered predicate_code.
    events = _typed_events([_rel("QUX_LINK")])
    assert len(events) == 1
    assert events[0]["predicate_code"] == _RELATED_TO
    assert events[0]["relationship_type"] == "QUX_LINK"


def test_reconciler_malformed_or_missing_type_stays_evidence_only() -> None:
    # Malformed relationship_type on RELATED_TO -> evidence-only (no assertion).
    assert _typed_events([_rel("RELATED_TO", relationship_type="has space")]) == []
    assert _typed_events([_rel("RELATED_TO", relationship_type="mentor-of")]) == []
    # Missing relationship_type on RELATED_TO -> evidence-only.
    assert _typed_events([_rel("RELATED_TO")]) == []
    # Malformed predicate -> evidence-only.
    assert _typed_events([_rel("MENTOR-OF")]) == []


def test_reconciler_related_to_requires_valid_type() -> None:
    events = SemanticReconciler().reconcile(_rel_input([_rel("RELATED_TO")]))
    assert all(e.payload["predicate_code"] != _RELATED_TO for e in events)


def test_reconciler_sibling_of_independent_of_generic_fallback() -> None:
    events = SemanticReconciler().reconcile(_rel_input([_rel("SIBLING_OF")]))
    siblings = [e for e in events if e.payload["predicate_code"] == "SIBLING_OF"]
    assert len(siblings) == 1
    assert siblings[0].payload["relationship_type"] is None
    # A registered sibling attempting to subtype itself (conflicting type) is malformed.
    assert _typed_events([_rel("SIBLING_OF", relationship_type="MENTOR_OF")]) == []
    siblings_bad = SemanticReconciler().reconcile(
        _rel_input([_rel("SIBLING_OF", relationship_type="MENTOR_OF")])
    )
    assert all(e.payload["predicate_code"] != "SIBLING_OF" for e in siblings_bad)


def test_reconciler_registry_never_mutated_by_payload() -> None:
    types = ["MENTOR_OF", "RIVAL_OF", "PARENT_OF", "MARRIED_TO", "COMMANDS", "QUX_LINK"]
    before = {t: is_known_predicate(t) for t in types}
    _typed_events([_rel(t) for t in types])
    after = {t: is_known_predicate(t) for t in types}
    assert after == before
    assert all(not is_known_predicate(t) for t in types)  # none became registered
    assert is_known_predicate(_RELATED_TO) and is_known_predicate("SIBLING_OF")


# ---------------------------------------------------------------------------
# P2-S3 — fact identity includes relationship_type; historical rows preserved
# ---------------------------------------------------------------------------


def test_fact_identity_includes_relationship_type_and_scope(umd_db: sa.Engine) -> None:
    """Two facts that differ ONLY in relationship_type (same predicate/subject/object/
    scope) must be distinct content-addressable facts — never one overwriting the
    other — and a scope difference must also separate facts."""
    _assert_typed(umd_db, "e:alice", "e:carol", "MENTOR_OF")
    _assert_typed(umd_db, "e:alice", "e:carol", "RIVAL_OF")
    _build_edges(umd_db, ActiveSemanticEdgeProjectionBuilder())

    assert len(_assertion_ids(umd_db, "e:alice", _RELATED_TO)) == 2
    assert len(_active_edge_fact_ids(umd_db, "e:alice", _RELATED_TO)) == 2

    # A fact with the SAME type but a different scope is a distinct identity.
    _commands(umd_db).assert_semantic(
        predicate_code=_RELATED_TO,
        subject_ref="e:alice",
        object_ref="e:carol",
        confidence=0.9,
        state="PROBABLE",
        scope="SOURCE",  # different scope from CONTINUITY used by _assert_typed
        support_refs=["source://s/mentor/scope"],
        generated_by={"provider": "plan-u-spec"},
        relationship_type="MENTOR_OF",
        actor="worker-plan-u",
    )
    _build_edges(umd_db, ActiveSemanticEdgeProjectionBuilder())
    assert len(_assertion_ids(umd_db, "e:alice", _RELATED_TO)) == 3
    assert len(_active_edge_fact_ids(umd_db, "e:alice", _RELATED_TO)) == 3


def test_historical_v1_v2_assertion_replays_without_rewrite(umd_db: sa.Engine) -> None:
    """Retained v1 (no scope) and v2 (scope, no relationship_type) SemanticAsserted
    rows replay deterministically through the upcasters with relationship_type=None,
    and re-running does not rewrite or duplicate them."""
    # Insert raw v1 (pre-scope) and v2 (scope, pre-relationship_type) SemanticAsserted
    # rows directly into the append-only ledger, exactly as they would exist if they
    # were committed before the upcasters shipped. Replay must upcast deterministically
    # (v1->v3 adds scope=GLOBAL + relationship_type=None; v2->v3 adds
    # relationship_type=None) WITHOUT rewriting the historical rows.
    v1_payload = {
        "predicate_code": "SPEAKS",
        "subject_ref": "e:hist",
        "object_ref": "utter:9",
        "authority": "asr",
        "confidence": 0.6,
        "state": "PROBABLE",
    }
    v2_payload = {
        "predicate_code": "SPEAKS",
        "subject_ref": "e:hist",
        "object_ref": "utter:10",
        "authority": "asr",
        "confidence": 0.5,
        "state": "PROBABLE",
        "scope": "CONTINUITY",
    }
    # INSERT raw v1 and v2 SemanticAsserted rows directly (bypassing prepare()'s
    # append-time upcast) so the replay path sees their original event versions.
    with umd_db.begin() as c:
        c.execute(
            sa.insert(semantic_event_table).values(
                [
                    {
                        "event_type": "SemanticAsserted",
                        "event_version": 1,
                        "authority": "asr",
                        "confidence": 0.6,
                        "payload": v1_payload,
                    },
                    {
                        "event_type": "SemanticAsserted",
                        "event_version": 2,
                        "authority": "asr",
                        "confidence": 0.5,
                        "payload": v2_payload,
                    },
                ]
            )
        )
    # Historical rows keep their ORIGINAL event_version (never rewritten by replay).
    with umd_db.connect() as c:
        rows = c.execute(
            sa.text(
                "SELECT event_version, payload->>'relationship_type' AS rt, "
                "payload->>'scope' AS scope FROM semantic_event ORDER BY seq"
            )
        ).fetchall()
    assert [(r[0], r[1]) for r in rows] == [(1, None), (2, None)]
    assert [r[2] for r in rows] == [None, "CONTINUITY"]  # v1 has no scope; v2 keeps its own

    builder = ActiveSemanticEdgeProjectionBuilder()
    _build_edges(umd_db, builder)
    derivs = _edge_derivations(umd_db, "e:hist", "SPEAKS")
    assert len(derivs) == 2
    # v1/v2 upcast to relationship_type=None (no typed identity invented for history).
    assert all(d.get("relationship_type") is None for d in derivs)

    # Wipe-and-replay yields the identical deterministic fact set (no drift, no rewrite).
    first = _active_edge_fact_ids(umd_db, "e:hist", "SPEAKS")
    _build_edges(umd_db, builder)
    second = _active_edge_fact_ids(umd_db, "e:hist", "SPEAKS")
    assert first == second
    with umd_db.connect() as c:
        still_two = int(
            c.execute(
                sa.text("SELECT count(*) FROM semantic_event WHERE event_version IN (1,2)")
            ).scalar()
            or 0
        )
    assert still_two == 2  # historical rows never rewritten


def test_wipe_replay_equality_typed(umd_db: sa.Engine) -> None:
    _assert_typed(umd_db, "e:alice", "e:carol", "MENTOR_OF")
    _assert_typed(umd_db, "e:alice", "e:carol", "RIVAL_OF")
    builder = ActiveSemanticEdgeProjectionBuilder()
    _build_edges(umd_db, builder)
    first = _active_edge_fact_ids(umd_db, "e:alice", _RELATED_TO)
    _build_edges(umd_db, builder)
    second = _active_edge_fact_ids(umd_db, "e:alice", _RELATED_TO)
    assert first == second == _assertion_ids(umd_db, "e:alice", _RELATED_TO)


# ---------------------------------------------------------------------------
# P2-S4 — typed correction / override / invalidation leaves the sibling active
# ---------------------------------------------------------------------------


def test_typed_override_leaves_sibling_active(umd_db: sa.Engine) -> None:
    _assert_typed(umd_db, "e:alice", "e:carol", "MENTOR_OF")
    _assert_typed(umd_db, "e:alice", "e:carol", "RIVAL_OF")
    _build_edges(umd_db, ActiveSemanticEdgeProjectionBuilder())

    _commands(umd_db).record_override(
        subject_ref="e:alice",
        predicate=_RELATED_TO,
        object_ref="e:carol",
        actor="operator",
        evidence=["manual"],
        reason="explicit",
        relationship_type="MENTOR_OF",
    )
    _build_edges(umd_db, ActiveSemanticEdgeProjectionBuilder())

    with umd_db.connect() as c:
        rows = c.execute(
            sa.text(
                "SELECT derivation->>'relationship_type' AS rt, authority, active "
                "FROM active_semantic_edge WHERE subject_ref='e:alice' AND predicate=:p "
                "ORDER BY ledger_seq"
            ),
            {"p": _RELATED_TO},
        ).fetchall()
    by_rt: dict[str, tuple[str, bool]] = {str(r[0]): (str(r[1]), bool(r[2])) for r in rows}
    # MENTOR_OF superseded by the user override; RIVAL_OF still ACTIVE machine edge.
    assert by_rt["MENTOR_OF"] == ("USER_OVERRIDE", True)  # override edge active
    assert by_rt["RIVAL_OF"] == ("machine", True)  # sibling untouched


def test_typed_invalidation_leaves_sibling_active(umd_db: sa.Engine) -> None:
    _assert_typed(umd_db, "e:alice", "e:carol", "MENTOR_OF")
    _assert_typed(umd_db, "e:alice", "e:carol", "RIVAL_OF")
    _build_edges(umd_db, ActiveSemanticEdgeProjectionBuilder())

    _commands(umd_db).invalidate(
        subject_ref="e:alice",
        predicate=_RELATED_TO,
        cause="retracted",
        scope="CONTINUITY",
        relationship_type="RIVAL_OF",
    )
    _build_edges(umd_db, ActiveSemanticEdgeProjectionBuilder())

    with umd_db.connect() as c:
        rows = c.execute(
            sa.text(
                "SELECT derivation->>'relationship_type' AS rt, active "
                "FROM active_semantic_edge WHERE subject_ref='e:alice' AND predicate=:p "
                "ORDER BY ledger_seq"
            ),
            {"p": _RELATED_TO},
        ).fetchall()
    by_rt = {str(r[0]): bool(r[1]) for r in rows}
    assert by_rt["RIVAL_OF"] is False  # invalidated
    assert by_rt["MENTOR_OF"] is True  # sibling left active


def test_typed_correction_leaves_sibling_active(umd_db: sa.Engine) -> None:
    _assert_typed(umd_db, "e:alice", "e:carol", "MENTOR_OF")
    _assert_typed(umd_db, "e:alice", "e:carol", "RIVAL_OF")
    _build_edges(umd_db, ActiveSemanticEdgeProjectionBuilder())

    _commands(umd_db).record_correction(
        subject_ref="e:alice",
        predicate=_RELATED_TO,
        object_ref="e:dave",  # corrected target for the MENTOR_OF edge only
        prior_ref="e:carol",
        actor="operator",
        reason="misread",
        relationship_type="MENTOR_OF",
    )
    _build_edges(umd_db, ActiveSemanticEdgeProjectionBuilder())

    with umd_db.connect() as c:
        rows = c.execute(
            sa.text(
                "SELECT derivation->>'relationship_type' AS rt, object_ref, active "
                "FROM active_semantic_edge WHERE subject_ref='e:alice' AND predicate=:p "
                "ORDER BY ledger_seq"
            ),
            {"p": _RELATED_TO},
        ).fetchall()
    by_rt = {str(r[0]): (str(r[1]), bool(r[2])) for r in rows}
    assert by_rt["MENTOR_OF"] == ("e:dave", True)  # corrected value active
    assert by_rt["RIVAL_OF"] == ("e:carol", True)  # sibling untouched


def test_typed_contradiction_marks_only_targeted_type(umd_db: sa.Engine) -> None:
    _assert_typed(umd_db, "e:alice", "e:carol", "MENTOR_OF")
    _assert_typed(umd_db, "e:alice", "e:carol", "RIVAL_OF")
    _build_edges(umd_db, ActiveSemanticEdgeProjectionBuilder())

    _commands(umd_db).record_contradiction(
        subject_ref="e:alice",
        predicate=_RELATED_TO,
        contradicting_ref="e:carol",
        refs=["evidence:x"],
        reason="denied",
        relationship_type="MENTOR_OF",
    )
    _build_edges(umd_db, ActiveSemanticEdgeProjectionBuilder())

    with umd_db.connect() as c:
        rows = c.execute(
            sa.text(
                "SELECT derivation->>'relationship_type' AS rt, state "
                "FROM active_semantic_edge WHERE subject_ref='e:alice' AND predicate=:p "
                "ORDER BY ledger_seq"
            ),
            {"p": _RELATED_TO},
        ).fetchall()
    by_rt = {str(r[0]): str(r[1]) for r in rows}
    assert by_rt["MENTOR_OF"] == "CONFLICTING"
    assert by_rt["RIVAL_OF"] == "PROBABLE"  # sibling untouched


# ---------------------------------------------------------------------------
# P2-S5 / P2-S6 — structured filters expose both types + provenance
# ---------------------------------------------------------------------------


def test_structured_filters_expose_both_types_and_provenance(umd_db: sa.Engine) -> None:
    _assert_typed(umd_db, "e:alice", "e:carol", "MENTOR_OF")
    _assert_typed(umd_db, "e:alice", "e:carol", "RIVAL_OF")
    _build_edges(umd_db, ActiveSemanticEdgeProjectionBuilder())

    page = QueryService(umd_db).relationship_edges(
        StructuredQuery(kind="RELATIONSHIP_EDGES", filters={"subject": "e:alice"})
    )
    assert page.total == 2
    seen: dict[str, dict[str, Any]] = {}
    for h in page.results:
        assert h.predicate == _RELATED_TO
        assert h.value == "e:carol"
        assert h.capabilities.get("edge") is True
        assert "relationship_type" in h.capabilities
        assert h.data.get("relationship_type") in {"MENTOR_OF", "RIVAL_OF"}
        assert h.provenance.get("fact_id")  # complete provenance (fact_id/state/scope/seq)
        assert h.provenance.get("state") in {"PROBABLE", "CONFIRMED"}
        assert h.provenance.get("scope") == "CONTINUITY"
        seen[str(h.data.get("relationship_type"))] = h.provenance
    assert set(seen) == {"MENTOR_OF", "RIVAL_OF"}
    assert seen["MENTOR_OF"]["fact_id"] != seen["RIVAL_OF"]["fact_id"]
