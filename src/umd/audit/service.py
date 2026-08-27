"""Audit explanations: why/current/prior/change cause (P3-S3).

Implements the binding contract
``AuditService.explain(subject, as_of, causation, correlation) -> ChangeExplanation``.

Wholly derived from the append-only semantic ledger and its Tier-0 projection —
nothing here is a projection writer and nothing mutates state. ``current`` is the
reduced Tier-0 value; ``prior`` is what the value was before the most recent
change for the subject; ``actor``/``evidence``/``generated_by``/``change_cause``
come from the latest relevant event and its causation chain.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa

from umd.domain.events import SemanticEvent
from umd.storage.postgres.reducer import CurrentStateReducer
from umd.storage.postgres.tables import metadata as db_meta

_event_t = db_meta.tables["semantic_event"]
_state_t = db_meta.tables["current_state"]


class ChangeExplanation:
    """Human- and machine-readable explanation of a subject's current/prior state."""

    __slots__ = (
        "subject",
        "predicate",
        "as_of",
        "current",
        "prior",
        "actor",
        "evidence",
        "generated_by",
        "change_cause",
        "history",
    )

    def __init__(
        self,
        *,
        subject: str,
        predicate: str | None,
        as_of: datetime | None,
        current: dict[str, Any] | None,
        prior: dict[str, Any] | None,
        actor: str | None,
        evidence: list[str],
        generated_by: dict[str, Any],
        change_cause: dict[str, Any] | None,
        history: list[dict[str, Any]],
    ) -> None:
        self.subject = subject
        self.predicate = predicate
        self.as_of = as_of
        self.current = current
        self.prior = prior
        self.actor = actor
        self.evidence = evidence
        self.generated_by = generated_by
        self.change_cause = change_cause
        self.history = history

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "current": self.current,
            "prior": self.prior,
            "actor": self.actor,
            "evidence": self.evidence,
            "generated_by": self.generated_by,
            "change_cause": self.change_cause,
            "history": self.history,
        }

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"ChangeExplanation(subject={self.subject!r}, current={self.current})"


class AuditService:
    """Query-only explanations over the ledger + Tier-0 (never writes)."""

    def __init__(self, engine: sa.Engine, reducer: CurrentStateReducer | None = None) -> None:
        self._engine = engine
        self._reducer = reducer or CurrentStateReducer()

    def explain(
        self,
        subject: str,
        as_of: datetime | None = None,
        causation: int | None = None,
        correlation: Any | None = None,
    ) -> ChangeExplanation:
        """Explain the change history for ``subject`` (optionally ``predicate``).

        Query-only over the ledger + Tier-0 (never writes). ``subject`` may be
        ``"<entity_ref>#<predicate>"`` to narrow to one predicate; the
        explanation reports current state, the prior state via replay, actor,
        evidence, generated-by, and the change cause (from the causation chain
        and latest event reason/cause).

        :param subject: entity reference, optionally ``\"#predicate\"``-suffixed.
        :param as_of: only events at/before this time are considered.
        :param causation: narrow to the chain originating from this seq.
        :param correlation: narrow to events with this correlation id.
        :return: a :class:`ChangeExplanation`.
        """
        predicate = None
        if "#" in subject:
            subject, predicate = subject.split("#", 1)

        with self._engine.connect() as conn:
            current = self._current_row(conn, subject, predicate)
            events = self._events(conn, subject, predicate, as_of, causation, correlation)

        if not events:
            return ChangeExplanation(
                subject=subject,
                predicate=predicate,
                as_of=as_of,
                current=current,
                prior=None,
                actor=None,
                evidence=[],
                generated_by={},
                change_cause=None,
                history=[],
            )

        prior = self._prior_value(events, subject, predicate)
        latest = events[-1]
        actor = latest.created_by or latest.authority
        evidence = self._evidence(latest)
        cause = self._causation_chain(events, latest)
        history = [self._history_entry(e) for e in events]
        return ChangeExplanation(
            subject=subject,
            predicate=predicate,
            as_of=as_of,
            current=current,
            prior=prior,
            actor=actor,
            evidence=evidence,
            generated_by=latest.generated_by or {},
            change_cause=cause,
            history=history,
        )

    # -- helpers ----------------------------------------------------------

    def _current_row(
        self, conn: sa.Connection, subject: str, predicate: str | None
    ) -> dict[str, Any] | None:
        stmt = sa.select(_state_t).where(_state_t.c.entity_ref == subject)
        if predicate:
            stmt = stmt.where(_state_t.c.predicate == predicate)
        rows = conn.execute(stmt).fetchall()
        if not rows:
            return None
        values = {
            r.predicate: {
                "object_ref": r.object_ref,
                "confidence": r.confidence,
                "authority": r.authority,
                "state": r.state,
                "seq": r.seq,
            }
            for r in rows
        }
        if predicate:
            return values[predicate]
        return {"predicates": values}

    def _events(
        self,
        conn: sa.Connection,
        subject: str,
        predicate: str | None,
        as_of: datetime | None,
        causation: int | None,
        correlation: Any | None,
    ) -> list[SemanticEvent]:
        stmt = sa.select(_event_t).order_by(_event_t.c.seq.asc())
        conditions = []
        # Match by subject ref OR entity id in the payload (JSONB).
        for key in ("subject_ref", "entity_ref", "source_id", "entity_id", "subject_entity_id"):
            conditions.append(_event_t.c.payload[key].as_string() == subject)
        stmt = stmt.where(sa.or_(*conditions) if conditions else sa.true())
        if predicate:
            stmt = stmt.where(
                sa.or_(
                    _event_t.c.payload["predicate_code"].as_string() == predicate,
                    _event_t.c.payload["predicate"].as_string() == predicate,
                )
            )
        if as_of is not None:
            stmt = stmt.where(_event_t.c.tx_time <= as_of)
        if causation is not None:
            stmt = stmt.where(_event_t.c.causation_id == causation)
        if correlation is not None:
            stmt = stmt.where(_event_t.c.correlation_id == correlation)
        rows = conn.execute(stmt).fetchall()
        out: list[SemanticEvent] = []
        for r in rows:
            out.append(
                SemanticEvent(
                    seq=r.seq,
                    event_type=r.event_type,
                    payload=dict(r.payload or {}),
                    authority=r.authority,
                    confidence=r.confidence,
                    generated_by=dict(r.generated_by or {}),
                    correlation_id=r.correlation_id,
                    causation_id=r.causation_id,
                    created_by=r.created_by,
                    valid_time=r.valid_time,
                )
            )
        return out

    def _prior_value(
        self, events: list[SemanticEvent], subject: str, predicate: str | None
    ) -> dict[str, Any] | None:
        # Reconstruct the state before the latest relevant event for the subject.
        prior_events = events[:-1]
        state = self._reducer.replay(prior_events)
        if predicate:
            row = state.rows.get((subject, predicate))
            if row is None:
                return None
            return {
                "object_ref": row.object_ref,
                "confidence": row.confidence,
                "authority": row.authority,
                "state": row.state,
                "seq": row.seq,
            }
        return {
            p: {
                "object_ref": r.object_ref,
                "confidence": r.confidence,
                "authority": r.authority,
                "state": r.state,
                "seq": r.seq,
            }
            for (_, p), r in state.rows.items()
            if r.entity_ref == subject
        } or None

    @staticmethod
    def _evidence(event: SemanticEvent) -> list[str]:
        p = event.payload
        out: list[str] = []
        for key in ("evidence", "support_refs", "refs", "derived_from"):
            val = p.get(key)
            if isinstance(val, list):
                out.extend(str(v) for v in val)
            elif isinstance(val, str):
                out.append(val)
        return out

    @staticmethod
    def _history_entry(event: SemanticEvent) -> dict[str, Any]:
        return {
            "seq": event.seq,
            "event_type": event.event_type,
            "authority": event.authority,
            "created_by": event.created_by,
            "tx_time": event.tx_time.isoformat() if event.tx_time else None,
            "causation_id": event.causation_id,
            "correlation_id": str(event.correlation_id) if event.correlation_id else None,
            "payload": event.payload,
        }

    @staticmethod
    def _causation_chain(
        events: list[SemanticEvent], latest: SemanticEvent
    ) -> dict[str, Any] | None:
        by_seq = {e.seq: e for e in events if e.seq is not None}
        chain: list[int] = []
        cur = latest.causation_id
        while cur is not None and cur in by_seq and cur not in chain:
            chain.append(int(cur))
            cur = by_seq[cur].causation_id
        cause: dict[str, Any] = {}
        if chain:
            cause["chain"] = chain
        cause["cause_seq"] = latest.causation_id
        reason = latest.payload.get("reason") or latest.payload.get("cause")
        if reason is not None:
            cause["reason"] = reason
        return cause if (chain or reason) else None
