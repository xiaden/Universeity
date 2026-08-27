"""Video baseline package (Phase C, P3-S1..S4).

Sandboxed PTS-native video decomposition: ffprobe stream inventory, reference
ffmpeg scene/shot detection, bounded PTS-native frame anchors, candidate
observations, audio-branch composition (reusing the Phase-2 audio baseline), and
independent embedded-subtitle track extraction (P3-S2). PyAV/PySceneDetect are
honestly GATED enhancers; the reference providers are hermetic and deterministic.
"""

from __future__ import annotations

from umd.video.availability import video_capability_report
from umd.video.evidence import VideoEvidencePlan, build_video_evidence_plan
from umd.video.pipeline import VideoPipeline
from umd.video.types import VideoConfig, VideoOutput

__all__ = [
    "VideoConfig",
    "VideoEvidencePlan",
    "VideoOutput",
    "VideoPipeline",
    "build_video_evidence_plan",
    "video_capability_report",
]
