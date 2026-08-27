"""Mandatory WebVTT pre-normalizer (Phase C, P3-S3, DD §24.3).

The DD hard rule: parse ``X-TIMESTAMP-MAP=LOCAL:...,MPEGTS:N``, shift every cue by
``N/90000 - LOCAL`` (MPEG-TS timescale is 90 000 per second), **strip the WEBVTT
header**, and **record the transformation**. This must happen BEFORE pysubs2
parsing so cue timestamps are in the media timeline, not the raw MPEG descriptor
timeline.

:func:`normalize_webvtt_timestamp_map` is the pre-normalizer. It always returns a
transformation dict — never ``None`` — and always strips the header metadata while
keeping the ``WEBVTT`` magic so the parser routes to the webvtt format:

  * No ``X-TIMESTAMP-MAP`` present -> strips the header, records only the header
    removal, and returns ``(normalized_text, transformation)`` where
    ``transformation`` records ``applied=False``, ``header_stripped=True``,
    ``shift_s=0.0`` and ``reason="no X-TIMESTAMP-MAP present"``.
  * Header + map present -> strips the header, shifts cues by the computed
    offset, returns ``(normalized_text, transformation)`` where ``transformation``
    records ``applied=True``, ``local``, ``mpegts``, ``shift_s`` and
    ``header_stripped=True``.

Shifting is performed on ``HH:MM:SS.mmm --> HH:MM:SS.mmm`` cue lines; negative
shifted values are clamped to 0 in the normalized timestamps.
"""

from __future__ import annotations

import re
from typing import Any

#: ``00:00:01.000 --> 00:00:02.500 align:start`` cue-timing line.
_TIMING_RE = re.compile(
    r"^(\d{1,2}):(\d{1,2}):(\d{1,2})\.(\d{3})\s*-->\s*"
    r"(\d{1,2}):(\d{1,2}):(\d{1,2})\.(\d{3})\s*(.*)$"
)
#: ``X-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:81819``
_MAP_RE = re.compile(
    r"X-TIMESTAMP-MAP\s*=\s*LOCAL:(?P<h>\d{1,2}):(?P<m>\d{1,2}):(?P<s>\d{1,2})\.(?P<ms>\d+),"
    r"MPEGTS:(?P<ts>\d+)",
    re.IGNORECASE,
)

#: MPEG-TS timescale (ticks per second).
TS_SCALE = 90000


def _hms_ms_to_ms(h: str, m: str, s: str, ms: str) -> int:
    return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(ms)


def _ms_to_hms_ms(ms_total: int) -> str:
    ms_total = max(0, int(ms_total))
    h, rem = divmod(ms_total, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _split_header(text: str) -> tuple[list[str], list[str]]:
    """Split a WebVTT doc into header lines and body lines (after first blank)."""
    lines = text.splitlines()
    header: list[str] = []
    body: list[str] = []
    seen_blank = False
    for ln in lines:
        if seen_blank:
            body.append(ln)
        else:
            # The WEBVTT magic line is part of the header; blank line starts body.
            if ln.strip() == "":
                seen_blank = True
            else:
                header.append(ln)
    return header, body


def normalize_webvtt_timestamp_map(text: str) -> tuple[str, dict[str, Any] | None]:
    """Pre-normalize a WebVTT doc per the DD mandatory rule.

    Returns ``(normalized_text, transformation)``. See module docstring. The body
    is normalized in place; the header (WEBVTT magic + X-TIMESTAMP-MAP + other
    metadata) is stripped.
    """
    header, body = _split_header(text)
    map_match = None
    for ln in header:
        m = _MAP_RE.search(ln)
        if m:
            map_match = m
            break

    if map_match is None:
        # No X-TIMESTAMP-MAP: still strip the header (DD: "strip the header"),
        # record only the header removal. Keep the WEBVTT magic so the parser
        # can route to the webvtt format.
        normalized = "WEBVTT\n\n" + "\n".join(body)
        transformation: dict[str, Any] = {
            "applied": False,
            "header_stripped": True,
            "shift_s": 0.0,
            "reason": "no X-TIMESTAMP-MAP present",
        }
        return normalized, transformation

    local_ms = _hms_ms_to_ms(
        map_match.group("h"), map_match.group("m"), map_match.group("s"), map_match.group("ms")
    )
    mpegts = int(map_match.group("ts"))
    mpegts_s = mpegts / TS_SCALE
    local_s = local_ms / 1000.0
    shift_s = mpegts_s - local_s
    shift_ms = int(round(shift_s * 1000.0))

    shifted: list[str] = []
    for ln in body:
        m = _TIMING_RE.match(ln)
        if m:
            start_ms = _hms_ms_to_ms(m.group(1), m.group(2), m.group(3), m.group(4))
            end_ms = _hms_ms_to_ms(m.group(5), m.group(6), m.group(7), m.group(8))
            new_start = _ms_to_hms_ms(start_ms + shift_ms)
            new_end = _ms_to_hms_ms(end_ms + shift_ms)
            shifted.append(f"{new_start} --> {new_end}{' ' + m.group(9) if m.group(9) else ''}")
        else:
            shifted.append(ln)
    transformation = {
        "applied": True,
        "header_stripped": True,
        "local": f"{_ms_to_hms_ms(local_ms)}",
        "local_ms": local_ms,
        "mpegts": mpegts,
        "shift_s": round(shift_s, 6),
        "shift_ms": shift_ms,
        "timescale": TS_SCALE,
        "formula": "shift = MPEGTS/90000 - LOCAL",
    }
    return "WEBVTT\n\n" + "\n".join(shifted), transformation


__all__ = ["TS_SCALE", "normalize_webvtt_timestamp_map"]
