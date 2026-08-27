"""Hatchet adapter + build-gate pin record (P1-S4).

Hatchet is the ONLY v1 scheduler/runner. This module adapts the in-repository
stage lineage to Hatchet workflows behind the :class:`DAGRunner` protocol seam
(:mod:`umd.jobs.runner`), so the execution shape is identical whether driven by
the in-memory double or by Hatchet. No second scheduler exists anywhere in v1.

BUILD GATE (recording the pin decision, not fabricating it)
-----------------------------------------------------------
The DD explicitly treats the exact Hatchet release as a BUILD GATE — *"pinned
only after retry/cancel/restart shape tests"*. Those shape tests are run against
the :class:`InMemoryRunner`/``DurableDAGRunner`` seam in this plan (P1-S5). Until
they pass and a real Hatchet cluster is exercised, NO concrete release is pinned
and no live-Hatchet behavior is claimed. The adapter therefore:

* builds the Hatchet workflow **specs** purely from the in-repo DAG (testable,
  no live cluster);
* documents the exact real-Hatchet integration points (the ``client`` interface);
* and raises :class:`HatchetNotConfiguredError` whenever it would actually touch a
  live cluster — so a consumer can never accidentally rely on unfabricated,
  unpinned Hatchet results.
"""
# ruff: noqa: ARG002 - run_graph must match the DAGRunner protocol signature even
# when the live client is absent (the pin build-gate keeps these paths untestable).

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .dag import STAGE_DEPENDENCIES, STAGE_ORDER
from .runner import StageRunEvent, StageWorkRegistry


class HatchetNotConfiguredError(RuntimeError):
    """No live Hatchet client is configured.

    Raised on any code path that would submit to a real Hatchet cluster. This is
    the build-gate: the Hatchet release is not pinned until the retry/cancel/
    restart shape tests (run through the ``DAGRunner`` seam) pass.
    """

    def __init__(self, detail: str = "") -> None:
        message = (
            "Hatchet is the v1 runner but no live client is configured; the exact "
            "Hatchet release is a BUILD GATE (pinned only after retry/cancel/restart "
            "shape tests pass). Run these through the in-memory / DurableDAGRunner "
            "seam instead. " + detail
        )
        super().__init__(message.strip())


#: The stable (non-pinned) description of the runner contract Hatchet must satisfy.
#: A *pinned* release string is intentionally absent — see module docstring.
HATCHET_RUNNER_CONTRACT = {
    "role": "sole-v1-scheduler",
    "requirements": [
        "claim-before-side-effect  (UNIQUE idempotency_key is authority)",
        "effective-once completion (artifact refs + StageCompleted in one txn)",
        "bounded backoff for transient failures; quarantine for deterministic",
        "restart-resume: re-claim keys; completed dedupe, crashed resume",
        "drain/cancel in-flight work before activating a new DAG universe",
    ],
}


@dataclass
class HatchetWorkflowSpec:
    """A pure mapping of one stage to a Hatchet workflow (no live cluster)."""

    #: the canonical in-repository stage name.
    stage: str
    #: upstream stages this workflow depends on (Hatchet ``depends_on``).
    depends_on: list[str] = field(default_factory=list)
    #: evidence classes consumed (the DAG edge metadata).
    consumes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": f"umd-{self.stage.lower()}",
            "stage": self.stage,
            "depends_on": self.depends_on,
            "consumes": self.consumes,
        }


def build_hatchet_workflows(
    dependency_table: Mapping[str, tuple[tuple[str, str], ...]] | None = None,
) -> list[HatchetWorkflowSpec]:
    """Build one Hatchet workflow per in-repo stage (pure, topologically ordered).

    ``dependency_table`` defaults to the canonical ``STAGE_DEPENDENCIES``. Each
    workflow carries the upstream-stage dependencies and the evidence classes
    found in :mod:`umd.jobs.dag` — the same lineage the runner and the selective
    invalidator consume. This is the documented mapping used to *submit* to
    Hatchet once a release is pinned.
    """
    table = dependency_table or STAGE_DEPENDENCIES
    specs: list[HatchetWorkflowSpec] = []
    for stage in STAGE_ORDER:
        deps = table.get(stage, ())
        specs.append(
            HatchetWorkflowSpec(
                stage=stage,
                depends_on=[d for d, _c in deps],
                consumes=[c for _d, c in deps],
            )
        )
    return specs


class HatchetRunner:
    """:class:`DAGRunner` adapter over a real Hatchet client.

    The ``client`` is the real-Hatchet integration point (its REST/gRPC submit
    surface). It is **not** wired in v1 until the pin build-gate is resolved, so
    the default ``client=None`` path refuses to run rather than fabricate results.
    The pure workflow-spec construction (:meth:`build_workflows`) IS exercised by
    tests without any Hatchet dependency.
    """

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    def build_workflows(self) -> list[HatchetWorkflowSpec]:
        return build_hatchet_workflows()

    def run_graph(
        self,
        *,
        job_id: str,
        source_id: str | None,
        dag_universe: str,
        work_registry: StageWorkRegistry,
        stages: list[str],
    ) -> list[StageRunEvent]:
        if self._client is None:
            raise HatchetNotConfiguredError(
                f"cannot submit {job_id} (dag_universe={dag_universe}) to a live cluster"
            )
        # Integration point: for each stage, submit the mapped workflow with the
        # stage's manifest; the durable executor runs as the workflow's run-fn.
        # Not reachable until HATCHET pin gate resolves (no fabricated results).
        self._client.submit_workflow_run(  # pragma: no cover - live-only
            workflow_name="umd-dag", input={"job_id": job_id, "source_id": source_id}
        )
        return []


__all__ = [
    "HatchetNotConfiguredError",
    "HatchetWorkflowSpec",
    "HatchetRunner",
    "build_hatchet_workflows",
    "HATCHET_RUNNER_CONTRACT",
]
