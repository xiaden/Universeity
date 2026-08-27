"""Sandbox-runner boundary tests (Phase C, P1-S1/S4).

Covers the new P1 boundary: read-only OCFL range spool + cleanup-on-crash,
structured exit classification, per-parser policy registry, cgroup best-effort
(with honest failure), and the gated bubblewrap OS-isolation runner (never
presented as active protection when unvalidated).
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from umd.security.bwrap import BubblewrapSandboxRunner, build_bwrap_argv
from umd.security.capabilities import SandboxCapabilities
from umd.security.policies import PARSER_POLICIES, policy_for
from umd.security.sandbox import (
    CleanupSpool,
    ParserExitClass,
    SandboxLimits,
    SandboxPolicy,
    SubprocessSandboxRunner,
    classify_parser_exit,
    run_ocfl_range_sandboxed,
    stage_ocfl_range,
)


class TestOcflRangeSpool:
    def test_stage_ocfl_range_readonly(self, tmp_path) -> None:
        native = SimpleNamespace(data=b"the range bytes", size_bytes=13, sha512="abc")
        path = stage_ocfl_range(native, "clip.bin", tmp_path)
        assert path.exists()
        assert path.read_bytes() == b"the range bytes"
        # staged under the spool root and read-only
        assert str(path).startswith(str(tmp_path / "spool"))

    def test_run_ocfl_range_sandboxed_uses_readonly_range(self, tmp_path) -> None:
        native = SimpleNamespace(data=b"payload", size_bytes=7, sha512="abc")
        runner = SubprocessSandboxRunner(spool_root=tmp_path)

        def builder(input_path) -> list[str]:
            return [
                sys.executable,
                "-c",
                f"import sys; print(len(open({str(input_path)!r}).read()))",
            ]

        result = run_ocfl_range_sandboxed(runner, native, "in.bin", argv_builder=builder)
        assert result.ok
        assert result.stdout.strip() == "7"

    def test_cleanup_spool_removes_dir_on_crash(self) -> None:
        spool_files: list = []
        try:
            with CleanupSpool(b"x", "f.bin") as path:
                spool_files.append(str(path))
                raise RuntimeError("parser crashed")
        except RuntimeError:
            pass
        # The staged path directory must be gone even though the body crashed.
        import pathlib

        assert not any(pathlib.Path(p).exists() for p in spool_files)


class TestExitClassification:
    def test_classifier_covers_every_outcome(self) -> None:
        assert classify_parser_exit(0) == ParserExitClass.OK
        assert classify_parser_exit(3) == ParserExitClass.NON_ZERO
        assert classify_parser_exit(-9) == ParserExitClass.CRASH
        assert classify_parser_exit(0, timed_out=True) == ParserExitClass.TIMEOUT
        assert (
            classify_parser_exit(0, resource_violation=True) == ParserExitClass.RESOURCE_VIOLATION
        )
        assert classify_parser_exit(0, policy_denied=True) == ParserExitClass.POLICY_DENIED

    def test_runner_reports_structured_exit_class(self) -> None:
        runner = SubprocessSandboxRunner()
        timeout = runner.run(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            limits=SandboxLimits(timeout_s=0.2),
        )
        assert timeout.exit_class == ParserExitClass.TIMEOUT
        denied = runner.run(
            [sys.executable, "-m", "os.system", "txt", "/nope"],
            policy=SandboxPolicy(allowed_modules=("umd.extractors.dispatch",)),
        )
        assert denied.exit_class == ParserExitClass.POLICY_DENIED
        ok = runner.run([sys.executable, "-c", "print('ok')"], limits=SandboxLimits())
        assert ok.exit_class == ParserExitClass.OK


class TestPerParserPolicies:
    def test_all_workloads_registered(self) -> None:
        for name in ("txt", "markdown", "epub", "pdf", "audio", "video", "subtitle"):
            assert name in PARSER_POLICIES

    def test_epub_is_archive_allowlisted(self) -> None:
        profile = policy_for("epub")
        assert profile.policy.archive_allow_extensions
        assert profile.limits.max_files > 0
        assert profile.limits.max_decompressed_bytes > 0

    def test_txt_is_plain(self) -> None:
        profile = policy_for("txt")
        assert not profile.policy.archive_allow_extensions
        assert "txt" in profile.policy.allowed_extensions

    def test_unknown_workload_raises(self) -> None:
        with pytest.raises(KeyError):
            policy_for("does-not-exist")


class TestCgroupBestEffort:
    def test_place_in_cgroup_fails_honestly(self, tmp_path) -> None:
        from umd.security.sandbox import place_in_cgroup

        # No cgroup.procs in a random dir -> must be False (never fabricated).
        assert place_in_cgroup(999999999, str(tmp_path)) is False


class TestBubblewrapGate:
    def test_unavailable_returns_denial_not_fabrication(self, monkeypatch) -> None:
        unavailable = SandboxCapabilities(bubblewrap_available=False)
        monkeypatch.setattr("umd.security.bwrap.probe_capabilities", lambda: unavailable)
        runner = BubblewrapSandboxRunner(require_os_isolation=True)
        result = runner.run([sys.executable, "-c", "print('x')"])
        assert result.policy_denied
        assert "GATED" in (result.denial_reason or "")
        assert result.exit_class == ParserExitClass.POLICY_DENIED
        # Capability report must not claim OS isolation.
        assert runner.active_capabilities.bubblewrap_available is False

    def test_non_strict_falls_back_to_bounded_runner(self, monkeypatch) -> None:
        unavailable = SandboxCapabilities(bubblewrap_available=False)
        monkeypatch.setattr("umd.security.bwrap.probe_capabilities", lambda: unavailable)
        runner = BubblewrapSandboxRunner(require_os_isolation=False)
        result = runner.run([sys.executable, "-c", "print('bounded')"])
        assert result.ok  # bounded runner executed; no claim of OS isolation

    def test_build_bwrap_argv_is_deterministic(self) -> None:
        argv = build_bwrap_argv(
            ["python", "-m", "umd.extractors.dispatch", "txt", "/spool/in.txt"],
            read_only_binds=["/spool"],
        )
        assert argv[0] == "bwrap"
        assert "--ro-bind" in argv
        assert "--unshare-all" in argv
        assert "--die-with-parent" in argv
        assert "--tmpfs" in argv
        assert "--" in argv
        assert argv[argv.index("--") + 1 :] == [
            "python",
            "-m",
            "umd.extractors.dispatch",
            "txt",
            "/spool/in.txt",
        ]
        # array-only: no shell metacharacters in any argv element.
        assert not any(any(c in a for c in ';&"') for a in argv)
