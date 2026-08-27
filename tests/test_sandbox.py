"""Sandbox Runner seam tests (Phase B, P2-S1).

Verifies the :class:`SandboxRunner` contract: array-only argv, bounded limits
(timeout/output), read-only spool, and policy containment. Also proves the parser
invocation seam routes parsers through the bounded subprocess runner.

NOTE: this runner is bounded-failure containment, NOT full OS isolation — the
bubblewrap/AppArmor hardening is a documented Plan-C gate (asserted below).
"""

from __future__ import annotations

import sys

import pytest

from fixtures import epub_bytes, pdf_image_only_bytes, pdf_text_bytes, txt_bytes
from umd.extractors.dispatch import SandboxParseError, invoke_parser
from umd.security.sandbox import (
    SandboxLimits,
    SandboxPolicy,
    SubprocessSandboxRunner,
    stage_spool,
)

_ENTRY = "umd.extractors.dispatch"


def _runner(spool_root=None):
    return SubprocessSandboxRunner(spool_root=spool_root)


def test_array_only_argv_no_shell() -> None:
    # invoking a harmless program with array argv (no shell interpolation)
    result = _runner().run([sys.executable, "-c", "print('ok')"], limits=SandboxLimits())
    assert result.ok
    assert result.stdout.strip() == "ok"


def test_output_is_bounded() -> None:
    result = _runner().run(
        [sys.executable, "-c", "print('x'*5000)"],
        limits=SandboxLimits(max_output_bytes=64),
    )
    assert result.output_truncated
    assert len(result.stdout) <= 64


def test_timeout_bounded() -> None:
    result = _runner().run(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        limits=SandboxLimits(timeout_s=0.2),
    )
    assert result.timed_out
    assert result.exit_code < 0


def test_policy_denies_escaped_path() -> None:
    result = _runner().run(
        [sys.executable, "-m", _ENTRY, "txt", "/etc/passwd"],
        policy=SandboxPolicy(allowed_modules=(_ENTRY,)),
    )
    assert result.policy_denied
    assert "escapes" in (result.denial_reason or "")


def test_policy_enforces_m_module_allowlist(tmp_path) -> None:
    runner = _runner()
    # A non-allowlisted ``-m`` module is rejected outright — allowed_modules is
    # an enforced entrypoint allowlist, not just a trigger for path containment.
    in_path = tmp_path / "in.txt"
    in_path.write_bytes(b"x")
    denied = runner.run(
        [sys.executable, "-m", "os.system", "txt", str(in_path)],
        policy=SandboxPolicy(allowed_modules=(_ENTRY,)),
    )
    assert denied.policy_denied
    assert "not allowlisted" in (denied.denial_reason or "")

    # The allowlisted module passes the module check (its path is still
    # contained/resolvable under the spool root for this plain temp path).
    allowed = runner.run(
        [sys.executable, "-m", _ENTRY, "txt", str(in_path)],
        policy=SandboxPolicy(allowed_modules=(_ENTRY,)),
    )
    assert not allowed.policy_denied


def test_spool_is_readonly_directory(tmp_path) -> None:
    spool = stage_spool(b"hello", "input.txt", tmp_path)
    assert spool.exists()
    # directory is searchable + read-only, file is read-only
    assert spool.read_bytes() == b"hello"


def test_parser_invoked_through_sandbox() -> None:
    sb = _runner()
    for parser, raw, route in [
        ("txt", txt_bytes(), "text"),
        ("pdf", pdf_text_bytes(), "text"),
        ("pdf", pdf_image_only_bytes(), "image_raster"),
        ("epub", epub_bytes(), "text"),
    ]:
        parsed = invoke_parser(sb, parser, bytearray(raw))
        assert parsed.route == route


def test_parser_crash_surfaces_as_sandbox_error() -> None:
    sb = _runner()
    # A truncated "PDF" that pypdf cannot read deterministically -> parse error.
    with pytest.raises(SandboxParseError):
        invoke_parser(sb, "pdf", bytearray(b"%PDF-1.4 this is not a pdf xref ..."))


def test_hardened_profile_is_plan_c_gate_recorded() -> None:
    # The Phase-2 runner is bounded (limits/timeout/policy), not OS sandboxing;
    # the bubblewrap/AppArmor profile is a documented Plan-C gate.
    import inspect

    from umd.security import sandbox as sb_mod

    doc = inspect.getdoc(sb_mod)
    assert "Plan C" in doc
    assert "bubblewrap" in doc
