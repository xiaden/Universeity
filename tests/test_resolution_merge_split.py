"""P1-S5 spec-first tests: merge/split restoration, split-time enumeration over
mentions/alignments/claims, ReferenceRebound, and ambiguity quarantine."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import func

from resolution_helpers import (
    insert_alignment,
    insert_assertion,
    insert_entity,
    insert_source,
    mention,
    quarantine_fn,
)
from umd.resolution.mentions import MentionService, PostgresMentionRepository
from umd.resolution.resolution import PostgresSplitEnumerator, Resolver
from umd.storage.postgres.ledger import SemanticLedger
from umd.storage.postgres.tables import metadata as db_meta

pytestmark = pytest.mark.postgres

_mention_t = db_meta.tables["entity_mention"]
_event_t = db_meta.tables["semantic_event"]
_q_t = db_meta.tables["quarantine"]


def _entity_id_of(engine: sa.Engine, mention_id: str) -> str | None:
    with engine.connect() as conn:
        row = conn.execute(
            sa.select(_mention_t.c.entity_id).where(_mention_t.c.id == mention_id)
        ).first()
    return str(row.entity_id) if row is not None and row.entity_id is not None else None


def _rebound_events(engine: sa.Engine) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.select(_event_t.c.payload).where(_event_t.c.event_type == "ReferenceRebound")
        ).fetchall()
    return [r.payload for r in rows]


def _quarantined(engine: sa.Engine) -> list[str]:
    with engine.connect() as conn:
        return [str(x) for x in conn.execute(sa.select(_q_t.c.locator)).scalars().all()]


def test_merge_is_log_record_not_delete(umd_db):
    """MERGE appends history but never deletes source mentions or their candidates."""
    source_id = insert_source(umd_db)
    ent_a = insert_entity(umd_db, label="A")
    ent_b = insert_entity(umd_db, label="B")
    svc = MentionService(
        ledger=SemanticLedger(umd_db), repository=PostgresMentionRepository(umd_db)
    )
    m = mention(source_id=source_id, entity_id=ent_b, text="B-the-name", candidates=[(ent_b, 0.9)])
    _, mid = svc.record(m)

    resolver = Resolver(
        ledger=SemanticLedger(umd_db),
        enumerator=PostgresSplitEnumerator(umd_db, PostgresMentionRepository(umd_db)),
        mentions=PostgresMentionRepository(umd_db),
        engine=umd_db,
    )
    commit = resolver.merge(target_entity=ent_a, merged_refs=[ent_b], reason="test merge")
    assert commit.seq > 0

    # Nothing was deleted: the mention still exists with its candidate set intact.
    still = PostgresMentionRepository(umd_db).get(mid)
    assert still is not None and still.entity_id == ent_b.replace("-", "")
    assert still.candidates[0].entity_ref == ent_b

    # The MERGE event was appended.
    with umd_db.connect() as conn:
        n = conn.execute(
            sa.select(func.count())
            .select_from(_event_t)
            .where(_event_t.c.event_type == "EntityResolved")
        ).scalar()
    assert n == 1


def test_split_rebounds_mentions_and_quarantines_ambiguous(umd_db):
    """SPLIT deterministically re-targets resolvable mentions and quarantines ambiguity."""
    source_id = insert_source(umd_db)
    ent_a = insert_entity(umd_db, label="A")
    ent_b = insert_entity(umd_db, label="B")
    ent_c = insert_entity(umd_db, label="C")
    ent_x = insert_entity(umd_db, label="X")

    svc = MentionService(
        ledger=SemanticLedger(umd_db), repository=PostgresMentionRepository(umd_db)
    )
    m1 = mention(
        source_id=source_id, entity_id=ent_a, text="Alex", candidates=[(ent_b, 0.9), (ent_c, 0.1)]
    )
    m2 = mention(source_id=source_id, entity_id=ent_a, text="lex", candidates=[(ent_c, 0.8)])
    m3 = mention(source_id=source_id, entity_id=ent_a, text="???", candidates=[(ent_x, 0.5)])
    _, m1_id = svc.record(m1)
    _, m2_id = svc.record(m2)
    _, m3_id = svc.record(m3)

    resolver = Resolver(
        ledger=SemanticLedger(umd_db),
        enumerator=PostgresSplitEnumerator(umd_db, PostgresMentionRepository(umd_db)),
        mentions=PostgresMentionRepository(umd_db),
        engine=umd_db,
        quarantine=quarantine_fn(umd_db),
    )
    outcome = resolver.split(entity=ent_a, targets=[ent_b, ent_c], reason="restore B/C")

    # Deterministic assignments: Alex -> B (highest), lex -> C.
    assert outcome.plan.assignments[m1_id] == ent_b
    assert outcome.plan.assignments[m2_id] == ent_c
    # The ambiguous mention is quarantined, never silently dropped from history.
    assert m3_id in outcome.plan.quarantined_refs
    assert m3_id in _quarantined(umd_db)

    # Rows are rebound.
    assert _entity_id_of(umd_db, m1_id) == ent_b
    assert _entity_id_of(umd_db, m2_id) == ent_c

    # Every reassignment emitted a ReferenceRebound event.
    rebounds = _rebound_events(umd_db)
    assert {r["reference"] for r in rebounds} == {m1_id, m2_id}
    assert {r["to_entity"] for r in rebounds} == {ent_b, ent_c}


def test_split_enumerates_alignments_and_claims(umd_db):
    """SPLIT re-targets alignments and semantic claims, not just mentions."""
    source_id = insert_source(umd_db)
    ent_a = insert_entity(umd_db, label="A")
    ent_b = insert_entity(umd_db, label="B")
    ent_c = insert_entity(umd_db, label="C")

    svc = MentionService(
        ledger=SemanticLedger(umd_db), repository=PostgresMentionRepository(umd_db)
    )
    m1 = mention(
        source_id=source_id, entity_id=ent_a, text="Alex", candidates=[(ent_b, 0.9), (ent_c, 0.1)]
    )
    m2 = mention(source_id=source_id, entity_id=ent_a, text="lex", candidates=[(ent_c, 0.8)])
    _, m1_id = svc.record(m1)
    _, m2_id = svc.record(m2)

    aln_id = insert_alignment(umd_db, left_ref=ent_a, right_ref=ent_c)
    claim_id = insert_assertion(umd_db, subject_ref=ent_a, predicate="SPEAKS")

    resolver = Resolver(
        ledger=SemanticLedger(umd_db),
        enumerator=PostgresSplitEnumerator(umd_db, PostgresMentionRepository(umd_db)),
        mentions=PostgresMentionRepository(umd_db),
        engine=umd_db,
        quarantine=quarantine_fn(umd_db),
    )
    plan = resolver._enumerator.enumerate(ent_a, [ent_b, ent_c])

    # Alignment left_ref=A right_ref=C -> single target C in {B,C}.
    assert plan.assignments[aln_id] == ent_c
    # Claim re-targets to the dominant mention target (tie between B/C).
    assert plan.assignments[claim_id] in {ent_b, ent_c}

    resolver.split(entity=ent_a, targets=[ent_b, ent_c])
    rebound_refs = {r["reference"] for r in _rebound_events(umd_db)}
    assert aln_id in rebound_refs
    assert claim_id in rebound_refs


def test_alias_assertion_persists_entity_map(umd_db):
    """ALIAS writes an explicit alias assertion into current_entity_map."""
    ent_a = insert_entity(umd_db, label="A")
    ent_b = insert_entity(umd_db, label="B")
    resolver = Resolver(
        ledger=SemanticLedger(umd_db),
        enumerator=PostgresSplitEnumerator(umd_db, PostgresMentionRepository(umd_db)),
        mentions=PostgresMentionRepository(umd_db),
        engine=umd_db,
    )
    resolver.alias(alias_entity=ent_b, canonical=ent_a, reason="same person")

    map_t = db_meta.tables["current_entity_map"]
    with umd_db.connect() as conn:
        row = conn.execute(sa.select(map_t).where(map_t.c.alias == ent_b)).first()
    assert row is not None
    assert str(row.canonical_entity_id) == ent_a
    assert row.origin_seq is not None


def test_split_restoration_is_deterministic(umd_db):
    """A re-split of the merged entity reproduces identical assignments (reversible projection)."""
    source_id = insert_source(umd_db)
    ent_a = insert_entity(umd_db, label="A")
    ent_b = insert_entity(umd_db, label="B")
    ent_c = insert_entity(umd_db, label="C")

    svc = MentionService(
        ledger=SemanticLedger(umd_db), repository=PostgresMentionRepository(umd_db)
    )
    m1 = mention(
        source_id=source_id, entity_id=ent_a, text="Alex", candidates=[(ent_b, 0.9), (ent_c, 0.1)]
    )
    m2 = mention(source_id=source_id, entity_id=ent_a, text="lex", candidates=[(ent_c, 0.8)])
    _, m1_id = svc.record(m1)
    _, m2_id = svc.record(m2)

    resolver = Resolver(
        ledger=SemanticLedger(umd_db),
        enumerator=PostgresSplitEnumerator(umd_db, PostgresMentionRepository(umd_db)),
        mentions=PostgresMentionRepository(umd_db),
        engine=umd_db,
        quarantine=quarantine_fn(umd_db),
    )
    first = resolver.split(entity=ent_a, targets=[ent_b, ent_c])

    assert first.plan.assignments[m1_id] == ent_b
    assert first.plan.assignments[m2_id] == ent_c
    # Candidates are retained post-split: restoration not destructive to history.
    got = PostgresMentionRepository(umd_db).get(m1_id)
    assert got is not None and {c.entity_ref for c in got.candidates} == {ent_b, ent_c}


# ---------------------------------------------------------------------------
# Plan N Phase 3 (P3-S2) — contradiction (no cross-seed collapse), quarantine
# tie retention, and lock/override precedence over machine resolution reruns.
# ---------------------------------------------------------------------------


def test_machine_rerun_never_collapses_two_existing_canonicals():
    """Two mentions already seeded to DIFFERENT canonicals but strongly linked
    are never merged by a machine rerun — the attempted cross-seed merge is
    surfaced as a contradiction and both canonicals are preserved."""
    import uuid

    from umd.resolution.mentions import SourceMention
    from umd.resolution.service import EntityResolutionService

    m1 = SourceMention(
        id=uuid.UUID("10000000-0000-0000-0000-000000000000"),
        source_id="s",
        entity_id="ent:A",
        mention_text="Alex",
        metadata_={"entity_type": "character"},
        confidence=0.9,
    )
    m2 = SourceMention(
        id=uuid.UUID("20000000-0000-0000-0000-000000000000"),
        source_id="s",
        entity_id="ent:B",
        mention_text="Alex",
        metadata_={"entity_type": "character"},
        confidence=0.9,
    )
    batch = EntityResolutionService().resolve_mentions([m1, m2])

    refs = {e.ref for e in batch.canonical_entities}
    assert refs == {"ent:A", "ent:B"}  # both preserved, never collapsed
    assert len(batch.contradictions) == 1  # surfaced, never silently merged
    assert m1.mention_id in batch.assignments and m2.mention_id in batch.assignments


def test_split_quarantines_ambiguous_tie_retaining_candidates(umd_db):
    """A mention whose candidates TIE between two split targets is quarantined
    (surfaced, never dropped) and its candidate set stays intact/reversible."""
    source_id = insert_source(umd_db)
    ent_a = insert_entity(umd_db, label="A")
    ent_b = insert_entity(umd_db, label="B")
    ent_c = insert_entity(umd_db, label="C")

    svc = MentionService(
        ledger=SemanticLedger(umd_db), repository=PostgresMentionRepository(umd_db)
    )
    m1 = mention(
        source_id=source_id, entity_id=ent_a, text="Alex", candidates=[(ent_b, 0.9), (ent_c, 0.1)]
    )
    m2 = mention(
        source_id=source_id, entity_id=ent_a, text="lex", candidates=[(ent_b, 0.5), (ent_c, 0.5)]
    )
    _, m1_id = svc.record(m1)
    _, m2_id = svc.record(m2)

    resolver = Resolver(
        ledger=SemanticLedger(umd_db),
        enumerator=PostgresSplitEnumerator(umd_db, PostgresMentionRepository(umd_db)),
        mentions=PostgresMentionRepository(umd_db),
        engine=umd_db,
        quarantine=quarantine_fn(umd_db),
    )
    outcome = resolver.split(entity=ent_a, targets=[ent_b, ent_c], reason="restore B/C")

    # Decisive mention is assigned; the TIED mention is quarantined, never guessed.
    assert outcome.plan.assignments[m1_id] == ent_b
    assert m2_id in outcome.plan.quarantined_refs
    assert m2_id in _quarantined(umd_db)
    # Quarantine never deletes the candidate set (reversible, append-only history).
    got = PostgresMentionRepository(umd_db).get(m2_id)
    assert got is not None and {c.entity_ref for c in got.candidates} == {ent_b, ent_c}


def test_user_override_and_lock_outrank_machine_resolution():
    """Human confirmation outranks machine reruns: a USER_OVERRIDE on an alias
    survives a later machine EntityResolved, and a locked entity rejects every
    later machine change (precedence enforced by the shared reducer)."""
    from umd.domain.events import SemanticEvent
    from umd.storage.postgres.reducer import (
        USER_OVERRIDE,
        CurrentReducedState,
        CurrentStateReducer,
    )

    def resolved(seq: int, entity: str, canonical: str) -> SemanticEvent:
        return SemanticEvent(
            event_type="EntityResolved",
            seq=seq,
            authority="machine",
            payload={"kind": "ALIAS", "entity_id": entity, "target_entity_id": canonical},
        )

    r = CurrentStateReducer()
    st = CurrentReducedState()

    # 1. A machine alias decision is folded.
    r.reduce(st, resolved(1, "alias:x", "canon:1"))
    assert st.rows[("alias:x", "CANONICAL_ENTITY")].object_ref == "canon:1"

    # 2. A human override pins alias:x -> canon:2.
    r.reduce(
        st,
        SemanticEvent(
            event_type="OverrideApplied",
            seq=2,
            authority=USER_OVERRIDE,
            payload={
                "subject_ref": "alias:x",
                "predicate": "CANONICAL_ENTITY",
                "object_ref": "canon:2",
            },
        ),
    )
    row = st.rows[("alias:x", "CANONICAL_ENTITY")]
    assert row.object_ref == "canon:2"
    assert row.authority == USER_OVERRIDE

    # 3. A LATER machine rerun must NOT overwrite the human pin.
    r.reduce(st, resolved(3, "alias:x", "canon:3"))
    assert st.rows[("alias:x", "CANONICAL_ENTITY")].object_ref == "canon:2"

    # 4. A locked entity rejects later machine resolution entirely.
    r.reduce(st, SemanticEvent(event_type="Locked", seq=4, payload={"entity_ref": "alias:y"}))
    r.reduce(st, resolved(5, "alias:y", "canon:9"))
    assert ("alias:y", "CANONICAL_ENTITY") not in st.rows  # locked -> no change row


def test_merge_is_log_record_not_identity_delete_and_replay_deterministic():
    """Plan S P1-S6: a merge of accepted canonicals is a log record, not a delete —
    the established identity metadata rows are neither removed nor rewritten, and
    replay of the same stream is deterministic."""
    from umd.domain.events import SemanticEvent
    from umd.resolution.resolution import resolved_event
    from umd.storage.postgres.reducer import (
        CANONICAL_IDENTITY_PREDICATE,
        CurrentReducedState,
        CurrentStateReducer,
    )

    def establish(canonical: str, seq: int, label: str) -> SemanticEvent:
        return resolved_event(
            kind="ESTABLISH", entity_id=canonical, target_entity_id=canonical, display_label=label
        ).model_copy(update={"seq": seq})

    events = [
        establish("canon:1", 1, "Alice"),
        establish("canon:2", 2, "Bob"),
        SemanticEvent(
            event_type="EntityResolved",
            seq=3,
            authority="machine",
            payload={
                "kind": "MERGE",
                "entity_id": "canon:1",
                "target_entity_id": "canon:2",
                "refs": ["canon:2"],
                "assignments": {"canon:2": "canon:1"},
            },
        ),
    ]

    r = CurrentStateReducer()
    st = CurrentReducedState()
    for ev in events:
        r.reduce(st, ev)

    # Merge is a log record, not a delete: both identity rows survive.
    assert ("canon:1", CANONICAL_IDENTITY_PREDICATE) in st.rows
    assert ("canon:2", CANONICAL_IDENTITY_PREDICATE) in st.rows
    # The merged target keeps its display label; nothing was synthesized.
    assert st.rows[("canon:1", CANONICAL_IDENTITY_PREDICATE)].object_ref is not None
    assert st.rows[("canon:2", CANONICAL_IDENTITY_PREDICATE)].object_ref is not None

    # Replaying the identical stream is deterministic.
    st2 = CurrentStateReducer().replay(events)
    assert st.rows.keys() == st2.rows.keys()
    for k in st.rows:
        assert st.rows[k].object_ref == st2.rows[k].object_ref
        assert st.rows[k].seq == st2.rows[k].seq
