"""P2-S1 / P2-S2: replay + storage-ownership acceptance (every Tier-1 projection).

Closes the two genuine Phase-2 acceptance gaps left by earlier phases:

* Wipe-and-replay is proven for ALL THREE Tier-1 projections — ``current_tier1``,
  ``search`` and ``vector`` (the vector projection was previously only tested for
  exact-fallback recall, never for wipe-and-replay determinism). For each, replaying
  from ``seq=0`` yields a canonical checksum equal to the inline / prior state, and
  **no authoritative event is skipped** (``events_seen == ledger tail``, ``skipped == 0``
  on a clean deck).
* Only projection builders can write the Tier-1 stores is proven at the ledger
  boundary: a semantic append writes the Tier-0 ``current_state`` (the authority) but
  writes NOTHING to ``search_document`` / ``embedding`` / ``projection_generation``; those
  appear only after a builder replay.

P2-S2: the query-cost control is asserted directly at the enforcement point
(:func:`umd.api.routers.query._bounded`) — max_depth is capped by ``query_cost.max_depth``
and limit by ``query_cost.max_limit`` regardless of what a caller requests.

These add to the suite; no earlier test is modified or weakened.
"""

from __future__ import annotations

import hashlib
import uuid
from types import SimpleNamespace
from typing import cast

import pytest
import sqlalchemy as sa

from resolution_helpers import insert_source
from umd.api.routers.query import _bounded
from umd.config import Settings
from umd.domain.events import SemanticEvent
from umd.projections.base import ReplayDriver
from umd.projections.checkpoint import ProjectionCheckpointStore
from umd.projections.current import CurrentTierOneBuilder, tier0_checksum
from umd.projections.edges import ActiveSemanticEdgeProjectionBuilder
from umd.projections.search import SearchProjectionBuilder
from umd.projections.tables import projection_generation, search_document_in
from umd.projections.vector import EmbeddingProjectionBuilder
from umd.storage.postgres.ledger import SemanticLedger
from umd.storage.postgres.reducer import USER_OVERRIDE
from umd.storage.postgres.tables import metadata as db_meta

pytestmark = pytest.mark.postgres

_se = db_meta.tables["semantic_event"]
_cs = db_meta.tables["current_state"]
_embed = db_meta.tables["embedding"]
_pg = projection_generation


# ---------------------------------------------------------------------------
# local fixture helpers (avoids cross-test import coupling)
# ---------------------------------------------------------------------------


def _assertion(ref: str, value: str) -> SemanticEvent:
    return SemanticEvent(
        event_type="SemanticAsserted",
        authority="machine",
        payload={
            "predicate_code": "SPEAKS",
            "subject_ref": ref,
            "object_ref": value,
            "authority": "machine",
            "confidence": 0.6,
            "state": "PROBABLE",
            "scope": "CONTINUITY",
        },
    )


def _mention_with_segment(source_id: str, text: str, segment_id: str) -> SemanticEvent:
    return SemanticEvent(
        event_type="EntityMentioned",
        authority="machine",
        payload={
            "mention_id": f"m:{uuid.uuid5(uuid.NAMESPACE_DNS, text)}",
            "source_id": source_id,
            "segment_id": segment_id,
            "mention_text": text,
        },
    )


def _override(ref: str, predicate: str, value: str) -> SemanticEvent:
    return SemanticEvent(
        event_type="OverrideApplied",
        authority=USER_OVERRIDE,
        payload={"subject_ref": ref, "predicate": predicate, "object_ref": value},
    )


def _make_segment(engine: sa.Engine, source_id: str, key: str) -> str:
    seg_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            db_meta.tables["segment"]
            .insert()
            .values(
                id=seg_id,
                source_id=source_id,
                segment_type="text",
                deterministic_key=key,
                ordinal=1,
            )
        )
    return seg_id


def _tail(engine: sa.Engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(sa.select(sa.func.max(_se.c.seq))).scalar() or 0)


def _sd_refs(engine: sa.Engine) -> set[tuple[str, str]]:
    t = search_document_in("public")
    with engine.connect() as conn:
        rows = conn.execute(sa.select(t.c.kind, t.c.ref)).fetchall()
    return {(str(r.kind), str(r.ref)) for r in rows}


def _embedding_checksum(engine: sa.Engine) -> str:
    h = hashlib.sha256()
    with engine.connect() as conn:
        rows = conn.execute(
            sa.select(_embed.c.evidence_ref, _embed.c.vector_json).order_by(_embed.c.evidence_ref)
        ).fetchall()
    for r in rows:
        h.update(str(r.evidence_ref).encode() + b"\x1f" + str(r.vector_json).encode() + b"\n")
    return f"{h.hexdigest()}:{len(rows)}"


# ---------------------------------------------------------------------------
# P2-S1: wipe-and-replay every Tier-1 projection; no authoritative event skipped
# ---------------------------------------------------------------------------


def test_wipe_replay_current_tier1_matches_tier0_and_skips_nothing(
    umd_db: sa.Engine,
) -> None:
    """The current_tier1 projection wipes to seq=0 and re-folds to Tier-0 exactly.

    Unlike the search/vector projections, current_tier1 folds EVERY semantic event
    (including authority overrides) because it IS the replay-equivalent Tier-0. A
    wipe-and-replay must reproduce the inline Tier-0 canonical checksum and must
    skip no authoritative event.
    """
    source_id = insert_source(umd_db, media_kind="text")
    seg = _make_segment(umd_db, source_id, "curr#1")
    ledger = SemanticLedger(umd_db)
    ledger.append(
        [
            _assertion("e:1", "utter:1"),
            _mention_with_segment(source_id, "Sherlock Holmes", seg),
            _override("e:1", "speaker", "Dr. Watson the canonical"),
            _assertion("e:1", "utter:loses-to-override"),
            _assertion("e:2", "utter:9"),
        ]
    )
    tail = _tail(umd_db)
    inline = tier0_checksum(umd_db)  # inline Tier-0 authority state after append

    store = ProjectionCheckpointStore(umd_db)
    driver = ReplayDriver(umd_db, store)
    builder = CurrentTierOneBuilder()

    r = driver.run(builder, wipe=True)  # wipe-and-replay from seq=0
    assert r.fresh and r.applied_seq == tail
    assert r.events_seen == tail  # every authoritative event was folded
    assert r.skipped == 0  # no authoritative event skipped
    assert builder.checksum(umd_db) == inline  # replayed Tier-1 == inline Tier-0

    # A SECOND wipe-and-replay yields the identical canonical checksum (deterministic).
    r2 = driver.run(builder, wipe=True)
    assert r2.events_seen == tail and r2.skipped == 0
    assert builder.checksum(umd_db) == inline

    # The authority override survived the replay (not lost to the machine tail).
    with umd_db.connect() as conn:
        row = conn.execute(
            sa.select(_cs.c.object_ref, _cs.c.authority).where(
                (_cs.c.entity_ref == "e:1") & (_cs.c.predicate == "speaker")
            )
        ).one()
    assert row.object_ref == "Dr. Watson the canonical"
    assert row.authority == USER_OVERRIDE


def test_wipe_replay_search_deterministic_no_authoritative_skip(umd_db: sa.Engine) -> None:
    """Search projection wipe-and-replays to the identical doc set, skipping nothing."""
    source_id = insert_source(umd_db, media_kind="text")
    seg = _make_segment(umd_db, source_id, "search#1")
    ledger = SemanticLedger(umd_db)
    ledger.append(
        [
            _mention_with_segment(source_id, "Sherlock Holmes", seg),
            _mention_with_segment(source_id, "Moriarty", seg),
            _assertion("e:1", "The game is afoot"),
        ]
    )
    tail = _tail(umd_db)
    store = ProjectionCheckpointStore(umd_db)
    driver = ReplayDriver(umd_db, store)
    builder = SearchProjectionBuilder()

    first = driver.run(builder, wipe=True)
    assert first.fresh and first.applied_seq == tail
    assert first.events_seen == tail  # no authoritative event skipped
    assert first.skipped == 0
    docs_first = _sd_refs(umd_db)

    second = driver.run(builder, wipe=True)  # wipe + replay again
    assert second.events_seen == tail and second.skipped == 0
    assert _sd_refs(umd_db) == docs_first  # canonical doc set identical


def test_wipe_replay_vector_projection_deterministic_no_authoritative_skip(
    umd_db: sa.Engine,
) -> None:
    """The vector (embedding) projection is a disposable Tier-1 store: wiping and
    replaying from seq=0 yields the identical immutable embedding row set."""
    source_id = insert_source(umd_db, media_kind="text")
    seg = _make_segment(umd_db, source_id, "vector#1")
    ledger = SemanticLedger(umd_db)
    ledger.append(
        [
            _mention_with_segment(source_id, "Sherlock Holmes solves cases", seg),
            _mention_with_segment(source_id, "The baker baked cookies", seg),
            _assertion("e:1", "A non segment-anchored utterance is not embeddable"),
        ]
    )
    tail = _tail(umd_db)
    store = ProjectionCheckpointStore(umd_db)
    driver = ReplayDriver(umd_db, store)
    builder = EmbeddingProjectionBuilder()

    first = driver.run(builder, wipe=True)
    assert first.fresh and first.applied_seq == tail
    assert first.events_seen == tail  # every event was seen (none skipped)
    assert first.skipped == 0
    checksum_a = _embedding_checksum(umd_db)

    # Wipe + replay again -> identical immutable embedding rows (canonical digest).
    second = driver.run(builder, wipe=True)
    assert second.events_seen == tail and second.skipped == 0
    assert _embedding_checksum(umd_db) == checksum_a
    assert int(checksum_a.rsplit(":", 1)[1]) == 2  # the two segment-anchored mentions


# ---------------------------------------------------------------------------
# P2-S1: only projection builders write projection stores
# ---------------------------------------------------------------------------


def test_only_builders_write_projection_stores_ledger_path_writes_none(
    umd_db: sa.Engine,
) -> None:
    """Semantic appends never write the Tier-1 stores; only a builder replay does.

    Tier-0 ``current_state`` is written by the authority (inline reducer) — that is the
    semantic ledger's job. But ``search_document``, ``embedding`` and
    ``projection_generation`` must remain empty after an append and appear only once a
    Tier-1 builder replays the ledger.
    """
    source_id = insert_source(umd_db, media_kind="text")
    seg = _make_segment(umd_db, source_id, "own#1")
    ledger = SemanticLedger(umd_db)
    ledger.append(
        [
            _assertion("e:1", "utter:1"),
            _mention_with_segment(source_id, "Ownership mention", seg),
        ]
    )

    # After the append, the Tier-0 table IS the authority (populated by the reducer)…
    with umd_db.connect() as conn:
        assert int(conn.execute(sa.select(sa.func.count()).select_from(_cs)).scalar() or 0) > 0
    # …but NOT ONE Tier-1 store has been touched by the append path.
    assert _sd_refs(umd_db) == set()
    with umd_db.connect() as conn:
        assert conn.execute(sa.select(sa.func.count()).select_from(_embed)).scalar() == 0
        assert conn.execute(sa.select(sa.func.count()).select_from(_pg)).scalar() == 0

    # Only a builder (driven by ReplayDriver) populates the Tier-1 stores.
    store = ProjectionCheckpointStore(umd_db)
    driver = ReplayDriver(umd_db, store)
    driver.run(SearchProjectionBuilder(), wipe=True)
    driver.run(EmbeddingProjectionBuilder(), wipe=True)
    assert len(_sd_refs(umd_db)) >= 1
    with umd_db.connect() as conn:
        assert int(conn.execute(sa.select(sa.func.count()).select_from(_embed)).scalar() or 0) >= 1


# ---------------------------------------------------------------------------
# P3-S2: migration 0008 applies on real PostgreSQL; edges written only by builder
# ---------------------------------------------------------------------------


def test_migration_0008_active_semantic_edge_and_indexes_exist(umd_db: sa.Engine) -> None:
    """P3-S2: migration 0008 applies on real PostgreSQL — the table and every
    read-path index (multi-edge subject/predicate/active, plus subject/predicate/
    active/scope/state) exist."""
    with umd_db.connect() as conn:
        table = conn.execute(
            sa.text("SELECT to_regclass('public.active_semantic_edge') IS NOT NULL")
        ).scalar()
        assert table is True
        idxs = {
            str(r[0])
            for r in conn.execute(
                sa.text("SELECT indexname FROM pg_indexes WHERE tablename = 'active_semantic_edge'")
            ).fetchall()
        }
    assert {
        "pk_active_semantic_edge",
        "ix_active_semantic_edge_subject_pred",
        "ix_active_semantic_edge_subject",
        "ix_active_semantic_edge_predicate",
        "ix_active_semantic_edge_active",
        "ix_active_semantic_edge_scope",
        "ix_active_semantic_edge_state",
    } <= idxs


def test_active_semantic_edge_written_only_by_builder(umd_db: sa.Engine) -> None:
    """P3-S2: no stage/API/ledger append path writes the edge store — active edges
    appear only after the replay-built ActiveSemanticEdgeProjectionBuilder runs."""
    source_id = insert_source(umd_db, media_kind="text")
    seg = _make_segment(umd_db, source_id, "edge#1")
    ledger = SemanticLedger(umd_db)
    ledger.append(
        [
            _assertion("e:1", "utter:1"),
            _assertion("e:2", "utter:2"),
            _mention_with_segment(source_id, "Ownership mention", seg),
        ]
    )
    with umd_db.connect() as conn:
        assert (
            int(conn.execute(sa.text("SELECT count(*) FROM active_semantic_edge")).scalar() or 0)
            == 0
        ), "append path must not write active_semantic_edge"

    builder = ActiveSemanticEdgeProjectionBuilder()
    ReplayDriver(umd_db, ProjectionCheckpointStore(umd_db)).run(builder, wipe=True)
    with umd_db.connect() as conn:
        n = int(conn.execute(sa.text("SELECT count(*) FROM active_semantic_edge")).scalar() or 0)
    assert n >= 2, "edge builder must materialize the appended assertions as active edges"


def test_edge_wipe_and_replay_is_deterministic(umd_db: sa.Engine) -> None:
    """P3-S2: wiping and replaying the edge builder is deterministic — the same
    active-edge fact set (fact_id, predicate, subject, object, active) is reproduced."""
    ledger = SemanticLedger(umd_db)
    ledger.append([_assertion("e:1", "utter:1"), _assertion("e:2", "utter:2")])

    def snapshot() -> set[tuple[str, str, str, str, bool]]:
        builder = ActiveSemanticEdgeProjectionBuilder()
        ReplayDriver(umd_db, ProjectionCheckpointStore(umd_db)).run(builder, wipe=True)
        with umd_db.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT fact_id, predicate, subject_ref, object_ref, active "
                    "FROM active_semantic_edge ORDER BY fact_id"
                )
            ).fetchall()
        return {
            (str(r.fact_id), r.predicate, r.subject_ref, r.object_ref, bool(r.active)) for r in rows
        }

    first = snapshot()
    second = snapshot()
    assert first == second
    assert len(first) >= 2


# ---------------------------------------------------------------------------
# P2-S2: query-cost control is enforced at the API boundary
# ---------------------------------------------------------------------------


def test_query_cost_caps_depth_and_limit_regardless_of_request() -> None:
    from umd.api.deps import AppContext
    from umd.api.schemas import StructuredQueryRequest

    # Defaults: query_cost.max_depth=4, query_cost.max_limit=200, default_limit=20.
    ctx = cast(AppContext, SimpleNamespace(settings=Settings()))
    # A caller asking for unbounded depth/limit is capped, never honored verbatim.
    depth, limit, _offset = _bounded(
        cast("StructuredQueryRequest", SimpleNamespace(max_depth=99, limit=9999, offset=0)),
        ctx,
    )
    assert depth == 4  # capped to query_cost.max_depth
    assert limit == 200  # capped to query_cost.max_limit
    # Omitted values fall back to the query-cost defaults (still bounded).
    depth2, limit2, _ = _bounded(
        cast("StructuredQueryRequest", SimpleNamespace(max_depth=None, limit=None, offset=5)),
        ctx,
    )
    assert depth2 == 4
    assert limit2 == 20  # default_limit
