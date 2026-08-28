"""Static guardrails that keep the public-boundary acceptance tests honest (P4-S1).

These guardrails PASS NOW -- they are the static half of the spec, independent of
whether the production scheduler/worker path is live.

(a) The live acceptance-test module ``tests/test_api_boundary_e2e.py`` must
    communicate ONLY through the versioned HTTP boundary against the RUNNING
    service: NO ``umd.*`` imports at all, NO ``TestClient`` / ``create_app``, NO
    direct modality/service/repository/ledger/projection-builder usage, NO manual
    projection rebuild, and NO in-process app construction anywhere in the
    scenario. In-process ``TestClient``/``create_app`` and direct repositories/
    ledgers/projection builders live ONLY in explicitly hermetic tests (e.g.
    ``tests/test_phase4_heterogeneous_ingestion.py`` and the postgres-seam tests
    in ``tests/test_hatchet_live.py``), never in the live acceptance path.
(b) The scenario must declare and enforce the P1-S5/P4-S2 metadata contract:
    every evidence/semantic answer carries provenance, confidence/uncertainty,
    generated-by, and capability metadata.
(c) The live acceptance path must NOT self-skip on capability checks: it skips
    only on an unreachable running service (named local gate) and runs fully on
    the protected/main docker-e2e job.

The runtime half is the gated scenario in ``tests/test_api_boundary_e2e.py`` itself.
"""

from __future__ import annotations

import ast
from pathlib import Path

SCENARIO = Path(__file__).parent / "test_api_boundary_e2e.py"

# The live acceptance path must import NO ``umd.*`` module whatsoever. It talks to
# the running service over external HTTP only.
_ALLOWED_UMD_IMPORTS: tuple[str, ...] = ()

# Internal service / projection symbols the scenario must never reference directly
# (imported or used as bare names) -- these are exactly the boundary the plan forbids
# the acceptance test from reaching past. ``TestClient`` / ``create_app`` are
# explicitly forbidden too: the live path must never build an in-process app.
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
        "TestClient",
        "create_app",
        "app_factory",
    }
)

# P1-S5/P4-S2: the metadata contract every evidence/semantic answer must carry.
_REQUIRED_METADATA = ("provenance", "confidence", "generated_by", "capabilities")


def _scenario_tree() -> ast.Module:
    return ast.parse(SCENARIO.read_text(encoding="utf-8"), filename=str(SCENARIO))


def _is_allowed(module: str) -> bool:
    return module in _ALLOWED_UMD_IMPORTS or any(
        module.startswith(m + ".") for m in _ALLOWED_UMD_IMPORTS
    )


# ---------------------------------------------------------------------------
# (a) Boundary-purity: the live scenario is HTTP-only, no internal services
# ---------------------------------------------------------------------------


def test_scenario_imports_no_internal_umd_module() -> None:
    """The live scenario file imports NO ``umd.*`` module at all."""
    tree = _scenario_tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "umd" or node.module.startswith("umd."):
                assert _is_allowed(node.module), (
                    f"forbidden internal-service import in live scenario: "
                    f"`from {node.module} import ...`"
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name == "umd" or name.startswith("umd."):
                    assert _is_allowed(name), (
                        f"forbidden umd import in live scenario: `import {name}`"
                    )


def test_scenario_no_direct_projection_or_ledger_usage() -> None:
    """The live scenario never references projection builders, the ledger, the segment
    registry, an internal service, ``TestClient``, or ``create_app`` by name."""
    tree = _scenario_tree()
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    for sym in _FORBIDDEN_SYMBOLS:
        assert sym not in names, f"live scenario references forbidden internal symbol {sym!r}"


def test_scenario_does_not_rebuild_projections() -> None:
    """The live scenario never calls a wipe/replay builder (manual projection rebuild)."""
    src = SCENARIO.read_text(encoding="utf-8")
    for marker in ("wipe=True", "ReplayDriver(", ".run(builder", "force_resume="):
        assert marker not in src, f"live scenario performs a manual projection rebuild ({marker!r})"


def test_scenario_uses_external_http_client_only() -> None:
    """The live scenario drives the running service over an HTTP client bound to a
    base URL; it never builds an in-process ASGI app or TestClient."""
    src = SCENARIO.read_text(encoding="utf-8")
    # It declares a base URL for the running service.
    assert "UMD_API_BASE_URL" in src, "live scenario must read the running service base URL"
    assert "httpx.Client" in src, "live scenario must use an external HTTP client"
    # No TestClient / create_app anywhere (belt-and-braces beyond symbol check).
    assert "TestClient" not in src
    assert "create_app" not in src
    # It must not skip on a capability self-check; the only skip is the reachable-service gate.
    # Strip metadata-contract declarations (which legitimately name "capabilities") and
    # the capability probe, leaving only a hypothetical skip gate to be rejected.
    stripped = (
        src.replace("PUBLIC_PROBES", "")
        .replace("/v1/capabilities", "")
        .replace("def _token_read_never_stale", "")
        .replace("def _assert_metadata_contract", "")
        .replace('"generated_by", "capabilities"', "")
    )
    assert "capabilities" not in stripped, "live scenario must not self-skip on capability checks"
    # It probes the running service's public surface (health/ready/capabilities/version).
    assert "/v1/health" in src and "/v1/ready" in src
    assert "/v1/capabilities" in src and "/v1/version" in src


# ---------------------------------------------------------------------------
# (b) P1-S5/P4-S2 metadata contract is declared and enforced by the scenario
# ---------------------------------------------------------------------------


def test_scenario_declares_and_enforces_metadata_contract() -> None:
    """The scenario declares the exact metadata keys and enforces the contract
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


# ---------------------------------------------------------------------------
# (c) The live acceptance path must not self-skip on capability checks
# ---------------------------------------------------------------------------


def test_scenario_runs_against_real_stack_not_capability_skip() -> None:
    """The live scenario must run against the real stack. It never consults a
    capability/scheduler status to decide whether to run; it only gates on the
    running service being reachable at ``UMD_API_BASE_URL``."""
    src = SCENARIO.read_text(encoding="utf-8")
    assert "pytest.skip" in src, "live scenario must gate on the running service (named local gate)"
    # The skip reason is reachability, never scheduler/capability state.
    assert "not reachable" in src, "live scenario skip must be a reachability gate"
    assert "scheduler" not in src.lower() or "_scheduler" not in src
    # Every scenario test is exercised against the live service (no production-path gate).
    for probe in ("/v1/health", "/v1/ready", "/v1/capabilities", "/v1/version"):
        assert probe in src, f"live scenario must probe {probe} against the running service"
