"""Scheduler/provider capability reporting (CONTRACTS.md:63, P3-S4).

``CapabilityReporter.report() -> CapabilityReport`` reports each provider/sandbox/
scheduler as ``active`` | ``reference-only`` | ``configured-but-unavailable`` |
``gated`` | ``disabled``, including a gate reason and the observed version.

The DD hard rule (Security-and-observability, Q3): an unavailable integration must
never be represented as active. With no live Hatchet cluster reachable, the sole
v1 scheduler is reported honestly — never ``active``. The probe reads the current
process environment (env vars + importability), so it stays truthful in every
deployment:

* SDK absent  -> ``gated`` (reason: hatchet_sdk not installed; worker cannot run).
* SDK present + no server env -> ``configured-but-unavailable``.
* SDK present + server env -> ``configured-but-unavailable`` until Plan J proves
  live connectivity — a reachable client is the only thing that flips it to
  ``active``.
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass, field
from typing import Any

from .hatchet import HATCHET_SDK_VERSION, HATCHET_SERVER_IMAGE


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


def _scheduler_report() -> dict[str, Any]:
    """Truthful scheduler capability from the current process environment.

    The observed version is the pinned candidate pair (P2-S1); it is reported
    alongside the status and gate reason so an operator can see exactly what is
    installed/pinned and why it is not ``active`` locally.
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
    if not sdk_importable:
        return {
            **base,
            "status": "gated",
            "reason": "hatchet_sdk not installed; the v1 worker cannot run",
        }
    if not configured:
        return {
            **base,
            "status": "configured-but-unavailable",
            "reason": "UMD_HATCHET_SERVER_URL / UMD_HATCHET_TOKEN not set; no reachable cluster",
        }
    # SDK + env present, but no live connectivity verified in this environment.
    # Only a real client connection (Plan J live validation) flips this to active.
    return {
        **base,
        "status": "configured-but-unavailable",
        "reason": (
            "SDK installed and env present but no live cluster connectivity verified "
            "in this environment (Plan J live validation required)"
        ),
    }


class CapabilityReporter:
    """Reports scheduler/provider capability status (CONTRACTS.md:63)."""

    def report(self) -> CapabilityReport:
        return CapabilityReport(
            scheduler=_scheduler_report(),
            providers={
                "worker": {
                    "bound_executors": "reported-by-worker-handle",
                    "ready": "requires live client + bound callbacks (never fake)",
                }
            },
        )


__all__ = ["CapabilityReporter", "CapabilityReport"]
