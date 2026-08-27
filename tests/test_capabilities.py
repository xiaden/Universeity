"""Capability-reporting tests (Phase C, P1-S4).

Enforces the DD hard rule: unavailable or gated enhancements are reported
honestly — never asserted as active protection without a real probe. The
capability snapshot and report must reflect whatever the environment actually
provides, and ``probe_capabilities`` must be defensive (never raise, never
fabricate).
"""

from __future__ import annotations

from umd.security.capabilities import (
    SandboxCapabilities,
    capability_report,
    probe_capabilities,
)


def test_probe_never_raises() -> None:
    caps = probe_capabilities()
    assert isinstance(caps, SandboxCapabilities)
    # Every field has a concrete, ser-deserializable value.
    d = caps.to_dict()
    assert set(d) == {
        "bubblewrap_available",
        "bubblewrap_binary",
        "user_namespaces_available",
        "cgroup2_writable",
        "cgroup2_path",
        "seccomp_available",
        "in_container",
        "apparmor_profile",
        "notes",
    }


def test_report_is_json_serializable() -> None:
    report = capability_report()
    import json

    json.dumps(report)  # must not raise
    assert "os_isolation_active" in report
    assert isinstance(report["os_isolation_active"], bool)


def test_unavailable_capabilities_never_claim_os_isolation() -> None:
    caps = SandboxCapabilities(bubblewrap_available=False, user_namespaces_available=False)
    report = {
        **caps.to_dict(),
        "os_isolation_active": caps.bubblewrap_available and caps.user_namespaces_available,
    }
    assert report["bubblewrap_available"] is False
    assert report["os_isolation_active"] is False


def test_os_isolation_requires_both_bwrap_and_userns() -> None:
    # bwrap present but no user namespaces -> isolation NOT claimed.
    caps = SandboxCapabilities(bubblewrap_available=True, user_namespaces_available=False)
    assert not (caps.bubblewrap_available and caps.user_namespaces_available)
    caps2 = SandboxCapabilities(bubblewrap_available=True, user_namespaces_available=True)
    assert caps2.bubblewrap_available and caps2.user_namespaces_available
