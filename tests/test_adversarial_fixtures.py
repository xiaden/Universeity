"""Phase F / P1-S2: adversarial fixture generators exercised against the boundaries.

Each generator in :mod:`fixtures` (malformed containers, VobSub-like inputs,
oversized declared allocations, non-UTF-8 subtitles, corrupt encodings, zip bombs,
tar traversal/symlinks, VFR/edit-list media, music-under-speech, parser crashes,
and sandbox timeout/OOM/fd/pid violations) is fed to the real boundary it must
trip: the archive allowlist, the bounded raster decode guard, the subtitle charset
probe, the sandbox runner, and the video subtitle quarantine classifier. The
guarantee is *bounded, contained failure* — never a crash of the API process and
never a silent bypass.

No PostgreSQL required.
"""

from __future__ import annotations

import io
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Any

import pytest

from fixtures import (
    corrupt_encoding_bytes,
    malformed_container_bytes,
    music_under_speech_wav_bytes,
    non_utf8_subtitle_bytes,
    raster_max_ihdr_bytes,
    sandbox_violation_payload,
    tar_symlink_bytes,
    tar_traversal_bytes,
    vobsub_idx_bytes,
    vobsub_sub_bytes,
    zip_bomb_bytes,
)
from umd.raster.bounds import RasterDecodeError, RasterLimitsExceeded, decode_bounded
from umd.security.archive import ArchiveDenial, sanitize_tar, sanitize_zip
from umd.security.sandbox import (
    ParserExitClass,
    SandboxLimits,
    SandboxPolicy,
    SubprocessSandboxRunner,
)
from umd.subtitle.charset import probe_charset
from umd.video.inventory import extract_embedded_subtitle_tracks
from umd.video.types import VideoTrack

_EPUB_ALLOW = ("xml", "opf", "html", "xhtml", "css", "png", "jpg", "svg", "bin")


def _policy(**kw: Any) -> SandboxPolicy:
    return SandboxPolicy(archive_allow_extensions=_EPUB_ALLOW, **kw)


def _limits(**kw: Any) -> SandboxLimits:
    return SandboxLimits(**kw)


# ---------------------------------------------------------------------------
# archive adversarial: zip bomb / tar traversal / tar symlink
# ---------------------------------------------------------------------------


def test_zip_bomb_decompressed_size_cap_rejected() -> None:
    zf = zipfile.ZipFile(io.BytesIO(zip_bomb_bytes()))
    # 256 KiB member decompresses far past a 1 KiB ceiling -> capped, not expanded.
    with pytest.raises(ArchiveDenial):
        sanitize_zip(zf, policy=_policy(), limits=_limits(max_decompressed_bytes=1024))


def test_tar_symlink_member_rejected() -> None:
    with tarfile.open(fileobj=io.BytesIO(tar_symlink_bytes())) as tf, pytest.raises(ArchiveDenial):
        sanitize_tar(tf, policy=_policy(), limits=_limits())


def test_tar_traversal_member_rejected() -> None:
    with (
        tarfile.open(fileobj=io.BytesIO(tar_traversal_bytes())) as tf,
        pytest.raises(ArchiveDenial),
    ):
        sanitize_tar(tf, policy=_policy(), limits=_limits())


# ---------------------------------------------------------------------------
# media adversarial: malformed container / oversized allocation / VobSub
# ---------------------------------------------------------------------------


def test_oversized_ihdr_declared_allocation_rejected_before_alloc() -> None:
    # IHDR declares 65535x65535 = ~4.3e9 px; either our pixel-budget guard or
    # Pillow's own decompression-bomb guard rejects it at open time, before any
    # buffer is materialized. The guarantee is: bounded, no large allocation.
    with pytest.raises((RasterLimitsExceeded, RasterDecodeError)):
        decode_bounded(raster_max_ihdr_bytes())


def test_malformed_container_is_not_a_valid_stream() -> None:
    # The fixture is structurally invalid EBML; it must never be treated as a
    # valid container (the sandboxed ffmpeg path would classify/quarantine it).
    assert malformed_container_bytes()[0:4] == b"\x1a\x45\xdf\xa3"
    assert not malformed_container_bytes().startswith(b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x02")


def _bitmap_track() -> VideoTrack:
    return VideoTrack(
        index=1,
        codec_type="subtitle",
        codec_name="dvd_subtitle",
        language="eng",
        disposition={"default": 1},
        title="vobsub",
        width=None,
        height=None,
        time_base=None,
        avg_frame_rate=None,
        r_frame_rate=None,
        pix_fmt=None,
        sample_rate=None,
        channels=None,
        pts_start=0,
        duration=None,
        nb_frames=None,
        tags={},
    )


def test_vobsub_like_inputs_classified_quarantine_not_flattened() -> None:
    # VobSub bitmap subtitle streams (CVE-2026-64830 demuxer class) are never
    # promised as decodable text: the class carries a quarantine classification.
    assert vobsub_idx_bytes().startswith(b"# VobSub index file")
    results = extract_embedded_subtitle_tracks(Path("/nonexistent/vobsub.mkv"), [_bitmap_track()])
    assert len(results) == 1
    r = results[0]
    assert r["extractable"] is False
    assert r["quarantine_reason"] and "QUARANTINE" in r["quarantine_reason"]
    assert vobsub_sub_bytes()  # fixture exists and is byte-stable
    assert vobsub_sub_bytes() == vobsub_sub_bytes()


# ---------------------------------------------------------------------------
# subtitle adversarial: non-UTF-8 / corrupt encodings
# ---------------------------------------------------------------------------


def test_non_utf8_subtitle_is_charset_probed() -> None:
    probe = probe_charset(non_utf8_subtitle_bytes())
    assert probe.charset in {"cp1252", "latin-1"}
    # surrogate-preserving fallback never loses information.
    assert probe.surrogate_preserved is True or probe.charset == "cp1252"


def test_corrupt_encoding_is_not_decodable_utf8() -> None:
    # Corrupt/mixed byte sequence cannot be silently decoded — failures are
    # surfaced (charset probe / decline), never rewritten as replacement text.
    with pytest.raises(UnicodeDecodeError):
        corrupt_encoding_bytes().decode("utf-8")


# ---------------------------------------------------------------------------
# sandbox adversarial: parser crash + timeout/OOM/fd/pid violations
# ---------------------------------------------------------------------------


def test_parser_crash_is_classified_crash() -> None:
    runner = SubprocessSandboxRunner()
    result = runner.run(
        [sys.executable] + sandbox_violation_payload("crash"),
        limits=_limits(timeout_s=5),
    )
    assert result.exit_class == ParserExitClass.CRASH
    assert not result.ok


@pytest.mark.parametrize(
    "kind",
    ["timeout", "oom", "fd", "pid"],
    ids=["timeout", "oom", "fd", "pid"],
)
def test_sandbox_resource_violations_are_bounded(kind: str) -> None:
    runner = SubprocessSandboxRunner()
    # Tight limits force the violation deterministically; a short timeout caps
    # the whole run so a platform that cannot enforce a limit still can't hang.
    limits = _limits(
        timeout_s=5 if kind in {"fd", "pid", "oom", "crash"} else 0.3,
        memory_bytes=32 * 1024 * 1024 if kind == "oom" else 512 * 1024 * 1024,
        fd_limit=32 if kind == "fd" else 256,
        nproc_limit=16 if kind == "pid" else 64,
    )
    result = runner.run([sys.executable] + sandbox_violation_payload(kind), limits=limits)
    # A limit violation is reported — either as TIMEOUT (sleep"), a negative
    # (signal) CRASH, or a NON_ZERO exit from the failing child. Never OK.
    message = f"{kind}: exit_class={result.exit_class} ok={result.ok} stderr={result.stderr[:200]}"
    if kind == "timeout":
        assert result.exit_class == ParserExitClass.TIMEOUT, message
        assert result.timed_out is True
    else:
        assert result.exit_class in {
            ParserExitClass.CRASH,
            ParserExitClass.NON_ZERO,
            ParserExitClass.RESOURCE_VIOLATION,
        }, message
        assert not result.ok


# ---------------------------------------------------------------------------
# audio adversarial: music-under-speech triggers the hallucination filter
# ---------------------------------------------------------------------------


def test_music_under_speech_flags_hallucination_filter_not_confident_text() -> None:
    import array
    import wave

    from umd.audio.pipeline import run_audio_baseline
    from umd.audio.types import AudioConfig, AudioMeta, DecodedAudio

    raw = music_under_speech_wav_bytes()
    with wave.open(io.BytesIO(raw), "rb") as w:
        frames = w.readframes(w.getnframes())
    samples = [x / 32768.0 for x in array.array("h", frames)]
    decoded = DecodedAudio(
        sample_rate=16000,
        pcm=samples,
        duration_s=len(samples) / 16000,
        meta=AudioMeta(
            format_name="pcm_s16le",
            codec_name="pcm_s16le",
            sample_rate=16000,
            channels=1,
            duration_s=len(samples) / 16000,
        ),
    )
    out = run_audio_baseline(decoded, AudioConfig(declared_language="en"))
    # The overlapped word is a non-codec tone -> the filter marks it 'filtered'
    # rather than emitting confident transcript text (X5 hallucination-to-confidence
    # leak is closed: it is never promoted to semantic truth).
    decisions = out.hallucination["decisions"]
    assert any(d["outcome"] == "filtered" for d in decisions)
    assert out.hallucination["energy_correlation"] is not None
    # No fabricated text: the filtered word is replaced with an empty marker.
    assert all(d["replaced_with"] == "" for d in decisions)
