"""API-process runner — invokes the audio baseline THROUGH the sandbox (P2-S1).

The DD mandates that audio decode/ASR/diarization never run in the API process.
This module is the API-process side of that boundary: it stages the raw OCFL byte
range into a read-only spool and runs ``python -m umd.audio.dispatch`` through a
:class:`~umd.security.sandbox.SandboxRunner` with the registered ``audio``
workload profile (:mod:`umd.security.policies`), then reconstructs the typed
:class:`~umd.audio.types.AudioOutput` from stdout. A parse/decode failure surfaces
as a typed :class:`AudioSandboxError` (quarantine-able; raw source is retained).
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from umd.audio.availability import audio_capability_report
from umd.audio.serialize import audio_output_from_dict
from umd.audio.types import AudioConfig, AudioOutput
from umd.security.policies import policy_for
from umd.security.sandbox import SandboxResult, SandboxRunner, stage_spool

#: The sole entrypoint module allowed as ``-m`` behind the audio policy.
_AUDIO_MODULE = "umd.audio.dispatch"


class AudioSandboxError(RuntimeError):
    """The audio worker failed in the sandbox (crash/timeout/denied/decode)."""

    def __init__(self, result: SandboxResult, detail: str | None = None) -> None:
        msg = (
            f"audio baseline failed in sandbox (exit={result.exit_code}, "
            f"timeout={result.timed_out}, denied={result.policy_denied})"
        )
        if detail:
            msg += f": {detail}"
        super().__init__(msg)
        self.result = result


def _argv_builder(input_path: Path) -> Sequence[str]:
    return [sys.executable, "-m", _AUDIO_MODULE, str(input_path)]


def invoke_audio_baseline(
    sandbox: SandboxRunner,
    raw: bytes,
    *,
    name: str = "audio",
    config: AudioConfig | None = None,
) -> AudioOutput:
    """Stage ``raw`` and run the sandboxed audio baseline; return typed output.

    :raises AudioSandboxError: the worker failed or emitted non-JSON/damaged output.
    """
    profile = policy_for("audio")
    with tempfile.TemporaryDirectory(prefix="umd_audio_spool_") as tmp:
        spool_root = Path(tmp)
        ext = Path(name).suffix.lstrip(".") or "wav"
        input_path = stage_spool(raw, f"{Path(name).name or 'audio'}.{ext}", spool_root)
        result: SandboxResult = sandbox.run(
            list(_argv_builder(input_path)),
            limits=profile.limits,
            policy=profile.policy,
        )
    # ``config`` is only used for capability disclosure of the *intended* gates;
    # the worker derives its own config from env (gates are honored on its side).
    if not result.ok:
        raise AudioSandboxError(result, detail=result.stderr or result.error)
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        raise AudioSandboxError(result, f"audio worker emitted non-JSON stdout: {exc}") from exc
    output = audio_output_from_dict(payload)
    if config is not None:
        output.capabilities.update(audio_capability_report(config))
    return output
