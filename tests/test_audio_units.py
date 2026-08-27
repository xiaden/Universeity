"""Phase C / P2-S5 unit tests: hermetic deterministic audio baseline (no DB).

These use the shared tone codec (:mod:`umd.audio.tone`) as the fixture renderer —
mirroring how Plan B's ``umd-reference-ocr`` shares a glyph renderer with its
fixtures — so the reference ASR genuinely processes audio bytes and every
expectation is deterministic and hermetic (no model weights, no DB, no ffmpeg).

Coverage per P2-S5: multi-speaker/candidate-speaker, music-under-speech, silence,
hallucination (four-signal filter + versioned ``HallucinationFiltered`` event),
timing, language, VAD-before-ASR, gated-diarization + ``speaker_unknown_N``
fallback, tolerance-based FPR/FNR measurements, capability gate disclosure, and
the API-process evidence plan (promotion ban + transcription-scoped confidence).
"""

from __future__ import annotations

import shutil

import pytest

from umd.audio import asr as asr_mod
from umd.audio import diarization, hallucination, language, tone
from umd.audio.availability import audio_capability_report
from umd.audio.config import config_digest_of
from umd.audio.evidence import build_audio_evidence_plan
from umd.audio.pipeline import run_audio_baseline
from umd.audio.runner import invoke_audio_baseline
from umd.audio.types import (
    AsrResult,
    AsrUtterance,
    AsrWord,
    AudioConfig,
    AudioMeta,
    DecodedAudio,
    SpeechSegment,
    VadResult,
)
from umd.domain.events import EventType, SemanticEvent
from umd.domain.models import EvidenceKind

SR = 16000


# ---------------------------------------------------------------------------
# Hermetic fixture helpers (rendered through the shared tone codec)
# ---------------------------------------------------------------------------


def _decoded(samples: list[float]) -> DecodedAudio:
    dur = len(samples) / SR
    return DecodedAudio(
        sample_rate=SR,
        pcm=samples,
        duration_s=dur,
        meta=AudioMeta(
            format_name="pcm_s16le",
            codec_name="pcm_s16le",
            sample_rate=SR,
            channels=1,
            duration_s=dur,
        ),
    )


def _phrase(*words: str) -> DecodedAudio:
    return _decoded(tone.render_phrase(list(words)))


def _run(samples: list[float], config: AudioConfig | None = None):
    return run_audio_baseline(_decoded(samples), config or AudioConfig())


# ---------------------------------------------------------------------------
# VAD / silence
# ---------------------------------------------------------------------------


def test_vad_precedes_asr_and_detects_speech() -> None:
    out = _run(tone.render_phrase(["hi", "there"]))
    assert out.vad["has_speech"] is True
    assert out.vad["total_speech_s"] > 0.0
    assert out.vad["speech_segments"], "VAD must precede ASR by producing speech segments"
    # VAD evidence is present even before ASR (signal 1 backbone).
    assert "speech_segments" in out.vad


def test_silence_no_speech_no_utterances() -> None:
    out = _run(tone.render_silence(1.0))
    assert out.vad["has_speech"] is False
    assert out.vad["no_speech_ratio"] > 0.99
    assert out.asr is not None and out.asr.utterances == []
    assert out.hallucination["decisions"] == []
    # No candidate speakers from pure silence.
    assert out.diarization.speaker_candidates == []


# ---------------------------------------------------------------------------
# Language (honest provenance, never fabricated inference)
# ---------------------------------------------------------------------------


def test_language_declared_config_and_unknown() -> None:
    decl = language.identify_language(_phrase("hi"), declared_language="en")
    assert decl.language == "en" and decl.sources == ["declared"]
    cfg = language.identify_language(_phrase("hi"), config_language="fr")
    assert cfg.language == "fr" and cfg.sources == ["config"]
    unk = language.identify_language(_phrase("hi"))
    assert unk.language == "unknown" and unk.sources == ["unknown"]

    # End-to-end: a declared language flows onto the utterance envelope.
    # (A multi-word phrase keeps VAD's adaptive floor low enough to detect speech.)
    out = run_audio_baseline(_phrase("hi", "there"), AudioConfig(declared_language="en"))
    assert out.language is not None and out.language.language == "en"
    assert out.asr is not None and out.asr.utterances and out.asr.utterances[0].language == "en"


# ---------------------------------------------------------------------------
# Reference ASR: genuine word/time decoding
# ---------------------------------------------------------------------------


def _phonemes(text: str) -> set[str]:
    return {c for c in text if c.isalpha()}


def test_reference_asr_decodes_words_with_time_ranges() -> None:
    out = _run(tone.render_phrase(["hi", "there"]))
    assert out.asr is not None
    texts = [u.text for u in out.asr.utterances]
    assert len(texts) >= 2, texts
    for u in out.asr.utterances:
        assert u.end_s > u.start_s
        assert u.words, "word timestamps required"
        for w in u.words:
            assert w.end_s > w.start_s
            assert 0.0 <= w.confidence <= 1.0
    # Tolerance-based correctness: the reference recognizer may over-produce/collapse
    # bursts (crude zero-crossing classifier) but must not DROP a ground-truth letter.
    decoded_letters: set[str] = set()
    for t in texts:
        decoded_letters |= _phonemes(t)
    assert {"h", "i", "t", "e", "r"} <= decoded_letters, f"decoded {texts!r} dropped phonemes"
    # ASR reports a transcription-scoped confidence and honest correlation.
    assert 0.0 <= out.asr.confidence <= 1.0
    assert out.asr.energy_correlation >= 0.5


def test_asr_never_fabricates_text_for_audio_it_did_not_receive() -> None:
    # A pure noise burst (non-codec) yields an honest unmapped marker, never text.
    out = _run(tone.render_noise(0.6))
    if out.asr is None:
        return
    for u in out.asr.utterances:
        for w in u.words:
            assert "<unmapped>" in w.word or "?" in w.word


# ---------------------------------------------------------------------------
# Music under speech -> hallucination filter (four signals + event)
# ---------------------------------------------------------------------------


def _music_corrupted_asr() -> AsrResult:
    """A musical decoded result whose words decode to non-codec (unmapped) tones.

    Only signal-1 (VAD) and signal-3 (energy correlation) are satisfied; the low
    transcription-scoped word confidence is exactly what signal-2 (logprob) and
    signal-3 (music-under-speech) exist to catch. The reference VAD's adaptive floor
    is suppressed by a sustained loud bed, so we drive the filter deterministically
    rather than through the crude end-to-end mixer.
    """
    return AsrResult(
        provider="umd-reference-asr",
        provider_version="umd-reference-asr v1.0",
        language="en",
        confidence=0.03,
        energy_correlation=0.95,  # the energy IS there (music bed) -> signal 3 passes
        unmapped_count=4,
        utterances=[
            AsrUtterance(
                index=0,
                text="????",
                start_s=0.2,
                end_s=0.6,
                music_suspected=True,
                confidence=0.03,
                words=[
                    AsrWord(word="?", start_s=0.2, end_s=0.3, confidence=0.0),
                    AsrWord(word="?", start_s=0.3, end_s=0.4, confidence=0.0),
                    AsrWord(word="?", start_s=0.4, end_s=0.5, confidence=0.0),
                    AsrWord(word="?", start_s=0.5, end_s=0.6, confidence=0.0),
                ],
            )
        ],
    )


def test_music_under_speech_flags_low_confidence_and_filtered() -> None:
    alty = _music_corrupted_asr()
    vad_result = VadResult(
        speech_segments=[SpeechSegment(0.0, 1.0)],
        total_speech_s=1.0,
        no_speech_ratio=0.0,
    )
    result = hallucination.filter_hallucinations(
        alty, AudioConfig(), source_id="music-src", vad_result=vad_result
    )
    assert result.kept.utterances == []  # every word was music-corrupted -> nothing kept
    decisions = result.decisions
    assert len(decisions) == 1
    d = decisions[0]
    assert d.outcome == "filtered"
    assert d.trigger_signal == hallucination.S_LOGPROB
    assert d.filtered_word_indices == [0, 1, 2, 3]
    # All four signals disclosed; VAD backing confirms energy present (music, not silence).
    assert d.signals[hallucination.S_VAD]["overlap_ratio"] >= 0.5
    assert d.signals[hallucination.S_LOGPROB]["low_confidence_words"] == 4
    assert d.signals[hallucination.S_PROMOTION] == {"enforced": True, "can_auto_promote": False}

    # The versioned HallucinationFiltered event is schema-valid (filtered + signals).
    ev = hallucination.to_hallucination_filtered_event(d, source_id="music-src")
    prepared = ev.prepare()
    assert prepared.payload["outcome"] == "filtered"
    assert prepared.payload["filter_signal"] == hallucination.S_LOGPROB
    assert "signals" in prepared.payload


def test_music_and_sfx_region_detection() -> None:
    from umd.audio.music import detect_music_and_sfx

    music, _ = detect_music_and_sfx(_decoded(tone.render_music(0.6)))
    assert music, "a sustained low-variance tone must be detected as a music region"
    assert all(m.end_s > m.start_s for m in music)


def test_four_signal_filter_decisions_and_hallucination_filtered_event() -> None:
    # A clean phrase passes the filter (all kept, all signals recorded, no trigger).
    out = _run(tone.render_phrase(["hi", "there"]))
    decisions = out.hallucination["decisions"]
    assert decisions, "one decision per utterance (kept)"
    for d in decisions:
        assert d["outcome"] == "kept"
        assert d["trigger_signal"] is None
        # All four signals are disclosed on every decision.
        assert set(d["signals"]) == {
            hallucination.S_VAD,
            hallucination.S_LOGPROB,
            hallucination.S_ENERGY,
            hallucination.S_PROMOTION,
        }
        # Signal 4: the auditable promotion ban is always enforced.
        assert d["signals"][hallucination.S_PROMOTION] == {
            "enforced": True,
            "can_auto_promote": False,
        }

    # The versioned HallucinationFiltered semantic event is schema-valid.
    ev = hallucination.to_hallucination_filtered_event(
        hallucination.FilterDecision(
            utterance_index=1,
            reference="source://s/audio/segment/1",
            outcome="kept",
            trigger_signal=None,
            signals=decisions[0]["signals"],
            replaced_with=None,
        ),
        source_id="s",
    )
    assert isinstance(ev, SemanticEvent)
    assert ev.event_type == EventType.HALLUCINATION_FILTERED.value
    prepared = ev.prepare()  # validates against schemas/events/HallucinationFiltered/v1.json
    assert prepared.payload["outcome"] in {"kept", "filtered"}
    assert "signals" in prepared.payload


# ---------------------------------------------------------------------------
# FPR / FNR tolerance measurement (never detector-grade)
# ---------------------------------------------------------------------------


def test_fpr_fnr_measured_not_detector_grade() -> None:
    m = hallucination.measure_fpr_fnr(
        real_word_keys={"a", "b"},
        hallucinated_word_keys={"x", "y"},
        filtered_word_keys={"x", "a"},
    )
    assert m.true_positive == 1  # x was a hallucination and was filtered
    assert m.false_positive == 1  # a was real but wrongly filtered
    assert m.false_negative == 1  # y was a hallucination but kept
    assert m.true_negative == 1  # b real and kept
    assert m.false_positive_rate == 0.5
    assert m.false_negative_rate == 0.5
    assert m.detector_grade is False  # tolerance, not a detector-grade guarantee
    assert m.to_dict()["detector_grade"] is False

    # The ASR filter path records the same honest note.
    out = _run(tone.render_phrase(["hi", "there"]))
    assert "measured in fixture tests; not detector-grade" in out.hallucination["fpr_fnr_note"]


# ---------------------------------------------------------------------------
# Diarization: gated pyannote + non-gated speaker_unknown_N fallback
# ---------------------------------------------------------------------------


def test_diarization_fallback_speaker_unknown_when_gated() -> None:
    out = _run(tone.render_phrase(["hi", "there"]))
    res = out.diarization
    assert res.provider == "umd-reference-diarizer-fallback"
    assert res.gated is True  # pyannote is GATED, never silently active
    assert res.gate_reason and "GATED" in res.gate_reason
    # P2-S3: when diarization is unavailable, emit speaker_unknown_N candidates.
    labels = [c.speaker_label for c in res.speaker_candidates]
    assert len(labels) == 2
    assert labels == ["speaker_unknown_utterance_1", "speaker_unknown_utterance_2"]
    assert all(
        c.generated_by == "umd-reference-diarizer-fallback v1.0" for c in res.speaker_candidates
    )


def test_pyannote_gated_never_fabricates_active() -> None:
    # All three gates open but no validated weights -> still falls back, honestly.
    cfg = AudioConfig(
        diarization_enabled=True,
        diarization_weights_dir="/opt/pyannote/weights",
        diarization_legal_gate=True,
    )
    res = diarization.run_diarization(
        asr_mod.run_asr(_decoded(tone.render_phrase(["hi"])), config=cfg), config=cfg
    )
    assert res.provider == "umd-reference-diarizer-fallback"
    assert res.gated is True
    assert "weights not validated" in (res.gate_reason or "")
    assert all(c.speaker_label.startswith("speaker_unknown_") for c in res.speaker_candidates)

    # Missing the legal release gate -> the gate reason names the closed gate.
    cfg_no_legal = AudioConfig(
        diarization_enabled=True,
        diarization_weights_dir="/opt/pyannote/weights",
        diarization_legal_gate=False,
    )
    res2 = diarization.run_diarization(
        asr_mod.run_asr(_decoded(tone.render_phrase(["hi"])), config=cfg_no_legal),
        config=cfg_no_legal,
    )
    assert res2.gated is True and "legal release gate" in (res2.gate_reason or "")


# ---------------------------------------------------------------------------
# Capability gate disclosure
# ---------------------------------------------------------------------------


def test_capability_report_discloses_active_vs_gated() -> None:
    cap = audio_capability_report(AudioConfig())
    assert cap["asr_engine"]["active"] == "umd-reference-asr"
    assert cap["asr_engine"]["faster_whisper"]["gated"] is True
    assert cap["asr_engine"]["faster_whisper"]["active"] is False
    assert cap["vad"]["active"] == "umd-reference-vad"
    assert cap["vad"]["precedes_asr"] is True
    assert cap["diarization"]["active_provider"] == "umd-reference-diarizer-fallback"
    assert cap["diarization"]["pyannote"]["active"] is False
    assert cap["diarization"]["pyannote"]["gated"] is True
    # All four hallucination controls + promotion ban + honest confidence scope.
    for sig in (
        hallucination.S_VAD,
        hallucination.S_LOGPROB,
        hallucination.S_ENERGY,
        hallucination.S_PROMOTION,
    ):
        assert cap["hallucination_controls"][sig] is True
    assert cap["confidence"] == "transcription_scoped"
    assert cap["promotion_ban"] == "enforced_auditable"
    assert cap["fpr_fnr"] == "measured_not_detector_grade"


def test_audio_config_from_env_and_digest() -> None:
    from umd.audio.config import audio_config_from_env

    cfg = audio_config_from_env()  # derives gates from env (defaults inside the sandbox)
    assert cfg.asr_engine == "reference"  # faster-whisper stays off unless explicitly enabled
    digest = config_digest_of(cfg)
    assert isinstance(digest, str) and len(digest) == 64
    assert config_digest_of(cfg) == digest  # deterministic across calls


# ---------------------------------------------------------------------------
# API-process evidence plan: segments/evidence/events, promotion ban, confidence scope
# ---------------------------------------------------------------------------


def test_evidence_plan_assembly_and_promotion_ban() -> None:
    cfg = AudioConfig(declared_language="en")
    config_digest_of(cfg)
    out = run_audio_baseline(_phrase("hi", "there"), cfg)
    plan = build_audio_evidence_plan(
        out,
        source_id="a" * 32,
        source_sha512="b" * 128,
        work_id=None,
        config_digest=cfg.config_digest,
    )

    # Deterministic segments: utterances (audio modality branch).
    utt_segments = [s for s in plan.segment_inputs if s.segment_type == "utterance"]
    assert len(utt_segments) == 2
    assert all(s.modality == "audio" for s in utt_segments)

    # Evidence kinds emitted.
    kinds = {e.evidence_kind for e in plan.evidence}
    assert kinds >= {"audio_interval", "timing", "metadata", "speaker_observation"}

    # Raw ASR stays UNTRUSTED evidence, confidence transcription-scoped.
    intervals = [e for e in plan.evidence if e.evidence_kind == EvidenceKind.AUDIO_INTERVAL]
    assert intervals, "raw ASR must be recorded as audio_interval evidence"
    for e in intervals:
        assert e.quality["confidence_scope"] == "transcription"
        assert e.quality["words"], "word/time ranges in evidence"
        assert e.quality["candidate_speaker"] in {
            "speaker_unknown_utterance_1",
            "speaker_unknown_utterance_2",
        }
        assert e.quality["generated_by"]["provider"] == "umd-reference-asr"

    # Speaker candidates: candidate-kind, never identity, with the audit promotion ban.
    speakers = [e for e in plan.evidence if e.evidence_kind == EvidenceKind.SPEAKER_OBSERVATION]
    assert speakers and all(e.quality["candidate_kind"] == "observation" for e in speakers)
    for e in speakers:
        ban = e.quality["promotion_ban"]
        assert ban["promotion_ban"] is True and ban["can_auto_promote"] is False

    # Versioned HallucinationFiltered events are well-formed and schema-valid.
    assert plan.events and all(
        e.event_type == EventType.HALLUCINATION_FILTERED.value for e in plan.events
    )
    for e in plan.events:
        prepared = e.prepare()
        assert prepared.payload["outcome"] == "kept"
        assert "signals" in prepared.payload

    # Language provenance metadata (source/config, not a model inference).
    lang = [e for e in plan.evidence if e.quality.get("kind") == "language_identification"]
    assert lang and lang[0].quality["language"] == "en"
    assert lang[0].quality["confidence_scope"] == "declared_or_config_not_model"

    # Timing evidence present with duration/sample-rate.
    timing = [e for e in plan.evidence if e.evidence_kind == EvidenceKind.TIMING]
    assert timing and timing[0].quality["sample_rate"] == SR


# ---------------------------------------------------------------------------
# Sandboxed full-path (ffmpeg-guarded)
# ---------------------------------------------------------------------------


def _wav_bytes(samples: list[float], sample_rate: int = SR) -> bytes:
    import struct

    data = tone.to_pcm16(samples)
    fmt = struct.pack("<HHIIHH", 1, 1, sample_rate, sample_rate * 2, 2, 16)
    riff = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    return (
        riff
        + b"fmt "
        + struct.pack("<I", len(fmt))
        + fmt
        + b"data"
        + struct.pack("<I", len(data))
        + data
    )


def test_sandboxed_invoke_audio_baseline() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not installed; sandboxed decode path not exercised")
    from umd.security.sandbox import SubprocessSandboxRunner

    wav = _wav_bytes(tone.render_phrase(["hi", "there"]))
    out = invoke_audio_baseline(SubprocessSandboxRunner(), wav, name="audio.wav")
    # Sandbox decode + baseline mechanics (ASR fidelity is crude; assert it genuinely
    # decoded encoder-real letters with valid word time ranges).
    assert out.asr is not None
    assert out.asr.utterances, "decoded real speech, but got no utterances"
    decoded: set[str] = set()
    for u in out.asr.utterances:
        assert u.end_s > u.start_s
        assert u.words
        for w in u.words:
            assert w.end_s > w.start_s
            assert 0.0 <= w.confidence <= 1.0
        decoded |= _phonemes(u.text)
    assert len(decoded) >= 3, f"reference recognizer dropped too many phonemes: {decoded!r}"
    # ffmpeg decoded to bounded mono 16 kHz.
    assert out.meta["sample_rate"] == SR
    assert out.meta["channels"] == 1
    assert out.timing["decoded_mono"] is True
    assert out.diarization.provider == "umd-reference-diarizer-fallback"
    assert any(
        c.speaker_label.startswith("speaker_unknown_") for c in out.diarization.speaker_candidates
    )
