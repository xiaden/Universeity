"""Video baseline configuration derivation (worker-side, env-driven)."""

from __future__ import annotations

import hashlib
import json
import os

from umd.video.types import VideoConfig


def config_digest_of(config: VideoConfig) -> str:
    """Deterministic sha256 config digest for evidence idempotency/determinism.

    Only behaviour-affecting fields participate, so an unchanged pipeline over
    the same source re-inserts as an idempotent duplicate (Plan B evidence rule).
    """
    material = json.dumps(
        {
            "max_duration_s": config.max_duration_s,
            "scene_threshold": config.scene_threshold,
            "max_scenes": config.max_scenes,
            "max_frames": config.max_frames,
            "scene_engine": config.scene_engine,
            "decode_engine": config.decode_engine,
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:64]
    config.config_digest = config.config_digest or digest
    return config.config_digest


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def video_config_from_env() -> VideoConfig:
    """Derive :class:`VideoConfig` from the environment (gates honored, never guessed)."""
    return VideoConfig(
        max_duration_s=_float_env("UMD_VIDEO_MAX_DURATION_S", 0.0),
        scene_threshold=_float_env("UMD_VIDEO_SCENE_THRESHOLD", 0.3),
        max_scenes=_int_env("UMD_VIDEO_MAX_SCENES", 512),
        max_frames=_int_env("UMD_VIDEO_MAX_FRAMES", 2000),
        scene_engine="pyscenedetect"
        if _bool_env("UMD_SCENE_ENGINE_PYSCENEDETECT")
        else "reference",
        decode_engine="PyAV" if _bool_env("UMD_VIDEO_DECODE_PYAV") else "reference",
        config_digest=os.environ.get("UMD_CONFIG_DIGEST") or None,
    )


__all__ = ["config_digest_of", "video_config_from_env"]
