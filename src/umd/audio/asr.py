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

``FasterWhisperAsrProvider`` is the validated self-hostable ASR path (P2-S2/S3):
it loads the pinned model lazily from the cache dir with explicit DD decoder
settings and a music-aware beam policy, and runs only inside the sandboxed audio
worker. It raises :class:`AsrProviderUnavailable` (typed, reported, never
fabricated) unless ``config.asr_engine == "faster-whisper"``, the runtime is
installed, and a model cache dir is present.
"""

from __future__ import annotations

import importlib
import os
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Protocol, cast

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
    """faster-whisper ASR provider — lazy model load, explicit decoder settings.

    Genuine (never fabricated) speech-to-text. The pinned CTranslate2 model is
    loaded **lazily** from the configured cache dir and runs only inside the
    sandboxed audio worker (``umd.audio.dispatch``), never in the API process and
    without spawning any subprocess here (faster-whisper manages its own decoder
    threads bounded by ``asr_cpu_threads`` / ``asr_num_workers``).

    It honors the DD's explicit decoder settings (``word_timestamps``, language
    detection, VAD with no-speech handling, ``logprob_threshold`` /
    ``compression_ratio_threshold`` / ``no_speech_threshold``,
    ``condition_on_previous_text=False``) and a music-aware beam policy (smaller
    beam when music/SFX is suspected). It raises :class:`AsrProviderUnavailable`
    (typed, never fabricating) unless the runtime is installed, a model cache dir
    is present, and the engine is selected.
    """

    name = "faster-whisper"
    provider_version = "faster-whisper v1.0"

    def __init__(self) -> None:
        self._model: object | None = None
        self._model_dir: str | None = None
        self._model_version: str | None = None
        self._model_id: str | None = None

    def asr(self, audio: DecodedAudio, *, config: AudioConfig) -> AsrResult:
        if config.asr_engine != "faster-whisper":
            raise AsrProviderUnavailable(
                "faster-whisper is GATED: UMD_ASR_ENGINE != 'faster-whisper'"
            )
        # The worker config is already env-populated (audio_config_from_env reads
        # UMD_ASR_MODEL_CACHE); the provider uses ONLY the explicit config value so a
        # caller that did not wire a cache dir is never silently served the API env.
        if not config.asr_model_dir:
            raise AsrProviderUnavailable(
                "faster-whisper configured but no model cache dir (set asr_model_dir)"
            )
        model, model_version, model_id = self._load(config.asr_model_dir, config)

        # Music-aware beam policy: greedy (beam=1) when music/SFX is suspected.
        music_regions, _sfx = music.detect_music_and_sfx(audio)
        beam = config.asr_beam_size if not music_regions else 1

        segments, info = self._transcribe(model, audio, config, beam)

        utterances = [
            AsrUtterance(
                index=idx,
                text=(seg.text or "").strip(),
                start_s=float(seg.start),
                end_s=float(seg.end),
                words=[
                    AsrWord(
                        word=(w.word or "").strip(),
                        start_s=float(w.start),
                        end_s=float(w.end),
                        confidence=float(w.probability),
                    )
                    for w in (seg.words or [])
                ],
                confidence=_word_conf(seg),
                language=getattr(info, "language", None),
                music_suspected=_overlaps_music(float(seg.start), float(seg.end), music_regions),
            )
            for idx, seg in enumerate(segments, start=1)
        ]
        asr_conf = (
            sum(u.confidence * u.duration_s for u in utterances)
            / sum(u.duration_s for u in utterances)
            if utterances
            else 0.0
        )
        return AsrResult(
            provider=self.name,
            provider_version=self.provider_version,
            language=getattr(info, "language", None),
            utterances=utterances,
            confidence=asr_conf,
            energy_correlation=_energy_correlation(audio, utterances),
            unmapped_count=0,
            model_id=model_id,
            model_version=model_version,
        )

    # -- internals ------------------------------------------------------------

    def _load(self, model_dir: str, config: AudioConfig) -> tuple[object, str | None, str]:
        if self._model is not None and self._model_dir == model_dir:
            return self._model, self._model_version, self._model_id or config.asr_model_id
        if not _faster_whisper_installed():
            raise AsrProviderUnavailable(
                "faster-whisper runtime not installed (install the 'asr' optional extra)"
            )
        model_dir = os.path.expanduser(model_dir)
        if not os.path.isdir(model_dir):
            raise AsrProviderUnavailable(f"faster-whisper model cache dir missing: {model_dir}")
        model_bin = os.path.join(model_dir, "model.bin")
        if not os.path.isfile(model_bin):
            raise AsrProviderUnavailable(
                f"faster-whisper model cache has no model.bin (invalid CT2 model): {model_dir}"
            )
        from faster_whisper import WhisperModel  # optional extra; lazy import

        model = WhisperModel(
            model_dir,
            device="cpu",
            compute_type=config.asr_compute_type,
            cpu_threads=config.asr_cpu_threads,
            num_workers=config.asr_num_workers,
        )
        model_version = _model_version_fingerprint(model_bin)
        self._model, self._model_dir = model, model_dir
        self._model_version, self._model_id = model_version, config.asr_model_id
        return model, model_version, config.asr_model_id

    def _transcribe(
        self,
        model: object,
        audio: DecodedAudio,
        config: AudioConfig,
        beam: int,
    ) -> tuple[Any, Any]:
        from importlib import import_module

        np = cast(Any, import_module("numpy"))  # faster-whisper runtime dep; lazy import

        language_code = config.declared_language or config.config_language
        audio_array = np.asarray(audio.pcm, dtype=np.float32)
        segments, info = cast(Any, model).transcribe(
            audio_array,
            language=language_code,
            beam_size=beam,
            word_timestamps=True,
            vad_filter=True,
            log_prob_threshold=-1.0,
            compression_ratio_threshold=2.4,
            no_speech_threshold=0.6,
            condition_on_previous_text=False,
        )
        return segments, info


def _word_conf(seg: object) -> float:
    """Transcription-scoped confidence for a whisper segment (mean word prob)."""
    words = getattr(seg, "words", None) or []
    if not words:
        return 0.0
    return sum(float(w.probability) for w in words) / len(words)


def _model_version_fingerprint(model_bin: str) -> str:
    """A short sha256 of the exact weights file (generated-by model version).

    Stream-hashes the file in bounded chunks so a ~75MB ``model.bin`` is never
    loaded wholesale into memory (the digest semantics are unchanged, so the
    pinned ``deploy/pins/asr-runtime.md`` match still holds).
    """
    h = sha256()
    with open(model_bin, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return f"weights.sha256={h.hexdigest()[:16]}"


def _faster_whisper_installed() -> bool:
    try:
        importlib.import_module("faster_whisper")  # noqa: PLC0415 - optional extra probe
        return True
    except ImportError:
        return False


def faster_whisper_runtime_ready(model_dir: str | None = None) -> bool:
    """True when the faster-whisper runtime is importable AND a valid cache is present.

    Mirrors the provider's :meth:`FasterWhisperAsrProvider._load` gate exactly:
    the faster-whisper package must be importable, the cache dir must exist, and
    it must contain ``model.bin`` (the file the provider actually loads). This
    prevents an empty/invalid cache dir from reporting ACTIVE in the capability
    report while :meth:`asr` would raise :class:`AsrProviderUnavailable`.
    """
    if not _faster_whisper_installed():
        return False
    cache = model_dir or os.environ.get("UMD_ASR_MODEL_CACHE")
    if not cache:
        return False
    cache = os.path.expanduser(cache)
    if not os.path.isdir(cache):
        return False
    return os.path.isfile(os.path.join(cache, "model.bin"))


ASR_PROVIDERS: dict[str, AsrProvider] = {
    "reference": ReferenceAsrProvider(),
    "faster-whisper": FasterWhisperAsrProvider(),
}


def run_asr(audio: DecodedAudio, *, config: AudioConfig) -> AsrResult:
    """Single ASR dispatch point: resolve ``config.asr_engine`` -> provider.

    Providers are resolved from :data:`ASR_PROVIDERS`. A provider that raises
    :class:`AsrProviderUnavailable` (gated/weights-absent/not-installed) is
    downgraded to the honest reference transcript explicitly marked ``gated=True``
    with the reason — never fabricated, never claiming the gated runtime is active.
    Every dispatched result is stamped with generated-by metadata (config digest +
    generation timestamp) so it is auditable.
    """
    engine = config.asr_engine
    provider = ASR_PROVIDERS.get(engine)
    if provider is None:
        result = ASR_PROVIDERS["reference"].asr(audio, config=config)
        return _stamp(
            _gated(result, f"ASR engine {engine!r} is not registered; reference fallback"),
            config,
        )
    try:
        result = provider.asr(audio, config=config)
    except AsrProviderUnavailable as exc:
        result = ASR_PROVIDERS["reference"].asr(audio, config=config)
        result = _gated(result, str(exc))
    return _stamp(result, config)


def _gated(result: AsrResult, reason: str) -> AsrResult:
    """Mark a reference-fallback result as gated with an explicit reason."""
    return replace(
        result,
        gated=True,
        gate_reason=reason,
        warnings=[*result.warnings, f"ASR gated: {reason}"],
    )


def _stamp(result: AsrResult, config: AudioConfig) -> AsrResult:
    """Stamp generated-by metadata (config digest + generation timestamp)."""
    return replace(
        result,
        generated_at=result.generated_at or datetime.now(UTC).isoformat(),
        config_digest=result.config_digest or config.config_digest,
    )


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
