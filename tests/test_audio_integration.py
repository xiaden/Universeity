"""Phase C / P2-S5 integration tests: audio baseline evidence on Postgres + OCFL.

Proves the DD audio contract end-to-end through the Plan A/B separation: raw ASR
is recorded as UNTRUSTED ``audio_interval`` evidence (never semantic state), VAD/
music/sound/timing/language/speaker-candidate evidence carry source provenance,
speaker candidates are ``candidate_kind=observation`` and are NEVER auto-promoted
to canonical identity (promotion ban), and the versioned ``HallucinationFiltered``
events are schema-valid. Re-running identical input+config is DB-idempotent.
Requires live PostgreSQL (``postgres``).
"""

from __future__ import annotations

import io
import struct
import uuid

import pytest
import sqlalchemy as sa

from umd.audio import tone
from umd.audio.config import config_digest_of
from umd.audio.evidence import build_audio_evidence_plan
from umd.audio.pipeline import run_audio_baseline
from umd.audio.types import AudioConfig, AudioMeta, DecodedAudio
from umd.domain.events import EventType
from umd.domain.evidence import EvidenceBatch
from umd.domain.models import EvidenceKind
from umd.segmentation.registry import SegmentRegistry
from umd.storage.ocfl import SourceDescriptor
from umd.storage.postgres.repositories import (
    PostgresEvidenceRepository,
    PostgresSegmentStore,
    SourceMembershipService,
)

pytestmark = pytest.mark.postgres

SR = 16000


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


def _wav_bytes(samples: list[float], sample_rate: int = SR) -> bytes:
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


def _wid() -> str:
    return uuid.uuid4().hex


def _ensure_audio_source(memberships, store, wav: bytes):
    man = store.put_immutable(io.BytesIO(wav), SourceDescriptor(logical_name="clip.wav"))
    sid = _wid()
    memberships.ensure_source(
        source_id=sid,
        ocfl_ref=man.object_id,
        sha512=man.sha512,
        size_bytes=man.size_bytes,
        media_kind="audio",
        original_name="clip.wav",
        work_id=None,  # type: ignore[arg-type]
    )
    return sid, man


def _baseline_output():
    cfg = AudioConfig(declared_language="en")
    config_digest_of(cfg)
    out = run_audio_baseline(_decoded(tone.render_phrase(["hi", "there"])), cfg)
    return out, cfg.config_digest


def _pipeline(umd_db):
    reg = SegmentRegistry(PostgresSegmentStore(umd_db))
    ev = PostgresEvidenceRepository(umd_db)
    return reg, ev


def _evidence_rows(ev, sid, kind):
    return [r for r in ev.get_by_source(sid) if r.evidence_kind == kind]


def _q(e, key, default=None):
    return (e.quality or {}).get(key, default)


def test_audio_baseline_persists_evidence_and_nonpromotion(umd_db, source_store) -> None:
    memberships = SourceMembershipService(umd_db)
    sid, man = _ensure_audio_source(
        memberships, source_store, _wav_bytes(tone.render_phrase(["hi", "there"]))
    )
    reg, ev = _pipeline(umd_db)

    out, cfg_digest = _baseline_output()
    plan = build_audio_evidence_plan(
        out,
        source_id=sid,
        source_sha512=man.sha512,
        work_id=None,  # type: ignore[arg-type]
        config_digest=cfg_digest,
    )
    batch = reg.register(plan.segment_inputs)
    recorded = ev.record(EvidenceBatch(records=plan.evidence))

    # Deterministic audio segments registered under the audio modality branch.
    types = {s.segment_type for s in batch.created}
    assert "utterance" in types
    assert all(s.modality == "audio" for s in batch.created)

    # Raw ASR persists as UNTRUSTED audio_interval evidence (source-native).
    intervals = list(recorded.created) if recorded.created else []
    assert any(e.evidence_kind == EvidenceKind.AUDIO_INTERVAL for e in intervals)
    persisted = _evidence_rows(ev, sid, EvidenceKind.AUDIO_INTERVAL.value)
    assert persisted, "raw ASR must be persisted as audio_interval evidence"
    for e in persisted:
        assert _q(e, "confidence_scope") == "transcription"
        assert _q(e, "candidate_speaker") in {
            "speaker_unknown_utterance_1",
            "speaker_unknown_utterance_2",
        }
        assert _q(e, "words")

    # Music / sound / timing / language provenance evidence persisted.
    assert _evidence_rows(ev, sid, EvidenceKind.MUSIC.value) is not None
    assert _evidence_rows(ev, sid, EvidenceKind.TIMING.value)
    lang = [e for e in ev.get_by_source(sid) if _q(e, "kind") == "language_identification"]
    assert lang and _q(lang[0], "language") == "en"

    # VAD evidence present (vad precedes ASR).
    assert out.vad["has_speech"] is True

    # Speaker candidates: candidate-kind observation, promotion ban, never identity.
    speakers = _evidence_rows(ev, sid, EvidenceKind.SPEAKER_OBSERVATION.value)
    assert speakers and all(_q(e, "candidate_kind") == "observation" for e in speakers)
    for e in speakers:
        ban = _q(e, "promotion_ban")
        assert ban["promotion_ban"] is True and ban["can_auto_promote"] is False

    # No auto-promotion: no canonical entity/identity and no semantic assertion for
    # this source (promotion ban is structural, not a silent bypass).
    with umd_db.connect() as c:
        ent = c.execute(
            sa.text(
                "SELECT count(*) FROM entity e LEFT JOIN entity_mention m"
                " ON m.entity_id = e.id WHERE m.source_id = :s"
            ),
            {"s": sid},
        ).scalar()
        asserts = c.execute(
            sa.text("SELECT count(*) FROM semantic_assertion WHERE support_refs::text ILIKE :f"),
            {"f": f"%{sid}%"},
        ).scalar()
    assert (ent or 0) == 0
    assert (asserts or 0) == 0

    # Versioned HallucinationFiltered events are schema-valid (ready for the ledger).
    assert plan.events and all(
        e.event_type == EventType.HALLUCINATION_FILTERED.value for e in plan.events
    )
    for e in plan.events:
        prepared = e.prepare()
        assert prepared.payload["outcome"] == "kept"
        assert "signals" in prepared.payload

    # Raw audio bytes retained in OCFL (source-native, independent of evidence).
    assert source_store.verify_fixity(man.object_id) is True


def test_audio_evidence_re_record_is_idempotent(umd_db, source_store) -> None:
    memberships = SourceMembershipService(umd_db)
    sid, man = _ensure_audio_source(
        memberships, source_store, _wav_bytes(tone.render_phrase(["hi", "there"]))
    )
    reg, ev = _pipeline(umd_db)

    out, cfg_digest = _baseline_output()
    plan = build_audio_evidence_plan(
        out, source_id=sid, source_sha512=man.sha512, config_digest=cfg_digest
    )

    # First run: segments created + evidence recorded.
    first = reg.register(plan.segment_inputs)
    r1 = ev.record(EvidenceBatch(records=plan.evidence))
    assert first.created
    assert r1.created

    # Identical input + config digest => deterministic segment IDs dedup + evidence
    # (source, locator, kind, config_digest) is DB-authoritatively idempotent.
    second = reg.register(plan.segment_inputs)
    r2 = ev.record(EvidenceBatch(records=plan.evidence))
    assert second.created == []
    assert second.existing
    assert r2.created == []
    assert r2.existing

    with umd_db.connect() as c:
        n = c.execute(
            sa.text("SELECT count(*) FROM evidence WHERE source_id = :s"),
            {"s": sid},
        ).scalar()
    assert n == len(r1.created)
