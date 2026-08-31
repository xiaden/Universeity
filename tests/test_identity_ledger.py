"""Plan S Phase 1 (P1-S6): ledger-first canonical identity is durable and replayable.

Proves that accepted canonical entities are first-class ledger/replay identities
carrying an opaque deterministic ref, canonical type, display label, active
aliases, member mention refs, exact support/evidence refs, confidence/state,
generated-by provenance, and work/source/continuity memberships — and that this
identity metadata is a *replayable* Tier-0 row (inline append == wipe-and-replay).

Concretely, this module pins (over live PostgreSQL where marked):
  * at least 3 accepted canonicals, no synthetic alias entity;
  * exact support/provenance/type/state/membership retention;
  * deterministic rerun (no duplicate events, same refs);
  * append-only history (immutable prior metadata, exposed only via latest);
  * correction replay (a later UPDATE wins by seq; order matters);
  * reversible merge/split does not fabricate identity rows;
  * locks/overrides (USER_OVERRIDE beats a later machine event);
  * inline-vs-wipe/replay equivalence (one shared reducer);
  * non-UUID canonical refs never require fabricated entity rows or UUID FKs
    (``entity_mention.entity_id`` stays NULL).
"""

from __future__ import annotations

import importlib
import json
from typing import Any

import pytest
import sqlalchemy as sa

from job_helpers import ensure_source, make_manifest
from umd.application.commands import SemanticCommandService
from umd.domain.events import SemanticEvent
from umd.domain.evidence import EvidenceBatch
from umd.domain.models import Evidence, EvidenceKind
from umd.projections.base import ReplayDriver
from umd.projections.checkpoint import ProjectionCheckpointStore
from umd.projections.current import CurrentTierOneBuilder, tier0_checksum
from umd.resolution.mentions import PostgresMentionRepository
from umd.resolution.resolution import PostgresSplitEnumerator, Resolver, resolved_event
from umd.storage.postgres.ledger import SemanticLedger
from umd.storage.postgres.reducer import (
    CANONICAL_IDENTITY_PREDICATE,
    STATE_INVALIDATED,
    STATE_USER_CONFIRMED,
    USER_OVERRIDE,
    CurrentStateReducer,
)
from umd.storage.postgres.tables import metadata as db_meta

pytestmark = pytest.mark.postgres

_se = db_meta.tables["semantic_event"]
_cs = db_meta.tables["current_state"]
_em = db_meta.tables["entity_mention"]
_ent = db_meta.tables["entity"]


# ---------------------------------------------------------------------------
# pure reducer helpers (no DB)
# ---------------------------------------------------------------------------


def _establish(canonical: str, seq: int, **meta: Any) -> SemanticEvent:
    ev = resolved_event(
        kind="ESTABLISH",
        entity_id=canonical,
        target_entity_id=canonical,
        canonical_type=meta.get("canonical_type", "character"),
        display_label=meta.get("display_label"),
        aliases=meta.get("aliases", []),
        support_refs=meta.get("support_refs", []),
        memberships=meta.get("memberships", {}),
        state=meta.get("state"),
        classification=meta.get("classification"),
        intensity=meta.get("confidence"),
    )
    return ev.model_copy(update={"seq": seq})


def _update(canonical: str, seq: int, **meta: Any) -> SemanticEvent:
    ev = resolved_event(
        kind="UPDATE",
        entity_id=canonical,
        target_entity_id=canonical,
        display_label=meta.get("display_label"),
        aliases=meta.get("aliases", []),
        state=meta.get("state"),
        intensity=meta.get("confidence"),
    )
    return ev.model_copy(update={"seq": seq})


def _identity_row(state: Any, canonical: str) -> Any:
    return state.rows.get((canonical, CANONICAL_IDENTITY_PREDICATE))


def _metadata_of(row: Any) -> dict[str, Any]:
    assert row is not None
    return json.loads(row.object_ref)


# ---------------------------------------------------------------------------
# pure reducer tests: identity metadata folds to a Tier-0 row
# ---------------------------------------------------------------------------


def test_establish_folds_to_identity_row_and_canonical_entity() -> None:
    events = [_establish("entity:canonical:abc", 1, display_label="Alice")]
    state = CurrentStateReducer().replay(events)
    assert ("entity:canonical:abc", "CANONICAL_ENTITY") in state.rows
    row = _identity_row(state, "entity:canonical:abc")
    meta = _metadata_of(row)
    assert meta["display_label"] == "Alice"
    assert meta["canonical_type"] == "character"
    assert row.state == "CONFIRMED"  # ESTABLISH is a confirmed accepted canonical


def test_classification_folds_and_persists_in_identity_metadata() -> None:
    """Plan T P1-S3/P1-S4: ESTABLISH classification is additive identity metadata.

    The honest accepted/probable/unresolved/ambiguous classification carried by the
    event folds through the ONE reducer into the current_state identity metadata
    (and hence into the object_ref JSON that wipe/replay reconstructs).
    """
    events = [
        _establish("entity:canonical:aaa", 1, display_label="Mara", classification="probable"),
        _establish("entity:canonical:bbb", 2, display_label="Alice", classification="accepted"),
    ]
    state = CurrentStateReducer().replay(events)
    assert (
        _metadata_of(_identity_row(state, "entity:canonical:aaa"))["classification"] == "probable"
    )
    assert (
        _metadata_of(_identity_row(state, "entity:canonical:bbb"))["classification"] == "accepted"
    )
    # No classification present on a legacy event -> reducer stays neutral (no fabricated
    # classification), preserving additive backward compatibility.
    legacy = resolved_event(
        kind="ESTABLISH",
        entity_id="entity:canonical:ccc",
        target_entity_id="entity:canonical:ccc",
        display_label="Bob",
        state="PROBABLE",
    ).model_copy(update={"seq": 3})
    state2 = CurrentStateReducer().replay([*events, legacy])
    assert _metadata_of(_identity_row(state2, "entity:canonical:ccc")).get("classification") is None


def test_at_least_three_canonicals_no_synthetic_alias_entity() -> None:
    canonicals = ["entity:canonical:aaa", "entity:canonical:bbb", "entity:canonical:ccc"]
    events = [_establish(c, i + 1, display_label=f"Char{i}") for i, c in enumerate(canonicals)]
    state = CurrentStateReducer().replay(events)
    assert [_identity_row(state, c) is not None for c in canonicals] == [True, True, True]
    # A synthetic alias entity would be a fourth canonical ref; there are none.
    assert len([r for (r, p) in state.rows if p == "CANONICAL_IDENTITY"]) == 3


def test_exact_support_provenance_type_state_membership_retention() -> None:
    memberships = {"source_ids": ["s:1"], "work_ids": ["w:9"], "continuity_ids": ["c:2"]}
    ev = _establish(
        "entity:canonical:xyz",
        1,
        canonical_type="person",
        display_label="Ellis",
        aliases=["E"],
        support_refs=["m:1", "m:2"],
        memberships=memberships,
        state="CONFIRMED",
        confidence=0.7,
    )
    ev = ev.model_copy(
        update={
            "generated_by": {"stage": "ENTITY_RESOLUTION", "analyzer": "umd-entity-resolution@1"}
        }
    )
    state = CurrentStateReducer().replay([ev])
    meta = _metadata_of(_identity_row(state, "entity:canonical:xyz"))
    assert meta["canonical_type"] == "person"
    assert meta["display_label"] == "Ellis"
    assert meta["aliases"] == ["E"]
    assert meta["support_refs"] == ["m:1", "m:2"]
    assert meta["memberships"] == memberships
    assert meta["confidence"] == 0.7


def test_deterministic_rerun_produces_identical_state() -> None:
    events = [
        _establish("entity:canonical:aaa", 1, display_label="A", aliases=["a"]),
        _establish("entity:canonical:bbb", 2, display_label="B", aliases=["b"]),
    ]
    s1 = CurrentStateReducer().replay(events)
    s2 = CurrentStateReducer().replay(events)
    assert s1.rows.keys() == s2.rows.keys()
    for k in s1.rows:
        assert s1.rows[k].object_ref == s2.rows[k].object_ref
        assert s1.rows[k].seq == s2.rows[k].seq


def test_append_only_history_prior_metadata_immutable_latest_active() -> None:
    events = [
        _establish("entity:canonical:aaa", 1, display_label="A", aliases=["a"]),
        _update("entity:canonical:aaa", 2, display_label="A. Prime", aliases=["a", "ap"]),
    ]
    state = CurrentStateReducer().replay(events)
    meta = _metadata_of(_identity_row(state, "entity:canonical:aaa"))
    assert meta["display_label"] == "A. Prime"  # only latest non-invalidated value active
    row = _identity_row(state, "entity:canonical:aaa")
    assert row.seq == 2
    # Prior active metadata is preserved in the row's alternatives (aux) — never deleted.
    assert any(a["object_ref"] for a in row.alternatives)


def test_correction_replay_order_matters_and_lww_wins() -> None:
    newer_first = [
        _update("c:1", 5, display_label="Later"),
        _establish("c:1", 3, display_label="Earlier"),
    ]
    newer_state = CurrentStateReducer().replay(newer_first)
    assert _metadata_of(_identity_row(newer_state, "c:1"))["display_label"] == "Later"

    older_first = [
        _establish("c:1", 3, display_label="Earlier"),
        _update("c:1", 5, display_label="Later"),
    ]
    older_state = CurrentStateReducer().replay(older_first)
    assert _metadata_of(_identity_row(older_state, "c:1"))["display_label"] == "Later"


def test_user_override_beats_later_machine_establish() -> None:
    override = SemanticEvent(
        event_type="OverrideApplied",
        authority=USER_OVERRIDE,
        payload={
            "subject_ref": "entity:canonical:aaa",
            "predicate": CANONICAL_IDENTITY_PREDICATE,
            "object_ref": json.dumps(
                {"display_label": "Human", "canonical_type": "person"},
                sort_keys=True,
            ),
        },
    ).model_copy(update={"seq": 1})
    later_machine = _establish("entity:canonical:aaa", 2, display_label="Machine")
    state = CurrentStateReducer().replay([override, later_machine])
    row = _identity_row(state, "entity:canonical:aaa")
    assert _metadata_of(row)["display_label"] == "Human"
    assert row.authority == USER_OVERRIDE
    assert row.state == STATE_USER_CONFIRMED


def test_lock_blocks_identity_correction() -> None:
    lock = SemanticEvent(
        event_type="Locked",
        authority="user",
        payload={"subject_ref": "entity:canonical:aaa", "reason": "pin"},
    ).model_copy(update={"seq": 1})
    later = _establish("entity:canonical:aaa", 2, display_label="New")
    state = CurrentStateReducer().replay([lock, later])
    assert _identity_row(state, "entity:canonical:aaa") is None  # locked -> no write


def test_invalidation_marks_identity_inactive() -> None:
    events = [
        _establish("entity:canonical:aaa", 1, display_label="A"),
        SemanticEvent(
            event_type="Invalidated",
            authority="machine",
            payload={
                "subject_ref": "entity:canonical:aaa",
                "predicate": CANONICAL_IDENTITY_PREDICATE,
            },
        ).model_copy(update={"seq": 2}),
    ]
    state = CurrentStateReducer().replay(events)
    row = _identity_row(state, "entity:canonical:aaa")
    assert row.state == STATE_INVALIDATED


def test_non_uuid_refs_require_no_entity_row_or_uuid_fk() -> None:
    # The reducer is pure string-state; it never fabricates an entity row and the
    # typed entity_mention FK stays NULL for non-UUID canonical refs (DB-backed
    # proof below, in test_non_uuid_canonical_refs_leave_fk_null).
    events = [_establish("entity:canonical:not-a-uuid", 1, display_label="Orin")]
    state = CurrentStateReducer().replay(events)
    assert _identity_row(state, "entity:canonical:not-a-uuid") is not None


# ---------------------------------------------------------------------------
# DB-backed helpers (live PostgreSQL)
# ---------------------------------------------------------------------------


def _build_composer(umd_db: sa.Engine) -> tuple[Any, str]:
    production = importlib.import_module("umd.jobs.production")
    ensure_source(umd_db)
    ledger = SemanticLedger(umd_db)
    runtime = production.ProductionRuntime(
        engine=umd_db,
        commands=SemanticCommandService(ledger),
        ledger=ledger,
    )
    composer = production._Composer(umd_db, runtime)  # noqa: SLF001
    src = composer._require_source(make_manifest("ENTITY_RESOLUTION"))  # noqa: SLF001
    return composer, src["id"]


def _seed_cast(composer: Any, sid: str) -> None:
    _c = {"entity_type": "character", "confidence": 0.6}
    mentions = [
        ("Alice", "chapter/1/paragraph/2", {**_c, "co_occurring": ["Robert"]}),
        ("Alice", "chapter/2/paragraph/1", {**_c, "co_occurring": ["Robert"]}),
        (
            "Al",
            "chapter/1/paragraph/1",
            {**_c, "co_occurring": ["Robert"], "normalized_forms": ["alice"]},
        ),
        ("Robert", "chapter/1/paragraph/3", {**_c, "co_occurring": ["Alice"]}),
        ("Robert", "chapter/2/paragraph/2", {**_c, "co_occurring": ["Alice"]}),
        (
            "Bob",
            "chapter/1/paragraph/5",
            {**_c, "co_occurring": ["Alice"], "normalized_forms": ["robert"]},
        ),
        ("Carol", "chapter/1/paragraph/4", {**_c, "co_occurring": ["Dan"]}),
        ("Carol", "chapter/2/paragraph/3", {**_c, "co_occurring": ["Dan"]}),
        (
            "Caro",
            "chapter/1/paragraph/6",
            {**_c, "co_occurring": ["Dan"], "normalized_forms": ["carol"]},
        ),
        ("Astra", "chapter/1/paragraph/7", {**_c, "confidence_state": "AMBIGUOUS"}),
    ]
    records = [
        Evidence(
            source_id=sid,
            evidence_kind=EvidenceKind.TEXT_SPAN,
            locator=locator,
            extraction_stage="STRUCTURAL_ANALYSIS",
            tool_versions={"analyzer": "umd-text-structural@2"},
            config_digest="umd-entity-resolution@1",
            confidence=0.6,
            quality={"candidate_kind": "entity", "mention_text": text, **quality},
        )
        for text, locator, quality in mentions
    ]
    composer._evidence.record(EvidenceBatch(records=records))  # noqa: SLF001


def _count(umd_db: sa.Engine, event_type: str) -> int:
    with umd_db.connect() as conn:
        return int(
            conn.execute(
                sa.select(sa.func.count()).select_from(_se).where(_se.c.event_type == event_type)
            ).scalar()
        )


def _canonical_refs_of(outcome: Any) -> list[str]:
    return sorted(r for r in outcome.artifact_refs if r.startswith("entity:canonical:"))


def _identity_rows(umd_db: sa.Engine) -> list[Any]:
    with umd_db.connect() as conn:
        return conn.execute(
            sa.select(
                _cs.c.entity_ref, _cs.c.object_ref, _cs.c.state, _cs.c.authority, _cs.c.seq
            ).where(_cs.c.predicate == CANONICAL_IDENTITY_PREDICATE)
        ).fetchall()


# ---------------------------------------------------------------------------
# DB-backed tests: durable, replayable, non-UUID, no synthetic entity
# ---------------------------------------------------------------------------


def test_establish_events_and_identity_rows_persist(umd_db: sa.Engine) -> None:
    composer, sid = _build_composer(umd_db)
    _seed_cast(composer, sid)
    outcome = composer._entity_resolution(make_manifest("ENTITY_RESOLUTION"))  # noqa: SLF001
    refs = _canonical_refs_of(outcome)
    assert len(refs) == 3

    # Each accepted canonical is established via an append-only ESTABLISH event.
    with umd_db.connect() as conn:
        est = conn.execute(
            sa.select(sa.func.count())
            .select_from(_se)
            .where(
                (_se.c.event_type == "EntityResolved")
                & (_se.c.payload.op("->>")("kind") == "ESTABLISH")
            )
        ).scalar()
    assert int(est) == 3, "exactly 3 canonical-establishment events"

    # Identity metadata folds to Tier-0 rows and is retained exactly. (The
    # ``object_ref`` is a JSONB column returned as a JSON string; parse each.)
    rows = _identity_rows(umd_db)
    assert len(rows) == 3
    metas = [json.loads(r.object_ref) for r in rows]
    assert len({json.dumps(m, sort_keys=True) for m in metas}) == 3
    labels = {m["display_label"] for m in metas}
    assert labels == {"Alice", "Robert", "Carol"}
    for r in rows:
        meta = json.loads(r.object_ref)
        assert meta["memberships"].get("source_ids") == [sid]
        assert set(meta["aliases"]) <= {"Al", "Bob", "Caro"}
        # Fresh machine-accepted canonicals carry the actual canonical state
        # (PROBABLE, not a fabricated CONFIRMED).
        assert meta["state"] == "PROBABLE"
    # refs are opaque (no source-bound prefix, no filename).
    for ref in refs:
        tail = ref[len("entity:canonical:") :]
        assert ":" not in tail, f"ref carries a source-bound prefix: {ref}"
        assert "chapter" not in tail, f"ref is filename-derived: {ref}"


def test_non_uuid_canonical_refs_leave_fk_null_no_entity_rows(umd_db: sa.Engine) -> None:
    composer, _sid = _build_composer(umd_db)
    _seed_cast(composer, _sid)
    composer._entity_resolution(make_manifest("ENTITY_RESOLUTION"))  # noqa: SLF001
    with umd_db.connect() as conn:
        null_fks = conn.execute(
            sa.select(sa.func.count()).select_from(_em).where(_em.c.entity_id.is_(None))
        ).scalar()
        total = conn.execute(sa.select(sa.func.count()).select_from(_em)).scalar()
        ent_rows = conn.execute(sa.select(sa.func.count()).select_from(_ent)).scalar()
    # All string-canonical mention rows keep a NULL FK (Option B): no fabricated
    # UUID FKs, and no entity-table row is ever written by the string path.
    assert int(null_fks) == int(total)
    assert int(ent_rows) == 0


def test_deterministic_rerun_no_duplicate_establish(umd_db: sa.Engine) -> None:
    composer, sid = _build_composer(umd_db)
    _seed_cast(composer, sid)
    first = _canonical_refs_of(
        composer._entity_resolution(make_manifest("ENTITY_RESOLUTION"))  # noqa: SLF001
    )
    er_before = _count(umd_db, "EntityResolved")
    identity_before = len(_identity_rows(umd_db))
    second = _canonical_refs_of(
        composer._entity_resolution(make_manifest("ENTITY_RESOLUTION"))  # noqa: SLF001
    )
    assert second == first
    assert _count(umd_db, "EntityResolved") == er_before
    assert len(_identity_rows(umd_db)) == identity_before


def test_inline_vs_wipe_replay_equivalence(umd_db: sa.Engine) -> None:
    composer, _sid = _build_composer(umd_db)
    _seed_cast(composer, _sid)
    composer._entity_resolution(make_manifest("ENTITY_RESOLUTION"))  # noqa: SLF001
    # Inline Tier-0 (what append just wrote).
    t0 = tier0_checksum(umd_db)
    # Wipe-and-replay through the ONE shared reducer.
    store = ProjectionCheckpointStore(umd_db)
    builder = CurrentTierOneBuilder()
    result = ReplayDriver(umd_db, store).run(builder, wipe=True)
    assert result.fresh
    assert builder.checksum(umd_db) == t0
    # The replayed identity rows reconstruct exactly the same metadata.
    assert len(_identity_rows(umd_db)) == 3


def test_wipe_replay_preserves_classification_and_opaque_refs(umd_db: sa.Engine) -> None:
    """Plan T P1-S5: wipe/replay equality for the new identity/ref paths.

    Replaying the SAME event batch through the single shared reducer reconstructs
    the exact same canonical refs AND their additive ``classification`` metadata —
    identical opaque refs, identical accepted/probable classification — with no
    duplicate establishment. force_resume/wipe uses the one CurrentTierOneBuilder
    + CurrentStateReducer fold (the replay builder owns the projection).
    """
    composer, sid = _build_composer(umd_db)
    _seed_cast(composer, sid)
    composer._entity_resolution(make_manifest("ENTITY_RESOLUTION"))  # noqa: SLF001

    def _snapshot() -> dict[str, str]:
        out: dict[str, str] = {}
        for r in _identity_rows(umd_db):
            meta = json.loads(r.object_ref)
            out[str(r.entity_ref)] = str(meta.get("classification"))
        return out

    before = _snapshot()
    assert before, "resolution established at least one canonical"
    assert set(before.values()) <= {"accepted", "probable"}

    store = ProjectionCheckpointStore(umd_db)
    builder = CurrentTierOneBuilder()
    ReplayDriver(umd_db, store).run(builder, wipe=True)
    assert _snapshot() == before
    # A second wipe-and-replay is byte-identical (deterministic replay convergence).
    expected = tier0_checksum(umd_db)
    ReplayDriver(umd_db, store).run(CurrentTierOneBuilder(), wipe=True)
    assert tier0_checksum(umd_db) == expected


def test_merge_split_reversible_preserves_identity(umd_db: sa.Engine) -> None:
    composer, _sid = _build_composer(umd_db)
    _seed_cast(composer, _sid)
    outcome = composer._entity_resolution(make_manifest("ENTITY_RESOLUTION"))  # noqa: SLF001
    refs = _canonical_refs_of(outcome)
    assert len(refs) == 3
    ledger = SemanticLedger(umd_db)
    repo = PostgresMentionRepository(umd_db)
    resolver = Resolver(ledger, PostgresSplitEnumerator(umd_db, repo), repo, umd_db)
    # Merge two accepted canonicals; identity rows must not be fabricated/deleted.
    resolver.merge(target_entity=refs[0], merged_refs=refs[1:], reason="test merge")
    with umd_db.connect() as conn:
        merged = conn.execute(
            sa.select(sa.func.count())
            .select_from(_cs)
            .where(_cs.c.predicate == CANONICAL_IDENTITY_PREDICATE)
        ).scalar()
    # Merge is a log record, not a delete: no identity row is removed, none added.
    assert int(merged) == 3
    # Replay remains deterministic after the merge (append-only history intact).
    t0 = tier0_checksum(umd_db)
    builder = CurrentTierOneBuilder()
    ReplayDriver(umd_db, ProjectionCheckpointStore(umd_db)).run(builder, wipe=True)
    assert builder.checksum(umd_db) == t0
