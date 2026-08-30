"""P1-S5 spec-first tests: many-to-many / omitted / adaptation-only / reordered /
contradictory alignment, monotone-parallel labeling, honest Vecalign gate, and
append-only Aligned event persistence."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from umd.alignment.align import (
    AlignableUnit,
    AlignedPair,
    AlignmentPlan,
    AlignmentService,
    AlignmentType,
    AlignMethod,
    ParallelityAssumption,
    VecalignAligner,
    VecalignUnavailable,
    align_embeddings,
    align_many_to_many,
    align_monotone_parallel,
    align_scene_order,
    aligned_event,
    build_plan,
    dtw_path,
    timecode_distance,
)
from umd.application.commands import SemanticCommandService
from umd.storage.postgres.ledger import SemanticLedger
from umd.storage.postgres.tables import metadata as db_meta

pytestmark = pytest.mark.postgres

_event_t = db_meta.tables["semantic_event"]
_alignment_t = db_meta.tables["alignment"]
_state_t = db_meta.tables["current_state"]


def _u(ref, start, end=0.0, scene="", embedding=(), speakers=frozenset()):
    return AlignableUnit(
        ref=ref,
        start=start,
        end=end,
        scene=scene,
        embedding=embedding,
        speakers=speakers,
    )


def test_many_to_many_correspondence_via_dtw():
    """DTW recovers one-to-many/many-to-many alignments (two left units -> one right)."""
    left = [_u("u1", 0.0, 1.0), _u("u2", 2.0, 3.0)]
    right = [_u("v1", 0.5, 1.5)]
    path = dtw_path(left, right, timecode_distance)
    plan = build_plan(
        left,
        right,
        path=path,
        method=AlignMethod.TIMECODE_DTW,
        alignment_type=AlignmentType.TEMPORAL,
        parallelity_assumption=ParallelityAssumption.TEMPORAL,
        confidence=0.6,
    )
    # both left units map onto the single right unit
    assert len(plan.pairs) == 2
    assert {p.left_ref for p in plan.pairs} == {"u1", "u2"}
    assert {p.right_ref for p in plan.pairs} == {"v1"}


def test_omitted_and_adaptation_only():
    """Omitted and added units are surfaced as first-class metadata."""
    left = [_u("L:1", 0.0, scene="s1"), _u("L:2", 0.0, scene="s2")]
    right = [_u("R:2", 0.0, scene="s2"), _u("R:3", 0.0, scene="s3")]
    plan = align_scene_order(left, right, confidence=0.5)
    # scene s2 is the shared adaptation anchor
    assert {p.left_ref for p in plan.pairs} == {"L:2"}
    assert {p.right_ref for p in plan.pairs} == {"R:2"}
    # L:1 (s1) has no scene match -> addition; R:3 (s3) is omitted from the source
    assert "L:1" in plan.additions
    assert "R:3" in plan.omissions
    assert plan.parallelity_assumption == ParallelityAssumption.ADAPTATION
    assert all(p.alignment_type == AlignmentType.ADAPTATION for p in plan.pairs)


def test_reordering_detected():
    """Reordering is flagged when left/right sequence order diverges."""
    left = [_u("L:1", 0.0), _u("L:2", 1.0)]
    right = [_u("R:2", 0.0), _u("R:1", 1.0)]
    path = [(0, 0), (1, 1)]  # L:1->R:2, L:2->R:1 (right order reversed)
    plan = build_plan(
        left,
        right,
        path=path,
        method=AlignMethod.SCENE_ORDER_DTW,
        alignment_type=AlignmentType.ADAPTATION,
        parallelity_assumption=ParallelityAssumption.ADAPTATION,
        confidence=0.5,
    )
    assert plan.reordering is True


def test_contradictory_alignment_flagged():
    """Embedding-dissimilar correspondence is labeled a contradiction, not merged."""
    left = [_u("u1", 0.0, embedding=(1.0, 0.0))]
    right = [_u("v1", 0.0, embedding=(-1.0, 0.0))]
    plan = align_embeddings(left, right, threshold=0.35, confidence=0.5)
    assert len(plan.contradictions) == 1
    assert plan.contradictions[0] == ("u1", "v1")


def test_monotone_parallel_is_labeled_parallel_monotone():
    left = [_u("a", 0.0, 1.0), _u("b", 2.0, 3.0)]
    right = [_u("a'", 0.0, 1.0), _u("b'", 2.0, 3.0)]
    plan = align_monotone_parallel(left, right, confidence=0.8)
    assert plan.parallelity_assumption == ParallelityAssumption.PARALLEL_MONOTONE
    for pair in plan.pairs:
        evt = aligned_event(pair)
        assert evt.payload["method"] == "timecode-dtw"
        assert evt.event_type == "Aligned"


def test_vecalign_is_honestly_gated():
    assert VecalignAligner.active() is False
    aligner = VecalignAligner()
    with pytest.raises(VecalignUnavailable):
        aligner.align([_u("a", 0.0)], [_u("b", 0.0)])


def test_align_many_to_many_dispatch_labels_method():
    left = [_u("u1", 0.0, 1.0), _u("u2", 2.0, 3.0)]
    right = [_u("v1", 0.5, 1.5)]
    plan = align_many_to_many(left, right, method=AlignMethod.TIMECODE_DTW)
    assert all(p.method == AlignMethod.TIMECODE_DTW for p in plan.pairs)
    # one-to-many preserved; evidence never merged (pairs are distinct)
    assert len(plan.pairs) == 2


def test_public_alignment_command_binds_event_to_query_row(umd_db):
    """The REST command's ledger event and correspondence row commit together."""
    svc = SemanticCommandService(SemanticLedger(umd_db))
    commit = svc.record_alignment(
        left_ref="source:left#text/1",
        right_ref="source:right#text/1",
        alignment_type="ADAPTATION",
        method="api",
        confidence=1.0,
    )
    assert commit.seq > 0

    with umd_db.connect() as conn:
        row = conn.execute(
            sa.select(
                _alignment_t.c.left_ref,
                _alignment_t.c.right_ref,
                _alignment_t.c.alignment_type,
                _alignment_t.c.method,
                _alignment_t.c.confidence,
            )
        ).one()
        event = conn.execute(
            sa.select(_event_t.c.payload).where(_event_t.c.event_type == "Aligned")
        ).one()

    assert dict(row._mapping) == {
        "left_ref": "source:left#text/1",
        "right_ref": "source:right#text/1",
        "alignment_type": "ADAPTATION",
        "method": "api",
        "confidence": 1.0,
    }
    assert event.payload["left_ref"] == row.left_ref
    assert event.payload["right_ref"] == row.right_ref


def test_alignment_service_appends_non_semantic_events_and_rows(umd_db):
    """Aligned events are NON_SEMANTIC (no Tier-0 fold) and bound to alignment rows."""

    def record_row(aid: str, pair: AlignedPair, _plan: AlignmentPlan, conn: sa.Connection) -> None:
        al_t = db_meta.tables["alignment"]
        conn.execute(
            al_t.insert().values(
                id=aid,
                left_ref=pair.left_ref,
                right_ref=pair.right_ref,
                alignment_type=pair.alignment_type.value,
                method=pair.method.value,
                assumptions={},
                source_events={},
                confidence=pair.confidence,
            )
        )

    left = [_u("u1", 0.0, 1.0), _u("u2", 2.0, 3.0)]
    right = [_u("v1", 0.5, 1.5)]
    plan = align_many_to_many(left, right)
    assert plan.pairs  # guard: the plan must produce pairs, else the test is vacuous

    svc = AlignmentService(SemanticLedger(umd_db), record_row=record_row)
    commit = svc.append_plan(plan)
    assert commit.seq > 0

    with umd_db.connect() as conn:
        n_aligned = conn.execute(
            sa.select(sa.func.count())
            .select_from(_event_t)
            .where(_event_t.c.event_type == "Aligned")
        ).scalar()
    assert n_aligned == len(plan.pairs)

    with umd_db.connect() as conn:
        n_rows = conn.execute(sa.select(sa.func.count()).select_from(_alignment_t)).scalar()
    assert n_rows == len(plan.pairs)

    # Aligned is NON_SEMANTIC: no Tier-0 current_state row is created.
    with umd_db.connect() as conn:
        n_state = conn.execute(sa.select(sa.func.count()).select_from(_state_t)).scalar()
    assert n_state == 0
