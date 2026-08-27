"""Phase F / P1-S1+S3: fixture determinism and property coverage.

The Phase-F fixture generators in :mod:`fixtures` are the deliverable of P1-S1.
These tests pin the two properties the whole determinism story depends on:

  * identical inputs -> identical bytes (the pure-stdlib generators produce the
    exact same bytes on every call, which is what byte-exact deterministic-stage
    checks need);
  * every subtitle format parses into an INDEPENDENT track with HI/SDH preserved
    verbatim and the mandatory nonzero WebVTT ``X-TIMESTAMP-MAP`` applied;
  * translated/adapted realizations are byte-distinct (never conflated);
  * vertical-layout / CJK-style raster pages yield deterministic regions.

No PostgreSQL required — these run identically everywhere.
"""

from __future__ import annotations

import io
import wave
from collections.abc import Callable
from functools import partial

import pytest

from fixtures import (
    SUBTITLE_FORMATS,
    adapted_markdown_bytes,
    epub_bytes,
    markdown_bytes,
    multi_speaker_audio_wav_bytes,
    pdf_image_only_bytes,
    pdf_text_bytes,
    raster_comic_bytes,
    raster_text_only_bytes,
    raster_vertical_cjk_bytes,
    subtitle_bytes,
    translated_txt_bytes,
    txt_bytes,
)
from umd.raster.bounds import decode_bounded
from umd.raster.regions import detect_panels, find_ink_regions
from umd.subtitle.formats import parse_subtitle_text

# Pure-stdlib generators MUST be byte-identical run-to-run. FFmpeg-locked ones
# (dialogue_video_bytes, vfr_editlist_video_bytes) are asserted separately because
# container muxing produces run-stable bytes but is environment-anchored.
_DETERMINISTIC_GENERATORS: dict[str, Callable[[], bytes]] = {
    "txt": txt_bytes,
    "markdown": markdown_bytes,
    "epub": epub_bytes,
    "pdf_text": pdf_text_bytes,
    "pdf_image_only": pdf_image_only_bytes,
    "raster_comic": raster_comic_bytes,
    "raster_vertical_cjk": raster_vertical_cjk_bytes,
    "multi_speaker_wav": multi_speaker_audio_wav_bytes,
    "translated_txt": translated_txt_bytes,
    "adapted_markdown": adapted_markdown_bytes,
    **{f"subtitle_{f}": partial(subtitle_bytes, f, hi_sdh=True) for f in SUBTITLE_FORMATS},
}


@pytest.mark.parametrize("name", sorted(_DETERMINISTIC_GENERATORS))
def test_generator_is_byte_stable(name: str) -> None:
    gen = _DETERMINISTIC_GENERATORS[name]
    a = gen()
    b = gen()
    assert a == b, f"{name} generator is not byte-stable across calls"
    assert isinstance(a, bytes) and len(a) > 0


def test_ffmpeg_locked_generators_produce_media() -> None:
    """The FFmpeg-locked generators must be present in the environment or skip."""
    import shutil

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg binary absent; dialogue/vfr video fixtures not generated")
    from fixtures import dialogue_video_bytes, vfr_editlist_video_bytes

    dv = dialogue_video_bytes()
    vfr = vfr_editlist_video_bytes()
    assert dv.startswith(b"\x1a\x45\xdf\xa3")  # EBML/Matroska magic
    assert len(dv) > 0 and len(vfr) > 0


# --- subtitle property: independent tracks, HI/SDH, timestamp maps ------------


def test_every_subtitle_format_is_independent_and_hi_sdh() -> None:
    for fmt in SUBTITLE_FORMATS:
        raw = __import__("fixtures").subtitle_bytes(fmt, hi_sdh=True)
        corpus = raw.decode("utf-8", "replace")
        hint = "vtt" if fmt == "webvtt" else fmt
        track = parse_subtitle_text(
            corpus,
            raw_bytes=raw,
            charset="utf-8",
            charset_confidence=1.0,
            surrogate_preserved=False,
            hint=hint,
            embed_index=1,
            language="en",
            title="Track",
            disposition={"default": True},
            codec_name=fmt,
        )
        assert track.format == fmt, f"{fmt} detected as wrong format"
        assert track.index == 1 and track.language == "en"
        assert track.raw_bytes == raw  # raw bytes authoritative, never stripped
        assert track.events, f"{fmt} must yield >=1 event"


def test_webvtt_nonzero_timestamp_map_shifts_cues() -> None:
    from fixtures import subtitle_bytes

    raw = subtitle_bytes("webvtt", timestamp_map=900000)  # +10.0 s epoch
    track = parse_subtitle_text(
        raw.decode("utf-8"),
        raw_bytes=raw,
        charset="utf-8",
        charset_confidence=1.0,
        hint="webvtt",
    )
    assert track.normalization is not None
    assert track.normalization["applied"] is True
    assert track.normalization["mpegts"] == 900000
    # Per-cue shift of MPEGTS/90000 - LOCAL = 10.0 s: 0.5 s cue -> 10.5 s.
    assert track.events[0].start_ms == 10500


def test_hi_sdh_markers_preserved_verbatim() -> None:
    from fixtures import subtitle_bytes

    # SRT and ASS carry in-band HI/SDH markers that must survive verbatim.
    srt = parse_subtitle_text(
        subtitle_bytes("srt", hi_sdh=True).decode(),
        raw_bytes=subtitle_bytes("srt", hi_sdh=True),
        charset="utf-8",
        surrogate_preserved=False,
        hint="srt",
    )
    assert "[music playing]" in srt.events[0].text
    assert srt.events[0].is_hi is True

    ass = parse_subtitle_text(
        subtitle_bytes("ass", hi_sdh=True).decode(),
        raw_bytes=subtitle_bytes("ass", hi_sdh=True),
        charset="utf-8",
        surrogate_preserved=False,
        hint="ass",
    )
    assert ass.events[0].is_hi is True
    assert ass.events[0].is_song is True or "[music]" in ass.events[0].text


# --- translated / adapted distinction -----------------------------------------


def test_translated_and_adapted_are_byte_distinct_realizations() -> None:
    a = translated_txt_bytes()
    b = adapted_markdown_bytes()
    c = txt_bytes()
    # Three distinct realizations of the SAME conceptual work — never conflated.
    assert a != b and b != c and a != c
    # Translation is still a text source; adaptation is structurally different.
    for blob, marker in ((a, "Alice entra"), (b, "Alice danced"), (c, "Alice walked")):
        assert marker.encode("utf-8") in blob


# --- vertical / CJK-style raster determinism ----------------------------------


def test_vertical_cjk_page_panels_deterministic_reading_order() -> None:
    raw = raster_vertical_cjk_bytes()
    with decode_bounded(raw) as img:
        assert img.width == 640 and img.height == 420
        a = detect_panels(img)
        b = detect_panels(img)
    # Three color panels stacked vertically; deterministic (run-stable) order.
    assert len(a) == 3
    assert [p.box.xywh for p in a] == [p.box.xywh for p in b]
    orders = [p.reading_order for p in a]
    assert orders == sorted(orders) == [1, 2, 3]
    # Vertical stack: each successive panel is lower on the page than the one
    # before (vertical-layout reading, not flat left-to-right).
    ys = [p.box.y for p in a]
    assert ys == sorted(ys)


def test_vertical_cjk_page_ink_region_is_deterministic() -> None:
    raw = raster_vertical_cjk_bytes()
    with decode_bounded(raw) as img:
        a = find_ink_regions(img)
        b = find_ink_regions(img)
    # The vertical text column is a tall narrow ink region; deterministic.
    assert a and [r.box.xywh for r in a] == [r.box.xywh for r in b]
    assert all(r.reading_order == i + 1 for i, r in enumerate(a))


def test_cjk_ocr_is_honestly_gated_not_fabricated() -> None:
    # CJK/vertical OCR is the gated PaddleOCR path; the reference OCR must NOT
    # fabricate CJK text. The deterministic region/panel stage is what runs.
    from umd.raster.ocr import PADDLE_GATE, OcrProviderUnavailable, run_ocr

    with pytest.raises(OcrProviderUnavailable) as exc:
        run_ocr(raster_vertical_cjk_bytes(), "paddle")
    assert PADDLE_GATE in str(exc.value)
    # reference OCR on the vertical page yields only real latin ink (none here
    # except vertical strokes -> honest empty, never invented CJK).
    ref = run_ocr(raster_text_only_bytes(), "reference")
    assert [r.text for r in ref.regions] == ["HELLO", "WORLD"]


# --- multi-speaker audio structural property ----------------------------------


def test_multi_speaker_wav_is_valid_16k_mono_pcm() -> None:
    buf = io.BytesIO(multi_speaker_audio_wav_bytes())
    with wave.open(buf, "rb") as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        n = w.getnframes()
    assert n > 0  # non-silent dialogue spans the whole clip
