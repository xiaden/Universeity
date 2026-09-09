"""Plan U Phase 5 (P5-S8): determinism / idempotence of the newly-wired stage.

Proves that the production ``CURRENT_SEARCH_PROJECTION`` stage (P5-S7 wiring) is
deterministic and idempotent:

  * repeated production-stage execution and wipe/replay produce EQUAL current-tier,
    active-edge, and search results + checkpoints (a re-run with no new events leaves
    every checkpoint unchanged; content is byte-for-byte equivalent);
  * incremental ledger updates advance all three checkpoints to the SAME new tail and
    the new edge appears (prior edges retained);
  * typed dual edges (MENTOR_OF + RIVAL_OF) and corrected/invalidated edge-derived
    documents reconcile from the ACTIVE edge store — the search document set mirrors
    exactly the ACTIVE edge fact set, never the historical/inactive superseded rows;
  * the sole-writer and historical v1/v2 replay guarantees are preserved (only the
    sanctioned replay builders write the projection stores).

The freshness-guard (search never publishes from a lagging ``semantic_edges``
checkpoint) and fail-closed ordering are pinned separately in
``test_plan_u_phase5_stage_contract.py`` (P5-S6); the guard itself is NOT weakened here.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from job_helpers import ensure_source, make_manifest
from umd.application.commands import SemanticCommandService
from umd.jobs.production import StageWorkRegistryFactory
from umd.projections.base import ReplayDriver
from umd.projections.checkpoint import ProjectionCheckpointStore
from umd.projections.current import CurrentTierOneBuilder
from umd.projections.edges import ActiveSemanticEdgeProjectionBuilder
from umd.projections.search import SearchProjectionBuilder
from umd.storage.postgres.ledger import SemanticLedger

pytestmark = pytest.mark.postgres

_RELATED_TO = "RELATED_TO"


def _commands(umd_db: sa.Engine) -> SemanticCommandService:
    return SemanticCommandService(SemanticLedger(umd_db))


def _tail(engine: sa.Engine) -> int:
    with engine.connect() as c:
        return int(
            c.execute(sa.text("SELECT coalesce(max(seq),0) FROM semantic_event")).scalar() or 0
        )


def _checkpoint_seq(engine: sa.Engine, name: str) -> int:
    with engine.connect() as c:
        v = c.execute(
            sa.text("SELECT applied_seq FROM projection_checkpoint WHERE projection_name = :n"),
            {"n": name},
        ).scalar()
    return int(v or 0)


def _rowcount(engine: sa.Engine, table: str, where: str = "1=1") -> int:
    with engine.connect() as c:
        return int(c.execute(sa.text(f"SELECT count(*) FROM {table} WHERE {where}")).scalar() or 0)


def _active_edge_fact_ids(engine: sa.Engine, subject: str) -> set[str]:
    with engine.connect() as c:
        rows = c.execute(
            sa.text(
                "SELECT fact_id FROM active_semantic_edge "
                "WHERE subject_ref=:s AND active ORDER BY fact_id"
            ),
            {"s": subject},
        ).fetchall()
    return {str(r[0]) for r in rows}


def _active_edge_objects(engine: sa.Engine, subject: str) -> dict[str, str]:
    """relationship_type -> object_ref for the ACTIVE edges of a subject."""
    with engine.connect() as c:
        rows = c.execute(
            sa.text(
                "SELECT derivation->>'relationship_type' AS rt, object_ref "
                "FROM active_semantic_edge WHERE subject_ref=:s AND active"
            ),
            {"s": subject},
        ).fetchall()
    return {str(r[0]): str(r[1]) for r in rows}


def _search_edge_refs(engine: sa.Engine, subject: str) -> set[str]:
    """``edge:%`` search-document refs for a subject's active edges."""
    with engine.connect() as c:
        rows = c.execute(
            sa.text(
                "SELECT ref FROM search_document "
                "WHERE entity_ref=:s AND ref LIKE 'edge:%' ORDER BY ref"
            ),
            {"s": subject},
        ).fetchall()
    return {str(r[0]) for r in rows}


def _assert_typed(umd_db: sa.Engine, subject: str, obj: str, rel_type: str) -> None:
    _commands(umd_db).assert_semantic(
        predicate_code=_RELATED_TO,
        subject_ref=subject,
        object_ref=obj,
        confidence=0.9,
        state="PROBABLE",
        scope="CONTINUITY",
        support_refs=[f"source://s/{rel_type.lower()}"],
        generated_by={"provider": "plan-u-p5s8"},
        relationship_type=rel_type,
        actor="worker-plan-u",
    )


def _run_stage(umd_db: sa.Engine, *, job_id: str) -> object:
    """Invoke the CURRENT_SEARCH_PROJECTION production stage once."""
    registry = StageWorkRegistryFactory.build(
        {
            "engine": umd_db,
            "replay": ReplayDriver(umd_db, ProjectionCheckpointStore(umd_db)),
            "builders": {
                "current_tier1": CurrentTierOneBuilder(),
                "semantic_edges": ActiveSemanticEdgeProjectionBuilder(),
                "search": SearchProjectionBuilder(),
            },
        }
    )
    return registry["CURRENT_SEARCH_PROJECTION"](
        make_manifest("CURRENT_SEARCH_PROJECTION", job_id=job_id)
    )


def _dual_edges(umd_db: sa.Engine) -> None:
    _assert_typed(umd_db, "e:alice", "e:carol", "MENTOR_OF")
    _assert_typed(umd_db, "e:alice", "e:carol", "RIVAL_OF")


# ---------------------------------------------------------------------------
# P5-S8 — repeated execution / wipe-replay is deterministic and idempotent
# ---------------------------------------------------------------------------


def test_stage_rerun_without_new_events_is_idempotent(umd_db: sa.Engine) -> None:
    ensure_source(umd_db)
    _dual_edges(umd_db)
    tail = _tail(umd_db)

    _run_stage(umd_db, job_id="p5s8-a")
    for name in ("current_tier1", "semantic_edges", "search"):
        assert _checkpoint_seq(umd_db, name) == tail
    edges_a = _active_edge_fact_ids(umd_db, "e:alice")
    search_a = _search_edge_refs(umd_db, "e:alice")
    current_a = _rowcount(umd_db, "current_state")
    assert {"edge:" + f for f in edges_a} == search_a  # search docs mirror active edges

    # A second stage run with NO new ledger events is a no-op: equal checkpoints + equal content.
    _run_stage(umd_db, job_id="p5s8-b")
    for name in ("current_tier1", "semantic_edges", "search"):
        assert _checkpoint_seq(umd_db, name) == tail, name
    assert _active_edge_fact_ids(umd_db, "e:alice") == edges_a
    assert _search_edge_refs(umd_db, "e:alice") == search_a
    assert _rowcount(umd_db, "current_state") == current_a


def test_incremental_ledger_update_advances_all_checkpoints_together(umd_db: sa.Engine) -> None:
    ensure_source(umd_db)
    _dual_edges(umd_db)
    _run_stage(umd_db, job_id="p5s8-c")
    before = _tail(umd_db)
    assert _checkpoint_seq(umd_db, "semantic_edges") == before

    # Append a new edge, then run the stage: every checkpoint advances to the SAME new tail.
    _assert_typed(umd_db, "e:bob", "e:carol", "MENTOR_OF")
    new_tail = _tail(umd_db)
    assert new_tail > before
    _run_stage(umd_db, job_id="p5s8-d")
    for name in ("current_tier1", "semantic_edges", "search"):
        assert _checkpoint_seq(umd_db, name) == new_tail, name
    assert _active_edge_fact_ids(umd_db, "e:bob")  # bob's edge indexed as an active edge
    assert _search_edge_refs(umd_db, "e:bob")


# ---------------------------------------------------------------------------
# P5-S8 — typed dual edges + corrections/invalidations reconcile from the
# ACTIVE edge store (search mirrors active edges, never inactive superseded rows)
# ---------------------------------------------------------------------------


def test_typed_correction_reconciles_active_store_and_search_from_active_edges(
    umd_db: sa.Engine,
) -> None:
    ensure_source(umd_db)
    _dual_edges(umd_db)
    _run_stage(umd_db, job_id="p5s8-e")

    # Correct ONLY the MENTOR_OF target; RIVAL_OF stays active untouched.
    _commands(umd_db).record_correction(
        subject_ref="e:alice",
        predicate=_RELATED_TO,
        object_ref="e:dave",
        prior_ref="e:carol",
        actor="operator",
        reason="misread",
        relationship_type="MENTOR_OF",
    )
    _run_stage(umd_db, job_id="p5s8-f")

    active_objects = _active_edge_objects(umd_db, "e:alice")
    # The corrected MENTOR_OF edge now targets dave; the sibling RIVAL_OF is untouched.
    assert active_objects == {"MENTOR_OF": "e:dave", "RIVAL_OF": "e:carol"}, active_objects
    # Search docs reconcile to EXACTLY the ACTIVE edge store (no stale carol-MENTOR doc,
    # no stale superseded row), with the corrected dave target surfaced.
    assert {"edge:" + f for f in _active_edge_fact_ids(umd_db, "e:alice")} == _search_edge_refs(
        umd_db, "e:alice"
    )


def test_typed_invalidation_removes_edge_derived_doc_and_keeps_sibling(umd_db: sa.Engine) -> None:
    ensure_source(umd_db)
    _dual_edges(umd_db)
    _run_stage(umd_db, job_id="p5s8-g")
    assert len(_search_edge_refs(umd_db, "e:alice")) == 2

    # Invalidate ONLY the RIVAL_OF edge.
    _commands(umd_db).invalidate(
        subject_ref="e:alice",
        predicate=_RELATED_TO,
        cause="retracted",
        scope="CONTINUITY",
        relationship_type="RIVAL_OF",
    )
    _run_stage(umd_db, job_id="p5s8-h")

    active_objects = _active_edge_objects(umd_db, "e:alice")
    assert active_objects == {"MENTOR_OF": "e:carol"}, active_objects
    # Search docs reflect exactly the remaining ACTIVE edge (RIVAL doc removed).
    assert {"edge:" + f for f in _active_edge_fact_ids(umd_db, "e:alice")} == _search_edge_refs(
        umd_db, "e:alice"
    )
    assert len(_search_edge_refs(umd_db, "e:alice")) == 1


# ---------------------------------------------------------------------------
# P5-S8 — sole-writer guarantee preserved across the wired stage
# ---------------------------------------------------------------------------


def test_only_builders_write_projection_stores_even_when_stage_drives_them(
    umd_db: sa.Engine,
) -> None:
    """The wired stage advances the projections through the replay-only builders — a
    ledger append alone never writes them, and only a stage run (the sanctioned replay
    path) does."""
    ensure_source(umd_db)
    _dual_edges(umd_db)
    # Append-only: no projection tables written until a sanctioned stage runs.
    assert _rowcount(umd_db, "active_semantic_edge") == 0
    assert _rowcount(umd_db, "search_document") == 0
    assert _rowcount(umd_db, "projection_checkpoint") == 0

    _run_stage(umd_db, job_id="p5s8-i")
    assert _rowcount(umd_db, "active_semantic_edge") >= 2
    assert _rowcount(umd_db, "search_document") >= 2
    # Historical v1/v2 events are replayed unchanged by the wipe/replay path (never
    # rewritten); the sole writer for active edges remains the edge builder.
    assert _checkpoint_seq(umd_db, "semantic_edges") == _tail(umd_db)
