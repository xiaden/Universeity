"""API-process evidence assembly for INDEPENDENT subtitle sources (P3-S2..S4).

Every subtitle track is an INDEPENDENT source/evidence stream: never flattened
into one representation, never treated as authoritative over another. Each track
contributes:

  * a ``track`` segment (modality ``subtitle``, media-fragment/scoped by track),
  * ``subtitle_event`` segments for each timed cue,
  * ``subtitle_event`` evidence (timing, verbatim text, style/speaker/sign/song/
    HI/SDH flags) at the SUBTITLE-EVENT confidence,
  * ``metadata`` evidence for track/codec/language/disposition + any WebVTT
    ``X-TIMESTAMP-MAP`` normalization that was applied.

All evidence is LOW-LEVEL, never promoted; raw bytes remain authoritative.
Kinds are existing EvidenceKind members only (immutable exact-set constraint).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from umd.domain.locators import MediaFragmentSelector, PipelineVersion
from umd.domain.models import Evidence, EvidenceKind
from umd.segmentation.registry import SegmentInput
from umd.subtitle.types import SubtitleTrack

SUBTITLE_VERSION = PipelineVersion("umd-subtitle", "pysubs2", "reference", version=1)

#: Subtitle-event confidence (independent-track evidence, not promotion-worthy).
SUBTITLE_EVENT_CONFIDENCE = 0.9


@dataclass
class SubtitleEvidencePlan:
    """Segments + evidence from one INDEPENDENT subtitle track."""

    segment_inputs: list[SegmentInput] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    track: SubtitleTrack | None = None


def _hex(value: Any) -> str:
    return value.hex if hasattr(value, "hex") else str(value)


def build_subtitle_evidence_plan(
    track: SubtitleTrack,
    *,
    source_id: Any,
    source_sha512: str,
    work_id: str | None = None,
    config_digest: str | None = None,
) -> SubtitleEvidencePlan:
    """Assemble the evidence plan for one independent subtitle track (no DB writes)."""
    plan = SubtitleEvidencePlan(track=track)
    sid = _hex(source_id)
    track_id = track.index if track.index is not None else 0

    # --- track segment + metadata ------------------------------------------
    plan.segment_inputs.append(
        SegmentInput(
            source_id=sid,
            source_sha512=source_sha512,
            work_id=work_id,
            modality="subtitle",
            structural_path=f"track/{track_id}",
            segment_type="track",
            version=SUBTITLE_VERSION,
            metadata_={
                "language": track.language,
                "title": track.title,
                "codec_name": track.codec_name,
                "source_note": track.source_note,
                "format": track.format,
                "charset": track.charset,
                "surrogate_preserved": track.surrogate_preserved,
                "translation_source": track.translation_source,
            },
        )
    )
    meta_quality: dict[str, Any] = {
        "kind": "subtitle_track",
        "format": track.format,
        "language": track.language,
        "title": track.title,
        "disposition": track.disposition,
        "charset": track.charset,
        "charset_confidence": track.charset_confidence,
        "surrogate_preserved": track.surrogate_preserved,
        "source_note": track.source_note,
        "scan_type": "independent_track",
        "independent_source": True,
    }
    if track.normalization is not None:
        meta_quality["webvtt_normalization"] = track.normalization
    plan.evidence.append(
        Evidence(
            source_id=_source_id(source_id),
            evidence_kind=EvidenceKind.METADATA,
            locator=f"subtitle/track/{track_id}",
            language=track.language,
            track=str(track_id),
            extraction_stage="FORMAT_ANALYSIS",
            tool_versions=_tool_versions(),
            config_digest=config_digest,
            confidence=1.0,
            quality=meta_quality,
        )
    )

    # --- per-event segments + evidence --------------------------------------
    for e in track.events:
        path = f"subtitle_event/{e.index}"
        plan.segment_inputs.append(
            SegmentInput(
                source_id=sid,
                source_sha512=source_sha512,
                work_id=work_id,
                modality="subtitle",
                structural_path=path,
                segment_type="subtitle_event",
                version=SUBTITLE_VERSION,
                frag=MediaFragmentSelector(t=f"{e.start_ms / 1000.0:.3f},{e.end_ms / 1000.0:.3f}"),
                metadata_={
                    "start_ms": e.start_ms,
                    "end_ms": e.end_ms,
                    "text": e.text,
                    "speaker": e.speaker,
                    "style": e.style,
                    "is_hi": e.is_hi,
                    "is_sdh": e.is_sdh,
                    "is_sign": e.is_sign,
                    "is_song": e.is_song,
                },
            )
        )
        plan.evidence.append(
            Evidence(
                source_id=_source_id(source_id),
                evidence_kind=EvidenceKind.SUBTITLE_EVENT,
                locator=f"subtitle/{path}",
                language=track.language,
                track=str(track_id),
                extraction_stage="LOW_LEVEL_EXTRACTION",
                tool_versions=_tool_versions(),
                config_digest=config_digest,
                confidence=SUBTITLE_EVENT_CONFIDENCE,
                quality={
                    "start_ms": e.start_ms,
                    "end_ms": e.end_ms,
                    "text": e.text,
                    "style": e.style,
                    "speaker": e.speaker,
                    "actor": e.actor,
                    "layer": e.layer,
                    "subtitle_flags": {
                        "hi": e.is_hi,
                        "sdh": e.is_sdh,
                        "sign": e.is_sign,
                        "song": e.is_song,
                    },
                    "verbatim_preserved": True,
                    "independent_track": track_id,
                },
            )
        )
    return plan


def _source_id(value: Any) -> Any:
    return value


def _tool_versions() -> dict[str, str]:
    return {"segmenter": "umd-subtitle", "parser": "pysubs2", "renderer": "reference"}


__all__ = ["SUBTITLE_VERSION", "SubtitleEvidencePlan", "build_subtitle_evidence_plan"]
