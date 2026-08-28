"""Audio baseline sandbox entrypoint — runs INSIDE the sandbox (Phase C, P2-S1).

Usage (invoked by the runner with array-only argv through the
:class:`~umd.security.sandbox.SandboxRunner`):

    python -m umd.audio.dispatch <readonly_spooled_input>

Reads the staged read-only audio range, bounded-decodes it via FFmpeg (itself a
bounded child subprocess with array-only argv — never shell), runs the full
deterministic audio baseline (:mod:`umd.audio.pipeline`), and prints the
:class:`~umd.audio.types.AudioOutput` payload as JSON on stdout. The API process
never runs decode/ASR/diarization itself (DD §Security).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from umd.audio.config import audio_config_from_env, config_digest_of
from umd.audio.decode import AudioDecodeError, decode_to_pcm
from umd.audio.pipeline import run_audio_baseline
from umd.audio.serialize import audio_output_to_dict


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: umd.audio.dispatch <input_path>", file=sys.stderr)
        return 2
    config = audio_config_from_env()
    config.config_digest = config_digest_of(config)
    try:
        audio = decode_to_pcm(Path(args[0]), max_duration_s=config.max_duration_s)
    except AudioDecodeError as exc:
        print(f"audio decode error: {exc}", file=sys.stderr)
        return 3
    output = run_audio_baseline(audio, config)
    print(json.dumps(audio_output_to_dict(output), sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    raise SystemExit(main())
