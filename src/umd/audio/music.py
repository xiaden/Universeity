"""Reference music/sound-event region detection (Phase C, P2-S1).

Deterministic acoustic heuristics over decoded PCM — *evidence* (music /
sound_event regions), never a music-classification model claim:

  * **music** — a sustained, low-variance (steady/tonal) moderate-energy region
    (DD: "music/sound regions"). Sustained energy with low frame-to-frame
    variance reads as continuous music/SFX-bed rather than speech transients.
  * **sound_event** — a short high-energy transient (an onset/burst) that is not
    part of a longer speech run.

Both are reference-provider findings (``umd-reference-music``) with honest
confidence, and both are recorded as evidence (``music`` / ``sound_event`` kinds)
— never promoted to semantic truth.
"""

from __future__ import annotations

from umd.audio.types import DecodedAudio, MusicRegion, SoundRegion

#: Frame length used by the region analysis (seconds).
_FRAME_S = 0.02
#: Minimum duration of a sustained region to label it music (seconds).
MIN_MUSIC_S = 0.25
#: Minimum gap so two active runs are split (seconds).
_SPLIT_GAP_S = 0.04
#: Energy floor below which a frame is "inactive" (relative 0..1 scale).
_ENERGY_FLOOR = 1e-3
#: Variance (relative to mean) below which a region reads as steady/tonal.
_LOW_VAR = 0.5
#: Confidence cap for the low-variance music heuristic (honest, not detector-grade).
_MUSIC_CONF = 0.6
#: Confidence for a clear transient burst.
_SFX_CONF = 0.55


def _frame_energy(pcm: list[float], sample_rate: int, frame_s: float) -> list[float]:
    frame = max(1, int(round(frame_s * sample_rate)))
    out: list[float] = []
    for i in range(0, len(pcm), frame):
        win = pcm[i : i + frame]
        if not win:
            continue
        acc = 0.0
        for v in win:
            acc += v * v
        out.append((acc / len(win)) ** 0.5)
    return out


def _active_runs(active: list[bool]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for i, on in enumerate(active):
        if on and start is None:
            start = i
        elif not on and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(active)))
    return runs


def detect_music_and_sfx(
    audio: DecodedAudio, *, frame_s: float = _FRAME_S
) -> tuple[list[MusicRegion], list[SoundRegion]]:
    """Return ``(music_regions, sound_regions)`` over decoded audio (reference)."""
    energy = _frame_energy(audio.pcm, audio.sample_rate, frame_s)
    floor = max(_ENERGY_FLOOR, _adaptive_floor(energy))
    active = [e > floor for e in energy]
    runs = _active_runs(active)

    gap_frames = max(1, int(round(_SPLIT_GAP_S / frame_s)))
    merged: list[tuple[int, int]] = []
    for r in runs:
        if merged and r[0] - merged[-1][1] <= gap_frames:
            prev = merged[-1]
            merged[-1] = (prev[0], max(prev[1], r[1]))
        else:
            merged.append(r)

    music: list[MusicRegion] = []
    sfx: list[SoundRegion] = []
    for start, end in merged:
        dur_s = (end - start) * frame_s
        window = energy[start:end] or [0.0]
        mean = sum(window) / len(window)
        var = (sum((e - mean) ** 2 for e in window) / len(window)) ** 0.5
        steady = var <= _LOW_VAR * max(mean, floor)
        t0 = start * frame_s
        t1 = end * frame_s
        if dur_s >= MIN_MUSIC_S and steady:
            music.append(MusicRegion(start_s=t0, end_s=t1, confidence=_MUSIC_CONF))
        elif dur_s < MIN_MUSIC_S:
            sfx.append(SoundRegion(start_s=t0, end_s=t1, kind="transient", confidence=_SFX_CONF))
    return music, sfx


def _adaptive_floor(energy: list[float]) -> float:
    if not energy:
        return 1e-3
    s = sorted(energy)
    return s[max(0, min(len(s) - 1, int(len(s) * 0.25)))]
