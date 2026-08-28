"""P1-S1/P1-S5 spec-first tests for the ordinary-speech (faster-whisper) ASR path.

Plan H Phase 1 is the spec-first phase: these tests are TESTS ONLY — no ``src/``
changes. They pin the transition contract for a self-hostable ordinary-speech
ASR path and the invariant that configured ASR is never bypassed.

Ordinary-speech model assumption (documented): the fast-whisper path needs a
small validated model cached on disk. The cache location is ``UMD_ASR_MODEL_CACHE``
(or the ``AudioConfig.asr_model_dir`` equivalent); ``faster-whisper`` must also be
installed (the optional runtime extra from Plan H P2-S1). In this test environment
neither is present, so the *runnable* path is honestly gated (skipped with a named
gate reason), exactly like the CONTRACTS capability-status convention — never a
fabricated active run.

What can pass now and is pinned:
  * faster-whisper absent → the provider raises :class:`AsrProviderUnavailable`
    and NEVER invents a transcript;
  * ``run_asr(asr_engine="faster-whisper")`` returns the honest reference transcript
    explicitly marked ``gated=True`` with a named gate reason;
  * ``AudioPipeline.asr_result`` regression: a *configured* provider is dispatched
    to rather than hardcoded reference (P2-S3 wires centralized selection);
  * the four-signal hallucination filter + promotion ban remain intact for any
    configured/gated path, and raw (pre-filter) ASR stays recoverable untrusted
    evidence (P2-S4).
"""

from __future__ import annotations

import os
import struct

import pytest

from umd.audio import asr as asr_mod
from umd.audio import hallucination, tone
from umd.audio.pipeline import AudioPipeline
from umd.audio.types import (
    AsrResult,
    AsrUtterance,
    AsrWord,
    AudioConfig,
    AudioMeta,
    DecodedAudio,
)

SR = 16000

#: Named gate reason for the self-hostable ASR path when the runtime/model is absent.
_FW_GATE_REASON = (
    "configured-but-unavailable: faster-whisper runtime and/or model cache "
    "(UMD_ASR_MODEL_CACHE) absent"
)


def _model_cache() -> str | None:
    return os.environ.get("UMD_ASR_MODEL_CACHE")


def _faster_whisper_ready() -> bool:
    """Honest readiness probe: runtime installed AND a validated model cache exists.

    Reuses :func:`umd.audio.asr.faster_whisper_runtime_ready` as the single source
    of truth — it requires the runtime to be importable AND ``model.bin`` present
    in the cache dir (an existing-but-empty cache dir must skip, not hard-fail).
    """
    return asr_mod.faster_whisper_runtime_ready()


# --- ordinary-speech fixture helpers ----------------------------------------


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


def _decoded_from_wav(wav: bytes) -> DecodedAudio:
    """Parse a deterministic PCM16 mono WAV into a :class:`DecodedAudio`."""
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    data = b""
    fmt: dict[str, int] = {}
    off = 12
    while off < len(wav):
        chunk = wav[off : off + 4]
        (size,) = struct.unpack_from("<I", wav, off + 4)
        body = wav[off + 8 : off + 8 + size]
        if chunk == b"fmt ":
            fmt["channels"], fmt["rate"], fmt["bits"] = struct.unpack_from("<HIH", body, 2)
        elif chunk == b"data":
            data = body
        off += 8 + size
    sample_rate = fmt.get("rate", SR)
    channels = fmt.get("channels", 1)
    n = len(data) // 2
    pcm = [struct.unpack_from("<h", data, i * 2)[0] / 32768.0 for i in range(n)]
    if channels > 1:  # downmix to mono deterministically
        pcm = [sum(pcm[i : i + channels]) / channels for i in range(0, len(pcm), channels)]
    dur = len(pcm) / sample_rate
    return DecodedAudio(
        sample_rate=sample_rate,
        pcm=pcm,
        duration_s=dur,
        meta=AudioMeta(
            format_name="pcm_s16le",
            codec_name="pcm_s16le",
            sample_rate=sample_rate,
            channels=1,
            duration_s=dur,
        ),
    )


# --- P1-S1(a): unavailable provider must NOT invent a transcript -------------


def test_faster_whisper_unavailable_when_runtime_absent_no_invented_transcript() -> None:
    """(a) When the runtime/model is absent the provider reports unavailable and
    never invents a transcript. This PASSES today."""
    cfg = AudioConfig(asr_engine="faster-whisper", asr_model_dir=None)
    provider = asr_mod.FasterWhisperAsrProvider()
    with pytest.raises(asr_mod.AsrProviderUnavailable):
        provider.asr(_phrase("hello", "there"), config=cfg)

    # The dispatch path returns the honest reference transcript explicitly marked
    # gated, never a fabricated faster-whisper transcript and never an empty/active claim.
    result = asr_mod.run_asr(_phrase("hello", "there"), config=cfg)
    assert result.gated is True
    assert result.provider == "umd-reference-asr"
    assert result.provider != "faster-whisper"
    assert result.gate_reason and "faster-whisper" in result.gate_reason
    # Transcription still genuinely happened through the reference provider (not invented).
    assert result.utterances


def test_faster_whisper_provider_never_reports_active_when_not_wired() -> None:
    """The adapter must not claim an active engine for any absent-weights posture."""
    # Engine configured but no model dir -> unavailable, never active.
    with pytest.raises(asr_mod.AsrProviderUnavailable):
        asr_mod.FasterWhisperAsrProvider().asr(
            _phrase("hi"), config=AudioConfig(asr_engine="faster-whisper", asr_model_dir=None)
        )
    # Engine not selected at all -> unavailable (gated), never active.
    with pytest.raises(asr_mod.AsrProviderUnavailable):
        asr_mod.FasterWhisperAsrProvider().asr(
            _phrase("hi"), config=AudioConfig(asr_engine="reference")
        )


# --- P1-S1(b): runnable path when a validated runtime+model is present (gated) --


@pytest.mark.skipif(
    not _faster_whisper_ready(),
    reason=_FW_GATE_REASON,
)
def test_faster_whisper_dispatch_yields_timestamps_and_provenance() -> None:
    """(b) WHEN a validated runtime+model is present, provider dispatch yields word
    + utterance timestamps, language, transcription confidence, and provider/model
    provenance. Honestly skipped when the gate is absent. Fails in the right way if
    the dispatch mechanism itself is still missing (unexpected AsrProviderUnavailable
    or a still-gated result)."""
    from fixtures import ordinary_speech_wav_bytes

    audio = _decoded_from_wav(ordinary_speech_wav_bytes())
    cfg = AudioConfig(asr_engine="faster-whisper", asr_model_dir=_model_cache())
    result = asr_mod.run_asr(audio, config=cfg)
    assert result.provider == "faster-whisper", f"dispatch mechanism missing: {result}"
    assert result.gated is False, "runtime present but ASR still reported gated"
    assert result.language  # language identified (declared/config/model)
    assert result.utterances, "validated runtime produced no utterances"
    for u in result.utterances:
        assert u.end_s > u.start_s  # utterance timestamps
        assert u.words and all(w.end_s > w.start_s for w in u.words)  # word timestamps
        assert all(0.0 <= w.confidence <= 1.0 for w in u.words)
    assert 0.0 <= result.confidence <= 1.0  # transcription-scoped confidence
    # Model/version/provider/config provenance is retained on the result.
    assert result.provider_version and result.provider


# --- P1-S5: configured ASR is not bypassed by AudioPipeline.asr_result ---------


def test_audio_pipeline_dispatches_configured_provider_not_reference() -> None:
    """A *configured* ASR provider is dispatched to by ``AudioPipeline.asr_result``
    rather than hardcoding the reference provider (P2-S3 centralizes selection via
    ``run_asr``). PASSES now: a registered configured provider must be invoked — this
    pins the regression that a bypass back to the hardcoded reference would break.
    """
    calls: list[str] = []

    class FakeProvider:
        name = "umd-fake-asr"
        provider_version = "umd-fake-asr v1.0"

        def asr(self, audio: DecodedAudio, *, config: AudioConfig) -> AsrResult:
            del audio, config  # fake configured provider ignores its inputs
            calls.append(self.name)
            return AsrResult(
                provider=self.name,
                provider_version=self.provider_version,
                language="en",
                confidence=1.0,
                energy_correlation=1.0,
                utterances=[
                    AsrUtterance(
                        index=1,
                        text="FAKE",
                        start_s=0.0,
                        end_s=0.1,
                        words=[AsrWord(word="FAKE", start_s=0.0, end_s=0.1, confidence=1.0)],
                        confidence=1.0,
                        language="en",
                    )
                ],
            )

    fake = FakeProvider()
    asr_mod.ASR_PROVIDERS["fake"] = fake  # type: ignore[assignment]  # register configured provider
    try:
        out = AudioPipeline(_phrase("hi", "there"), AudioConfig(asr_engine="fake")).asr_result
    finally:
        asr_mod.ASR_PROVIDERS.pop("fake", None)
    assert calls == ["umd-fake-asr"], "AudioPipeline bypassed the configured ASR provider"
    assert out.provider == "umd-fake-asr"


def test_configured_asr_still_four_signal_filtered_and_not_promoted() -> None:
    """The four-signal hallucination filter + promotion ban survive any provider
    selection. A low-confidence (music-corrupted) ASR is filtered with all four
    signals disclosed, and the raw (pre-filter) output remains recoverable."""
    alty = AsrResult(
        provider="umd-reference-asr",
        provider_version="umd-reference-asr v1.0",
        language="en",
        confidence=0.03,
        energy_correlation=0.95,
        unmapped_count=4,
        utterances=[
            AsrUtterance(
                index=1,
                text="????",
                start_s=0.2,
                end_s=0.6,
                music_suspected=True,
                confidence=0.03,
                words=[
                    AsrWord(word="?", start_s=0.2, end_s=0.3, confidence=0.0),
                    AsrWord(word="?", start_s=0.3, end_s=0.4, confidence=0.0),
                ],
            )
        ],
    )
    outcome = hallucination.filter_hallucinations(
        alty, AudioConfig(), source_id="src", vad_result=None
    )
    assert outcome.kept.utterances == []
    d = outcome.decisions[0]
    assert d.outcome == "filtered"
    # All four signals disclosed on the filtered decision.
    assert {
        hallucination.S_VAD,
        hallucination.S_LOGPROB,
        hallucination.S_ENERGY,
        hallucination.S_PROMOTION,
    }.issubset(d.signals)
    # Signal 4: auditable promotion ban, never auto-promote.
    assert d.signals[hallucination.S_PROMOTION] == {
        "enforced": True,
        "can_auto_promote": False,
    }
    # Raw (pre-filter) ASR remains recoverable as untrusted evidence.
    assert alty.utterances, "raw ASR must be retained, not silently dropped"
