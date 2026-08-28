"""P1-S2: provider capability-transition tests (spec-first, TESTS ONLY).

Pins the honest transition vocabulary across the provider lifecycle:
``active`` / ``reference-only`` / ``configured-but-unavailable`` / ``gated`` /
``disabled`` — and asserts the same statuses are exposed through the
``/v1/capabilities`` API endpoint and the audio baseline warnings.

* default reference-only (reference ASR active, faster-whisper gated);
* configured-but-unavailable when engine/weights are missing (faster-whisper today);
* active when the validated runtime is present (honestly gate-skipped);
* gated for unvalidated heavyweight paths (pyannote diarization, PaddleOCR).

Pass-now assertions verify what the environment truthfully reports (absent
faster-whisper, absent tesseract binary); the API cross-check asserts the same
statuses the report function exposes are the ones served by ``/v1/capabilities``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fixtures import raster_text_only_bytes
from umd.audio import tone
from umd.audio.availability import audio_capability_report, flatten_audio_capabilities
from umd.audio.pipeline import run_audio_baseline
from umd.audio.types import AudioConfig, AudioMeta, DecodedAudio
from umd.raster.ocr import OcrProviderUnavailable, _tesseract_available, run_ocr
from umd.security.capabilities import capability_report

SR = 16000

#: Canonical status vocabulary (Task §13/DD §"Provider interfaces", CONTRACTS).
ACTIVE = "active"
REFERENCE_ONLY = "reference-only"
CONFIGURED_UNAVAILABLE = "configured-but-unavailable"
GATED = "gated"
DISABLED = "disabled"


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


def _audio_status(cap: dict) -> dict:
    """Map the audio capability block to the canonical status vocabulary."""
    asr = cap["asr_engine"]
    fw = asr["faster_whisper"]
    if fw["active"]:
        fw_status = ACTIVE
    elif fw["enabled"]:
        fw_status = CONFIGURED_UNAVAILABLE
    else:
        fw_status = GATED
    return {
        "asr_engine": ACTIVE if asr["active"] == "umd-reference-asr" else REFERENCE_ONLY,
        "faster_whisper": fw_status,
        "diarization": (GATED if cap["diarization"]["pyannote"]["gated"] else DISABLED),
    }


# ---------------------------------------------------------------------------
# Pass-now: default reference-only, configured-but-unavailable, gated
# ---------------------------------------------------------------------------


def test_default_reference_only_and_faster_whisper_configured_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap = audio_capability_report(AudioConfig())
    status = _audio_status(cap)
    assert status["asr_engine"] == ACTIVE  # reference provider genuinely active
    # faster-whisper engine not selected by default -> gated, never active.
    assert cap["asr_engine"]["active"] == "umd-reference-asr"
    assert cap["asr_engine"]["faster_whisper"]["gated"] is True
    assert cap["asr_engine"]["faster_whisper"]["active"] is False

    # Requesting faster-whisper (configured) but runtime absent -> configured-but-unavailable.
    # Deterministic regardless of environment: never fall back to a provisioned
    # UMD_ASR_MODEL_CACHE (that would honestly report ACTIVE); pin an explicit
    # nonexistent model dir and clear the env cache so the gate is exercised.
    monkeypatch.delenv("UMD_ASR_MODEL_CACHE", raising=False)
    cap_cfg = audio_capability_report(
        AudioConfig(asr_engine="faster-whisper", asr_model_dir="/nonexistent/umd-model-cache")
    )
    assert _audio_status(cap_cfg)["faster_whisper"] == CONFIGURED_UNAVAILABLE


def test_tesseract_absent_is_configured_but_unavailable_never_active() -> None:
    # Tesseract binary is NOT installed in this environment: the provider gate is
    # honest (no fabricated active OCR). The transition is "configured-but-unavailable".
    assert _tesseract_available() is False
    with pytest.raises(OcrProviderUnavailable) as exc:
        run_ocr(raster_text_only_bytes(), "tesseract")
    assert "tesseract" in str(exc.value).lower()


def test_heavyweight_paths_gated_pyannote_and_paddle() -> None:
    # pyannote diarization is gated behind license/weights (never active).
    cap = audio_capability_report(AudioConfig())
    assert cap["diarization"]["pyannote"]["gated"] is True
    assert cap["diarization"]["pyannote"]["active"] is False
    assert _audio_status(cap)["diarization"] == GATED

    # PaddleOCR is a named gate (not installed), never reported active.
    from umd.raster.ocr import PADDLE_GATE

    with pytest.raises(OcrProviderUnavailable) as exc:
        run_ocr(raster_text_only_bytes(), "paddle")
    assert PADDLE_GATE in str(exc.value)


def test_evidence_warnings_expose_same_status_as_capability_report() -> None:
    # The pipeline warnings expose the same gates as the capability report.
    # (pyannote diarization gate is genuinely surfaced in the baseline warnings.)
    cap = audio_capability_report(AudioConfig())
    assert cap["diarization"]["pyannote"]["gated"] is True
    out = run_audio_baseline(_decoded(tone.render_phrase(["hi", "there"])), AudioConfig())
    assert any("diarization gated" in w for w in out.warnings), (
        "pipeline warnings must expose the same diarization gate as the report"
    )
    # faster-whisper requested but runtime absent -> configured-but-unavailable in
    # the capability report (the pipeline-side faster-whisper gate warning is wired
    # by P2-S3 centralized selection; today the bypass is pinned by the P1-S5 test).
    # Deterministic: pin an explicit nonexistent model dir instead of falling back
    # to a provisioned UMD_ASR_MODEL_CACHE (which would honestly report ACTIVE).
    cap_fw = audio_capability_report(
        AudioConfig(asr_engine="faster-whisper", asr_model_dir="/nonexistent/umd-model-cache")
    )
    assert cap_fw["asr_engine"]["faster_whisper"]["gated"] is True
    assert cap_fw["asr_engine"]["faster_whisper"]["active"] is False
    assert _audio_status(cap_fw)["faster_whisper"] == CONFIGURED_UNAVAILABLE


# ---------------------------------------------------------------------------
# Gate-skipped: active when the validated runtime is present
# ---------------------------------------------------------------------------


def _faster_whisper_ready() -> bool:
    import importlib
    import os
    from pathlib import Path

    try:
        importlib.import_module("faster_whisper")
    except ImportError:
        return False
    cache = os.environ.get("UMD_ASR_MODEL_CACHE")
    return bool(cache) and Path(cache).is_dir()


@pytest.mark.skipif(
    not _faster_whisper_ready(),
    reason="configured-but-unavailable: faster-whisper runtime/model cache absent",
)
def test_faster_whisper_active_when_validated_runtime_present() -> None:
    cap = audio_capability_report(AudioConfig(asr_engine="faster-whisper"))
    assert _audio_status(cap)["faster_whisper"] == ACTIVE
    assert cap["asr_engine"]["faster_whisper"]["active"] is True


@pytest.mark.skipif(
    not _tesseract_available(),
    reason="configured-but-unavailable: tesseract binary absent",
)
def test_tesseract_active_when_binary_present() -> None:
    result = run_ocr(raster_text_only_bytes(), "tesseract")
    assert result.provider == "umd-tesseract"
    assert result.regions  # real OCR regions when the binary is installed


# ---------------------------------------------------------------------------
# API /v1/capabilities exposes the SAME statuses (cross-check, postgres)
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_ctx(umd_db, source_store):
    from umd.api.app import create_app
    from umd.config import AuthSettings, ConsistencySettings, RateLimitSettings, Settings

    settings = Settings(
        auth=AuthSettings(api_keys=["write-key", "read-key"], write_keys=["write-key"]),
        rate_limit=RateLimitSettings(
            enabled=True, requests_per_window=10000, window_seconds=60.0, burst=100
        ),
        consistency=ConsistencySettings(lag_wait_multiplier=1, max_waiters=16),
        lag_budget_seconds=0.05,
    )
    app = create_app(engine=umd_db, source_store=source_store, settings=settings)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client)


def test_api_capabilities_expose_same_audio_statuses(api_ctx) -> None:
    cap = capability_report()
    assert set(_audio_status(cap["audio"])) == {
        "asr_engine",
        "faster_whisper",
        "diarization",
    }
    assert _audio_status(cap["audio"])["asr_engine"] == ACTIVE
    assert _audio_status(cap["audio"])["faster_whisper"] == GATED
    assert _audio_status(cap["audio"])["diarization"] == GATED

    r = api_ctx.client.get("/v1/capabilities", headers={"Authorization": "Bearer read-key"})
    assert r.status_code == 200, r.text
    api_report = r.json()["capabilities"]
    # The API and the report function expose the SAME status vocabulary.
    assert _audio_status(api_report["audio"]) == _audio_status(cap["audio"])
    assert api_report["audio"]["asr_engine"]["active"] == "umd-reference-asr"
    assert api_report["audio"]["asr_engine"]["faster_whisper"]["active"] is False
    # Aggregate report is JSON-serializable and flat-audio is consistent.
    flatten_audio_capabilities(api_report["audio"])
