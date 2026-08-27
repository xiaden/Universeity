"""API-process evidence assembly for the video baseline (Phase C, P3-S1/S2).

The worker payload (:class:`~umd.video.types.VideoOutput`) is structured but not
yet *evidence*. This module maps it — in the API process — onto the Plan A/B
separation: deterministic segments (``video`` modality), evidence rows (scene/
shot/frame/time/track + candidate observations), and the audio-branch
composition that reuses the Phase-2 audio baseline. It never writes semantic
state (candidate observations carry an auditable promotion ban; the promotion
ban is structural).

Kinds emitted (existing EvidenceKind members only, per the immutable exact-set
test): ``scene_boundary`` (scenes+shots), ``frame`` (PTS-native frame anchors),
``video_interval`` (scene/shot time spans), ``metadata`` (stream/track
inventory + composition + env/object/temporal candidate observations), ``timing``.
Subtitle tracks are announced here but extracted/parsed by the independent
subtitle worker into their own independent sources (never flattened).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from umd.domain.locators import MediaFragmentSelector, PipelineVersion
from umd.domain.models import Evidence, EvidenceKind
from umd.segmentation.registry import SegmentInput
from umd.video.types import VideoOutput

VIDEO_VERSION = PipelineVersion("umd-video", "ffmpeg", "reference", version=1)

#: The promotion-ban statement attached to candidate observation evidence.
PROMOTION_BAN = {"promotion_ban": True, "can_auto_promote": False}


@dataclass
class VideoEvidencePlan:
    """Segments + evidence + audio-branch composition from one baseline output."""

    segment_inputs: list[SegmentInput] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    audio_tracks: list[dict[str, Any]] = field(default_factory=list)
    subtitle_tracks: list[dict[str, Any]] = field(default_factory=list)


def _hex(value: Any) -> str:
    return value.hex if hasattr(value, "hex") else str(value)


def build_video_evidence_plan(
    output: VideoOutput,
    *,
    source_id: Any,
    source_sha512: str,
    work_id: str | None = None,
    config_digest: str | None = None,
) -> VideoEvidencePlan:
    """Assemble the evidence plan from the worker output (no DB writes)."""
    plan = VideoEvidencePlan()
    sid = _hex(source_id)

    # --- File-level segment -------------------------------------------------
    plan.segment_inputs.append(
        SegmentInput(
            source_id=sid,
            source_sha512=source_sha512,
            work_id=work_id,
            modality="video",
            structural_path="file/1",
            segment_type="file",
            version=VIDEO_VERSION,
        )
    )

    # --- Track segments + stream-inventory metadata -------------------------
    audio_compose: list[dict[str, Any]] = []
    for t in output.inventory:
        seg_type = t.codec_type  # video | audio | subtitle
        path = f"track/{t.index}"
        plan.segment_inputs.append(
            SegmentInput(
                source_id=sid,
                source_sha512=source_sha512,
                work_id=work_id,
                modality="video",
                structural_path=path,
                segment_type=seg_type,
                version=VIDEO_VERSION,
            )
        )
        plan.evidence.append(
            Evidence(
                source_id=_uid(source_id),
                evidence_kind=EvidenceKind.METADATA,
                locator=f"video/{path}",
                language=t.language,
                track=str(t.index),
                extraction_stage="FORMAT_ANALYSIS",
                tool_versions=_tool_versions(),
                config_digest=config_digest,
                confidence=1.0,
                quality={
                    "kind": "stream_inventory",
                    "codec_type": t.codec_type,
                    "codec_name": t.codec_name,
                    "disposition": t.disposition,
                    "title": t.title,
                    "width": t.width,
                    "height": t.height,
                    "time_base": t.time_base,
                    "avg_frame_rate": t.avg_frame_rate,
                    "sample_rate": t.sample_rate,
                    "channels": t.channels,
                    "duration": t.duration,
                    "pts_start": t.pts_start,
                },
            )
        )
        if t.codec_type == "audio":
            # Audio branch composition: record the video<->audio track pair so the
            # Phase-2 audio baseline operates on the matching audio stream.
            audio_compose.append(
                {
                    "video_track_index": None,
                    "audio_track_index": t.index,
                    "language": t.language,
                    "pts_start": t.pts_start,
                    "audio_branch": "umd.audio baseline",
                }
            )

    # --- Scene + shot boundaries -------------------------------------------
    for sc in output.scenes:
        plan.segment_inputs.append(
            SegmentInput(
                source_id=sid,
                source_sha512=source_sha512,
                work_id=work_id,
                modality="video",
                structural_path=f"scene/{sc.index}",
                segment_type="scene",
                version=VIDEO_VERSION,
                frag=MediaFragmentSelector(t=f"{sc.start_s},{sc.end_s}"),
            )
        )
        plan.evidence.append(
            Evidence(
                source_id=_uid(source_id),
                evidence_kind=EvidenceKind.SCENE_BOUNDARY,
                locator=f"video/scene/{sc.index}",
                extraction_stage="LOW_LEVEL_EXTRACTION",
                tool_versions=_tool_versions(),
                config_digest=config_digest,
                confidence=0.8,
                quality={
                    "start_s": sc.start_s,
                    "end_s": sc.end_s,
                    "start_pts": sc.start_pts,
                    "threshold": sc.threshold,
                    "provider": sc.provider,
                    "generated_by": {"provider": sc.provider},
                },
            )
        )
        plan.evidence.append(
            Evidence(
                source_id=_uid(source_id),
                evidence_kind=EvidenceKind.VIDEO_INTERVAL,
                locator=f"video/scene/{sc.index}",
                extraction_stage="LOW_LEVEL_EXTRACTION",
                tool_versions=_tool_versions(),
                config_digest=config_digest,
                confidence=0.8,
                quality={
                    "kind": "scene_time",
                    "start_s": sc.start_s,
                    "end_s": sc.end_s,
                    "segmentation": "PTS-native",
                },
            )
        )
    for sh in output.shots:
        plan.segment_inputs.append(
            SegmentInput(
                source_id=sid,
                source_sha512=source_sha512,
                work_id=work_id,
                modality="video",
                structural_path=f"shot/{sh.index}",
                segment_type="shot",
                version=VIDEO_VERSION,
                frag=MediaFragmentSelector(t=f"{sh.start_s},{sh.end_s}"),
            )
        )
        plan.evidence.append(
            Evidence(
                source_id=_uid(source_id),
                evidence_kind=EvidenceKind.SCENE_BOUNDARY,
                locator=f"video/shot/{sh.index}",
                extraction_stage="LOW_LEVEL_EXTRACTION",
                tool_versions=_tool_versions(),
                config_digest=config_digest,
                confidence=0.7,
                quality={
                    "kind": "shot",
                    "start_s": sh.start_s,
                    "end_s": sh.end_s,
                    "start_pts": sh.start_pts,
                    "provider": sh.provider,
                },
            )
        )

    # --- PTS-native frame anchors -------------------------------------------
    for f in output.frame_anchors:
        plan.segment_inputs.append(
            SegmentInput(
                source_id=sid,
                source_sha512=source_sha512,
                work_id=work_id,
                modality="video",
                structural_path=f"frame/{f.index}",
                segment_type="frame",
                version=VIDEO_VERSION,
                frag=MediaFragmentSelector(t=f"{f.pts_time_s:.4f}"),
            )
        )
        plan.evidence.append(
            Evidence(
                source_id=_uid(source_id),
                evidence_kind=EvidenceKind.FRAME,
                locator=f"video/frame/{f.index}",
                extraction_stage="LOW_LEVEL_EXTRACTION",
                tool_versions=_tool_versions(),
                config_digest=config_digest,
                confidence=1.0,
                quality={
                    "pts": f.pts,
                    "pts_time_s": f.pts_time_s,
                    "pic_type": f.pic_type,
                    "pts_native": True,
                },
            )
        )

    # --- Candidate observations (env/object/temporal) ------------------------
    for o in output.observations:
        plan.evidence.append(
            Evidence(
                source_id=_uid(source_id),
                evidence_kind=EvidenceKind.METADATA,
                locator="video/file/1",
                extraction_stage="STRUCTURAL_ANALYSIS",
                tool_versions=_tool_versions(),
                config_digest=config_digest,
                confidence=round(o.confidence, 4),
                quality={
                    "kind": f"{o.kind}_observation",
                    "candidate_kind": "observation",
                    "label": o.label,
                    "note": o.note,
                    "generated_by": {"provider": o.generated_by},
                    "promotion_ban": PROMOTION_BAN,
                    **(o.quality or {}),
                },
            )
        )

    # --- Timing --------------------------------------------------------------
    plan.evidence.append(
        Evidence(
            source_id=_uid(source_id),
            evidence_kind=EvidenceKind.TIMING,
            extraction_stage="LOW_LEVEL_EXTRACTION",
            tool_versions=_tool_versions(),
            config_digest=config_digest,
            confidence=1.0,
            quality={
                "duration_s": output.timing.get("duration_s"),
                "fps": output.timing.get("fps"),
                "time_base": output.timing.get("time_base"),
                "generated_by": {"provider": "umd-reference-video", "version": "v1.0"},
            },
        )
    )

    # --- Audio branch composition + subtitle announcements -------------------
    plan.audio_tracks = list(output.audio_tracks)
    plan.subtitle_tracks = list(output.subtitle_tracks)
    plan.evidence.append(
        Evidence(
            source_id=_uid(source_id),
            evidence_kind=EvidenceKind.METADATA,
            locator="video/file/1#composition/audio",
            extraction_stage="LOW_LEVEL_EXTRACTION",
            tool_versions=_tool_versions(),
            config_digest=config_digest,
            confidence=1.0,
            quality={
                "kind": "video_audio_composition",
                "audio_tracks": audio_compose,
                "subtitle_tracks": [
                    {
                        "index": st["index"],
                        "codec_name": st["codec_name"],
                        "language": st["language"],
                    }
                    for st in output.subtitle_tracks
                ],
                "audio_branch": "Phase-2 audio baseline (independent) — never flattened",
                "subtitle_tracks_independent_sources": True,
            },
        )
    )
    return plan


def _tool_versions() -> dict[str, str]:
    return {"segmenter": "umd-video", "decoder": "ffmpeg", "renderer": "reference"}


def _uid(value: Any) -> Any:
    return value


__all__ = ["PROMOTION_BAN", "VIDEO_VERSION", "VideoEvidencePlan", "build_video_evidence_plan"]
