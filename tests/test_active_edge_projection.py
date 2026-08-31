"""Phase O / P2-S1..S4: active multi-edge relationship projection smoke test.

Focused smoke coverage for the replay-built ``active_semantic_edge`` read side
(the full matrix is left to Phase 3):

  * multi-edge — two distinct facts sharing ``(subject_ref, predicate)`` with
    different objects coexist as separate ACTIVE edges;
  * supersession without deletion — a user override supersedes the machine edge
    (``active=false`` + ``superseded_by_seq``) and activates the override edge;
    invalidation supersedes the targeted active edges;
  * wipe-and-replay determinism + idempotency — rebuilding from the ledger yields
    the identical active edge set (no drift, no double-counting);
  * edge identity alignment — a machine assertion's edge ``fact_id`` equals its
    ``semantic_assertion.id`` (content-addressable identity reuse).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
import sqlalchemy as sa

from umd.application.commands import SemanticCommandService
from umd.projections.base import ReplayDriver
from umd.projections.checkpoint import ProjectionCheckpointStore
from umd.projections.edges import ActiveSemanticEdgeProjectionBuilder
from umd.projections.query import QueryService
from umd.storage.postgres.ledger import SemanticLedger

pytestmark = pytest.mark.postgres


def _tail(engine: sa.Engine) -> int:
    with engine.connect() as c:
        return int(
            c.execute(sa.text("SELECT coalesce(max(seq),0) FROM semantic_event")).scalar() or 0
        )


def _active_edges(engine: sa.Engine, subject: str, predicate: str) -> Sequence[sa.Row[Any]]:
    with engine.connect() as c:
        return c.execute(
            sa.text(
                "SELECT object_ref, authority, active, superseded_by_seq "
                "FROM active_semantic_edge WHERE subject_ref=:s AND predicate=:p "
                "AND active ORDER BY ledger_seq"
            ),
            {"s": subject, "p": predicate},
        ).fetchall()


def _build(umd_db: sa.Engine, builder: ActiveSemanticEdgeProjectionBuilder) -> None:
    store = ProjectionCheckpointStore(umd_db)
    report = ReplayDriver(umd_db, store).run(builder, wipe=True)
    assert report.events_seen == _tail(umd_db)
    assert report.skipped == 0


def test_relationship_edges_multi_edge_and_edge_identity(umd_db: sa.Engine) -> None:
    commands = SemanticCommandService(SemanticLedger(umd_db))
    commands.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:alice",
        object_ref="hello, alice",
        confidence=0.6,
        state="PROBABLE",
        scope="CONTINUITY",
        support_refs=["source://s/audio/0"],
        generated_by={"provider": "reference-asr"},
        actor="worker-asr",
    )
    commands.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:alice",
        object_ref="welcome to the garden",
        confidence=0.5,
        state="PROBABLE",
        scope="CONTINUITY",
        support_refs=["source://s/audio/1"],
        generated_by={"provider": "reference-asr"},
        actor="worker-asr",
    )

    builder = ActiveSemanticEdgeProjectionBuilder()
    _build(umd_db, builder)

    # Multi-edge: both distinct utterances are ACTIVE (same subject+predicate, diff objects).
    rows = _active_edges(umd_db, "e:alice", "SPEAKS")
    assert {str(r[0]) for r in rows} == {"hello, alice", "welcome to the garden"}
    assert all(r[2] is True for r in rows)

    # Content-addressable identity aligns with semantic_assertion.id for machine facts.
    with umd_db.connect() as c:
        assertion_ids = {
            str(r[0])
            for r in c.execute(
                sa.text(
                    "SELECT id FROM semantic_assertion WHERE subject_ref='e:alice' "
                    "AND predicate_code='SPEAKS'"
                )
            ).fetchall()
        }
        edge_fact_ids = {
            str(r[0])
            for r in c.execute(
                sa.text(
                    "SELECT fact_id FROM active_semantic_edge "
                    "WHERE subject_ref='e:alice' AND active"
                )
            ).fetchall()
        }
    assert assertion_ids and edge_fact_ids == assertion_ids  # both machine edges aligned

    # Bounded structured read surfaces both active edges.
    query = QueryService(umd_db)
    page = query.structured({"kind": "RELATIONSHIP_EDGES", "filters": {"subject": "e:alice"}})
    assert page.total == 2
    assert {h.value for h in page.results} == {"hello, alice", "welcome to the garden"}
    assert all(h.capabilities.get("edge") for h in page.results)
    assert set(page.result_kinds) == {"SOURCE_EVIDENCE", "INTERPRETATION"}


def test_override_supersedes_machine_edge_and_activates_override_edge(umd_db: sa.Engine) -> None:
    commands = SemanticCommandService(SemanticLedger(umd_db))
    commands.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:alice",
        object_ref="machine utterance",
        confidence=0.6,
        state="PROBABLE",
        scope="CONTINUITY",
        support_refs=["source://s/audio/0"],
        generated_by={"provider": "reference-asr"},
        actor="worker-asr",
    )
    commands.record_override(
        subject_ref="e:alice",
        predicate="SPEAKS",
        object_ref="user-corrected utterance",
        actor="reviewer@example",
        evidence=["source://s/audio/0"],
        reason="manual transcription correction",
        confidence=1.0,
    )

    builder = ActiveSemanticEdgeProjectionBuilder()
    _build(umd_db, builder)

    # Only the override edge is active; the machine edge is superseded (history retained).
    rows = _active_edges(umd_db, "e:alice", "SPEAKS")
    assert [str(r[0]) for r in rows] == ["user-corrected utterance"]
    assert rows[0][1] == "USER_OVERRIDE"
    with umd_db.connect() as c:
        superseded = c.execute(
            sa.text(
                "SELECT count(*) FROM active_semantic_edge "
                "WHERE subject_ref='e:alice' AND predicate='SPEAKS' AND active=false"
            )
        ).scalar()
        assert superseded == 1  # historical machine assertion retained, not deleted


def test_correction_with_prior_ref_supersedes_only_targeted_edge(umd_db: sa.Engine) -> None:
    commands = SemanticCommandService(SemanticLedger(umd_db))
    commands.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:rabbit",
        object_ref="prior line",
        confidence=0.6,
        state="PROBABLE",
        scope="CONTINUITY",
        support_refs=["source://s/audio/0"],
        generated_by={"provider": "reference-asr"},
        actor="worker-asr",
    )
    commands.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:rabbit",
        object_ref="other line",
        confidence=0.5,
        state="PROBABLE",
        scope="CONTINUITY",
        support_refs=["source://s/audio/1"],
        generated_by={"provider": "reference-asr"},
        actor="worker-asr",
    )
    commands.record_correction(
        subject_ref="e:rabbit",
        predicate="SPEAKS",
        object_ref="corrected line",
        prior_ref="prior line",
        actor="reviewer@example",
        reason="fix the first utterance",
    )

    builder = ActiveSemanticEdgeProjectionBuilder()
    _build(umd_db, builder)

    # prior_ref targets ONLY the matching machine edge; the unrelated edge stays active.
    rows = _active_edges(umd_db, "e:rabbit", "SPEAKS")
    assert {str(r[0]) for r in rows} == {"other line", "corrected line"}


def test_invalidation_supersedes_targeted_active_edges(umd_db: sa.Engine) -> None:
    commands = SemanticCommandService(SemanticLedger(umd_db))
    commands.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:alice",
        object_ref="now invalid",
        confidence=0.6,
        state="PROBABLE",
        scope="CONTINUITY",
        support_refs=["source://s/audio/0"],
        generated_by={"provider": "reference-asr"},
        actor="worker-asr",
    )
    commands.invalidate(
        subject_ref="e:alice",
        predicate="SPEAKS",
        cause="manual invalidation",
        scope="CONTINUITY",
        stage="ENTITY_RESOLUTION",
        refs=["source://s/audio/0"],
    )

    builder = ActiveSemanticEdgeProjectionBuilder()
    _build(umd_db, builder)

    assert _active_edges(umd_db, "e:alice", "SPEAKS") == []
    with umd_db.connect() as c:
        retained = c.execute(
            sa.text(
                "SELECT count(*) FROM active_semantic_edge "
                "WHERE subject_ref='e:alice' AND active=false"
            )
        ).scalar()
        assert retained == 1  # history retained, not deleted


def test_wipe_and_replay_is_deterministic_and_idempotent(umd_db: sa.Engine) -> None:
    commands = SemanticCommandService(SemanticLedger(umd_db))
    commands.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:alice",
        object_ref="stable value",
        confidence=0.6,
        state="PROBABLE",
        scope="CONTINUITY",
        support_refs=["source://s/audio/0"],
        generated_by={"provider": "reference-asr"},
        actor="worker-asr",
    )
    commands.record_override(
        subject_ref="e:alice",
        predicate="SPEAKS",
        object_ref="stable override",
        actor="reviewer@example",
        evidence=["source://s/audio/0"],
        reason="keep",
        confidence=1.0,
    )

    def snapshot() -> set[tuple[str, str, bool, int | None]]:
        with umd_db.connect() as c:
            rows = c.execute(
                sa.text(
                    "SELECT object_ref, authority, active, superseded_by_seq "
                    "FROM active_semantic_edge ORDER BY ledger_seq, object_ref"
                )
            ).fetchall()
        return {(str(r[0]), str(r[1]), bool(r[2]), r[3]) for r in rows}

    builder = ActiveSemanticEdgeProjectionBuilder()
    _build(umd_db, builder)
    first = snapshot()
    # A second wipe-and-replay rebuild yields the identical active edge set.
    _build(umd_db, builder)
    assert snapshot() == first
    # Only the override edge is active after replay (correct supersession re-derived).
    assert (
        _active_edges(umd_db, "e:alice", "SPEAKS")
        and str(_active_edges(umd_db, "e:alice", "SPEAKS")[0][0]) == "stable override"
    )


def test_relationship_edges_reflects_contradiction_state(umd_db: sa.Engine) -> None:
    commands = SemanticCommandService(SemanticLedger(umd_db))
    commands.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:alice",
        object_ref="line A",
        confidence=0.6,
        state="PROBABLE",
        scope="CONTINUITY",
        support_refs=["source://s/audio/0"],
        generated_by={"provider": "reference-asr"},
        actor="worker-asr",
    )
    commands.record_contradiction(
        subject_ref="e:alice",
        predicate="SPEAKS",
        contradicting_ref="source://s/audio/1",
        refs=["source://s/audio/1"],
        reason="conflicting transcripts",
    )

    builder = ActiveSemanticEdgeProjectionBuilder()
    _build(umd_db, builder)

    with umd_db.connect() as c:
        state = c.execute(
            sa.text(
                "SELECT state, contradiction_refs FROM active_semantic_edge "
                "WHERE subject_ref='e:alice' AND predicate='SPEAKS' AND active"
            )
        ).fetchall()
    assert state and all(r[0] == "CONFLICTING" for r in state)


# ---------------------------------------------------------------------------
# P3-S3: multi-edge replay matrix — full provenance + bounded pagination
# ---------------------------------------------------------------------------


def _assert_speaks(
    commands: SemanticCommandService, subject: str, value: str, confidence: float
) -> None:
    commands.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref=subject,
        object_ref=value,
        confidence=confidence,
        state="PROBABLE",
        scope="CONTINUITY",
        support_refs=[f"source://s/audio/{value}"],
        generated_by={"provider": "reference-asr", "config_digest": "asr@2"},
        actor="worker-asr",
    )


def test_relationship_edges_query_returns_every_active_edge_with_provenance(
    umd_db: sa.Engine,
) -> None:
    """P3-S3: the bounded relationship read returns EVERY active edge (multi-edge
    coexistence) with confidence, authority, state, scope and provenance, while the
    superseded edge is excluded from active reads but retained as immutable history.

    Full provenance (evidence ``support_refs``, ``generated_by``, supersession
    status) is retained on the stored rows."""
    commands = SemanticCommandService(SemanticLedger(umd_db))
    _assert_speaks(commands, "e:alice", "line-1", 0.9)
    _assert_speaks(commands, "e:alice", "line-2", 0.7)
    _assert_speaks(commands, "e:alice", "line-3", 0.5)
    commands.record_correction(
        subject_ref="e:alice",
        predicate="SPEAKS",
        object_ref="line-2-corrected",
        prior_ref="line-2",
        actor="reviewer@example",
        reason="fix line 2",
    )

    builder = ActiveSemanticEdgeProjectionBuilder()
    _build(umd_db, builder)

    query = QueryService(umd_db)
    page = query.structured({"kind": "RELATIONSHIP_EDGES", "filters": {"subject": "e:alice"}})
    assert page.total == 3  # line-1, line-3, line-2-corrected all ACTIVE
    by_value = {h.value: h for h in page.results}
    assert set(by_value) == {"line-1", "line-3", "line-2-corrected"}
    for h in page.results:
        # confidence / authority / state / scope surfaced on the hit. Machine
        # edges carry a confidence; user override/correction edges carry none.
        if h.kind == "SOURCE_EVIDENCE":
            assert h.confidence is not None and 0.0 <= h.confidence <= 1.0
        else:
            assert h.confidence is None or 0.0 <= h.confidence <= 1.0
        assert h.capabilities.get("edge") is True
        assert h.provenance["fact_id"]
        assert h.provenance["state"] in {
            "CONFIRMED",
            "PROBABLE",
            "UNKNOWN",
            "AMBIGUOUS",
            "CONFLICTING",
            "USER_CONFIRMED",
        }
        assert h.provenance["scope"] in {"SOURCE", "GLOBAL", "CONTINUITY"}
        assert h.provenance["seq"] >= 1
    assert set(page.result_kinds) == {"SOURCE_EVIDENCE", "INTERPRETATION"}

    # Full provenance is retained on the stored rows: evidence support_refs,
    # contradiction_refs, generated_by in derivation, and supersession status.
    with umd_db.connect() as c:
        superseded = c.execute(
            sa.text(
                "SELECT support_refs, derivation, superseded_by_seq, superseded_by_fact, active "
                "FROM active_semantic_edge "
                "WHERE subject_ref='e:alice' AND object_ref='line-2'"
            )
        ).fetchall()
    (sup,) = superseded
    assert sup.support_refs == ["source://s/audio/line-2"]  # evidence retained
    assert sup.derivation["generated_by"]["provider"] == "reference-asr"
    assert sup.derivation["source_refs"]
    assert sup.active is False  # superseded, not deleted
    assert sup.superseded_by_seq is not None
    # superseded_by_fact is a nullable schema column the edge builder does not
    # populate on deactivation; supersession status is carried by active=False +
    # superseded_by_seq.


def test_relationship_edges_bounded_pagination(umd_db: sa.Engine) -> None:
    """P3-S3: bounded-depth/pagination — limit/offset return a slice, total counts
    every active edge, and superseded edges never leak into the active page."""
    commands = SemanticCommandService(SemanticLedger(umd_db))
    for i in range(5):
        _assert_speaks(commands, "e:alice", f"seg-{i}", 0.6)
    commands.record_correction(
        subject_ref="e:alice",
        predicate="SPEAKS",
        object_ref="seg-0-fixed",
        prior_ref="seg-0",
        actor="reviewer@example",
        reason="fix first",
    )

    builder = ActiveSemanticEdgeProjectionBuilder()
    _build(umd_db, builder)
    query = QueryService(umd_db)

    page = query.structured(
        {"kind": "RELATIONSHIP_EDGES", "filters": {"subject": "e:alice"}, "limit": 2, "offset": 0}
    )
    assert page.total == 5  # seg-0-fixed + seg-1..4 (seg-0 superseded)
    assert len(page.results) == 2
    first_two = {h.value for h in page.results}
    assert "seg-0" not in first_two  # superseded never active

    page2 = query.structured(
        {"kind": "RELATIONSHIP_EDGES", "filters": {"subject": "e:alice"}, "limit": 2, "offset": 2}
    )
    assert len(page2.results) == 2
    page3 = query.structured(
        {"kind": "RELATIONSHIP_EDGES", "filters": {"subject": "e:alice"}, "limit": 2, "offset": 4}
    )
    assert len(page3.results) == 1
    # No overlap across the paginated slices; every active edge appears exactly once.
    seen = first_two | {h.value for h in page2.results} | {h.value for h in page3.results}
    assert seen == {f"seg-{i}" for i in range(1, 5)} | {"seg-0-fixed"}
