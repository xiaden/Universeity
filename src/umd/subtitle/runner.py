"""API-process runner — invokes subtitle parsing THROUGH the sandbox (P3-S3).

Standalone subtitle files (and the independent raw extracted bytes of each
embedded track) are parsed via ``python -m umd.subtitle.dispatch`` inside the
sandbox with the registered ``subtitle`` workload profile. The API process never
parses untrusted subtitle text itself; a failure surfaces as a typed
:class:`SubtitleSandboxError` (quarantine-able; raw source retained).
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

from umd.security.policies import policy_for
from umd.security.sandbox import SandboxResult, SandboxRunner, stage_spool
from umd.subtitle.serialize import subtitle_output_from_dict
from umd.subtitle.types import SubtitleOutput

_SUBTITLE_MODULE = "umd.subtitle.dispatch"


class SubtitleSandboxError(RuntimeError):
    """The subtitle worker failed in the sandbox (crash/timeout/denied/parse)."""

    def __init__(self, result: SandboxResult, detail: str | None = None) -> None:
        msg = (
            f"subtitle parse failed in sandbox (exit={result.exit_code}, "
            f"timeout={result.timed_out}, denied={result.policy_denied})"
        )
        if detail:
            msg += f": {detail}"
        super().__init__(msg)
        self.result = result


def _argv_builder(module: str) -> Callable[[Path], Sequence[str]]:
    def _build(input_path: Path) -> Sequence[str]:
        return [sys.executable, "-m", module, str(input_path)]

    return _build


def invoke_subtitle_parse(
    sandbox: SandboxRunner,
    raw: bytes,
    *,
    name: str = "subtitles",
) -> SubtitleOutput:
    """Stage ``raw`` and run the sandboxed subtitle parse; return typed output.

    :raises SubtitleSandboxError: the worker failed or emitted non-JSON output.
    """
    profile = policy_for("subtitle")
    with tempfile.TemporaryDirectory(prefix="umd_subtitle_spool_") as tmp:
        spool_root = Path(tmp)
        ext = Path(name).suffix.lstrip(".") or "srt"
        input_path = stage_spool(raw, f"{Path(name).name or 'subtitles'}.{ext}", spool_root)
        result = sandbox.run(
            list(_argv_builder(_SUBTITLE_MODULE)(input_path)),
            limits=profile.limits,
            policy=profile.policy,
        )
    if not result.ok:
        raise SubtitleSandboxError(result, detail=result.stderr or result.error)
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        raise SubtitleSandboxError(
            result, f"subtitle worker emitted non-JSON stdout: {exc}"
        ) from exc
    return subtitle_output_from_dict(payload)


__all__ = ["SubtitleSandboxError", "invoke_subtitle_parse"]
