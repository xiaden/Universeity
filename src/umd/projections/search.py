"""Exact / full-text search projection (P2-S3): builder + service.

The search projection is a Tier-1, single-writer, replay-only projection. Its ONLY
writer is :class:`SearchProjectionBuilder` (driven by :class:`ReplayDriver`); readers go
through :class:`SearchService` which queries the ``search_document`` store with native
PostgreSQL ``tsvector`` exact matching and ``pg_trgm`` fuzzy matching, and (optionally)
fuses a pgvector/vector score into a hybrid, result-kind-labelled page.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa

from umd.domain.events import SemanticEvent
from umd.projections.base import ReplayDriver
from umd.projections.edges import EDGE_PROJECTION_NAME
from umd.projections.embedder import embed_text
from umd.projections.tables import (
    RESULT_KIND_CANONICAL_ENTITY,
    RESULT_KIND_INTERPRETATION,
    RESULT_KIND_SOURCE_EVIDENCE,
    add_fulltext_columns,
    search_document_in,
)
from umd.projections.tables import (
    active_semantic_edge as _active_edge,
)
from umd.storage.postgres.reducer import CANONICAL_IDENTITY_PREDICATE

#: Predicates whose ``object_ref`` is natural utterance/pronunciation text worth indexing.
_UTTERANCE_PREDICATES = frozenset({"SPEAKS", "SAYS", "UTTERANCE", "PRONUNCIATION"})

#: The ``ref`` prefix under which relationship-edge docs are indexed. The whole
#: ``edge:%`` family is reconciled deterministically on every incremental finalize
#: (P4-S2): superseded/corrected/overridden edges can never remain searchable.
_EDGE_DOC_PREFIX = "edge:"

#: The ``ref`` prefix under which utterance-predicate docs are indexed. In Phase 5
#: the immutable assertion event stream is NO LONGER a search-doc source for
#: utterances: ``apply`` no longer writes ``assert:{seq}`` docs. Instead the whole
#: ``assert:%`` family is rebuilt on every finalize from the ACTIVE edge store (the
#: single read-side source) as ``assert:{fact_id}``, so a corrected/overridden/
#: invalidated utterance can never stay searchable under its superseded value and
#: the corrected value is always indexed once the edge store is current.
_ASSERT_DOC_PREFIX = "assert:"

_NAMESPACE = b"umd.search_doc"


class EdgeProjectionLagError(RuntimeError):
    """The ``semantic_edges`` projection trailed the search replay target.

    Raised from :meth:`SearchProjectionBuilder._index_active_edges` when the edge
    checkpoint has not reached the search replay target. It propagates through the
    :class:`ReplayDriver` transaction so the whole search rebuild rolls back — no
    edge-derived documents are written and the search checkpoint is never advanced
    (a search must not publish a checkpoint after reading a lagging edge store).
    """


def _doc_id(kind: str, ref: str) -> str:
    return hashlib.sha256(_NAMESPACE + kind.encode() + b"\x1f" + ref.encode()).hexdigest()[:36]


class SearchProjectionBuilder:
    """Single-writer search-store projector over the semantic ledger."""

    projection_name = "search"

    def __init__(self, schema: str = "public") -> None:
        self.schema = schema
        self._table = search_document_in(schema)

    def prepare(self, conn: sa.Connection, driver: ReplayDriver) -> None:
        # Ensure the full-text wiring exists for the target schema (idempotent). On a
        # blue/green generation schema the publish manager already created it; here we
        # guarantee it for the default public target too (migration 0004 also did).
        add_fulltext_columns(conn, self.schema)

    def wipe(self, conn: sa.Connection, driver: ReplayDriver) -> None:
        conn.execute(self._table.delete())

    def apply(self, conn: sa.Connection, driver: ReplayDriver, event: SemanticEvent) -> None:
        if event.event_type == "EntityMentioned":
            self._upsert(
                conn,
                ref=str(event.payload.get("mention_id") or event.payload.get("source_id") or ""),
                kind=RESULT_KIND_SOURCE_EVIDENCE,
                text=str(event.payload.get("mention_text") or ""),
                source_id=event.payload.get("source_id"),
                segment_id=event.payload.get("segment_id"),
                entity_ref=event.payload.get("entity_id"),
                seq=event.seq or 0,
            )
            return
        # NOTE (P5-S1): utterance predicates are NO LONGER indexed here from the
        # immutable assertion stream (previously ``assert:{seq}`` docs). The immutable
        # event stream is not a search-doc source for utterances anymore — the ACTIVE
        # edge store is the single read-side source, reconciled on every finalize in
        # ``_index_active_edges`` as ``assert:{fact_id}``. This is what lets a
        # correction/override/invalidation supersede an utterance on the public search
        # surface (a stale ``assert:{seq}`` doc would otherwise survive it).

    def on_skip(self, conn: sa.Connection, driver: ReplayDriver, event: SemanticEvent) -> None:
        return None

    def on_pause(self, conn: sa.Connection, driver: ReplayDriver, event: SemanticEvent) -> None:
        return None

    def finalize(self, conn: sa.Connection, driver: ReplayDriver) -> None:
        # Plan S (P2-S3): refresh canonical-entity docs from the reducer Tier-1 state.
        # The CANONICAL_IDENTITY row carries the durable identity metadata (display
        # label + active aliases); we index those under the canonical opaque ref. This
        # is a deterministic full-family rebuild — every finalize deletes ALL
        # CANONICAL_ENTITY docs and reindexes exactly the current active labels +
        # aliases, so a corrected/overridden historical label can never remain
        # searchable. A canonical WITHOUT identity metadata (legacy/alias-only) falls
        # back to indexing its CANONICAL_ENTITY object_ref, preserving prior behavior.
        identity_refs = {
            str(ref)
            for (ref, predicate) in driver.state.rows
            if predicate == CANONICAL_IDENTITY_PREDICATE
        }
        conn.execute(self._table.delete().where(self._table.c.kind == RESULT_KIND_CANONICAL_ENTITY))
        for (ref, predicate), row in driver.state.rows.items():
            if predicate == CANONICAL_IDENTITY_PREDICATE and row.object_ref:
                self._index_canonical_identity(conn, str(ref), row)
            elif (
                predicate == "CANONICAL_ENTITY" and row.object_ref and str(ref) not in identity_refs
            ):
                self._upsert(
                    conn,
                    ref=str(ref),
                    kind=RESULT_KIND_CANONICAL_ENTITY,
                    text=str(row.object_ref),
                    source_id=None,
                    segment_id=None,
                    entity_ref=str(ref),
                    predicate=predicate,
                    seq=row.seq,
                )
        # Surfacing (P2-S4/P5-S1): index ACTIVE relationship edges from the edge store as
        # typed INTERPRETATION hits. The edge builder is the sole WRITER of the edge store;
        # this builder only READS it. Every finalize deterministically reconciles BOTH the
        # ``edge:%`` and ``assert:%`` document families against the current active edge
        # store: non-utterance predicates (e.g. HAS_EMOTION, CO_OCCURS) are indexed as
        # ``edge:{fact_id}`` and utterance predicates (SPEAKS|SAYS|UTTERANCE|PRONUNCIATION)
        # as ``assert:{fact_id}``. Only ``active=true`` edges are indexed — superseded
        # edges never surface in search.
        # P4-S1/P4-S2/P5-S1: gated on the semantic_edges freshness, and every finalize
        # deterministically reconciles the whole ``edge:%`` + ``assert:%`` document
        # families.
        self._index_active_edges(conn, driver)

    def _index_canonical_identity(self, conn: sa.Connection, ref: str, row: Any) -> None:
        """Index a canonical identity's active display label + aliases under its ref.

        The display label is indexed under the opaque canonical ``ref`` itself; each
        active alias gets its own CANONICAL_ENTITY doc under a derived ``ref::alias:``
        ref with ``entity_ref`` pointing back at the canonical — so exact, fuzzy and
        alias searches all resolve to the same canonical opaque ref. Inactive
        historical labels/aliases (only in ``row.alternatives`` + the immutable
        ledger) are never indexed here.
        """
        try:
            meta = json.loads(str(row.object_ref))
        except (TypeError, ValueError):
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        label = str(meta.get("display_label") or "")
        self._upsert(
            conn,
            ref=ref,
            kind=RESULT_KIND_CANONICAL_ENTITY,
            text=label,
            source_id=None,
            segment_id=None,
            entity_ref=ref,
            predicate=CANONICAL_IDENTITY_PREDICATE,
            seq=row.seq,
        )
        for alias in meta.get("aliases") or []:
            if not alias:
                continue
            alias_ref = f"{ref}::alias::{hashlib.sha256(str(alias).encode()).hexdigest()[:12]}"
            self._upsert(
                conn,
                ref=alias_ref,
                kind=RESULT_KIND_CANONICAL_ENTITY,
                text=str(alias),
                source_id=None,
                segment_id=None,
                entity_ref=ref,
                predicate=CANONICAL_IDENTITY_PREDICATE,
                seq=row.seq,
            )

    def _index_active_edges(self, conn: sa.Connection, driver: ReplayDriver) -> None:
        # P4-S1 — cross-projection freshness protocol. Serialize this finalize against the
        # semantic_edges projection rebuild lock (same advisory key the edge builder's
        # ReplayDriver acquires), then require the edge checkpoint to have reached THIS
        # search replay target before reading active_semantic_edge. A lagging edge store
        # would yield stale/partial edge docs; aborting (raising) rolls the whole search
        # transaction back so the search checkpoint is never advanced and no edge-derived
        # document is written from a lagging dependency. When the search projection is
        # paused it publishes a paused checkpoint (never fresh), so the gate is skipped.
        if conn.dialect.name == "postgresql":
            conn.execute(
                sa.select(sa.func.pg_advisory_xact_lock(sa.func.hashtext(EDGE_PROJECTION_NAME)))
            )
        edge_cp = driver.store.get(EDGE_PROJECTION_NAME, conn=conn)
        if (
            not getattr(driver, "paused", False)
            and edge_cp is not None
            and edge_cp.applied_seq < driver.applied_seq
        ):
            raise EdgeProjectionLagError(
                f"semantic_edges checkpoint ({edge_cp.applied_seq}) trails search replay "
                f"target ({driver.applied_seq}); refusing to index stale edges or advance "
                "the search checkpoint"
            )

        # P4-S2 / P5-S1 — deterministic reconciliation. Delete the complete ``edge:%`` AND
        # ``assert:%`` document families, then reindex EXACTLY the currently active edges
        # from the active edge store. Non-utterance predicates are indexed as
        # ``edge:{fact_id}``; utterance predicates (SPEAKS|SAYS|UTTERANCE|PRONUNCIATION) as
        # ``assert:{fact_id}``. Corrections / overrides / invalidations can no longer leave
        # a superseded utterance or edge hit searchable, and the corrected value (from the
        # active edge store) is always indexed; the ledger + active-edge history are
        # untouched. The immutable event stream is no longer a search-doc source for
        # utterances — active edges are the single read-side source.
        conn.execute(self._table.delete().where(self._table.c.ref.like(f"{_EDGE_DOC_PREFIX}%")))
        conn.execute(self._table.delete().where(self._table.c.ref.like(f"{_ASSERT_DOC_PREFIX}%")))

        edge = _active_edge
        rows = conn.execute(
            sa.select(
                edge.c.fact_id,
                edge.c.subject_ref,
                edge.c.object_ref,
                edge.c.predicate,
                edge.c.confidence,
                edge.c.ledger_seq,
            ).where(edge.c.active.is_(sa.true()))
        ).fetchall()
        for r in rows:
            pred = r.predicate or ""
            obj = r.object_ref
            text = obj if isinstance(obj, str) and obj.strip() else (r.subject_ref or "")
            if not text:
                continue
            ref = (
                f"{_ASSERT_DOC_PREFIX}{str(r.fact_id)}"
                if pred in _UTTERANCE_PREDICATES
                else f"{_EDGE_DOC_PREFIX}{str(r.fact_id)}"
            )
            self._upsert(
                conn,
                ref=ref,
                kind=RESULT_KIND_INTERPRETATION,
                text=text,
                source_id=None,
                segment_id=None,
                entity_ref=r.subject_ref,
                predicate=pred,
                seq=int(r.ledger_seq or 0),
            )

    # -- store writer ------------------------------------------------------

    def _upsert(
        self,
        conn: sa.Connection,
        *,
        ref: str,
        kind: str,
        text: str,
        source_id: Any,
        segment_id: Any,
        entity_ref: Any,
        predicate: str | None = None,
        seq: int,
    ) -> None:
        if not ref or not text:
            return
        values = {
            "id": _doc_id(kind, ref),
            "ref": ref,
            "kind": kind,
            "text": text,
            "language": None,
            "source_id": str(source_id) if source_id else None,
            "segment_id": str(segment_id) if segment_id else None,
            "entity_ref": str(entity_ref) if entity_ref else None,
            "predicate": predicate,
            "locator": None,
            "seq": seq,
        }
        stmt = sa.dialects.postgresql.insert(self._table).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_search_document_kind_ref",
            set_={
                "text": values["text"],
                "source_id": values["source_id"],
                "segment_id": values["segment_id"],
                "entity_ref": values["entity_ref"],
                "predicate": values["predicate"],
                "seq": values["seq"],
            },
        )
        conn.execute(stmt)


# ---------------------------------------------------------------------------
# Search service (read path)
# ---------------------------------------------------------------------------


@dataclass
class SearchFilters:
    """Typed locator/content filters (CONTRACTS: exact/full-text + locator filters)."""

    source_id: str | None = None
    segment_id: str | None = None
    entity_ref: str | None = None
    kind: str | None = None
    language: str | None = None
    locator_prefix: str | None = None


@dataclass
class KindTaggedSearchHit:
    ref: str
    kind: str
    text: str
    source_id: str | None
    segment_id: str | None
    entity_ref: str | None
    score: float
    exact_score: float | None
    vector_score: float | None
    label: str


@dataclass
class KindTaggedSearchPage:
    engine: str  # "exact" | "fuzzy" | "hybrid"
    vector_backend: str
    hits: list[KindTaggedSearchHit]
    total: int
    limit: int
    offset: int
    query: str


_KIND_LABEL = {
    RESULT_KIND_SOURCE_EVIDENCE: "source evidence",
    RESULT_KIND_INTERPRETATION: "interpretation",
    RESULT_KIND_CANONICAL_ENTITY: "canonical entity",
}


class SearchService:
    """Read path over a search projection (exact / fuzzy / hybrid).

    ``schema`` selects which search-document store to read: the public base store or a
    blue/green generation schema (pinned per-connection via ``search_path``).
    """

    def __init__(self, engine: sa.Engine, schema: str = "public") -> None:
        self._engine = engine
        self.schema = schema
        self._table = search_document_in(schema)

    # -- backend capability (honest disclosure) ----------------------------

    def vector_backend(self, vector_index: Any | None) -> str:
        from umd.projections.vector import PgHNSWIndex

        if vector_index is None:
            return "unavailable"
        if isinstance(vector_index, PgHNSWIndex):
            return "pgvector-hnsw-active" if vector_index.active() else "exact-fallback-active"
        return "exact-fallback-active" if vector_index.active() else "unavailable"

    # -- exact -------------------------------------------------------------

    def exact(
        self, query: str, filters: SearchFilters | None = None, *, limit: int = 20, offset: int = 0
    ) -> KindTaggedSearchPage:
        t = self._table
        conds = [t.c.search_tsv.op("@@")(sa.func.plainto_tsquery("simple", query))]
        conds = list(self._apply_filters(conds, filters))
        rank = sa.func.ts_rank(t.c.search_tsv, sa.func.plainto_tsquery("simple", query))
        stmt = (
            sa.select(
                t.c.ref,
                t.c.kind,
                t.c.text,
                t.c.source_id,
                t.c.segment_id,
                t.c.entity_ref,
                rank.label("score"),
            )
            .where(*conds)
            .order_by(sa.desc("score"), t.c.ref)
            .limit(limit)
            .offset(offset)
        )
        total = self._count(conds)
        hits = self._rows_to_hits(self._query(stmt), exact=True)
        return KindTaggedSearchPage(
            engine="exact",
            vector_backend="unavailable",
            hits=hits,
            total=total,
            limit=limit,
            offset=offset,
            query=query,
        )

    # -- fuzzy (pg_trgm) ----------------------------------------------------

    def fuzzy(
        self, query: str, filters: SearchFilters | None = None, *, limit: int = 20, offset: int = 0
    ) -> KindTaggedSearchPage:
        t = self._table
        conds = [t.c.text.op("%")(query)]
        conds = list(self._apply_filters(conds, filters))
        sim = sa.func.similarity(t.c.text, query)
        stmt = (
            sa.select(
                t.c.ref,
                t.c.kind,
                t.c.text,
                t.c.source_id,
                t.c.segment_id,
                t.c.entity_ref,
                sim.label("score"),
            )
            .where(*conds)
            .order_by(sa.desc("score"), t.c.ref)
            .limit(limit)
            .offset(offset)
        )
        total = self._count(conds)
        hits = self._rows_to_hits(self._query(stmt), exact=True)
        return KindTaggedSearchPage(
            engine="fuzzy",
            vector_backend="unavailable",
            hits=hits,
            total=total,
            limit=limit,
            offset=offset,
            query=query,
        )

    # -- hybrid -------------------------------------------------------------

    def hybrid(
        self,
        query: str,
        filters: SearchFilters | None = None,
        *,
        limit: int = 20,
        offset: int = 0,
        vector_index: Any | None = None,
        vector_weight: float = 0.5,
    ) -> KindTaggedSearchPage:
        """Fuse exact ``tsvector`` scores with pgvector/exact-vector cosine scores.

        Each hit carries a result-kind label (source evidence / interpretation /
        canonical entity) and both the exact and vector score it contributed. If no
        vector backend is active, hybrid degrades honestly to exact-only.
        """
        exact_page = self.exact(query, filters, limit=max(limit * 4, 40), offset=0)
        exact_scores = {h.ref: h.score for h in exact_page.hits}

        vector_scores: dict[str, float] = {}
        backend = "unavailable"
        if vector_index is not None:
            from umd.projections.vector import PgHNSWIndex

            try:
                if vector_index.active():
                    backend = (
                        "pgvector-hnsw-active"
                        if isinstance(vector_index, PgHNSWIndex)
                        else "exact-fallback-active"
                    )
                    qv = embed_text(query)
                    for ref, score in vector_index.search(qv, top_k=max(limit * 4, 40)):
                        vector_scores[str(ref)] = float(score)
                else:
                    backend = "exact-fallback-active"
                    qv = embed_text(query)
                    for ref, score in vector_index.search(qv, top_k=max(limit * 4, 40)):
                        vector_scores[str(ref)] = float(score)
            except Exception:  # noqa: BLE001 - never bubble a search to a 500
                backend = "unavailable"

        # Map vector result refs back to search docs for text/kind.
        vector_hits: dict[str, KindTaggedSearchHit] = {}
        if vector_scores:
            for h in self._by_refs(list(vector_scores.keys())):
                vector_hits[h.ref] = h

        fused: dict[str, tuple[float, float | None, float | None]] = {}
        for ref, es in exact_scores.items():
            vs = vector_scores.get(ref)
            fused[ref] = (self._fuse(es, vs, vector_weight), es, vs)
        for ref, vs in vector_scores.items():
            if ref in fused:
                continue
            eh = exact_scores.get(ref)
            fused[ref] = (self._fuse(eh, vs, vector_weight), eh, vs)

        ordered = sorted(fused.keys(), key=lambda r: fused[r][0], reverse=True)[
            offset : offset + limit
        ]
        by_ref = {h.ref: h for h in exact_page.hits} | vector_hits
        hits: list[KindTaggedSearchHit] = []
        for ref in ordered:
            base = by_ref.get(ref)
            fused_score, exact_part, vector_part = fused[ref]
            hits.append(
                KindTaggedSearchHit(
                    ref=ref,
                    kind=base.kind if base else RESULT_KIND_INTERPRETATION,
                    text=base.text if base else ref,
                    source_id=base.source_id if base else None,
                    segment_id=base.segment_id if base else None,
                    entity_ref=base.entity_ref if base else None,
                    score=fused_score,
                    exact_score=exact_part,
                    vector_score=vector_part,
                    label=_KIND_LABEL.get(
                        base.kind if base else RESULT_KIND_INTERPRETATION,
                        base.kind if base else "interpretation",
                    ),
                )
            )
        return KindTaggedSearchPage(
            engine="hybrid",
            vector_backend=backend,
            hits=hits,
            total=len(fused),
            limit=limit,
            offset=offset,
            query=query,
        )

    # -- internals ----------------------------------------------------------

    def _fuse(self, exact: float | None, vector: float | None, vw: float) -> float:
        exact = exact if exact is not None else 0.0
        vector = vector if vector is not None else 0.0
        ew = 1.0 - vw
        return round(ew * self._norm(exact) + vw * self._norm(vector), 6)

    @staticmethod
    def _norm(score: float) -> float:
        # Normalize arbitrary scores (ts_rank / cosine) into [0, 1] for fusion.
        if score <= 0:
            return 0.0
        return min(1.0, score)

    def _apply_filters(self, conds: list[Any], filters: SearchFilters | None) -> list[Any]:
        t = self._table
        if filters is None:
            return conds
        if filters.source_id:
            conds.append(t.c.source_id == filters.source_id)
        if filters.segment_id:
            conds.append(t.c.segment_id == filters.segment_id)
        if filters.entity_ref:
            conds.append(t.c.entity_ref == filters.entity_ref)
        if filters.kind:
            conds.append(t.c.kind == filters.kind)
        if filters.language:
            conds.append(t.c.language == filters.language)
        if filters.locator_prefix:
            conds.append(t.c.locator.like(f"{filters.locator_prefix}%"))
        return conds

    def _count(self, conds: list[Any]) -> int:
        with self._engine.connect() as conn:
            val = conn.execute(
                sa.select(sa.func.count()).select_from(self._table).where(*conds)
            ).scalar()
        return int(val or 0)

    def _query(self, stmt: Any) -> list[Any]:
        with self._engine.connect() as conn:
            return list(conn.execute(stmt).fetchall())

    def _by_refs(self, refs: list[str]) -> list[KindTaggedSearchHit]:
        if not refs:
            return []
        t = self._table
        stmt = sa.select(
            t.c.ref, t.c.kind, t.c.text, t.c.source_id, t.c.segment_id, t.c.entity_ref
        ).where(t.c.ref.in_(refs))
        return [
            KindTaggedSearchHit(
                ref=r.ref,
                kind=r.kind,
                text=r.text,
                source_id=r.source_id,
                segment_id=r.segment_id,
                entity_ref=r.entity_ref,
                score=0.0,
                exact_score=None,
                vector_score=None,
                label=_KIND_LABEL.get(r.kind, r.kind),
            )
            for r in self._query(stmt)
        ]

    def _rows_to_hits(self, rows: list[Any], *, exact: bool) -> list[KindTaggedSearchHit]:
        out: list[KindTaggedSearchHit] = []
        for r in rows:
            score = float(r.score or 0.0)
            out.append(
                KindTaggedSearchHit(
                    ref=r.ref,
                    kind=r.kind,
                    text=r.text,
                    source_id=r.source_id,
                    segment_id=r.segment_id,
                    entity_ref=r.entity_ref,
                    score=score,
                    exact_score=score if exact else None,
                    vector_score=None,
                    label=_KIND_LABEL.get(r.kind, r.kind),
                )
            )
        return out


__all__ = [
    "SearchProjectionBuilder",
    "SearchService",
    "SearchFilters",
    "KindTaggedSearchHit",
    "KindTaggedSearchPage",
]
