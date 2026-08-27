"""API-process evidence assembly for the audio baseline (Phase C, P2-S5).

The worker payload (:class:`~umd.audio.types.AudioOutput`) is structured but not
yet *evidence*. This module maps it — in the API process — onto the Plan A/B
separation: deterministic segments (``audio`` modality), evidence rows (raw ASR
stays untrusted evidence), and the versioned ``HallucinationFiltered`` semantic
events. It never writes semantic state (promotion ban is structural).

Kinds emitted: ``audio_interval`` (utterances + word/time ranges, transcription-
scoped confidence + candidate speaker), ``music`` and ``sound_event`` (regions),
``speaker_observation`` (candidate-kind, NEVER identity), ``timing``,
``metadata`` (language provenance + model-call record), and ``metadata`` for each
hallucination decision (all four signals).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from umd.audio.hallucination import S_PROMOTION
from umd.audio.types import AudioOutput
from umd.domain.events import EventType, SemanticEvent
from umd.domain.locators import PipelineVersion
from umd.domain.models import Evidence, EvidenceKind
from umd.segmentation.registry import SegmentInput

AUDIO_VERSION = PipelineVersion("umd-audio", "ffmpeg", "reference", version=1)


@dataclass
class AudioEvidencePlan:
    """Segments + evidence + events assembled from one baseline output."""

    segment_inputs: list[SegmentInput] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    events: list[SemanticEvent] = field(default_factory=list)
    utterance_locators: dict[int, str] = field(default_factory=dict)

    #: Word-level keys of words the filter decided to remove (for FPR/FNR).
    filtered_word_keys: set[str] = field(default_factory=set)


def build_audio_evidence_plan(
    output: AudioOutput,
    *,
    source_id: Any,
    source_sha512: str,
    work_id: str | None = None,
    config_digest: str | None = None,
) -> AudioEvidencePlan:
    """Assemble the evidence plan from the worker output (no DB writes)."""
    plan = AudioEvidencePlan()
    sid = _hex(source_id)
    tools = _tool_versions(output)

    # --- Per-utterance segments + audio_interval evidence -------------------
    asr = output.asr
    for utt in asr.utterances if asr else []:
        path = f"utterance/{utt.index}"
        plan.segment_inputs.append(
            SegmentInput(
                source_id=sid,
                source_sha512=source_sha512,
                work_id=work_id,
                modality="audio",
                structural_path=path,
                segment_type="utterance",
                version=AUDIO_VERSION,
            )
        )
        locator = f"audio/{path}"
        plan.utterance_locators[utt.index] = locator
        plan.evidence.append(
            Evidence(
                source_id=_uid(source_id),
                evidence_kind=EvidenceKind.AUDIO_INTERVAL,
                locator=locator,
                language=utt.language,
                extraction_stage="LOW_LEVEL_EXTRACTION",
                tool_versions=tools,
                config_digest=config_digest,
                confidence=round(utt.confidence, 4),
                quality={
                    "utterance_index": utt.index,
                    "text": utt.text,
                    "start_s": round(utt.start_s, 4),
                    "end_s": round(utt.end_s, 4),
                    "music_suspected": utt.music_suspected,
                    "candidate_speaker": _candidate_speaker_for(output, utt.index),
                    # Word/time ranges (transcription-scoped, raw evidence).
                    "words": [
                        {
                            "word": w.word,
                            "start_s": round(w.start_s, 4),
                            "end_s": round(w.end_s, 4),
                            "confidence": round(w.confidence, 4),
                        }
                        for w in utt.words
                    ],
                    # Transcription-scoped confidence is explicitly NOT semantic.
                    "confidence_scope": "transcription",
                    "generated_by": {
                        "provider": asr.provider if asr else output.meta.get("decoder"),
                        "version": asr.provider_version if asr else "none",
                    },
                },
            )
        )

    # --- Music + sound-event regions ---------------------------------------
    for idx, r in enumerate(output.music, start=1):
        path = f"music/{idx}"
        plan.segment_inputs.append(
            SegmentInput(
                source_id=sid,
                source_sha512=source_sha512,
                work_id=work_id,
                modality="audio",
                structural_path=path,
                segment_type="music",
                version=AUDIO_VERSION,
            )
        )
        plan.evidence.append(
            Evidence(
                source_id=_uid(source_id),
                evidence_kind=EvidenceKind.MUSIC,
                locator=f"audio/{path}",
                extraction_stage="LOW_LEVEL_EXTRACTION",
                tool_versions=tools,
                config_digest=config_digest,
                confidence=round(r.get("confidence", 0.0), 4),
                quality={
                    "start_s": r.get("start_s"),
                    "end_s": r.get("end_s"),
                    "generated_by": {"provider": "umd-reference-music", "version": "v1.0"},
                },
            )
        )
    for idx, r in enumerate(output.sound_events, start=1):
        path = f"sound_event/{idx}"
        plan.segment_inputs.append(
            SegmentInput(
                source_id=sid,
                source_sha512=source_sha512,
                work_id=work_id,
                modality="audio",
                structural_path=path,
                segment_type="sound_event",
                version=AUDIO_VERSION,
            )
        )
        plan.evidence.append(
            Evidence(
                source_id=_uid(source_id),
                evidence_kind=EvidenceKind.SOUND_EVENT,
                locator=f"audio/{path}",
                extraction_stage="LOW_LEVEL_EXTRACTION",
                tool_versions=tools,
                config_digest=config_digest,
                confidence=round(r.get("confidence", 0.0), 4),
                quality={
                    "start_s": r.get("start_s"),
                    "end_s": r.get("end_s"),
                    "kind": r.get("kind", "sfx"),
                    "generated_by": {"provider": "umd-reference-music", "version": "v1.0"},
                },
            )
        )

    # --- Timing -------------------------------------------------------------
    plan.evidence.append(
        Evidence(
            source_id=_uid(source_id),
            evidence_kind=EvidenceKind.TIMING,
            extraction_stage="LOW_LEVEL_EXTRACTION",
            tool_versions=tools,
            config_digest=config_digest,
            confidence=1.0,
            quality={
                "duration_s": output.timing.get("duration_s"),
                "sample_rate": output.timing.get("sample_rate"),
                "n_samples": output.timing.get("n_samples"),
                "decoded_mono": output.timing.get("decoded_mono"),
                "generated_by": {
                    "provider": asr.provider if asr else output.meta.get("decoder"),
                    "version": asr.provider_version if asr else "none",
                },
            },
        )
    )

    # --- Language provenance (metadata) -------------------------------------
    if output.language is not None:
        plan.evidence.append(
            Evidence(
                source_id=_uid(source_id),
                evidence_kind=EvidenceKind.METADATA,
                locator="audio/language",
                language=output.language.language,
                extraction_stage="LOW_LEVEL_EXTRACTION",
                tool_versions=tools,
                config_digest=config_digest,
                confidence=round(output.language.confidence, 4),
                quality={
                    "kind": "language_identification",
                    "language": output.language.language,
                    "sources": output.language.sources,
                    "provider": output.language.provider,
                    "confidence_scope": "declared_or_config_not_model",
                },
            )
        )

    # --- Speaker candidates (candidate-kind, NEVER identity) ----------------
    for cand in output.diarization.speaker_candidates:
        plan.evidence.append(
            Evidence(
                source_id=_uid(source_id),
                evidence_kind=EvidenceKind.SPEAKER_OBSERVATION,
                locator=plan.utterance_locators.get(cand.utterance_index, "audio"),
                extraction_stage="STRUCTURAL_ANALYSIS",
                tool_versions=tools,
                config_digest=config_digest,
                confidence=round(cand.confidence, 4),
                quality={
                    "candidate_kind": "observation",
                    "speaker_label": cand.speaker_label,
                    "start_s": round(cand.start_s, 4),
                    "end_s": round(cand.end_s, 4),
                    "generated_by": {"provider": cand.generated_by},
                    "promotion_ban": _promotion_ban_block(),
                },
            )
        )

    # --- Hallucination filter decisions: evidence + versioned events --------
    for dec in output.hallucination.get("decisions", []):
        locator = plan.utterance_locators.get(dec["utterance_index"], "audio")
        plan.evidence.append(
            Evidence(
                source_id=_uid(source_id),
                evidence_kind=EvidenceKind.METADATA,
                locator=locator,
                extraction_stage="STRUCTURAL_ANALYSIS",
                tool_versions=tools,
                config_digest=config_digest,
                confidence=None,
                quality={
                    "kind": "hallucination_filter_decision",
                    "outcome": dec["outcome"],
                    "trigger_signal": dec["trigger_signal"],
                    "signals": dec["signals"],
                    "replaced_with": dec["replaced_with"],
                    "filtered_word_indices": dec["filtered_word_indices"],
                    "promotion_ban": _promotion_ban_block(),
                },
            )
        )
        plan.events.append(
            SemanticEvent(
                event_type=EventType.HALLUCINATION_FILTERED.value,
                payload={
                    "source_id": sid,
                    "reference": dec["reference"],
                    "outcome": dec["outcome"],
                    "filter_signal": dec["trigger_signal"],
                    "signals": dec["signals"],
                    "replaced_with": dec["replaced_with"],
                },
                generated_by={"module": "umd.audio", "version": "v1"},
            )
        )
        for w_idx in dec["filtered_word_indices"]:
            plan.filtered_word_keys.add(f"{dec['utterance_index']}:{w_idx}")

    return plan


def _promotion_ban_block() -> dict[str, bool]:
    """The auditable promotion-ban statement attached to candidate/ASR evidence."""
    return {S_PROMOTION: True, "can_auto_promote": False}


def _candidate_speaker_for(output: AudioOutput, utterance_index: int) -> str | None:
    for c in output.diarization.speaker_candidates:
        if c.utterance_index == utterance_index:
            return c.speaker_label
    return None


def _tool_versions(output: AudioOutput) -> dict[str, str]:
    if output.asr is None:
        return {"segmenter": "umd-audio", "decoder": "ffmpeg", "renderer": "reference"}
    asr = output.asr
    return {
        "segmenter": "umd-audio",
        "decoder": "ffmpeg",
        "renderer": "reference",
        "asr": asr.provider,
        "asr_version": asr.provider_version,
        "diarizer": output.diarization.provider,
    }


def _hex(value: Any) -> str:
    return value.hex if hasattr(value, "hex") else str(value)


def _uid(value: Any) -> Any:
    return value
