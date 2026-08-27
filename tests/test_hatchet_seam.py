"""P1-S4: Hatchet adapter behind the DAGRunner seam + build-gate (unit)."""

from __future__ import annotations

import pytest

from umd.jobs.dag import STAGE_DEPENDENCIES, STAGE_ORDER
from umd.jobs.hatchet import (
    HATCHET_RUNNER_CONTRACT,
    HatchetNotConfiguredError,
    HatchetRunner,
    build_hatchet_workflows,
)


def test_workflow_specs_cover_every_in_repo_stage_dependency_ordered() -> None:
    specs = build_hatchet_workflows()
    assert [s.stage for s in specs] == list(STAGE_ORDER)
    by_stage = {s.stage: s for s in specs}
    # Each workflow declares its upstream dependencies with their evidence class.
    for stage, deps in STAGE_DEPENDENCIES.items():
        spec = by_stage[stage]
        assert spec.depends_on == [d for d, _c in deps]
        assert spec.consumes == [c for _d, c in deps]


def test_workflow_spec_dict_shape() -> None:
    spec = build_hatchet_workflows()[1]
    assert spec.stage == "FORMAT_ANALYSIS"
    d = spec.to_dict()
    assert d["depends_on"] == ["INGEST"]
    assert d["consumes"]  # evidence-class metadata survives the mapping


def test_hatchet_runner_refuses_live_submission_without_a_pinned_client() -> None:
    runner = HatchetRunner()
    with pytest.raises(HatchetNotConfiguredError) as exc:
        runner.run_graph(
            job_id="j",
            source_id="s",
            dag_universe="v1-dag:base",
            work_registry={},
            stages=["INGEST"],
        )
    # The build-gate is explicit: no fabricated/pinned release is being claimed.
    assert "no live client" in str(exc.value)
    assert "BUILD GATE" in str(exc.value) or "build-gate" in str(exc.value)


def test_runner_contract_records_the_pin_gate() -> None:
    # Hatchet is the SOLE v1 scheduler; the contract names no competing scheduler.
    assert HATCHET_RUNNER_CONTRACT["role"] == "sole-v1-scheduler"
    joined = " ".join(HATCHET_RUNNER_CONTRACT["requirements"]).lower()
    assert "claim-before-side-effect" in joined
    assert "restart" in joined


def test_workflow_specs_built_from_custom_dependency_table() -> None:
    custom = {"INGEST": (), "FORMAT_ANALYSIS": (("INGEST", "source_bytes"),)}
    specs = build_hatchet_workflows(custom)
    by_stage = {s.stage: s for s in specs}
    assert by_stage["FORMAT_ANALYSIS"].depends_on == ["INGEST"]
