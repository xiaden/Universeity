"""P3-S4: the documentation Python client example stays runnable against the API.

Loads and executes ``docs/examples/python_client.py`` — the maintained
public-contract example — against the real FastAPI app (via a live Postgres
ledger + OCFL store, just like ``test_api_contract``). This proves every curl
and Python example in ``docs/examples/`` is driven by the actual ``/v1``
contract and is not stale, while exercising the two consistency failure classes
(``transient-lag`` and ``rebuild-in-progress``) plus RFC 7807 handling.

The example itself uses only public, versioned ``/v1`` endpoints — no internal
storage/provider/ledger API. Projection-state transitions (rebuild / pause) are
staged here as the operator-side harness, exactly as described in the example
module docstring.
"""

from __future__ import annotations

import importlib.util
import pathlib
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from umd.api.app import create_app
from umd.config import AuthSettings, ConsistencySettings, RateLimitSettings, Settings
from umd.projections.base import ReplayDriver
from umd.projections.checkpoint import ProjectionCheckpoint, ProjectionCheckpointStore
from umd.projections.current import CurrentTierOneBuilder
from umd.projections.search import SearchProjectionBuilder

pytestmark = pytest.mark.postgres

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_EXAMPLE = _ROOT / "docs" / "examples" / "python_client.py"


def _load_example() -> SimpleNamespace:
    spec = importlib.util.spec_from_file_location("umd_docs_python_client", _EXAMPLE)
    assert spec is not None and spec.loader is not None, "could not load docs example"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return SimpleNamespace(
        PublicContractClient=module.PublicContractClient,
        run_demo=module.run_demo,
        ApiError=module.ApiError,
    )


def _client_settings() -> Settings:
    return Settings(
        auth=AuthSettings(api_keys=["write-key", "read-key"], write_keys=["write-key"]),
        rate_limit=RateLimitSettings(
            enabled=True, requests_per_window=10000, window_seconds=60.0, burst=100
        ),
        consistency=ConsistencySettings(lag_wait_multiplier=1, max_waiters=16),
        lag_budget_seconds=0.05,
    )


def _build(engine: sa.Engine, *, force_search_resume: bool = True) -> None:
    store = ProjectionCheckpointStore(engine)
    ReplayDriver(engine, store).run(CurrentTierOneBuilder(), wipe=True)
    ReplayDriver(engine, store).run(
        SearchProjectionBuilder(), wipe=True, force_resume=force_search_resume
    )


def test_docs_python_client_is_runnable_and_current(umd_db: sa.Engine, source_store) -> None:
    example = _load_example()
    app = create_app(
        engine=umd_db, source_store=source_store, settings=_client_settings(), runner="hermetic"
    )
    api = example.PublicContractClient(
        base_url="http://localhost:8080", app=app, api_key="write-key"
    )

    staged: list[str] = []

    def stage(name: str) -> None:
        staged.append(name)
        if name in ("projections_caught_up", "resume"):
            # Operator/rebuild path: bring both Tier-1 projections to the ledger tail.
            _build(umd_db)
        elif name == "projection_paused":
            # Operator/poison path: pin the projection as paused (authority rebuild).
            store = ProjectionCheckpointStore(umd_db)
            store.save(
                ProjectionCheckpoint("current_tier1", applied_seq=0).paused(
                    "docs example: projection paused to demonstrate the 503 contract", 0
                )
            )
        # "projections_behind" is intentionally a no-op: the projection stays
        # unbuilt so the token-bearing read observes transient lag.

    try:
        summary = example.run_demo(api, stage=stage)
    finally:
        api.close()

    # The example exercised both consistency classes and RFC 7807 handling, and
    # each consistency failure was staged (not fabricated in the client).
    assert summary["api_version"] == "v1"
    assert summary["transient_lag_503"] == "consistency_transient_lag"
    assert summary["rebuild_in_progress_503"] == "consistency_rebuild"
    assert summary["rfc7807"] == "not_found"
    assert "projections_behind" in staged
    assert "projections_caught_up" in staged
    assert "projection_paused" in staged
    assert "resume" in staged
    assert summary["semantic_authority"] == "tier0-ledger; projections never authoritative"
    assert summary["rerun_job"]  # selective rerun issued
