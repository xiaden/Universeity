"""Active relationship-edge projection builder (Phase O, P2-S1..S3).

Rebuilds the ``active_semantic_edge`` store from the immutable semantic ledger — the
bounded ACTIVE multi-edge read side. Unlike the scalar ``current_state`` (single value
per ``(entity_ref, predicate)``), this projection retains *all* currently-active
relationship edges, including multiple distinct facts sharing ``(subject_ref,
predicate)`` with different objects (multi-edge).

Derivation from ledger events (P2-S2/S3):

  * ``SemanticAsserted`` — activates an edge keyed by its content-addressable
    ``fact_id`` (identical to ``semantic_assertion.id``); same fact re-asserted maps to
    the SAME row (LWW), distinct facts coexist as separate active edges.
  * ``OverrideApplied`` / ``CorrectionApplied`` — mirror the shared reducer's
    ``USER_OVERRIDE`` precedence: supersede the targeted active edge(s) for
    ``(subject_ref, predicate)`` (``active=false`` + ``superseded_by_seq``; history
    retained, never deleted) and activate the override edge. Corrections with
    ``prior_ref`` supersede exactly the targeted prior edge(s).
  * ``Invalidated`` — supersede the active edge(s) matching the invalidation target.
  * ``ContradictionRecorded`` — mark the affected active edge(s) ``CONFLICTING`` and
    attach the contradiction refs.
  * Lock precedence mirrors the reducer: while an entity is locked, machine
    ``SemanticAsserted`` (and override/correction) events never activate or supersede
    edges — they remain history only.

This is a disposable, single-writer, checkpointed wipe-and-replay projection: builders
are the ONLY writers to ``active_semantic_edge``, and no API/worker path writes it.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import sqlalchemy as sa

from umd.domain.events import latest_version
from umd.projections.base import ReplayDriver
from umd.projections.tables import active_semantic_edge as _edge_t
from umd.storage.postgres.ledger import _assertion_fact_id

pg_insert = sa.dialects.postgresql.insert

#: Projection name registered in app wiring + consistency/health seams.
EDGE_PROJECTION_NAME = "semantic_edges"

#: Event types that produce or mutate active edges.
_EDGE_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "SemanticAsserted",
        "OverrideApplied",
        "CorrectionApplied",
        "Invalidated",
        "ContradictionRecorded",
    }
)

_MACHINE_AUTHORITY = "machine"
_USER_AUTHORITY = "USER_OVERRIDE"
_EDGE_VERSION = "edge:v1"


def _override_fact_id(
    event_type: str, subject_ref: str, predicate: str, object_ref: str
) -> uuid.UUID:
    """Deterministic content-addressable id for a user-authority (override/correction) edge.

    Derived only from the stable semantic identity + the user-authority marker so a
    rerun applying the same override maps to the SAME row (idempotency +
    wipe-and-replay stability).
    """
    key = json.dumps(
        {
            "event_type": event_type,
            "authority": _USER_AUTHORITY,
            "subject_ref": subject_ref,
            "predicate": predicate,
            "object_ref": object_ref,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{_EDGE_VERSION}:{key}")


class ActiveSemanticEdgeProjectionBuilder:
    """Single-writer wipe-and-replay builder for the active relationship-edge store."""

    projection_name = EDGE_PROJECTION_NAME

    # This projection IS the canonical active-edge state (like current_tier1), so it
    # folds every semantic event and never pauses/skips on poison (authority events —
    # overrides/corrections/invalidations — are part of the active-edge derivation).
    poison_enabled = False

    # -- ProjectionBuilder protocol ---------------------------------------

    def prepare(self, conn: sa.Connection, driver: ReplayDriver) -> None:
        return None

    def wipe(self, conn: sa.Connection, driver: ReplayDriver) -> None:
        conn.execute(_edge_t.delete())

    def apply(self, conn: sa.Connection, driver: ReplayDriver, event: Any) -> None:
        etype = event.event_type
        if etype not in _EDGE_EVENT_TYPES:
            return
        seq = int(event.seq or 0)
        payload = event.payload or {}
        subj = payload.get("subject_ref")
        if etype == "SemanticAsserted":
            pred = payload.get("predicate_code")
            obj = payload.get("object_ref")
            if not pred or not subj:
                return
            if driver.state.locks.get(subj):
                return  # locked entity: machine assert never activates/supersedes
            fact_id = _assertion_fact_id(payload, latest_version("SemanticAsserted"))
            self._upsert(
                conn,
                fact_id=fact_id,
                event_type=etype,
                predicate=pred,
                subject_ref=subj,
                object_ref=obj,
                payload=payload,
                event=event,
                seq=seq,
                state=payload.get("state") or "UNKNOWN",
                authority=payload.get("authority") or event.authority or _MACHINE_AUTHORITY,
            )
        elif etype in ("OverrideApplied", "CorrectionApplied"):
            pred = payload.get("predicate")
            obj = payload.get("object_ref")
            if not pred or not subj:
                return
            if driver.state.locks.get(subj):
                return  # locked entity: no override/correction change
            prior_ref = payload.get("prior_ref") if etype == "CorrectionApplied" else None
            self._supersede(conn, subj, pred, seq, match=prior_ref)
            if obj is not None:
                self._upsert(
                    conn,
                    fact_id=_override_fact_id(etype, subj, pred, obj),
                    event_type=etype,
                    predicate=pred,
                    subject_ref=subj,
                    object_ref=obj,
                    payload=payload,
                    event=event,
                    seq=seq,
                    state="USER_CONFIRMED",
                    authority=_USER_AUTHORITY,
                )
        elif etype == "Invalidated":
            if subj:
                self._invalidate(conn, subj, payload.get("predicate"), payload.get("scope"), seq)
        elif etype == "ContradictionRecorded":
            pred = payload.get("predicate")
            if subj and pred:
                self._mark_conflicting(conn, subj, pred, seq, payload)

    def on_skip(self, conn: sa.Connection, driver: ReplayDriver, event: Any) -> None:
        return None

    def on_pause(self, conn: sa.Connection, driver: ReplayDriver, event: Any) -> None:
        return None

    def finalize(self, conn: sa.Connection, driver: ReplayDriver) -> None:
        # All edge writes happen in apply(); nothing extra to persist on finalize.
        return None

    # -- helpers -----------------------------------------------------------

    def _upsert(
        self,
        conn: sa.Connection,
        *,
        fact_id: uuid.UUID,
        event_type: str,
        predicate: str,
        subject_ref: str,
        object_ref: str | None,
        payload: dict[str, Any],
        event: Any,
        seq: int,
        state: str,
        authority: str,
    ) -> None:
        derivation = {
            "generated_by": payload.get("generated_by") or event.generated_by,
            "derived_from": payload.get("derived_from") or [],
            "source_seq": seq,
            "event_type": event_type,
            "source_refs": payload.get("support_refs") or [],
            "narrative_time": _normalize_narrative_time(payload.get("narrative_time")),
            "spatial": payload.get("spatial"),
        }
        values = {
            "fact_id": fact_id,
            "event_type": event_type,
            "predicate": predicate,
            "subject_ref": subject_ref,
            "object_ref": object_ref,
            "authority": authority,
            "confidence": payload.get("confidence")
            if payload.get("confidence") is not None
            else event.confidence,
            "state": state,
            "scope": payload.get("scope") or "GLOBAL",
            "support_refs": payload.get("support_refs") or [],
            "contradiction_refs": payload.get("contradiction_refs") or [],
            "derivation": derivation,
            "active": True,
            "superseded_by_seq": None,
            "superseded_by_fact": None,
            "ledger_seq": seq,
        }
        stmt = pg_insert(_edge_t).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="pk_active_semantic_edge",
            set_={
                "event_type": event_type,
                "predicate": predicate,
                "subject_ref": subject_ref,
                "object_ref": object_ref,
                "authority": authority,
                "confidence": values["confidence"],
                "state": state,
                "scope": values["scope"],
                "support_refs": values["support_refs"],
                "contradiction_refs": values["contradiction_refs"],
                "derivation": derivation,
                "active": True,
                "superseded_by_seq": None,
                "superseded_by_fact": None,
                "ledger_seq": seq,
            },
        )
        conn.execute(stmt)

    def _supersede(
        self, conn: sa.Connection, subj: str, pred: str, seq: int, match: Any = None
    ) -> None:
        conds = [
            _edge_t.c.subject_ref == subj,
            _edge_t.c.predicate == pred,
            _edge_t.c.active.is_(sa.true()),
        ]
        if match:
            # Correction prior_ref may be the prior object value OR the prior fact id.
            conds.append(
                sa.or_(
                    _edge_t.c.object_ref == match,
                    sa.cast(_edge_t.c.fact_id, sa.String) == str(match),
                )
            )
        self._deactivate(conn, conds, seq)

    def _invalidate(self, conn: sa.Connection, subj: str, pred: Any, scope: Any, seq: int) -> None:
        conds = [_edge_t.c.subject_ref == subj, _edge_t.c.active.is_(sa.true())]
        if pred:
            conds.append(_edge_t.c.predicate == pred)
        if scope:
            conds.append(_edge_t.c.scope == scope)
        self._deactivate(conn, conds, seq)

    def _deactivate(self, conn: sa.Connection, conds: list[Any], seq: int) -> None:
        conn.execute(
            _edge_t.update()
            .where(*conds)
            .values(active=False, superseded_by_seq=seq, ledger_seq=seq)
        )

    def _mark_conflicting(
        self, conn: sa.Connection, subj: str, pred: str, seq: int, payload: dict[str, Any]
    ) -> None:
        rows = conn.execute(
            sa.select(_edge_t.c.fact_id, _edge_t.c.contradiction_refs).where(
                _edge_t.c.subject_ref == subj,
                _edge_t.c.predicate == pred,
                _edge_t.c.active.is_(sa.true()),
            )
        ).fetchall()
        for r in rows:
            existing = list(r.contradiction_refs or [])
            merged: list[str] = []
            seen: set[str] = set()
            for ref in existing:
                if ref not in seen:
                    seen.add(ref)
                    merged.append(ref)
            for ref in payload.get("refs") or []:
                if ref not in seen:
                    seen.add(ref)
                    merged.append(ref)
            contradicting = payload.get("contradicting_ref")
            if contradicting is not None and contradicting not in seen:
                seen.add(contradicting)
                merged.append(contradicting)
            conn.execute(
                _edge_t.update()
                .where(_edge_t.c.fact_id == r.fact_id)
                .values(
                    contradiction_refs=[v for v in merged if v is not None],
                    state="CONFLICTING",
                    ledger_seq=seq,
                )
            )


def _normalize_narrative_time(value: Any) -> Any:
    """Return ``value`` unchanged if a mapping, else wrap scalars for queryable scope."""
    if isinstance(value, dict):
        return value
    if value is None:
        return None
    return {"from": value, "to": value}


__all__ = ["ActiveSemanticEdgeProjectionBuilder", "EDGE_PROJECTION_NAME"]
