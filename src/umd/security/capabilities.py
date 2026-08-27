"""Security-boundary capability introspection (Phase C, P1-S1).

Probes the *current process environment* for which OS-level sandboxing /
isolation layers are genuinely available and active, and exposes them as an
honest, reportable :class:`SandboxCapabilities` snapshot.

The DD hard rule (Security and observability and Q3) is that unvalidated
sandlock / OS-isolation must never be presented as *shipped* protection. This
module exists so the rest of the sandbox boundary can make that distinction
concretely: every capability is probed for real (binary present + functional)
before it is reported ``available``; anything that cannot be validated is
reported ``available=False`` and the caller falls back to the bounded-failure
runner *without* claiming OS isolation.

The first-class bare-metal/VM posture is bubblewrap + the required Ubuntu
profile. Container postures are conditional on user namespaces / capabilities
and never ``--privileged``. This module does not install anything — it reports
what the environment already provides.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SandboxCapabilities:
    """An honest, runtime-probed snapshot of the OS-isolation capabilities.

    A capability is ``available`` only after a real probe succeeded in this
    environment; ``False`` means it is NOT active and must not be reported as
    protection.
    """

    #: bubblewrap binary present *and* functional (``bwrap --version`` exits 0).
    bubblewrap_available: bool = False
    bubblewrap_binary: str | None = None
    #: Kernel/container support for unprivileged user namespaces (Linux).
    user_namespaces_available: bool = False
    #: A writable cgroup v2 hierarchy is available for memory/pid accounting.
    cgroup2_writable: bool = False
    cgroup2_path: str | None = None
    #: seccomp filter support is reportable (kernel + usable via the runner).
    seccomp_available: bool = False
    #: Whether the current process runs inside a container (conditional posture).
    in_container: bool = False
    #: An active AppArmor profile name, if any (bare-metal Ubuntu posture).
    apparmor_profile: str | None = None
    #: Extra diagnostic notes (which probe failed, expected-but-absent tools).
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "bubblewrap_available": self.bubblewrap_available,
            "bubblewrap_binary": self.bubblewrap_binary,
            "user_namespaces_available": self.user_namespaces_available,
            "cgroup2_writable": self.cgroup2_writable,
            "cgroup2_path": self.cgroup2_path,
            "seccomp_available": self.seccomp_available,
            "in_container": self.in_container,
            "apparmor_profile": self.apparmor_profile,
            "notes": list(self.notes),
        }


def _bwrap_probe() -> tuple[bool, str | None, str | None]:
    """Return ``(available, binary_path, note)`` for bubblewrap."""
    binary = shutil.which("bwrap")
    if binary is None:
        return False, None, "bwrap binary not on PATH; OS-isolation activation is GATED"
    try:
        # Gated, bounded probe: `bwrap --version` must exit 0 with our exact
        # binary; a failure means bwrap cannot be validated in this environment.
        proc = subprocess.run(  # noqa: S603 - fixed allowlisted binary from which()
            [binary, "--version"],
            capture_output=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False, binary, "bwrap present but did not validate (probe failed)"
    if proc.returncode != 0:
        return False, binary, f"bwrap --version exited {proc.returncode}"
    return True, binary, None


def _userns_probe() -> bool:
    """Best-effort check for unprivileged user namespaces (Linux)."""
    try:
        with open("/proc/sys/kernel/unprivileged_userns_clone", encoding="utf-8") as f:
            return f.read().strip() == "1"
    except OSError:
        # On kernels/distros where the knob is absent, default to pessimism:
        # do not claim userns support unless we can confirm it.
        return False


def _cgroup2_probe() -> tuple[bool, str | None]:
    """Probe a writable cgroup v2 hierarchy (``/sys/fs/cgroup``)."""
    path = "/sys/fs/cgroup"
    # cgroup v2 is identifiable by the presence of ``cgroup.controllers``.
    if not os.path.isfile(os.path.join(path, "cgroup.controllers")):
        return False, None
    # We only claim writable when the current process can create a leaf cgroup.
    probe_dir = os.path.join(path, "umd_probe")
    try:
        os.makedirs(probe_dir, exist_ok=False)
        os.rmdir(probe_dir)
        return True, path
    except OSError:
        return False, path


def _seccomp_probe() -> bool:
    """Report seccomp availability from the kernel config when readable."""
    try:
        with open("/proc/config.gz", "rb") as _f:  # not present on many systems
            return False
    except OSError:
        pass
    # seccomp is universally available on modern Linux but proxied through the
    # runner only when an explicit seccomp policy is applied; default pessimistic.
    return False


def _container_probe() -> bool:
    """Detect a containerized process (conditional container posture)."""
    if os.path.exists("/.dockerenv"):
        return True
    if os.path.exists("/run/.containerenv"):
        return True
    try:
        with open("/proc/self/cgroup", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return False
    return any(marker in content for marker in ("docker", "kubepods", "containerd", "lxc"))


def _apparmor_probe() -> str | None:
    """Read the process AppArmor profile, if one is active."""
    try:
        with open("/proc/self/attr/current", encoding="utf-8") as f:
            profile = f.read().strip()
    except OSError:
        return None
    # "unconfined" is the absence of a profile, not an active one.
    return profile if profile and profile != "unconfined" else None


def probe_capabilities() -> SandboxCapabilities:
    """Probe and return an honest snapshot of the current environment.

    Every probe is defensive and non-fatal: a probe failure lowers (never
    raises) the reported capability. This is the single source the sandbox
    boundary and its capability reporting use; nothing here guesses.
    """
    bwrap_ok, bwrap_bin, bwrap_note = _bwrap_probe()
    notes: list[str] = []
    if bwrap_note:
        notes.append(bwrap_note)
    return SandboxCapabilities(
        bubblewrap_available=bwrap_ok,
        bubblewrap_binary=bwrap_bin,
        user_namespaces_available=_userns_probe(),
        cgroup2_writable=_cgroup2_probe()[0],
        cgroup2_path=_cgroup2_probe()[1],
        seccomp_available=_seccomp_probe(),
        in_container=_container_probe(),
        apparmor_profile=_apparmor_probe(),
        notes=notes,
    )


def capability_report() -> dict[str, object]:
    """Return the capability snapshot as a JSON-serializable report dict.

    This is the capability-reporting surface for the API ``/capabilities`` and
    for tests asserting that unavailable/gated enhancements are reported
    honestly (never as active protection). Audio path gates (ASR/VAD/diarization)
    are disclosed once per report via :func:`audio_capability_report`.
    """
    caps = probe_capabilities()
    report: dict[str, object] = {
        **caps.to_dict(),
        # A convenience aggregate: whether genuine OS isolation can be activated.
        "os_isolation_active": caps.bubblewrap_available and caps.user_namespaces_available,
        "probe_at": "runtime",
    }
    try:
        from umd.audio.availability import audio_capability_report

        report["audio"] = audio_capability_report()
    except ImportError:  # pragma: no cover - audio package absent in minimal installs
        report["audio"] = {"error": "audio baseline unavailable"}
    try:
        from umd.video.availability import video_capability_report as _vc

        report["video"] = _vc()
    except ImportError:  # pragma: no cover - video package absent in minimal installs
        report["video"] = {"error": "video baseline unavailable"}
    try:
        from umd.subtitle.availability import subtitle_capability_report

        report["subtitle"] = subtitle_capability_report()
    except ImportError:  # pragma: no cover - subtitle package absent in minimal installs
        report["subtitle"] = {"error": "subtitle baseline unavailable"}
    return report
