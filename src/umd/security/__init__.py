"""Security boundary: sandboxing, capability-capped OS isolation, archive policy.

Delivered Plan C security surface:

  * ``sandbox`` — the ``SandboxRunner`` protocol with the reference
    ``SubprocessSandboxRunner``, ``stage_spool``/``run_ocfl_range_sandboxed``,
    the ``CleanupSpool`` spool lifecycle, ``ParserExitClass``, and
    ``SandboxLimits``/``SandboxPolicy`` bounds.
  * ``capabilities`` — runtime probe of bwrap/userns/cgroup2/seccomp/container/
    AppArmor availability plus ``capability_report``.
  * ``bwrap`` — ``BubblewrapSandboxRunner`` + ``build_bwrap_argv`` (bubblewrap
    OS isolation).
  * ``policies`` — per-parser ``ParserProfile`` registry (``PARSER_POLICIES``).
  * ``archive`` — zip/tar allowlist with traversal/symlink rejection.

OS-isolation (bubblewrap/AppArmor) is capability-GATED: it is claimed active
only when the runtime probe reports the underlying facilities. The
``SubprocessSandboxRunner`` is the always-available reference boundary.
"""
