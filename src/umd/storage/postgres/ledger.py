"""Append-only semantic ledger: the sole semantic write authority (P3-S1/P3-S2).

Implements the binding contract
``SemanticLedger.append(events, expected_version, idempotency_key) ->
CommitResult(seq, read_your_writes_token)``.

Invariants enforced here:
  * append-only — events are INSERTed into ``semantic_event`` only; no in-place
    UPDATE (Phase 1 already installs the blocking trigger);
  * atomicity — the event row(s) AND the Tier-0 ``current_state`` update commit
    in ONE transaction (a crash cannot commit an event without its Tier-0 delta);
  * idempotency — a duplicate ``idempotency_key`` returns the existing commit
    (seq) and does NOT duplicate authoritative completion;
  * read-your-writes — a mutation returns ``read_your_writes_token = seq``;
  * Tier-0 is updated only through the shared pure :class:`CurrentStateReducer`
    (the same code path as wipe-and-replay).
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa

from umd.domain.events import EventSchemaError, SemanticEvent
from umd.storage.postgres.reducer import (
    STATE_UNLOCKED,
    CurrentReducedState,
    CurrentStateReducer,
)
from umd.storage.postgres.tables import metadata as db_meta

_event_t = db_meta.tables["semantic_event"]
_state_t = db_meta.tables["current_state"]

#: PostgreSQL-dialect insert so ``on_conflict_do_nothing`` type-checks cleanly.
pg_insert = sa.dialects.postgresql.insert


class LedgerConflictError(RuntimeError):
    """Raised when an optimistic ``expected_version`` check fails on append."""


class LedgerError(RuntimeError):
    """Raised when an event cannot be appended (e.g. validation)."""


class CommitResult:
    """Result of a successful :meth:`SemanticLedger.append`."""

    __slots__ = ("seq", "read_your_writes_token")

    def __init__(self, seq: int, read_your_writes_token: int) -> None:
        self.seq = seq
        self.read_your_writes_token = read_your_writes_token

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"CommitResult(seq={self.seq}, read_your_writes_token={self.read_your_writes_token})"


class SemanticLedger:
    """PostgreSQL append-only authority over semantic events and Tier-0 state."""

    def __init__(self, engine: sa.Engine, reducer: CurrentStateReducer | None = None) -> None:
        self._engine = engine
        self._reducer = reducer or CurrentStateReducer()

    # -- public contract --------------------------------------------------

    def append(
        self,
        events: list[SemanticEvent],
        expected_version: int | None = None,
        idempotency_key: str | uuid.UUID | None = None,
    ) -> CommitResult:
        """Atomically append event(s) and apply the Tier-0 reducer delta.

        ``expected_version`` is optimistic concurrency on the ledger tail (the
        committed seq the caller believes it is at); ``None`` disables the check.

        The event rows and the Tier-0 ``current_state`` delta commit in the ONE
        transaction opened here. Callers that need to anchor additional side
        effects (e.g. a ``stage_run`` completion row) to the SAME transaction
        should use the internal :meth:`_append_all_events_on` with an explicit connection
        instead of this standalone wrapper.
        """
        key = uuid.UUID(str(idempotency_key)) if idempotency_key is not None else None
        with self._engine.begin() as conn:
            return self._append_all_events_on(
                conn, events, expected_version=expected_version, key=key
            )

    def complete_and_append(
        self,
        *,
        events: list[SemanticEvent],
        idempotency_key: str | uuid.UUID | None = None,
        side_effects: Any,
    ) -> CommitResult:
        """Append ``events`` and run ``side_effects(conn)`` in the SAME transaction.

        This is the durable stage-completion path: the caller supplies a
        ``side_effects`` callable that performs non-ledger writes on the same
        connection (e.g. ``UPDATE stage_run SET status/artifact_refs``). Everything
        commits atomically — a crash cannot commit the StageCompleted event without
        the authoritative stage artifact references, and vice versa.

        :param events: the semantic event(s) to append (anchored to ``events[0]``
            for the idempotency key, exactly like :meth:`append`).
        :param idempotency_key: idempotency key anchored to the first event.
        :param side_effects: ``side_effects(conn)`` executed within the same
            transaction. Its writes roll back with the append on failure.
        :return: the :class:`CommitResult` of the appended event(s).
        """
        key = uuid.UUID(str(idempotency_key)) if idempotency_key is not None else None
        with self._engine.begin() as conn:
            result = self._append_all_events_on(conn, events, expected_version=None, key=key)
            side_effects(conn)
            return result

    def _append_all_events_on(
        self,
        conn: sa.Connection,
        events: list[SemanticEvent],
        *,
        expected_version: int | None,
        key: uuid.UUID | None,
    ) -> CommitResult:
        """Transaction-body of :meth:`append` / :meth:`complete_and_append`.

        Runs on the caller-supplied ``conn`` (which owns the transaction). Keeps
        the shared single code path for validate/upcast, insert, idempotent dedup
        and Tier-0 folding so ``append`` (public) and ``complete_and_append``
        (durable stage completion) cannot drift. ``expected_version`` is checked
        only on the standalone public path.
        """
        if not events:
            raise LedgerError("append requires at least one event")

        # -- idempotency: a duplicate key returns the existing commit, never
        #    a second authoritative completion. -----------------------------
        if key is not None:
            existing = conn.execute(
                sa.select(_event_t.c.seq).where(_event_t.c.idempotency_key == key)
            ).scalar()
            if existing is not None:
                return CommitResult(int(existing), int(existing))

        # -- optimistic concurrency on the ledger tail ------------------
        if expected_version is not None:
            tail = conn.execute(sa.select(sa.func.max(_event_t.c.seq))).scalar()
            tail = int(tail) if tail is not None else 0
            if tail != expected_version:
                raise LedgerConflictError(f"ledger tail is {tail}, expected {expected_version}")

        # -- validate + upcast every event (construction path) ---------
        try:
            prepared = [ev.prepare() for ev in events]
        except EventSchemaError as exc:
            raise LedgerError(str(exc)) from exc

        # -- insert immutable event rows, capturing seqs ----------------
        seqs: list[int] = []
        for ev, pe in zip(events, prepared, strict=True):
            values = dict(
                event_type=pe.event_type,
                event_version=pe.event_version,
                schema_url=pe.schema_url,
                valid_time=pe.valid_time,
                authority=pe.authority,
                confidence=pe.confidence,
                generated_by=pe.generated_by,
                correlation_id=pe.correlation_id,
                causation_id=pe.causation_id,
                payload=pe.payload,
                created_by=pe.created_by,
            )
            if ev is events[0] and key is not None:
                # The idempotency key is anchored to the FIRST event. A
                # ``DO NOTHING`` conflict means another transaction already
                # committed this key; fall back to the pre-existing
                # authoritative seq instead of surfacing an IntegrityError.
                values["idempotency_key"] = key
                stmt = (
                    pg_insert(_event_t)
                    .values(**values)
                    .on_conflict_do_nothing()
                    .returning(_event_t.c.seq)
                )
            else:
                stmt = _event_t.insert().values(**values).returning(_event_t.c.seq)
            inserted = conn.execute(stmt)
            seq = inserted.scalar()
            if seq is None:
                # Lost the dedup race: return the existing commit (same seq),
                # never a duplicate authoritative completion.
                existing = conn.execute(
                    sa.select(_event_t.c.seq).where(_event_t.c.idempotency_key == key)
                ).scalar()
                if existing is None:  # pragma: no cover - defensive
                    raise LedgerError(f"idempotency key {key} conflicted but has no committed row")
                return CommitResult(int(existing), int(existing))
            seqs.append(int(seq))
        # The idempotency key is anchored to the FIRST event, so the initial
        # append and a duplicate-key dedup return the SAME authoritative seq
        # (a re-submission never gets a different token).
        first_seq = seqs[0]

        # -- Tier-0 reducer delta, committed in the SAME transaction ----.
        self._apply_tier0(conn, events, seqs)

        return CommitResult(seq=first_seq, read_your_writes_token=first_seq)

    # -- Tier-0 -----------------------------------------------------------

    def _apply_tier0(
        self,
        conn: sa.Connection,
        events: list[SemanticEvent],
        seqs: list[int],
    ) -> None:
        """Fold the append's semantic events through the reducer and persist delta.

        Bounded to indexed row operations: only lock-marker rows (indexed by the
        ``entity_ref`` PK prefix) and the specific ``(entity_ref, predicate)``
        target rows are loaded; all changes are upserted atomically.
        """
        semantic = [ev for ev, s in zip(events, seqs, strict=True) if ev.is_semantic]
        if not semantic:
            return
        state = self._load_affected_state(conn, semantic)

        # Fold via a copy carrying the assigned seq so reducer LWW uses the real,
        # authoritative ordering (the DB value overrides any caller placeholder)
        # WITHOUT mutating the caller's event objects (no hidden side effect).
        for ev, s in zip(events, seqs, strict=True):
            if not ev.is_semantic:
                continue
            self._reducer.reduce(state, ev.model_copy(update={"seq": s}))

        self._persist_delta(conn, state)

    def _load_affected_state(
        self, conn: sa.Connection, events: list[SemanticEvent]
    ) -> CurrentReducedState:
        from umd.storage.postgres.reducer import LOCK_PREDICATE, entity_ref_of, event_target

        state = CurrentReducedState()
        refs: set[str] = set()
        targets: set[tuple[str, str]] = set()
        for ev in events:
            ref = entity_ref_of(ev)
            if ref:
                refs.add(ref)
            tgt = event_target(ev)
            if tgt and tgt[1] != "*":
                targets.add(tgt)
        # Lock markers per involved entity (indexed prefix) -> lock map + rows.
        if refs:
            lock_rows = conn.execute(
                sa.select(_state_t).where(
                    (_state_t.c.entity_ref.in_(list(refs)))
                    & (_state_t.c.predicate == LOCK_PREDICATE)
                )
            ).fetchall()
            for r in lock_rows:
                row = _row_from_state(r)
                state.rows[(row.entity_ref, row.predicate)] = row
                state.locks[row.entity_ref] = row.state == "LOCKED"
        # Target rows (indexed PK).
        if targets:
            rows = conn.execute(
                sa.select(_state_t).where(
                    sa.tuple_(_state_t.c.entity_ref, _state_t.c.predicate).in_(list(targets))
                )
            ).fetchall()
            for r in rows:
                row = _row_from_state(r)
                state.rows[(row.entity_ref, row.predicate)] = row
        return state

    def _persist_delta(self, conn: sa.Connection, state: CurrentReducedState) -> None:
        from umd.storage.postgres.reducer import LOCK_PREDICATE

        for _key, row in state.rows.items():
            if row.predicate == LOCK_PREDICATE and row.state == STATE_UNLOCKED:
                # An unlocked marker is a no-op row; drop it (absence => unlocked).
                continue
            cols = row.scalar()
            stmt = sa.dialects.postgresql.insert(_state_t).values(**cols)
            stmt = stmt.on_conflict_do_update(
                constraint="pk_current_state_tier0",
                set_={
                    "object_ref": cols["object_ref"],
                    "confidence": cols["confidence"],
                    "authority": cols["authority"],
                    "state": cols["state"],
                    "seq": cols["seq"],
                },
            )
            conn.execute(stmt)


def _row_from_state(row: Any) -> Any:
    from umd.storage.postgres.reducer import CurrentStateRow

    return CurrentStateRow(
        entity_ref=row.entity_ref,
        predicate=row.predicate,
        object_ref=row.object_ref,
        confidence=row.confidence,
        authority=row.authority,
        state=row.state,
        seq=row.seq or 0,
        locked=row.state == "LOCKED",
    )
