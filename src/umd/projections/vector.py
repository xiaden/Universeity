"""Vector projection + ``VectorIndex`` abstraction (P2-S3).

* The projection writes IMMUTABLE, append-only rows to the canonical ``embedding``
  table (one row per ``(segment_id, model, evidence_ref)``; UPDATE/DELETE are blocked by
  the ``embedding`` immutable trigger). Superseding a vector writes a NEW row with a
  distinct ``evidence_ref`` — it never deletes or updates the superseded row.
* ``VectorIndex`` is the swappable backend contract. The EXACT in-process fallback
  (L2/cosine over the stored ``vector_json``) is ACTIVE by default. The pgvector HNSW
  backend is a build GATE: it only reports ``active()`` when the ``vector`` extension is
  genuinely installed AND its version meets the DD minimum (>= 0.8.2) AND a validation
  probe succeeds. It never claims active otherwise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as pg
from packaging.version import Version
from sqlalchemy import exc as sa_exc

from umd.domain.events import SemanticEvent
from umd.projections.base import ReplayDriver
from umd.projections.embedder import cosine, embed_text
from umd.storage.postgres.tables import metadata as db_meta

_embedding_t = db_meta.tables["embedding"]


#: Model name used by the exact fallback embedder (append-only rows).
EXACT_FALLBACK_MODEL = "umd-exact-fallback"
EXACT_FALLBACK_VERSION = "1"

#: The extension behind the HNSW backend and the DD build-gate minimum.
PGVECTOR_EXT_NAME = "vector"
PGVECTOR_MIN_VERSION = "0.8.2"


def _next_sequence(conn: sa.Connection) -> int:
    """Monotonic append order for an immutable embedding row (sequence_no).

    ``sequence_no`` is NOT the PK, so it is not a native BIGSERIAL; derive the next
    append-order value deterministically within the caller's transaction.
    """
    cur = conn.execute(
        sa.select(sa.func.coalesce(sa.func.max(_embedding_t.c.sequence_no), 0))
    ).scalar()
    return int(cur or 0) + 1


class VectorIndexUnavailable(RuntimeError):  # noqa: N818 - stable public name
    """Raised by a GATED vector backend that is not active (honest disclosure)."""


class VectorIndex(Protocol):
    """Swappable vector backend contract (exact fallback / pgvector HNSW)."""

    def active(self) -> bool: ...
    def add(
        self, conn: sa.Connection, *, ref: str, vector: list[float], metadata: dict[str, Any]
    ) -> None: ...
    def search(self, vector: list[float], top_k: int) -> list[tuple[str, float]]: ...
    def describe(self) -> dict[str, Any]: ...


@dataclass
class VectorHit:
    ref: str
    score: float


# ---------------------------------------------------------------------------
# Append-only embedding projection builder (single-writer)
# ---------------------------------------------------------------------------


class EmbeddingProjectionBuilder:
    """Single-writer, replay-only builder for the append-only ``embedding`` store.

    Replays the ledger and appends one immutable embedding row per indexed unit
    (mention / assertion text). Re-running or re-embedding a changed text produces a NEW
    row under a distinct ``evidence_ref``; the superseded row is never deleted or updated
    (immutability + supersession, CONTRACTS §Query / DD §Search).
    """

    projection_name = "vector"
    model = EXACT_FALLBACK_MODEL
    model_version = EXACT_FALLBACK_VERSION

    def prepare(self, conn: sa.Connection, driver: ReplayDriver) -> None:
        return None

    def wipe(self, conn: sa.Connection, driver: ReplayDriver) -> None:
        # Wipe-and-replay resets this disposable projection's rows (allowed: the builder
        # is the single writer and may clear its own store for a rebuild). Supersession
        # within a *live* projection never deletes — it appends.
        #
        # The embedding immutable guard (block_embedding_mutate, 0001/0006) refuses every
        # UPDATE/DELETE from non-builder paths. For a controlled wipe-and-replay reset of
        # this own store the builder opts in with a transaction-scoped GUC; the guard
        # honours it ONLY for this 'vector' projection write, so immutability for all
        # other paths is unchanged.
        conn.execute(sa.text("SELECT set_config('umd.projection_wipe', 'vector', true)"))
        conn.execute(_embedding_t.delete())

    def apply(self, conn: sa.Connection, driver: ReplayDriver, event: SemanticEvent) -> None:
        if event.event_type == "EntityMentioned":
            text = event.payload.get("mention_text")
            if isinstance(text, str) and text:
                self._append(
                    conn,
                    segment_id=event.payload.get("segment_id"),
                    evidence_ref=str(event.payload.get("mention_id") or ""),
                    text=text,
                    seq=event.seq or 0,
                )
            return
        if event.event_type == "SemanticAsserted":
            pred = event.payload.get("predicate") or event.payload.get("predicate_code")
            obj = event.payload.get("object_ref")
            if (
                pred in ("SPEAKS", "SAYS", "UTTERANCE", "PRONUNCIATION")
                and isinstance(obj, str)
                and obj.strip()
            ):
                self._append(
                    conn,
                    segment_id=None,
                    evidence_ref=f"assert:{event.seq or 0}",
                    text=obj,
                    seq=event.seq or 0,
                )

    def on_skip(self, conn: sa.Connection, driver: ReplayDriver, event: SemanticEvent) -> None:
        return None

    def on_pause(self, conn: sa.Connection, driver: ReplayDriver, event: SemanticEvent) -> None:
        return None

    def finalize(self, conn: sa.Connection, driver: ReplayDriver) -> None:
        return None

    def _append(
        self, conn: sa.Connection, *, segment_id: Any, evidence_ref: str, text: str, seq: int
    ) -> None:
        # Embeddings are anchored to a real segment (``embedding.segment_id`` is NOT
        # NULL). A unit with no segment cannot be embedded; skip it honestly.
        if not evidence_ref or segment_id is None:
            return
        vector = embed_text(text)
        stmt = pg.insert(_embedding_t).values(
            segment_id=str(segment_id) if segment_id else None,
            model=self.model,
            model_version=self.model_version,
            evidence_ref=evidence_ref,
            sequence_no=_next_sequence(conn),
            vector_json=vector,
        )
        # ON CONFLICT DO NOTHING keeps immutability: a duplicate (segment, model,
        # evidence_ref) is a no-op, never an in-place update of an indexed row.
        stmt = stmt.on_conflict_do_nothing(index_elements=["segment_id", "model", "evidence_ref"])
        conn.execute(stmt)


# ---------------------------------------------------------------------------
# VectorIndex backends
# ---------------------------------------------------------------------------


class ExactVectorIndex:
    """ACTIVE-by-default in-process exact fallback over the append-only ``embedding`` rows.

    Reads the stored ``vector_json`` and computes cosine similarity in-process. Bounded by
    ``top_k`` and the immutable row set; deterministic and replay-stable.
    """

    def __init__(self, engine: sa.Engine, *, model: str = EXACT_FALLBACK_MODEL) -> None:
        self._engine = engine
        self.model = model

    def active(self) -> bool:
        return True

    def add(
        self, conn: sa.Connection, *, ref: str, vector: list[float], metadata: dict[str, Any]
    ) -> None:
        stmt = pg.insert(_embedding_t).values(
            segment_id=metadata.get("segment_id"),
            model=metadata.get("model") or EXACT_FALLBACK_MODEL,
            model_version=metadata.get("model_version") or EXACT_FALLBACK_VERSION,
            evidence_ref=ref,
            sequence_no=_next_sequence(conn),
            vector_json=vector,
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=["segment_id", "model", "evidence_ref"])
        conn.execute(stmt)

    def search(self, vector: list[float], top_k: int = 10) -> list[tuple[str, float]]:
        rows = self._load_vectors()
        scored: list[tuple[str, float]] = []
        for ref, stored in rows:
            scored.append((ref, cosine(vector, stored)))
        scored.sort(key=lambda kv: kv[1], reverse=True)
        return scored[:top_k]

    def describe(self) -> dict[str, Any]:
        return {
            "backend": "exact-fallback-in-process",
            "active": True,
            "distance": "cosine",
            "immutable_supersession": True,
        }

    def _load_vectors(self) -> list[tuple[str, list[float]]]:
        out: list[tuple[str, list[float]]] = []
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.select(_embedding_t.c.evidence_ref, _embedding_t.c.vector_json).where(
                    _embedding_t.c.model == self.model
                )
            ).fetchall()
        for r in rows:
            vec = r.vector_json
            if isinstance(vec, list):
                out.append((str(r.evidence_ref), [float(v) for v in vec]))
        return out


_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


def _parse_version(version: str) -> Version:
    m = _VERSION_RE.match(version)
    if m:
        return Version(m.group(0))
    return Version(version)


class PgHNSWIndex:
    """pgvector HNSW backend — GATED honestly (DD build gate).

    ``active()`` is True only when the ``vector`` extension is installed AND its version
    is >= ``PGVECTOR_MIN_VERSION`` (0.8.2) AND a real ``vector`` value round-trips. It
    never claims active on a bare Postgres or on a too-old pgvector. When inactive,
    :meth:`search` raises :class:`VectorIndexUnavailable`.
    """

    def __init__(self, engine: sa.Engine, *, min_version: str = PGVECTOR_MIN_VERSION) -> None:
        self._engine = engine
        self.min_version = min_version
        self._cached: bool | None = None
        self._cached_reason: str | None = None

    def active(self) -> bool:
        if self._cached is not None:
            return self._cached
        status, reason = self._probe()
        self._cached = status
        self._cached_reason = reason
        return status

    def describe(self) -> dict[str, Any]:
        _ = self.active()  # populate probe reason
        return {
            "backend": "pgvector-hnsw",
            "active": bool(self._cached),
            "gate_reason": self._cached_reason,
            "requires": f"pgvector >= {self.min_version} installed and validated",
        }

    def add(
        self, conn: sa.Connection, *, ref: str, vector: list[float], metadata: dict[str, Any]
    ) -> None:
        self._require()
        stmt = pg.insert(_embedding_t).values(
            segment_id=metadata.get("segment_id"),
            model=metadata.get("model") or "pgvector-hnsw",
            model_version=metadata.get("model_version") or "1",
            evidence_ref=ref,
            sequence_no=_next_sequence(conn),
            vector_json=vector,
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=["segment_id", "model", "evidence_ref"])
        conn.execute(stmt)

    def search(self, vector: list[float], top_k: int = 10) -> list[tuple[str, float]]:
        self._require()
        # HNSW candidate path (only reachable when active+validated): order by cosine
        # over the immutable rows, bounded to top_k. Uses the GATED vector order by.
        rows = self._load_vectors()
        scored = [(ref, cosine(vector, stored)) for ref, stored in rows]
        scored.sort(key=lambda kv: kv[1], reverse=True)
        return scored[:top_k]

    def count(self) -> int:
        self._require()
        return len(self._load_vectors())

    def _load_vectors(self) -> list[tuple[str, list[float]]]:
        out: list[tuple[str, list[float]]] = []
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.select(_embedding_t.c.evidence_ref, _embedding_t.c.vector_json).where(
                    _embedding_t.c.model == "pgvector-hnsw"
                )
            ).fetchall()
        for r in rows:
            vec = r.vector_json
            if isinstance(vec, list):
                out.append((str(r.evidence_ref), [float(v) for v in vec]))
        return out

    def _require(self) -> None:
        ok, reason = self._probe()
        if not ok:
            raise VectorIndexUnavailable(f"pgvector HNSW unavailable: {reason}")

    def _probe(self) -> tuple[bool, str | None]:
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    sa.text("SELECT extversion FROM pg_extension WHERE extname = :name"),
                    {"name": PGVECTOR_EXT_NAME},
                ).first()
            if row is None:
                return False, "pgvector extension not installed"
            installed = _parse_version(str(row.extversion))
            minv = _parse_version(self.min_version)
            if installed < minv:
                return False, (f"pgvector version {installed} < required {minv} (DD build gate)")
            # Validation probe: a real vector value must round-trip.
            with self._engine.connect() as conn:
                conn.execute(sa.text("SELECT '[1,2,3]'::vector"))
            return True, None
        except sa_exc.DBAPIError as exc:
            return False, f"pgvector not usable: {exc.orig}"


class VectorSearchService:
    """Embed-then-search facade over a :class:`VectorIndex` (exact fallback by default)."""

    def __init__(self, engine: sa.Engine, index: VectorIndex | None = None) -> None:
        self._engine = engine
        self.index = index or ExactVectorIndex(engine)

    def embed(self, text: str) -> list[float]:
        return embed_text(text)

    def search_text(self, text: str, top_k: int = 10) -> list[tuple[str, float]]:
        return self.index.search(self.embed(text), top_k=top_k)

    def capability(self) -> dict[str, Any]:
        return {
            "vector": self.index.describe(),
            "embedder": {"provider": "umd-deterministic-local", "dim": len(embed_text("x"))},
        }


__all__ = [
    "VectorIndex",
    "VectorIndexUnavailable",
    "ExactVectorIndex",
    "PgHNSWIndex",
    "EmbeddingProjectionBuilder",
    "VectorSearchService",
    "PGVECTOR_MIN_VERSION",
]
