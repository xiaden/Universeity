"""Shared FastAPI dependencies and the app-level service context (Phase 3).

An :class:`AppContext` bundles every service the routers need, constructed once by
the app factory and stored on ``app.state``. The ``get_context`` dependency reads
it from ``request.app.state`` so routers never re-instantiate services and never
open their own engine connections.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from fastapi import Depends, Request

from umd.api.auth import Principal, authenticate, require_write
from umd.api.ratelimit import RateLimitGuard
from umd.config import Settings


@dataclass
class AppContext:
    """The assembled runtime context for the REST API."""

    settings: Settings
    engine: Any
    commands: Any
    ledger: Any
    query: Any
    search: Any
    question: Any
    audit: Any
    jobs: Any
    segments: Any
    evidence: Any
    sources: Any
    memberships: Any
    source_store: Any
    #: Phase-1 reversible entity resolver (ledger append + rebind + quarantine).
    resolver: Any = None
    #: Consistency guard implementing read-your-writes token handling.
    consistency: Any = None
    #: Projection freshness reader (untokened reads expose freshness metadata).
    freshness: Any = None
    #: The production stage-work registry (never ``{}``) used by submit / rerun /
    #: retry / invalidate (P3-S3). Composed once by the app factory from the
    #: production runtime; routers never pass an empty registry.
    work_registry: Any = None
    log: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


def serialize_audits(records: Any) -> list[dict[str, Any]]:
    """Convert :class:`JobAuditRecord` objects to JSON-safe dicts (P3-S4).

    The jobs ``events`` path returns durable ``JobAuditRecord`` rows; they are not
    natively JSON-serializable, so endpoint boundaries flatten them into dicts.
    ``records`` may also be an empty list (no-op).
    """
    out: list[dict[str, Any]] = []
    for rec in records or []:
        if isinstance(rec, dict):
            out.append(rec)
            continue
        created = getattr(rec, "created_at", None)
        out.append(
            {
                "id": getattr(rec, "id", None),
                "job_id": getattr(rec, "job_id", None),
                "stage": getattr(rec, "stage_name", None),
                "action": getattr(rec, "action", None),
                "attempt": getattr(rec, "attempt", None),
                "status": getattr(rec, "status", None),
                "created_at": created.isoformat() if created is not None else None,
            }
        )
    return out


def get_context(request: Request) -> AppContext:
    """Dependency: the :class:`AppContext` bound to the current app."""
    ctx = getattr(request.app.state, "ctx", None)
    if ctx is None:
        from umd.api.errors import ApiError

        raise ApiError("API context not initialised", status=500, code="app_uninitialised")
    return cast(AppContext, ctx)


def get_principal(request: Request, context: AppContext = Depends(get_context)) -> Principal:
    """Authenticate the request against the app's auth settings."""
    return authenticate(request, context.settings.auth)


def get_write_principal(
    principal: Principal = Depends(get_principal),
) -> Principal:
    """Authenticate AND authorize a mutating route."""
    return require_write(principal)


def get_rate_guard(context: AppContext = Depends(get_context)) -> RateLimitGuard:
    return cast(RateLimitGuard, context.extra["rate_guard"])


def enforce_rate_limit(
    request: Request,
    principal: Principal = Depends(get_principal),
    guard: RateLimitGuard = Depends(get_rate_guard),
) -> None:
    """Apply per-key/IP rate limiting to a request."""
    guard.check(client_ip=request.client.host if request.client else "unknown", key=principal.key)


__all__ = [
    "AppContext",
    "get_context",
    "get_principal",
    "get_write_principal",
    "get_rate_guard",
    "enforce_rate_limit",
]
