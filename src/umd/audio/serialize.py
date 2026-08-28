"""JSON serialization of :class:`AudioOutput` across the sandbox boundary (P2-S1).

The audio worker runs **inside** the sandbox (a bounded subprocess); its structured
payload crosses back to the API process as JSON on stdout. This module converts
the typed :class:`~umd.audio.types.AudioOutput` (and nested value types) to/from
plain JSON-serializable dicts deterministically.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from umd.audio.types import (
    AsrResult,
    AsrUtterance,
    AsrWord,
    AudioOutput,
    DiarizationResult,
    LanguageResult,
    SpeakerCandidate,
)


def audio_output_to_dict(output: AudioOutput) -> dict[str, Any]:
    return {
        "meta": output.meta,
        "timing": output.timing,
        "vad": output.vad,
        "language": _optional(_lang_to_dict, output.language),
        "asr": _optional(_asr_to_dict, output.asr),
        "music": output.music,
        "sound_events": output.sound_events,
        "diarization": _diar_to_dict(output.diarization),
        "hallucination": output.hallucination,
        "capabilities": output.capabilities,
        "warnings": output.warnings,
    }


def audio_output_from_dict(data: dict[str, Any]) -> AudioOutput:
    return AudioOutput(
        meta=dict(data.get("meta") or {}),
        timing=dict(data.get("timing") or {}),
        vad=dict(data.get("vad") or {}),
        language=_optional(_lang_from_dict, data.get("language")),
        asr=_optional(_asr_from_dict, data.get("asr")),
        music=list(data.get("music") or []),
        sound_events=list(data.get("sound_events") or []),
        diarization=_diar_from_dict(dict(data.get("diarization") or {})),
        hallucination=dict(data.get("hallucination") or {}),
        capabilities=dict(data.get("capabilities") or {}),
        warnings=list(data.get("warnings") or []),
    )


def _optional(fn: Callable[[Any], Any], value: Any) -> Any:  # noqa: UP047
    if value is None:
        return None
    return fn(value)


def _lang_to_dict(lang: LanguageResult) -> dict[str, Any]:
    return {
        "language": lang.language,
        "confidence": lang.confidence,
        "provider": lang.provider,
        "sources": list(lang.sources),
    }


def _lang_from_dict(d: Any) -> LanguageResult:
    return LanguageResult(
        language=str(d.get("language") or "unknown"),
        confidence=float(d.get("confidence") or 0.0),
        provider=str(d.get("provider") or "umd-reference-lang"),
        sources=list(d.get("sources") or []),
    )


def _asr_to_dict(a: AsrResult) -> dict[str, Any]:
    return {
        "provider": a.provider,
        "provider_version": a.provider_version,
        "language": a.language,
        "confidence": a.confidence,
        "energy_correlation": a.energy_correlation,
        "warnings": list(a.warnings),
        "unmapped_count": a.unmapped_count,
        "gated": a.gated,
        "gate_reason": a.gate_reason,
        "model_id": a.model_id,
        "model_version": a.model_version,
        "config_digest": a.config_digest,
        "generated_at": a.generated_at,
        "utterances": [
            {
                "index": u.index,
                "text": u.text,
                "start_s": u.start_s,
                "end_s": u.end_s,
                "confidence": u.confidence,
                "language": u.language,
                "music_suspected": u.music_suspected,
                "words": [
                    {
                        "word": w.word,
                        "start_s": w.start_s,
                        "end_s": w.end_s,
                        "confidence": w.confidence,
                    }
                    for w in u.words
                ],
            }
            for u in a.utterances
        ],
    }


def _asr_from_dict(d: Any) -> AsrResult:
    return AsrResult(
        provider=str(d.get("provider") or "umd-reference-asr"),
        provider_version=str(d.get("provider_version") or "umd-reference-asr v1.0"),
        language=d.get("language"),
        confidence=float(d.get("confidence") or 0.0),
        energy_correlation=float(d.get("energy_correlation") or 0.0),
        warnings=list(d.get("warnings") or []),
        unmapped_count=int(d.get("unmapped_count") or 0),
        gated=bool(d.get("gated") or False),
        gate_reason=d.get("gate_reason"),
        model_id=d.get("model_id"),
        model_version=d.get("model_version"),
        config_digest=d.get("config_digest"),
        generated_at=d.get("generated_at"),
        utterances=[
            AsrUtterance(
                index=int(u["index"]),
                text=str(u.get("text") or ""),
                start_s=float(u.get("start_s") or 0.0),
                end_s=float(u.get("end_s") or 0.0),
                confidence=float(u.get("confidence") or 0.0),
                language=u.get("language"),
                music_suspected=bool(u.get("music_suspected") or False),
                words=[
                    AsrWord(
                        word=str(w.get("word") or ""),
                        start_s=float(w.get("start_s") or 0.0),
                        end_s=float(w.get("end_s") or 0.0),
                        confidence=float(w.get("confidence") or 0.0),
                    )
                    for w in u.get("words") or []
                ],
            )
            for u in d.get("utterances") or []
        ],
    )


def _diar_to_dict(d: DiarizationResult) -> dict[str, Any]:
    return {
        "provider": d.provider,
        "gated": d.gated,
        "gate_reason": d.gate_reason,
        "speaker_candidates": [
            {
                "utterance_index": c.utterance_index,
                "speaker_label": c.speaker_label,
                "confidence": c.confidence,
                "generated_by": c.generated_by,
                "start_s": c.start_s,
                "end_s": c.end_s,
            }
            for c in d.speaker_candidates
        ],
    }


def _diar_from_dict(d: dict[str, Any]) -> DiarizationResult:
    return DiarizationResult(
        provider=str(d.get("provider") or "umd-reference-diarizer-fallback"),
        gated=bool(d.get("gated") or False),
        gate_reason=d.get("gate_reason"),
        speaker_candidates=[
            SpeakerCandidate(
                utterance_index=int(c["utterance_index"]),
                speaker_label=str(c.get("speaker_label") or "speaker_unknown_0"),
                confidence=float(c.get("confidence") or 0.3),
                generated_by=str(c.get("generated_by") or "umd-reference-diarizer-fallback"),
                start_s=float(c.get("start_s") or 0.0),
                end_s=float(c.get("end_s") or 0.0),
            )
            for c in d.get("speaker_candidates") or []
        ],
    )
