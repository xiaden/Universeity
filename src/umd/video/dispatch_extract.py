"""Embedded-subtitle extraction entrypoint — runs INSIDE the sandbox (P3-S2).

Usage:

    python -m umd.video.dispatch_extract <readonly_spooled_video>

Inventory the container and extract EVERY embedded subtitle track into an
independent source (raw extracted bytes base64 + full track metadata) or into a
classified quarantine record for unsupported/bitmap codecs. The API process
never runs ffmpeg itself; it only reconstructs the typed payload and stores each
track's raw bytes as an independent OCFL source.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from umd.video.inventory import VideoDecodeError, extract_embedded_subtitle_tracks, probe_inventory


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: umd.video.dispatch_extract <input_path>", file=sys.stderr)
        return 2
    try:
        tracks = probe_inventory(Path(args[0]))
        extracted = extract_embedded_subtitle_tracks(Path(args[0]), tracks)
    except VideoDecodeError as exc:
        print(f"video subtitle extraction error: {exc}", file=sys.stderr)
        return 3
    print(json.dumps({"tracks": extracted}, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    raise SystemExit(main())
