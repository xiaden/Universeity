"""Deterministic tone codec + fixture synthesizer for the reference ASR (P2-S1/S5).

The v1 audio baseline is the DD's *bounded* baseline: sandboxed FFmpeg decode +
VAD-before-ASR + reference ASR. Because faster-whisper requires model weights
(heavy / GATED — see :mod:`umd.audio.asr`), the hermetic, non-gated baseline is
:class:`~umd.audio.asr.ReferenceAsrProvider` ``umd-reference-asr``.

This module is the **shared renderer + codec** the reference ASR and the test
fixture synthesizer both use (mirroring how Plan B's ``umd-reference-ocr`` and
its fixtures share a glyph renderer). A *word* is rendered deterministically as a
sequence of fixed-slot pure tones (one frequency per character), and decoded back
by measuring each slot's dominant frequency via zero-crossings. The reference ASR
therefore genuinely processes the audio bytes — it never invents transcript text
for audio it did not receive. For audio that does not match the codec it emits an
honest ``unmapped`` marker (transcription-scoped, never a claim of truth).

Everything here is pure stdlib DSP (no numpy/audio deps): arithmetic over float
sample lists. Bounded and deterministic by construction.
"""

from __future__ import annotations

import math

#: Default sample rate the baseline decodes to (+ synthesizer renders at).
DEFAULT_SAMPLE_RATE = 16000
#: Duration of one character (letter) **tone burst**, in seconds.
LETTER_S = 0.09
#: Intra-word silence between letter bursts in a word, in seconds.
BURST_GAP_S = 0.015
#: Extra inter-word silence inserted between words (kept > BURST_GAP so the word
#: detector can separate words by gap size), in seconds.
WORD_GAP_S = 0.16
#: Whole-word amplitude envelope fade duration, in seconds (avoid clicks).
FADE_S = 0.006
#: Peak amplitude of rendered speech (well below clipping so music/noise stack).
SPEECH_AMP = 0.35

#: Character set the codec can encode/decode (lowercase letters + digits).
_CHARS = "abcdefghijklmnopqrstuvwxyz" + "0123456789"
#: Base frequency of the first character slot; each subsequent char adds ``_STEP``.
_BASE_FREQ = 800.0
_STEP = 40.0

CHAR_TO_FREQ: dict[str, float] = {
    ch: _BASE_FREQ + float(ord(ch) - ord(_CHARS[0]) if ch in _CHARS else 0) * _STEP for ch in _CHARS
}
#: Inverse map used by the decoder (nearest-frequency character resolution).
_FREQ_BY_VALUE: dict[float, str] = {v: k for k, v in CHAR_TO_FREQ.items()}

#: Music reference frequency used by the synthesizer's ``music_under_speech``
#: mode. It sits at a codec midpoint (strictly >tolerance from every character
#: slot: y=1760, z=1800) so a music-dominant burst decodes as ambiguous => the
#: reference ASR reports low confidence and the hallucination filter flags it.
MUSIC_FREQ = 1780.0


def char_frequency(ch: str) -> float:
    """The slot frequency for a single codec character (0.0 for space/silence)."""
    if not ch:
        return 0.0
    ch = ch.lower()
    if ch == " " or ch not in CHAR_TO_FREQ:
        return 0.0
    return CHAR_TO_FREQ[ch]


def nearest_char(freq: float, tolerance: float = 15.0) -> str | None:
    """Map a measured frequency to the nearest codec character, if within tolerance.

    Tolerance is held strictly below half the 40 Hz codec step (20 Hz), so a
    frequency falling between two slots (e.g. a music-overlaid burst) resolves to
    ``None`` (ambiguous) and lowers the reference decode confidence — an honest
    low-confidence signal rather than a forced guess.
    """
    best: tuple[float, str] | None = None
    for target, ch in _FREQ_BY_VALUE.items():
        dist = abs(freq - target)
        if dist <= tolerance and (best is None or dist < best[0]):
            best = (dist, ch)
    return best[1] if best else None


def slots_for(word: str) -> list[str]:
    """Normalize ``word`` to a codec slot sequence (space -> silence slot)."""
    out: list[str] = []
    for ch in word.lower():
        if ch in _CHARS:
            out.append(ch)
        elif ch.isspace():
            out.append(" ")
    return out


def _tone(freq: float, duration_s: float, sample_rate: int, amp: float) -> list[float]:
    n = int(round(duration_s * sample_rate))
    phase = 2.0 * math.pi * freq / sample_rate
    return [amp * math.sin(phase * t) for t in range(n)]


def _silence(duration_s: float, sample_rate: int) -> list[float]:
    return [0.0] * int(round(duration_s * sample_rate))


def _apply_fade(samples: list[float], sample_rate: int) -> list[float]:
    hemi = int(round(FADE_S * sample_rate))
    if hemi <= 0 or len(samples) < 2 * hemi:
        return samples
    out = list(samples)
    for i in range(hemi):
        env = i / hemi
        out[i] *= env
        out[-1 - i] *= env
    return out


def _letter_burst(ch: str, sample_rate: int, *, amp: float) -> list[float]:
    """One letter = a short tone burst followed by a small intra-word silence gap.

    The tone portion is the *burst*; its trailing silence is what makes the word
    detector treat each letter as one discrete energy block (no slot-alignment
    needed) while keeping words separable from larger gaps.
    """
    f = char_frequency(ch)
    tone_part = _tone(f, LETTER_S, sample_rate, amp) if f > 0 else _silence(LETTER_S, sample_rate)
    return tone_part + _silence(BURST_GAP_S, sample_rate)


def render_word(
    word: str,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    *,
    amp: float = SPEECH_AMP,
) -> list[float]:
    """Render ``word`` as a run of letter tone-bursts (each followed by a gap)."""
    samples: list[float] = []
    for ch in slots_for(word):
        samples.extend(_letter_burst(ch, sample_rate, amp=amp))
    return samples


def render_phrase(words: list[str], sample_rate: int = DEFAULT_SAMPLE_RATE) -> list[float]:
    """Render several words separated by a larger inter-word silence gap."""
    out: list[float] = []
    for i, word in enumerate(words):
        if i > 0:
            # The preceding word already ends with BURST_GAP; add the rest so the
            # total inter-word gap is held large enough to separate words.
            extra = max(0.0, WORD_GAP_S - BURST_GAP_S)
            out.extend(_silence(extra, sample_rate))
        out.extend(render_word(word, sample_rate))
    return out


def render_silence(duration_s: float, sample_rate: int = DEFAULT_SAMPLE_RATE) -> list[float]:
    """A pure-silence segment (VAD no-speech / silence fixtures)."""
    return [0.0] * int(round(duration_s * sample_rate))


def render_noise(
    duration_s: float, sample_rate: int = DEFAULT_SAMPLE_RATE, *, amp: float = 0.15
) -> list[float]:
    """Deterministic white-noise burst (SFX / sound-event fixture)."""
    seed = 0x5DEECE66D
    mask = (1 << 48) - 1
    out: list[float] = []
    count = int(round(duration_s * sample_rate))
    for _ in range(count):
        seed = (seed * 0x5DEECE66D + 0xB) & mask
        out.append((seed / (1 << 48)) * 2.0 - 1.0)
    return [amp * s for s in out]


def render_music(
    duration_s: float, sample_rate: int = DEFAULT_SAMPLE_RATE, *, amp: float = 0.18
) -> list[float]:
    """A sustained tone representing background music (tonal, low onset variance)."""
    return _apply_fade(_tone(MUSIC_FREQ, duration_s, sample_rate, amp), sample_rate)


def overlay_music(
    samples: list[float],
    start_s: float,
    duration_s: float,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> list[float]:
    """Mix a sustained music tone under ``samples`` beginning at ``start_s``.

    Sample-wise **max-select**: wherever the music tone's amplitude exceeds the
    underlying signal, that sample is replaced by the tone. This models loud music
    dominating the acoustic mix — the reference ASR then reads a non-codec tone
    in the overlapped word (ambiguous) and the hallucination filter flags it.
    """
    out = list(samples)
    music = render_music(duration_s, sample_rate, amp=0.5)
    start = int(round(start_s * sample_rate))
    for i, m in enumerate(music):
        idx = start + i
        if idx >= len(out):
            break
        if abs(m) >= abs(out[idx]):
            out[idx] = m
    return out


def render_mixed(
    segments: list[tuple[str, float, float]],
    duration_s: float | None = None,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> list[float]:
    """Mix heterogeneous audio segments into one timeline.

    ``segments`` entries are ``(channel, offset_s, payload)`` where ``channel`` is
    one of ``"phrase"``, ``"silence"``, ``"noise"``, ``"music"`` and ``payload`` is
    either a ``list[float]`` (pre-rendered) or a duration ``float``. Useful for
    assembling complex fixtures from the shared renderer.
    """
    rendered: list[list[float]] = []
    for _kind, offset, payload in segments:
        if isinstance(payload, (int, float)):
            blk: list[float] = _silence(float(payload), sample_rate)
        else:
            blk = list(payload)
        pad = int(round(offset * sample_rate))
        rendered.append([0.0] * pad + blk)
    if not rendered:
        return []
    max_len = max(len(r) for r in rendered)
    out = [0.0] * max_len
    for r in rendered:
        for i, v in enumerate(r):
            out[i] += v
    peak = max((abs(v) for v in out), default=0.0)
    if peak > 1.0:
        out = [v / peak for v in out]
    if duration_s is not None and len(out) < int(round(duration_s * sample_rate)):
        out.extend([0.0] * (int(round(duration_s * sample_rate)) - len(out)))
    return out


def to_pcm16(samples: list[float]) -> bytes:
    """Convert float samples in [-1,1] to little-endian signed 16-bit PCM bytes."""
    out = bytearray()
    for v in samples:
        clamped = max(-1.0, min(1.0, v))
        out.extend(int(clamped * 32767).to_bytes(2, "little", signed=True))
    return bytes(out)


def dominant_frequency(samples: list[float], sample_rate: int = DEFAULT_SAMPLE_RATE) -> float:
    """Estimate the dominant frequency via zero-crossing rate (pure DSP)."""
    n = len(samples)
    if n < 4:
        return 0.0
    crossings = 0
    prev = samples[0]
    for v in samples[1:]:
        if (prev < 0.0 <= v) or (v < 0.0 <= prev):
            crossings += 1
        prev = v
    return crossings / (2.0 * (n / sample_rate))


def slot_energy(samples: list[float]) -> float:
    """RMS energy of a sample run (0..1 scale)."""
    if not samples:
        return 0.0
    return math.sqrt(sum(v * v for v in samples) / len(samples))


def rms_energy(samples: list[float]) -> float:
    """Alias for :func:`slot_energy` (acoustic-energy correlation uses RMS)."""
    return slot_energy(samples)
