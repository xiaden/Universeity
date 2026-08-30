"""Plan H P3-S1/S2: the production registry's raster + video branches compose REAL
modality work (bounded OCR/spatial/IIIF crops; sandboxed demux/scenes/shots +
independent embedded-subtitle sources) when the runtime carries real deps, and
honestly degrade to the deterministic baseline when deps are absent.

These tests are ADDITIVE to the Phase-1/Plan-G spec tests: they wire the full
runtime (engine + source_store + artifacts + sandbox) and assert that committed
evidence actually flows through the canonical stage registry — not placeholder
refs. Requires live PostgreSQL and the FFmpeg/faster-whisper sandbox path.
"""

from __future__ import annotations

import importlib
import io
import os
from pathlib import Path

import pytest
import sqlalchemy as sa

from fixtures import (
    dialogue_video_bytes,
    raster_comic_bytes,
    speech_video_bytes,
)
from umd.storage.ocfl import SourceDescriptor, SourceStore
from umd.storage.postgres.artifacts import PostgresArtifactStore
from umd.storage.postgres.repositories import SourceMembershipService

pytestmark = pytest.mark.postgres


def _production_module():
    return importlib.import_module("umd.jobs.production")


def _put_source(store, raw: bytes, name: str):
    man = store.put_immutable(io.BytesIO(raw), SourceDescriptor(logical_name=name))
    return man


def _seed_source(
    engine,
    store,
    raw: bytes,
    *,
    source_id: str,
    media_kind: str,
    name: str,
) -> None:
    man = _put_source(store, raw, name)
    SourceMembershipService(engine).ensure_source(
        source_id=source_id,
        ocfl_ref=man.object_id,
        sha512=man.sha512,
        size_bytes=man.size_bytes,
        media_kind=media_kind,
        original_name=name,
        work_id=None,
    )


def _evidence_kinds(engine, source_id: str) -> set[str]:
    from umd.storage.postgres.tables import metadata as _meta

    ev_t = _meta.tables["evidence"]
    with engine.connect() as conn:
        rows = conn.execute(sa.select(ev_t.c.evidence_kind).where(ev_t.c.source_id == source_id))
        return {r[0] for r in rows}


def _sources_count(engine, media_kind: str) -> int:
    from umd.storage.postgres.tables import metadata as _meta

    src_t = _meta.tables["source"]
    with engine.connect() as conn:
        return conn.execute(
            sa.select(sa.func.count()).where(src_t.c.media_kind == media_kind)
        ).scalar_one()


def _runtime(umd_db, tmp_path, *, sandbox):
    """Wire the full production runtime with real deps (large-range OCFL store)."""
    store = SourceStore.create(
        tmp_path / "ocfl", max_upload_bytes=16 * 1024 * 1024, max_range_bytes=16 * 1024 * 1024
    )
    artifacts = PostgresArtifactStore(umd_db)
    return {"engine": umd_db, "source_store": store, "artifacts": artifacts, "sandbox": sandbox}


# --- raster branch (P3-S1) -------------------------------------------------


@pytest.mark.skipif(
    __import__("os").environ.get("UMD_TEST_POSTGRES") != "true",
    reason="production registry composition requires live PostgreSQL",
)
def test_production_registry_raster_branch_commits_real_ocr(umd_db, tmp_path) -> None:
    from umd.jobs.stage_execution import StageOutcome
    from umd.security.sandbox import SubprocessSandboxRunner

    sid = "b3f98f72-0000-0000-0000-000000000000"
    mod = _production_module()
    runtime = _runtime(umd_db, tmp_path, sandbox=SubprocessSandboxRunner())
    registry = mod.StageWorkRegistryFactory.build(runtime)
    stage = registry["LOW_LEVEL_EXTRACTION"]
    assert callable(stage)

    _seed_source(
        umd_db,
        runtime["source_store"],
        raster_comic_bytes(),
        source_id=sid,
        media_kind="image",
        name="page.png",
    )
    manifest = mod.StageManifest(
        job_id="media-raster",
        stage_name="LOW_LEVEL_EXTRACTION",
        source_id=sid,
        dag_universe=None,
        evidence_refs=[],
        input_manifest={"source_id": sid},
    )
    outcome = stage(manifest)
    assert isinstance(outcome, StageOutcome)
    assert outcome.evidence_refs, "raster branch must produce real evidence refs"
    # REAL OCR/spatial evidence committed — not the deterministic baseline.
    kinds = _evidence_kinds(umd_db, sid)
    assert "ocr_region" in kinds or "text_span" in kinds, f"expected OCR evidence, got {kinds}"
    assert "panel" in kinds, f"expected spatial panel evidence, got {kinds}"


# --- video branch (P3-S2) --------------------------------------------------


@pytest.mark.skipif(
    __import__("os").environ.get("UMD_TEST_POSTGRES") != "true",
    reason="production registry composition requires live PostgreSQL",
)
def test_production_registry_video_branch_commits_scenes_and_subtitles(umd_db, tmp_path) -> None:
    from umd.jobs.stage_execution import StageOutcome
    from umd.security.sandbox import SubprocessSandboxRunner

    sid = "b3f98f72-0000-0000-0000-000000000001"
    mod = _production_module()
    runtime = _runtime(umd_db, tmp_path, sandbox=SubprocessSandboxRunner())
    registry = mod.StageWorkRegistryFactory.build(runtime)
    stage = registry["LOW_LEVEL_EXTRACTION"]

    video = dialogue_video_bytes()
    _seed_source(
        umd_db,
        runtime["source_store"],
        video,
        source_id=sid,
        media_kind="video",
        name="dialogue.mkv",
    )
    manifest = mod.StageManifest(
        job_id="media-video",
        stage_name="LOW_LEVEL_EXTRACTION",
        source_id=sid,
        dag_universe=None,
        evidence_refs=[],
        input_manifest={"source_id": sid},
    )
    outcome = stage(manifest)
    assert isinstance(outcome, StageOutcome)
    assert outcome.evidence_refs, "video branch must produce real evidence refs"
    kinds = _evidence_kinds(umd_db, sid)
    assert "scene_boundary" in kinds or "video_interval" in kinds, (
        f"expected video scene/interval evidence, got {kinds}"
    )
    assert "frame" in kinds, f"expected frame anchors, got {kinds}"
    # The embedded SRT track is extracted as an INDEPENDENT source (never flattened).
    assert _sources_count(umd_db, "subtitle") >= 1, "embedded subtitle must become a source"
    # Composition (audio branch) is recorded as metadata on the video source.
    assert "metadata" in kinds, f"expected stream/composition metadata, got {kinds}"


@pytest.mark.skipif(
    __import__("os").environ.get("UMD_TEST_POSTGRES") != "true",
    reason="production registry composition requires live PostgreSQL",
)
def test_video_embedded_subtitle_track_reuses_committed_bytes(umd_db, tmp_path) -> None:
    """A byte-identical embedded subtitle track (already committed as a standalone
    subtitle source) is content-addressed reused, not re-inserted: LOW_LEVEL_EXTRACTION
    must not violate the ``source_ocfl_ref_key`` unique constraint on re-ingest/retry.
    """
    from umd.jobs.stage_execution import StageOutcome
    from umd.security.sandbox import SubprocessSandboxRunner
    from umd.video.runner import extract_embedded_subtitles

    mod = _production_module()
    runtime = _runtime(umd_db, tmp_path, sandbox=SubprocessSandboxRunner())
    registry = mod.StageWorkRegistryFactory.build(runtime)
    stage = registry["LOW_LEVEL_EXTRACTION"]

    video = dialogue_video_bytes()
    extracted = extract_embedded_subtitles(SubprocessSandboxRunner(), video, name="dialogue.mkv")
    assert extracted and extracted[0]["extractable"]
    track_payload = bytes(extracted[0]["payload"])

    # Standalone subtitle source committed FIRST, byte-identical to the embedded track.
    _seed_source(
        umd_db,
        runtime["source_store"],
        track_payload,
        source_id="aaaaaaaa-0000-0000-0000-000000000001",
        media_kind="subtitle",
        name="dialog.srt",
    )
    assert _sources_count(umd_db, "subtitle") == 1

    # Video source whose embedded track is byte-identical to the standalone subtitle.
    _seed_source(
        umd_db,
        runtime["source_store"],
        video,
        source_id="bbbbbbbb-0000-0000-0000-000000000002",
        media_kind="video",
        name="dialogue.mkv",
    )
    manifest = mod.StageManifest(
        job_id="media-video-subtitle-reuse",
        stage_name="LOW_LEVEL_EXTRACTION",
        source_id="bbbbbbbb-0000-0000-0000-000000000002",
        dag_universe=None,
        evidence_refs=[],
        input_manifest={"source_id": "bbbbbbbb-0000-0000-0000-000000000002"},
    )
    outcome = stage(manifest)
    assert isinstance(outcome, StageOutcome)
    assert outcome.evidence_refs, "video branch must produce real evidence refs"
    # Content-addressed reuse: the embedded track maps to the EXISTING standalone
    # subtitle source — no duplicate source row (which previously violated
    # source_ocfl_ref_key and failed/quarantined the stage).
    assert _sources_count(umd_db, "subtitle") == 1


# --- P3-S5: composed audio-ASR evidence through the video branch -----------------


def _audio_interval_evidence(engine, sid):
    from umd.storage.postgres.repositories import PostgresEvidenceRepository

    ev = PostgresEvidenceRepository(engine)
    return [e for e in ev.get_by_source(sid) if e.evidence_kind == "audio_interval"]


def _faster_whisper_ready() -> bool:
    """Honest readiness probe: runtime installed AND a validated model dir exists.

    Resolves the dir containing ``model.bin`` under ``UMD_ASR_MODEL_CACHE`` (the
    cache may point at the model directly or at a parent containing the pinned
    ``faster-whisper-tiny.en`` directory).
    """
    try:
        importlib.import_module("faster_whisper")
    except ImportError:
        return False
    return _model_dir() is not None


def _model_dir() -> str | None:
    cache = os.environ.get("UMD_ASR_MODEL_CACHE")
    if not cache:
        return None
    for candidate in (Path(cache), Path(cache) / "faster-whisper-tiny.en"):
        if (candidate / "model.bin").is_file():
            return str(candidate)
    return None


def _video_manifest(mod, job_id: str, sid: str):
    return mod.StageManifest(
        job_id=job_id,
        stage_name="LOW_LEVEL_EXTRACTION",
        source_id=sid,
        dag_universe=None,
        evidence_refs=[],
        input_manifest={"source_id": sid},
    )


@pytest.mark.skipif(
    __import__("os").environ.get("UMD_TEST_POSTGRES") != "true",
    reason="production registry composition requires live PostgreSQL",
)
def test_production_registry_video_branch_honest_asr_gate_when_unavailable(
    umd_db, tmp_path, monkeypatch
) -> None:
    """When the configured ASR engine/model cache is unavailable, the video branch
    emits an honest 'asr gated:' warning and records NO fabricated transcript, while
    still completing visual/temporal/subtitle evidence intact (P3-S5)."""
    from umd.jobs.stage_execution import StageOutcome
    from umd.security.sandbox import SubprocessSandboxRunner

    # Force the configured-but-unavailable path: request faster-whisper with a model
    # cache dir that does not exist -> the audio worker raises AsrProviderUnavailable
    # (never fabricates) and the branch must surface the named gate.
    monkeypatch.setenv("UMD_ASR_ENGINE", "faster-whisper")
    monkeypatch.setenv("UMD_ASR_MODEL_CACHE", "/nonexistent/model-cache")

    sid = "b3f98f72-0000-0000-0000-0000000000aa"
    mod = _production_module()
    runtime = _runtime(umd_db, tmp_path, sandbox=SubprocessSandboxRunner())
    stage = mod.StageWorkRegistryFactory.build(runtime)["LOW_LEVEL_EXTRACTION"]
    assert callable(stage)

    _seed_source(
        umd_db,
        runtime["source_store"],
        dialogue_video_bytes(),
        source_id=sid,
        media_kind="video",
        name="dialogue.mkv",
    )
    outcome = stage(_video_manifest(mod, "media-video-gate", sid))
    assert isinstance(outcome, StageOutcome)
    # Honest named gate surfaced on the stage.
    assert any("asr gated:" in w for w in outcome.warnings), outcome.warnings
    # No fabricated transcript recorded for the video source when ASR is gated.
    assert not _audio_interval_evidence(umd_db, sid), (
        "must not record audio_interval transcript evidence when ASR is gated"
    )
    # The branch still completes with visual/temporal/subtitle evidence intact.
    assert outcome.evidence_refs, "video branch must still complete when ASR is gated"
    kinds = _evidence_kinds(umd_db, sid)
    assert {"scene_boundary", "video_interval", "frame"}.issubset(kinds), kinds
    assert _sources_count(umd_db, "subtitle") >= 1, "embedded subtitle must still become a source"


@pytest.mark.skipif(
    __import__("os").environ.get("UMD_TEST_POSTGRES") != "true",
    reason="production registry composition requires live PostgreSQL",
)
@pytest.mark.skipif(
    not _faster_whisper_ready(),
    reason=(
        "configured-but-unavailable: faster-whisper runtime and/or model cache "
        "(UMD_ASR_MODEL_CACHE) absent"
    ),
)
def test_production_registry_video_branch_composes_asr_utterances_when_enabled(
    umd_db, tmp_path, monkeypatch
) -> None:
    """When the local model gate is enabled, composed ASR utterances (word/utterance
    timestamps, confidence, language, provider/model/config provenance, generated_by,
    promotion ban) appear through video-branch evidence on the EXTRACTED audio track
    (P3-S5) -- not a separate fixture WAV."""
    from umd.jobs.stage_execution import StageOutcome
    from umd.security.sandbox import SubprocessSandboxRunner

    # Force the validated faster-whisper engine + model dir for the worker subprocess
    # (the gate guarantees a validated model dir is resolvable from UMD_ASR_MODEL_CACHE).
    model_dir = _model_dir()
    assert model_dir, "gate requires a validated model dir"
    monkeypatch.setenv("UMD_ASR_ENGINE", "faster-whisper")
    monkeypatch.setenv("UMD_ASR_MODEL_DIR", model_dir)

    sid = "b3f98f72-0000-0000-0000-0000000000bb"
    mod = _production_module()
    runtime = _runtime(umd_db, tmp_path, sandbox=SubprocessSandboxRunner())
    stage = mod.StageWorkRegistryFactory.build(runtime)["LOW_LEVEL_EXTRACTION"]
    assert callable(stage)

    _seed_source(
        umd_db,
        runtime["source_store"],
        speech_video_bytes(),
        source_id=sid,
        media_kind="video",
        name="speech.mkv",
    )
    outcome = stage(_video_manifest(mod, "media-video-asr", sid))
    assert isinstance(outcome, StageOutcome)
    assert outcome.evidence_refs, "video branch must produce evidence refs"

    rows = _audio_interval_evidence(umd_db, sid)
    assert rows, "composed ASR utterances must appear as audio_interval video evidence"
    for ev in rows:
        q = ev.quality or {}
        assert q.get("confidence_scope") == "transcription"
        assert q.get("start_s") is not None and q.get("end_s") is not None
        assert q.get("words"), "word-level timestamps required"
        for w in q["words"]:
            assert w["start_s"] <= w["end_s"]
        assert ev.confidence is not None, "transcription-scoped confidence required"
        assert ev.language, "language provenance required"
        gb = q.get("generated_by") or {}
        assert gb.get("provider") == "faster-whisper", gb
        assert gb.get("model_id"), gb
        assert gb.get("model_version"), gb
        assert q.get("promotion_ban", {}).get("can_auto_promote") is False
        assert ev.config_digest, "config provenance (digest) required"
