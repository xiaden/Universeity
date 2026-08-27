"""Audio capability disclosure: which audio paths are active vs GATED (P2-S5, DD).

Capability responses must disclose which audio paths (ASR engine, VAD,
diarization) are active vs gated, and record FPR/FNR measurements WITHOUT
claiming detector-grade guarantees (Task/DD). This module is the single honest
source the API ``/capabilities`` (and tests) consult. It never reports a gated
enhancement as active.
"""

from __future__ import annotations

from umd.audio.hallucination import S_ENERGY, S_LOGPROB, S_PROMOTION, S_VAD
from umd.audio.types import AudioConfig

#: The two supported ASR engines.
REFERENCE_ASR = "umd-reference-asr"
FASTER_WHISPER = "faster-whisper"


def audio_capability_report(config: AudioConfig | None = None) -> dict[str, object]:
    """The audio capability snapshot for ``/capabilities`` (honest gates)."""
    cfg = config or AudioConfig()
    asr_active = REFERENCE_ASR if cfg.asr_engine != FASTER_WHISPER else None
    fw_gated = cfg.asr_engine == FASTER_WHISPER
    return {
        "asr_engine": {
            "active": asr_active or "none",
            "reference_provider": REFERENCE_ASR,
            "faster_whisper": {"gated": True, "enabled": fw_gated, "active": False},
        },
        "vad": {"active": "umd-reference-vad", "precedes_asr": True},
        "language": {"active": "umd-reference-lang", "honest_declared_or_unknown": True},
        "diarization": {
            "active_provider": "umd-reference-diarizer-fallback",
            "pyannote": {
                "gated": True,
                "enabled": cfg.diarization_enabled,
                "weights_configured": bool(cfg.diarization_weights_dir),
                "legal_release_gate": bool(cfg.diarization_legal_gate),
                "active": False,
            },
        },
        "hallucination_controls": {
            S_VAD: True,
            S_LOGPROB: True,
            S_ENERGY: True,
            S_PROMOTION: True,
        },
        "confidence": "transcription_scoped",
        "promotion_ban": "enforced_auditable",
        "fpr_fnr": "measured_not_detector_grade",
    }


def flatten_audio_capabilities(cap: dict[str, object]) -> dict[str, object]:
    """Merge the audio capability block into a JSON-serializable flat report."""
    out: dict[str, object] = {}
    for key, value in cap.items():
        if isinstance(value, dict):
            out[key] = _jsonable(value)
        else:
            out[key] = value
    return out


def _jsonable(value: object) -> object:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value
