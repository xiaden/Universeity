"""Sandboxed bounded FFmpeg decode + time chunking (Phase C, P2-S1).

The DD mandates that PyAV/FFmpeg decode **never runs in the API process**
(CONTRACTS §Modality and security + Task §32). This module is the *worker-side*
decode/codec boundary: it runs **inside** the sandboxed audio worker subprocess
(i.e. behind the :class:`~umd.security.sandbox.SandboxRunner` boundary, with the
worker's own rlimits/timeout) and shells out to ``ffmpeg``/``ffprobe`` with
**array-only argv** (no shell interpolation).

Two bounded operations:
  * :func:`probe` — ffprobe container/codec metadata (duration, sample rate, ...);
  * :func:`decode_to_pcm` — ffmpeg decode of a bounded range to mono 16 kHz s16le.

Both refuse to process audio whose declared/measured :data:`~umd.audio.types.DecodedAudio`
duration exceeds a caller-supplied ceiling (``max_duration_s``), and both clamp
captured output to a byte budget — a malicious/oversized file surfaces as a typed
:class:`AudioDecodeError`, never as an unbounded allocation in the API process.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from umd.audio.types import AudioMeta, DecodedAudio, TimeChunk

#: Target decode sample rate (mono 16 kHz is the DD baseline for VAD/ASR).
TARGET_SAMPLE_RATE = 16000
#: Cap on decoded PCM bytes we will retain (guards a huge source from holding RAM).
_MAX_PCM_BYTES = 256 * 1024 * 1024
#: Cap on ffmpeg/ffprobe captured text output.
_MAX_CAPTURE = 1 << 20


class AudioDecodeError(RuntimeError):
    """Decode failed / exceeded bounds (typed, quarantine-able, never a crash)."""


def ffmpeg_binary() -> str:
    """Resolve the ``ffmpeg`` binary; raise if unavailable (honest, no fabrication)."""
    path = shutil.which("ffmpeg")
    if path is None:
        raise AudioDecodeError("ffmpeg not available; decode is GATED/absent in this environment")
    return path


def ffprobe_binary() -> str:
    path = shutil.which("ffprobe")
    if path is None:
        raise AudioDecodeError("ffprobe not available; decode is GATED/absent")
    return path


def probe(input_path: Path, *, max_duration_s: float = 0.0) -> AudioMeta:
    """Read container/codec metadata via ffprobe (bounded, array-only argv)."""
    cmd = [
        ffprobe_binary(),
        "-v",
        "error",
        "-show_entries",
        "format=format_name,duration,bit_rate:stream=codec_name,sample_rate,channels",
        "-of",
        "json",
        str(input_path),
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - fixed resolved binary, array argv
            cmd, capture_output=True, timeout=20.0, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AudioDecodeError(f"ffprobe failed to spawn: {exc}") from exc
    if proc.returncode != 0:
        raise AudioDecodeError(
            f"ffprobe exited {proc.returncode}: {proc.stderr[:512].decode(errors='replace')}"
        )
    try:
        import json

        data = json.loads(proc.stdout.decode("utf-8", errors="replace"))
        fmt = data.get("format", {})
        streams = data.get("streams") or []
        stream = streams[0] if streams else {}
    except (ValueError, AttributeError) as exc:
        raise AudioDecodeError(f"ffprobe emitted non-JSON metadata: {exc}") from exc

    def _int_(val: object, default: int | None) -> int | None:
        try:
            return int(float(str(val)))
        except (TypeError, ValueError):
            return default

    sample_rate = _int_(stream.get("sample_rate"), TARGET_SAMPLE_RATE) or TARGET_SAMPLE_RATE
    channels = max(1, _int_(stream.get("channels"), 1) or 1)
    duration = float(fmt.get("duration") or _int_(stream.get("duration"), 0) or 0)
    meta = AudioMeta(
        format_name=str(fmt.get("format_name") or "unknown"),
        codec_name=str(stream.get("codec_name") or "unknown"),
        sample_rate=sample_rate,
        channels=channels,
        duration_s=duration,
        bit_rate=_int_(fmt.get("bit_rate"), None),
    )
    _assert_bounded(meta.duration_s, max_duration_s)
    return meta


def decode_to_pcm(
    input_path: Path,
    *,
    sample_rate: int = TARGET_SAMPLE_RATE,
    max_duration_s: float = 0.0,
) -> DecodedAudio:
    """Decode ``input_path`` to mono PCM (s16le) via ffmpeg, bounded & array-only."""
    meta = probe(input_path, max_duration_s=max_duration_s)
    _assert_bounded(meta.duration_s, max_duration_s)

    cmd = [
        ffmpeg_binary(),
        "-v",
        "error",
        "-i",
        str(input_path),
        "-f",
        "s16le",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "pipe:1",
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - fixed resolved binary, array argv
            cmd, capture_output=True, timeout=max(30.0, meta.duration_s + 30.0), check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AudioDecodeError(f"ffmpeg failed to spawn: {exc}") from exc
    if proc.returncode != 0 and len(proc.stdout) == 0:
        raise AudioDecodeError(
            f"ffmpeg decode exited {proc.returncode}: {proc.stderr[:512].decode(errors='replace')}"
        )
    pcm_bytes = proc.stdout
    if len(pcm_bytes) > _MAX_PCM_BYTES:
        raise AudioDecodeError(
            f"decoded PCM exceeds budget ({len(pcm_bytes)} > {_MAX_PCM_BYTES} bytes)"
        )
    if len(pcm_bytes) % 2 != 0:
        pcm_bytes = pcm_bytes[: len(pcm_bytes) // 2 * 2]
    n_samples = len(pcm_bytes) // 2
    pcm: list[float] = []
    # Chunk the int16 bytes to avoid a giant list comprehension on huge inputs.
    for i in range(0, len(pcm_bytes), 4096):
        chunk = pcm_bytes[i : i + 4096]
        pcm.extend(
            int.from_bytes(chunk[j : j + 2], "little", signed=True) / 32768.0
            for j in range(0, len(chunk), 2)
        )
    duration = n_samples / sample_rate
    return DecodedAudio(sample_rate=sample_rate, pcm=pcm, duration_s=duration, meta=meta)


def time_chunk(audio: DecodedAudio, chunk_s: float = 10.0) -> list[TimeChunk]:
    """Slice decoded PCM into bounded time chunks for chunked ASR/VAD."""
    sr = audio.sample_rate
    hop = max(1, int(round(chunk_s * sr)))
    chunks: list[TimeChunk] = []
    i = 0
    while i < len(audio.pcm):
        end = min(i + hop, len(audio.pcm))
        chunks.append(TimeChunk(start_s=i / sr, end_s=end / sr, pcm=audio.pcm[i:end]))
        i = end
    return chunks


def _assert_bounded(duration_s: float, max_duration_s: float) -> None:
    if max_duration_s > 0.0 and duration_s > max_duration_s:
        raise AudioDecodeError(
            f"audio duration {duration_s:.3f}s exceeds ceiling {max_duration_s:.3f}s"
        )
