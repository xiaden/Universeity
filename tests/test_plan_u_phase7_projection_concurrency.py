"""Plan U Phase 7 (Amendment 3): concurrent CURRENT_SEARCH_PROJECTION reliability.

Hosted run ``34403280352`` failed two public-boundary jobs because many independent
Hatchet jobs ran the terminal ``CURRENT_SEARCH_PROJECTION`` stage CONCURRENTLY against
one shared PostgreSQL database. The stage replays the three global projections in the
fixed order ``current_tier1 -> semantic_edges -> search`` as three SEPARATE
wipe-and-replay transactions. When another concurrent job commits new ledger events in
the window between a job's ``semantic_edges`` pass and its ``search`` pass, the search
replay target (``driver.applied_seq``) advances past the committed ``semantic_edges``
checkpoint. ``SearchProjectionBuilder``'s freshness guard then correctly raises
``EdgeProjectionLagError`` (observed hosted: 97<100, 102<103, 107<108, 354<362, 392<393)
and the stage fails after bounded executor retries — an AVOIDABLE concurrency race, not
stale data. This test targets that race ONLY; it does not touch the independent stale-edge
guard tests (which must remain green) because the guard itself is the freshness invariant.

What is pinned here (P7-S1 spec-first regression, RED on current production code):

  * TWO concurrent ``CURRENT_SEARCH_PROJECTION`` stage invocations run against the SAME
    persisted PostgreSQL database with OVERLAPPING replay windows and deterministic
    barriers (a test-injected driver blocks each pass just before its ``search`` replay
    until a coordinating thread has advanced the ledger — simulating events committed by
    a concurrent job between the pass's edge replay and its search replay). No timing luck.
  * The fixed builder order current-tier -> semantic-edges -> search is preserved for every
    concurrent invocation (mirrors the recording-driver technique from
    ``test_plan_u_phase5_stage_contract.py``).
  * On the FIXED code (P7-S2) the concurrent stage calls complete WITHOUT an avoidable
    ``EdgeProjectionLagError``, all three checkpoints converge to the observed ledger tail,
    active-edge/search contents are deterministic, and no partial search publication occurs
    (search only advances in step with ``semantic_edges`` to the same tail).
  * On the CURRENT code the concurrency-race test FAILS because the uncoordinated search
    pass raises ``EdgeProjectionLagError`` (search replay target > committed
    ``semantic_edges`` checkpoint) — proving the test captures the defect rather than
    passing vacuously.

The independent stale-edge guard (search against a semantic_edges checkpoint left behind
on purpose, expecting ``EdgeProjectionLagError``) stays in
``test_plan_u_phase5_stage_contract.py`` / ``test_search_edge_reconciliation.py`` and is
untouched and green. No production file is modified here.
"""

from __future__ import annotations

import threading
import traceback

import pytest
import sqlalchemy as sa

from job_helpers import ensure_source, make_manifest
from umd.application.commands import SemanticCommandService
from umd.jobs.production import _CURRENT_SEARCH_MAX_PASS_ATTEMPTS, StageWorkRegistryFactory
from umd.projections.base import ReplayDriver
from umd.projections.checkpoint import ProjectionCheckpoint, ProjectionCheckpointStore
from umd.projections.current import CurrentTierOneBuilder
from umd.projections.edges import ActiveSemanticEdgeProjectionBuilder
from umd.projections.search import EdgeProjectionLagError, SearchProjectionBuilder
from umd.storage.postgres.ledger import SemanticLedger

pytestmark = pytest.mark.postgres

_FIXED_ORDER = ["current_tier1", "semantic_edges", "search"]
_RELATED_TO = "RELATED_TO"

#: Absolute lower bound on how long a coordinated worker may be parked at a barrier
#: before we treat it as a hang and fail loudly (never block indefinitely).
_BARRIER_TIMEOUT_S = 60.0


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


def _active_edge_fact_ids(engine: sa.Engine) -> set[str]:
    with engine.connect() as c:
        rows = c.execute(
            sa.text("SELECT fact_id FROM active_semantic_edge WHERE active ORDER BY fact_id")
        ).fetchall()
    return {str(r[0]) for r in rows}


def _search_edge_refs(engine: sa.Engine) -> set[str]:
    with engine.connect() as c:
        rows = c.execute(
            sa.text("SELECT ref FROM search_document WHERE ref LIKE 'edge:%' ORDER BY ref")
        ).fetchall()
    return {str(r[0]) for r in rows}


def _assert_typed(umd_db: sa.Engine, subject: str, obj: str, rel_type: str, marker: str) -> None:
    """Append one typed RELATED_TO edge event (the ledger authority) to the shared DB."""
    _commands(umd_db).assert_semantic(
        predicate_code=_RELATED_TO,
        subject_ref=subject,
        object_ref=obj,
        confidence=0.9,
        state="PROBABLE",
        scope="CONTINUITY",
        support_refs=[f"source://s/{rel_type.lower()}-{marker}"],
        generated_by={"provider": "plan-u-p7s1"},
        relationship_type=rel_type,
        actor="worker-plan-u",
    )


def _builders() -> dict[str, object]:
    return {
        "current_tier1": CurrentTierOneBuilder(),
        "semantic_edges": ActiveSemanticEdgeProjectionBuilder(),
        "search": SearchProjectionBuilder(),
    }


class _StagePassDriver(ReplayDriver):
    """ReplayDriver that records replay order and can hold a pass at a deterministic barrier.

    Mirrors ``_OrderRecordingDriver`` from ``test_plan_u_phase5_stage_contract.py``: every
    ``run`` records the builder's ``projection_name`` in ``order``. In addition it supports a
    concurrency barrier for the ``search`` replay (the seam where the avoidable race bites):

      * after its own ``semantic_edges`` wipe-and-replay COMMITS, ``edges_done`` is set
        (lets the coordinator know this pass reached a stable edge checkpoint); and
      * the ``search`` replay does not START until ``search_gate`` is set — letting the
        coordinator advance the ledger (a concurrent job's committed events) after the edge
        checkpoint but before the search replay reads its (larger) replay target.

    The barrier is test-side wiring injected through the runtime ``replay`` seam (the same
    seam ``StageWorkRegistryFactory`` already uses); no production code is modified.
    """

    def __init__(
        self,
        engine: sa.Engine,
        store: ProjectionCheckpointStore,
        *,
        edges_done: threading.Event | None = None,
        search_gate: threading.Event | None = None,
    ) -> None:
        super().__init__(engine, store)
        self.order: list[str] = []
        self._edges_done = edges_done
        self._search_gate = search_gate

    def run(
        self,
        builder: object,
        *,
        wipe: bool = False,
        force_resume: bool = False,
    ) -> object:
        name = getattr(builder, "projection_name", type(builder).__name__)
        self.order.append(name)
        if name == "semantic_edges" and self._edges_done is not None:
            report = super().run(builder, wipe=wipe, force_resume=force_resume)
            self._edges_done.set()
            return report
        if (
            name == "search"
            and self._search_gate is not None
            and not self._search_gate.wait(timeout=_BARRIER_TIMEOUT_S)
        ):
            raise AssertionError(
                "concurrency barrier timed out before the coordinator released the "
                "search replay; the concurrent stage pass did not reach the race window"
            )
        return super().run(builder, wipe=wipe, force_resume=force_resume)


def _run_stage_with_driver(umd_db: sa.Engine, *, job_id: str, driver: ReplayDriver) -> object:
    """Invoke the CURRENT_SEARCH_PROJECTION production stage once over a committed source."""
    registry = StageWorkRegistryFactory.build(
        {
            "engine": umd_db,
            "replay": driver,
            "builders": _builders(),
        }
    )
    return registry["CURRENT_SEARCH_PROJECTION"](
        make_manifest("CURRENT_SEARCH_PROJECTION", job_id=job_id)
    )


def _spawn(
    umd_db: sa.Engine, job_id: str, driver: ReplayDriver
) -> tuple[threading.Thread, dict[str, object]]:
    """Run one stage invocation on a worker thread, capturing outcome/exception + traceback."""
    captured: dict[str, object] = {}

    def _target() -> None:
        try:
            captured["outcome"] = _run_stage_with_driver(umd_db, job_id=job_id, driver=driver)
            captured["order"] = list(getattr(driver, "order", []))
        except BaseException as exc:  # noqa: BLE001 - record ANY failure incl. the race
            captured["exception"] = exc
            captured["traceback"] = traceback.format_exc()

    thread = threading.Thread(target=_target, name=f"stage-{job_id}", daemon=True)
    return thread, captured


def _join(thread: threading.Thread) -> None:
    thread.join(timeout=_BARRIER_TIMEOUT_S)
    assert not thread.is_alive(), "concurrent stage invocation hung (worker did not finish)"


# ---------------------------------------------------------------------------
# P7-S1 — ordinary concurrent passes preserve the fixed order, stay lag-free over a
# stable ledger, and converge deterministically (GREEN on current code)
# ---------------------------------------------------------------------------
def test_concurrent_projection_stage_passes_preserve_order_and_converge(umd_db: sa.Engine) -> None:
    """Two concurrent CURRENT_SEARCH_PROJECTION invocations over a STABLE ledger both
    complete without an avoidable EdgeProjectionLagError, replay in the exact fixed order
    current-tier -> semantic-edges -> search, and leave all three checkpoints converged to
    the observed tail with deterministic active-edge/search content."""
    ensure_source(umd_db)
    _assert_typed(umd_db, "e:alice", "e:carol", "MENTOR_OF", marker="base1")
    _assert_typed(umd_db, "e:alice", "e:carol", "RIVAL_OF", marker="base2")
    tail = _tail(umd_db)
    assert tail >= 2

    store = ProjectionCheckpointStore(umd_db)
    thread_a, cap_a = _spawn(umd_db, "p7-green-a", _StagePassDriver(umd_db, store))
    thread_b, cap_b = _spawn(umd_db, "p7-green-b", _StagePassDriver(umd_db, store))
    thread_a.start()
    thread_b.start()
    _join(thread_a)
    _join(thread_b)

    # No concurrent invocation manufactured an avoidable EdgeProjectionLagError.
    assert "exception" not in cap_a, "invocation A failed:\n" + str(cap_a.get("traceback", ""))
    assert "exception" not in cap_b, "invocation B failed:\n" + str(cap_b.get("traceback", ""))
    assert cap_a["outcome"] is not None and cap_b["outcome"] is not None

    # The fixed current-tier -> semantic-edges -> search order is preserved per invocation.
    assert cap_a["order"] == _FIXED_ORDER, cap_a["order"]
    assert cap_b["order"] == _FIXED_ORDER, cap_b["order"]

    # All three checkpoints converge to the SAME observed ledger tail.
    for name in ("current_tier1", "semantic_edges", "search"):
        assert _checkpoint_seq(umd_db, name) == tail, name

    # Active-edge / search contents are deterministic regardless of run interleaving.
    assert _rowcount(umd_db, "active_semantic_edge") == 2
    active = _active_edge_fact_ids(umd_db)
    assert len(active) == 2
    search_refs = _search_edge_refs(umd_db)
    # Every active edge is surfaced as an edge:% search document (no partial publication).
    assert search_refs == {f"edge:{fid}" for fid in active}


# ---------------------------------------------------------------------------
# P7-S1 — the AVOIDABLE concurrent replay race (RED on current code)
# ---------------------------------------------------------------------------
def test_concurrent_projection_stage_does_not_fail_on_avoidable_replay_race(
    umd_db: sa.Engine,
) -> None:
    """Two concurrent CURRENT_SEARCH_PROJECTION invocations whose replay windows overlap a
    ledger that ADVANCES (concurrent job commits) between their ``semantic_edges`` pass and
    their ``search`` pass must COMPLETE (coordinate / bounded-retry) without an avoidable
    ``EdgeProjectionLagError``, converge all three checkpoints to the final tail, and never
    publish a partial search checkpoint from a lagging edge store.

    RED on current production code: each uncoordinated search pass replays to the new
    (larger) ledger tail while the committed ``semantic_edges`` checkpoint is still the old
    tail, so ``SearchProjectionBuilder._index_active_edges`` raises ``EdgeProjectionLagError``
    and the stage call fails. P7-S2 arbitrates / bounded-retries the pass so it succeeds.
    """
    ensure_source(umd_db)
    # Base active edges both concurrent passes observe before the ledger advances.
    _assert_typed(umd_db, "e:alice", "e:carol", "MENTOR_OF", marker="base1")
    base_tail = _tail(umd_db)
    assert base_tail >= 1

    edges_done_a = threading.Event()
    edges_done_b = threading.Event()
    search_gate = threading.Event()  # released only after the coordinator advances the ledger

    store = ProjectionCheckpointStore(umd_db)
    thread_a, cap_a = _spawn(
        umd_db,
        "p7-race-a",
        _StagePassDriver(umd_db, store, edges_done=edges_done_a, search_gate=search_gate),
    )
    thread_b, cap_b = _spawn(
        umd_db,
        "p7-race-b",
        _StagePassDriver(umd_db, store, edges_done=edges_done_b, search_gate=search_gate),
    )

    # Both invocations share the same persisted DB and start concurrently. Their replay
    # windows overlap: each runs its tier1 + semantic_edges wipe-and-replay against the
    # base ledger, then is held at the deterministic barrier just before its search replay.
    thread_a.start()
    thread_b.start()

    # Wait until BOTH invocations have committed their semantic_edges pass (both edge
    # checkpoints are at base_tail) and are parked before their search replay.
    got_a = edges_done_a.wait(timeout=_BARRIER_TIMEOUT_S)
    got_b = edges_done_b.wait(timeout=_BARRIER_TIMEOUT_S)
    assert got_a and got_b, "both concurrent passes must reach the semantic_edges barrier"
    assert _checkpoint_seq(umd_db, "semantic_edges") == base_tail

    # A concurrent job commits NEW active-edge events in the window between the concurrent
    # passes' edge replay and their search replay — the exact hosted race. The search replay
    # target is now strictly ahead of the committed semantic_edges checkpoint.
    _assert_typed(umd_db, "e:bob", "e:carol", "MENTOR_OF", marker="grow1")
    _assert_typed(umd_db, "e:bob", "e:dana", "RIVAL_OF", marker="grow2")
    final_tail = _tail(umd_db)
    assert final_tail > base_tail
    assert _checkpoint_seq(umd_db, "semantic_edges") == base_tail < final_tail

    # Release BOTH concurrent search replays. On the FIXED code each pass coordinates /
    # bounded-retries so semantic_edges catches up to final_tail before search publishes.
    search_gate.set()
    _join(thread_a)
    _join(thread_b)

    # --- Post-fix contract (RED on current code) ---
    # No concurrent invocation failed with the AVOIDABLE EdgeProjectionLagError.
    failures = []
    for label, cap in (("A", cap_a), ("B", cap_b)):
        if "exception" in cap:
            failures.append(f"invocation {label} raised {cap['exception']!r}:\n{cap['traceback']}")
    assert not failures, (
        "concurrent CURRENT_SEARCH_PROJECTION pass raised an AVOIDABLE "
        "EdgeProjectionLagError (the search replay target outran the committed "
        "semantic_edges checkpoint only because another concurrent pass committed events "
        "in the overlap window):\n" + "\n".join(failures)
    )
    assert cap_a["outcome"] is not None and cap_b["outcome"] is not None

    # The fixed order is preserved for every successful concurrent invocation.
    assert cap_a["order"] == _FIXED_ORDER, cap_a["order"]
    assert cap_b["order"] == _FIXED_ORDER, cap_b["order"]

    # All three checkpoints converge to the SAME observed ledger tail (no partial search
    # publication — search never advanced past / ahead of semantic_edges).
    for name in ("current_tier1", "semantic_edges", "search"):
        assert _checkpoint_seq(umd_db, name) == final_tail, name

    # Content is deterministic: every ACTIVE edge (base + grown) is surfaced, none partial.
    assert _rowcount(umd_db, "active_semantic_edge") == 3  # MENTOR_OF + RIVAL_OF + MENTOR_OF
    active = _active_edge_fact_ids(umd_db)
    search_refs = _search_edge_refs(umd_db)
    assert search_refs == {f"edge:{fid}" for fid in active}


def _ledger_seqs(engine: sa.Engine) -> list[int]:
    """The ordered seq of every semantic_event row (append-only ledger audit)."""
    with engine.connect() as c:
        rows = c.execute(sa.text("SELECT seq FROM semantic_event ORDER BY seq")).fetchall()
    return [int(r[0]) for r in rows]


def _make_appender(umd_db: sa.Engine):
    """Return a callable appending one distinct new active-edge event per call.

    Models a concurrent writer committing a fresh active edge between a pass's
    ``semantic_edges`` rebuild and its ``search`` replay (the hosted race). Each call
    appends to the append-only ledger only — never to any projection table.
    """
    counter = {"n": 0}

    def _append() -> None:
        counter["n"] += 1
        i = counter["n"]
        _assert_typed(umd_db, f"e:grow{i}", "e:carol", "MENTOR_OF", marker=f"grow{i}")

    return _append


class _PersistentLagDriver(ReplayDriver):
    """ReplayDriver that forces the freshness violation to RECUR on every bounded-retry
    attempt, so the whole-pass bounded retry (P7-S2) must exhaust and fail honestly.

    After each ``semantic_edges`` wipe-and-replay commits, a concurrent writer (modelled
    here serially, with no thread timing) appends a NEW active-edge event before the
    following ``search`` replay. The search replay target therefore ALWAYS outruns the
    committed ``semantic_edges`` checkpoint, so ``SearchProjectionBuilder`` raises
    ``EdgeProjectionLagError`` on every attempt — including the P7-S2 catch-up re-passes,
    which this driver intercepts by overriding ``_run_locked`` (the exact seam
    ``_run_projection_pass`` drives for attempts >= 1). A truly persistent writer keeps
    committing faster than any bounded catch-up can finish, so the fixed attempt bound is
    the correct honest-failure behavior — never silent success, never stale publication.
    """

    def __init__(
        self,
        engine: sa.Engine,
        store: ProjectionCheckpointStore,
        *,
        append_edge,
    ) -> None:
        super().__init__(engine, store)
        self._append_edge = append_edge
        self.edges_passes = 0
        self.search_attempts = 0

    def _run_locked(
        self,
        builder: object,
        *,
        wipe: bool = False,
        force_resume: bool = False,
    ) -> object:
        name = getattr(builder, "projection_name", type(builder).__name__)
        if name == "search":
            self.search_attempts += 1
        report = super()._run_locked(builder, wipe=wipe, force_resume=force_resume)  # type: ignore[arg-type]
        if name == "semantic_edges":
            self.edges_passes += 1
            self._append_edge()
        return report


# ---------------------------------------------------------------------------
# P7-S3 — failure path 1: the PERSISTENT race exhausts the bounded whole-pass retry
# and the stage fails HONESTLY (real EdgeProjectionLagError, no partial search
# publication, append-only ledger preserved, retries genuinely finite)
# ---------------------------------------------------------------------------
def test_stage_fails_honestly_after_bounded_retry_exhaustion_with_no_partial_search(
    umd_db: sa.Engine,
) -> None:
    """A freshness violation that recurs on EVERY bounded-retry attempt (a persistent
    concurrent writer) must exhaust the fixed ``_CURRENT_SEARCH_MAX_PASS_ATTEMPTS``
    bound and fail the stage by re-raising the REAL ``EdgeProjectionLagError`` — never a
    wrapper, never silent success. The search checkpoint and the edge-derived search
    documents remain byte-for-byte unchanged (each failing search rebuild rolls back),
    and the ledger stays append-only (only new rows, no rewrites)."""
    ensure_source(umd_db)
    _assert_typed(umd_db, "e:alice", "e:carol", "MENTOR_OF", marker="base1")
    _assert_typed(umd_db, "e:alice", "e:carol", "RIVAL_OF", marker="base2")

    # Establish a GREEN baseline through the production stage: all three checkpoints sit
    # at the base tail and the search store carries live edge-derived docs.
    store = ProjectionCheckpointStore(umd_db)
    _run_stage_with_driver(umd_db, job_id="p7-exh-baseline", driver=ReplayDriver(umd_db, store))
    base_tail = _tail(umd_db)
    search_cp0 = _checkpoint_seq(umd_db, "search")
    assert search_cp0 == base_tail and base_tail >= 2
    baseline_docs = _search_edge_refs(umd_db)
    baseline_doc_count = _rowcount(umd_db, "search_document")
    assert len(baseline_docs) == 2
    ledger_before = _ledger_seqs(umd_db)

    # The PERSISTENT race: a concurrent writer keeps appending a new edge after every
    # semantic_edges rebuild, so every one of the bounded retries observes a search replay
    # target ahead of the committed semantic_edges checkpoint.
    driver = _PersistentLagDriver(umd_db, store, append_edge=_make_appender(umd_db))
    with pytest.raises(EdgeProjectionLagError, match="trails search replay target"):
        _run_stage_with_driver(umd_db, job_id="p7-exhaust", driver=driver)

    # Boundedness is real: the retry loop ran exactly the fixed bound and then re-raised
    # the REAL freshness error (no silent success, no unbounded loop, no wrapper).
    assert driver.edges_passes == _CURRENT_SEARCH_MAX_PASS_ATTEMPTS
    assert driver.search_attempts == _CURRENT_SEARCH_MAX_PASS_ATTEMPTS
    assert _CURRENT_SEARCH_MAX_PASS_ATTEMPTS == 3

    # Honest failure / rollback: the search checkpoint never advanced and no edge-derived
    # search document was published from a lagging edge store (every failing search
    # rebuild rolled back wholesale).
    assert _checkpoint_seq(umd_db, "search") == search_cp0
    assert _search_edge_refs(umd_db) == baseline_docs
    assert _rowcount(umd_db, "search_document") == baseline_doc_count

    # Append-only ledger: only NEW rows were appended (one per attempt), never deleted or
    # rewritten; the pre-existing rows are a byte-identical prefix.
    ledger_after = _ledger_seqs(umd_db)
    assert ledger_after[: len(ledger_before)] == ledger_before
    assert len(ledger_after) == len(ledger_before) + _CURRENT_SEARCH_MAX_PASS_ATTEMPTS
    assert ledger_after == list(range(1, len(ledger_after) + 1))  # gap-free, no reorder


# ---------------------------------------------------------------------------
# P7-S3 — failure paths 2 & 3: an independently forced stale semantic_edges checkpoint
# makes SearchProjectionBuilder refuse to publish (search checkpoint + edge docs
# unchanged), and only a coordinated subsequent pass that replays semantic_edges to the
# SAME target the search observed publishes fresh docs and advances the search checkpoint
# (converged values, no partial publication in between)
# ---------------------------------------------------------------------------
def test_independently_stale_edge_checkpoint_refuses_then_coordinated_pass_converges(
    umd_db: sa.Engine,
) -> None:
    """DIRECTLY forcing the committed ``semantic_edges`` checkpoint to trail the search
    replay target (independent of any concurrency) must make ``SearchProjectionBuilder``
    refuse to publish — search checkpoint unchanged, edge-derived docs unchanged. Only a
    coordinated subsequent pass that replays ``semantic_edges`` to the SAME target the
    search observed publishes fresh docs and advances the search checkpoint to that
    converged value, with no partial publication in between."""
    ensure_source(umd_db)
    _assert_typed(umd_db, "e:alice", "e:carol", "MENTOR_OF", marker="base1")
    _assert_typed(umd_db, "e:alice", "e:carol", "RIVAL_OF", marker="base2")
    store = ProjectionCheckpointStore(umd_db)
    _run_stage_with_driver(umd_db, job_id="p7-stale-baseline", driver=ReplayDriver(umd_db, store))
    tail0 = _tail(umd_db)
    search_cp0 = _checkpoint_seq(umd_db, "search")
    assert search_cp0 == tail0 and tail0 >= 2
    baseline_docs = _search_edge_refs(umd_db)
    doc_count0 = _rowcount(umd_db, "search_document")
    assert len(baseline_docs) == 2

    # Advance the ledger with a NEW active edge but do NOT replay semantic_edges, then
    # DIRECTLY FORCE the committed semantic_edges checkpoint to trail the search replay
    # target (stale independent of any concurrency / event-order timing).
    _assert_typed(umd_db, "e:bob", "e:carol", "MENTOR_OF", marker="grow1")
    target = _tail(umd_db)
    assert target > tail0
    store.save(ProjectionCheckpoint("semantic_edges", applied_seq=0))
    assert _checkpoint_seq(umd_db, "semantic_edges") == 0 < target

    # Exercising SearchProjectionBuilder alone against the forced-stale edge store refuses
    # to publish: the freshness guard raises and the whole search rebuild rolls back
    # (search checkpoint unchanged, edge-derived docs unchanged).
    with pytest.raises(EdgeProjectionLagError, match="trails search replay target"):
        ReplayDriver(umd_db, store).run(SearchProjectionBuilder(), wipe=True, force_resume=True)
    assert _checkpoint_seq(umd_db, "search") == search_cp0
    assert _search_edge_refs(umd_db) == baseline_docs
    assert _rowcount(umd_db, "search_document") == doc_count0

    # A COORDINATED subsequent pass replays tier1 + semantic_edges to the SAME target the
    # search observed and only THEN publishes fresh search docs and advances the search
    # checkpoint — all three checkpoints converge to that exact target.
    outcome = _run_stage_with_driver(
        umd_db, job_id="p7-stale-catchup", driver=ReplayDriver(umd_db, store)
    )
    for name in ("current_tier1", "semantic_edges", "search"):
        assert _checkpoint_seq(umd_db, name) == target, name
        # existing stage artifact/evidence checkpoint-reference shape is preserved.
        assert f"projection_checkpoint:{name}:seq{target}" in (outcome.evidence_refs or []), (
            f"missing {name} checkpoint ref {target} in {outcome.evidence_refs}"
        )
    # No partial publication in between: after the coordinated pass the search store
    # indexes EXACTLY the current active edges, including the new one.
    active = _active_edge_fact_ids(umd_db)
    converged = _search_edge_refs(umd_db)
    assert converged == {f"edge:{fid}" for fid in active}
    assert len(converged) == 3
    assert _rowcount(umd_db, "search_document") > doc_count0
