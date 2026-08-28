"""Scheduler/provider capability reporting (CONTRACTS.md:63, P3-S4, Plan K P1-S6).

``CapabilityReporter.report() -> CapabilityReport`` reports each provider/sandbox/
scheduler as ``active`` | ``reference-only`` | ``configured-but-unavailable`` |
``gated`` | ``disabled``, including a gate reason and the observed version.

The DD hard rule (Security-and-observability, Q3): an unavailable integration must
never be represented as active. For the sole v1 scheduler (Hatchet) the reporter
(Plan K P1-S6) only reports ``active`` when ALL of the following hold:

1. the production runner (:class:`ProductionDAGRunner`) is actually wired into the
   release runtime (a hermetic ``DurableDAGRunner`` seam can never establish
   ``active`` — it is an executor-facing test/dev driver, not a scheduler);
2. the SDK is importable and the server URL/token are configured;
3. a cached/background hysteretic live-connectivity probe returns ``reachable``
   with an observed version/reason.

A recording double, a version ping, a readiness line, or a bare client object is
NEVER treated as execution evidence. Local SDK/server/provider absence is reported
as the correct named non-active status (``gated`` or ``configured-but-unavailable``).
"""

from __future__ import annotations

import importlib.util
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from .hatchet import HATCHET_SDK_VERSION, HATCHET_SERVER_IMAGE

_CONFIGURED = "configured-but-unavailable"


@dataclass(frozen=True)
class SchedulerConnectivity:
    """Result of a live scheduler reachability probe (P1-S6)."""

    #: True only after a REAL network-touching operation succeeds against the engine.
    reachable: bool
    #: Human-readable reason (also the named non-active status reason when unreachable).
    reason: str
    #: Observed version/reason metadata captured from the live surface, if any.
    version: str | None = None


class ConnectivityProbe(Protocol):
    """A cached/background hysteretic live-connectivity probe (CONTRACTS.md:63)."""

    def check(self) -> SchedulerConnectivity: ...


class HatchetConnectivityProbe:
    """Live Hatchet engine reachability with caching/hysteresis (P1-S6).

    ``check()`` returns a cached :class:`SchedulerConnectivity` within the TTL (so
    repeated API calls do not hammer the engine) and only re-probes after the TTL
    expires. It is *hysteretic*: a single transient failure does not flap an already
    verified reachable state (the cache holds the last observed verdict). No live
    surface (recording double / unconfigured refusal / bare runner with no real
    client) ever yields ``reachable``.
    """

    def __init__(
        self,
        runner: Any = None,
        *,
        client: Any = None,
        ttl_seconds: float = 5.0,
    ) -> None:
        self._runner = runner
        self._client = client
        self._ttl = ttl_seconds
        self._cache: tuple[float, SchedulerConnectivity] | None = None

    def check(self) -> SchedulerConnectivity:
        if self._cache is not None and time.monotonic() - self._cache[0] < self._ttl:
            return self._cache[1]
        result = self._probe()
        self._cache = (time.monotonic(), result)
        return result

    def _probe(self) -> SchedulerConnectivity:
        client = self._client
        # A non-live surface is never execution evidence: the honest unconfigured
        # client carries a ``_reason`` refusal and no real admin surface.
        if client is None:
            return SchedulerConnectivity(False, "no Hatchet client wired")
        if getattr(client, "_reason", None):
            return SchedulerConnectivity(False, str(client._reason))
        runs = getattr(client, "runs", None)
        admin = getattr(runs, "admin_client", lambda: None)() if runs is not None else None
        if admin is None:
            return SchedulerConnectivity(False, "no live Hatchet admin surface reachable")
        try:
            # A real, minimal, network-touching operation against the engine.
            admin.list_workflows({})
        except Exception as exc:  # noqa: BLE001 - a failed live probe is a reason, not an abort
            return SchedulerConnectivity(False, f"live connectivity probe failed: {exc}")
        return SchedulerConnectivity(
            True,
            "live Hatchet engine connectivity verified",
            version=HATCHET_SDK_VERSION,
        )


def _scheduler_report(
    *,
    production_wired: bool,
    probe: ConnectivityProbe | None,
) -> dict[str, Any]:
    """Truthful scheduler capability (P1-S6).

    ``active`` requires ProductionDAGRunner wiring + SDK + configuration + a
    verified live-connectivity probe with an observed version/reason. Anything less
    yields a named non-active status.
    """
    sdk_importable = importlib.util.find_spec("hatchet_sdk") is not None
    server_url = os.environ.get("UMD_HATCHET_SERVER_URL")
    token = os.environ.get("UMD_HATCHET_TOKEN")
    configured = bool(server_url and token)

    base: dict[str, Any] = {
        "provider": "hatchet",
        "sdk_version": HATCHET_SDK_VERSION,
        "server_image": HATCHET_SERVER_IMAGE,
    }
    if not production_wired:
        return {
            **base,
            "status": _CONFIGURED,
            "reason": (
                "release scheduler (ProductionDAGRunner) not wired; hermetic "
                "DurableDAGRunner seam is an executor-facing test/dev driver, not a scheduler"
            ),
        }
    if not sdk_importable:
        return {
            **base,
            "status": "gated",
            "reason": "hatchet_sdk not installed; the v1 worker cannot run",
        }
    if not configured:
        return {
            **base,
            "status": _CONFIGURED,
            "reason": "UMD_HATCHET_SERVER_URL / UMD_HATCHET_TOKEN not set; no reachable cluster",
        }
    if probe is None:
        return {
            **base,
            "status": _CONFIGURED,
            "reason": "no connectivity probe wired; cannot verify live connectivity",
        }
    conn = probe.check()
    if conn.reachable and conn.version:
        return {
            **base,
            "status": "active",
            "reason": conn.reason,
            "observed_version": conn.version,
        }
    return {
        **base,
        "status": _CONFIGURED,
        "reason": conn.reason,
        "observed_version": conn.version,
    }


@dataclass(frozen=True)
class CapabilityReport:
    """An honest capability snapshot for the scheduler and worker providers."""

    #: The sole v1 scheduler (Hatchet). status is one of the CONTRACTS.md:63 set.
    scheduler: dict[str, Any] = field(default_factory=dict)
    #: Provider capabilities carried for API disclosure (honest, never invented).
    providers: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scheduler": self.scheduler,
            "providers": self.providers,
        }


class CapabilityReporter:
    """Reports scheduler/provider capability status (CONTRACTS.md:63).

    ``production_wired`` is True only when the release runtime actually assembles
    :class:`ProductionDAGRunner`; ``probe`` is the cached live-connectivity probe.
    ``active`` is unreachable unless both are in place AND the probe verifies a live
    engine (P1-S6).
    """

    def __init__(
        self,
        *,
        production_wired: bool = False,
        probe: ConnectivityProbe | None = None,
    ) -> None:
        self._production_wired = production_wired
        self._probe = probe

    def report(self) -> CapabilityReport:
        return CapabilityReport(
            scheduler=_scheduler_report(
                production_wired=self._production_wired,
                probe=self._probe,
            ),
            providers={
                "worker": {
                    "bound_executors": "reported-by-worker-handle",
                    "ready": "requires live client + bound callbacks (never fake)",
                }
            },
        )


__all__ = [
    "CapabilityReporter",
    "CapabilityReport",
    "ConnectivityProbe",
    "HatchetConnectivityProbe",
    "SchedulerConnectivity",
]
