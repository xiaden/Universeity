"""Optional gated diarization + non-gated ``speaker_unknown_N`` fallback (P2-S4).

The DD §Audio requires diarization/speaker embeddings **only** behind the
pyannote weights/license decision (Q1/U1) and vendored pinned weights; the
non-gated/deferred fallback must never block the audio baseline. This module
provides:

  * :func:`speaker_unknown_candidates` — the deterministic, non-gated fallback
    that emits ``speaker_unknown_N`` candidates (one per turn) whenever
    diarization is unavailable/gated. This is what keeps the baseline running with
    no weights and is the ``P2-S3`` candidate-speaker path.
  * :class:`PyannoteDiarizationProvider` — the GATED adapter: raises a typed
    :class:`DiarizationUnavailable` unless the operator explicitly enables it
    (``config.diarization_enabled``) AND pins an offline weights dir
    (``config.diarization_weights_dir``) AND passes the **legal release gate**
    (``config.diarization_legal_gate`` — pyannote community weights require
    legal/commercial sign-off, Q1/U1). It never fabricates an active model.

Capability reporting discloses whether the active path is the fallback or (in
future) an activated pyannote provider — never a silent claim.
"""

from __future__ import annotations

from umd.audio.types import AsrResult, AudioConfig, DiarizationResult, SpeakerCandidate
from umd.domain.models import EntityType


class DiarizationUnavailable(RuntimeError):  # noqa: N818 - stable contract name
    """Diarization could not be used (gated / weights absent / legal gate closed)."""


def speaker_unknown_candidates(
    asr_result: AsrResult, *, turn_of: str = "utterance"
) -> list[SpeakerCandidate]:
    """Deterministic non-gated fallback: one ``speaker_unknown_N`` per turn.

    ``speaker_unknown_N`` is an explicit candidate — never a canonical identity
    (candidate-kind evidence, matching :mod:`~umd.analysis.text_structural` and
    Plan B's object/face non-promotion rule).
    """
    out: list[SpeakerCandidate] = []
    for i, utt in enumerate(asr_result.utterances, start=1):
        out.append(
            SpeakerCandidate(
                utterance_index=utt.index,
                speaker_label=f"speaker_unknown_{turn_of}_{i}",
                confidence=0.3,
                generated_by="umd-reference-diarizer-fallback v1.0",
                start_s=utt.start_s,
                end_s=utt.end_s,
            )
        )
    return out


class PyannoteDiarizationProvider:
    """GATED pyannote diarization/speaker-embedding adapter (license + weights)."""

    name = "pyannote-diarization"
    provider_version = "gated (pyannote)"

    def diarize(self, asr_result: AsrResult, *, config: AudioConfig) -> DiarizationResult:
        if not config.diarization_enabled:
            raise DiarizationUnavailable(
                "pyannote diarization is GATED: UMD_DIARIZATION_ENABLED != true"
            )
        if not config.diarization_weights_dir:
            raise DiarizationUnavailable(
                "pyannote diarization is GATED: no offline weights dir configured"
            )
        if not config.diarization_legal_gate:
            raise DiarizationUnavailable(
                "pyannote diarization is GATED: legal release gate (Q1/U1) not granted"
            )
        # Even with all gates open, the trained runtime is not wired in this
        # hermetic build; the fallback still applies until validated weights are
        # pinned (never fabricated).
        return _fallback(asr_result, gated=True, reason="weights not validated for runtime")


def run_diarization(asr_result: AsrResult, *, config: AudioConfig) -> DiarizationResult:
    """Return the active diarization result: gated-provider if truly active, else fallback."""
    if (
        config.diarization_enabled
        and config.diarization_weights_dir
        and config.diarization_legal_gate
    ):
        try:
            return PyannoteDiarizationProvider().diarize(asr_result, config=config)
        except DiarizationUnavailable as exc:
            return _fallback(asr_result, gated=True, reason=str(exc))
    reason = _gate_reason(config)
    return _fallback(asr_result, gated=bool(reason), reason=reason)


def _fallback(asr_result: AsrResult, *, gated: bool, reason: str | None) -> DiarizationResult:
    return DiarizationResult(
        speaker_candidates=speaker_unknown_candidates(asr_result),
        provider="umd-reference-diarizer-fallback",
        gated=gated,
        gate_reason=reason,
    )


def _gate_reason(config: AudioConfig) -> str | None:
    if not config.diarization_enabled:
        return "UMD_DIARIZATION_ENABLED not set (pyannote GATED)"
    if not config.diarization_weights_dir:
        return "no offline weights dir configured (pyannote GATED)"
    if not config.diarization_legal_gate:
        return "legal release gate (Q1/U1) not granted (pyannote GATED)"
    return None


#: Typecarried for capability disclosure (candidate-kind, not canonical identity).
CANDIDATE_KIND = "observation"
CANDIDATE_ENTITY_TYPE = EntityType.SPEAKER_IDENTITY.value
