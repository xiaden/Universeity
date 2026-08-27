"""P1-S5 spec-first tests: persisted mentions, provenance/confidence, unknown-candidate,
multilingual aliases, and candidate sets."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import func

from resolution_helpers import insert_source, mention
from umd.resolution.mentions import MentionService, PostgresMentionRepository
from umd.storage.postgres.ledger import SemanticLedger
from umd.storage.postgres.tables import metadata as db_meta

pytestmark = pytest.mark.postgres

_mention_t = db_meta.tables["entity_mention"]
_event_t = db_meta.tables["semantic_event"]


def _mention_id_seq(engine: sa.Engine) -> list[str]:
    with engine.connect() as conn:
        return [str(x) for x in conn.execute(sa.select(_mention_t.c.id)).scalars().all()]


def test_mention_record_persists_provenance_confidence_and_candidates(umd_db):
    source_id = insert_source(umd_db)

    svc = MentionService(
        ledger=SemanticLedger(umd_db), repository=PostgresMentionRepository(umd_db)
    )
    m = mention(
        source_id=source_id,
        entity_id=None,  # unknown-candidate: not resolved to an entity yet
        text="Alexander",
        candidates=[("ent-b", 0.9), ("ent-c", 0.1)],
    )
    m.language = "en"
    m.confidence_state = "PROBABLE"
    m.confidence = 0.7
    m.provenance = {"tool": "ocr-stack", "stage": "extract"}
    m.metadata_ = {"extra": "kept"}

    commit, mid = svc.record(m)
    assert commit.seq > 0
    assert mid == str(m.id)

    with umd_db.connect() as conn:
        row = conn.execute(sa.select(_mention_t).where(_mention_t.c.id == mid)).first()
    assert row is not None
    meta = row.metadata_
    # provenance + confidence state + candidate set are all represented.
    assert meta["mention_kind"] == "name"
    assert meta["confidence_state"] == "PROBABLE"
    assert meta["confidence"] == 0.7
    assert meta["provenance"] == {"tool": "ocr-stack", "stage": "extract"}
    assert meta["candidates"] == [
        {"entity_ref": "ent-b", "confidence": 0.9, "role": "candidate"},
        {"entity_ref": "ent-c", "confidence": 0.1, "role": "candidate"},
    ]
    # entity_id stays NULL (unknown candidate) but candidates are retained.
    assert row.entity_id is None

    # An EntityMentioned event landed in the append-only ledger.
    with umd_db.connect() as conn:
        n_events = conn.execute(
            sa.select(func.count())
            .select_from(_event_t)
            .where(_event_t.c.event_type == "EntityMentioned")
        ).scalar()
    assert n_events == 1


def test_mention_roundtrip_restores_candidate_sets(umd_db):
    """A re-read mention restores its candidate set + provenance (no loss)."""
    source_id = insert_source(umd_db)
    repo = PostgresMentionRepository(umd_db)
    svc = MentionService(ledger=SemanticLedger(umd_db), repository=repo)

    m = mention(
        source_id=source_id,
        entity_id=None,
        text="Wilhelm",
        candidates=[("ent-x", 0.55), ("ent-y", 0.45)],
    )
    m.face_cluster = "fc-7"
    svc.record(m)

    got = repo.get(str(m.id))
    assert got is not None
    assert {c.entity_ref for c in got.candidates} == {"ent-x", "ent-y"}
    assert got.confidence_state == "UNKNOWN"
    assert got.face_cluster == "fc-7"


def test_multilingual_alias_candidates_via_transliteration_index():
    """Multilingual aliases surface the transliterated form as a candidate."""
    from umd.resolution.candidates import (
        CandidatePolicy,
        MentionBlockIndex,
        SourceMention,
    )

    src = "src-lang"
    en = SourceMention(id=uuid.uuid4(), source_id=src, mention_text="Alexander", language="en")
    jp = SourceMention(
        id=uuid.uuid4(),
        source_id=src,
        mention_text="アレクサンダー",
        language="ja",
        normalized_forms=["alexander"],  # shared romanized alias
    )
    idx = MentionBlockIndex([en, jp], CandidatePolicy())
    hits = idx.link(en)
    refs = [c.entity_ref for c in hits.candidates]
    assert jp.mention_id in refs, "transliteration block did not surface the JA alias"


def test_unknown_candidate_remains_unresolved_but_retained(umd_db):
    """An unknown mention keeps its candidate set and no false entity binding."""
    source_id = insert_source(umd_db)
    repo = PostgresMentionRepository(umd_db)
    svc = MentionService(ledger=SemanticLedger(umd_db), repository=repo)

    m = mention(
        source_id=source_id,
        entity_id=None,
        text="???",
        candidates=[("ent-a", 0.4)],
    )
    svc.record(m)
    got = repo.get(str(m.id))
    assert got is not None and got.entity_id is None
    assert got.candidates[0].entity_ref == "ent-a"
