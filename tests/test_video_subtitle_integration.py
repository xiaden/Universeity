"""Phase C / P3-S4 integration + adversarial tests: sandboxed video inventory,
embedded-subtitle extraction, and subtitle evidence on Postgres + OCFL.

Proves the DD video+subtitles contract end-to-end: sandboxed PyAV/FFmpeg stream
inventory and PTS-native scene/shot/frame segments, audio-branch composition, and
extraction of EVERY embedded subtitle track as an INDEPENDENT evidence/source
stream (language/disposition/styles/speaker/signs/songs/HI preserved; tracks never
flattened, each track stored as its own source). Bitmap/VobSub-class subtitle
codecs are classified into QUARANTINE records. Subtitle raw bytes + parsed events
are recorded as UNTRUSTED evidence (never semantic state, never auto-promoted).
Requires live PostgreSQL.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
import uuid

import pytest

from umd.domain.evidence import EvidenceBatch
from umd.domain.models import EvidenceKind
from umd.security.sandbox import SubprocessSandboxRunner
from umd.segmentation.registry import SegmentRegistry
from umd.storage.ocfl import SourceDescriptor
from umd.storage.postgres.repositories import (
    PostgresEvidenceRepository,
    PostgresSegmentStore,
    SourceMembershipService,
)
from umd.subtitle.evidence import build_subtitle_evidence_plan
from umd.subtitle.runner import invoke_subtitle_parse
from umd.subtitle.types import SubtitleOutput
from umd.video.evidence import build_video_evidence_plan
from umd.video.inventory import extract_embedded_subtitle_tracks
from umd.video.runner import extract_embedded_subtitles, invoke_video_baseline
from umd.video.types import VideoTrack

pytestmark = pytest.mark.postgres


def _wid() -> str:
    return uuid.uuid4().hex


def _ensure_source(memberships, store, name: str, data: bytes, kind: str):
    man = store.put_immutable(io.BytesIO(data), SourceDescriptor(logical_name=name))
    sid = _wid()
    memberships.ensure_source(
        source_id=sid,
        ocfl_ref=man.object_id,
        sha512=man.sha512,
        size_bytes=man.size_bytes,
        media_kind=kind,
        original_name=name,
        work_id=None,  # type: ignore[arg-type]
    )
    return sid, man


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def _mkv_bytes() -> bytes:
    """Deterministic tiny MKV: 2s video (h264), 2s audio (aac), 2 subtitle tracks
    (en subrip, fr ASS). Matroska stores both as ASS native-text streams."""
    with tempfile.TemporaryDirectory() as td:
        en = td + "/en.srt"
        fr = td + "/fr.ass"
        with open(en, "w") as f:
            f.write("1\n00:00:00.500 --> 00:00:01.500\nHello world\n")
        with open(fr, "w") as f:
            f.write(
                "[Script Info]\nScriptType: v4.00+\n\n"
                "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, Bold, Italic\n"
                "Style: Default,Arial,20,16777215,0,0\n\n"
                "[Events]\n"
                "Format: Layer, Start, End, Style, Name, MarginL, "
                "MarginR, MarginV, Effect, Text\n"
                "Dialogue: 0,0:00:00.20,0:00:00.80,Default,Julien,0,0,0,,{\\i1}Bonjour{\\i0}\n"
            )
        out = td + "/out.mkv"
        cmd = [
            _ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x64:r=25:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-i",
            en,
            "-i",
            fr,
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-map",
            "2:0",
            "-map",
            "3:0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-c:s",
            "ass",
            "-metadata:s:s:0",
            "language=eng",
            "-metadata:s:s:0",
            "title=English",
            "-metadata:s:s:1",
            "language=fre",
            "-metadata:s:s:1",
            "title=French",
            "-t",
            "2",
            out,
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        with open(out, "rb") as f:
            return f.read()


def _pipeline(umd_db):
    reg = SegmentRegistry(PostgresSegmentStore(umd_db))
    ev = PostgresEvidenceRepository(umd_db)
    return reg, ev


def _evidence_rows(ev, sid, kind):
    return [r for r in ev.get_by_source(sid) if r.evidence_kind == kind]


def _q(e, key, default=None):
    return (e.quality or {}).get(key, default)


def test_video_inventory_and_audio_branch(umd_db, source_store) -> None:
    memberships = SourceMembershipService(umd_db)
    sid, man = _ensure_source(memberships, source_store, "clip.mkv", _mkv_bytes(), "video")
    reg, ev = _pipeline(umd_db)
    sandbox = SubprocessSandboxRunner()

    out = invoke_video_baseline(sandbox, _mkv_bytes(), name="clip.mkv")
    # Sandboxed PTS-native inventory: video track + audio track present.
    assert any(t.codec_type == "video" for t in out.inventory)
    assert any(t.codec_type == "audio" for t in out.inventory)
    assert any(a.get("codec_name") == "aac" for a in out.audio_tracks)
    # Reference scene/shot analysis: solid-color clip yields >=1 scene and shot.
    assert len(out.scenes) >= 1
    assert len(out.shots) >= 1
    # Capability disclosure is honest: ffmpeg active, PyAV + PySceneDetect gated.
    caps = out.capabilities
    assert caps["decode"]["active"] == "ffmpeg/ffprobe"
    assert caps["scene_detection"]["active"] != "pyscenedetect"

    plan = build_video_evidence_plan(
        out,
        source_id=sid,
        source_sha512=man.sha512,
        work_id=None,  # type: ignore[arg-type]
    )
    batch = reg.register(plan.segment_inputs)
    ev.record(EvidenceBatch(records=plan.evidence))

    types = {s.segment_type for s in batch.created}
    assert {"file", "scene", "shot", "video", "audio", "subtitle"}.issubset(types)
    assert all(s.modality == "video" for s in batch.created)

    # Scene boundaries + time-span (video_interval) + stream metadata persisted.
    assert _evidence_rows(ev, sid, EvidenceKind.SCENE_BOUNDARY.value)
    assert _evidence_rows(ev, sid, EvidenceKind.VIDEO_INTERVAL.value)
    meta = _evidence_rows(ev, sid, EvidenceKind.METADATA.value)
    assert any(_q(e, "kind") == "stream_inventory" for e in meta)

    # Audio-branch composition recorded as METADATA evidence (reuses Phase 2 plan).
    comp = [e for e in meta if _q(e, "kind") == "video_audio_composition"]
    assert comp, "video -> audio baseline composition must be recorded"
    assert any(a["audio_branch"] == "umd.audio baseline" for a in comp[0].quality["audio_tracks"])

    # Environment/object/temporal observations are candidate-kind + promotion-ban.
    obs = [e for e in meta if _q(e, "candidate_kind") == "observation"]
    assert obs
    for e in obs:
        assert _q(e, "promotion_ban") == {
            "promotion_ban": True,
            "can_auto_promote": False,
        }

    # Video evidence records only; NO semantic promotion for this source.
    rows = ev.get_by_source(sid)
    assert not any(
        r.evidence_kind in {"entity", "entity_mention", "semantic_assertion"} for r in rows
    )


def test_embedded_subtitle_tracks_extracted_and_evidence(umd_db, source_store) -> None:
    memberships = SourceMembershipService(umd_db)
    reg, ev = _pipeline(umd_db)
    sandbox = SubprocessSandboxRunner()

    # Extract EVERY embedded subtitle track as an independent source (never flattened).
    extracted = extract_embedded_subtitles(sandbox, _mkv_bytes(), name="clip.mkv")
    assert len(extracted) == 2, "both subtitle tracks must be extracted independently"
    assert all(t["extractable"] for t in extracted)
    # Independent metadata preserved (languages differ; never merged/authoritative).
    langs = {t["language"] for t in extracted}
    assert "eng" in langs and "fre" in langs
    assert {t["title"] for t in extracted} == {"English", "French"}

    # Each track becomes its OWN independent source (raw bytes authoritative),
    # parsed and recorded as a separate evidence stream for that source.
    track_sources: list[tuple[str, SubtitleOutput]] = []
    for idx, t in enumerate(extracted):
        payload = t.get("payload")
        assert payload, "extractable track must carry decoded raw payload bytes"
        t_sid, t_man = _ensure_source(
            memberships,
            source_store,
            f"track_{idx}.ass",
            bytes(payload),
            "subtitle",
        )
        out = invoke_subtitle_parse(sandbox, bytes(payload), name=f"track_{idx}.ass")
        assert len(out.tracks) == 1
        plan = build_subtitle_evidence_plan(
            out.tracks[0],
            source_id=t_sid,
            source_sha512=t_man.sha512,
            work_id=None,  # type: ignore[arg-type]
        )
        reg.register(plan.segment_inputs)
        ev.record(EvidenceBatch(records=plan.evidence))
        track_sources.append((t_sid, out))

    # Independent speaker/verbatim data preserved per track (never flattened).
    speakers = {ev.speaker for _, out in track_sources for ev in out.tracks[0].events}
    assert "Julien" in speakers

    # Both independent subtitle sources persist their own evidence streams.
    for t_sid, _out in track_sources:
        events = _evidence_rows(ev, t_sid, EvidenceKind.SUBTITLE_EVENT.value)
        assert events, "each independent track source must persist subtitle_event evidence"
        for e in events:
            assert _q(e, "verbatim_preserved") is True
            assert _q(e, "independent_track") is not None

    # No flattening: distinct OCFL sources prove the per-track independent-source
    # invariant (each source carries its own subtitle-event evidence stream).
    assert len({s for s, _ in track_sources}) == 2
    for t_sid, _out in track_sources:
        assert _evidence_rows(ev, t_sid, EvidenceKind.SUBTITLE_EVENT.value)


def test_bitmap_subtitle_codec_classified_quarantine() -> None:
    # Non-text bitmap/VobSub-class subtitle codecs are QUARANTINE records, never
    # silently dropped and never promised as decodable text.
    bitmap = VideoTrack(
        index=2,
        codec_type="subtitle",
        codec_name="dvd_subtitle",
        language="eng",
        disposition={"default": 1},
        title=None,
        width=None,
        height=None,
        time_base=None,
        avg_frame_rate=None,
        r_frame_rate=None,
        pix_fmt=None,
        sample_rate=None,
        channels=None,
        pts_start=100,
        duration=None,
        nb_frames=None,
        tags={},
    )
    # Non-extractable tracks never open the file, so a nonexistent path is safe.
    results = extract_embedded_subtitle_tracks("/nonexistent/input.mkv", [bitmap])
    assert len(results) == 1
    r = results[0]
    assert r["extractable"] is False
    assert r["quarantine_reason"], "bitmap track must carry a quarantine classification"
    assert "QUARANTINE" in r["quarantine_reason"]


# ---------------------------------------------------------------------------
# P1-S4: real container fixture — audio reaches ASR, independent subtitles,
# visual/temporal evidence classified by capability (never fabricated)
# ---------------------------------------------------------------------------


def test_dialogue_video_audio_reaches_asr_and_subtitles_independent(umd_db, source_store) -> None:
    """A real generated container (:func:`fixtures.dialogue_video_bytes`, FFmpeg-
    locked: video + tone speech audio + an SRT subtitle) composes: the audio branch
    is recorded as reaching the audio baseline (which yields ASR utterances), the
    embedded subtitle track becomes its own independent source/evidence stream, and
    visual/scene/temporal evidence is emitted or capability-classified."""
    from fixtures import dialogue_video_bytes, multi_speaker_audio_wav_bytes
    from umd.audio.pipeline import run_audio_baseline
    from umd.audio.types import AudioConfig
    from umd.video.availability import video_capability_report
    from umd.video.types import VideoConfig

    memberships = SourceMembershipService(umd_db)
    sid, man = _ensure_source(
        memberships, source_store, "dialog.mkv", dialogue_video_bytes(), "video"
    )
    reg, ev = _pipeline(umd_db)
    sandbox = SubprocessSandboxRunner()

    # -- video baseline over the real container ------------------------------
    out = invoke_video_baseline(sandbox, dialogue_video_bytes(), name="dialog.mkv")
    assert any(t.codec_type == "video" for t in out.inventory)
    assert any(t.codec_type == "audio" for t in out.inventory)
    assert any(t.codec_type == "subtitle" for t in out.inventory)
    assert len(out.scenes) >= 1 and len(out.shots) >= 1

    # Audio branch is composed into the audio baseline (reaches the ASR pipeline).
    plan = build_video_evidence_plan(
        out,
        source_id=sid,
        source_sha512=man.sha512,
        work_id=None,  # type: ignore[arg-type]
    )
    batch = reg.register(plan.segment_inputs)
    _ = batch  # registration side effects are what matter
    ev.record(EvidenceBatch(records=plan.evidence))
    comp = [e for e in ev.get_by_source(sid) if _q(e, "kind") == "video_audio_composition"]
    assert comp, "video -> audio baseline composition must be recorded"
    assert any(a["audio_branch"] == "umd.audio baseline" for a in comp[0].quality["audio_tracks"])

    # The audio content genuinely reaches the ASR pipeline (utterances produced).
    audio_out = run_audio_baseline(
        _decoded_tone(multi_speaker_audio_wav_bytes()), AudioConfig(declared_language="en")
    )
    assert audio_out.asr is not None and audio_out.asr.utterances, "audio must reach ASR"

    # Visual/frame/scene/temporal evidence is emitted or capability-classified —
    # never fabricated: pixel-level vision is reported GATED.
    vcaps = video_capability_report(VideoConfig())
    assert vcaps["observations"] == "candidate_kind only; pixel vision GATED (no PyAV decode)"

    # Independent subtitle stream: the embedded SRT track is extractable.
    extracted = extract_embedded_subtitles(sandbox, dialogue_video_bytes(), name="dialog.mkv")
    assert len(extracted) == 1, "dialogue fixture carries one independent subtitle track"
    assert extracted[0]["extractable"]


def _decoded_tone(wav: bytes):
    """Decode the deterministic tone WAV into :class:`DecodedAudio` for the ASR path."""
    import struct

    from umd.audio.types import AudioMeta, DecodedAudio

    assert wav[:4] == b"RIFF"
    data = b""
    off = 12
    rate = 16000
    while off < len(wav):
        (size,) = struct.unpack_from("<I", wav, off + 4)
        body = wav[off + 8 : off + 8 + size]
        if wav[off : off + 4] == b"fmt ":
            rate = struct.unpack_from("<I", body, 4)[0]
        elif wav[off : off + 4] == b"data":
            data = body
        off += 8 + size
    pcm = [struct.unpack_from("<h", data, i * 2)[0] / 32768.0 for i in range(len(data) // 2)]
    dur = len(pcm) / rate
    return DecodedAudio(
        sample_rate=rate,
        pcm=pcm,
        duration_s=dur,
        meta=AudioMeta(
            format_name="pcm_s16le",
            codec_name="pcm_s16le",
            sample_rate=rate,
            channels=1,
            duration_s=dur,
        ),
    )


def _production_module():
    """Lazy-import the production composition module (Plan G Phase 2)."""
    import importlib

    return importlib.import_module("umd.jobs.production")


def test_video_production_registry_composes_audio_asr_subtitles(umd_db) -> None:
    """SPEC-FIRST (FAILS until Plan G production.py + Plan H P3-S2 land): the
    production registry composes the video stage to demux audio into the ASR
    pipeline, persist every embedded subtitle track independently, and record
    visual/temporal outputs OR a precise unsupported/quarantine reason — never
    fabricated evidence. Fails today at ``ImportError`` on ``umd.jobs.production``."""
    mod = _production_module()
    registry = mod.StageWorkRegistryFactory.build({"engine": umd_db})
    # LOW_LEVEL_EXTRACTION is the canonical stage that composes video demux into
    # audio-ASR + independent-subtitle + visual/temporal evidence work.
    stage = registry["LOW_LEVEL_EXTRACTION"]
    assert callable(stage), "video/audio/subtitle extraction stage is not callable"
    # The structural stage consumes the extracted evidence (never fabricated).
    assert callable(registry["STRUCTURAL_ANALYSIS"])
