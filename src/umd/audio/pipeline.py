"""Audio baseline orchestration — runs inside the sandboxed worker (P2-S1..S4).

This is the pure, worker-side brain of the audio baseline. Given a fully decoded
:class:`~umd.audio.types.DecodedAudio`, it runs the DD-ordered pipeline:

    VAD-before-ASR -> language(id) -> ASR (reference, transcription-scoped)
        -> music/sound regions -> four-signal hallucination filter
        -> diarization fallback (speaker_unknown_N)

and returns a :class:`AudioOutput` structured payload that is JSON-serialized to
stdout and reconstructed by the API-process caller (see :mod:`umd.audio.dispatch`
/ :mod:`umd.audio.runner`). It performs NO I/O and writes NO semantic state; it
only produces evidence-shaped, auditable facts + the promotion ban enforcement.
"""

from __future__ import annotations

from functools import cached_property
from typing import Any

from umd.audio import asr as asr_mod
from umd.audio import diarization, hallucination, language, music, vad
from umd.audio.availability import audio_capability_report
from umd.audio.types import (
    AsrResult,
    AudioConfig,
    AudioOutput,
    DecodedAudio,
    DiarizationResult,
    LanguageResult,
    MusicRegion,
    SoundRegion,
    VadResult,
)

#: Version tag used in segment/locator/evidence versioning for the audio baseline.
AUDIO_SEGMENTER = "umd-audio"
AUDIO_DECODER = "ffmpeg"
AUDIO_RENDERER = "reference"


class AudioPipeline:
    """The deterministic audio baseline (worker-side, no I/O)."""

    provider_version = "umd-audio-reference v1.0"

    def __init__(self, audio: DecodedAudio, config: AudioConfig) -> None:
        self.audio = audio
        self.config = config

    @cached_property
    def vad_result(self) -> VadResult:
        return vad.detect_speech(self.audio)

    @cached_property
    def language_result(self) -> LanguageResult:
        return language.identify_language(
            self.audio,
            declared_language=self.config.declared_language,
            config_language=self.config.config_language,
        )

    @cached_property
    def music_regions(self) -> list[MusicRegion]:
        m, _sfx = music.detect_music_and_sfx(self.audio)
        return m

    @cached_property
    def sound_regions(self) -> list[SoundRegion]:
        _m, sfx = music.detect_music_and_sfx(self.audio)
        return sfx

    @cached_property
    def asr_result(self) -> AsrResult:
        return asr_mod.run_asr(self.audio, config=self.config)

    @cached_property
    def filtered(self) -> hallucination.FilterOutcome:
        return hallucination.filter_hallucinations(
            self.asr_result, self.config, vad_result=self.vad_result
        )

    @cached_property
    def diarization_result(self) -> DiarizationResult:
        return diarization.run_diarization(self.asr_result, config=self.config)

    @cached_property
    def warnings(self) -> list[str]:
        out = list(self.asr_result.warnings)
        if self.asr_result.gated and self.asr_result.gate_reason:
            out.append(f"asr gated: {self.asr_result.gate_reason}")
        if self.diarization_result.gated and self.diarization_result.gate_reason:
            out.append(f"diarization gated: {self.diarization_result.gate_reason}")
        return out

    def run(self) -> AudioOutput:
        """Execute the baseline and return the cross-boundary payload."""
        return AudioOutput(
            meta=_meta_dict(self.audio),
            timing=_timing_dict(self.audio),
            vad=_vad_dict(self.vad_result),
            language=self.language_result,
            asr=self.asr_result,
            music=[_region_dict(r) for r in self.music_regions],
            sound_events=[_region_dict(r) for r in self.sound_regions],
            diarization=self.diarization_result,
            hallucination=_filter_dict(self.filtered),
            capabilities=audio_capability_report(self.config),
            warnings=self.warnings,
        )


def run_audio_baseline(audio: DecodedAudio, config: AudioConfig) -> AudioOutput:
    """Run the audio baseline; see :class:`AudioPipeline`."""
    return AudioPipeline(audio, config).run()


def _meta_dict(audio: DecodedAudio) -> dict[str, Any]:
    m = audio.meta
    return {
        "format_name": m.format_name,
        "codec_name": m.codec_name,
        "sample_rate": m.sample_rate,
        "channels": m.channels,
        "duration_s": round(m.duration_s, 4),
        "bit_rate": m.bit_rate,
        "decoder": AUDIO_DECODER,
        "renderer": AUDIO_RENDERER,
    }


def _timing_dict(audio: DecodedAudio) -> dict[str, Any]:
    return {
        "duration_s": round(audio.duration_s, 4),
        "n_samples": audio.n_samples,
        "sample_rate": audio.sample_rate,
        "decoded_mono": True,
    }


def _vad_dict(vres: VadResult) -> dict[str, Any]:
    return {
        "has_speech": vres.has_speech,
        "total_speech_s": round(vres.total_speech_s, 4),
        "no_speech_ratio": round(vres.no_speech_ratio, 4),
        "speech_segments": [
            {"start_s": round(s.start_s, 4), "end_s": round(s.end_s, 4)}
            for s in vres.speech_segments
        ],
    }


def _region_dict(region: MusicRegion | SoundRegion) -> dict[str, Any]:
    out: dict[str, Any] = {
        "start_s": round(region.start_s, 4),
        "end_s": round(region.end_s, 4),
        "confidence": round(region.confidence, 4),
    }
    if isinstance(region, SoundRegion):
        out["kind"] = region.kind
    return out


def _filter_dict(outcome: hallucination.FilterOutcome) -> dict[str, Any]:
    return {
        "energy_correlation": round(outcome.energy_correlation, 4),
        "decisions": [
            {
                "utterance_index": d.utterance_index,
                "reference": d.reference,
                "outcome": d.outcome,
                "trigger_signal": d.trigger_signal,
                "signals": d.signals,
                "replaced_with": d.replaced_with,
                "filtered_word_indices": d.filtered_word_indices,
            }
            for d in outcome.decisions
        ],
        "fpr_fnr_note": "measured in fixture tests; not detector-grade",
    }
