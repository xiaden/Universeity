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

import json
import uuid
from typing import Any

import sqlalchemy as sa

from umd.domain.events import EventSchemaError, EventType, SemanticEvent
from umd.domain.models import PREDICATE_VOCABULARY
from umd.storage.postgres.reducer import (
    LOCK_PREDICATE,
    STATE_LOCKED,
    STATE_UNLOCKED,
    USER_OVERRIDE,
    CurrentReducedState,
    CurrentStateReducer,
)
from umd.storage.postgres.tables import metadata as db_meta

_event_t = db_meta.tables["semantic_event"]
_state_t = db_meta.tables["current_state"]
_assertion_t = db_meta.tables["semantic_assertion"]
_pred_t = db_meta.tables["predicate"]

#: PostgreSQL-dialect insert so ``on_conflict_do_nothing`` type-checks cleanly.
pg_insert = sa.dialects.postgresql.insert


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    """Coerce a payload ref to a UUID FK value, or None when it is not UUID-shaped.

    The reconciler/observation refs are deterministic STRINGS (canonical refs,
    segment locators), never entity-table UUIDs, so ``subject_entity_id`` /
    ``object_entity_id`` / ``continuity_id`` stay NULL for those; a UUID-shaped
    value is honored when a caller supplies one.
    """
    if value is None or value == "":
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _assertion_fact_id(payload: dict[str, Any], event_version: int) -> uuid.UUID:
    """Deterministic content-addressable id for one semantic fact.

    Derived ONLY from the stable semantic identity (predicate, subject/object
    refs + entity ids, scope) — never from random evidence ids or seqs — so a
    rerun asserting the same fact maps to the SAME row (idempotency +
    wipe-and-replay stability). Distinct facts map to distinct ids.
    """
    key = json.dumps(
        {
            "predicate_code": payload.get("predicate_code"),
            "subject_ref": payload.get("subject_ref"),
            "object_ref": payload.get("object_ref"),
            "subject_entity_id": str(payload["subject_entity_id"])
            if payload.get("subject_entity_id")
            else None,
            "object_entity_id": str(payload["object_entity_id"])
            if payload.get("object_entity_id")
            else None,
            "scope": payload.get("scope"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{event_version}:{key}")


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

        # -- materialize SemanticAsserted events into the read-side
        #    semantic_assertion table, in the SAME transaction (P1-S3). ----
        self._materialize_assertions(conn, prepared, seqs)

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

    def _materialize_assertions(
        self,
        conn: sa.Connection,
        prepared: list[Any],
        seqs: list[int],
    ) -> None:
        """Materialize every ``SemanticAsserted`` event into ``semantic_assertion``.

        Runs inside the SAME transaction as the event append (P1-S3) so a crash
        can never commit an event without its read-side mirror (and vice versa).
        Each distinct semantic fact (predicate + subject/object refs + scope) gets
        ONE deterministic row: the id is content-addressed so retries/reruns never
        duplicate and wipe-and-replay is stable, and ``on_conflict_do_update``
        keeps the row reflecting the latest assertion for that fact.

        The FK-safe ``predicate`` row is seeded idempotently from the registered
        vocabulary (data, not a migration) so materialization never invents a
        predicate. Provenance that has no dedicated column (``generated_by``,
        ``scope``, ``derived_from``) is preserved in the ``derivation`` JSONB;
        ``support_refs``/``contradiction_refs`` stay as their own source-evidence
        columns, distinct from machine interpretation.

        Precedence guards (P4-S3): the mirror must never let a machine reassertion
        downgrade a ``USER_OVERRIDE`` mirror row or write a locked entity. The lock
        markers are read from the Tier-0 ``current_state`` (already folded in this
        transaction) so a locked entity's machine assertions never materialize, and a
        ``USER_OVERRIDE`` row with the same deterministic fact identity is preserved.
        """
        # First pass: collect the subject refs to check for entity locks.
        subject_refs: set[str] = set()
        for pe, _s in zip(prepared, seqs, strict=True):
            if pe.event_type != EventType.SEMANTIC_ASSERTED.value:
                continue
            sr = pe.payload.get("subject_ref")
            if sr:
                subject_refs.add(sr)
        locked_entities: set[str] = set()
        if subject_refs:
            locked_entities = set(
                conn.execute(
                    sa.select(_state_t.c.entity_ref).where(
                        _state_t.c.predicate == LOCK_PREDICATE,
                        _state_t.c.state == STATE_LOCKED,
                        _state_t.c.entity_ref.in_(tuple(subject_refs)),
                    )
                ).scalars()
            )

        for pe, s in zip(prepared, seqs, strict=True):
            if pe.event_type != EventType.SEMANTIC_ASSERTED.value:
                continue
            payload = pe.payload
            code = payload.get("predicate_code")
            if not code:
                continue
            description = PREDICATE_VOCABULARY.get(code) or code
            conn.execute(
                pg_insert(_pred_t)
                .values(code=code, description=description)
                .on_conflict_do_nothing(index_elements=["code"])
            )
            fact_id = _assertion_fact_id(payload, pe.event_version)
            # P4-S3: a locked entity's machine assertion never materializes to the mirror
            # (mirrors the reducer + edge-builder lock guard).
            if payload.get("subject_ref") in locked_entities:
                continue
            # P4-S3: a machine reassertion must never downgrade an existing USER_OVERRIDE
            # mirror row with the same deterministic fact identity.
            existing_authority = conn.execute(
                sa.select(_assertion_t.c.authority).where(_assertion_t.c.id == fact_id)
            ).scalar()
            incoming_authority = payload.get("authority") or pe.authority
            if existing_authority == USER_OVERRIDE and incoming_authority != USER_OVERRIDE:
                continue
            values: dict[str, Any] = {
                "id": fact_id,
                "predicate_code": code,
                "subject_ref": payload.get("subject_ref"),
                "object_ref": payload.get("object_ref"),
                "subject_entity_id": _uuid_or_none(payload.get("subject_entity_id")),
                "object_entity_id": _uuid_or_none(payload.get("object_entity_id")),
                "authority": payload.get("authority") or pe.authority,
                "confidence": (
                    payload.get("confidence")
                    if payload.get("confidence") is not None
                    else pe.confidence
                ),
                "state": payload.get("state") or "UNKNOWN",
                "continuity_id": _uuid_or_none(payload.get("continuity_id")),
                "valid_time": pe.valid_time,
                "support_refs": payload.get("support_refs") or [],
                "contradiction_refs": payload.get("contradiction_refs") or [],
                "schema_ref": pe.schema_url,
                "derivation": {
                    "generated_by": pe.generated_by or {},
                    "scope": payload.get("scope"),
                    "derived_from": payload.get("derived_from") or [],
                    "source_seq": int(s),
                },
            }
            set_ = {k: v for k, v in values.items() if k != "id"}
            conn.execute(
                pg_insert(_assertion_t)
                .values(**values)
                .on_conflict_do_update(index_elements=["id"], set_=set_)
            )

    def _load_affected_state(
        self, conn: sa.Connection, events: list[SemanticEvent]
    ) -> CurrentReducedState:
        from umd.storage.postgres.reducer import (
            LOCK_PREDICATE,
            entity_ref_of,
            event_target,
            identity_event_target,
        )

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
            # Plan S (P1-S4): load the durable canonical-identity metadata row so
            # the inline Tier-0 fold merges (LWW) rather than clobbering it.
            idtgt = identity_event_target(ev)
            if idtgt:
                targets.add(idtgt)
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
