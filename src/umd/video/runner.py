"""API-process runner — invokes the video baseline THROUGH the sandbox (P3-S1/S2).

The DD mandates that PyAV/FFmpeg decode/inventory never run in the API process.
This module is the API-process side of that boundary: it stages the raw OCFL byte
range into a read-only spool and runs ``python -m umd.video.dispatch`` (baseline
inventory/scene/frame) or ``python -m umd.video.dispatch_extract`` (embedded
subtitle-track extraction) through a
:class:`~umd.security.sandbox.SandboxRunner` with the registered ``video``
workload profile (:mod:`umd.security.policies`), then reconstructs the typed
payloads. A failure surfaces as a typed :class:`VideoSandboxError`
(quarantine-able; raw source is retained).
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

from umd.security.policies import policy_for
from umd.security.sandbox import SandboxResult, SandboxRunner, stage_spool
from umd.video.serialize import video_output_from_dict
from umd.video.types import VideoOutput

_VIDEO_MODULE = "umd.video.dispatch"
_EXTRACT_MODULE = "umd.video.dispatch_extract"


class VideoSandboxError(RuntimeError):
    """The video worker failed in the sandbox (crash/timeout/denied/decode)."""

    def __init__(self, result: SandboxResult, detail: str | None = None) -> None:
        msg = (
            f"video baseline failed in sandbox (exit={result.exit_code}, "
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


def invoke_video_baseline(
    sandbox: SandboxRunner,
    raw: bytes,
    *,
    name: str = "video",
) -> VideoOutput:
    """Stage ``raw`` and run the sandboxed video baseline; return typed output.

    :raises VideoSandboxError: the worker failed or emitted non-JSON/damaged output.
    """
    profile = policy_for("video")
    with tempfile.TemporaryDirectory(prefix="umd_video_spool_") as tmp:
        spool_root = Path(tmp)
        ext = Path(name).suffix.lstrip(".") or "mp4"
        input_path = stage_spool(raw, f"{Path(name).name or 'video'}.{ext}", spool_root)
        result = sandbox.run(
            list(_argv_builder(_VIDEO_MODULE)(input_path)),
            limits=profile.limits,
            policy=profile.policy,
        )
    if not result.ok:
        raise VideoSandboxError(result, detail=result.stderr or result.error)
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        raise VideoSandboxError(result, f"video worker emitted non-JSON stdout: {exc}") from exc
    output = video_output_from_dict(payload)
    output.warnings = list(output.warnings)
    return output


def extract_embedded_subtitles(
    sandbox: SandboxRunner,
    raw: bytes,
    *,
    name: str = "video",
) -> list[dict[str, object]]:
    """Stage ``raw`` and run the sandboxed embedded-subtitle extraction.

    Returns the per-track extraction payloads (raw extracted bytes base64, track
    metadata) or classified quarantine records. The API process stores each
    track's raw bytes as an independent source (P3-S2 / P3-S3).
    """
    profile = policy_for("video")
    with tempfile.TemporaryDirectory(prefix="umd_vid_sub_spool_") as tmp:
        spool_root = Path(tmp)
        ext = Path(name).suffix.lstrip(".") or "mp4"
        input_path = stage_spool(raw, f"{Path(name).name or 'video'}.{ext}", spool_root)
        result = sandbox.run(
            list(_argv_builder(_EXTRACT_MODULE)(input_path)),
            limits=profile.limits,
            policy=profile.policy,
        )
    if not result.ok:
        raise VideoSandboxError(result, detail=result.stderr or result.error)
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        raise VideoSandboxError(result, f"extract worker emitted non-JSON stdout: {exc}") from exc
    tracks = payload.get("tracks") or []
    for t in tracks:
        if t.get("payload_b64"):
            # Pre-decode so the API process handles bytes, never leaves base64 in
            # evidence; a track's raw extracted bytes remain authoritative.
            try:
                t["payload"] = base64.b64decode(t["payload_b64"])
            except (ValueError, TypeError):
                t["payload"] = b""
                t["quarantine_reason"] = "malformed base64 payload"
            t.pop("payload_b64", None)
        else:
            t["payload"] = None
    return tracks


__all__ = ["VideoSandboxError", "extract_embedded_subtitles", "invoke_video_baseline"]
