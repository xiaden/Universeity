"""JSON serialization of :class:`VideoOutput` across the sandbox boundary (P3-S1).

The video worker runs **inside** the sandbox; its structured payload crosses back
to the API process as JSON on stdout. This converts the typed
:class:`~umd.video.types.VideoOutput` to/from plain JSON-serializable dicts
deterministically (mirrors ``umd.audio.serialize``).
"""

from __future__ import annotations

from typing import Any

from umd.video.types import (
    FrameAnchor,
    SceneBoundary,
    ShotBoundary,
    VideoObservation,
    VideoOutput,
    VideoTrack,
)


def video_output_to_dict(out: VideoOutput) -> dict[str, Any]:
    return {
        "meta": out.meta,
        "timing": out.timing,
        "inventory": [_track_to_dict(t) for t in out.inventory],
        "scenes": [_scene_to_dict(s) for s in out.scenes],
        "shots": [_shot_to_dict(s) for s in out.shots],
        "frame_anchors": [_frame_to_dict(f) for f in out.frame_anchors],
        "observations": [_obs_to_dict(o) for o in out.observations],
        "audio_tracks": out.audio_tracks,
        "subtitle_tracks": out.subtitle_tracks,
        "capabilities": out.capabilities,
        "warnings": out.warnings,
    }


def video_output_from_dict(data: dict[str, Any]) -> VideoOutput:
    return VideoOutput(
        meta=dict(data.get("meta") or {}),
        timing=dict(data.get("timing") or {}),
        inventory=[_track_from_dict(t) for t in data.get("inventory") or []],
        scenes=[_scene_from_dict(s) for s in data.get("scenes") or []],
        shots=[_shot_from_dict(s) for s in data.get("shots") or []],
        frame_anchors=[_frame_from_dict(f) for f in data.get("frame_anchors") or []],
        observations=[_obs_from_dict(o) for o in data.get("observations") or []],
        audio_tracks=list(data.get("audio_tracks") or []),
        subtitle_tracks=list(data.get("subtitle_tracks") or []),
        capabilities=dict(data.get("capabilities") or {}),
        warnings=list(data.get("warnings") or []),
    )


def _track_to_dict(t: VideoTrack) -> dict[str, Any]:
    return {
        "index": t.index,
        "codec_type": t.codec_type,
        "codec_name": t.codec_name,
        "language": t.language,
        "disposition": t.disposition,
        "title": t.title,
        "width": t.width,
        "height": t.height,
        "time_base": t.time_base,
        "avg_frame_rate": t.avg_frame_rate,
        "r_frame_rate": t.r_frame_rate,
        "pix_fmt": t.pix_fmt,
        "sample_rate": t.sample_rate,
        "channels": t.channels,
        "pts_start": t.pts_start,
        "duration": t.duration,
        "nb_frames": t.nb_frames,
        "tags": t.tags,
    }


def _track_from_dict(d: Any) -> VideoTrack:
    return VideoTrack(
        index=int(d.get("index") or 0),
        codec_type=str(d.get("codec_type") or "unknown"),
        codec_name=str(d.get("codec_name") or "unknown"),
        language=d.get("language"),
        disposition=dict(d.get("disposition") or {}),
        title=d.get("title"),
        width=d.get("width"),
        height=d.get("height"),
        time_base=d.get("time_base"),
        avg_frame_rate=d.get("avg_frame_rate"),
        r_frame_rate=d.get("r_frame_rate"),
        pix_fmt=d.get("pix_fmt"),
        sample_rate=d.get("sample_rate"),
        channels=d.get("channels"),
        pts_start=d.get("pts_start"),
        duration=d.get("duration"),
        nb_frames=d.get("nb_frames"),
        tags=dict(d.get("tags") or {}),
    )


def _scene_to_dict(s: SceneBoundary) -> dict[str, Any]:
    return {
        "index": s.index,
        "start_pts": s.start_pts,
        "start_s": s.start_s,
        "end_s": s.end_s,
        "threshold": s.threshold,
        "provider": s.provider,
    }


def _scene_from_dict(d: Any) -> SceneBoundary:
    return SceneBoundary(
        index=int(d.get("index") or 0),
        start_pts=d.get("start_pts"),
        start_s=float(d.get("start_s") or 0.0),
        end_s=float(d.get("end_s") or 0.0),
        threshold=float(d.get("threshold") or 0.0),
        provider=str(d.get("provider") or "umd-reference-scene"),
    )


def _shot_to_dict(s: ShotBoundary) -> dict[str, Any]:
    return {
        "index": s.index,
        "start_pts": s.start_pts,
        "start_s": s.start_s,
        "end_s": s.end_s,
        "threshold": s.threshold,
        "provider": s.provider,
    }


def _shot_from_dict(d: Any) -> ShotBoundary:
    return ShotBoundary(
        index=int(d.get("index") or 0),
        start_pts=d.get("start_pts"),
        start_s=float(d.get("start_s") or 0.0),
        end_s=float(d.get("end_s") or 0.0),
        threshold=float(d.get("threshold") or 0.0),
        provider=str(d.get("provider") or "umd-reference-scene"),
    )


def _frame_to_dict(f: FrameAnchor) -> dict[str, Any]:
    return {"index": f.index, "pts": f.pts, "pts_time_s": f.pts_time_s, "pic_type": f.pic_type}


def _frame_from_dict(d: Any) -> FrameAnchor:
    return FrameAnchor(
        index=int(d.get("index") or 0),
        pts=d.get("pts"),
        pts_time_s=float(d.get("pts_time_s") or 0.0),
        pic_type=d.get("pic_type"),
    )


def _obs_to_dict(o: VideoObservation) -> dict[str, Any]:
    return {
        "kind": o.kind,
        "label": o.label,
        "confidence": o.confidence,
        "generated_by": o.generated_by,
        "note": o.note,
        "quality": o.quality,
    }


def _obs_from_dict(d: Any) -> VideoObservation:
    return VideoObservation(
        kind=str(d.get("kind") or "temporal"),
        label=str(d.get("label") or ""),
        confidence=float(d.get("confidence") or 0.0),
        generated_by=str(d.get("generated_by") or "umd-reference-video v1.0"),
        note=d.get("note"),
        quality=dict(d.get("quality") or {}),
    )


__all__ = ["video_output_from_dict", "video_output_to_dict"]
