"""pysubs2-backed subtitle parsing for SRT/ASS/WebVTT/TTML/SAMI/MicroDVD/MPL2/TMP.

Phases C P3-S3. Every format is parsed into an INDEPENDENT
:class:`~umd.subtitle.types.SubtitleTrack` preserving timing, styles, speaker
labels (ASS actor/``Name``), layer, and verbatim text (signs/songs/typesetting/
HI/SDH markers are never stripped). The DD-mandated WebVTT ``X-TIMESTAMP-MAP``
pre-normalization is applied BEFORE parsing (see :mod:`umd.subtitle.webvtt`) and
the transformation is recorded on the track. Charset probing + surrogate
preservation is applied by the caller via :mod:`umd.subtitle.charset` so raw
bytes remain authoritative.
"""

from __future__ import annotations

import io
import re
from typing import Any

from pysubs2.formats.microdvd import MicroDVDFormat
from pysubs2.formats.tmp import TmpFormat
from pysubs2.ssaevent import SSAEvent
from pysubs2.ssafile import SSAFile

from umd.subtitle.types import SubtitleEvent, SubtitleTrack
from umd.subtitle.webvtt import normalize_webvtt_timestamp_map

#: Formats we claim + their capability label / extension hints.
SUPPORTED_FORMATS = {
    "srt": {"kind": "srt", "extensions": ("srt",)},
    "ass": {"kind": "ass", "extensions": ("ass", "ssa")},
    "webvtt": {"kind": "webvtt", "extensions": ("vtt",)},
    "ttml": {"kind": "ttml", "extensions": ("ttml", "xml")},
    "sami": {"kind": "sami", "extensions": ("smi",)},
    "microdvd": {"kind": "microdvd", "extensions": ("sub",)},
    "mpl2": {"kind": "mpl2", "extensions": ("mpl2",)},
    "tmp": {"kind": "tmp", "extensions": ("tmp",)},
}

_MARKERS: list[tuple[str, str]] = [
    ("ass", "[Script Info]"),
    ("ass", "[V4+ Styles]"),
    ("webvtt", "WEBVTT"),
    ("ttml", "<tt"),
    ("sami", "<SAMI"),
]
_MICRODVD_RE = re.compile(r"^\{\d+\}\{\d+\}\s*")
_SQUARE_CUE_RE = re.compile(r"^\[(?P<a>[0-9:.]+)\]\[(?P<b>[^]]+)\]")
_TMP_RE = re.compile(r"^\s*\d{1,2}:\d{2}:\d{2}:")


class SubtitleFormatError(RuntimeError):
    """A subtitle document could not be parsed (typed, quarantine-able)."""


def detect_format(content: str, hint: str | None = None) -> str:
    """Detect the subtitle format from content markers + extension hint.

    Order: explicit marker match, extension hint, then bracket-cue scale tests
    (MicroDVD is frame-based with small ints; MPL2/TMP are fractional-seconds).
    Falls back to a pysubs2 autodetect probe; raises on unknown.
    """
    stripped = content.lstrip()
    for fmt, marker in _MARKERS:
        if stripped.startswith(marker):
            return fmt
    if hint:
        ext = hint.lstrip(".").lower()
        for fmt, info in SUPPORTED_FORMATS.items():
            if ext in info["extensions"]:
                return fmt
    # brace cues are MicroDVD (frame-based): ``{start}{end}``
    if _MICRODVD_RE.search(stripped):
        return "microdvd"
    # TMP is ``H:MM:SS:text``
    if _TMP_RE.search(stripped):
        return "tmp"
    # square-bracket cues are MPL2: ``[start][end] text`` (tenths-of-seconds ints)
    sm = _SQUARE_CUE_RE.search(stripped)
    if sm:
        return "mpl2"
    # SRT numeric-only index like ``1`` on the first line
    first = stripped.splitlines()[0].strip() if stripped.splitlines() else ""
    if re.match(r"^\d+$", first):
        return "srt"
    raise SubtitleFormatError("could not autodetect subtitle format")


def parse_subtitle_text(
    content: str,
    *,
    raw_bytes: bytes,
    charset: str = "utf-8",
    charset_confidence: float = 1.0,
    surrogate_preserved: bool = False,
    hint: str | None = None,
    embed_index: int | None = None,
    language: str | None = None,
    title: str | None = None,
    disposition: dict[str, Any] | None = None,
    codec_name: str | None = None,
    translation_source: str | None = None,
) -> SubtitleTrack:
    """Parse one subtitle document into an INDEPENDENT track (never flattened)."""
    fmt = detect_format(content, hint)
    normalization: dict[str, Any] | None = None
    if fmt == "webvtt":
        content, normalization = normalize_webvtt_timestamp_map(content)
    try:
        if fmt == "microdvd":
            file = SSAFile()
            MicroDVDFormat.from_file(file, io.StringIO(content), format_="microdvd", fps=25.0)
        elif fmt == "tmp":
            file = SSAFile()
            TmpFormat.from_file(file, io.StringIO(content), format_="tmp")
        else:
            file = SSAFile.from_string(content)
    except Exception as exc:  # pysubs2 raises several typed errors
        raise SubtitleFormatError(f"{fmt} parse failed: {exc}") from exc
    events = [_event_from_ssa(i, e, fmt) for i, e in enumerate(file.events)]
    styles = [
        {
            "name": sname,
            "fontname": s.fontname,
            "fontsize": s.fontsize,
            "primarycolor": str(s.primarycolor),
            "bold": s.bold,
            "italic": s.italic,
            "outline": s.outline,
            "shadow": s.shadow,
        }
        for sname, s in file.styles.items()
    ]
    return SubtitleTrack(
        index=embed_index,
        source_note="embedded" if embed_index is not None else "standalone",
        language=language,
        disposition=disposition or {},
        title=title,
        codec_name=codec_name,
        raw_bytes=raw_bytes,
        charset=charset,
        charset_confidence=charset_confidence,
        surrogate_preserved=surrogate_preserved,
        format=fmt,
        normalization=normalization,
        events=events,
        styles=styles,
        meta={
            "format": fmt,
            "event_count": len(events),
            "style_count": len(styles),
            "script_info": _script_info(file),
            "translation_source": translation_source,
        },
        translation_source=translation_source,
    )


def _script_info(file: SSAFile) -> dict[str, str]:
    try:
        return {str(k): str(v) for k, v in file.info.items()}
    except AttributeError:
        return {}


def _event_from_ssa(index: int, e: SSAEvent, fmt: str) -> SubtitleEvent:
    text = e.text if e.text is not None else ""
    actor = (e.name if getattr(e, "name", "") else "") or ""
    speaker = actor.strip() or None
    song = _is_song(text)
    sign = _is_sign(text)
    hi = _is_hi(text, song, sign)
    return SubtitleEvent(
        index=index,
        start_ms=int(e.start),
        end_ms=int(e.end),
        text=text,
        style=str(e.style) if getattr(e, "style", "") else None,
        speaker=speaker,
        layer=str(e.layer) if getattr(e, "layer", "") else None,
        actor=actor,
        is_hi=hi,
        is_sdh=hi,
        is_sign=sign,
        is_song=song,
        quality={
            "format": fmt,
            "marked": bool(getattr(e, "marked", False)),
            "text_preserved_verbatim": True,
        },
    )


def _is_song(text: str) -> bool:
    return any(mark in text for mark in ("♪", "♫", "♬", "[music", "[♪", "[song"))


def _is_sign(text: str) -> bool:
    low = text.lower()
    return any(
        mark in low
        for mark in ("[sign", "(sign", "sign language", "[visual", " [english]", "sings")
    )


def _is_hi(text: str, song: bool, sign: bool) -> bool:
    if song or sign:
        return True
    low = text.lower()
    return any(
        mark in low
        for mark in (
            "[",
            "]",
            "(sighs)",
            "(laughs)",
            "(music playing)",
            "(speaks in",
            "(telephone rings)",
            "(door opens)",
        )
    ) or bool(re.search(r"\([a-z]+[a-z ]+\)", low))


__all__ = [
    "SUPPORTED_FORMATS",
    "SubtitleFormatError",
    "detect_format",
    "parse_subtitle_text",
]
