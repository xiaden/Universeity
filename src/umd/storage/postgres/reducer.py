"""Pure, total, deterministic Tier-0 current-state reducer (P3-S2).

Implements the binding contract ``reduce_current_state(current_row, event) ->
current_row`` and a fold (:meth:`CurrentStateReducer.replay`) that serves both
the inline Tier-0 update (same transaction as the event append) and
wipe-and-replay tests.

The reducer is I/O-free, *total* (handles every event type, never raises on an
unknown type), *deterministic* (a pure function of ``(row, event)``), and
*bounded* to indexed ``(entity_ref, predicate)`` row operations.

Semantics (from CONTRACTS.md / the DD):
  * winner = **last-write-wins** per ``(entity_ref, predicate)`` after
    authority/lock rules;
  * **authority precedence**: ``USER_OVERRIDE`` always beats machine inference —
    a machine event can never overwrite a ``USER_OVERRIDE`` winner;
  * **locks prevent changes**: a ``Locked`` event pins an entity; change events
    are no-ops while locked (``Unlocked`` releases);
  * numeric ``confidence`` is preserved so indexed threshold queries work;
  * **candidate / contradiction / alternative state**: a superseded winner moves
    into ``alternatives``; ``ContradictionRecorded`` sets ``state=CONFLICTING``
    and records the contradicting ref; entity resolution writes candidate /
    canonical-entity pseudo-rows.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from umd.domain.events import SemanticEvent

#: Authority value that always beats machine inference (see domain authority).
USER_OVERRIDE = "USER_OVERRIDE"

#: Confidence states the reducer may emit on a Tier-0 row.
STATE_UNKNOWN = "UNKNOWN"
STATE_AMBIGUOUS = "AMBIGUOUS"
STATE_CONFLICTING = "CONFLICTING"
STATE_PROBABLE = "PROBABLE"
STATE_CONFIRMED = "CONFIRMED"
STATE_USER_CONFIRMED = "USER_CONFIRMED"
STATE_INVALIDATED = "INVALIDATED"

#: Pseudo-predicate under which lock state is persisted as a Tier-0 row so that
#: lock state is queryable, recoverable by wipe-and-replay, and read via an index
#: prefix (entity_ref) by the inline append transaction.
LOCK_PREDICATE = "*LOCK*"
STATE_LOCKED = "LOCKED"
STATE_UNLOCKED = "UNLOCKED"

#: Pseudo-predicate under which a canonical entity's durable identity metadata
#: (type, display label, aliases, support refs, memberships, state, confidence)
#: is folded as a Tier-0 row (Plan S P1-S3/P1-S4). Persisted like any scalar row,
#: so it is queryable and reconstructable by wipe-and-replay.
CANONICAL_IDENTITY_PREDICATE = "CANONICAL_IDENTITY"


class CurrentStateRow(BaseModel):
    """The Tier-0 ``current_state`` row for one ``(entity_ref, predicate)``.

    Scalar fields map 1:1 onto the ``current_state`` table columns and are the
    only persisted part (see :meth:`scalar`). ``locked``, ``alternatives`` and
    ``contradiction_refs`` are reducer-only auxiliary state consumed by replay /
    Tier-1 builders, not stored in the inline scalar row.
    """

    entity_ref: str
    predicate: str
    object_ref: str | None = None
    confidence: float | None = None
    authority: str | None = None
    state: str = STATE_UNKNOWN
    seq: int = 0
    locked: bool = False
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    contradiction_refs: list[str] = Field(default_factory=list)

    def scalar(self) -> dict[str, Any]:
        """The subset persisted to the ``current_state`` table columns."""
        return {
            "entity_ref": self.entity_ref,
            "predicate": self.predicate,
            "object_ref": self.object_ref,
            "confidence": self.confidence,
            "authority": self.authority,
            "state": self.state,
            "seq": self.seq,
        }


class CurrentReducedState(BaseModel):
    """Full reduced Tier-0 state: all rows + per-entity lock state.

    This is the shape produced by :meth:`CurrentStateReducer.replay` from an
    empty state (wipe-and-replay) and consumed by the inline append transaction.
    """

    rows: dict[tuple[str, str], CurrentStateRow] = Field(default_factory=dict)
    locks: dict[str, bool] = Field(default_factory=dict)

    def row(self, entity_ref: str, predicate: str) -> CurrentStateRow:
        row = self.rows.get((entity_ref, predicate))
        if row is None:
            row = CurrentStateRow(entity_ref=entity_ref, predicate=predicate)
            self.rows[(entity_ref, predicate)] = row
        return row

    def snapshot(self) -> list[CurrentStateRow]:
        return list(self.rows.values())


# ---------------------------------------------------------------------------
# Event -> target key resolution
# ---------------------------------------------------------------------------


def entity_ref_of(event: SemanticEvent) -> str | None:
    """The subject/entity reference an event addresses, if any."""
    p = event.payload
    for key in ("subject_ref", "entity_ref", "source_id"):
        val = p.get(key)
        if val:
            return str(val)
    for key in ("subject_entity_id", "entity_id"):
        val = p.get(key)
        if val:
            return str(val)
    return None


def event_target(event: SemanticEvent) -> tuple[str, str] | None:
    """The ``(entity_ref, predicate)`` Tier-0 row an event updates, or ``None``.

    ``None`` means the event does not reduce a ``current_state`` row (e.g. pure
    provenance/projection events and ``JobRunAudit``, which is excluded from
    semantic replay). Locks are entity-scoped, so ``Locked``/``Unlocked`` match by
    entity and the predicate is the row's own predicate.
    """
    etype = event.event_type
    if etype in NON_SEMANTIC:
        return None
    ref = entity_ref_of(event)
    if ref is None:
        return None
    if etype in ("Locked", "Unlocked"):
        return (ref, "*")  # matched by entity; predicate overridden per row
    predicate = event.payload.get("predicate") or event.payload.get("predicate_code")
    if predicate is None:
        # Entity resolution / candidate pseudo-rows.
        if etype == "EntityResolved":
            return (ref, "CANONICAL_ENTITY")
        if etype == "EntityMentioned":
            return (ref, "CANDIDATE")
        return None
    return (ref, str(predicate))


#: Event types excluded from semantic Tier-0 replay (auditable records only).
NON_SEMANTIC = frozenset(
    {
        "JobRunAudit",
        "SourceIngested",
        "SourceAliased",
        "FormatAnalyzed",
        "SegmentCreated",
        "StageCompleted",
        "ReferenceRebound",
        "Aligned",
        "LocatorRebased",
        "HallucinationFiltered",
    }
)

#: Event types that are change events subject to authority/lock rules.
_CHANGE_EVENTS = frozenset(
    {
        "SemanticAsserted",
        "OverrideApplied",
        "CorrectionApplied",
        "ContradictionRecorded",
        "Invalidated",
        "EntityResolved",
        "EntityMentioned",
    }
)


def _targets_row(row: CurrentStateRow, event: SemanticEvent) -> bool:
    target = event_target(event)
    if target is None:
        return False
    ref, predicate = target
    if ref != row.entity_ref:
        return False
    if predicate == "*":
        return True  # entity-scoped lock/unlock applies to every row of the entity
    return predicate == row.predicate


# ---------------------------------------------------------------------------
# The contract function
# ---------------------------------------------------------------------------


def reduce_current_state(
    current_row: CurrentStateRow | None, event: SemanticEvent
) -> CurrentStateRow:
    """Apply one event to one current_state row (pure, total, deterministic).

    ``current_row`` may be ``None`` (the key has no row yet) — the function always
    returns a concrete row (an empty/anonymous row for a non-matching event).

    Lock / unlock are matched by entity and applied to the row; all other change
    events are subject to authority precedence and LWW ordering.
    """
    if current_row is None:
        current_row = CurrentStateRow(entity_ref="", predicate="")

    if event.event_type == "Locked":
        if _targets_row(current_row, event):
            return current_row.model_copy(update={"locked": True})
        return current_row
    if event.event_type == "Unlocked":
        if _targets_row(current_row, event):
            return current_row.model_copy(update={"locked": False})
        return current_row

    # Authority/lock guard: a locked row rejects any change event.
    if current_row.locked:
        return current_row

    if event.event_type not in _CHANGE_EVENTS:
        return current_row
    if not _targets_row(current_row, event):
        return current_row

    return _apply_change(current_row, event)


def _apply_change(row: CurrentStateRow, event: SemanticEvent) -> CurrentStateRow:
    etype = event.event_type
    event_seq = event.seq if event.seq is not None else row.seq + 1

    # --- USER_OVERRIDE beats machine inference, always. ---
    if etype in ("OverrideApplied", "CorrectionApplied"):
        return _override_winner(row, event, event_seq)

    # --- machine infer|auditable events: authority precedence + LWW ---
    if row.authority == USER_OVERRIDE and (event.authority or "machine") != USER_OVERRIDE:
        # A machine event must never overwrite a confirmed user override.
        return row
    if event_seq < row.seq:
        return row  # out-of-order / stale event loses LWW
    if event_seq == row.seq:
        return row  # same event replayed -> no-op

    if etype == "ContradictionRecorded":
        return _contradiction(row, event, event_seq)
    if etype == "Invalidated":
        return row.model_copy(
            update={
                "state": STATE_INVALIDATED,
                "seq": event_seq,
                "authority": event.authority or row.authority,
            }
        )
    if etype == "EntityResolved":
        return _entity_resolved(row, event, event_seq)
    if etype == "EntityMentioned":
        return _candidate(row, event, event_seq)
    # SemanticAsserted (machine inference)
    return _assertion(row, event, event_seq)


def _override_winner(row: CurrentStateRow, event: SemanticEvent, seq: int) -> CurrentStateRow:
    payload = event.payload
    new_value = payload.get("object_ref")
    return row.model_copy(
        update={
            "object_ref": _or_ref(new_value),
            "confidence": payload.get("confidence", row.confidence),
            "authority": USER_OVERRIDE,
            "state": STATE_USER_CONFIRMED,
            "seq": seq,
            "locked": row.locked,
        }
    )


def _assertion(row: CurrentStateRow, event: SemanticEvent, seq: int) -> CurrentStateRow:
    payload = event.payload
    new_value = payload.get("object_ref") or payload.get("object_entity_id")
    alternatives = list(row.alternatives)
    if new_value is not None and new_value != row.object_ref and row.object_ref is not None:
        alternatives.append(
            {
                "object_ref": row.object_ref,
                "authority": row.authority,
                "state": row.state,
                "confidence": row.confidence,
                "seq": row.seq,
            }
        )
    return row.model_copy(
        update={
            "object_ref": _or_ref(new_value),
            "confidence": (
                payload.get("confidence")
                if payload.get("confidence") is not None
                else row.confidence
            ),
            "authority": event.authority or payload.get("authority") or row.authority,
            "state": payload.get("state") or row.state,
            "seq": seq,
            "alternatives": alternatives,
            "locked": row.locked,
        }
    )


def _contradiction(row: CurrentStateRow, event: SemanticEvent, seq: int) -> CurrentStateRow:
    payload = event.payload
    refs = list(row.contradiction_refs)
    contrad = payload.get("contradicting_ref") or payload.get("refs") or []
    if isinstance(contrad, str):
        refs.append(contrad)
    elif isinstance(contrad, list):
        refs.extend(str(r) for r in contrad)
    return row.model_copy(
        update={
            "state": STATE_CONFLICTING,
            "seq": seq,
            "contradiction_refs": refs,
            "authority": event.authority or row.authority,
            "locked": row.locked,
        }
    )


def _entity_resolved(row: CurrentStateRow, event: SemanticEvent, seq: int) -> CurrentStateRow:
    payload = event.payload
    kind = payload.get("kind", "ALIAS")
    target = payload.get("target_entity_id") or payload.get("entity_id")
    state = payload.get("state") or (
        STATE_CONFIRMED if kind in ("ALIAS", "ESTABLISH") else STATE_PROBABLE
    )
    conf = payload.get("confidence")
    return _assertion(
        row.model_copy(update={"authority": None}),
        SemanticEvent(
            event_type="SemanticAsserted",
            payload={
                "predicate_code": "CANONICAL_ENTITY",
                "subject_ref": str(payload.get("entity_id", "")),
                "object_ref": str(target) if target else None,
                "authority": event.authority,
                "confidence": conf,
                "state": state,
            },
            authority=event.authority,
            seq=seq,
        ),
        seq,
    )


def identity_event_target(event: SemanticEvent) -> tuple[str, str] | None:
    """The ``(canonical_ref, CANONICAL_IDENTITY)`` row an event establishes or
    corrects, or ``None`` if the event carries no canonical-identity metadata.

    Canonical-identity events address the canonical entity itself, not an alias:
      * ``EntityResolved`` kind ``ESTABLISH``/``UPDATE`` (creation / correction)
        — ``entity_id`` IS the canonical ref;
      * ``OverrideApplied``/``CorrectionApplied``/``Invalidated`` that explicitly
        carry ``predicate == CANONICAL_IDENTITY`` (human override / invalidation).
    Plain ``MERGE``/``SPLIT``/``ALIAS`` events address alias/candidate mentions
    and do not rewrite the canonical's identity.
    """
    if event.event_type == "EntityResolved" and event.payload.get("kind") in (
        "ESTABLISH",
        "UPDATE",
    ):
        ref = event.payload.get("entity_id")
    elif event.event_type in ("OverrideApplied", "CorrectionApplied", "Invalidated"):
        if event.payload.get("predicate") != CANONICAL_IDENTITY_PREDICATE:
            return None
        ref = entity_ref_of(event)
    else:
        return None
    if not ref:
        return None
    return (str(ref), CANONICAL_IDENTITY_PREDICATE)


def _identity_metadata(event: SemanticEvent) -> dict[str, Any]:
    """The canonical-identity metadata dict an event carries.

    For an override/correction the corrected metadata may arrive as a JSON blob in
    ``object_ref`` (parsed if valid JSON); otherwise it is assembled from the
    additive payload fields. Only the latest non-invalidated/non-corrected values
    are exposed active; prior values stay immutable in the event stream.
    """
    payload = event.payload
    if event.event_type in ("OverrideApplied", "CorrectionApplied") and payload.get("object_ref"):
        raw = str(payload.get("object_ref"))
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    kind = payload.get("kind")
    return {
        "canonical_type": payload.get("canonical_type"),
        "display_label": payload.get("display_label"),
        "aliases": list(payload.get("aliases") or []),
        "support_refs": list(payload.get("support_refs") or []),
        "memberships": dict(payload.get("memberships") or {}),
        "state": payload.get("state") or (STATE_CONFIRMED if kind == "ESTABLISH" else None),
        "confidence": payload.get("confidence"),
        "classification": payload.get("classification"),
    }


def _empty_memberships() -> dict[str, list[str]]:
    return {"source_ids": [], "work_ids": [], "continuity_ids": []}


def _memberships_of(row: CurrentStateRow) -> dict[str, list[str]]:
    """Parse the memberships carried on a row's active metadata (or empty)."""
    if not row.object_ref:
        return _empty_memberships()
    try:
        parsed = json.loads(row.object_ref)
    except (TypeError, ValueError):
        return _empty_memberships()
    if not isinstance(parsed, dict):
        return _empty_memberships()
    memberships = parsed.get("memberships")
    if isinstance(memberships, dict):
        return {
            str(k): [str(x) for x in (v if isinstance(v, list) else [])]
            for k, v in memberships.items()
        }
    return _empty_memberships()


def _union_memberships(
    prev: dict[str, list[str]], incoming: dict[str, list[str]]
) -> dict[str, list[str]]:
    """Deterministically union two membership dicts, per sub-list, deduped.

    Plan S (P3-S1/S2): membership is CUMULATIVE across the sources that feed a
    canonical identity — re-establishing a canonical from a second source of the
    same work accumulates that source (and never drops a prior one). Order is
    ``prev`` then ``incoming``, deduplicated, so replay is deterministic.
    """
    out: dict[str, list[str]] = {}
    for key in sorted(set(prev) | set(incoming)):
        seen: list[str] = []
        for item in list(prev.get(key) or []) + list(incoming.get(key) or []):
            if item not in seen:
                seen.append(item)
        out[key] = seen
    return out


def _reduce_canonical_identity(row: CurrentStateRow, event: SemanticEvent) -> CurrentStateRow:
    """Fold a canonical-identity establishment/correction/override/invalidation.

    Pure, total, deterministic: honours USER_OVERRIDE precedence, lock state,
    and last-write-wins ordering; invalidation marks the identity inactive. The
    prior active metadata is retained in ``alternatives`` (reducer auxiliary) and
    remains immutable in the event stream.
    """
    etype = event.event_type
    seq = event.seq if event.seq is not None else row.seq + 1
    if etype == "Invalidated":
        if row.authority == USER_OVERRIDE and (event.authority or "machine") != USER_OVERRIDE:
            return row
        if seq < row.seq:
            return row
        if seq == row.seq:
            return row
        return row.model_copy(
            update={
                "state": STATE_INVALIDATED,
                "seq": seq,
                "authority": event.authority or row.authority,
                "locked": row.locked,
            }
        )

    # USER_OVERRIDE beats machine inference, always.
    if row.authority == USER_OVERRIDE and (event.authority or "machine") != USER_OVERRIDE:
        return row
    if seq < row.seq:
        return row
    if seq == row.seq:
        return row

    metadata = _identity_metadata(event)
    if metadata.get("memberships"):
        metadata["memberships"] = _union_memberships(_memberships_of(row), metadata["memberships"])
    alternatives = list(row.alternatives)
    if row.object_ref and row.object_ref != json.dumps(metadata, sort_keys=True):
        alternatives.append(
            {
                "object_ref": row.object_ref,
                "authority": row.authority,
                "state": row.state,
                "confidence": row.confidence,
                "seq": row.seq,
            }
        )
    return row.model_copy(
        update={
            "object_ref": json.dumps(metadata, sort_keys=True),
            "confidence": (payload_conf(event, row)),
            "authority": (
                USER_OVERRIDE
                if event.authority == USER_OVERRIDE
                else event.authority or row.authority
            ),
            "state": (
                STATE_USER_CONFIRMED
                if event.authority == USER_OVERRIDE
                else metadata.get("state") or row.state or STATE_CONFIRMED
            ),
            "seq": seq,
            "alternatives": alternatives,
            "locked": row.locked,
        }
    )


def payload_conf(event: SemanticEvent, row: CurrentStateRow) -> float | None:
    p = event.payload.get("confidence")
    if p is not None:
        return float(p)
    if event.confidence is not None:
        return event.confidence
    return row.confidence


def _candidate(row: CurrentStateRow, event: SemanticEvent, seq: int) -> CurrentStateRow:
    payload = event.payload
    alternatives = list(row.alternatives)
    alternatives.append(
        {
            "mention": payload.get("mention_text")
            or payload.get("mention_id")
            or str(payload.get("source_id", "")),
        }
    )
    return row.model_copy(
        update={
            "state": STATE_AMBIGUOUS,
            "seq": seq,
            "authority": event.authority or row.authority,
            "alternatives": alternatives,
            "locked": row.locked,
        }
    )


def _or_ref(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


# ---------------------------------------------------------------------------
# Replay / fold
# ---------------------------------------------------------------------------


class CurrentStateReducer:
    """Folds events into Tier-0 state, tracking per-entity locks.

    ``replay`` is deterministic and I/O-free: given any ordered event stream it
    produces the identical :class:`CurrentReducedState` (used for wipe-and-replay).
    """

    def reduce(self, state: CurrentReducedState, event: SemanticEvent) -> CurrentReducedState:
        """Fold one ``event`` into ``state``, returning the updated state.

        Pure, total, deterministic, I/O-free: applies authority/lock precedence,
        last-write-wins per ``(entity_ref, predicate)`` using ``event.seq`` when
        set, lock-pin/unpin, contradiction/alternative state, and invalidation.
        Rows are replaced immutably (``model_copy``); the ``state`` container is
        updated in place and returned.

        :param state: the current reduced state to fold into.
        :param event: the semantic event to apply.
        :return: ``state`` updated to reflect the folded event.
        """
        etype = event.event_type

        # Locks are entity-scoped: update the lock map and pin/unpin every row of
        # the entity (so inline ``current_row`` reads see the right lock state),
        # and persist a ``*LOCK*`` marker row under the entity so lock state is
        # queryable, indexed by entity, and recoverable by wipe-and-replay.
        if etype in ("Locked", "Unlocked"):
            ref = entity_ref_of(event)
            if ref is not None:
                locked = etype == "Locked"
                state.locks[ref] = locked
                for key in list(state.rows):
                    if key[0] == ref:
                        row = state.rows[key]
                        state.rows[key] = row.model_copy(update={"locked": locked})
                marker = state.row(ref, LOCK_PREDICATE)
                state.rows[(ref, LOCK_PREDICATE)] = marker.model_copy(
                    update={
                        "state": STATE_LOCKED if locked else STATE_UNLOCKED,
                        "object_ref": None,
                        "seq": event.seq or marker.seq,
                        "locked": locked,
                    }
                )
            return state

        target = event_target(event)
        if target is None or target[1] == "*":
            # Not a Tier-0 change (auditable/provenance event) -> no-op.
            return state

        # Locks prevent changes for any row of a locked entity.
        if state.locks.get(target[0]):
            return state

        current = state.rows.get(target)
        if current is None:
            # Seed an empty row with its own key so ``reduce_current_state`` can
            # match ``_targets_row`` and apply the change to a brand-new row.
            current = CurrentStateRow(entity_ref=target[0], predicate=target[1])
        updated = reduce_current_state(current, event)
        state.rows[target] = updated

        # Plan S (P1-S4): a canonical establishment/correction also reduces the
        # durable identity metadata row (same lock/authority/LWW rules).
        identity_target = identity_event_target(event)
        if identity_target is not None:
            if state.locks.get(identity_target[0]):
                return state
            identity_row = state.rows.get(identity_target)
            if identity_row is None:
                identity_row = CurrentStateRow(
                    entity_ref=identity_target[0], predicate=identity_target[1]
                )
            state.rows[identity_target] = _reduce_canonical_identity(identity_row, event)
        return state

    def replay(self, events: list[SemanticEvent]) -> CurrentReducedState:
        state = CurrentReducedState()
        for event in events:
            self.reduce(state, event)
        return state
