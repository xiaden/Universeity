"""bubblewrap-based OS-isolation runner (Phase C, P1-S1).

Implements the *hardened* boundary the DD describes (Q3 and Security and
observability): the parser subprocess runs under bubblewrap with read-only
binds, ``--die-with-parent``, unshared namespaces and an isolated ``/tmp``,
so a compromise of the parser cannot write outside its read-only spool or
escape the namespace.

Hard rule honored: activation is **gated on a real capability probe**. If
:func:`~umd.security.capabilities.probe_capabilities` reports bubblewrap as
unavailable in this environment, :class:`BubblewrapSandboxRunner` does NOT fall
back to a weaker mode and pretend OS isolation is active — it returns an honest
``policy_denied`` result naming the missing capability (and reports it through
``active_capabilities``). Callers that only require bounded-failure containment
should use :class:`~umd.security.sandbox.SubprocessSandboxRunner` directly and
consume the capability report for what it is.

The bare-metal/VM Ubuntu profile is the first-class posture; container postures
are conditional on user namespaces / capabilities and never ``--privileged``
(see ``capabilities.py``). This module introduces no OS-level dependencies.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from umd.security.capabilities import SandboxCapabilities, probe_capabilities
from umd.security.sandbox import (
    ParserExitClass,
    SandboxLimits,
    SandboxPolicy,
    SandboxResult,
    SubprocessSandboxRunner,
)


def build_bwrap_argv(
    command: Sequence[str],
    *,
    read_only_binds: Sequence[str] = (),
    # noqa: S108 - "/tmp" is a bwrap tmpfs *mount target*, not a Python tempfile.
    tmpfs_paths: Sequence[str] = ("/tmp",),  # noqa: S108
    dev_null: bool = True,
    unshare: bool = True,
    die_with_parent: bool = True,
) -> list[str]:
    """Build the bubblewrap argv that wraps ``command``.

    This is a pure, deterministic function (unit-testable without bwrap). It
    composes a conservative profile: the host root is bound read-only, the
    given extra paths are bound read-only, ``/tmp`` (and any other listed path)
    is an empty ``tmpfs``, namespaces are unshared, and the sandbox dies with
    its parent so an orphaned parser cannot linger.

    The caller passes at least the *read-only spool root* (staged from OCFL) as
    a ``read_only_bind`` so the parser can read, but never write, its input.
    """
    argv: list[str] = ["bwrap"]
    if dev_null:
        argv.append("--dev")
        argv.append("/dev")
    if unshare:
        argv.append("--unshare-all")
    if die_with_parent:
        argv.append("--die-with-parent")
    argv.append("--ro-bind")
    argv.append("/")
    argv.append("/")
    for ro in read_only_binds:
        argv.append("--ro-bind")
        argv.append(ro)
        argv.append(ro)
    for tmp in tmpfs_paths:
        argv.append("--tmpfs")
        argv.append(tmp)
    argv.append("--")
    argv.extend(str(a) for a in command)
    return argv


@dataclass
class BubblewrapSandboxRunner:
    """OS-isolation wrapping of a :class:`SubprocessSandboxRunner`.

    The inner runner does bounded-failure work; this wrapper routes the parser
    through bubblewrap for namespace/read-only isolation. ``require_os_isolation
    =True`` (default) is the strict posture: if bwrap cannot be validated right
    now, ``run`` returns an honest ``policy_denied`` result instead of silently
    degrading.
    """

    inner: SubprocessSandboxRunner | None = None
    require_os_isolation: bool = True
    #: Extra read-only bind targets (the OCFL spool root goes here).
    read_only_binds: list[str] = field(default_factory=list)
    #: Cache the capability probe across runs (vs. re-probe each call).
    freeze_caps: bool = False
    _caps: SandboxCapabilities | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.inner is None:
            self.inner = SubprocessSandboxRunner()

    @property
    def active_capabilities(self) -> SandboxCapabilities:
        """The capability snapshot governing this runner (honest + cached)."""
        if self._caps is None or not self.freeze_caps:
            self._caps = probe_capabilities()
        return self._caps

    def run(
        self,
        argv: Sequence[str],
        limits: SandboxLimits | None = None,
        policy: SandboxPolicy | None = None,
    ) -> SandboxResult:
        caps = self.active_capabilities
        if self.require_os_isolation and not caps.bubblewrap_available:
            return SandboxResult(
                argv=list(argv),
                exit_code=-2,
                policy_denied=True,
                denial_reason=(
                    "bubblewrap OS-isolation is unavailable in this environment; "
                    "activation is GATED (capability report: "
                    f"bubblewrap_available={caps.bubblewrap_available})"
                ),
                exit_class=ParserExitClass.POLICY_DENIED,
            )
        if not caps.bubblewrap_available:
            # Non-strict posture: bounded-failure containment still applies, but we
            # do NOT claim OS isolation.
            return self.inner.run(argv, limits=limits, policy=policy)  # type: ignore[union-attr]

        argv_list = list(argv)
        inner = self.inner
        if inner is None:  # defensive; __post_init__ always sets it
            return SandboxResult(
                argv=argv_list,
                exit_code=-2,
                policy_denied=True,
                denial_reason="no inner runner configured",
                exit_class=ParserExitClass.POLICY_DENIED,
            )
        # Validate the *real* parser command against the caller's policy before
        # wrapping, so the module/path allowlists are enforced on the true argv.
        if policy is not None:
            denied, reason = inner._check_policy(argv_list, policy)
            if denied:
                return SandboxResult(
                    argv=argv_list,
                    exit_code=-2,
                    policy_denied=True,
                    denial_reason=reason or "policy denied",
                    exit_class=ParserExitClass.POLICY_DENIED,
                )

        ro_binds = list(self.read_only_binds)
        if ro_binds:
            spool_parent = str(Path(ro_binds[0]).resolve() if os.path.exists(ro_binds[0]) else "/")
            wrapped = build_bwrap_argv(argv_list, read_only_binds=[spool_parent, *ro_binds])
        else:
            wrapped = build_bwrap_argv(argv_list)

        # Run the bwrap-wrapped argv through the inner runner, allowing only the
        # fixed bwrap binary (the real command's policy was already validated).
        result = inner.run(
            wrapped,
            limits=limits,
            policy=SandboxPolicy(allowed_executables=("bwrap",)),
        )
        return result
