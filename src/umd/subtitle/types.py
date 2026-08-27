"""Shared value types for the subtitle baseline (Phase C, P3-S2..S4).

Independent subtitle sources. Every track is an independent source/evidence
stream — never flattened, never treated as authoritative over another —
preserving language, disposition, track metadata, timing, styles, speaker
labels, signs, songs, typesetting, HI/SDH markers, raw bytes, and translation
differences. These dataclasses are the typed worker output that crosses the
sandbox boundary as JSON (standalone parse and embedded extraction).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SubtitleConfig:
    """Subtitle parse configuration (env-derived, worker-side)."""

    format: str | None = (
        None  # forced format ('srt','ass','webvtt','ttml','sami','microdvd','mpl2','tmp') or auto
    )
    max_events: int = 20000
    #: Enforce X-TIMESTAMP-MAP normalization for webvtt (DD-mandated).
    normalize_webvtt: bool = True
    config_digest: str | None = None


@dataclass
class SubtitleEvent:
    """One timed subtitle event/sign/song/HE-speech cue on an independent track."""

    index: int
    start_ms: int
    end_ms: int
    text: str
    style: str | None = None
    speaker: str | None = None
    #: Integrity-preserving flags (best-effort, preserved even when not detected).
    is_hi: bool = False  # hearing-impaired / SDH marker
    is_sdh: bool = False
    is_sign: bool = False  # visual-description / sign cue
    is_song: bool = False
    layer: str | None = None
    actor: str | None = None
    quality: dict[str, Any] = field(default_factory=dict)


@dataclass
class SubtitleTrack:
    """An INDEPENDENT subtitle source (standalone file or one embedded track).

    ``raw_bytes`` is the authoritative source content. ``charset``/
    ``surrogate_preserved`` record how raw bytes were decoded (surrogate-preserving
    when non-UTF-8). ``normalization`` records any WebVTT ``X-TIMESTAMP-MAP``
    transformation applied before parsing.
    """

    index: int | None  # embedded stream index, or None for a standalone file
    source_note: str
    language: str | None = None
    disposition: dict[str, Any] = field(default_factory=dict)
    title: str | None = None
    codec_name: str | None = None
    raw_bytes: bytes = b""
    charset: str = "utf-8"
    charset_confidence: float = 1.0
    surrogate_preserved: bool = False
    format: str = "srt"
    normalization: dict[str, Any] | None = None
    events: list[SubtitleEvent] = field(default_factory=list)
    styles: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    translation_source: str | None = None  # e.g. "en" track paired with "fr" track


@dataclass
class SubtitleOutput:
    """One subtitle worker parse result (standalone: 1 track; embedded: per-track)."""

    tracks: list[SubtitleTrack] = field(default_factory=list)
    capability: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


__all__ = [
    "SubtitleConfig",
    "SubtitleEvent",
    "SubtitleOutput",
    "SubtitleTrack",
]
