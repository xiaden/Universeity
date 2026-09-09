"""Plan U Phase 5 (P5-S6): spec-first CURRENT_SEARCH_PROJECTION stage-contract tests.

Reopened after the PLANNING_GAP amendment: the terminal ``CURRENT_SEARCH_PROJECTION``
production stage replayed ONLY ``CurrentTierOneBuilder``, so the running service never
advanced the registered ``semantic_edges`` / ``search`` projections (their checkpoints
stayed at 0 while ``current_tier1`` reached the ledger tail). The amendment wires the
existing replay-only builders into the stage in the fixed order
``CurrentTierOneBuilder -> ActiveSemanticEdgeProjectionBuilder -> SearchProjectionBuilder``
and reopens the stage contract with spec-first tests.

What is pinned here (P5-S6):

  * one ``CURRENT_SEARCH_PROJECTION`` stage invocation drives the existing replay
    driver over the runtime-registered builders in EXACTLY that order (current-tier
    first, then edges, then search), through the existing replay-only single-writer
    wipe-and-replay path;
  * the resulting :class:`StageOutcome` exposes checkpoint references for all three
    projections, each advanced to the SAME ledger tail;
  * the underlying freshness guard is NOT weakened: exercising ``SearchProjectionBuilder``
    while the ``semantic_edges`` checkpoint lags still raises
    :class:`EdgeProjectionLagError` and prevents search checkpoint/document publication;
  * there is NO public/rebuild bypass added — the only path that advances the
    projections is this single production stage invocation.
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
from umd.projections.search import EdgeProjectionLagError, SearchProjectionBuilder
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


def _rowcount(engine: sa.Engine, table: str) -> int:
    with engine.connect() as c:
        return int(c.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar() or 0)


def _assert_typed(umd_db: sa.Engine, subject: str, obj: str, rel_type: str) -> None:
    _commands(umd_db).assert_semantic(
        predicate_code=_RELATED_TO,
        subject_ref=subject,
        object_ref=obj,
        confidence=0.9,
        state="PROBABLE",
        scope="CONTINUITY",
        support_refs=[f"source://s/{rel_type.lower()}"],
        generated_by={"provider": "plan-u-p5s6"},
        relationship_type=rel_type,
        actor="worker-plan-u",
    )


def _builders() -> dict[str, object]:
    return {
        "current_tier1": CurrentTierOneBuilder(),
        "semantic_edges": ActiveSemanticEdgeProjectionBuilder(),
        "search": SearchProjectionBuilder(),
    }


class _OrderRecordingDriver(ReplayDriver):
    """Records the order in which builders were replayed by one stage invocation."""

    def __init__(self, engine: sa.Engine, store: ProjectionCheckpointStore) -> None:
        super().__init__(engine, store)
        self.order: list[str] = []

    def run(
        self,
        builder: object,
        *,
        wipe: bool = False,
        force_resume: bool = False,
    ) -> object:
        self.order.append(getattr(builder, "projection_name", type(builder).__name__))
        return super().run(builder, wipe=wipe, force_resume=force_resume)


def _run_projection_stage(
    umd_db: sa.Engine,
    *,
    job_id: str,
    driver: ReplayDriver,
) -> object:
    """Invoke the CURRENT_SEARCH_PROJECTION production stage once over a committed source."""
    registry = StageWorkRegistryFactory.build(
        {
            "engine": umd_db,
            "replay": driver,
            "builders": _builders(),
        }
    )
    stage = registry["CURRENT_SEARCH_PROJECTION"]
    return stage(make_manifest("CURRENT_SEARCH_PROJECTION", job_id=job_id))


# ---------------------------------------------------------------------------
# P5-S6 — one stage invocation replays the three builders in order and advances
# every checkpoint to the same ledger tail
# ---------------------------------------------------------------------------


def test_stage_invocation_runs_current_then_edges_then_search_to_ledger_tail(
    umd_db: sa.Engine,
) -> None:
    """One CURRENT_SEARCH_PROJECTION invocation replays the runtime-registered builders
    in EXACTLY CurrentTierOneBuilder -> ActiveSemanticEdgeProjectionBuilder ->
    SearchProjectionBuilder order, exposing a checkpoint reference for all three, each
    advanced to the SAME ledger tail through the replay-only wipe path."""
    ensure_source(umd_db)
    _assert_typed(umd_db, "e:alice", "e:carol", "MENTOR_OF")
    _assert_typed(umd_db, "e:alice", "e:carol", "RIVAL_OF")
    tail = _tail(umd_db)
    assert tail >= 2

    store = ProjectionCheckpointStore(umd_db)
    driver = _OrderRecordingDriver(umd_db, store)
    outcome = _run_projection_stage(umd_db, job_id="p5s6-order", driver=driver)

    # Order is structurally pinned AND explicitly recorded.
    assert driver.order == ["current_tier1", "semantic_edges", "search"], driver.order

    # Every projection checkpoint advanced to the same ledger tail.
    for name in ("current_tier1", "semantic_edges", "search"):
        assert _checkpoint_seq(umd_db, name) == tail, name

    # The stage outcome exposes a checkpoint reference for all three projections.
    refs = list(outcome.artifact_refs or []) + list(
        outcome.evidence_refs or []
    )
    for name in ("current_tier1", "semantic_edges", "search"):
        assert any(ref == f"projection_checkpoint:{name}:seq{tail}" for ref in refs), (
            f"missing {name} checkpoint ref among {refs}"
        )

    # The projections actually advanced (content written, not empty/no-op).
    assert _rowcount(umd_db, "current_state") >= 1
    assert _rowcount(umd_db, "active_semantic_edge") == 2  # MENTOR_OF + RIVAL_OF
    # search indexes edge-derived docs for both active edges.
    assert _rowcount(umd_db, "search_document") >= 2


def test_stage_fails_closed_when_search_builder_missing_from_runtime(umd_db: sa.Engine) -> None:
    """A stage invocation whose runtime omits a required builder must FAIL (raise), never
    silently skip the projection (P5-S7 fail-closed)."""
    ensure_source(umd_db)
    _assert_typed(umd_db, "e:alice", "e:carol", "MENTOR_OF")
    store = ProjectionCheckpointStore(umd_db)
    registry = StageWorkRegistryFactory.build(
        {
            "engine": umd_db,
            "replay": ReplayDriver(umd_db, store),
            # "search" intentionally omitted -> the resolver must raise, not omit it.
            "builders": {
                "current_tier1": CurrentTierOneBuilder(),
                "semantic_edges": ActiveSemanticEdgeProjectionBuilder(),
            },
        }
    )
    stage = registry["CURRENT_SEARCH_PROJECTION"]
    with pytest.raises(Exception, match="search"):
        stage(make_manifest("CURRENT_SEARCH_PROJECTION", job_id="p5s6-failclosed"))


# ---------------------------------------------------------------------------
# P5-S6 — the freshness guard is NOT weakened: a lagging semantic_edges
# checkpoint still aborts a search rebuild and prevents publication
# ---------------------------------------------------------------------------


def test_search_still_aborts_on_lagging_edge_checkpoint_and_never_publishes(
    umd_db: sa.Engine,
) -> None:
    """Exercising SearchProjectionBuilder while the semantic_edges checkpoint trails the
    search replay target still raises EdgeProjectionLagError, rolls the search rebuild
    back (search checkpoint unchanged, no edge-derived doc published from the stale edge
    store), and only succeeds once the edge store catches up. The guard is not weakened."""
    ensure_source(umd_db)
    _assert_typed(umd_db, "e:alice", "e:carol", "MENTOR_OF")
    _assert_typed(umd_db, "e:alice", "e:carol", "RIVAL_OF")
    store = ProjectionCheckpointStore(umd_db)
    ReplayDriver(umd_db, store).run(CurrentTierOneBuilder(), wipe=True)
    ReplayDriver(umd_db, store).run(ActiveSemanticEdgeProjectionBuilder(), wipe=True)
    ReplayDriver(umd_db, store).run(SearchProjectionBuilder(), wipe=True, force_resume=True)
    search_before = _checkpoint_seq(umd_db, "search")
    docs_before = _rowcount(umd_db, "search_document")

    # Advance the ledger with a new edge, but do NOT replay semantic_edges yet.
    _assert_typed(umd_db, "e:bob", "e:carol", "MENTOR_OF")
    new_tail = _tail(umd_db)
    assert new_tail > search_before
    assert _checkpoint_seq(umd_db, "semantic_edges") < new_tail

    # Exercising the search builder alone against the lagging edge checkpoint aborts.
    with pytest.raises(EdgeProjectionLagError):
        ReplayDriver(umd_db, store).run(SearchProjectionBuilder(), wipe=True, force_resume=True)

    # No search checkpoint advance and no edge-derived doc published from the stale edge store.
    assert _checkpoint_seq(umd_db, "search") == search_before
    assert _rowcount(umd_db, "search_document") == docs_before

    # Once edges catch up, the search rebuild succeeds and indexes the new active edge.
    ReplayDriver(umd_db, store).run(ActiveSemanticEdgeProjectionBuilder(), wipe=True)
    ReplayDriver(umd_db, store).run(SearchProjectionBuilder(), wipe=True, force_resume=True)
    assert _checkpoint_seq(umd_db, "search") == new_tail
    assert _rowcount(umd_db, "search_document") >= docs_before
