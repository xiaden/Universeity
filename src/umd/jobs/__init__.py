"""Jobs: in-repository stage DAG/lineage, durable execution, job commands, runner.

Phase-B (P1) adds the canonical single lineage (:mod:`umd.jobs.dag`), deterministic
stage manifests/idempotency keys (:mod:`umd.jobs.manifest`), claim-before-side-
effect durable execution (:mod:`umd.jobs.stage_execution`), the job aggregate +
DAG runner (:mod:`umd.jobs.runner`), the Hatchet adapter / build-gate pin seam
(:mod:`umd.jobs.hatchet`), and the DAG-version drain policy (:mod:`umd.jobs.drain`).
Hatchet is the ONLY v1 scheduler; there is no second scheduler anywhere.
"""

from .dag import (
    MODALITY_BRANCHES,
    STAGE_DEPENDENCIES,
    STAGE_DEPENDENTS,
    STAGE_ORDER,
    StageDef,
    stage_dependency,
    stages,
)
from .drain import DagUniverseGate, DrainResult, SimpleUniverseGate, restart_policy
from .hatchet import (
    HATCHET_RUNNER_CONTRACT,
    HatchetNotConfiguredError,
    HatchetRunner,
    HatchetWorkflowSpec,
    build_hatchet_workflows,
)
from .invalidation import InvalidationPlanner, StageTarget, StageTargets
from .job import InMemoryJobStore, JobRecord, JobStatus, JobStore, StageState
from .manifest import (
    StageManifest,
    build_dag_universe,
    deterministic_stage_idempotency_key,
)
from .runner import DAGRunner, DurableDAGRunner, StageRunEvent, initial_stages

__all__ = [
    "MODALITY_BRANCHES",
    "STAGE_DEPENDENCIES",
    "STAGE_DEPENDENTS",
    "STAGE_ORDER",
    "StageDef",
    "stage_dependency",
    "stages",
    "DagUniverseGate",
    "DrainResult",
    "SimpleUniverseGate",
    "restart_policy",
    "HATCHET_RUNNER_CONTRACT",
    "HatchetNotConfiguredError",
    "HatchetRunner",
    "HatchetWorkflowSpec",
    "build_hatchet_workflows",
    "InvalidationPlanner",
    "StageTarget",
    "StageTargets",
    "InMemoryJobStore",
    "JobRecord",
    "JobStatus",
    "JobStore",
    "StageState",
    "StageManifest",
    "build_dag_universe",
    "deterministic_stage_idempotency_key",
    "DAGRunner",
    "DurableDAGRunner",
    "StageRunEvent",
    "initial_stages",
]
