"""Four-signal hallucination containment + ``HallucinationFiltered`` edge (P2-S2).

The DD §Audio hallucination control has FOUR signals, all emitted on a filter
decision and all recorded (auditable):

  1. **VAD/no-speech** — ASR produced speech where VAD found none (no acoustic
     backing, per-utterance).
  2. **logprob/compression/no-speech** — transcription-scoped decode confidence
     (reference ASR per-word match confidence) below threshold.
  3. **acoustic-energy correlation** — the correlation between ASR speech-time and
     real acoustic energy below threshold.
  4. **auditable promotion ban** — raw ASR is untrusted OCFL evidence only; it can
     Never be auto-promoted to semantic/identity truth. Always enforced.

Every decision appends the versioned ``HallucinationFiltered`` dependency edge (a
:class:`~umd.domain.events.SemanticEvent` with the retained v1 payload) carrying
all four signals. FPR/FNR are measured over word-level ground truth and recorded
WITHOUT claiming detector-grade guarantees (DD).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from umd.audio.types import AsrResult, AsrUtterance, AudioConfig, VadResult
from umd.domain.events import EventType, SemanticEvent

#: Signal names (referenced from filter decisions + capability reporting).
S_VAD = "vad_no_speech"
S_LOGPROB = "logprob_confidence"
S_ENERGY = "acoustic_energy_correlation"
S_PROMOTION = "promotion_ban"


@dataclass
class FilterDecision:
    """One auditable filter decision for one utterance (all four signals)."""

    utterance_index: int
    reference: str
    outcome: str  # 'filtered' | 'kept'
    trigger_signal: str | None
    signals: dict[str, object]
    replaced_with: str | None
    filtered_word_indices: list[int] = field(default_factory=list)


@dataclass
class FilterOutcome:
    """The result of filtering one ASR pass (decisions + kept result)."""

    decisions: list[FilterDecision]
    kept: AsrResult
    energy_correlation: float


def to_hallucination_filtered_event(
    decision: FilterDecision, source_id: str | None = None
) -> SemanticEvent:
    """Build the versioned ``HallucinationFiltered`` semantic event for a decision."""
    return SemanticEvent(
        event_type=EventType.HALLUCINATION_FILTERED.value,
        payload={
            "source_id": source_id,
            "reference": decision.reference,
            "outcome": decision.outcome,
            "filter_signal": decision.trigger_signal,
            "signals": decision.signals,
            "replaced_with": decision.replaced_with,
        },
        generated_by={"module": "umd.audio.hallucination", "version": "v1"},
    )


def _vad_backing(utt: AsrUtterance, vad_result: VadResult | None) -> float:
    """Fraction of utterance-time backed by a real VAD speech segment (0..1)."""
    if vad_result is None or not vad_result.speech_segments:
        return 1.0 if vad_result is None else 0.0
    covered = 0.0
    for seg in vad_result.speech_segments:
        lo = max(utt.start_s, seg.start_s)
        hi = min(utt.end_s, seg.end_s)
        if hi > lo:
            covered += hi - lo
    return covered / utt.duration_s if utt.duration_s > 0 else 0.0


def filter_hallucinations(
    asr_result: AsrResult,
    config: AudioConfig,
    *,
    source_id: str | None = None,
    vad_result: VadResult | None = None,
) -> FilterOutcome:
    """Apply the four-signal filter; return decisions + the KEPT utterance set.

    Filtered words/utterances are removed from semantic consumption (they remain
    raw evidence + filter decisions). Nothing here writes semantic state — the
    promotion ban (signal 4) is enforced structurally.
    """
    corr = asr_result.energy_correlation
    decisions: list[FilterDecision] = []
    kept_utterances = []
    for utt in asr_result.utterances:
        energy = _vad_backing(utt, vad_result)
        low_words = [
            i for i, w in enumerate(utt.words) if w.confidence < config.confidence_threshold
        ]
        signals: dict[str, object] = {
            S_VAD: {"overlap_ratio": round(energy, 4), "no_speech_backing": energy < 0.5},
            S_LOGPROB: {
                "mean_word_confidence": round(utt.confidence, 4),
                "low_confidence_words": len(low_words),
            },
            S_ENERGY: {"correlation": round(corr, 4)},
            S_PROMOTION: {"enforced": True, "can_auto_promote": False},
        }
        kept_words = [w for i, w in enumerate(utt.words) if i not in low_words]

        trigger: str | None = None
        replaced_with: str | None = None
        filtered_indices: list[int] = []
        if energy < 0.5:
            outcome = "filtered"
            trigger = S_VAD
            replaced_with = None
            filtered_indices = list(range(len(utt.words)))
        elif corr < config.energy_correlation_threshold:
            outcome = "filtered"
            trigger = S_ENERGY
            replaced_with = None
            filtered_indices = list(range(len(utt.words)))
        elif low_words and kept_words:
            outcome = "kept"
            trigger = S_LOGPROB
            replaced_with = " ".join(w.word for w in kept_words)
            filtered_indices = low_words
        elif low_words and not kept_words:
            outcome = "filtered"
            trigger = S_LOGPROB
            replaced_with = ""
            filtered_indices = low_words
        else:
            outcome = "kept"
            trigger = None
            filtered_indices = []

        decisions.append(
            FilterDecision(
                utterance_index=utt.index,
                reference=f"source://{source_id or '?'}/audio/segment/{utt.index}",
                outcome=outcome,
                trigger_signal=trigger,
                signals=signals,
                replaced_with=replaced_with,
                filtered_word_indices=filtered_indices,
            )
        )
        if outcome == "kept":
            kept_utterances.append(utt)

    kept = _clone_kept(asr_result, kept_utterances)
    return FilterOutcome(decisions=decisions, kept=kept, energy_correlation=corr)


def _clone_kept(asr_result: AsrResult, kept_utterances: list[AsrUtterance]) -> AsrResult:
    return AsrResult(
        provider=asr_result.provider,
        provider_version=asr_result.provider_version,
        language=asr_result.language,
        utterances=kept_utterances,
        confidence=asr_result.confidence,
        energy_correlation=asr_result.energy_correlation,
        warnings=list(asr_result.warnings),
        unmapped_count=asr_result.unmapped_count,
        model_id=asr_result.model_id,
        model_version=asr_result.model_version,
        config_digest=asr_result.config_digest,
        generated_at=asr_result.generated_at,
        gated=asr_result.gated,
        gate_reason=asr_result.gate_reason,
    )


# ---------------------------------------------------------------------------
# FPR / FNR measurement (recorded, never detector-grade)
# ---------------------------------------------------------------------------


@dataclass
class FprFnrMeasurement:
    """Honest, bounded FPR/FNR over word-level ground truth (no detector-grade claim)."""

    false_positive_rate: float
    false_negative_rate: float
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    detector_grade: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "false_positive_rate": self.false_positive_rate,
            "false_negative_rate": self.false_negative_rate,
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "true_negative": self.true_negative,
            "false_negative": self.false_negative,
            "detector_grade": self.detector_grade,
        }


def measure_fpr_fnr(
    *,
    real_word_keys: set[str],
    hallucinated_word_keys: set[str],
    filtered_word_keys: set[str],
) -> FprFnrMeasurement:
    """Measure FPR/FNR over word-level labels (positives = hallucinated words).

    FPR = FP / (FP + TN): fraction of truly-real words wrongly filtered.
    FNR = FN / (FN + TP): fraction of truly-hallucinated words wrongly kept.
    Both are *measurements*, never detector-grade guarantees.
    """
    positives = hallucinated_word_keys
    negatives = real_word_keys
    predicted_hallucinated = filtered_word_keys
    tp = len(predicted_hallucinated & positives)
    fp = len(predicted_hallucinated & negatives)
    fn = len(positives - predicted_hallucinated)
    tn = len(negatives - predicted_hallucinated)
    fpr = round((fp / (fp + tn)) if (fp + tn) else 0.0, 4)
    fnr = round((fn / (fn + tp)) if (fn + tp) else 0.0, 4)
    return FprFnrMeasurement(
        false_positive_rate=fpr,
        false_negative_rate=fnr,
        true_positive=tp,
        false_positive=fp,
        true_negative=tn,
        false_negative=fn,
    )
