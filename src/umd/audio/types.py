"""Shared value types for the audio baseline (Phase C, P2-S1..S5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AudioMeta:
    """Container/codec metadata read via ffprobe (bounded)."""

    format_name: str
    codec_name: str
    sample_rate: int
    channels: int
    duration_s: float
    bit_rate: int | None = None


@dataclass
class DecodedAudio:
    """Fully-decoded, normalized mono PCM (the sandboxed decode output)."""

    sample_rate: int
    pcm: list[float]
    duration_s: float
    meta: AudioMeta

    @property
    def n_samples(self) -> int:
        return len(self.pcm)


@dataclass
class TimeChunk:
    """One bounded time chunk of decoded audio (for chunked processing)."""

    start_s: float
    end_s: float
    pcm: list[float]


@dataclass
class SpeechSegment:
    """A VAD speech region (signal 1 / no-speech evidence)."""

    start_s: float
    end_s: float
    mean_energy: float = 0.0
    peak_energy: float = 0.0

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)


@dataclass
class VadResult:
    """Reference VAD output over one decoded audio."""

    speech_segments: list[SpeechSegment] = field(default_factory=list)
    total_speech_s: float = 0.0
    no_speech_ratio: float = 0.0

    @property
    def has_speech(self) -> bool:
        return self.total_speech_s > 0.0


@dataclass
class MusicRegion:
    """A sustained/tonal music region (evidence kind ``music``)."""

    start_s: float
    end_s: float
    confidence: float = 0.0

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)


@dataclass
class SoundRegion:
    """A transient sound-event region (evidence kind ``sound_event``)."""

    start_s: float
    end_s: float
    kind: str = "sfx"
    confidence: float = 0.0

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)


@dataclass
class LanguageResult:
    """Reference language identification output.

    The baseline never fabricates a language it did not receive: it reports the
    declared/source-native or configured language, else ``unknown``.
    """

    language: str
    confidence: float
    provider: str
    sources: list[str] = field(default_factory=list)


@dataclass
class AsrWord:
    """One transcribed word with a word-level time range (P2-S1 word timestamps)."""

    word: str
    start_s: float
    end_s: float
    confidence: float = 0.0  # transcription-scoped decode confidence


@dataclass
class AsrUtterance:
    """One ASR utterance (semantic-utterance envelope) with words + timing."""

    index: int
    text: str
    start_s: float
    end_s: float
    words: list[AsrWord] = field(default_factory=list)
    confidence: float = 0.0  # transcription-scoped
    language: str | None = None
    music_suspected: bool = False

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)


@dataclass
class AsrResult:
    """Structured ASR output (provider-adapted, transcription-scoped)."""

    provider: str
    provider_version: str
    language: str | None
    utterances: list[AsrUtterance] = field(default_factory=list)
    confidence: float = 0.0
    energy_correlation: float = 0.0
    warnings: list[str] = field(default_factory=list)
    #: ``unmapped`` words (audio not matching the codec) — honest lexical gap.
    unmapped_count: int = 0
    #: Honest gate marker — True when the requested engine is GATED and only the
    #: reference path produced transcript (never claims the gated runtime is active).
    gated: bool = False
    #: Human-readable reason when ``gated`` is True (e.g. weights absent / not wired).
    gate_reason: str | None = None
    #: generated-by metadata (P2-S3): the exact model that produced this transcript.
    model_id: str | None = None
    #: generated-by metadata: model/weight version actually observed at run time.
    model_version: str | None = None
    #: Config digest captured when the transcript was produced (evidence idempotency).
    config_digest: str | None = None
    #: ISO-8601 UTC timestamp of transcript generation (timestamped confidence).
    generated_at: str | None = None


@dataclass
class SpeakerCandidate:
    """A candidate speaker assignment for one utterance / turn."""

    utterance_index: int
    speaker_label: str
    confidence: float
    generated_by: str
    start_s: float
    end_s: float


@dataclass
class DiarizationResult:
    """Diarization output — gated provider result OR the non-gated fallback."""

    speaker_candidates: list[SpeakerCandidate] = field(default_factory=list)
    provider: str = "umd-reference-diarizer-fallback"
    gated: bool = False
    gate_reason: str | None = None


@dataclass
class AudioConfig:
    """Baseline configuration passed to the audio worker (env-derived)."""

    #: Source-native / descriptor-declared language (honest, not inferred).
    declared_language: str | None = None
    #: Config-declared language fallback (e.g. UMD_AUDIO_LANGUAGE).
    config_language: str | None = None
    #: ASR engine: ``reference`` (non-gated) or ``faster-whisper`` (GATED).
    asr_engine: str = "reference"
    #: Weights directory for the GATED faster-whisper path (None => gated/absent).
    asr_model_dir: str | None = None
    #: Pinned faster-whisper model id/repo to load from ``asr_model_dir``.
    asr_model_id: str = "Systran/faster-whisper-tiny.en"
    #: CPU threads granted to the ASR worker (bounded, never the API process).
    asr_cpu_threads: int = 4
    #: faster-whisper decoder threads (CTranslate2 num_workers).
    asr_num_workers: int = 1
    #: Beam size for ordinary speech; reduced when music/SFX is suspected.
    asr_beam_size: int = 5
    #: faster-whisper compute type (int8 on CPU for self-hostable small models).
    asr_compute_type: str = "int8"
    #: Gated diarization switch (pyannote behind license/weights gate).
    diarization_enabled: bool = False
    #: Weights directory for GATED pyannote diarization (None => gated/absent).
    diarization_weights_dir: str | None = None
    #: Legal release gate for pyannote weights (False => never activates).
    diarization_legal_gate: bool = False
    #: Ceiling (seconds) for decode; 0 = not enforced by the worker.
    max_duration_s: float = 0.0
    #: Transcription-scoped word-confidence below which a word is hallucination-flagged.
    confidence_threshold: float = 0.45
    #: ASR-speech/acoustic-energy correlation below which speech is hallucination-flagged.
    energy_correlation_threshold: float = 0.5
    #: Config digest recorded on every evidence row (determinism/idempotency).
    config_digest: str | None = None


@dataclass
class AudioOutput:
    """The full in-worker baseline output (serialized to/from JSON)."""

    meta: dict[str, Any] = field(default_factory=dict)
    timing: dict[str, Any] = field(default_factory=dict)
    vad: dict[str, Any] = field(default_factory=dict)
    language: LanguageResult | None = None
    asr: AsrResult | None = None
    music: list[dict[str, Any]] = field(default_factory=list)
    sound_events: list[dict[str, Any]] = field(default_factory=list)
    diarization: DiarizationResult = field(default_factory=DiarizationResult)
    hallucination: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
