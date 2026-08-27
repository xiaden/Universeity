"""Video baseline sandbox entrypoint — runs INSIDE the sandbox (Phase C, P3-S1).

Usage (invoked by the runner with array-only argv through the
:class:`~umd.security.sandbox.SandboxRunner`):

    python -m umd.video.dispatch <readonly_spooled_input>

Reads the staged read-only video range, runs the deterministic video baseline
(:mod:`umd.video.pipeline` — ffprobe inventory, reference ffmpeg scene detection,
bounded PTS-native frame anchors, candidate observations, audio/subtitle track
composition announcements), and prints the :class:`~umd.video.types.VideoOutput`
payload as JSON on stdout. The API process never runs decode/inventory itself
(DD §Security).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from umd.video.config import config_digest_of, video_config_from_env
from umd.video.inventory import VideoDecodeError
from umd.video.pipeline import VideoPipeline
from umd.video.serialize import video_output_to_dict


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: umd.video.dispatch <input_path>", file=sys.stderr)
        return 2
    config = video_config_from_env()
    config_digest_of(config)
    try:
        output = VideoPipeline(Path(args[0]), config).run()
    except VideoDecodeError as exc:
        print(f"video decode error: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(video_output_to_dict(output), sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    raise SystemExit(main())
