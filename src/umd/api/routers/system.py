"""Health / readiness / capabilities / version boundaries (P3-S4).

Honest disclosure: health reports the freshness/lag/pause state of the Tier-1
projections that back queries, /ready degrades (503) while a projection is being
rebuilt, /capabilities reuses the sandbox capability report (plus enabled
modalities/providers/limits), and /version exposes the API + schema/DAG versions.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from umd.alignment.align import alignment_capability_report
from umd.api.deps import AppContext, enforce_rate_limit, get_context
from umd.api.errors import ConsistencyLagError
from umd.api.schemas import (
    CapabilitiesResponse,
    HealthComponent,
    HealthResponse,
    VersionResponse,
)
from umd.jobs.capability import CapabilityReporter
from umd.observability.metrics import METRICS
from umd.observability.tracing import otel_export_active
from umd.projections.embedder import embed_text
from umd.projections.vector import ExactVectorIndex, PgHNSWIndex
from umd.resolution.linkage import linkage_capability_report
from umd.security.capabilities import capability_report

router = APIRouter(prefix="/v1", tags=["system"], dependencies=[Depends(enforce_rate_limit)])


def _projection_components(ctx: AppContext) -> list[HealthComponent]:
    comps: list[HealthComponent] = []
    for name, guard_name in (("current_tier1", "query_guard"), ("search", "search_guard")):
        guard = ctx.consistency if guard_name == "query_guard" else ctx.extra.get("search_guard")
        if guard is None:
            continue
        snap = guard.freshness.snapshot()
        comps.append(
            HealthComponent(
                name=f"projection:{name}",
                status="ok" if snap.status == "fresh" else "degraded",
                detail=snap.to_meta(),
            )
        )
    return comps


def _scheduler_component() -> HealthComponent:
    """Honest scheduler/provider capability as a health component (P3-S4).

    The sole v1 scheduler is ``degraded`` whenever it is not ``active`` (absent
    SDK / no live cluster), matching the DD rule that unavailable integrations are
    never represented as active. Readiness stays projection-driven (see
    :func:`readiness`), so this surfaces capability without faking readiness.
    """
    sched = CapabilityReporter().report().scheduler
    detail = {
        "provider": sched.get("provider"),
        "status": sched.get("status"),
        "reason": sched.get("reason"),
        "sdk_version": sched.get("sdk_version"),
        "server_image": sched.get("server_image"),
    }
    return HealthComponent(
        name="scheduler",
        status="ok" if sched.get("status") == "active" else "degraded",
        detail=detail,
    )


@router.get("/health", response_model=HealthResponse)
def health(ctx: AppContext = Depends(get_context)) -> HealthResponse:
    components = _projection_components(ctx) + [_scheduler_component()]
    degraded = any(c.status != "ok" for c in components)
    return HealthResponse(status="degraded" if degraded else "ok", components=components)


@router.get("/ready")
def readiness(ctx: AppContext = Depends(get_context)) -> dict[str, Any]:
    components = _projection_components(ctx)
    for c in components:
        if c.detail.get("status") == "rebuild-in-progress":
            raise ConsistencyLagError(
                "projection rebuild in progress; not ready",
                code="not_ready",
                retryable=True,
                extra={
                    "x-consistency": "rebuild-in-progress",
                    "retry_after": ctx.settings.consistency.rebuild_retry_after,
                },
            )
    return {
        "status": "ready",
        "components": [c.model_dump() for c in components],
        "scheduler": CapabilityReporter().report().scheduler,
    }


def _vector_capability_report(engine: Any) -> dict[str, Any]:
    """Honest vector capability disclosure (exact fallback active; pgvector-HNSW gated)."""
    return {
        "vector": {
            "active_provider": "exact-fallback-in-process",
            "providers": {
                "exact_fallback": ExactVectorIndex(engine).describe(),
                "pgvector_hnsw": PgHNSWIndex(engine).describe(),
            },
        },
        "embedder": {
            "provider": "umd-deterministic-local",
            "dim": len(embed_text("x")),
        },
    }


@router.get("/capabilities", response_model=CapabilitiesResponse)
def capabilities(ctx: AppContext = Depends(get_context)) -> CapabilitiesResponse:
    report = capability_report()
    report["modalities_enabled"] = ["txt", "markdown", "epub", "pdf", "audio", "video", "subtitle"]
    # Honest capability disclosure (P3-S4): surface the gated linkage/alignment/vector
    # providers so /v1/capabilities reports them as gated/inactive where they are not
    # installed, alongside the active reference/builtin providers. Nothing is
    # fabricated as active.
    report.update(linkage_capability_report())
    report.update(alignment_capability_report())
    report.update(_vector_capability_report(ctx.engine))
    report["providers"] = ["builtin"]
    report["sandbox_posture"] = report.get("os_isolation_active", False)
    report["query_max_depth"] = ctx.settings.query_cost.max_depth
    report["query_max_limit"] = ctx.settings.query_cost.max_limit
    report["relationships_bounded"] = True
    report["semantic_authority"] = "tier0-ledger; projections never authoritative"
    # Honest scheduler/provider capability (P3-S4): never represented as active
    # without a live reachable cluster.
    report["scheduler"] = CapabilityReporter().report().scheduler
    return CapabilitiesResponse(capabilities=report)


@router.get("/metrics")
def metrics() -> dict[str, Any]:
    """Expose the in-process metric registry snapshot (P1-S1).

    ``otel_export_active`` reports the real gate condition (true only when
    ``UMD_OTEL_ENABLED`` AND ``opentelemetry`` is importable), never a fabricated
    value — it stays honest False when OTel is absent.
    """
    export_active = otel_export_active()
    return {
        "service": "universeity-umd",
        "metrics": METRICS.snapshot(),
        "otel_export_active": export_active,
        "otel_gate": (
            "active" if export_active else "UMD_OTEL_ENABLED + opentelemetry-sdk required"
        ),
    }


@router.get("/version", response_model=VersionResponse)
def version(ctx: AppContext = Depends(get_context)) -> VersionResponse:
    return VersionResponse(
        service="universeity-umd",
        api_version=ctx.settings.api.version,
        contract_version=ctx.settings.api.contract_version,
        dag_universe="base",
        schema_version=1,
    )
