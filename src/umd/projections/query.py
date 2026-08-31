"""Bounded relational graph-like query engine (P2-S4).

Implements the binding contract ``QueryService.structured(query) -> ProvenanceBearingPage``
— the query STORE/ENGINE (Phase 3 adds the HTTP/JSON boundary). It compiles the supported
bounded graph-like operations to indexed PostgreSQL SQL and bounded-depth enumeration over
the typed relational tables for scenes / entities / utterances / evidence /
correspondence / contradictions / unresolved aliases, with confidence thresholds,
continuity and temporal/spatial scope, pagination, and result-kind labels.

V1 NON-GOAL (explicit): no arbitrary-depth graph algorithms, no Neo4j/RDF/XTDB. Traversal
is capped at ``max_depth`` (bounded); results carry a bound report.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from pydantic import BaseModel, Field
from sqlalchemy.dialects import postgresql

from umd.projections.tables import (
    RESULT_KIND_CANONICAL_ENTITY,
    RESULT_KIND_INTERPRETATION,
    RESULT_KIND_SOURCE_EVIDENCE,
)
from umd.projections.tables import (
    active_semantic_edge as _edge,
)
from umd.storage.postgres.reducer import CANONICAL_IDENTITY_PREDICATE
from umd.storage.postgres.tables import metadata as db_meta

_cs = db_meta.tables["current_state"]
_map = db_meta.tables["current_entity_map"]
_entity = db_meta.tables["entity"]
_mention = db_meta.tables["entity_mention"]
_align = db_meta.tables["alignment"]
_seg = db_meta.tables["segment"]
_ev = db_meta.tables["evidence"]
_assert = db_meta.tables["semantic_assertion"]
_src = db_meta.tables["source"]
_se = db_meta.tables["semantic_event"]

#: Predicates treated as natural-language utterances.
UTTERANCE_PREDICATES = frozenset({"SPEAKS", "SAYS", "UTTERANCE", "PRONUNCIATION"})

#: Segment types treated as scenes / shots / chapters (bounded scene query).
SCENE_SEGMENT_TYPES = frozenset({"scene", "chapter", "shot", "frame", "section", "act"})


def _identity_metadata(object_ref: Any) -> dict[str, Any]:
    """Parse a persisted ``CANONICAL_IDENTITY`` row's JSON metadata dict.

    ``current_state.object_ref`` is a JSON serialization of the canonical-identity
    metadata ({canonical_type, display_label, aliases, support_refs, memberships,
    state, confidence}). A malformed/unparsable blob degrades to ``{}`` so a read
    never raises on storage that predates the field.
    """
    if not object_ref:
        return {}
    try:
        parsed = json.loads(str(object_ref))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


# ---------------------------------------------------------------------------
# Query model / result types
# ---------------------------------------------------------------------------


class StructuredQuery(BaseModel):
    """A bounded typed structured query (result-kind labelled)."""

    # ENTITY|UTTERANCE|SCENE|EVIDENCE|CORRESPONDENCE|CONTRADICTIONS|UNRESOLVED_ALIASES|TRAVERSAL
    kind: str
    ref: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    confidence_min: float | None = None
    continuity_id: str | None = None
    temporal_from: str | None = None
    temporal_to: str | None = None
    spatial: dict[str, Any] | None = None
    result_kind: str | None = None
    max_depth: int = 2  # bounded traversal depth (cap)
    limit: int = 50
    offset: int = 0


class QueryResultHit(BaseModel):
    ref: str
    kind: str
    label: str
    predicate: str | None = None
    value: str | None = None
    score: float | None = None
    confidence: float | None = None
    source_id: str | None = None
    segment_id: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    generated_by: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)


class BoundedReport(BaseModel):
    depth_used: int = 0
    max_depth_cap: int = 1
    bounded: bool = True
    note: str = "v1 bounded-depth enumeration; no arbitrary-depth graph algorithms"


class ProvenanceBearingPage(BaseModel):
    query: str
    results: list[QueryResultHit]
    total: int
    limit: int
    offset: int
    result_kinds: list[str]
    provenance: dict[str, Any] = Field(default_factory=dict)
    bound_report: BoundedReport = Field(default_factory=BoundedReport)


_I = RESULT_KIND_INTERPRETATION
_SE = RESULT_KIND_SOURCE_EVIDENCE
_CE = RESULT_KIND_CANONICAL_ENTITY


class ScopeUnmappableError(ValueError):
    """A query scope filter (continuity/temporal/spatial) cannot be mapped to the op.

    Raised instead of silently returning unfiltered results. The REST boundary maps
    this to an explicit RFC 7807 ``422`` (code ``unmappable_scope``).
    """


def _parse_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _parse_dt(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


class QueryService:
    """Compiles bounded typed queries over the relational semantic/current-state tables."""

    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    # -- dispatch ----------------------------------------------------------

    def structured(self, query: StructuredQuery | dict[str, Any]) -> ProvenanceBearingPage:
        q = query if isinstance(query, StructuredQuery) else StructuredQuery(**query)
        dispatcher = {
            "ENTITY": self.entities,
            "UTTERANCE": self.utterances,
            "SCENE": self.scenes,
            "EVIDENCE": self.evidence,
            "CORRESPONDENCE": self.correspondence,
            "CONTRADICTIONS": self.contradictions,
            "UNRESOLVED_ALIASES": self.unresolved_aliases,
            "TRAVERSAL": self.traverse,
            "RELATIONSHIP_EDGES": self.relationship_edges,
        }
        handler = dispatcher.get(q.kind)
        if handler is None:
            raise ValueError(f"unknown structured query kind {q.kind!r}")
        return handler(q)

    # -- entities ----------------------------------------------------------

    def entities(self, q: StructuredQuery) -> ProvenanceBearingPage:
        """Bounded canonical-ENTITY read over ledger/reducer-backed identity.

        Plan S (P2-S1): a canonical entity is read from the reducer ``current_state``
        ``CANONICAL_IDENTITY`` row (its durable identity metadata) — never the SQL
        ``entity`` table, which is not an authority. When no identity row exists the
        read falls back to the ``CANONICAL_ENTITY`` row (alias/legacy canonicals),
        preserving earlier behavior. ``ref`` matches the opaque ref, ``alias`` resolves
        an alias surface to its canonical, and ``name``/``name_fuzzy`` match the active
        display label (exact / case-insensitive substring) — all resolve the same
        canonical. Historical labels/aliases live in ``row.alternatives`` and the
        immutable ledger; they are audit-only and never active here.
        """
        self._scope(q)
        base: list[Any] = [(_cs.c.object_ref.is_not(None))]
        if q.confidence_min is not None:
            base.append(_cs.c.confidence >= q.confidence_min)
        if q.filters.get("ref"):
            base.append(_cs.c.entity_ref == q.filters["ref"])
        name = q.filters.get("name")
        fuzzy_name = q.filters.get("name_fuzzy") or q.filters.get("label_contains")
        alias = q.filters.get("alias")

        if name is not None or fuzzy_name is not None:
            # Display-label matching applies only to canonical-identity metadata
            # (labels/aliases live in the reducer row, never the SQL entity table).
            conds = base + [_cs.c.predicate == CANONICAL_IDENTITY_PREDICATE]
            filtered: list[Any] = []
            for r in self._identity_rows(conds):
                label = str(_identity_metadata(r.object_ref).get("display_label") or "")
                if name is not None and label != str(name):
                    continue
                if fuzzy_name is not None and str(fuzzy_name).lower() not in label.lower():
                    continue
                filtered.append(r)
            ordered = sorted(filtered, key=lambda r: str(r.entity_ref))
            total = len(ordered)
        elif alias is not None:
            # Resolve the alias surface to its canonical(s): id-based resolution
            # (mention ids, current_entity_map, ALIAS events) union the canonical's
            # active aliases carried in identity metadata. Reads identity + entity
            # rows so a legacy/alias canonical with no identity row still resolves.
            ids = self._alias_entity_ids(alias)
            ids += self._identity_alias_refs(alias)
            refs = list(dict.fromkeys(ids))
            conds = base + [_cs.c.predicate.in_(["CANONICAL_ENTITY", CANONICAL_IDENTITY_PREDICATE])]
            if refs:
                conds.append(_cs.c.entity_ref.in_(refs))
            else:
                conds.append(sa.literal(False))
            ordered, total = self._entity_ordered(conds, q)
        else:
            # General / ref path: canonical identities + legacy CANONICAL_ENTITY rows
            # keyed by a canonical-like ref (contains ':') — never a raw UUID alias
            # surface (a mention marker, not an entity). Dedup by ref, identity wins.
            conds = base + [
                sa.or_(
                    _cs.c.predicate == CANONICAL_IDENTITY_PREDICATE,
                    sa.and_(_cs.c.predicate == "CANONICAL_ENTITY", _cs.c.entity_ref.contains(":")),
                )
            ]
            ordered, total = self._entity_ordered(conds, q)
        results = [self._entity_hit(r) for r in ordered[q.offset : q.offset + q.limit]]
        return ProvenanceBearingPage(
            query=q.kind,
            results=results,
            total=total,
            limit=q.limit,
            offset=q.offset,
            result_kinds=[_CE],
            provenance={"authority": "postgres typed relational projection"},
        )

    def _entity_rows(self, conds: list[Any], q: StructuredQuery) -> list[Any]:
        """Fetch candidate entity/identity rows, bounded so pagination+dedup suffice.

        Each distinct ref contributes at most two rows (CANONICAL_IDENTITY +
        CANONICAL_ENTITY), adjacent under the ``entity_ref`` ordering, so fetching
        ``2 * (offset + limit)`` rows guarantees at least ``limit`` distinct refs.
        """
        cols = [
            (_cs.c.entity_ref, "entity_ref"),
            (_cs.c.predicate, "predicate"),
            (_cs.c.object_ref, "object_ref"),
            (_cs.c.confidence, "confidence"),
            (_cs.c.authority, "authority"),
            (_cs.c.seq, "seq"),
            (_cs.c.state, "state"),
        ]
        stmt = (
            sa.select(*[c.label(n) for c, n in cols])
            .where(*conds)
            .order_by(_cs.c.entity_ref)
            .limit((q.limit + q.offset) * 2 + 4)
        )
        with self._engine.connect() as conn:
            return list(conn.execute(stmt).fetchall())

    def _identity_rows(self, conds: list[Any]) -> list[Any]:
        cols = [
            (_cs.c.entity_ref, "entity_ref"),
            (_cs.c.predicate, "predicate"),
            (_cs.c.object_ref, "object_ref"),
            (_cs.c.confidence, "confidence"),
            (_cs.c.authority, "authority"),
            (_cs.c.seq, "seq"),
            (_cs.c.state, "state"),
        ]
        stmt = sa.select(*[c.label(n) for c, n in cols]).where(*conds)
        with self._engine.connect() as conn:
            return list(conn.execute(stmt).fetchall())

    def _identity_alias_refs(self, alias: Any) -> list[str]:
        """Canonical refs whose active identity metadata lists ``alias`` as an alias."""
        rows = self._identity_rows([_cs.c.predicate == CANONICAL_IDENTITY_PREDICATE])
        result: list[str] = []
        for r in rows:
            aliases = _identity_metadata(r.object_ref).get("aliases") or []
            if str(alias) in {str(a) for a in aliases}:
                result.append(str(r.entity_ref))
        return result

    def _entity_ordered(self, conds: list[Any], q: StructuredQuery) -> tuple[list[Any], int]:
        """Fetch entity/identity rows, dedup by ref (identity wins), and paginate."""
        best: dict[str, Any] = {}
        for r in self._entity_rows(conds, q):
            key = str(r.entity_ref)
            if r.predicate == CANONICAL_IDENTITY_PREDICATE or key not in best:
                best[key] = r
        ordered = sorted(best.values(), key=lambda r: str(r.entity_ref))
        return ordered, self._entity_total(conds)

    def _entity_total(self, conds: list[Any]) -> int:
        with self._engine.connect() as c:
            val = c.execute(
                sa.select(sa.func.count(sa.distinct(_cs.c.entity_ref)))
                .select_from(_cs)
                .where(*conds)
            ).scalar()
        return int(val or 0)

    def _entity_hit(self, r: Any) -> QueryResultHit:
        if r.predicate == CANONICAL_IDENTITY_PREDICATE:
            meta = _identity_metadata(r.object_ref)
            label = meta.get("display_label") or str(r.entity_ref)
            conf = meta.get("confidence")
            if conf is None:
                conf = r.confidence
            state = meta.get("state") or r.state or "UNKNOWN"
            aliases = list(meta.get("aliases") or [])
            support = list(meta.get("support_refs") or [])
            memberships = dict(meta.get("memberships") or {})
            ctype = meta.get("canonical_type")
            return QueryResultHit(
                ref=str(r.entity_ref),
                kind=_CE,
                label=label,
                predicate="CANONICAL_ENTITY",
                value=label,
                confidence=conf,
                provenance={
                    "predicate": CANONICAL_IDENTITY_PREDICATE,
                    "support_refs": support,
                    "state": state,
                },
                capabilities={
                    "canonical_type": ctype,
                    "aliases": aliases,
                    "state": state,
                    "memberships": memberships,
                    "display_label": label,
                },
                data={
                    "seq": r.seq,
                    "authority": r.authority,
                    "canonical_type": ctype,
                    "aliases": aliases,
                    "state": state,
                    "confidence": conf,
                    "support_refs": support,
                    "memberships": memberships,
                    "display_label": label,
                },
            )
        # Fallback: a CANONICAL_ENTITY row without identity metadata (alias/legacy).
        return QueryResultHit(
            ref=str(r.entity_ref),
            kind=_CE,
            label="canonical entity",
            predicate="CANONICAL_ENTITY",
            value=r.object_ref,
            confidence=r.confidence,
            data={"seq": r.seq, "authority": r.authority},
        )

    # -- utterances --------------------------------------------------------

    def utterances(self, q: StructuredQuery) -> ProvenanceBearingPage:
        self._scope(q)
        conds: list[Any] = [_cs.c.predicate.in_(list(UTTERANCE_PREDICATES))]
        if q.confidence_min is not None:
            conds.append(_cs.c.confidence >= q.confidence_min)
        if q.filters.get("speaker"):
            conds.append(_cs.c.entity_ref == q.filters["speaker"])
        page = self._run(
            q,
            _cs,
            [
                (_cs.c.entity_ref, "entity_ref"),
                (_cs.c.predicate, "predicate"),
                (_cs.c.object_ref, "object_ref"),
                (_cs.c.confidence, "confidence"),
                (_cs.c.authority, "authority"),
                (_cs.c.seq, "seq"),
            ],
            conds,
            lambda r: QueryResultHit(
                ref=str(r.entity_ref),
                kind=(_SE if r.authority != "USER_OVERRIDE" else _I),
                label="utterance",
                predicate=r.predicate,
                value=r.object_ref,
                confidence=r.confidence,
                score=None,
                data={"seq": r.seq, "authority": r.authority},
            ),
        )
        page.result_kinds = [_SE, _I]
        return page

    # -- scenes ------------------------------------------------------------

    def scenes(self, q: StructuredQuery) -> ProvenanceBearingPage:
        self._scope(q, continuity=True, temporal=True, spatial=True)
        conds: list[Any] = [_seg.c.segment_type.in_(list(SCENE_SEGMENT_TYPES))]
        if q.filters.get("source_id"):
            conds.append(_seg.c.source_id == q.filters["source_id"])
        if q.filters.get("locator"):
            conds.append(_seg.c.locator.op("~*")(q.filters["locator"]))
        conds.extend(self._continuity_pred(_seg.c.source_id, q))
        conds.extend(self._temporal_pred(_seg.c.start_time, _seg.c.end_time, q))
        conds.extend(self._spatial_pred(_seg.c.metadata_, q))
        page = self._run(
            q,
            _seg,
            [
                (_seg.c.id, "id"),
                (_seg.c.source_id, "source_id"),
                (_seg.c.locator, "locator"),
                (_seg.c.segment_type, "segment_type"),
                (_seg.c.ordinal, "ordinal"),
            ],
            conds,
            lambda r: QueryResultHit(
                ref=str(r.id),
                kind=_SE,
                label="scene",
                predicate=r.segment_type,
                value=r.locator,
                source_id=str(r.source_id) if r.source_id else None,
                data={"ordinal": r.ordinal},
            ),
        )
        page.result_kinds = [_SE]
        return page

    # -- evidence ----------------------------------------------------------

    def evidence(self, q: StructuredQuery) -> ProvenanceBearingPage:
        self._scope(q, continuity=True)
        conds: list[Any] = []
        if q.filters.get("locator"):
            conds.append(_ev.c.locator.op("~*")(q.filters["locator"]))
        if q.filters.get("evidence_kind"):
            conds.append(_ev.c.evidence_kind == q.filters["evidence_kind"])
        if q.filters.get("source_id"):
            conds.append(_ev.c.source_id == q.filters["source_id"])
        conds.extend(self._continuity_pred(_ev.c.source_id, q))
        page = self._run(
            q,
            _ev,
            [
                (_ev.c.id, "id"),
                (_ev.c.source_id, "source_id"),
                (_ev.c.segment_id, "segment_id"),
                (_ev.c.locator, "locator"),
                (_ev.c.evidence_kind, "evidence_kind"),
                (_ev.c.confidence, "confidence"),
            ],
            conds,
            lambda r: QueryResultHit(
                ref=str(r.id),
                kind=_SE,
                label="evidence",
                predicate=r.evidence_kind,
                value=r.locator,
                source_id=str(r.source_id) if r.source_id else None,
                segment_id=str(r.segment_id) if r.segment_id else None,
                confidence=r.confidence,
                provenance={
                    "source_id": str(r.source_id) if r.source_id else None,
                    "segment_id": str(r.segment_id) if r.segment_id else None,
                    "locator": r.locator,
                },
                generated_by={},
                capabilities={"evidence_kind": r.evidence_kind},
            ),
        )
        page.result_kinds = [_SE]
        return page

    # -- correspondence (alignment) -----------------------------------------

    def correspondence(self, q: StructuredQuery) -> ProvenanceBearingPage:
        self._scope(q)
        conds: list[Any] = []
        if q.confidence_min is not None:
            conds.append(_align.c.confidence >= q.confidence_min)
        if q.filters.get("type"):
            conds.append(_align.c.alignment_type == q.filters["type"])
        if q.filters.get("entity"):
            ref = q.filters["entity"]
            conds.append(sa.or_(_align.c.left_ref == ref, _align.c.right_ref == ref))
        page = self._run(
            q,
            _align,
            [
                (_align.c.id, "id"),
                (_align.c.left_ref, "left_ref"),
                (_align.c.right_ref, "right_ref"),
                (_align.c.alignment_type, "alignment_type"),
                (_align.c.method, "method"),
                (_align.c.confidence, "confidence"),
            ],
            conds,
            lambda r: QueryResultHit(
                ref=str(r.id),
                kind=_SE,
                label="correspondence",
                predicate=r.alignment_type,
                value=f"{r.left_ref} <-> {r.right_ref}",
                confidence=r.confidence,
                data={"left_ref": r.left_ref, "right_ref": r.right_ref, "method": r.method},
            ),
        )
        page.result_kinds = [_SE]
        return page

    # -- contradictions ------------------------------------------------------

    def contradictions(self, q: StructuredQuery) -> ProvenanceBearingPage:
        self._scope(q)
        conds: list[Any] = [(_cs.c.state == "CONFLICTING")]
        if q.confidence_min is not None:
            conds.append(sa.or_(_cs.c.confidence >= q.confidence_min, _cs.c.confidence.is_(None)))
        page = self._run(
            q,
            _cs,
            [
                (_cs.c.entity_ref, "entity_ref"),
                (_cs.c.predicate, "predicate"),
                (_cs.c.object_ref, "object_ref"),
                (_cs.c.confidence, "confidence"),
            ],
            conds,
            lambda r: QueryResultHit(
                ref=str(r.entity_ref),
                kind=_I,
                label="contradiction",
                predicate=r.predicate,
                value=r.object_ref,
                confidence=r.confidence,
                data={"state": r.state},
            ),
        )
        page.result_kinds = [_I]
        return page

    # -- unresolved aliases ----------------------------------------------------

    def unresolved_aliases(self, q: StructuredQuery) -> ProvenanceBearingPage:
        """Genuinely ambiguous mentions with no canonical resolution event.

        Returns ``entity_mention`` rows whose ``entity_id`` IS NULL and that no
        canonical ``EntityMentioned``/ALIAS ``EntityResolved`` ledger event has
        resolved — such mention ids are excluded (they are not truly ambiguous),
        so only reviewable unresolved mentions are returned.
        """
        self._scope(q, continuity=True)
        conds: list[Any] = [_mention.c.entity_id.is_(None)]
        # Option B (P4-S5): exclude mention ids that ARE resolved by canonical
        # MENTION/ALIAS ledger events (their typed rows keep entity_id=NULL, so
        # they are not genuinely ambiguous) while retaining genuinely ambiguous
        # mentions that no event resolved.
        resolved = self._resolved_mention_ids()
        if resolved:
            conds.append(~_mention.c.id.in_(resolved))
        if q.filters.get("source_id"):
            conds.append(_mention.c.source_id == q.filters["source_id"])
        conds.extend(self._continuity_pred(_mention.c.source_id, q))
        order = sa.desc(_mention.c.created_at)
        rows = self._select(
            _mention,
            [
                (_mention.c.id, "id"),
                (_mention.c.mention_text, "mention_text"),
                (_mention.c.source_id, "source_id"),
                (_mention.c.segment_id, "segment_id"),
            ],
            conds,
            q,
            order_by=order,
        ).fetchall()
        results = [
            QueryResultHit(
                ref=str(r.id),
                kind=_I,
                label="unresolved alias",
                value=r.mention_text,
                source_id=str(r.source_id) if r.source_id else None,
                segment_id=str(r.segment_id) if r.segment_id else None,
                data={"unresolved": True},
            )
            for r in rows
        ]
        return ProvenanceBearingPage(
            query="UNRESOLVED_ALIASES",
            results=results,
            total=len(results),
            limit=q.limit,
            offset=q.offset,
            result_kinds=[_I],
            provenance={"authority": "entity_mention projection"},
            bound_report=BoundedReport(max_depth_cap=q.max_depth),
        )

    def _alias_entity_ids(self, alias: str) -> list[str]:
        """Resolve an alias surface to candidate canonical entity refs (P4-S5).

        Supports BOTH the legacy UUID-backed ``current_entity_map`` rows and the
        Option B ledger-first string refs (reducer ``current_state``
        ``CANONICAL_ENTITY`` rows keyed by the alias mention id, plus ALIAS
        ``EntityResolved`` events).
        """
        out: list[str] = []
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.select(_map.c.entity_id, _map.c.canonical_entity_id).where(_map.c.alias == alias)
            ).fetchall()
            for r in rows:
                if r.entity_id:
                    out.append(str(r.entity_id))
                if r.canonical_entity_id:
                    out.append(str(r.canonical_entity_id))
            # Option B: string aliases live in current_state CANONICAL_ENTITY rows
            # (entity_ref == alias mention id, object_ref == canonical).
            for r in conn.execute(
                sa.select(_cs.c.object_ref).where(
                    (_cs.c.predicate == "CANONICAL_ENTITY") & (_cs.c.entity_ref == alias)
                )
            ).fetchall():
                if r.object_ref:
                    out.append(str(r.object_ref))
            # ... and in ALIAS EntityResolved events (ledger-first authority).
            # Bounded: filter to the target ALIAS events server-side instead of
            # scanning every EntityResolved payload into Python. There is no
            # entity_mention row anchor (targets are STRING canonical refs).
            for r in conn.execute(
                sa.select(_se.c.payload["target_entity_id"].astext).where(
                    (_se.c.event_type == "EntityResolved")
                    & (_se.c.payload["kind"].astext == "ALIAS")
                    & (_se.c.payload["entity_id"].astext == alias)
                )
            ).fetchall():
                if r[0]:
                    out.append(r[0])
        seen: set[str] = set()
        result: list[str] = []
        for v in out:
            if v not in seen:
                seen.add(v)
                result.append(v)
        return result

    def _resolved_mention_ids(self) -> set[str]:
        """Mention ids resolved by canonical MENTION/ALIAS ledger events.

        Under Option B these mentions carry ``entity_mention.entity_id`` NULL,
        so the row alone cannot distinguish them from genuinely ambiguous ones;
        the immutable ledger event is the authoritative resolution signal.

        Bounded: the caller only applies the result as
        ``~entity_mention.id.in_(...)``, so any id absent from
        ``entity_mention.id`` cannot affect the outcome. Semijoin the ledger
        scan against ``entity_mention.id`` to keep the read bounded by corpus
        size instead of a full-ledger scan.
        """
        id_expr = sa.case(
            (
                (_se.c.event_type == "EntityMentioned")
                & (_se.c.payload["entity_id"].astext.is_not(None))
                & (_se.c.payload["mention_id"].astext.is_not(None)),
                _se.c.payload["mention_id"].astext,
            ),
            (
                (_se.c.event_type == "EntityResolved")
                & (_se.c.payload["kind"].astext == "ALIAS")
                & (_se.c.payload["entity_id"].astext.is_not(None)),
                _se.c.payload["entity_id"].astext,
            ),
            else_=None,
        )
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.select(id_expr)
                .join(
                    _mention,
                    sa.cast(_mention.c.id, sa.Text) == id_expr,
                )
                .where(_se.c.event_type.in_(("EntityMentioned", "EntityResolved")))
                .distinct()
            ).fetchall()
        return {str(r[0]) for r in rows if r[0] is not None}

    # -- bounded traversal ------------------------------------------------------

    def traverse(self, q: StructuredQuery) -> ProvenanceBearingPage:
        """Bounded-depth neighbor enumeration from an entity ref (no arbitrary depth)."""
        self._scope(q)
        start = q.ref or q.filters.get("ref")
        if not start:
            raise ValueError("TRAVERSAL requires a starting ref")
        depth = max(0, min(q.max_depth, 4))  # hard cap keeps traversal bounded
        report = BoundedReport(max_depth_cap=depth)
        results: list[QueryResultHit] = []
        seen_refs: set[str] = set()
        frontier = [start]
        depth_used = 0
        for d in range(1, depth + 1):
            if not frontier:
                break
            depth_used = d
            neighbors: dict[str, QueryResultHit] = {}
            conds: list[Any] = [_cs.c.entity_ref.in_(frontier)]
            if q.result_kind == _CE:
                conds.append(_cs.c.predicate == "CANONICAL_ENTITY")
            elif q.result_kind:
                conds.append(sa.true())
            rows = self._select(
                _cs,
                [
                    (_cs.c.entity_ref, "entity_ref"),
                    (_cs.c.predicate, "predicate"),
                    (_cs.c.object_ref, "object_ref"),
                    (_cs.c.confidence, "confidence"),
                ],
                conds,
                StructuredQuery(kind="TRAVERSAL", limit=500),
            ).fetchall()
            next_frontier: list[str] = []
            for r in rows:
                key = (
                    f"{r.object_ref}:{r.predicate}"
                    if r.object_ref
                    else f"{r.entity_ref}:{r.predicate}"
                )
                if key in seen_refs:
                    continue
                seen_refs.add(key)
                if r.object_ref:
                    next_frontier.append(str(r.object_ref))
                neighbors[key] = QueryResultHit(
                    ref=str(r.object_ref or r.entity_ref),
                    kind=_CE if r.predicate == "CANONICAL_ENTITY" else _SE,
                    label="neighbor",
                    predicate=r.predicate,
                    value=r.object_ref,
                    confidence=r.confidence,
                    data={"depth": d},
                )
            results.extend(neighbors.values())
            frontier = sorted(set(next_frontier))
        report.depth_used = depth_used
        results = results[q.offset : q.offset + q.limit]
        return ProvenanceBearingPage(
            query="TRAVERSAL",
            results=results,
            total=len(results),
            limit=q.limit,
            offset=q.offset,
            result_kinds=[_CE, _SE],
            provenance={"start": start},
            bound_report=report,
        )

    # -- relationship edges (P2-S4) -------------------------------------------

    def relationship_edges(self, q: StructuredQuery) -> ProvenanceBearingPage:
        """Bounded structured read over ACTIVE relationship edges (multi-edge).

        Returns every currently-active relationship edge (assertion/override/correction)
        with its confidence, authority, semantic state, scope, and provenance. Multiple
        distinct active edges may share ``(subject_ref, predicate)`` with different
        objects (multi-edge). Superseded edges (``active=false``) are excluded — they
        remain in the store as immutable history, never surfaced as active.
        """
        self._scope(q, temporal=True, spatial=True)
        conds: list[Any] = [_edge.c.active.is_(sa.true())]
        if q.confidence_min is not None:
            conds.append(_edge.c.confidence >= q.confidence_min)
        if q.filters.get("subject"):
            conds.append(_edge.c.subject_ref == q.filters["subject"])
        if q.filters.get("ref"):
            ref = q.filters["ref"]
            conds.append(sa.or_(_edge.c.subject_ref == ref, _edge.c.object_ref == ref))
        if q.filters.get("predicate"):
            conds.append(_edge.c.predicate == q.filters["predicate"])
        if q.filters.get("object"):
            conds.append(_edge.c.object_ref == q.filters["object"])
        if q.filters.get("scope"):
            conds.append(_edge.c.scope == q.filters["scope"])
        conds.extend(self._edge_temporal_pred(q))
        conds.extend(self._edge_spatial_pred(q))
        if q.result_kind == _SE:
            conds.append(_edge.c.authority != "USER_OVERRIDE")
        elif q.result_kind == _I:
            conds.append(_edge.c.authority == "USER_OVERRIDE")
        page = self._run(
            q,
            _edge,
            [
                (_edge.c.subject_ref, "subject_ref"),
                (_edge.c.predicate, "predicate"),
                (_edge.c.object_ref, "object_ref"),
                (_edge.c.confidence, "confidence"),
                (_edge.c.authority, "authority"),
                (_edge.c.state, "state"),
                (_edge.c.scope, "scope"),
                (_edge.c.ledger_seq, "seq"),
                (_edge.c.fact_id, "fact_id"),
            ],
            conds,
            lambda r: QueryResultHit(
                ref=str(r.subject_ref),
                kind=(_I if r.authority == "USER_OVERRIDE" else _SE),
                label="relationship edge",
                predicate=r.predicate,
                value=r.object_ref,
                confidence=r.confidence,
                provenance={
                    "fact_id": str(r.fact_id),
                    "state": r.state,
                    "scope": r.scope,
                    "seq": r.seq,
                },
                generated_by={},
                capabilities={"edge": True},
                data={"authority": r.authority, "state": r.state, "scope": r.scope},
            ),
        )
        page.result_kinds = [_SE, _I]
        return page

    def _edge_temporal_pred(self, q: StructuredQuery) -> list[Any]:
        """Bounded temporal predicate over the edge's narrative-time range."""
        if not (q.temporal_from or q.temporal_to):
            return []
        f = _parse_dt(q.temporal_from) if q.temporal_from else None
        t = _parse_dt(q.temporal_to) if q.temporal_to else None
        if q.temporal_from and f is None:
            raise ScopeUnmappableError("temporal_from is not a valid ISO-8601 datetime")
        if q.temporal_to and t is None:
            raise ScopeUnmappableError("temporal_to is not a valid ISO-8601 datetime")
        conds: list[Any] = []
        nt = _edge.c.derivation["narrative_time"]
        if f is not None:
            conds.append(sa.cast(nt["to"].astext, sa.TIMESTAMP(timezone=True)) >= f)
        if t is not None:
            conds.append(sa.cast(nt["from"].astext, sa.TIMESTAMP(timezone=True)) <= t)
        return conds

    def _edge_spatial_pred(self, q: StructuredQuery) -> list[Any]:
        """Bounded JSONB-containment spatial predicate over the edge's spatial payload."""
        if not q.spatial:
            return []
        payload = sa.cast(sa.literal(json.dumps({"spatial": q.spatial})), postgresql.JSONB())
        return [_edge.c.derivation.op("@>")(payload)]

    # -- scope filters (P4-S1..S3) ----------------------------------------------
    def _scope(
        self,
        q: StructuredQuery,
        *,
        continuity: bool = False,
        temporal: bool = False,
        spatial: bool = False,
    ) -> None:
        """Validate that any provided scope filter maps to this operation.

        A scope field that cannot map to the operation's typed columns raises
        :class:`ScopeUnmappableError` (surfaced as RFC 7807 ``422`` by the API)
        rather than silently returning unfiltered rows.
        """
        if q.continuity_id and not continuity:
            raise ScopeUnmappableError(
                f"continuity_id scope is not mappable to {q.kind!r} "
                "(rows do not expose alignment/segment continuity)"
            )
        if (q.temporal_from or q.temporal_to) and not temporal:
            raise ScopeUnmappableError(
                f"temporal scope is not mappable to {q.kind!r} (no valid-time/time-range column)"
            )
        if q.spatial and not spatial:
            raise ScopeUnmappableError(
                f"spatial scope is not mappable to {q.kind!r} (no spatial-capable column)"
            )

    def _continuity_pred(self, source_col: Any, q: StructuredQuery) -> list[Any]:
        """Bounded indexed continuity predicate via ``source.continuity_id``."""
        if not q.continuity_id:
            return []
        cid = _parse_uuid(q.continuity_id)
        if cid is None:
            raise ScopeUnmappableError("continuity_id is not a valid UUID")
        subq = sa.select(_src.c.id).where(_src.c.continuity_id == cid)
        return [source_col.in_(subq)]

    def _temporal_pred(
        self, range_from_col: Any, range_to_col: Any, q: StructuredQuery
    ) -> list[Any]:
        """Indexed temporal predicate (open-ended bounds) over a valid-time range."""
        if not (q.temporal_from or q.temporal_to):
            return []
        f = _parse_dt(q.temporal_from) if q.temporal_from else None
        t = _parse_dt(q.temporal_to) if q.temporal_to else None
        if q.temporal_from and f is None:
            raise ScopeUnmappableError("temporal_from is not a valid ISO-8601 datetime")
        if q.temporal_to and t is None:
            raise ScopeUnmappableError("temporal_to is not a valid ISO-8601 datetime")
        conds: list[Any] = []
        # Range overlap: [range_from, range_to] intersects [f, t].
        if f is not None:
            conds.append(range_to_col >= f)
        if t is not None:
            conds.append(range_from_col <= t)
        return conds

    def _spatial_pred(self, spatial_col: Any, q: StructuredQuery) -> list[Any]:
        """Indexed JSONB-containment spatial predicate over a spatial-capable column."""
        if not q.spatial:
            return []
        payload = sa.cast(sa.literal(json.dumps({"spatial": q.spatial})), postgresql.JSONB())
        return [spatial_col.op("@>")(payload)]

    # -- internals ---------------------------------------------------------------

    def _run(
        self,
        q: StructuredQuery,
        table: Any,
        columns: list[tuple[Any, str]],
        conds: list[Any],
        mapper: Any,
    ) -> ProvenanceBearingPage:
        stmt = self._select(table, columns, conds, q)
        rows = stmt.fetchall()
        results = [mapper(r) for r in rows]
        with self._engine.connect() as c:
            total = int(
                c.execute(sa.select(sa.func.count()).select_from(table).where(*conds)).scalar() or 0
            )
        return ProvenanceBearingPage(
            query=q.kind,
            results=results[0 : q.limit],
            total=total,
            limit=q.limit,
            offset=q.offset,
            result_kinds=[q.result_kind] if q.result_kind else [],
            provenance={"authority": "postgres typed relational projection"},
        )

    def _select(
        self,
        table: Any,
        columns: list[tuple[Any, str]],
        conds: list[Any],
        q: StructuredQuery,
        order_by: Any | None = None,
    ) -> Any:
        cols = [c.label(name) for c, name in columns]
        stmt = sa.select(*cols).where(*conds)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        if q.kind != "TRAVERSAL" or q.limit:
            stmt = stmt.limit(q.limit).offset(q.offset)
        with self._engine.connect() as conn:
            return conn.execute(stmt)


def _uid() -> str:
    return uuid.uuid4().hex


__all__ = [
    "QueryService",
    "StructuredQuery",
    "QueryResultHit",
    "ProvenanceBearingPage",
    "BoundedReport",
    "ScopeUnmappableError",
    "UTTERANCE_PREDICATES",
]
