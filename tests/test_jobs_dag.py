"""P1-S1: canonical in-repository stage lineage (unit)."""

from __future__ import annotations

from umd.jobs.dag import (
    MODALITY_BRANCHES,
    STAGE_DEPENDENCIES,
    STAGE_DEPENDENTS,
    STAGE_ORDER,
    stage_dependency,
    stages,
)
from umd.jobs.invalidation import InvalidationPlanner

CANONICAL_ORDER = [
    "INGEST",
    "FORMAT_ANALYSIS",
    "BASIC_SEGMENTATION",
    "LOW_LEVEL_EXTRACTION",
    "STRUCTURAL_ANALYSIS",
    "ENTITY_RESOLUTION",
    "CROSS_SOURCE_ALIGNMENT",
    "SEMANTIC_RECONCILIATION",
    "CURRENT_SEARCH_PROJECTION",
]


def test_canonical_dependency_order() -> None:
    assert list(STAGE_ORDER) == CANONICAL_ORDER


def test_every_edge_is_declared_with_an_evidence_class() -> None:
    for stage, deps in STAGE_DEPENDENCIES.items():
        if not deps:
            continue
        for _upstream, evidence_class in deps:
            assert evidence_class, f"{stage} edge lacks an evidence class"
    # INGEST is the root; every other stage has at least one declared dependency.
    assert STAGE_DEPENDENCIES["INGEST"] == ()
    for stage in CANONICAL_ORDER[1:]:
        assert STAGE_DEPENDENCIES[stage], f"{stage} has no upstream dependency"


def test_dependents_is_the_consistent_downward_lineage() -> None:
    # Recompute dependents from the dependency table and compare.
    recomputed: dict[str, list[str]] = {s: [] for s in STAGE_ORDER}
    for stage, deps in STAGE_DEPENDENCIES.items():
        for upstream, _c in deps:
            recomputed[upstream].append(stage)
    assert recomputed == STAGE_DEPENDENTS


def test_ingest_has_no_upstream_and_projection_is_terminal() -> None:
    assert STAGE_DEPENDENTS["INGEST"]
    assert STAGE_DEPENDENTS["CURRENT_SEARCH_PROJECTION"] == []


def test_dependency_rows_match_contracts_vocabulary() -> None:
    rows = stage_dependency()
    edges = {(r["stage"], r["depends_on_stage"]) for r in rows}
    assert ("FORMAT_ANALYSIS", "INGEST") in edges
    assert ("LOW_LEVEL_EXTRACTION", "BASIC_SEGMENTATION") in edges
    assert ("CURRENT_SEARCH_PROJECTION", "SEMANTIC_RECONCILIATION") in edges
    # The lineage names follow the CONTRACTS vocabulary.
    assert all({"stage", "depends_on_stage", "evidence_class"} <= set(r) for r in rows)


def test_stage_defs_are_complete() -> None:
    defs = stages()
    assert {d.name for d in defs} == set(STAGE_ORDER)
    for d in defs:
        assert d.description


def test_modality_branch_metadata_is_per_modality() -> None:
    assert {"text", "image", "audio", "video"} <= set(MODALITY_BRANCHES)
    for branch in MODALITY_BRANCHES.values():
        assert branch.modality
        assert branch.segment_types  # per-modality segmentation fan-out metadata


def test_planner_consumes_the_canonical_lineage() -> None:
    """The canonical dependents map feeds InvalidationPlanner directly."""
    planner = InvalidationPlanner()
    targets = planner.plan(
        causation="test", scope="SOURCE", stage="LOW_LEVEL_EXTRACTION", lineage=STAGE_DEPENDENTS
    )
    planned = [t.stage for t in targets.targets]
    # Descendant-only: nothing upstream of LOW_LEVEL_EXTRACTION is targeted.
    assert "INGEST" not in planned
    assert "FORMAT_ANALYSIS" not in planned
    assert "BASIC_SEGMENTATION" not in planned
    # Its transitive descendants must be (via both branches of the DAG).
    assert set(planned) == {
        "STRUCTURAL_ANALYSIS",
        "ENTITY_RESOLUTION",
        "CROSS_SOURCE_ALIGNMENT",
        "SEMANTIC_RECONCILIATION",
        "CURRENT_SEARCH_PROJECTION",
    }
