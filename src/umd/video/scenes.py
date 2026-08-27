"""Scene/shot analysis providers (Phase C, P3-S1).

The DD video contract calls for scene/shot detection. The **non-gated, hermetic
reference** provider uses the locked system ffmpeg ``scene`` filter (real,
deterministic — see :func:`~umd.video.inventory.reference_scene_shots`);
PySceneDetect is the heavier enhancer and is GATED exactly like faster-whisper /
pyannote / PaddleOCR (heavy weights/runtime; not installed here). Capability
reporting discloses which of the two is active vs gated and never fabricates an
active detector.
"""

from __future__ import annotations

from abc import abstractmethod
from pathlib import Path
from typing import Protocol

from umd.video.inventory import reference_scene_shots
from umd.video.types import SceneBoundary, ShotBoundary, VideoConfig

#: The reference (non-gated) scene/shot provider identity.
REFERENCE_SCENE_PROVIDER = "umd-reference-scene"
PYSCENEDETECT = "pyscenedetect"


class SceneUnavailableError(RuntimeError):
    """A gated/absent scene provider was requested (typed, honest)."""


class SceneProvider(Protocol):
    """Yields scene/shot boundaries from an inventory + duration."""

    #: Provider identity, e.g. ``umd-reference-scene``.
    provider: str = REFERENCE_SCENE_PROVIDER

    @abstractmethod
    def detect(
        self,
        input_path: Path,
        config: VideoConfig,
        total_duration_s: float,
    ) -> tuple[list[SceneBoundary], list[ShotBoundary]]: ...


class ReferenceSceneProvider:
    """Deterministic ffmpeg-scene-filter provider (non-gated reference)."""

    provider = REFERENCE_SCENE_PROVIDER
    provider_version = "umd-reference-scene v1.0"

    def detect(
        self,
        input_path: Path,
        config: VideoConfig,
        total_duration_s: float,
    ) -> tuple[list[SceneBoundary], list[ShotBoundary]]:
        return reference_scene_shots(input_path, config, total_duration_s)


class PySceneDetectProvider:
    """GATED PySceneDetect enhancer. Never reports active unless installed + gated.

    Heavy runtime (model-free but weight-path dependent) — stays GATED by default.
    """

    provider = PYSCENEDETECT
    provider_version = "pyscenedetect (GATED)"

    def __init__(self) -> None:
        self._available = self._probe()

    @staticmethod
    def _probe() -> bool:
        try:
            import scenedetect  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            return False
        return True

    def detect(
        self,
        input_path: Path,
        config: VideoConfig,
        total_duration_s: float,
    ) -> tuple[list[SceneBoundary], list[ShotBoundary]]:
        del input_path, config, total_duration_s  # gated provider: no decode in v1
        if not self._available:
            raise SceneUnavailableError(
                "PySceneDetect not installed; scene detection is GATED (reference ffmpeg used)"
            )
        # Even when installed, the heavy runtime is a gated decode path that is not
        # wired in the v1 baseline (mirrors faster-whisper/pyannote honesty).
        raise SceneUnavailableError(
            "PySceneDetect runtime not wired in v1 baseline; stays GATED (reference used)"
        )


__all__ = [
    "PYSCENEDETECT",
    "REFERENCE_SCENE_PROVIDER",
    "PySceneDetectProvider",
    "ReferenceSceneProvider",
    "SceneProvider",
    "SceneUnavailableError",
]
