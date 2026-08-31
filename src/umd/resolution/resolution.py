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

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

import sqlalchemy as sa

from umd.domain.events import SemanticEvent
from umd.resolution.mentions import (
    PostgresMentionRepository,
    SourceMention,
    uuid_ref_or_none,
)
from umd.storage.postgres.ledger import CommitResult, SemanticLedger
from umd.storage.postgres.tables import metadata as db_meta

_alignment_t = db_meta.tables["alignment"]
_mention_t = db_meta.tables["entity_mention"]
_map_t = db_meta.tables["current_entity_map"]
_assertion_t = db_meta.tables["semantic_assertion"]
_event_t = db_meta.tables["semantic_event"]

pg_insert = sa.dialects.postgresql.insert


#: Stable alias idempotency namespace: (alias_entity, canonical) -> deterministic
#: ledger idempotency key so a repeated ALIAS application is a no-op (P4-S2).
_ALIAS_IDEM = uuid.NAMESPACE_URL


def _alias_idempotency_key(alias_entity: str, canonical: str) -> uuid.UUID:
    return uuid.uuid5(_ALIAS_IDEM, f"umd-alias:{alias_entity}\x1f{canonical}")


class ResolutionKind(StrEnum):
    MERGE = "MERGE"
    SPLIT = "SPLIT"
    ALIAS = "ALIAS"
    ESTABLISH = "ESTABLISH"
    UPDATE = "UPDATE"


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
    canonical_type: str | None = None,
    display_label: str | None = None,
    aliases: list[str] | None = None,
    support_refs: list[str] | None = None,
    memberships: dict[str, list[str]] | None = None,
    state: str | None = None,
    classification: str | None = None,
    authority: str = "machine",
    created_by: str | None = None,
) -> SemanticEvent:
    """Build an ``EntityResolved`` event conforming to ``EntityResolved/v2.json``.

    v2 (Plan S P1-S3) adds additive canonical-identity metadata (canonical type,
    display label, active aliases, support refs, memberships, state). Retained
    v1 MERGE/SPLIT/ALIAS events upcast with neutral defaults; nothing historical
    is mutated.

    ``authority`` defaults to ``"machine"`` (the deterministic resolution path).
    Plan T (P2-S3) lets the operator/human boundary establish a canonical with
    ``"operator"`` / ``"human"`` authority; the reducer keeps ``USER_OVERRIDE``
    precedence unchanged, and a non-USER_OVERRIDE authority behaves like machine
    w.r.t. lock/override protection.
    """
    payload: dict[str, Any] = {
        "kind": kind,
        "entity_id": entity_id,
        "target_entity_id": target_entity_id,
        "refs": refs or [],
        "assignments": assignments or {},
        "reason": reason,
        "quarantined_refs": quarantined_refs or [],
        "canonical_type": canonical_type,
        "display_label": display_label,
        "aliases": aliases or [],
        "support_refs": support_refs or [],
        "memberships": memberships or {},
        "state": state,
        "classification": classification,
    }
    if intensity is not None:
        payload["confidence"] = intensity
    return SemanticEvent(
        event_type="EntityResolved",
        authority=authority,
        confidence=intensity,
        created_by=created_by,
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
        mention_sources = list(self._mentions.mentions_for_entity(entity_ref))
        # Option B (P4-S4): split-time enumeration must ALSO discover string-
        # resolved mention ids attached to ``entity_ref`` by immutable ledger
        # events (EntityMentioned with entity_id==entity_ref / ALIAS resolved to
        # it). Their typed rows store entity_id=NULL, so the row query above
        # finds nothing — the ledger event is the authoritative attachment.
        seen_ids: set[str] = set()
        for m in mention_sources:
            seen_ids.add(m.mention_id)
        for mid in self._event_resolved_mention_ids(entity_ref):
            if mid in seen_ids:
                continue
            seen_ids.add(mid)
            loaded = self._mentions.get(mid)
            if loaded is not None:
                mention_sources.append(loaded)
        for m in mention_sources:
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

    def _event_resolved_mention_ids(self, entity_ref: str) -> list[str]:
        """Mention ids attached to ``entity_ref`` via ledger events (Option B).

        String-resolved mentions keep ``entity_mention.entity_id`` NULL; their
        resolution is authoritative only in the immutable ledger. Collect the
        mention ids whose ``EntityMentioned`` payload carries ``entity_id`` ==
        ``entity_ref`` and whose ``EntityResolved`` ALIAS event resolves them to
        it (``target_entity_id`` == ``entity_ref``).

        Bounded: the split enumerator only keeps ids that load from the mention
        store (``self._mentions.get(mid)``), so an id absent from
        ``entity_mention.id`` is skipped regardless. Semijoin the ledger scan
        against ``entity_mention.id`` to keep the read bounded by corpus size
        instead of a full-ledger scan.
        """
        id_expr = sa.case(
            (
                (_event_t.c.event_type == "EntityMentioned")
                & (_event_t.c.payload["entity_id"].astext == entity_ref)
                & (_event_t.c.payload["mention_id"].astext.is_not(None)),
                _event_t.c.payload["mention_id"].astext,
            ),
            (
                (_event_t.c.event_type == "EntityResolved")
                & (_event_t.c.payload["kind"].astext == "ALIAS")
                & (_event_t.c.payload["target_entity_id"].astext == entity_ref)
                & (_event_t.c.payload["entity_id"].astext.is_not(None)),
                _event_t.c.payload["entity_id"].astext,
            ),
            else_=None,
        )
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.select(id_expr)
                .join(
                    _mention_t,
                    sa.cast(_mention_t.c.id, sa.Text) == id_expr,
                )
                .where(_event_t.c.event_type.in_(("EntityMentioned", "EntityResolved")))
                .distinct()
            ).fetchall()
        return [str(r[0]) for r in rows if r[0] is not None]

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
    """Applies ESTABLISH / MERGE / ALIAS / SPLIT as append-only events + ledger transactions."""

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

    def establish(
        self,
        *,
        canonical: str,
        metadata: dict[str, Any] | None = None,
        reason: str | None = None,
        authority: str = "machine",
        created_by: str | None = None,
    ) -> CommitResult:
        """ESTABLISH: record an accepted canonical's identity metadata.

        Plan S (P1-S3): the canonical becomes a first-class ledger identity — the
        event carries canonical type, display label, active aliases, support refs,
        memberships, state, and confidence. Idempotent via a stable canonical key
        so a machine rerun converges (never duplicates the establishment).
        """
        meta = dict(metadata or {})
        event = resolved_event(
            kind="ESTABLISH",
            entity_id=canonical,
            target_entity_id=canonical,
            refs=list(meta.get("support_refs") or [canonical]),
            assignments={canonical: canonical},
            reason=reason or "canonical establishment",
            canonical_type=meta.get("canonical_type"),
            display_label=meta.get("display_label"),
            aliases=list(meta.get("aliases") or []),
            support_refs=list(meta.get("support_refs") or []),
            memberships=meta.get("memberships"),
            state=meta.get("state"),
            classification=meta.get("classification"),
            intensity=meta.get("confidence"),
            authority=authority,
            created_by=created_by,
        )
        # Plan S (P3-S1): the idempotency key includes a deterministic fingerprint
        # of the identity metadata, so re-establishing the SAME canonical with a
        # DIFFERENT source's membership appends (and the reducer union accumulates
        # it), while a same-content rerun still converges without duplication.
        # ``state`` is intentionally EXCLUDED from the fingerprint: a machine rerun
        # that seeds onto an existing canonical flips PROBABLE -> CONFIRMED, which is
        # a transient annotation, not new identity content — dropping it keeps the
        # fingerprint stable so a rerun over the same members converges instead of
        # appending a duplicate establishment.
        # ``classification`` is likewise excluded (Plan T P1-S3/R8): a rerun that
        # first saw a fresh (probable) canonical and, on a later pass, seeds it from
        # the now-committed assignment (accepted) must NOT emit a duplicate
        # ESTABLISH. Dropping both keeps the fingerprint stable so a rerun converges
        # instead of creating a second canonical topology (R1 — one authority).
        fingerprint = {k: v for k, v in meta.items() if k not in ("state", "classification")}
        digest = json.dumps(fingerprint, sort_keys=True, default=str)
        idem = uuid.uuid5(uuid.NAMESPACE_URL, f"umd-establish:{canonical}\x1f{digest}")
        return self._ledger.append([event], idempotency_key=idem)

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
        """ALIAS: explicit alias assertion (source mentions remain intact).

        Option B (P4-S2): the deterministic mention id is the ``alias_entity``
        (``EntityResolved.entity_id``) and the deterministic/seeded STRING is the
        ``canonical`` (``target_entity_id``). Application is idempotent via a
        stable ``(alias_entity, canonical)`` ledger idempotency key. The
        ``current_entity_map`` projection (UUID-only) is written ONLY when both
        refs are UUID-compatible (legacy UUID-backed paths); for text-resolution
        string refs the ALIAS event + reducer current_state are the authority.
        """
        event = resolved_event(
            kind="ALIAS",
            entity_id=alias_entity,
            target_entity_id=canonical,
            refs=[alias_entity],
            assignments={alias_entity: canonical},
            reason=reason or "resolution alias",
        )
        idem = _alias_idempotency_key(alias_entity, canonical)
        alias_uuid = uuid_ref_or_none(alias_entity)
        canonical_uuid = uuid_ref_or_none(canonical)
        if alias_uuid is None or canonical_uuid is None:
            # string canonical/alias refs -> ledger-first representation; the
            # ALIAS event + reducer current_state hold the decision.
            return self._ledger.append([event], idempotency_key=idem)

        def _record_alias(conn: sa.Connection) -> None:
            # derive the origin seq within the same transaction so the map row is
            # durable with the ALIAS event (origin_seq is NOT NULL).
            nxt = conn.execute(
                sa.select(sa.func.coalesce(sa.func.max(_event_t.c.seq), 0) + 1)
            ).scalar()
            conn.execute(
                pg_insert(_map_t)
                .values(
                    entity_id=alias_uuid,
                    alias=alias_entity,
                    canonical_entity_id=canonical_uuid,
                    origin_seq=nxt,
                )
                .on_conflict_do_nothing(
                    index_elements=["entity_id", "alias", "canonical_entity_id"]
                )
            )

        return self._ledger.complete_and_append(
            events=[event], idempotency_key=idem, side_effects=_record_alias
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
            # Option B (P4-S4): the typed ``entity_mention.entity_id`` FK is a
            # UUID. A split of a string canonical entity (rows store NULL) or a
            # reassignment to a non-UUID target is skipped — the resolution lives
            # in the ledger events, never materialized into a second authority.
            entity_uuid = uuid_ref_or_none(entity)
            if entity_uuid is not None:
                for ref, tgt in plan.reassignments():
                    tgt_uuid = uuid_ref_or_none(tgt)
                    if tgt_uuid is None:
                        continue  # non-UUID target -> ledger owns the resolution
                    conn.execute(
                        _mention_t.update()
                        .where(_mention_t.c.id == ref)
                        .where(_mention_t.c.entity_id == entity_uuid)
                        .values(entity_id=tgt_uuid)
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
