"""P4-S1/S2: search freshness protocol + deterministic edge-doc reconciliation.

Spec-first postgres tests for the search projection's cross-projection freshness
protocol and edge-derived document reconciliation (Plan O, P4/P5):

  * P4-S2 — every incremental search finalize deterministically reconciles the whole
    ``edge:%`` document family against the ACTIVE relationship edges: superseded /
    corrected / overridden edges are deleted from search, never left searchable, and a
    stale superseded object term never turns up in a token search;
  * P4-S1 — a search finalize that reads a lagging ``semantic_edges`` checkpoint ABORTS
    (raises :class:`EdgeProjectionLagError`), rolls the transaction back so the search
    checkpoint is never advanced and no edge-derived document is written from a stale
    edge store; once edges catch up the search rebuild succeeds;
  * P4-S1 — edge-derived reads (``RELATIONSHIP_EDGES`` structured queries and
    relationship semantic questions) are gated on the ``semantic_edges`` ``edge_guard``,
    not only the scalar ``current_tier1`` ``query_guard``, so a token-bearing edge read
    503s while the edge store trails the token even when ``current_tier1`` is fresh.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from umd.application.commands import SemanticCommandService
from umd.projections.base import ReplayDriver
from umd.projections.checkpoint import ProjectionCheckpointStore
from umd.projections.current import CurrentTierOneBuilder
from umd.projections.edges import ActiveSemanticEdgeProjectionBuilder
from umd.projections.search import EdgeProjectionLagError, SearchProjectionBuilder, SearchService
from umd.storage.postgres.ledger import SemanticLedger

pytestmark = pytest.mark.postgres


def _svc(umd_db: sa.Engine) -> tuple[SemanticLedger, SemanticCommandService]:
    ledger = SemanticLedger(umd_db)
    return ledger, SemanticCommandService(ledger)


def _build(
    umd_db: sa.Engine,
    builder,
    *,
    wipe: bool = False,
    force_resume: bool = False,
):
    store = ProjectionCheckpointStore(umd_db)
    return ReplayDriver(umd_db, store).run(builder, wipe=wipe, force_resume=force_resume)


def _build_all(umd_db: sa.Engine) -> None:
    """Build every Tier-1 projection fresh (edges BEFORE search: finalize reads them)."""
    _build(umd_db, CurrentTierOneBuilder(), wipe=True)
    _build(umd_db, ActiveSemanticEdgeProjectionBuilder(), wipe=True)
    _build(umd_db, SearchProjectionBuilder(), wipe=True)


def _edge_doc_texts(umd_db: sa.Engine) -> set[str]:
    """The ``text`` of every ``edge:%`` search document (the active edge object terms)."""
    with umd_db.connect() as c:
        rows = c.execute(
            sa.text("SELECT text FROM search_document WHERE ref LIKE 'edge:%'")
        ).fetchall()
    return {r[0] for r in rows}


def _assert_doc_texts(umd_db: sa.Engine) -> set[str]:
    """The ``text`` of every ``assert:%`` search document (active utterance terms).

    P5-S1: the ``assert:%`` family now holds ONLY utterance-predicate docs rebuilt
    from the ACTIVE edge store (never the immutable assertion stream).
    """
    with umd_db.connect() as c:
        rows = c.execute(
            sa.text("SELECT text FROM search_document WHERE ref LIKE 'assert:%'")
        ).fetchall()
    return {r[0] for r in rows}


def _checkpoint_seq(umd_db: sa.Engine, name: str) -> int:
    with umd_db.connect() as c:
        v = c.execute(
            sa.text("SELECT applied_seq FROM projection_checkpoint WHERE projection_name = :n"),
            {"n": name},
        ).scalar()
    return int(v or 0)


def _tail(umd_db: sa.Engine) -> int:
    with umd_db.connect() as c:
        v = c.execute(sa.text("SELECT max(seq) FROM semantic_event")).scalar()
    return int(v or 0)


# ---------------------------------------------------------------------------
# P4-S2: incremental replay deterministically reconciles edge-derived docs
# ---------------------------------------------------------------------------


def test_incremental_replay_after_correction_reconciles_edge_docs(umd_db: sa.Engine) -> None:
    """P4-S2: a correction supersedes the machine edge; incremental replay deletes the
    superseded ``edge:%`` doc and reindexes exactly the ACTIVE edge — a stale token
    search for the superseded object term returns nothing."""
    _, svc = _svc(umd_db)
    svc.assert_semantic(
        predicate_code="HAS_EMOTION",
        subject_ref="e:hero",
        object_ref="blue-dawn",
        confidence=0.6,
    )
    _build_all(umd_db)
    assert _edge_doc_texts(umd_db) == {"blue-dawn"}
    assert SearchService(umd_db).exact("blue-dawn").total >= 1

    # A user correction supersedes the machine edge and activates an override edge.
    svc.record_correction(
        subject_ref="e:hero",
        predicate="HAS_EMOTION",
        object_ref="red-dusk",
        prior_ref="blue-dawn",
        actor="human",
        reason="correction",
    )
    # Incremental replay: edges first, then search. The correction is authority poison
    # for search, so resume it (re-reconcile THROUGH the correction) to reach finalize.
    _build(umd_db, ActiveSemanticEdgeProjectionBuilder(), wipe=False)
    _build(umd_db, SearchProjectionBuilder(), wipe=False, force_resume=True)

    # P4-S2: the superseded edge doc is gone; only the ACTIVE override edge remains.
    assert _edge_doc_texts(umd_db) == {"red-dusk"}
    assert SearchService(umd_db).exact("blue-dawn").total == 0, (
        "stale superseded edge doc remained searchable after incremental replay"
    )
    assert SearchService(umd_db).exact("red-dusk").total >= 1


def test_incremental_replay_after_override_reconciles_edge_docs(umd_db: sa.Engine) -> None:
    """P4-S2: same reconciliation via an override (no prior_ref) — the machine edge is
    superseded and its edge doc removed from search."""
    _, svc = _svc(umd_db)
    svc.assert_semantic(
        predicate_code="CO_OCCURS",
        subject_ref="e:hero",
        object_ref="e:villain",
        confidence=0.6,
    )
    _build_all(umd_db)
    assert _edge_doc_texts(umd_db) == {"e:villain"}

    svc.record_override(
        subject_ref="e:hero",
        predicate="CO_OCCURS",
        object_ref="e:sidekick",
        confidence=1.0,
        actor="human",
        reason="correction",
    )
    _build(umd_db, ActiveSemanticEdgeProjectionBuilder(), wipe=False)
    _build(umd_db, SearchProjectionBuilder(), wipe=False, force_resume=True)

    assert _edge_doc_texts(umd_db) == {"e:sidekick"}
    assert SearchService(umd_db).exact("e:villain").total == 0
    assert SearchService(umd_db).exact("e:sidekick").total >= 1


# ---------------------------------------------------------------------------
# P5-S2: utterance (SPEAKS) correction/override reconcile the assert:% family
# ---------------------------------------------------------------------------


def test_utterance_correction_reconciles_assert_docs(umd_db: sa.Engine) -> None:
    """P5-S1/S2: a SPEAKS correction must not leave the superseded utterance text
    searchable and must index the corrected value. The ``assert:%`` family is rebuilt
    from the ACTIVE edge store (the immutable assertion stream is no longer a search-doc
    source), so after an edges-first incremental replay the stale ``assert:%`` doc is gone
    and the corrected utterance is searchable. A subsequent wipe replay is identical.
    """
    _, svc = _svc(umd_db)
    svc.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:hero",
        object_ref="old-line",
        confidence=0.8,
    )
    _build_all(umd_db)
    assert _assert_doc_texts(umd_db) == {"old-line"}
    assert SearchService(umd_db).exact("old-line").total >= 1

    svc.record_correction(
        subject_ref="e:hero",
        predicate="SPEAKS",
        object_ref="corrected-line",
        prior_ref="old-line",
        actor="human",
        reason="correction",
    )
    # Edges-first incremental search replay (correction is authority poison -> resume).
    _build(umd_db, ActiveSemanticEdgeProjectionBuilder(), wipe=False)
    _build(umd_db, SearchProjectionBuilder(), wipe=False, force_resume=True)

    assert _assert_doc_texts(umd_db) == {"corrected-line"}, (
        "stale superseded utterance doc remained searchable after correction"
    )
    assert SearchService(umd_db).exact("old-line").total == 0
    assert SearchService(umd_db).exact("corrected-line").total >= 1

    # Wipe replay reconciles identically.
    _build_all(umd_db)
    assert _assert_doc_texts(umd_db) == {"corrected-line"}
    assert SearchService(umd_db).exact("old-line").total == 0
    assert SearchService(umd_db).exact("corrected-line").total >= 1


def test_utterance_override_reconciles_assert_docs(umd_db: sa.Engine) -> None:
    """P5-S1/S2: same reconciliation via an operator override (no prior_ref) — the
    superseded SPEAKS utterance is removed from search and the override value indexed.
    """
    _, svc = _svc(umd_db)
    svc.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:hero",
        object_ref="original-utter",
        confidence=0.8,
    )
    _build_all(umd_db)
    assert _assert_doc_texts(umd_db) == {"original-utter"}

    svc.record_override(
        subject_ref="e:hero",
        predicate="SPEAKS",
        object_ref="override-utter",
        confidence=1.0,
        actor="human",
        reason="override",
    )
    _build(umd_db, ActiveSemanticEdgeProjectionBuilder(), wipe=False)
    _build(umd_db, SearchProjectionBuilder(), wipe=False, force_resume=True)

    assert _assert_doc_texts(umd_db) == {"override-utter"}
    assert SearchService(umd_db).exact("original-utter").total == 0
    assert SearchService(umd_db).exact("override-utter").total >= 1

    _build_all(umd_db)
    assert _assert_doc_texts(umd_db) == {"override-utter"}
    assert SearchService(umd_db).exact("original-utter").total == 0
    assert SearchService(umd_db).exact("override-utter").total >= 1


# ---------------------------------------------------------------------------
# P4-S1: cross-projection freshness protocol (search vs semantic_edges)
# ---------------------------------------------------------------------------


def test_search_rebuild_aborts_when_edge_projection_lags(umd_db: sa.Engine) -> None:
    """P4-S1: a search finalize that reads a lagging edge checkpoint raises
    EdgeProjectionLagError, rolls back (search checkpoint not advanced, no new edge doc),
    and succeeds once the edge store catches up."""
    _, svc = _svc(umd_db)
    svc.assert_semantic(
        predicate_code="HAS_EMOTION",
        subject_ref="e:hero",
        object_ref="term-one",
        confidence=0.6,
    )
    _build_all(umd_db)
    search_before = _checkpoint_seq(umd_db, "search")
    tail_before = _tail(umd_db)

    # Advance the ledger with a new assertion, but do NOT replay the edges yet.
    svc.assert_semantic(
        predicate_code="HAS_EMOTION",
        subject_ref="e:villain",
        object_ref="term-two",
        confidence=0.6,
    )
    assert _tail(umd_db) > tail_before

    with pytest.raises(EdgeProjectionLagError):
        _build(umd_db, SearchProjectionBuilder(), wipe=False)

    # The search checkpoint must NOT have advanced and no new edge doc was written.
    assert _checkpoint_seq(umd_db, "search") == search_before
    assert "term-two" not in _edge_doc_texts(umd_db)

    # Once edges catch up, the search rebuild succeeds and indexes the new active edge.
    _build(umd_db, ActiveSemanticEdgeProjectionBuilder(), wipe=False)
    _build(umd_db, SearchProjectionBuilder(), wipe=False)
    assert _checkpoint_seq(umd_db, "search") == _checkpoint_seq(umd_db, "semantic_edges")
    assert "term-two" in _edge_doc_texts(umd_db)


def test_utterance_search_aborts_when_edge_projection_lags(umd_db: sa.Engine) -> None:
    """P5-S3: an utterance-specific lag window. With a new SPEAKS event ahead of
    ``semantic_edges``, a search finalize raises EdgeProjectionLagError, leaves the
    search checkpoint unchanged, publishes NO corrected ``assert:%`` doc, and succeeds
    with the corrected utterance doc only after the edge store catches up (retaining the
    non-utterance lag assertions above).
    """
    _, svc = _svc(umd_db)
    svc.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:hero",
        object_ref="utter-one",
        confidence=0.8,
    )
    _build_all(umd_db)
    assert _assert_doc_texts(umd_db) == {"utter-one"}
    search_before = _checkpoint_seq(umd_db, "search")
    tail_before = _tail(umd_db)

    # Advance the ledger with a new SPEAKS utterance, but do NOT replay edges yet.
    svc.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:villain",
        object_ref="utter-two",
        confidence=0.8,
    )
    assert _tail(umd_db) > tail_before

    with pytest.raises(EdgeProjectionLagError):
        _build(umd_db, SearchProjectionBuilder(), wipe=False)

    # Search checkpoint unchanged and NO corrected assert:% doc published.
    assert _checkpoint_seq(umd_db, "search") == search_before
    assert "utter-two" not in _assert_doc_texts(umd_db)

    # Once edges catch up, the search rebuild succeeds and indexes the corrected
    # utterance under assert:{fact_id}.
    _build(umd_db, ActiveSemanticEdgeProjectionBuilder(), wipe=False)
    _build(umd_db, SearchProjectionBuilder(), wipe=False)
    assert _checkpoint_seq(umd_db, "search") == _checkpoint_seq(umd_db, "semantic_edges")
    assert _assert_doc_texts(umd_db) == {"utter-one", "utter-two"}
    assert SearchService(umd_db).exact("utter-two").total >= 1
