"""P3-S3: pure descendant-only invalidation planner (unit, no DB)."""

from __future__ import annotations

from umd.jobs.invalidation import InvalidationPlanner

# The v1 DAG lineage (stage -> direct dependents) from the DD.
LINEAGE: dict[str, list[str]] = {
    "INGEST": ["FORMAT_ANALYSIS"],
    "FORMAT_ANALYSIS": ["BASIC_SEGMENTATION"],
    "BASIC_SEGMENTATION": ["LOW_LEVEL_EXTRACTION"],
    "LOW_LEVEL_EXTRACTION": ["STRUCTURAL_ANALYSIS", "OCR_ASR"],
    "STRUCTURAL_ANALYSIS": ["ENTITY_RESOLUTION", "CROSS_SOURCE_ALIGNMENT"],
    "OCR_ASR": ["ENTITY_RESOLUTION"],
    "ENTITY_RESOLUTION": ["CROSS_SOURCE_ALIGNMENT", "SEMANTIC_RECONCILIATION"],
    "CROSS_SOURCE_ALIGNMENT": ["SEMANTIC_RECONCILIATION"],
    "SEMANTIC_RECONCILIATION": [],
}


def test_planner_selects_only_descendants() -> None:
    p = InvalidationPlanner()
    targets = p.plan(
        causation="filter-version-bump",
        scope="source:1",
        stage="ENTITY_RESOLUTION",
        lineage=LINEAGE,
    )
    stages = {t.stage for t in targets.targets}
    # descendants of ENTITY_RESOLUTION only
    assert stages == {"CROSS_SOURCE_ALIGNMENT", "SEMANTIC_RECONCILIATION"}
    # never re-runs ancestors / unaffected branches (OCR/ASR/segmentation)
    assert "OCR_ASR" not in stages
    assert "LOW_LEVEL_EXTRACTION" not in stages
    assert "BASIC_SEGMENTATION" not in stages
    assert targets.descendant_only is True
    assert targets.root_stage == "ENTITY_RESOLUTION"


def test_rerun_speaker_resolution_does_not_rerun_extraction() -> None:
    p = InvalidationPlanner()
    targets = p.plan(
        causation="correction",
        scope="source:1",
        stage="ENTITY_RESOLUTION",
        lineage=LINEAGE,
    )
    stages = {t.stage for t in targets.targets}
    # Correction schedules only resolution/presence/alignment/reconciliation.
    assert {"CROSS_SOURCE_ALIGNMENT", "SEMANTIC_RECONCILIATION"} <= stages
    assert not (
        stages
        & {"OCR_ASR", "LOW_LEVEL_EXTRACTION", "BASIC_SEGMENTATION", "FORMAT_ANALYSIS", "INGEST"}
    )
    assert targets.unaffected >= 5  # unrelated/ancestor stages retained


def test_empty_or_none_lineage_yields_no_targets() -> None:
    p = InvalidationPlanner()
    assert p.plan("x", "s", "ENTITY_RESOLUTION", None).targets == []
    assert p.plan("x", "s", None, LINEAGE).targets == []
