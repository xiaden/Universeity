"""Subtitle parse entrypoint — runs INSIDE the sandbox (Phase C, P3-S3).

Usage:

    python -m umd.subtitle.dispatch <readonly_spooled_subtitle> [format_hint]

Reads the staged read-only subtitle source bytes, probes the charset
(surrogate-preserving, raw bytes authoritative), applies the mandatory WebVTT
``X-TIMESTAMP-MAP`` pre-normalization for webvtt, parses via pysubs2
(SRT/ASS/WebVTT/TTML/SAMI/MicroDVD/MPL2/TMP) into an INDEPENDENT
:class:`~umd.subtitle.types.SubtitleTrack`, and prints JSON on stdout. The API
process only receives the structured, type-checked payload.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from umd.subtitle.availability import subtitle_capability_report
from umd.subtitle.charset import SubtitleDecodeError, decode_subtitle_bytes
from umd.subtitle.config import config_digest_of, subtitle_config_from_env
from umd.subtitle.formats import SubtitleFormatError, parse_subtitle_text
from umd.subtitle.serialize import subtitle_output_to_dict
from umd.subtitle.types import SubtitleOutput


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not (1 <= len(args) <= 2):
        print("usage: umd.subtitle.dispatch <input_path> [format_hint]", file=sys.stderr)
        return 2
    config = subtitle_config_from_env()
    config_digest_of(config)
    path = Path(args[0])
    hint = args[1] if len(args) == 2 else (Path(args[0]).suffix.lstrip(".") or None)
    try:
        raw = path.read_bytes()
        text, probe = decode_subtitle_bytes(raw)
        track = parse_subtitle_text(
            text,
            raw_bytes=raw,
            charset=probe.charset,
            charset_confidence=probe.confidence,
            surrogate_preserved=probe.surrogate_preserved,
            hint=config.format or hint,
        )
    except (SubtitleFormatError, SubtitleDecodeError, OSError) as exc:
        print(f"subtitle parse error: {exc}", file=sys.stderr)
        return 3
    if len(track.events) > config.max_events:
        track.events = track.events[: config.max_events]
    out = SubtitleOutput(
        tracks=[track],
        capability=subtitle_capability_report(),
        warnings=[],
    )
    print(json.dumps(subtitle_output_to_dict(out), sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
