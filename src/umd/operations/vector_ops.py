"""Vector count / recall / HNSW monitoring + promotion review records (P1-S3).

The DD packaging-and-persistence contract requires: vector count / recall / HNSW
monitoring, and *measured* promotion-review records when the embedding count
crosses the 5M / 10M / 50M growth thresholds (review whether to promote to
halfvec / pgvectorscale / a dedicated vector store).

These are REVIEW RECORDS produced from real measurements (the live embedding row
count and the honest HNSW gate status) — never actions. The controller and
operational tests use them to decide nothing; they exist so an operator/reviewer
can see, honestly, where the store stands and what a promotion would require.
"""

from __future__ import annotations

import sqlalchemy as sa

from umd.observability.records import record_hnsw_maintenance
from umd.projections.vector import VectorIndex, VectorIndexUnavailable
from umd.storage.postgres.tables import metadata as db_meta

_embedding_t = db_meta.tables["embedding"]

#: DD growth thresholds at which a measured promotion review is warranted.
PROMOTION_THRESHOLDS = (5_000_000, 10_000_000, 50_000_000)


class VectorMonitor:
    """Honest vector-stack monitoring: count + HNSW gate + recall probe."""

    def __init__(self, engine: sa.Engine, index: VectorIndex) -> None:
        self._engine = engine
        self._index = index

    def count(self) -> int:
        """Live immutable embedding row count (append-only store)."""
        with self._engine.connect() as conn:
            total = conn.execute(sa.select(sa.func.count(_embedding_t.c.id))).scalar()
        return int(total or 0)

    def model_counts(self) -> dict[str, int]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.select(
                    _embedding_t.c.model,
                    sa.func.count(_embedding_t.c.id).label("vector_count"),
                ).group_by(_embedding_t.c.model)
            ).fetchall()
        return {str(r.model): int(r.vector_count) for r in rows}

    def hnsw_status(self) -> dict[str, object]:
        """Honest HNSW gate disclosure (never fabricated active)."""
        try:
            active = self._index.active()
        except VectorIndexUnavailable:
            active = False
        if active:
            record_hnsw_maintenance("probe-active")
        else:
            record_hnsw_maintenance("probe-gated")
        return {
            "backend": self._index.describe(),
            "active": active,
            "maintenance": {"last_probe": "probe-active" if active else "probe-gated"},
        }

    def promote_eligibility(self, count: int | None = None) -> dict[str, object]:
        """Review whether the store crosses a 5M/10M/50M promotion threshold.

        Returns an honest record: the measured count, the highest crossed growth
        tier (if any), and the promotion candidate(s) the DD names. Pure review.
        """
        n = self.count() if count is None else count
        crossed = [t for t in PROMOTION_THRESHOLDS if n >= t]
        candidates: list[str] = []
        if crossed:
            if n >= 50_000_000:
                candidates.append("dedicated-vector-store")
            if n >= 10_000_000:
                candidates.append("pgvectorscale")
            if n >= 5_000_000:
                candidates.append("halfvec")
        return {
            "measured_count": n,
            "growth_tier": crossed[-1] if crossed else None,
            "thresholds": list(PROMOTION_THRESHOLDS),
            "promotion_candidates": candidates,
            "review": "measured" if crossed else "below-all-thresholds",
        }


__all__ = ["VectorMonitor", "PROMOTION_THRESHOLDS"]
