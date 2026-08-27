"""Cross-source alignment (Phase 1).

Append-only many-to-many ``Aligned`` correspondence events. Vecalign is GATED
(``PARALLEL_MONOTONE`` only); adaptation/subtitle/nonparallel correspondence uses
bounded reference methods (timecode/DTW, scene order, embeddings, signals) and is
labeled with ``ADAPTATION``/``TEMPORAL`` assumptions plus omission, addition,
reordering and contradiction metadata. Evidence is never merged.
"""

from __future__ import annotations

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
    align_timecode,
    aligned_event,
    alignment_capability_report,
    build_plan,
    cosine_similarity,
    dtw_path,
)

__all__ = [
    "AlignMethod",
    "AlignedPair",
    "AlignableUnit",
    "AlignmentPlan",
    "AlignmentService",
    "AlignmentType",
    "ParallelityAssumption",
    "VecalignAligner",
    "VecalignUnavailable",
    "aligned_event",
    "align_embeddings",
    "align_many_to_many",
    "align_monotone_parallel",
    "align_scene_order",
    "align_timecode",
    "alignment_capability_report",
    "build_plan",
    "cosine_similarity",
    "dtw_path",
]
