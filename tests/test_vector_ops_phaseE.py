"""Plan E (P1-S3): unit tests for the vector-promotion-review surface (issue #4).

Covers :class:`VectorMonitor` (:mod:`umd.operations.vector_ops`) and the
controller's ``promotion_review`` / ``vector_capability`` / ``PromotionReview``
over the live ``umd_db`` Postgres fixture:

* the measured embedding-count + model-count reads against the real ``embedding``
  table;
* the honest HNSW gate disclosure — a gated ``VectorIndex`` (``active()==False``)
  is reported as inactive, never fabricated active;
* the 5M / 10M / 50M promotion-threshold crossing logic (measured thresholds are
  asserted by passing the count directly so no 50M-row fixture is needed).
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from resolution_helpers import insert_source
from umd.operations.controller import ProjectionController, PromotionReview
from umd.operations.vector_ops import PROMOTION_THRESHOLDS, VectorMonitor
from umd.storage.postgres.tables import metadata as db_meta

pytestmark = pytest.mark.postgres

_embedding_t = db_meta.tables["embedding"]
_segment_t = db_meta.tables["segment"]


def _insert_segment(engine: sa.Engine, source_id: str) -> str:
    seg_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            _segment_t.insert().values(
                id=seg_id,
                source_id=source_id,
                segment_type="scene",
                deterministic_key=f"k#{seg_id[:8]}",
                locator=f"source://s/{seg_id}",
                ordinal=1,
            )
        )
    return seg_id


def _insert_embeddings(engine: sa.Engine, segment_id: str, *, n: int, model: str = "m1") -> None:
    with engine.begin() as conn:
        for i in range(n):
            conn.execute(
                _embedding_t.insert().values(
                    segment_id=segment_id,
                    model=model,
                    model_version="1",
                    evidence_ref=f"ev:{segment_id}:{i}",
                    sequence_no=i + 1,
                    vector_json=[0.1 * i, 0.2, 0.3],
                )
            )


class _GatedIndex:
    """A stub vector backend that is honestly gated (never active)."""

    def active(self) -> bool:
        return False

    def describe(self) -> dict[str, object]:
        return {"backend": "stub-gated", "active": False}


class _ActiveIndex:
    def active(self) -> bool:
        return True

    def describe(self) -> dict[str, object]:
        return {"backend": "stub-active", "active": True}


# ---------------------------------------------------------------------------
# VectorMonitor over the live embedding table
# ---------------------------------------------------------------------------


def test_vector_monitor_counts_live_embeddings(umd_db: sa.Engine) -> None:
    sid = insert_source(umd_db)
    seg = _insert_segment(umd_db, sid)
    _insert_embeddings(umd_db, seg, n=3, model="m1")
    _insert_embeddings(umd_db, seg, n=2, model="m2")

    monitor = VectorMonitor(umd_db, _ActiveIndex())
    assert monitor.count() == 5
    counts = monitor.model_counts()
    assert counts == {"m1": 3, "m2": 2}


def test_vector_monitor_hnsw_gate_reports_inactive_honestly(umd_db: sa.Engine) -> None:
    # A gated backend (active()==False — e.g. pgvector not installed on bare PG)
    # must be reported inactive, never fabricated active.
    monitor = VectorMonitor(umd_db, _GatedIndex())
    status = monitor.hnsw_status()
    assert status["active"] is False
    assert status["backend"]["active"] is False
    assert status["maintenance"]["last_probe"] == "probe-gated"


def test_vector_monitor_hnsw_active_reports_probe(umd_db: sa.Engine) -> None:
    monitor = VectorMonitor(umd_db, _ActiveIndex())
    status = monitor.hnsw_status()
    assert status["active"] is True
    assert status["backend"]["active"] is True
    assert status["maintenance"]["last_probe"] == "probe-active"


# ---------------------------------------------------------------------------
# Promotion thresholds (measured review, not action)
# ---------------------------------------------------------------------------


def test_promote_eligibility_below_all_thresholds() -> None:
    monitor = VectorMonitor.__new__(VectorMonitor)  # no DB needed; count passed in
    rec = monitor.promote_eligibility(count=100)
    assert rec["measured_count"] == 100
    assert rec["growth_tier"] is None
    assert rec["promotion_candidates"] == []
    assert rec["review"] == "below-all-thresholds"


@pytest.mark.parametrize(
    ("count", "tier", "candidates"),
    [
        (5_000_000, 5_000_000, ["halfvec"]),
        (9_999_999, 5_000_000, ["halfvec"]),
        (10_000_000, 10_000_000, ["pgvectorscale", "halfvec"]),
        (20_000_000, 10_000_000, ["pgvectorscale", "halfvec"]),
        (50_000_000, 50_000_000, ["dedicated-vector-store", "pgvectorscale", "halfvec"]),
    ],
)
def test_promote_eligibility_threshold_crossing(
    count: int, tier: int, candidates: list[str]
) -> None:
    monitor = VectorMonitor.__new__(VectorMonitor)
    rec = monitor.promote_eligibility(count=count)
    assert rec["growth_tier"] == tier
    assert rec["promotion_candidates"] == candidates
    assert rec["review"] == "measured"
    assert rec["thresholds"] == list(PROMOTION_THRESHOLDS)


# ---------------------------------------------------------------------------
# Controller promotion_review / vector_capability
# ---------------------------------------------------------------------------


def test_controller_promotion_review_bridges_thresholds(umd_db: sa.Engine) -> None:
    controller = ProjectionController(umd_db, ledger_tail_fn=lambda _name: 0)
    # Measured count crossing the 5M tier without a 5M-row fixture.
    review: PromotionReview = controller.promotion_review(count=5_000_000)
    assert review.measured_count == 5_000_000
    assert review.growth_tier == 5_000_000
    assert review.promotion_candidates == ["halfvec"]
    assert review.thresholds == tuple([5_000_000, 10_000_000, 50_000_000])
    assert review.to_dict()["growth_tier"] == 5_000_000


def test_controller_vector_capability_reports_gated_backend(umd_db: sa.Engine) -> None:
    sid = insert_source(umd_db)
    seg = _insert_segment(umd_db, sid)
    _insert_embeddings(umd_db, seg, n=2, model="m1")

    controller = ProjectionController(umd_db, ledger_tail_fn=lambda _name: 0)
    cap = controller.vector_capability(_GatedIndex())
    assert cap["count"] == 2
    assert cap["model_counts"] == {"m1": 2}
    # The gated HNSW backend is honestly reported inactive.
    assert cap["hnsw"]["active"] is False
    assert cap["promotion"]["review"] == "below-all-thresholds"
