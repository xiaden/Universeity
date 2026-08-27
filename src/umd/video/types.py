"""Shared value types for the video baseline (Phase C, P3-S1..S4).

The video baseline runs **inside** the sandboxed worker subprocess (mirroring the
audio package): it inventories the container/tracks via ffprobe, detects
scene/shot boundaries with the ffmpeg scene filter, emits PTS-native
file/track/episode/scene/shot/frame/region/time segments, records bounded
visual/environment/object/temporal observations, and composes the audio branch
(reusing the Phase-2 audio baseline). These dataclasses are the typed worker
output that crosses the sandbox boundary as JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class VideoConfig:
    """Baseline configuration passed to the video worker (env-derived)."""

    #: Ceiling (seconds) for inventory/scene decode; 0 = not enforced by worker.
    max_duration_s: float = 0.0
    #: Scene-detection threshold for the ffmpeg ``scene`` filter (0..1).
    scene_threshold: float = 0.3
    #: Bounded scene/shot/frame analysis ceiling (0 = default).
    max_scenes: int = 512
    #: Bounded PTS frame-anchor sampling ceiling.
    max_frames: int = 2000
    #: PySceneDetect switch (GATED heavy enhancer; reference uses ffmpeg).
    scene_engine: str = "reference"
    #: PyAV switch (GATED heavy decode; reference uses ffprobe/ffmpeg).
    decode_engine: str = "reference"
    #: Config digest recorded on evidence (determinism/idempotency).
    config_digest: str | None = None


@dataclass
class VideoTrack:
    """One stream/track from the container inventory (independent source)."""

    index: int  # stream index
    codec_type: str  # video | audio | subtitle
    codec_name: str
    language: str | None = None
    disposition: dict[str, Any] = field(default_factory=dict)
    title: str | None = None
    # video
    width: int | None = None
    height: int | None = None
    time_base: str | None = None
    avg_frame_rate: str | None = None
    r_frame_rate: str | None = None
    pix_fmt: str | None = None
    # audio / subtitle
    sample_rate: int | None = None
    channels: int | None = None
    # timing (PTS-native framing)
    pts_start: int | None = None
    duration: float | None = None
    nb_frames: int | None = None
    tags: dict[str, Any] = field(default_factory=dict)


@dataclass
class SceneBoundary:
    """A detected scene boundary (PTS-native start/end)."""

    index: int
    start_pts: int | None
    start_s: float
    end_s: float
    threshold: float
    provider: str = "umd-reference-scene"

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)


@dataclass
class ShotBoundary:
    """A shot boundary (a semantic sub-partition of a scene, PTS-native)."""

    index: int
    start_pts: int | None
    start_s: float
    end_s: float
    threshold: float
    provider: str = "umd-reference-scene"


@dataclass
class FrameAnchor:
    """A bounded PTS-native frame timing anchor."""

    index: int
    pts: int | None
    pts_time_s: float
    pic_type: str | None = None


@dataclass
class VideoObservation:
    """A bounded visual/environment/object/temporal candidate observation.

    These are metres/derived-from-metadata candidate observations: they are
    evidence only, always carry ``candidate_kind="observation"``, and are never
    promoted to canonical identity. Pixel-level object/environment detection is
    GATED behind PyVA/PySceneDetect (not installed); the reference emits honest
    metadata-derived candidates at low confidence and discloses the gate.
    """

    kind: str
    label: str
    confidence: float
    generated_by: str
    note: str | None = None
    quality: dict[str, Any] = field(default_factory=dict)


@dataclass
class VideoOutput:
    """The full in-worker baseline output (serialized to/from JSON)."""

    meta: dict[str, Any] = field(default_factory=dict)
    timing: dict[str, Any] = field(default_factory=dict)
    inventory: list[VideoTrack] = field(default_factory=list)
    scenes: list[SceneBoundary] = field(default_factory=list)
    shots: list[ShotBoundary] = field(default_factory=list)
    frame_anchors: list[FrameAnchor] = field(default_factory=list)
    observations: list[VideoObservation] = field(default_factory=list)
    #: Audio branch composition: audio tracks discovered in the container that the
    #: Phase-2 audio baseline composes for this video source.
    audio_tracks: list[dict[str, Any]] = field(default_factory=list)
    #: Subtitle tracks discovered in the container (extracted independently by the
    #: subtitle worker; announced here for PTS/track correspondence).
    subtitle_tracks: list[dict[str, Any]] = field(default_factory=list)
    capabilities: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


__all__ = [
    "FrameAnchor",
    "SceneBoundary",
    "ShotBoundary",
    "VideoConfig",
    "VideoObservation",
    "VideoOutput",
    "VideoTrack",
]
