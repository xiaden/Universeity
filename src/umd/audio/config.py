"""Audio baseline configuration derivation (worker-side, env-driven)."""

from __future__ import annotations

import hashlib
import json
import os

from umd.audio.types import AudioConfig


def config_digest_of(config: AudioConfig) -> str:
    """Deterministic sha256 config digest for evidence idempotency/determinism.

    Only the behavior-affecting fields participate, so an unchanged pipeline over
    the same source re-inserts as an idempotent duplicate (Plan B evidence rule).

    Pure: this never mutates the passed ``config`` (the caller assigns
    ``config.config_digest = config_digest_of(config)`` when it needs the digest
    persisted on the config object).
    """
    # An explicitly pinned digest (e.g. UMD_CONFIG_DIGEST) is authoritative.
    if config.config_digest:
        return config.config_digest
    material = json.dumps(
        {
            "asr_engine": config.asr_engine,
            "asr_model_dir": config.asr_model_dir,
            "asr_model_id": config.asr_model_id,
            "asr_cpu_threads": config.asr_cpu_threads,
            "asr_num_workers": config.asr_num_workers,
            "asr_beam_size": config.asr_beam_size,
            "asr_compute_type": config.asr_compute_type,
            "diarization_enabled": config.diarization_enabled,
            "diarization_legal_gate": config.diarization_legal_gate,
            "max_duration_s": config.max_duration_s,
            "confidence_threshold": config.confidence_threshold,
            "energy_correlation_threshold": config.energy_correlation_threshold,
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:64]


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def audio_config_from_env() -> AudioConfig:
    """Derive :class:`AudioConfig` from the environment (gates honored, never guessed).

    Heavy paths (faster-whisper, pyannote) activate only under their explicit
    gates; absence of a gate/weights is reported as GATED, never fabricated.
    """
    return AudioConfig(
        declared_language=os.environ.get("UMD_AUDIO_DECLARED_LANGUAGE") or None,
        config_language=os.environ.get("UMD_AUDIO_LANGUAGE") or None,
        asr_engine=os.environ.get("UMD_ASR_ENGINE") or "reference",
        asr_model_dir=os.environ.get("UMD_ASR_MODEL_DIR")
        or os.environ.get("UMD_ASR_MODEL_CACHE")
        or None,
        asr_model_id=os.environ.get("UMD_ASR_MODEL_ID") or "Systran/faster-whisper-tiny.en",
        asr_cpu_threads=int(os.environ.get("UMD_ASR_CPU_THREADS") or 4),
        asr_num_workers=int(os.environ.get("UMD_ASR_NUM_WORKERS") or 1),
        asr_beam_size=int(os.environ.get("UMD_ASR_BEAM_SIZE") or 5),
        asr_compute_type=os.environ.get("UMD_ASR_COMPUTE_TYPE") or "int8",
        diarization_enabled=_bool_env("UMD_DIARIZATION_ENABLED"),
        diarization_weights_dir=os.environ.get("UMD_DIARIZATION_WEIGHTS_DIR") or None,
        diarization_legal_gate=_bool_env("UMD_DIARIZATION_LEGAL_GATE"),
        max_duration_s=float(os.environ.get("UMD_AUDIO_MAX_DURATION_S") or 0.0),
        confidence_threshold=float(os.environ.get("UMD_AUDIO_CONFIDENCE_THRESHOLD") or 0.45),
        energy_correlation_threshold=float(
            os.environ.get("UMD_AUDIO_ENERGY_CORR_THRESHOLD") or 0.5
        ),
        config_digest=os.environ.get("UMD_CONFIG_DIGEST") or None,
    )
