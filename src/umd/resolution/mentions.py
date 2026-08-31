"""Persisted source mentions with provenance and confidence states (P1-S1).

Implements the DD §Reversible entity resolution requirement to *persist every
source mention* — names, scripts, transliterations, titles, nicknames, OCR
forms, speaker labels, face clusters, unknown placeholders and candidate sets —
carrying exact provenance back to source evidence and an explicit confidence
state.

Representation
--------------
A mention maps onto the canonical ``entity_mention`` table row plus an
``EntityMentioned`` semantic event appended to the ledger. The typed columns
(``mention_text``, ``normalized_forms``, ``speaker_label``, ``face_cluster``)
hold the surface form; provenance, candidate set, confidence state and mention
kind live in the JSONB ``metadata_`` extension field (the DD's typed-core-plus-
JSONB rule). The ``mention_id`` in the event payload is the row id, so the event
and the row are traceable.

Invariants
----------
  * provenance always names source/segment/evidence refs, never an untrusted
    filename or path — a surface form is never a storage key;
  * recording a mention appends the ``EntityMentioned`` event AND writes the
    ``entity_mention`` row atomically through the ledger's side-effects path
    (both commit or neither commits);
  * candidate sets and confidence states are *represented* as a typed model and
    persisted — they are evidence about identity, never a fabricated canonical
    decision.

Plan N canonical-reference representation (v1 — Option B, CONTRACTS.md):
  production text resolution is *ledger-first*. The resolved canonical ref is a
  deterministic, source-independent STRING (``entity:canonical:<sha256-16hex>``
  — per Plan S P1-S2, replacing the earlier source-bound
  ``entity:canonical:<src>:<digest>`` form) carried in the immutable
  ``EntityMentioned`` payload and reducer-backed ``current_state``;
  ``entity_mention.entity_id`` is a nullable UUID FK, so a non-UUID ref is
  stored NULL on the row (never coerced, never fabricated into an ``entity``
  row). Valid UUID refs (legacy UUID-backed materialized paths) are still
  stored as-is. Reruns are idempotent (the deterministic mention id is the
  ledger idempotency key); nothing is ever deleted or mutated in place.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Protocol

import sqlalchemy as sa
from pydantic import BaseModel, Field

from umd.analysis.semantic import SemanticAnalysisResult
from umd.domain.events import SemanticEvent
from umd.domain.models import ConfidenceState
from umd.storage.postgres.ledger import CommitResult, SemanticLedger
from umd.storage.postgres.tables import metadata as db_meta

_mention_t = db_meta.tables["entity_mention"]

pg_insert = sa.dialects.postgresql.insert


def _uuid_hex() -> str:
    return uuid.uuid4().hex


def uuid_ref_or_none(entity_id: str | None) -> str | None:
    """Map an entity ref to the ``entity_mention.entity_id`` FK column value (P4-S3).

    Option B: ``entity_mention.entity_id`` is a nullable UUID FK. A valid UUID
    ref (legacy UUID-backed path) is passed through; a non-UUID STRING canonical
    ref (the ledger-first text-resolution representation) binds as NULL — the
    immutable ``EntityMentioned`` event retains the string ref, so the typed
    row never receives a non-UUID value (which would raise an ``SAUuid`` bind
    error). ``None`` stays ``None``.
    """
    if not entity_id:
        return None
    try:
        uuid.UUID(str(entity_id))
    except (ValueError, TypeError, AttributeError):
        return None
    return str(entity_id)


#: Stable mention-kind vocabulary (DD §Reversible entity resolution).
MENTION_KINDS: tuple[str, ...] = (
    "name",
    "script",
    "transliteration",
    "title",
    "nickname",
    "ocr_form",
    "speaker_label",
    "face_cluster",
    "unknown_placeholder",
    "candidate_set",
)

#: Metadata keys consumed as typed mention fields (not free extension data).
_RESERVED_METADATA = frozenset(
    {
        "mention_kind",
        "confidence_state",
        "confidence",
        "language",
        "script",
        "provenance",
        "candidates",
    }
)


class MentionCandidate(BaseModel):
    """One candidate entity for a mention, with its supporting confidence."""

    entity_ref: str
    confidence: float
    role: str = "candidate"  # candidate|canonical|unknown


class SourceMention(BaseModel):
    """A source mention pinned to evidence, with provenance + confidence state.

    Plan S (P1-S1): the mention remains a **source-local** record. It may carry
    optional work/continuity membership scope (``work_id``/``continuity_id``) so a
    canonical cluster can aggregate membership context; the mention itself is
    never promoted to a cross-source entity. ``entity_id`` for a non-UUID string
    canonical ref stays NULL on the typed row (nullable UUID FK, Option B).
    """

    id: uuid.UUID | None = None
    source_id: str
    segment_id: str | None = None
    entity_id: str | None = None
    mention_text: str
    mention_kind: str = "name"
    normalized_forms: list[str] = Field(default_factory=list)
    speaker_label: str | None = None
    face_cluster: str | None = None
    confidence_state: str = ConfidenceState.UNKNOWN.value
    confidence: float | None = None
    language: str | None = None
    script: str | None = None
    candidates: list[MentionCandidate] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    metadata_: dict[str, Any] = Field(default_factory=dict)
    #: Optional work/continuity membership scope (Plan S P1-S1): the mention
    #: stays source-local; these carry the scope a canonical cluster aggregates.
    work_id: str | None = None
    continuity_id: str | None = None

    @property
    def mention_id(self) -> str:
        return str(self.id) if self.id is not None else self._computed_id

    @property
    def _computed_id(self) -> str:
        # Deterministic pre-insert mention id so split-time rebound references
        # and replay stay stable even before the row id is assigned.
        raw = f"{self.source_id}\x1f{self.mention_text}\x1f{self.segment_id or ''}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def to_event(self) -> SemanticEvent:
        """The ``EntityMentioned`` semantic event for this mention."""
        authority = (
            "USER_OVERRIDE"
            if self.confidence_state == ConfidenceState.USER_CONFIRMED.value
            else "machine"
        )
        return SemanticEvent(
            event_type="EntityMentioned",
            authority=authority,
            confidence=self.confidence,
            generated_by=self.provenance.get("generated_by") or {},
            payload={
                "mention_id": self.mention_id,
                "source_id": self.source_id,
                "entity_id": self.entity_id,
                "segment_id": self.segment_id,
                "mention_text": self.mention_text,
                "normalized_forms": self.normalized_forms,
                "speaker_label": self.speaker_label,
            },
        )

    def _metadata_blob(self) -> dict[str, Any]:
        blob: dict[str, Any] = {
            "mention_kind": self.mention_kind,
            "confidence_state": self.confidence_state,
            "confidence": self.confidence,
            "language": self.language,
            "script": self.script,
            "provenance": self.provenance,
            **self.metadata_,
        }
        if self.candidates:
            blob["candidates"] = [
                {"entity_ref": c.entity_ref, "confidence": c.confidence, "role": c.role}
                for c in self.candidates
            ]
        return blob


class MentionRepository(Protocol):
    """Persists source mentions (the ``entity_mention`` table)."""

    def record(self, mention: SourceMention) -> str: ...
    def get(self, mention_id: str) -> SourceMention | None: ...
    def mentions_for_source(self, source_id: str) -> list[SourceMention]: ...
    def mentions_for_entity(self, entity_id: str) -> list[SourceMention]: ...
    def rebind(self, mention_id: str, entity_id: str | None) -> None: ...


@dataclass
class RecordedMention:
    """Result of recording one mention."""

    mention_id: str
    is_new: bool


def _deterministic_mention_id(
    source_id: str, locator: str, segment_id: str | None, mention_text: str
) -> str:
    """A deterministic sha256 mention id keyed by source/segment/span identity.

    P1-S1: two mentions are the *same* mention only when they share the source,
    the exact segment/span (``locator``, and ``segment_id`` where registered) and
    the surface text. Confidence, provenance and candidate-set differences never
    change the id, so a deterministic re-run converges to the same mention row
    (idempotent) rather than appending a duplicate. Returns a 32-char hex digest
    that :class:`uuid.UUID` can parse (matching the ``_computed_id`` convention).
    """
    raw = f"{source_id}\x1f{locator}\x1f{segment_id or ''}\x1f{mention_text}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _co_occurrence_by_locator(result: SemanticAnalysisResult) -> dict[str, list[str]]:
    """Co-occurring entity names per exact locator, from relationship observations.

    Deterministic (sorted) so the resulting mention metadata is stable across
    reruns. ``CO_OCCURS`` is the deterministic structural baseline predicate
    (:mod:`umd.analysis.text_structural`).
    """
    by_locator: dict[str, set[str]] = defaultdict(set)
    for rel in result.relationships:
        if rel.predicate not in ("CO_OCCURS", "CO_OCCURS_WITH"):
            continue
        if rel.subject_ref:
            by_locator[rel.segment.locator].add(rel.subject_ref)
        if rel.object_ref:
            by_locator[rel.segment.locator].add(rel.object_ref)
    return {loc: sorted(vals) for loc, vals in by_locator.items()}


def _mention_provenance(candidate: Any) -> dict[str, Any]:
    """Exact support refs + provider provenance from a typed observation."""
    seg = candidate.segment
    generated = candidate.generated_by
    generated_by = generated.model_dump() if hasattr(generated, "model_dump") else dict(generated)
    return {
        "locator": seg.locator,
        "evidence_ref": seg.evidence_ref,
        "chapter": seg.chapter,
        "paragraph": seg.paragraph,
        "segment_id": seg.segment_id,
        "generated_by": generated_by,
    }


def _mention_metadata(candidate: Any, co_occurring: list[str]) -> dict[str, Any]:
    """Type/context metadata retained on the mention (never fabricated)."""
    meta: dict[str, Any] = {"entity_type": candidate.entity_type}
    if co_occurring:
        meta["co_occurring"] = co_occurring
    return meta


def mentions_from_semantic(result: SemanticAnalysisResult) -> list[SourceMention]:
    """Bridge typed semantic-analysis observations into deterministic mentions (P1-S1).

    Converts the Plan M typed observations (:class:`EntityMention` and
    :class:`NormalizedAlias`) into persisted-resolution :class:`SourceMention`
    records. Each mention is keyed by source/segment/span identity through a
    deterministic sha256 mention id (:func:`_deterministic_mention_id`) and retains:

      * the normalized form(s) via the existing ``normalize_name`` machinery;
      * the mention kind (``name`` for entity mentions; aliases keep ``name`` and
        carry their canonical mapping in metadata, staying within the closed
        :data:`MENTION_KINDS` vocabulary);
      * the speaker label where the observation carries one (typed observations
        do not, so it stays ``None``);
      * type/context/co-occurrence metadata;
      * exact support refs (locator / evidence_ref / chapter / paragraph /
        segment_id) and full provider provenance (``generated_by``);
      * the observation confidence and semantic state.

    Purely a projection over the observation result — it writes nothing. Prior
    mention/evidence rows are never touched. ``entity_ref`` from an alias
    observation becomes the mention's initial ``entity_id`` only when the
    observation names a canonical entity (provider-backed); ambiguous aliases
    leave it ``None`` and stay reviewable.
    """
    from umd.resolution.candidates import normalize_name  # lazy: candidates imports mentions

    co_occurrence = _co_occurrence_by_locator(result)
    out: list[SourceMention] = []
    seen: set[str] = set()

    for em in result.entity_mentions:
        sid = _deterministic_mention_id(
            result.source_id, em.segment.locator, em.segment.segment_id, em.mention
        )
        if sid in seen:
            continue
        seen.add(sid)
        out.append(
            SourceMention(
                id=uuid.UUID(sid),
                source_id=result.source_id,
                segment_id=em.segment.segment_id,
                mention_text=em.mention,
                mention_kind="name",
                normalized_forms=[f for f in (normalize_name(em.mention),) if f],
                confidence_state=em.state.value,
                confidence=em.confidence,
                provenance=_mention_provenance(em),
                metadata_=_mention_metadata(em, co_occurrence.get(em.segment.locator, [])),
            )
        )

    for alias in result.aliases:
        sid = _deterministic_mention_id(
            result.source_id, alias.segment.locator, alias.segment.segment_id, alias.alias
        )
        if sid in seen:
            continue
        seen.add(sid)
        forms = [normalize_name(alias.alias), normalize_name(alias.canonical_name)]
        out.append(
            SourceMention(
                id=uuid.UUID(sid),
                source_id=result.source_id,
                segment_id=alias.segment.segment_id,
                entity_id=alias.entity_ref,
                mention_text=alias.alias,
                mention_kind="name",
                normalized_forms=[f for f in forms if f],
                confidence_state=alias.state.value,
                confidence=alias.confidence,
                provenance=_mention_provenance(alias),
                metadata_={
                    "entity_type": "character",
                    "canonical_name": alias.canonical_name,
                    "entity_ref": alias.entity_ref,
                },
            )
        )

    return out


class PostgresMentionRepository:
    """``MentionRepository`` backed by the ``entity_mention`` table."""

    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    def record(self, mention: SourceMention) -> str:
        mid = str(self._row_values(mention)["id"])
        with self._engine.begin() as conn:
            conn.execute(
                pg_insert(_mention_t)
                .values(**self._row_values(mention))
                .on_conflict_do_nothing(index_elements=["id"])
            )
        return mid

    def get(self, mention_id: str) -> SourceMention | None:
        with self._engine.connect() as conn:
            r = conn.execute(sa.select(_mention_t).where(_mention_t.c.id == mention_id)).first()
        return self._to_mention(r) if r is not None else None

    def mentions_for_source(self, source_id: str) -> list[SourceMention]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.select(_mention_t).where(_mention_t.c.source_id == source_id)
            ).fetchall()
        return [self._to_mention(r) for r in rows]

    def mentions_for_entity(self, entity_id: str) -> list[SourceMention]:
        # Option B: a non-UUID STRING canonical ref cannot exist in the UUID FK
        # (rows store NULL for it); binding it here would raise an SAUuid error.
        # Such mentions are discovered via ledger events, not the typed row.
        if uuid_ref_or_none(entity_id) is None:
            return []
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.select(_mention_t).where(_mention_t.c.entity_id == entity_id)
            ).fetchall()
        return [self._to_mention(r) for r in rows]

    def rebind(self, mention_id: str, entity_id: str | None) -> None:
        """Re-point a mention at an entity (split/merge rebound).

        Option B (P4-S4): only a UUID-compatible target is written to the UUID
        ``entity_id`` FK. A non-UUID STRING canonical ref (ledger-first text
        resolution) is skipped — the mention's resolution already lives in the
        immutable ledger events, so a typed-row UPDATE is neither possible nor
        needed (no second authority). ``None`` (unbind) still writes NULL for
        the legacy UUID path.
        """
        if not mention_id:
            return
        bound: str | None
        if entity_id is None:
            bound = None  # unbind -> NULL (legacy path)
        elif uuid_ref_or_none(entity_id) is None:
            return  # non-UUID string ref -> ledger owns the resolution
        else:
            bound = str(entity_id)
        with self._engine.begin() as conn:
            conn.execute(
                _mention_t.update().where(_mention_t.c.id == mention_id).values(entity_id=bound)
            )

    @staticmethod
    def _row_values(mention: SourceMention) -> dict[str, Any]:
        return {
            "id": str(mention.id) if mention.id is not None else _uuid_hex(),
            "entity_id": uuid_ref_or_none(mention.entity_id),
            "source_id": mention.source_id,
            "segment_id": mention.segment_id,
            "mention_text": mention.mention_text,
            "normalized_forms": mention.normalized_forms or [],
            "speaker_label": mention.speaker_label,
            "face_cluster": mention.face_cluster,
            "metadata_": mention._metadata_blob(),
        }

    @staticmethod
    def _to_mention(r: Any) -> SourceMention:
        meta = dict(r.metadata_ or {})
        return SourceMention(
            id=r.id,
            source_id=PostgresMentionRepository._sid(r.source_id),
            segment_id=PostgresMentionRepository._sid(r.segment_id) if r.segment_id else None,
            entity_id=PostgresMentionRepository._sid(r.entity_id) if r.entity_id else None,
            mention_text=r.mention_text,
            mention_kind=meta.get("mention_kind", "name"),
            normalized_forms=[str(f) for f in (r.normalized_forms or [])],
            speaker_label=r.speaker_label,
            face_cluster=r.face_cluster,
            confidence_state=meta.get("confidence_state", ConfidenceState.UNKNOWN.value),
            confidence=meta.get("confidence"),
            language=meta.get("language"),
            script=meta.get("script"),
            candidates=[
                MentionCandidate(**c) for c in meta.get("candidates") or [] if isinstance(c, dict)
            ],
            provenance=dict(meta.get("provenance") or {}),
            metadata_={k: v for k, v in meta.items() if k not in _RESERVED_METADATA},
        )

    @staticmethod
    def _sid(value: Any) -> str:
        return value.hex if hasattr(value, "hex") else str(value)


@dataclass
class MentionService:
    """Appends an ``EntityMentioned`` event and persists its row atomically."""

    ledger: SemanticLedger
    repository: MentionRepository

    def record(self, mention: SourceMention) -> tuple[CommitResult, str]:
        """Persist the mention row and append its event in ONE transaction.

        Returns ``(commit, mention_id)``. The row is written via
        ``complete_and_append`` side-effects so the event and the row commit
        atomically — a crash cannot leave an event without its mention row.

        P1-S3 idempotency: when no id is supplied the deterministic
        ``_computed_id`` (source/segment/span key) is used, and that same key is
        passed as the ledger ``idempotency_key``. A retry therefore converges to
        the SAME mention row (``on_conflict_do_nothing``) and the SAME
        ``EntityMentioned`` event seq (ledger dedup) — never a duplicate row or a
        second authoritative completion. Prior evidence and mention history are
        never mutated or deleted.
        """
        mid = str(mention.id) if mention.id is not None else mention._computed_id
        mention = mention.model_copy(update={"id": uuid.UUID(mid)})
        event = mention.to_event()

        def _side(conn: sa.Connection) -> None:
            conn.execute(
                pg_insert(_mention_t)
                .values(**PostgresMentionRepository._row_values(mention))
                .on_conflict_do_nothing(index_elements=["id"])
            )

        result = self.ledger.complete_and_append(
            events=[event], idempotency_key=mid, side_effects=_side
        )
        return result, mid
