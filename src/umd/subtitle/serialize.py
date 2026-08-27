"""JSON serialization of subtitle results across the sandbox boundary (P3-S3)."""

from __future__ import annotations

import base64
from typing import Any

from umd.subtitle.types import SubtitleEvent, SubtitleOutput, SubtitleTrack


def subtitle_output_to_dict(out: SubtitleOutput) -> dict[str, Any]:
    return {
        "tracks": [_track_to_dict(t) for t in out.tracks],
        "capability": out.capability,
        "warnings": out.warnings,
    }


def subtitle_output_from_dict(data: dict[str, Any]) -> SubtitleOutput:
    return SubtitleOutput(
        tracks=[_track_from_dict(t) for t in data.get("tracks") or []],
        capability=dict(data.get("capability") or {}),
        warnings=list(data.get("warnings") or []),
    )


def _track_to_dict(t: SubtitleTrack) -> dict[str, Any]:
    return {
        "index": t.index,
        "source_note": t.source_note,
        "language": t.language,
        "disposition": t.disposition,
        "title": t.title,
        "codec_name": t.codec_name,
        "raw_b64": base64.b64encode(t.raw_bytes).decode("ascii"),
        "charset": t.charset,
        "charset_confidence": t.charset_confidence,
        "surrogate_preserved": t.surrogate_preserved,
        "format": t.format,
        "normalization": t.normalization,
        "events": [_event_to_dict(e) for e in t.events],
        "styles": t.styles,
        "meta": t.meta,
        "translation_source": t.translation_source,
    }


def _track_from_dict(d: Any) -> SubtitleTrack:
    raw = base64.b64decode(d.get("raw_b64") or "") if d.get("raw_b64") else b""
    return SubtitleTrack(
        index=d.get("index"),
        source_note=str(d.get("source_note") or "standalone"),
        language=d.get("language"),
        disposition=dict(d.get("disposition") or {}),
        title=d.get("title"),
        codec_name=d.get("codec_name"),
        raw_bytes=raw,
        charset=str(d.get("charset") or "utf-8"),
        charset_confidence=float(d.get("charset_confidence") or 1.0),
        surrogate_preserved=bool(d.get("surrogate_preserved")),
        format=str(d.get("format") or "srt"),
        normalization=d.get("normalization"),
        events=[_event_from_dict(e) for e in d.get("events") or []],
        styles=list(d.get("styles") or []),
        meta=dict(d.get("meta") or {}),
        translation_source=d.get("translation_source"),
    )


def _event_to_dict(e: SubtitleEvent) -> dict[str, Any]:
    return {
        "index": e.index,
        "start_ms": e.start_ms,
        "end_ms": e.end_ms,
        "text": e.text,
        "style": e.style,
        "speaker": e.speaker,
        "is_hi": e.is_hi,
        "is_sdh": e.is_sdh,
        "is_sign": e.is_sign,
        "is_song": e.is_song,
        "layer": e.layer,
        "actor": e.actor,
        "quality": e.quality,
    }


def _event_from_dict(d: Any) -> SubtitleEvent:
    return SubtitleEvent(
        index=int(d.get("index") or 0),
        start_ms=int(d.get("start_ms") or 0),
        end_ms=int(d.get("end_ms") or 0),
        text=str(d.get("text") or ""),
        style=d.get("style"),
        speaker=d.get("speaker"),
        is_hi=bool(d.get("is_hi")),
        is_sdh=bool(d.get("is_sdh")),
        is_sign=bool(d.get("is_sign")),
        is_song=bool(d.get("is_song")),
        layer=d.get("layer"),
        actor=d.get("actor"),
        quality=dict(d.get("quality") or {}),
    )


__all__ = ["subtitle_output_from_dict", "subtitle_output_to_dict"]
