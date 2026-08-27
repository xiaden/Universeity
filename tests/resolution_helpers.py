"""Shared helpers for Phase-1 resolution/alignment tests."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import sqlalchemy as sa

from umd.resolution.mentions import MentionCandidate, SourceMention
from umd.storage.postgres.tables import metadata as db_meta

_source_t = db_meta.tables["source"]
_entity_t = db_meta.tables["entity"]
_pred_t = db_meta.tables["predicate"]
_alignment_t = db_meta.tables["alignment"]
_assertion_t = db_meta.tables["semantic_assertion"]
_map_t = db_meta.tables["current_entity_map"]
_q_t = db_meta.tables["quarantine"]

_pg_insert = sa.dialects.postgresql.insert


def _sha() -> str:
    return uuid.uuid4().hex * 4


def insert_source(engine: sa.Engine, *, media_kind: str = "subtitle") -> str:
    sid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            _source_t.insert().values(
                id=sid,
                ocfl_ref="ocfl:" + _sha(),
                sha512=_sha(),
                size_bytes=10,
                media_kind=media_kind,
            )
        )
    return sid


def insert_entity(engine: sa.Engine, *, kind: str = "CHARACTER", label: str) -> str:
    eid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(_entity_t.insert().values(id=eid, entity_type=kind, label=label))
    return eid


def seed_predicates(engine: sa.Engine, codes: tuple[str, ...] = ("SPEAKS",)) -> None:
    with engine.begin() as conn:
        for code in codes:
            conn.execute(
                _pg_insert(_pred_t)
                .values(code=code, description=code)
                .on_conflict_do_nothing(index_elements=["code"])
            )


def insert_alignment(
    engine: sa.Engine,
    *,
    left_ref: str,
    right_ref: str,
    alignment_type: str = "ADAPTATION",
    method: str = "scene-order-dtw",
    confidence: float = 0.7,
) -> str:
    aid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            _alignment_t.insert().values(
                id=aid,
                left_ref=left_ref,
                right_ref=right_ref,
                alignment_type=alignment_type,
                method=method,
                assumptions={},
                source_events={},
                confidence=confidence,
            )
        )
    return aid


def insert_assertion(engine: sa.Engine, *, subject_ref: str, predicate: str = "SPEAKS") -> str:
    seed_predicates(engine, (predicate,))
    aid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            _assertion_t.insert().values(
                id=aid,
                predicate_code=predicate,
                subject_ref=subject_ref,
                authority="machine",
                state="UNKNOWN",
            )
        )
    return aid


def insert_alias_map(
    engine: sa.Engine, *, entity_id: str, alias: str, canonical: str, origin_seq: int
) -> None:
    with engine.begin() as conn:
        conn.execute(
            _map_t.insert().values(
                entity_id=entity_id,
                alias=alias,
                canonical_entity_id=canonical,
                origin_seq=origin_seq,
            )
        )


def quarantine_fn(engine: sa.Engine) -> Callable[[str, str], None]:
    """Return a quarantine callable that inserts into the quarantine table."""

    def quarantine(ref: str, reason: str) -> None:
        with engine.begin() as conn:
            conn.execute(
                _q_t.insert().values(
                    locator=ref, reason=reason, stage="resolution", refs={"ref": ref}
                )
            )

    return quarantine


def mention(
    *,
    source_id: str,
    entity_id: str | None,
    text: str,
    candidates: list[tuple[str, float]] | None = None,
    speaker: str | None = None,
    kind: str = "name",
) -> SourceMention:
    return SourceMention(
        id=uuid.uuid4(),
        source_id=source_id,
        entity_id=entity_id,
        mention_text=text,
        mention_kind=kind,
        candidates=[MentionCandidate(entity_ref=c, confidence=s) for c, s in (candidates or [])],
        speaker_label=speaker,
    )
