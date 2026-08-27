"""Video capability disclosure: which video paths are active vs GATED (P3-S1).

Capability responses must disclose which video paths (decode engine, scene/shot
detection) are active vs gated, and never report a gated enhancement as active.
The reference video baseline uses the locked system ffprobe/ffmpeg; PyAV and
PySceneDetect are GATED enhancers not installed/wired here.
"""

from __future__ import annotations

from umd.video.scenes import PYSCENEDETECT, REFERENCE_SCENE_PROVIDER
from umd.video.types import VideoConfig

REFERENCE_DECODER = "ffmpeg/ffprobe"
PYAV = "PyAV"


def video_capability_report(config: VideoConfig | None = None) -> dict[str, object]:
    """The video capability snapshot for ``/capabilities`` (honest gates)."""
    cfg = config or VideoConfig()
    return {
        "decode": {
            "active": REFERENCE_DECODER,
            REFERENCE_DECODER: {"active": True},
            PYAV: {"gated": True, "enabled": cfg.decode_engine == PYAV, "active": False},
        },
        "scene_detection": {
            "active": REFERENCE_SCENE_PROVIDER,
            "reference_provider": REFERENCE_SCENE_PROVIDER,
            "reference_via": "ffmpeg scene filter",
            "threshold": cfg.scene_threshold,
            PYSCENEDETECT: {
                "gated": True,
                "enabled": cfg.scene_engine == PYSCENEDETECT,
                "active": False,
            },
        },
        "pts_native": {"segments": True, "frames": True, "time_base": "PTS"},
        "observations": "candidate_kind only; pixel vision GATED (no PyAV decode)",
        "promotion_ban": "enforced_auditable",
    }


def flatten_video_capabilities(cap: dict[str, object]) -> dict[str, object]:
    """Merge the video capability block into a JSON-serializable flat report."""
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


__all__ = [
    "PYAV",
    "REFERENCE_DECODER",
    "flatten_video_capabilities",
    "video_capability_report",
]
