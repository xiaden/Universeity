"""Static guardrails that keep the public-boundary acceptance tests honest (P1-S5).

These guardrails PASS NOW -- they are the static half of the spec, independent of
whether the production scheduler/worker path is live.

(a) The acceptance-test module ``tests/test_api_boundary_e2e.py`` must communicate
    ONLY through the versioned HTTP boundary in its scenario path: no direct
    modality/service/repository/ledger/projection-builder imports, no manual
    projection rebuild, no ``ProjectionBuilder`` / ``ReplayDriver`` /
    ``SemanticLedger`` / ``SegmentRegistry`` (or any internal service) usage.
(b) The scenario must declare and enforce the P1-S5 metadata contract: every
    evidence/semantic answer carries provenance, confidence/uncertainty,
    generated-by, and capability metadata.

The runtime half is the gated scenario in ``tests/test_api_boundary_e2e.py`` itself.
"""

from __future__ import annotations

import ast
from pathlib import Path

SCENARIO = Path(__file__).parent / "test_api_boundary_e2e.py"

# The only ``umd.*`` modules the scenario may import to bootstrap the ASGI app.
_ALLOWED_UMD_IMPORTS = ("umd.api.app", "umd.config")

# Internal service / projection symbols the scenario must never reference directly
# (imported or used as bare names) -- these are exactly the boundary the plan forbids
# the acceptance test from reaching past.
_FORBIDDEN_SYMBOLS = frozenset(
    {
        "ProjectionBuilder",
        "ReplayDriver",
        "SemanticLedger",
        "SegmentRegistry",
        "CurrentTierOneBuilder",
        "SearchProjectionBuilder",
        "InvalidationPlanner",
        "StageRunRepository",
        "JobRunAudit",
        "SemanticCommandService",
        "SourceMembershipService",
        "PostgresEvidenceRepository",
        "PostgresSegmentStore",
        "PostgresSourceRepository",
        "PostgresQuarantine",
        "PostgresMentionRepository",
        "PostgresSplitEnumerator",
        "Resolver",
        "QueryService",
        "QuestionService",
        "SearchService",
        "AuditService",
        "MentionService",
        "SourceStore",
        "LocatorResolver",
    }
)

# P1-S5: the metadata contract every evidence/semantic answer must carry.
_REQUIRED_METADATA = ("provenance", "confidence", "generated_by", "capabilities")


def _scenario_tree() -> ast.Module:
    return ast.parse(SCENARIO.read_text(encoding="utf-8"), filename=str(SCENARIO))


def _is_allowed(module: str) -> bool:
    return module in _ALLOWED_UMD_IMPORTS or any(
        module.startswith(m + ".") for m in _ALLOWED_UMD_IMPORTS
    )


# ---------------------------------------------------------------------------
# (a) Boundary-purity: the scenario is HTTP-only, no internal services
# ---------------------------------------------------------------------------


def test_scenario_imports_only_boundary_bootstrap() -> None:
    """The scenario file imports no ``umd.*`` internal-service module."""
    tree = _scenario_tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "umd" or node.module.startswith("umd."):
                assert _is_allowed(node.module), (
                    f"forbidden internal-service import in scenario: "
                    f"`from {node.module} import ...`"
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name == "umd" or name.startswith("umd."):
                    assert _is_allowed(name), f"forbidden umd import in scenario: `import {name}`"


def test_scenario_no_direct_projection_or_ledger_usage() -> None:
    """The scenario never references projection builders, the ledger, the segment
    registry, or any internal service by name."""
    tree = _scenario_tree()
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    for sym in _FORBIDDEN_SYMBOLS:
        assert sym not in names, f"scenario references forbidden internal symbol {sym!r}"


def test_scenario_does_not_rebuild_projections() -> None:
    """The scenario never calls a wipe/replay builder (manual projection rebuild)."""
    src = SCENARIO.read_text(encoding="utf-8")
    for marker in ("wipe=True", "ReplayDriver(", ".run(builder", "force_resume="):
        assert marker not in src, f"scenario performs a manual projection rebuild ({marker!r})"


# ---------------------------------------------------------------------------
# (b) P1-S5 metadata contract is declared and enforced by the scenario
# ---------------------------------------------------------------------------


def test_scenario_declares_and_enforces_metadata_contract() -> None:
    """The scenario declares the exact P1-S5 metadata keys and enforces the contract
    on the evidence/semantic answers it inspects."""
    src = SCENARIO.read_text(encoding="utf-8")
    tree = _scenario_tree()

    declared: set[str] | None = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "_METADATA_KEYS" for t in node.targets)
            and isinstance(node.value, ast.Tuple)
        ):
            declared = {
                e.value
                for e in node.value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            }
    assert declared is not None, "scenario must declare `_METADATA_KEYS`"
    for required in _REQUIRED_METADATA:
        assert required in declared, f"scenario metadata contract missing required key {required!r}"

    # It enforces the contract on the answers it inspects (evidence + semantic answer).
    assert src.count("_assert_metadata_contract(") >= 2, (
        "scenario must enforce the metadata contract on every evidence/semantic answer"
    )
