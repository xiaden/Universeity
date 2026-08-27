"""Phase C / P3-S3/P3-S4 standalone subtitle-worker tests (no Postgres).

Covers the DD subtitle contract at the worker boundary: every supported format
is parsed into an INDEPENDENT track (never flattened), non-UTF-8 input is charset-
probed with surrogate-preserving fallback while raw bytes stay authoritative, and
the mandatory WebVTT ``X-TIMESTAMP-MAP=LOCAL:...,MPEGTS:N`` pre-normalization
(shifts cues by ``N/90000 - LOCAL`` before parsing, strips the header, records the
transformation) is applied. Runs entirely in-process (no sandbox, no DB).
"""

from __future__ import annotations

import pytest

from umd.subtitle.charset import probe_charset, recover_raw_bytes
from umd.subtitle.formats import detect_format, parse_subtitle_text

# (format keyword, corpus, expected detection, expected start_ms, expected end_ms)
FORMAT_CORPORA: list[tuple[str, str, str, int, int]] = [
    (
        "srt",
        "1\n00:00:01.000 --> 00:00:02.000\nHello world",
        "srt",
        1000,
        2000,
    ),
    (
        "ass",
        (
            "[Script Info]\nScriptType: v4.00+\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, Bold, Italic\n"
            "Style: Default,Arial,20,16777215,0,0\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, "
            "MarginR, MarginV, Effect, Text\n"
            "Dialogue: 0,0:00:01.00,0:00:02.00,Default,Julien,0,0,0,,{\\i1}Bonjour{\\i0}"
        ),
        "ass",
        1000,
        2000,
    ),
    (
        "webvtt",
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello",
        "webvtt",
        1000,
        2000,
    ),
    (
        "ttml",
        (
            '<tt xmlns="http://www.w3.org/ns/ttml"><body><div>'
            '<p begin="00:00:01.000" end="00:00:02.000">Hi</p>'
            "</div></body></tt>"
        ),
        "ttml",
        1000,
        2000,
    ),
    (
        "sami",
        "<SAMI><HEAD></HEAD><BODY><SYNC Start=1000><P>Hello</P></SYNC></BODY></SAMI>",
        "sami",
        1000,
        None,  # pysubs2 estimates an end for SAMI
    ),
    (
        "microdvd",
        "{1}{25}Hello",
        "microdvd",
        40,
        1000,
    ),
    (
        "mpl2",
        "[0][100]Hello",
        "mpl2",
        0,
        10000,
    ),
    (
        "tmp",
        "0:00:01:Hello",
        "tmp",
        1000,
        None,  # pysubs2 estimates an end for TMP
    ),
]


@pytest.mark.parametrize(
    "name,corpus,expect_fmt,start_ms,end_ms",
    FORMAT_CORPORA,
    ids=[c[0] for c in FORMAT_CORPORA],
)
def test_each_format_parses_as_independent_track(
    name: str, corpus: str, expect_fmt: str, start_ms: int, end_ms: int | None
) -> None:
    raw = corpus.encode("utf-8")
    track = parse_subtitle_text(
        corpus,
        raw_bytes=raw,
        charset="utf-8",
        charset_confidence=1.0,
        surrogate_preserved=False,
        hint=None,
        embed_index=1,
        language="en",
        title="Track",
        disposition={"default": True},
        codec_name=name,
        translation_source=None,
    )
    assert detect_format(corpus, None) == expect_fmt
    assert track.format == expect_fmt
    assert track.events, f"{name} should yield at least one event"
    ev = track.events[0]
    assert ev.start_ms == start_ms
    if end_ms is not None:
        assert ev.end_ms == end_ms
    # Independent track metadata preserved, never flattened.
    assert track.index == 1
    assert track.language == "en"
    assert track.raw_bytes == raw


def test_ass_preserves_speaker_sign_song_hi_and_verbatim_text() -> None:
    corpus = (
        "[Script Info]\nScriptType: v4.00+\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, Bold, Italic\n"
        "Style: Default,Arial,20,16777215,0,0\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, "
        "MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:02.00,Default,Julien,0,0,0,,{\\i1}"
        "[music playing] (laughs){\\i0}\n"
        "Dialogue: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,{\\an8}[Sign] STOP"
    )
    track = parse_subtitle_text(
        corpus,
        raw_bytes=corpus.encode("utf-8"),
        charset="utf-8",
        charset_confidence=1.0,
        surrogate_preserved=False,
        hint="ass",
    )
    assert track.format == "ass"
    e0, e1 = track.events[0], track.events[1]
    assert e0.speaker == "Julien"  # ASS Name/actor preserved
    assert e0.is_song is True
    assert e0.is_hi is True
    assert "{\\i1}[music playing] (laughs){\\i0}" in e0.text  # verbatim, not stripped
    assert e1.is_sign is True
    assert "[Sign] STOP" in e1.text  # typesetting preserved verbatim


def test_webvtt_x_timestamp_map_positive_shift() -> None:
    corpus = (
        "WEBVTT\n"
        "X-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:900000\n\n"
        "00:00:01.000 --> 00:00:02.000\nHello after shift"
    )
    track = parse_subtitle_text(
        corpus,
        raw_bytes=corpus.encode("utf-8"),
        charset="utf-8",
        charset_confidence=1.0,
        surrogate_preserved=False,
        hint="webvtt",
    )
    assert track.format == "webvtt"
    assert track.normalization is not None
    norm = track.normalization
    # MPEGTS 900000 / 90000 = 10.0s ; LOCAL 0s  => shift = +10.0s
    assert norm["applied"] is True
    assert norm["header_stripped"] is True
    assert norm["mpegts"] == 900000
    assert abs(norm["shift_s"] - 10.0) < 1e-6
    assert track.events[0].start_ms == 11000
    assert track.events[0].end_ms == 12000


def test_webvtt_no_timestamp_map_strips_header_only() -> None:
    corpus = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello"
    track = parse_subtitle_text(
        corpus,
        raw_bytes=corpus.encode("utf-8"),
        charset="utf-8",
        charset_confidence=1.0,
        surrogate_preserved=False,
        hint="webvtt",
    )
    assert track.normalization is not None
    assert track.normalization["applied"] is False
    assert track.normalization["header_stripped"] is True
    # Unshifted cues preserved.
    assert track.events[0].start_ms == 1000
    assert track.events[0].end_ms == 2000


def test_non_utf8_cp1252_probing_smart_quotes() -> None:
    raw = b"1\x0a00:00:01.000 --> 00:00:02.000\x0acaf\xe9 \x93perfect\x94"
    probe = probe_charset(raw)
    assert probe.charset in {"cp1252", "latin-1"}
    # Western cp1252 smart-quote content is decoded without surrogate escape.
    track = parse_subtitle_text(
        "1\n00:00:01.000 --> 00:00:02.000\ncaf\xe9 \x93perfect\x94",
        raw_bytes=raw,
        charset=probe.charset,
        charset_confidence=probe.confidence,
        surrogate_preserved=probe.surrogate_preserved,
        hint="srt",
    )
    assert "caf\xe9" in track.events[0].text
    assert track.raw_bytes == raw  # raw bytes remain authoritative


def test_surrogate_preserving_foreign_high_bytes_roundtrip() -> None:
    # High C1-range bytes that are not valid western-cp1252 text: route to
    # latin-1 + surrogateescape so decoding never loses information.
    raw = "1\n00:00:01.000 --> 00:00:02.000\n\x81\x82\x83".encode("latin-1")
    probe = probe_charset(raw)
    assert probe.surrogate_preserved is True
    track = parse_subtitle_text(
        "1\n00:00:01.000 --> 00:00:02.000\n\x81\x82\x83",
        raw_bytes=raw,
        charset=probe.charset,
        charset_confidence=probe.confidence,
        surrogate_preserved=probe.surrogate_preserved,
        hint="srt",
    )
    assert track.surrogate_preserved is True
    # Surrogate-preserved text round-trips back to the original bytes.
    assert recover_raw_bytes(track.events[0].text) == b"\x81\x82\x83"


def test_detect_format_by_extension_hint() -> None:
    assert detect_format("anything", hint=".srt") == "srt"
    assert detect_format("anything", hint="ass") == "ass"
    assert detect_format("anything", hint="vtt") == "webvtt"
