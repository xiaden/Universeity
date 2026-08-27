"""P3-S1/P3-S2: append-only ledger, atomic event+Tier-0 commit, idempotency.

Postgres-backed (``postgres`` marker): proves the ledger is the ONLY semantic
write authority.
  * append commits event(s) + Tier-0 delta atomically and returns
    ``read_your_writes_token = seq``;
  * a duplicate ``idempotency_key`` does not duplicate authoritative completion
    (same token returned, no new rows);
  * wipe-and-replay (replay the persisted event log from empty) equals the inline
    Tier-0 state — event construction vs replay conformance;
  * no in-place UPDATE is possible on ``semantic_event`` (append-only trigger);
  * JobRunAudit-type events are written but excluded from semantic replay.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from umd.domain.events import SemanticEvent
from umd.storage.postgres.ledger import SemanticLedger
from umd.storage.postgres.reducer import (
    STATE_USER_CONFIRMED,
    USER_OVERRIDE,
    CurrentStateReducer,
)
from umd.storage.postgres.tables import metadata as db_meta

pytestmark = pytest.mark.postgres

_se = db_meta.tables["semantic_event"]
_cs = db_meta.tables["current_state"]


def _assertion(seq: int, ref: str, value: str) -> SemanticEvent:
    return SemanticEvent(
        event_type="SemanticAsserted",
        seq=seq,
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


def test_caller_event_unmutated_after_append(umd_db: sa.Engine) -> None:
    """append must not mutate the caller's SemanticEvent (model_copy non-mutation)."""
    ledger = SemanticLedger(umd_db)
    ev = _assertion(0, "e:1", "utter:1")  # caller-provided placeholder seq
    orig = ev.model_dump()
    res = ledger.append([ev], idempotency_key=uuid.uuid4())
    assert res.seq > 0
    # The DB seq overwrote the placeholder internally, but the caller's object
    # must be untouched (no hidden side effect).
    assert ev.model_dump() == orig
    assert ev.seq == 0


def test_append_commits_event_and_tier0_atomically(umd_db: sa.Engine) -> None:
    ledger = SemanticLedger(umd_db)
    key = uuid.uuid4()
    events = [_assertion(0, "e:1", "utter:1")]
    res = ledger.append(events, idempotency_key=key)
    assert res.seq > 0
    assert res.read_your_writes_token == res.seq  # token = seq

    with umd_db.connect() as conn:
        row = conn.execute(sa.select(_se.c.seq, _se.c.payload).where(_se.c.seq == res.seq)).one()
        state = conn.execute(
            sa.select(_cs).where((_cs.c.entity_ref == "e:1") & (_cs.c.predicate == "SPEAKS"))
        ).one()
    assert row.payload["subject_ref"] == "e:1"
    assert state.object_ref == "utter:1"
    assert state.seq == res.seq  # Tier-0 row points at the same event seq


def test_idempotency_key_dedup_does_not_duplicate_completion(
    umd_db: sa.Engine,
) -> None:
    ledger = SemanticLedger(umd_db)
    key = uuid.uuid4()
    e1 = [_assertion(0, "e:1", "utter:1"), _assertion(0, "e:2", "utter:9")]
    r1 = ledger.append(e1, idempotency_key=key)
    # A duplicate submission of the SAME idempotency key returns the same token
    # and inserts nothing new.
    r2 = ledger.append(e1, idempotency_key=key)
    assert r1.seq == r2.seq
    assert r2.read_your_writes_token == r1.read_your_writes_token
    with umd_db.connect() as conn:
        n = conn.execute(sa.select(sa.func.count()).select_from(_se)).scalar()
    assert n == len(e1)  # exactly one authoritative completion, no duplication


def test_expected_version_conflict_raises(umd_db: sa.Engine) -> None:
    from umd.storage.postgres.ledger import LedgerConflictError

    ledger = SemanticLedger(umd_db)
    ledger.append([_assertion(0, "e:1", "u:1")])
    with pytest.raises(LedgerConflictError):
        ledger.append([_assertion(0, "e:2", "u:2")], expected_version=0)


def test_wipe_and_replay_equals_inline_tier0(umd_db: sa.Engine) -> None:
    """Event-construction vs replay conformance: replay reproduces Tier-0."""
    ledger = SemanticLedger(umd_db)
    # an idempotency-keyed batch
    ledger.append([_assertion(0, "e:1", "utter:1"), _assertion(0, "e:2", "utter:9")])
    # builder events via the command/construction path
    ledger.append(
        [
            SemanticEvent(
                event_type="OverrideApplied",
                authority=USER_OVERRIDE,
                payload={"subject_ref": "e:1", "predicate": "SPEAKS", "object_ref": "u:truth"},
            )
        ]
    )
    ledger.append([_assertion(0, "e:1", "utter:should-not-win")])

    # Replay the persisted log from EMPTY (wipe-and-replay of the ledger).
    events = _load_all_events(umd_db)
    state = CurrentStateReducer().replay(events)

    with umd_db.connect() as conn:
        db_rows = conn.execute(
            sa.select(
                _cs.c.entity_ref,
                _cs.c.predicate,
                _cs.c.object_ref,
                _cs.c.confidence,
                _cs.c.authority,
                _cs.c.state,
                _cs.c.seq,
            )
        ).fetchall()
    db_map = {(r.entity_ref, r.predicate): r for r in db_rows}

    assert ("e:1", "SPEAKS") in state.rows
    replayed = state.rows[("e:1", "SPEAKS")]
    persisted = db_map[("e:1", "SPEAKS")]
    # USER_OVERRIDE winner survives the trailing machine assertion in both.
    assert replayed.object_ref == "u:truth"
    assert persisted.object_ref == "u:truth"
    assert replayed.authority == USER_OVERRIDE
    assert persisted.authority == USER_OVERRIDE
    assert replayed.state == STATE_USER_CONFIRMED
    assert persisted.state == STATE_USER_CONFIRMED


def test_lock_marker_persisted_and_blocks_locked_append(
    umd_db: sa.Engine,
) -> None:
    """Lock state persists to PG (*LOCK* marker) and blocks subsequent appends."""
    ledger = SemanticLedger(umd_db)

    # Lock an entity via the ledger (the only semantic write authority).
    ledger.append([SemanticEvent(event_type="Locked", payload={"entity_ref": "e:9"})])

    # The lock must be persisted as a queryable *LOCK* marker on current_state.
    with umd_db.connect() as conn:
        marker = conn.execute(
            sa.select(_cs).where((_cs.c.entity_ref == "e:9") & (_cs.c.predicate == "*LOCK*"))
        ).one()
    assert marker.state == "LOCKED"

    # A semantic append on the locked entity must be rejected (no Tier-0 change).
    res = ledger.append([_assertion(0, "e:9", "utter:locked")])
    assert res.seq > 0  # the event row is still appended (auditable)
    with umd_db.connect() as conn:
        n = conn.execute(
            sa.select(sa.func.count())
            .select_from(_cs)
            .where((_cs.c.entity_ref == "e:9") & (_cs.c.predicate == "SPEAKS"))
        ).scalar()
    assert n == 0  # locked entity: the change is a no-op on Tier-0


def test_append_only_no_inplace_update(umd_db: sa.Engine) -> None:
    ledger = SemanticLedger(umd_db)
    res = ledger.append([_assertion(0, "e:1", "utter:1")])
    with pytest.raises(sa.exc.DBAPIError), umd_db.begin() as conn:
        conn.execute(
            sa.text("UPDATE semantic_event SET event_type='HACKED' WHERE seq=:s"),
            {"s": res.seq},
        )
    with umd_db.connect() as conn:
        val = conn.execute(
            sa.text(
                "SELECT count(*) FROM semantic_event WHERE seq=:s AND event_type='SemanticAsserted'"
            ),
            {"s": res.seq},
        ).scalar()
    assert val == 1


def test_job_run_audit_event_excluded_from_replay(umd_db: sa.Engine) -> None:
    """JobRunAudit is committed as an event but excluded from semantic replay."""
    ledger = SemanticLedger(umd_db)
    audit = SemanticEvent(
        event_type="JobRunAudit",
        payload={"job_id": "j1", "stage_name": "INGEST", "action": "complete"},
    )
    res = ledger.append([_assertion(0, "e:1", "utter:1"), audit])
    assert res.seq > 0
    assert not audit.is_semantic  # this event type never feeds Tier-0
    events = _load_all_events(umd_db)
    # Only the SemanticAsserted drives Tier-0 rows (JobRunAudit excluded).
    tier0_keys = {k for k in CurrentStateReducer().replay(events).rows if k[1] != "*LOCK*"}
    assert ("e:1", "SPEAKS") in tier0_keys
    assert ("j1", "JOB_RUN") not in tier0_keys


def _load_all_events(engine: sa.Engine) -> list[SemanticEvent]:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.select(
                _se.c.seq, _se.c.event_type, _se.c.payload, _se.c.authority, _se.c.created_by
            ).order_by(_se.c.seq)
        ).fetchall()
    return [
        SemanticEvent(
            event_type=r.event_type,
            payload=dict(r.payload or {}),
            authority=r.authority,
            created_by=r.created_by,
            seq=r.seq,
        )
        for r in rows
    ]
