"""Reference VAD — genuine energy-based voice activity detection (Phase C, P2-S1).

VAD **precedes** ASR (DD §Audio: "VAD precedes ASR"). This is the deterministic,
non-gated reference VAD (``umd-reference-vad``): it binds decoded PCM to short
frames, computes RMS energy, derives an adaptive speech threshold (noise floor +
margin) and applies minimum-speech-duration + hangover so brief clicks never
register as speech and trailing energy is not chopped.

It is *genuine* signal processing on the decoded bytes (not fabricated), so the
no-speech fixture (pure silence) is correctly classified with
``has_speech == False`` — feeding hallucination *signal 1* (VAD/no-speech).
"""

from __future__ import annotations

from umd.audio.types import DecodedAudio, SpeechSegment, VadResult

#: Analysis frame length (seconds).
FRAME_S = 0.02
#: RMS below which a frame is "silent" relative to the adaptive floor margin.
_SILENCE_MARGIN = 2.5
#: Minimum contiguous speech duration to keep a segment (seconds).
MIN_SPEECH_S = 0.05
#: Hangover silence to append after a speech run (seconds).
HANGOVER_S = 0.04


def _rms_frames(pcm: list[float], sample_rate: int, frame_s: float = FRAME_S) -> list[float]:
    """Per-frame RMS energy of the PCM (overlap-free windows)."""
    frame_size = max(1, int(round(frame_s * sample_rate)))
    rms: list[float] = []
    for i in range(0, len(pcm), frame_size):
        win = pcm[i : i + frame_size]
        if not win:
            continue
        acc = 0.0
        for v in win:
            acc += v * v
        rms.append((acc / len(win)) ** 0.5)
    return rms


def _adaptive_threshold(rms: list[float]) -> float:
    """A floor+margin threshold: a low-percentile RMS (noise floor) times a margin."""
    if not rms:
        return 0.0
    sorted_rms = sorted(rms)
    floor = sorted_rms[max(0, min(len(sorted_rms) - 1, int(len(sorted_rms) * 0.1)))]
    return max(floor * _SILENCE_MARGIN, 1e-4)


def _speech_mask(rms: list[float], threshold: float, hangover_frames: int) -> list[bool]:
    """Speech-frame mask with hangover: trailing silence is appended to a run."""
    mask = [False] * len(rms)
    active = False
    last_speech = -1
    for i, e in enumerate(rms):
        if e >= threshold:
            last_speech = i
            active = True
        elif active and i - last_speech <= hangover_frames:
            active = True  # hangover keeps the run "on"
        else:
            active = False
        mask[i] = active
    return mask


def detect_speech(audio: DecodedAudio, *, frame_s: float = FRAME_S) -> VadResult:
    """Run reference VAD over decoded audio; return speech segments."""
    rms = _rms_frames(audio.pcm, audio.sample_rate, frame_s)
    if not rms:
        return VadResult()
    threshold = _adaptive_threshold(rms)
    hangover = max(1, int(round(HANGOVER_S / frame_s)))
    mask = _speech_mask(rms, threshold, hangover)

    segments: list[SpeechSegment] = []
    start_idx: int | None = None
    for i, on in enumerate(mask):
        if on and start_idx is None:
            start_idx = i
        elif not on and start_idx is not None:
            if (i - start_idx) * frame_s >= MIN_SPEECH_S:
                segments.append(_segment_from(rms, start_idx, i, frame_s))
            start_idx = None
    if start_idx is not None and (len(mask) - start_idx) * frame_s >= MIN_SPEECH_S:
        segments.append(_segment_from(rms, start_idx, len(mask), frame_s))

    merge_overlaps(segments)
    total = sum(s.duration_s for s in segments)
    no_speech = max(0.0, audio.duration_s - total)
    ratio = (no_speech / audio.duration_s) if audio.duration_s > 0 else 1.0
    return VadResult(speech_segments=segments, total_speech_s=total, no_speech_ratio=ratio)


def _segment_from(rms: list[float], start: int, end: int, frame_s: float) -> SpeechSegment:
    window = rms[start:end] or [0.0]
    return SpeechSegment(
        start_s=start * frame_s,
        end_s=end * frame_s,
        mean_energy=sum(window) / len(window),
        peak_energy=max(window),
    )


def merge_overlaps(segments: list[SpeechSegment]) -> None:
    """Merge adjacent/overlapping speech segments (in place)."""
    if not segments:
        return
    segments.sort(key=lambda s: (s.start_s, s.end_s))
    merged: list[SpeechSegment] = [segments[0]]
    for seg in segments[1:]:
        prev = merged[-1]
        if seg.start_s <= prev.end_s + 1e-6:
            prev.end_s = max(prev.end_s, seg.end_s)
            prev.peak_energy = max(prev.peak_energy, seg.peak_energy)
            prev.mean_energy = (prev.mean_energy + seg.mean_energy) / 2.0
        else:
            merged.append(seg)
    segments[:] = merged
