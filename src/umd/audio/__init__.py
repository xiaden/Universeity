"""Audio baseline package (Phase C, P2-S1..S5).

Sandboxed decode + time chunking, VAD-before-ASR, reference ASR (with GATED
faster-whisper), music/sound regions, language, timing, the four-signal
hallucination filter with the versioned ``HallucinationFiltered`` edge, and gated
pyannote diarization with a non-gated ``speaker_unknown_N`` fallback. Raw ASR is
untrusted OCFL evidence only; confidence is transcription-scoped; nothing here
promotes ASR/diarization output to semantic/identity truth (auditable promotion
ban).
"""

from __future__ import annotations

from umd.audio.availability import audio_capability_report, flatten_audio_capabilities
from umd.audio.config import audio_config_from_env, config_digest_of
from umd.audio.decode import AudioDecodeError, decode_to_pcm, probe, time_chunk
from umd.audio.diarization import (
    DiarizationUnavailable,
    PyannoteDiarizationProvider,
    run_diarization,
    speaker_unknown_candidates,
)
from umd.audio.hallucination import (
    FilterDecision,
    FilterOutcome,
    FprFnrMeasurement,
    filter_hallucinations,
    measure_fpr_fnr,
    to_hallucination_filtered_event,
)
from umd.audio.pipeline import AUDIO_DECODER, AUDIO_RENDERER, AUDIO_SEGMENTER, run_audio_baseline
from umd.audio.runner import AudioSandboxError, invoke_audio_baseline
from umd.audio.types import (
    AsrResult,
    AsrUtterance,
    AsrWord,
    AudioConfig,
    AudioMeta,
    AudioOutput,
    DecodedAudio,
    DiarizationResult,
    LanguageResult,
    MusicRegion,
    SoundRegion,
    SpeakerCandidate,
    SpeechSegment,
    TimeChunk,
    VadResult,
)

__all__ = [
    "AudioDecodeError",
    "AudioConfig",
    "AudioMeta",
    "AudioOutput",
    "AudioSandboxError",
    "AUDIO_DECODER",
    "AUDIO_RENDERER",
    "AUDIO_SEGMENTER",
    "AsrResult",
    "AsrUtterance",
    "AsrWord",
    "DecodedAudio",
    "DiarizationResult",
    "DiarizationUnavailable",
    "FilterDecision",
    "FilterOutcome",
    "FprFnrMeasurement",
    "LanguageResult",
    "MusicRegion",
    "PyannoteDiarizationProvider",
    "SoundRegion",
    "SpeakerCandidate",
    "SpeechSegment",
    "TimeChunk",
    "VadResult",
    "audio_capability_report",
    "audio_config_from_env",
    "config_digest_of",
    "decode_to_pcm",
    "filter_hallucinations",
    "flatten_audio_capabilities",
    "invoke_audio_baseline",
    "measure_fpr_fnr",
    "probe",
    "run_audio_baseline",
    "run_diarization",
    "speaker_unknown_candidates",
    "time_chunk",
    "to_hallucination_filtered_event",
]
