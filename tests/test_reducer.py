"""P3-S2: pure total ``CurrentStateReducer``.

Tests the shared ``reduce_current_state(current_row, event) -> current_row``
contract and the fold ``CurrentStateReducer.reduce/replay``:

  * totality + determinism (identical inputs => identical outputs);
  * last-write-wins per (entity_ref, predicate) within an authority tier;
  * authority precedence: USER_OVERRIDE beats machine inference (a machine event
    must NOT overwrite a user override);
  * locks prevent changes (a locked entity's rows are immutable);
  * contradiction/alternative state (CONFLICTING + contradiction refs; superseded
    winners recorded as alternatives);
  * the <= 5ms p99 Tier-0 target fixture (measured).
"""

from __future__ import annotations

import statistics
import time

from umd.domain.events import SemanticEvent
from umd.storage.postgres.reducer import (
    STATE_AMBIGUOUS,
    STATE_CONFLICTING,
    STATE_USER_CONFIRMED,
    USER_OVERRIDE,
    CurrentReducedState,
    CurrentStateReducer,
    reduce_current_state,
)


def _assertion(seq: int, ref: str, value: str, authority: str = "machine") -> SemanticEvent:
    return SemanticEvent(
        event_type="SemanticAsserted",
        seq=seq,
        authority=authority,
        payload={
            "predicate_code": "SPEAKS",
            "subject_ref": ref,
            "object_ref": value,
            "authority": authority,
            "confidence": 0.6,
            "state": "PROBABLE",
        },
    )


# ---------------------------------------------------------------------------
# totality + determinism
# ---------------------------------------------------------------------------


def test_reduce_is_total_and_deterministic() -> None:
    r = CurrentStateReducer()
    events = [
        _assertion(1, "e:1", "utter:1"),
        _assertion(2, "e:1", "utter:2"),
        SemanticEvent(
            event_type="OverrideApplied",
            seq=3,
            authority=USER_OVERRIDE,
            payload={"subject_ref": "e:1", "predicate": "SPEAKS", "object_ref": "u:user"},
        ),
        _assertion(4, "e:2", "utter:9"),
    ]
    a = r.replay(events)
    b = r.replay(events)
    assert a.rows[("e:1", "SPEAKS")].scalar() == b.rows[("e:1", "SPEAKS")].scalar()
    assert a.rows[("e:2", "SPEAKS")].scalar() == b.rows[("e:2", "SPEAKS")].scalar()
    # total: any event (including unknown / provenance types) folds without error
    r.reduce(CurrentReducedState(), SemanticEvent(event_type="SourceIngested", seq=1, payload={}))
    r.reduce(
        CurrentReducedState(),
        SemanticEvent(event_type="NoSuchThing", seq=1, payload={"foo": 1}),
    )


def test_reduce_current_state_single_row_contract() -> None:
    row = reduce_current_state(
        None,
        SemanticEvent(
            event_type="SemanticAsserted",
            seq=5,
            payload={"predicate_code": "SPEAKS", "subject_ref": "e:1", "object_ref": "u:1"},
        ),
    )
    # Total/deterministic pure function over a row; the fold seeds key-aware rows.
    assert row.state == "UNKNOWN" or row.entity_ref  # never raises


# ---------------------------------------------------------------------------
# last-write-wins + authority precedence
# ---------------------------------------------------------------------------


def test_last_write_wins_within_machine_tier() -> None:
    r = CurrentStateReducer()
    st = CurrentReducedState()
    r.reduce(st, _assertion(1, "e:1", "utter:1"))
    r.reduce(st, _assertion(2, "e:1", "utter:2"))
    assert st.rows[("e:1", "SPEAKS")].object_ref == "utter:2"
    assert st.rows[("e:1", "SPEAKS")].seq == 2


def test_authority_precedence_user_override_beats_machine() -> None:
    r = CurrentStateReducer()
    st = CurrentReducedState()
    r.reduce(st, _assertion(1, "e:1", "machine:1"))
    r.reduce(
        st,
        SemanticEvent(
            event_type="OverrideApplied",
            seq=2,
            authority=USER_OVERRIDE,
            payload={
                "subject_ref": "e:1",
                "predicate": "SPEAKS",
                "object_ref": "user:truth",
                "actor": "user@example",
            },
        ),
    )
    r.reduce(st, _assertion(3, "e:1", "machine:2"))  # must NOT overwrite the user
    row = st.rows[("e:1", "SPEAKS")]
    assert row.object_ref == "user:truth"
    assert row.authority == USER_OVERRIDE
    assert row.state == STATE_USER_CONFIRMED


def test_correction_is_user_authority() -> None:
    r = CurrentStateReducer()
    st = CurrentReducedState()
    r.reduce(st, _assertion(1, "e:1", "machine:1"))
    r.reduce(
        st,
        SemanticEvent(
            event_type="CorrectionApplied",
            seq=2,
            authority=USER_OVERRIDE,
            payload={"subject_ref": "e:1", "predicate": "SPEAKS", "object_ref": "fixed"},
        ),
    )
    assert st.rows[("e:1", "SPEAKS")].object_ref == "fixed"


# ---------------------------------------------------------------------------
# locks prevent changes
# ---------------------------------------------------------------------------


def test_lock_prevents_changes() -> None:
    r = CurrentStateReducer()
    st = CurrentReducedState()
    r.reduce(st, _assertion(1, "e:9", "utter:a"))
    r.reduce(st, SemanticEvent(event_type="Locked", seq=2, payload={"entity_ref": "e:9"}))
    r.reduce(st, _assertion(3, "e:9", "utter:locked"))
    assert st.rows[("e:9", "SPEAKS")].object_ref == "utter:a"  # unchanged
    marker = st.rows[("e:9", "*LOCK*")]
    assert marker.state == "LOCKED"
    assert st.locks["e:9"] is True


def test_unlock_resumes_changes() -> None:
    r = CurrentStateReducer()
    st = CurrentReducedState()
    r.reduce(st, SemanticEvent(event_type="Locked", seq=1, payload={"entity_ref": "e:5"}))
    r.reduce(st, _assertion(2, "e:5", "x"))  # blocked
    r.reduce(st, SemanticEvent(event_type="Unlocked", seq=3, payload={"entity_ref": "e:5"}))
    r.reduce(st, _assertion(4, "e:5", "y"))
    assert st.rows[("e:5", "SPEAKS")].object_ref == "y"


# ---------------------------------------------------------------------------
# EntityResolved / EntityMentioned folding
# ---------------------------------------------------------------------------


def test_entity_resolved_folds_to_canonical_entity_row() -> None:
    r = CurrentStateReducer()
    st = CurrentReducedState()
    r.reduce(
        st,
        SemanticEvent(
            event_type="EntityResolved",
            seq=1,
            payload={"entity_id": "e:1", "target_entity_id": "e:canonical", "kind": "ALIAS"},
        ),
    )
    # EntityResolution folds onto a CANONICAL_ENTITY pseudo-row.
    row = st.rows[("e:1", "CANONICAL_ENTITY")]
    assert row.object_ref == "e:canonical"
    assert row.state == "CONFIRMED"  # ALIAS resolution -> CONFIRMED


def test_entity_resolved_merge_is_probable() -> None:
    r = CurrentStateReducer()
    st = CurrentReducedState()
    r.reduce(
        st,
        SemanticEvent(
            event_type="EntityResolved",
            seq=1,
            payload={"entity_id": "e:1", "target_entity_id": "e:canonical", "kind": "MERGE"},
        ),
    )
    row = st.rows[("e:1", "CANONICAL_ENTITY")]
    assert row.state == "PROBABLE"  # MERGE/SPLIT resolution -> PROBABLE


def test_entity_mentioned_folds_to_candidate_row() -> None:
    r = CurrentStateReducer()
    st = CurrentReducedState()
    r.reduce(
        st,
        SemanticEvent(
            event_type="EntityMentioned",
            seq=1,
            payload={"entity_id": "e:1", "mention_text": "Alice"},
        ),
    )
    # EntityMentioned folds onto a CANDIDATE pseudo-row, marked AMBIGUOUS.
    row = st.rows[("e:1", "CANDIDATE")]
    assert row.state == STATE_AMBIGUOUS
    assert row.alternatives[-1]["mention"] == "Alice"


# ---------------------------------------------------------------------------
# contradiction / alternative state
# ---------------------------------------------------------------------------


def test_contradiction_sets_conflicting_state() -> None:
    r = CurrentStateReducer()
    st = CurrentReducedState()
    r.reduce(st, _assertion(1, "e:1", "utter:1"))
    r.reduce(
        st,
        SemanticEvent(
            event_type="ContradictionRecorded",
            seq=2,
            payload={
                "subject_ref": "e:1",
                "predicate": "SPEAKS",
                "contradicting_ref": "utter:2",
                "refs": ["utter:2"],
            },
        ),
    )
    row = st.rows[("e:1", "SPEAKS")]
    assert row.state == STATE_CONFLICTING
    assert "utter:2" in row.contradiction_refs


def test_invalidated_row_marked() -> None:
    r = CurrentStateReducer()
    st = CurrentReducedState()
    r.reduce(st, _assertion(1, "e:1", "utter:1"))
    r.reduce(
        st,
        SemanticEvent(
            event_type="Invalidated",
            seq=2,
            payload={"subject_ref": "e:1", "predicate": "SPEAKS", "refs": ["utter:1"]},
        ),
    )
    assert st.rows[("e:1", "SPEAKS")].state == "INVALIDATED"


def test_superseded_winner_recorded_as_alternative() -> None:
    r = CurrentStateReducer()
    st = CurrentReducedState()
    r.reduce(st, _assertion(1, "e:1", "utter:1"))
    r.reduce(st, _assertion(2, "e:1", "utter:2"))
    row = st.rows[("e:1", "SPEAKS")]
    assert row.object_ref == "utter:2"
    assert row.alternatives  # the superseded winner is retained as a candidate


# ---------------------------------------------------------------------------
# <= 5 ms p99 Tier-0 target fixture (measured)
# ---------------------------------------------------------------------------

P99_TARGET_SECONDS = 0.005  # 5 ms
_P99_ITERATIONS = 2000


def test_reducer_p99_under_5ms() -> None:
    r = CurrentStateReducer()
    # A representative semantic mix against several entities (indexed row ops).
    mix: list[SemanticEvent] = []
    for i in range(20):
        ref = f"e:{i % 5}"
        mix.append(_assertion(10 + i, ref, f"utter:{i}"))
        if i % 3 == 0:
            mix.append(
                SemanticEvent(
                    event_type="Locked",
                    seq=100 + i,
                    payload={"entity_ref": f"e:{i % 5}"},
                )
            )

    durations: list[float] = []
    for _ in range(_P99_ITERATIONS):
        st = CurrentReducedState()
        t0 = time.perf_counter()
        for ev in mix:
            r.reduce(st, ev)
        durations.append(time.perf_counter() - t0)

    p99 = sorted(durations)[int(len(durations) * 0.99)]
    median = statistics.median(durations)
    print(
        f"reducer p99={p99 * 1000:.3f}ms median={median * 1000:.3f}ms "
        f"(target <= {P99_TARGET_SECONDS * 1000:.0f}ms)"
    )
    assert p99 <= P99_TARGET_SECONDS
