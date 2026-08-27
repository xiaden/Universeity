"""Subtitle baseline package (Phase C, P3-S2..S4).

Independent subtitle sources: embedded-track extraction (raw bytes authoritative),
charset probing + surrogate-preserving decode, mandatory WebVTT ``X-TIMESTAMP-MAP``
pre-normalization, and pysubs2 parsing of SRT/ASS/WebVTT/TTML/SAMI/MicroDVD/MPL2/
TMP into independent tracks that never flatten language/disposition/styles/
speaker/sign/song/HI-SDH markers or translation differences.
"""

from __future__ import annotations

from umd.subtitle.availability import subtitle_capability_report
from umd.subtitle.charset import decode_subtitle_bytes, probe_charset
from umd.subtitle.evidence import SubtitleEvidencePlan, build_subtitle_evidence_plan
from umd.subtitle.formats import detect_format, parse_subtitle_text
from umd.subtitle.types import SubtitleConfig, SubtitleOutput, SubtitleTrack
from umd.subtitle.webvtt import normalize_webvtt_timestamp_map

__all__ = [
    "SubtitleConfig",
    "SubtitleEvidencePlan",
    "SubtitleOutput",
    "SubtitleTrack",
    "build_subtitle_evidence_plan",
    "decode_subtitle_bytes",
    "detect_format",
    "normalize_webvtt_timestamp_map",
    "parse_subtitle_text",
    "probe_charset",
    "subtitle_capability_report",
]
