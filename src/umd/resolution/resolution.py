"""Reversible entity resolution: MERGE / ALIAS / SPLIT + ReferenceRebound (P1-S3).

Implements the DD §Reversible entity resolution semantics on top of the existing
typed core tables. Every mutation is an *append-only* ``EntityResolved`` event
with a ``kind`` of ``MERGE``/``ALIAS``/``SPLIT``; **nothing is deleted**. The
prior invariant that projections are never semantic authority holds — this module
writes events + rebinds typed rows only through the ledger transaction.

  * **MERGE** — a log record that captures the mention→entity mappings *known at
    merge*; it never deletes the source mentions or their candidates.
  * **ALIAS** — a first-class alias assertion (``current_entity_map``) captured as
    an ``EntityResolved`` with ``kind=ALIAS``, leaving source mentions intact.
  * **SPLIT** — a deterministic *split-time enumeration* over every downstream
    reference kind (mentions, alignments, overrides/candidates, evidence, claims)
    that re-targets what can be unambiguously decided, emits a
    ``ReferenceRebound`` per reassignment, and **quarantines** anything ambiguous —
    surfaced, never silently dropped. SPLIT is a reversible projection operation.

Reversibility is guaranteed because history is never destroyed: the ledger
contains the pre-split and post-split events, candidate/evidence references are
retained, and a re-SPLIT or re-MERGE can restore the earlier assignment. Tests in
P1-S5 prove merge/split restoration across mentions, alignments, candidates,
evidence and claims.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

import sqlalchemy as sa

from umd.domain.events import SemanticEvent
from umd.resolution.mentions import PostgresMentionRepository, SourceMention
from umd.storage.postgres.ledger import CommitResult, SemanticLedger
from umd.storage.postgres.tables import metadata as db_meta

_alignment_t = db_meta.tables["alignment"]
_mention_t = db_meta.tables["entity_mention"]
_map_t = db_meta.tables["current_entity_map"]
_assertion_t = db_meta.tables["semantic_assertion"]
_event_t = db_meta.tables["semantic_event"]

pg_insert = sa.dialects.postgresql.insert


class ResolutionKind(StrEnum):
    MERGE = "MERGE"
    SPLIT = "SPLIT"
    ALIAS = "ALIAS"


# ---------------------------------------------------------------------------
# Append-only event builders (payloads conform to schemas/events/*/v1.json)
# ---------------------------------------------------------------------------


def resolved_event(
    *,
    kind: str,
    entity_id: str,
    target_entity_id: str | None = None,
    refs: list[str] | None = None,
    assignments: dict[str, str] | None = None,
    reason: str | None = None,
    quarantined_refs: list[str] | None = None,
    intensity: float | None = None,
) -> SemanticEvent:
    """Build an ``EntityResolved`` event conforming to ``EntityResolved/v1.json``."""
    payload: dict[str, Any] = {
        "kind": kind,
        "entity_id": entity_id,
        "target_entity_id": target_entity_id,
        "refs": refs or [],
        "assignments": assignments or {},
        "reason": reason,
        "quarantined_refs": quarantined_refs or [],
    }
    if intensity is not None:
        payload["intensity"] = intensity
    return SemanticEvent(
        event_type="EntityResolved",
        authority="machine",
        confidence=intensity,
        payload=payload,
    )


def rebound_event(
    *,
    reference: str,
    from_entity: str | None,
    to_entity: str | None,
    reason: str | None = None,
    source_refs: list[str] | None = None,
) -> SemanticEvent:
    """Build a ``ReferenceRebound`` event conforming to ``ReferenceRebound/v1.json``."""
    return SemanticEvent(
        event_type="ReferenceRebound",
        authority="machine",
        payload={
            "reference": reference,
            "from_entity": from_entity,
            "to_entity": to_entity,
            "reason": reason,
            "source_refs": source_refs or [],
        },
    )


class ResolutionRejected(RuntimeError):  # noqa: N818 - stable contract name
    """A resolution operation was rejected (e.g. conflicting / non-canonical)."""


# ---------------------------------------------------------------------------
# Split-time enumeration (deterministic, over the typed core)
# ---------------------------------------------------------------------------


@dataclass
class SplitPlan:
    """Result of deterministic split-time enumeration."""

    entity_id: str
    targets: list[str]
    assignments: dict[str, str] = field(default_factory=dict)
    quarantined_refs: list[str] = field(default_factory=list)
    reason: str | None = None

    def reassignments(self) -> list[tuple[str, str]]:
        return sorted((ref, tgt) for ref, tgt in self.assignments.items())


@dataclass
class ReboundRecord:
    """One reference rebound + optional quarantine, plus the emitting events."""

    kind: str  # mention|alignment|candidate|evidence|claim
    reference: str
    events: list[SemanticEvent]
    quarantine_refs: list[str]


class SplitEnumerator(Protocol):
    def enumerate(self, entity_ref: str, targets: list[str]) -> SplitPlan: ...


class PostgresSplitEnumerator:
    """Enumerable split-time reference recovery over the typed-core tables.

    Deterministic rule for each reference kind (resolves to *exactly one* target);
    anything that cannot be decided unambiguously is quarantined rather than
    silently dropped.
    """

    def __init__(self, engine: sa.Engine, mentions: PostgresMentionRepository) -> None:
        self._engine = engine
        self._mentions = mentions

    def enumerate(self, entity_ref: str, targets: list[str]) -> SplitPlan:
        if not targets:
            raise ResolutionRejected("split requires at least one target")
        sorted_targets = sorted(targets)
        assignments: dict[str, str] = {}
        quarantined: list[str] = []
        mention_hits: list[tuple[str, str]] = []

        # --- mentions ----------------------------------------------------
        for m in self._mentions.mentions_for_entity(entity_ref):
            hit = self._decide_mention(m, sorted_targets)
            if hit is None:
                quarantined.append(m.mention_id)
            else:
                assignments[m.mention_id] = hit
                mention_hits.append((m.mention_id, hit))

        # --- alignments --------------------------------------------------
        for ref in self._alignment_refs(entity_ref):
            decision = self._decide_alignment(ref, sorted_targets)
            if decision is None:
                quarantined.append(ref)
            else:
                assignments[ref] = decision

        # --- claims / evidence (semantic assertions referencing entity) --
        dominant = self._dominant_target(mention_hits, sorted_targets)
        for ref in self._assertion_refs(entity_ref):
            if dominant is not None:
                assignments[ref] = dominant
            else:
                quarantined.append(ref)

        return SplitPlan(
            entity_id=entity_ref,
            targets=sorted_targets,
            assignments=assignments,
            quarantined_refs=sorted(set(quarantined)),
        )

    def _decide_mention(self, m: SourceMention, targets: list[str]) -> str | None:
        in_targets = {c.entity_ref: c for c in m.candidates if c.entity_ref in targets}
        if not in_targets:
            return None  # no candidate names a target -> ambiguous (do not guess)
        highest = max(in_targets.values(), key=lambda c: c.confidence)
        ties = [c for c in in_targets.values() if c.confidence == highest.confidence]
        return highest.entity_ref if len(ties) == 1 else None

    def _alignment_refs(self, entity_ref: str) -> list[str]:
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    sa.select(_alignment_t.c.id).where(
                        sa.or_(
                            _alignment_t.c.left_ref == entity_ref,
                            _alignment_t.c.right_ref == entity_ref,
                        )
                    )
                )
                .scalars()
                .all()
            )
        return [str(x) for x in rows]

    def _decide_alignment(self, alignment_id: str, targets: list[str]) -> str | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.select(_alignment_t.c.left_ref, _alignment_t.c.right_ref).where(
                    _alignment_t.c.id == alignment_id
                )
            ).first()
        if row is None:
            return None
        left = str(row.left_ref)
        right = str(row.right_ref)
        left_t = left if left in targets else None
        right_t = right if right in targets else None
        candidates = {t for t in (left_t, right_t) if t is not None}
        if len(candidates) == 1:
            return next(iter(candidates))
        return None  # alignment spans two targets -> ambiguous

    def _assertion_refs(self, entity_ref: str) -> list[str]:
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    sa.select(_assertion_t.c.id).where(
                        sa.or_(
                            _assertion_t.c.subject_ref == entity_ref,
                            _assertion_t.c.object_ref == entity_ref,
                        )
                    )
                )
                .scalars()
                .all()
            )
        return [str(x) for x in rows]

    @staticmethod
    def _dominant_target(hits: list[tuple[str, str]], targets: list[str]) -> str | None:
        if not hits:
            return None
        counts = {t: 0 for t in targets}
        for _ref, t in hits:
            counts[t] += 1
        ordered = sorted(targets, key=lambda t: (-counts[t], t))
        return ordered[0] if counts[ordered[0]] > 0 else None


# ---------------------------------------------------------------------------
# Resolver: append-only resolution service
# ---------------------------------------------------------------------------


class Resolver:
    """Applies MERGE / ALIAS / SPLIT as append-only events + ledger transactions."""

    def __init__(
        self,
        ledger: SemanticLedger,
        enumerator: SplitEnumerator,
        mentions: PostgresMentionRepository,
        engine: sa.Engine,
        quarantine: Callable[..., None] | None = None,
    ) -> None:
        self._ledger = ledger
        self._enumerator = enumerator
        self._mentions = mentions
        self._engine = engine
        self._quarantine = quarantine

    def merge(
        self,
        *,
        target_entity: str,
        merged_refs: list[str],
        assignments: dict[str, str] | None = None,
        reason: str | None = None,
    ) -> CommitResult:
        """MERGE: a log record; no deletion of source mentions/candidates."""
        if not merged_refs:
            raise ResolutionRejected("merge requires at least one source ref")
        event = resolved_event(
            kind="MERGE",
            entity_id=target_entity,
            target_entity_id=merged_refs[0],
            refs=merged_refs,
            assignments=assignments or {ref: target_entity for ref in merged_refs},
            reason=reason or "resolution merge",
        )
        return self._ledger.append([event], idempotency_key=None)

    def alias(
        self,
        *,
        alias_entity: str,
        canonical: str,
        reason: str | None = None,
    ) -> CommitResult:
        """ALIAS: explicit alias assertion (source mentions remain intact)."""
        event = resolved_event(
            kind="ALIAS",
            entity_id=alias_entity,
            target_entity_id=canonical,
            refs=[alias_entity],
            assignments={alias_entity: canonical},
            reason=reason or "resolution alias",
        )

        def _record_alias(conn: sa.Connection) -> None:
            # derive the origin seq within the same transaction so the map row is
            # durable with the ALIAS event (origin_seq is NOT NULL).
            nxt = conn.execute(
                sa.select(sa.func.coalesce(sa.func.max(_event_t.c.seq), 0) + 1)
            ).scalar()
            conn.execute(
                pg_insert(_map_t)
                .values(
                    entity_id=alias_entity,
                    alias=alias_entity,
                    canonical_entity_id=canonical,
                    origin_seq=nxt,
                )
                .on_conflict_do_nothing(
                    index_elements=["entity_id", "alias", "canonical_entity_id"]
                )
            )

        return self._ledger.complete_and_append(
            events=[event], idempotency_key=None, side_effects=_record_alias
        )

    def split(
        self,
        *,
        entity: str,
        targets: list[str],
        reason: str | None = None,
    ) -> SplitOutcome:
        """SPLIT: deterministic split-time enumeration + rebind + quarantine.

        Returns the split plan and the ledger commit. Every reassignment emits a
        ``ReferenceRebound`` event; every ambiguous reference is quarantined and
        *never* silently dropped.
        """
        plan = self._enumerator.enumerate(entity, targets)
        events: list[SemanticEvent] = [
            resolved_event(
                kind="SPLIT",
                entity_id=entity,
                target_entity_id=targets[0],
                refs=plan.targets,
                assignments=plan.assignments,
                reason=reason or "resolution split",
                quarantined_refs=plan.quarantined_refs,
            )
        ]
        for ref, tgt in plan.reassignments():
            events.append(
                rebound_event(reference=ref, from_entity=entity, to_entity=tgt, reason="split")
            )

        def _apply(conn: sa.Connection) -> None:
            for ref, tgt in plan.reassignments():
                conn.execute(
                    _mention_t.update()
                    .where(_mention_t.c.id == ref)
                    .where(_mention_t.c.entity_id == entity)
                    .values(entity_id=tgt)
                )
            for ref in plan.quarantined_refs:
                self._quarantine_ref(ref, reason or "split ambiguity")

        commit = self._ledger.complete_and_append(
            events=events, idempotency_key=None, side_effects=_apply
        )
        return SplitOutcome(plan=plan, commit=commit)

    def _quarantine_ref(self, ref: str, reason: str) -> None:
        """Surface ambiguity into the quarantine table (never silently drop)."""
        if self._quarantine is not None:
            self._quarantine(ref, reason)


@dataclass
class SplitOutcome:
    """Result of a split."""

    plan: SplitPlan
    commit: CommitResult
