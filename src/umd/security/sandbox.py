"""Sandbox Runner — the invocation seam for untrusted parsers / extraction.

Phase B (P2-S1) introduced the practical bounded runner; Phase C (P1-S1/S2) makes
the *hardened* boundary real. This module implements the binding contract
``SandboxRunner.run(argv, limits, policy) -> SandboxResult``:

  * **array-only argv** — the runner never shell-interpolates; arguments are an
    explicit sequence (``list[str]``) passed to ``subprocess.Popen`` verbatim;
  * **bounded limits** — CPU seconds, address-space, file descriptors, child
    processes, wall-clock timeout, captured-output size, archive entry count,
    decompressed size, media duration and pixel budgets are capped;
  * **read-only OCFL range spool** — parser inputs are staged from immutable
    OCFL byte ranges into a read-only directory before the subprocess runs
    (:func:`stage_spool`, :func:`run_ocfl_range_sandboxed`);
  * **policy checks** — the executable/entrypoint is allowlisted and an input
    path must live under the spool root (traversal rejection);
  * **rlimits/cgroups/timeouts** — ``setrlimit`` caps plus optional cgroup v2
    placement (:func:`place_in_cgroup`) plus wall-clock kill;
  * **structured parser exit classes** — every outcome is classified
    (:data:`ParserExitClass`) for metrics/correlation logging;
  * **cleanup on crash/retry** — :class:`CleanupSpool` guarantees the staged
    spool is removed even when the parser crashes or a retry is scheduled;
  * **containment** — a parser crash, timeout, resource violation or oversize
    output surfaces as a structured :class:`SandboxResult`.

OS-isolation honesty (DD hard rule): this module is bounded-failure containment
(rlimits + timeout + policy + read-only spool). The bubblewrap/AppArmor
OS-isolation boundary (the *Plan C* hardening) is implemented in
:mod:`umd.security.bwrap` and is **gated on a real capability probe**
(:mod:`umd.security.capabilities`) — it is never presented as active unless the
environment validates it. Readers must not conflate the two.
"""

from __future__ import annotations

import contextlib
import os
import resource
import shutil
import subprocess
import sys
import tempfile
from abc import abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

#: Exit code reserved for "wall-clock timeout" (subprocess.kill) — not a parser exit.
_TIMEOUT_EXIT = -1


class ParserExitClass(StrEnum):
    """Structured classification of a sandboxed process outcome (P1-S2).

    Used for correlation/job/source/stage logging and parser-exit metrics so a
    decomposition report can explain *why* a stage finished (not just the code).
    """

    OK = "ok"
    TIMEOUT = "timeout"
    RESOURCE_VIOLATION = "resource_violation"
    POLICY_DENIED = "policy_denied"
    CRASH = "crash"  # negative exit code => terminated by a signal
    NON_ZERO = "non_zero"  # parser exited non-zero for its own reason


def classify_parser_exit(
    exit_code: int,
    *,
    timed_out: bool = False,
    policy_denied: bool = False,
    resource_violation: bool = False,
) -> ParserExitClass:
    """Deterministically map a subprocess outcome to a :class:`ParserExitClass`."""
    if policy_denied:
        return ParserExitClass.POLICY_DENIED
    if timed_out:
        return ParserExitClass.TIMEOUT
    if resource_violation:
        return ParserExitClass.RESOURCE_VIOLATION
    if exit_code == 0:
        return ParserExitClass.OK
    if exit_code < 0:
        return ParserExitClass.CRASH
    return ParserExitClass.NON_ZERO


@dataclass(frozen=True)
class SandboxLimits:
    """Bounded resource limits applied to a sandboxed parser subprocess.

    All limits are upper bounds; a parser exceeding any of them is terminated
    and reported, never allowed to run unbounded. The archive/media fields are
    ceilings enforced by the archive (:mod:`umd.security.archive`) and media
    extraction layers respectively (0/``None`` = not additionally enforced here,
    beyond the OS-level rlimits).
    """

    timeout_s: float = 30.0
    cpu_s: int = 10
    memory_bytes: int = 512 * 1024 * 1024  # RLIMIT_AS (generous enough for CPython)
    fd_limit: int = 256
    nproc_limit: int = 64
    max_output_bytes: int = 16 * 1024 * 1024
    max_args: int = 256
    #: Archive entry-count ceiling (P1-S2 archive limits).
    max_files: int = 1000
    #: Archive decompressed-size ceiling in bytes (P1-S2 archive limits).
    max_decompressed_bytes: int = 512 * 1024 * 1024
    #: Media duration ceiling in seconds (0 = not enforced; media layers enforce).
    max_duration_s: float = 0.0
    #: Pixel budget for media frames (0 = not enforced; raster/media enforce).
    max_pixels: int = 0
    #: Optional writable cgroup v2 leaf for memory/pid accounting (best-effort).
    cgroup_path: str | None = None


@dataclass(frozen=True)
class SandboxPolicy:
    """Policy allowlists / containment rules checked before a run (P1-S1/S2)."""

    #: Executable basenames that may be invoked (e.g. ``python3``). Empty string
    #: means "require the current interpreter" (the callers pass ``sys.executable``
    #: and this policy only admits that exact binary).
    allowed_executables: tuple[str, ...] = ()
    #: Parser entrypoint modules allowed as ``-m <module>`` arguments.
    allowed_modules: tuple[str, ...] = ()
    #: Extensions an input path may have (archive allowlist). Empty = any.
    allowed_extensions: tuple[str, ...] = ()
    #: Archive-member suffix allowlist (P1-S2). Empty = no per-member extension
    #: allowlist (path-safety + limit rules still apply to every member).
    archive_allow_extensions: tuple[str, ...] = ()
    #: Reject archive members with absolute paths (escape hardening).
    reject_absolute: bool = True
    #: Reject archive members with ``..`` traversal (escape hardening).
    reject_traversal: bool = True
    #: Reject archive members that are symlinks / escape their extraction root.
    reject_symlinks: bool = True


@dataclass
class SandboxResult:
    """Result of one :meth:`SandboxRunner.run` invocation."""

    argv: list[str]
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    resource_violation: bool = False
    output_truncated: bool = False
    policy_denied: bool = False
    denial_reason: str | None = None
    error: str | None = None
    exit_class: ParserExitClass = ParserExitClass.OK

    @property
    def ok(self) -> bool:
        return (
            self.exit_code == 0
            and not self.timed_out
            and not self.resource_violation
            and not self.policy_denied
        )


class SandboxRunner(Protocol):
    """The binding ``SandboxRunner`` seam (CONTRACTS.md §Modality and security).

    Implementations run a parser as a *bounded* subprocess: array-only argv,
    resource limits, read-only input spool, policy allowlists, and containment.
    """

    @abstractmethod
    def run(
        self,
        argv: Sequence[str],
        limits: SandboxLimits | None = None,
        policy: SandboxPolicy | None = None,
    ) -> SandboxResult: ...


# ---------------------------------------------------------------------------
# Read-only OCFL range spool + guaranteed cleanup
# ---------------------------------------------------------------------------


def stage_spool(raw: bytes, name: str, root: Path) -> Path:
    """Write ``raw`` into a read-only spool directory; return the input path.

    The spool is staged from immutable OCFL bytes (never from a user-controlled
    path) into a fresh directory under ``root`` which is then made read-only so a
    sandboxed parser cannot modify its own input. Returns the spooled file path.
    """
    spool_dir = root / "spool"
    spool_dir.mkdir(parents=True, exist_ok=True)
    input_path = spool_dir / (Path(name).name or "input.bin")
    input_path.write_bytes(raw)
    try:
        # Directory: read+execute (searchable but not writable); file: read-only.
        # Narrow masks are deliberate hardening of the spool; bandit's S103 is
        # inapplicable here (we are *restricting* permissions, not loosening them).
        os.chmod(spool_dir, 0o555)  # noqa: S103
        os.chmod(input_path, 0o444)  # noqa: S103
    except OSError:
        pass
    return input_path


def stage_ocfl_range(native: object, name: str, root: Path) -> Path:
    """Stage a bounded OCFL range (``NativeRepresentation``) into the read-only spool.

    Accepts any object exposing ``.data: bytes`` (the :class:`NativeRepresentation`
    returned by ``SourceStore.get_range``), staging only that bounded range — never
    the whole source — into a read-only spool for a sandboxed parser.
    """
    data: bytes = native.data  # type: ignore[attr-defined]
    return stage_spool(data, name, root)


class CleanupSpool:
    """Context manager staging raw bytes into a temp read-only spool.

    The spool is created on ``__enter__`` and *always* removed on ``__exit__*
    (crashes and retries included) — this is the cleanup-on-crash/retry guarantee.
    """

    def __init__(self, raw: bytes, name: str, base: Path | None = None) -> None:
        self._raw = raw
        self._name = name
        self._base = base or Path(tempfile.gettempdir())
        self._dir: Path | None = None

    def __enter__(self) -> Path:
        self._dir = Path(tempfile.mkdtemp(prefix="umd_spool_"))
        return stage_spool(self._raw, self._name, self._dir)

    def __exit__(self, *exc: object) -> None:
        if self._dir is not None:
            _make_removable(self._dir)
            shutil.rmtree(self._dir, ignore_errors=True)


def _make_removable(root: Path) -> None:
    """Restore write permissions so a read-only staged spool can be deleted.

    ``stage_spool`` narrows the spool dir/file to ``0o555``/``0o444`` which also
    makes them non-removable (delete needs write on the containing directory).
    Cleanup must restore writability before ``rmtree`` or the spool leaks —
    violating the cleanup-on-crash/retry guarantee.
    """
    if not root.exists():
        return
    for p in sorted(root.rglob("*"), reverse=True):
        with contextlib.suppress(OSError):
            os.chmod(p, 0o700)
    with contextlib.suppress(OSError):
        os.chmod(root, 0o700)


def run_ocfl_range_sandboxed(
    runner: SandboxRunner,
    native: object,
    name: str,
    *,
    argv_builder: Callable[[Path], Sequence[str]],
    limits: SandboxLimits | None = None,
    policy: SandboxPolicy | None = None,
) -> SandboxResult:
    """Stage an OCFL byte range for ``runner`` and invoke ``argv_builder``.

    Guarantees spool cleanup on crash/retry via :class:`CleanupSpool`. This is
    the ergonomic entry point feeding a media/parser stage its *read-only
    bounded* input without ever loading the whole source into the API process
    or leaving staged bytes behind.
    """
    with CleanupSpool(native.data, name) as input_path:  # type: ignore[attr-defined]
        argv = list(argv_builder(input_path))
        result = runner.run(argv, limits=limits, policy=policy)
    return result


def place_in_cgroup(pid: int, cgroup_path: str) -> bool:
    """Best-effort place ``pid`` into a writable cgroup v2 leaf; return success.

    cgroup placement is an *additional* accounting/containment guard on top of
    rlimits. It is purely best-effort: if the leaf is not writable this returns
    ``False`` and the run continues under rlimit+timeout containment. It never
    fabricates protection.
    """
    procs = Path(cgroup_path) / "cgroup.procs"
    try:
        if not procs.is_file():
            return False
        procs.write_text(f"{pid}\n")
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Practical bounded-failure runner
# ---------------------------------------------------------------------------


class SubprocessSandboxRunner:
    """The practical bounded subprocess implementation of :class:`SandboxRunner`.

    Bounds enforced:

    * **array-only argv** — the exact sequence is passed to ``subprocess.Popen``;
      nothing is interpolated into a shell.
    * **wall-clock timeout** — a manual ``communicate(timeout=...)`` kills an
      overrun (and cleans the pipe buffers).
    * **CPU / address-space / fd / nproc** — ``resource.setrlimit`` in a
      ``preexec_fn`` so the parser inherits the caps before it starts.
    * **cgroups** — when ``limits.cgroup_path`` is a writable v2 leaf, the child
      PID is placed in it (best-effort, see :func:`place_in_cgroup`).
    * **policy** — the executable must match an allowlist (or, when empty, the
      current interpreter), any input path must resolve under the spool root, and
      when an extension allowlist is declared the resolved input's suffix must be
      in it.
    * **output** — captured stdout/stderr are truncated to ``max_output_bytes``.
    * **exit classification** — every outcome carries a :class:`ParserExitClass`.

    This runner performs bounded-failure containment, NOT OS-level isolation;
    the bubblewrap/AppArmor hardening is a gated boundary in
    :mod:`umd.security.bwrap` (see module docstring).
    """

    def __init__(
        self,
        *,
        executable: str | None = None,
        spool_root: Path | None = None,
    ) -> None:
        self._executable = executable or sys.executable
        self._spool_root = (spool_root or Path(tempfile.gettempdir())).resolve()

    def run(
        self,
        argv: Sequence[str],
        limits: SandboxLimits | None = None,
        policy: SandboxPolicy | None = None,
    ) -> SandboxResult:
        limits = limits or SandboxLimits()
        policy = policy or SandboxPolicy()
        argv_list = list(argv)

        if not argv_list or len(argv_list) > limits.max_args:
            return self._reject(argv_list, "argv empty or exceeds max_args")

        denied, reason = self._check_policy(argv_list, policy)
        if denied:
            return self._reject(argv_list, reason or "policy denied")

        def _bounded() -> None:
            try:
                resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_s, limits.cpu_s))
                resource.setrlimit(
                    resource.RLIMIT_AS,
                    (limits.memory_bytes, limits.memory_bytes),
                )
                resource.setrlimit(resource.RLIMIT_NOFILE, (limits.fd_limit, limits.fd_limit))
                with contextlib.suppress(ValueError, OSError):
                    # RLIMIT_NPROC is not enforceable on all platforms.
                    resource.setrlimit(
                        resource.RLIMIT_NPROC, (limits.nproc_limit, limits.nproc_limit)
                    )
            except (ValueError, OSError):
                pass  # resource limits are best-effort; timeout+policy still guard

        try:
            proc = subprocess.Popen(  # noqa: S603 - allowlisted/fixed interpreter below
                argv_list,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=_bounded,
            )
        except OSError as exc:
            return SandboxResult(
                argv=argv_list,
                exit_code=-2,
                error=f"failed to spawn subprocess: {exc}",
                exit_class=ParserExitClass.CRASH,
            )

        placed_cgroup = False
        if limits.cgroup_path:
            placed_cgroup = place_in_cgroup(proc.pid, limits.cgroup_path)

        timed_out = False
        try:
            out_b, err_b = proc.communicate(timeout=limits.timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            # Reap and drain the pipes so no resource leak lingers on retries.
            out_b, err_b = proc.communicate()

        stdout = out_b.decode("utf-8", errors="replace")
        stderr = err_b.decode("utf-8", errors="replace")
        truncated = len(stdout) > limits.max_output_bytes or len(stderr) > limits.max_output_bytes
        exit_code = (
            _TIMEOUT_EXIT if timed_out else (proc.returncode if proc.returncode is not None else -2)
        )
        return SandboxResult(
            argv=argv_list,
            exit_code=exit_code,
            stdout=self._clip(stdout, limits.max_output_bytes),
            stderr=self._clip(stderr, limits.max_output_bytes),
            output_truncated=truncated,
            timed_out=timed_out,
            exit_class=classify_parser_exit(exit_code, timed_out=timed_out, policy_denied=False),
            error=None if placed_cgroup or not limits.cgroup_path else "cgroup placement failed",
        )

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _reject(argv_list: list[str], reason: str) -> SandboxResult:
        return SandboxResult(
            argv=argv_list,
            exit_code=-2,
            policy_denied=True,
            denial_reason=reason,
            exit_class=ParserExitClass.POLICY_DENIED,
        )

    def _check_policy(self, argv: list[str], policy: SandboxPolicy) -> tuple[bool, str | None]:
        if policy.allowed_executables:
            exe = Path(argv[0]).name
            if exe not in policy.allowed_executables:
                return True, f"executable {argv[0]!r} not allowlisted"
        elif isinstance(argv[0], str) and not self._same_interpreter(argv[0]):
            return True, f"executable {argv[0]!r} is not the allowlisted interpreter"

        # Enforce the ``-m <module>`` allowlist: any ``-m`` invocation must name a
        # module present in ``allowed_modules``.
        if len(argv) > 1 and argv[1] == "-m":
            if not policy.allowed_modules:
                return True, "no -m modules allowlisted for this policy"
            if len(argv) < 3:
                return True, "-m requires a module argument"
            module = argv[2]
            if module not in policy.allowed_modules:
                return True, f"module {module!r} not allowlisted"

        if policy.allowed_extensions or policy.allowed_modules:
            trailing = argv[-1]
            if trailing and not trailing.startswith("-"):
                p = Path(trailing)
                try:
                    resolved = p.resolve()
                except OSError:
                    return True, f"cannot resolve path {trailing!r}"
                if not str(resolved).startswith(str(self._spool_root)):
                    return True, f"input path {trailing!r} escapes the read-only spool"
                if policy.allowed_extensions:
                    suffix = resolved.suffix.lower()
                    allowed = {f".{e.lower()}" for e in policy.allowed_extensions}
                    if suffix not in allowed:
                        return True, (
                            f"input path {trailing!r} extension {suffix!r} is not allowlisted"
                        )
        return False, None

    @staticmethod
    def _same_interpreter(exe: str) -> bool:
        try:
            return os.path.realpath(exe) == os.path.realpath(sys.executable)
        except OSError:
            return False

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[:limit]
