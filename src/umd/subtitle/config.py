"""Subtitle baseline configuration (worker-side, env-driven)."""

from __future__ import annotations

import hashlib
import json
import os

from umd.subtitle.types import SubtitleConfig


def config_digest_of(config: SubtitleConfig) -> str:
    """Deterministic sha256 config digest for evidence idempotency/determinism."""
    material = json.dumps(
        {
            "format": config.format,
            "max_events": config.max_events,
            "normalize_webvtt": config.normalize_webvtt,
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


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def subtitle_config_from_env() -> SubtitleConfig:
    forced = os.environ.get("UMD_SUBTITLE_FORMAT")
    return SubtitleConfig(
        format=forced or None,
        max_events=_int_env("UMD_SUBTITLE_MAX_EVENTS", 20000),
        normalize_webvtt=_bool_env("UMD_SUBTITLE_NORMALIZE_WEBVTT", True),
        config_digest=os.environ.get("UMD_CONFIG_DIGEST") or None,
    )


__all__ = ["config_digest_of", "subtitle_config_from_env"]
