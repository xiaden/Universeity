"""Provider-adapted ASR — reference (non-gated) + faster-whisper (GATED) (P2-S1).

The DD baseline is faster-whisper with explicit decoder settings and word
timestamps, but heavier use (faster-whisper) is **GATED** behind model weights/
config (DD §Limitations; Plan C gate policy). The hermetic, non-gated ASR is the
:class:`ReferenceAsrProvider` ``umd-reference-asr``, which:

  * runs after VAD (``condition_on_previous_text=False``-equivalent: each word is
    decoded independently from its own acoustic run — never chained across
    previous context, which is one of the four hallucination controls);
  * splits each speech segment into word time-runs on real energy gaps (word/time
    ranges);
  * decodes each word's dominant-frequencies through the shared codec
    (:mod:`umd.audio.tone`) — *genuine* audio processing, never fabricated;
  * emits transcription-scoped confidence (about the acoustic decode, not
    semantic truth) and an honest ``unmapped`` marker for non-codec audio.

``FasterWhisperAsrProvider`` is the GATED adapter: it raises
:class:`AsrProviderUnavailable` (typed, reported, never fabricated) unless
``config.asr_engine == "faster-whisper"`` **and** a weights directory is
configured and the model is installed.
"""

from __future__ import annotations

from typing import Protocol

from umd.audio import language, music, tone, vad
from umd.audio.types import (
    AsrResult,
    AsrUtterance,
    AsrWord,
    AudioConfig,
    DecodedAudio,
    MusicRegion,
)

NO_LEXICAL_MAP = "<unmapped>"


class AsrProviderUnavailable(RuntimeError):  # noqa: N818 - stable contract name
    """ASR provider could not be used (gated / weights absent / not installed)."""


class AsrProvider(Protocol):
    """The provider-adapted ASR seam (transcription-scoped confidence)."""

    name: str
    provider_version: str

    def asr(self, audio: DecodedAudio, *, config: AudioConfig) -> AsrResult: ...


class ReferenceAsrProvider:
    """Deterministic, non-gated reference ASR (``umd-reference-asr v1.0``)."""

    name = "umd-reference-asr"
    provider_version = "umd-reference-asr v1.0"

    def asr(self, audio: DecodedAudio, *, config: AudioConfig) -> AsrResult:
        lang = language.identify_language(
            audio,
            declared_language=config.declared_language,
            config_language=config.config_language,
        )
        vres = vad.detect_speech(audio)
        music_regions, _sfx = music.detect_music_and_sfx(audio)

        utterances: list[AsrUtterance] = []
        unmapped = 0
        for _sidx, seg in enumerate(vres.speech_segments):
            words = _words_in_segment(audio.pcm, seg.start_s, seg.end_s, audio.sample_rate)
            text_parts: list[str] = []
            asr_words: list[AsrWord] = []
            for wstart, wend, word, conf in words:
                asr_words.append(AsrWord(word=word, start_s=wstart, end_s=wend, confidence=conf))
                text_parts.append(word)
                if word == NO_LEXICAL_MAP or "?" in word:
                    unmapped += 1
            if not asr_words:
                continue
            text = " ".join(text_parts)
            utt_conf = sum(w.confidence for w in asr_words) / len(asr_words)
            music_suspected = _overlaps_music(seg.start_s, seg.end_s, music_regions)
            utterances.append(
                AsrUtterance(
                    index=len(utterances) + 1,
                    text=text,
                    start_s=seg.start_s,
                    end_s=seg.end_s,
                    words=asr_words,
                    confidence=utt_conf,
                    language=lang.language,
                    music_suspected=music_suspected,
                )
            )

        asr_conf = (
            sum(u.confidence * u.duration_s for u in utterances)
            / sum(u.duration_s for u in utterances)
            if utterances
            else 0.0
        )
        return AsrResult(
            provider=self.name,
            provider_version=self.provider_version,
            language=lang.language if lang.language != "unknown" else None,
            utterances=utterances,
            confidence=asr_conf,
            energy_correlation=_energy_correlation(audio, utterances),
            unmapped_count=unmapped,
            warnings=(
                [f"reference ASR has no lexical map for {unmapped} word(s)"] if unmapped else []
            ),
        )


class FasterWhisperAsrProvider:
    """GATED faster-whisper adapter (never active without weights/config)."""

    name = "faster-whisper"
    provider_version = "faster-whisper gated"

    def asr(self, audio: DecodedAudio, *, config: AudioConfig) -> AsrResult:
        del audio  # unused until the trained runtime is wired behind the gate
        if config.asr_engine != "faster-whisper":
            raise AsrProviderUnavailable(
                "faster-whisper is GATED: UMD_ASR_ENGINE != 'faster-whisper'"
            )
        if not config.asr_model_dir:
            raise AsrProviderUnavailable("faster-whisper is GATED: no weight/model dir configured")
        raise AsrProviderUnavailable(
            "faster-whisper configured but trained runtime is not wired; engine stays GATED"
        )


ASR_PROVIDERS: dict[str, AsrProvider] = {
    "reference": ReferenceAsrProvider(),
}


def run_asr(audio: DecodedAudio, *, config: AudioConfig) -> AsrResult:
    """Dispatch ASR by ``config.asr_engine`` (reference default; faster-whisper GATED).

    The faster-whisper engine is GATED and raises :class:`AsrProviderUnavailable`
    while it is not wired. We catch it and return the honest reference transcript
    explicitly marked ``gated=True`` with the gate reason, so a naive caller is
    routed through capability reporting instead of an uncaught typed failure.
    """
    engine = config.asr_engine
    if engine == "faster-whisper":
        try:
            FasterWhisperAsrProvider().asr(audio, config=config)  # raises unless truly active
        except AsrProviderUnavailable as exc:
            result = ASR_PROVIDERS["reference"].asr(audio, config=config)
            return AsrResult(
                provider=result.provider,
                provider_version=result.provider_version,
                language=result.language,
                utterances=result.utterances,
                confidence=result.confidence,
                energy_correlation=result.energy_correlation,
                unmapped_count=result.unmapped_count,
                warnings=[*result.warnings, f"faster-whisper gated: {exc}"],
                gated=True,
                gate_reason=str(exc),
            )
    return ASR_PROVIDERS["reference"].asr(audio, config=config)


# ---------------------------------------------------------------------------
# Reference word segmentation / tone-codec decoding
# ---------------------------------------------------------------------------


def _frame_energy(pcm: list[float], sr: int, frame_s: float) -> list[float]:
    frame = max(1, int(round(frame_s * sr)))
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


def _words_in_segment(
    pcm: list[float], start_s: float, end_s: float, sr: int
) -> list[tuple[float, float, str, float]]:
    """Split a VAD speech segment into words and decode each via the tone codec.

    The reference audio codes each letter as a distinct tone **burst** followed by
    a small gap (:mod:`umd.audio.tone`). We detect the discrete bursts by fine
    energy frames, group bursts into words by gap size (intra-word gaps are small,
    inter-word gaps larger), and read each burst's dominant frequency -> character.
    Word timing ranges span the first burst start to the last burst end.
    """
    frame_s = 0.005
    fs = max(1, int(round(frame_s * sr)))
    s0 = max(0, int(round(start_s * sr)))
    s1 = min(len(pcm), int(round(end_s * sr)))
    seg = pcm[s0:s1]
    if not seg:
        return []
    energy = _frame_energy(seg, sr, frame_s)
    floor = max(music._adaptive_floor(energy), 1e-3) if energy else 1e-3
    active = [e > floor for e in energy]

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

    # Group bursts into words: a gap >= WORD_GAP_S starts a new word.
    words: list[list[tuple[int, int]]] = []
    for run in runs:
        if words and (run[0] * frame_s - words[-1][-1][1] * frame_s) < tone.WORD_GAP_S:
            words[-1].append(run)
        else:
            words.append([run])

    out: list[tuple[float, float, str, float]] = []
    for group in words:
        chars: list[str] = []
        n_matched = 0
        for a, b in group:
            burst = seg[a * fs : b * fs]
            freq = tone.dominant_frequency(burst, sr)
            ch = tone.nearest_char(freq)
            if ch is not None:
                n_matched += 1
                chars.append(ch)
            else:
                chars.append("?")
        word = "".join(chars)
        t0 = start_s + group[0][0] * frame_s
        t1 = start_s + group[-1][1] * frame_s
        conf = (n_matched / len(chars)) if chars else 0.0
        if not word:
            continue
        out.append((t0, t1, word if n_matched else NO_LEXICAL_MAP, conf))
    return out


#: Compatibility: for callers expecting a slot-based decode we reuse the burst
#: word decoder (a word is already the burst group by the time it reaches us).
def _decode_word(pcm_run: list[float], sr: int) -> tuple[str, float] | None:
    """Decode a single contiguous burst run (internal compat helper)."""
    if len(pcm_run) < 4:
        return None
    freq = tone.dominant_frequency(pcm_run, sr)
    ch = tone.nearest_char(freq)
    word = ch if ch is not None else "?"
    conf = 1.0 if ch is not None else 0.0
    return word, conf


def _overlaps_music(start_s: float, end_s: float, regions: list[MusicRegion]) -> bool:
    return any(not (r.end_s <= start_s or r.start_s >= end_s) for r in regions)


def _energy_correlation(audio: DecodedAudio, utterances: list[AsrUtterance]) -> float:
    """Fraction of ASR speech-time overlapping real acoustic energy (0..1).

    This is the *v3* "acoustic-energy correlation" guard: if ASR emitted speech
    where the reference VAD/energy found none, correlation falls below the
    threshold and the utterance is hallucination-flagged. Deterministic and
    honest (not detector-grade).
    """
    if not utterances:
        return 0.0
    vres = vad.detect_speech(audio)
    covered = 0.0
    total = 0.0
    for u in utterances:
        total += u.duration_s
        for seg in vres.speech_segments:
            lo = max(u.start_s, seg.start_s)
            hi = min(u.end_s, seg.end_s)
            if hi > lo:
                covered += hi - lo
    return covered / total if total else 0.0
