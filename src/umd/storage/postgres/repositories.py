"""PostgreSQL-backed segment/source/quarantine repositories (Phase 2).

Production wiring for :class:`umd.segmentation.registry.SegmentRegistry` and
:class:`umd.resolution.locator_resolver.LocatorResolver` against the canonical
schema in ``umd.storage.postgres.tables``.

Invariants preserved end-to-end:
  * a user filename is never a key — segments are addressed by the deterministic
    key whose first component is the source content identity (sha512), never by
    ``original_name``;
  * the ``segment`` uniqueness constraint ``(source_id, deterministic_key)`` is
    honored (idempotent re-registration returns ``False`` / ``existing``);
  * unresolved locators land in the ``quarantine`` table as ``PATH_UNRESOLVED``,
    never silently repaired.
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa

from umd.domain.evidence import EvidenceBatch, RecordedEvidence, RecordedEvidenceBatch
from umd.domain.ids import deterministic_segment_id
from umd.domain.locators import PipelineVersion, parse_locator
from umd.domain.models import Evidence
from umd.resolution.locator_resolver import SourceRecord
from umd.segmentation.registry import RegisteredSegment
from umd.storage.ocfl import SourceStore
from umd.storage.postgres.tables import metadata as db_meta

_segment_t = db_meta.tables["segment"]
_source_t = db_meta.tables["source"]
_source_membership_t = db_meta.tables["source_membership"]
_quarantine_t = db_meta.tables["quarantine"]
_work_t = db_meta.tables["work"]
_evidence_t = db_meta.tables["evidence"]

#: PostgreSQL-dialect insert so ``on_conflict_do_nothing`` type-checks cleanly.
pg_insert = sa.dialects.postgresql.insert


def _uuid_hex() -> str:
    return uuid.uuid4().hex


class PostgresSegmentStore:
    """SegmentStore backed by the ``segment`` table."""

    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    def put(self, segment: RegisteredSegment) -> bool:
        """Insert a registered segment; ``False`` if ``(source_id, key)`` exists.

        ``UNIQUE(source_id, deterministic_key)`` is authoritative: a concurrent
        same-key put is deduplicated via ``ON CONFLICT DO NOTHING`` (returning
        ``False``) rather than surfacing an ``IntegrityError``.
        """
        with self._engine.begin() as conn:
            inserted = conn.execute(
                pg_insert(_segment_t)
                .values(
                    id=_uuid_hex(),
                    source_id=segment.source_id,
                    segment_type=segment.segment_type,
                    deterministic_key=segment.deterministic_key,
                    locator=segment.locator,
                    ordinal=segment.ordinal,
                    metadata_={},
                )
                .on_conflict_do_nothing()
                .returning(_segment_t.c.id)
            )
            return inserted.scalar() is not None

    def newest_version(
        self,
        _source_identity: str,
        modality: str,
        structural_path: str,
    ) -> PipelineVersion | None:
        # ``modality`` is an exact ``deterministic_key`` component; push it into
        # SQL so only candidate rows are read (not a full-table scan). The
        # redundant structural_path equality is finished in Python on the small
        # residue so behavior stays identical to the previous full-table fold.
        clause = _segment_t.c.deterministic_key.like(f"%#{modality}#%")
        with self._engine.connect() as conn:
            rows = conn.execute(sa.select(_segment_t).where(clause)).fetchall()
        versions = [
            s.version
            for s in self._rows_to_segments(rows)
            if s.modality == modality and s.structural_path == structural_path
        ]
        return max(versions, default=None)

    def find_by_locator(
        self, source_id: str, modality: str, segment_id: str
    ) -> list[RegisteredSegment]:
        clause = sa.and_(
            _segment_t.c.source_id == source_id,
            _segment_t.c.deterministic_key.like(f"%#{modality}#%"),
        )
        with self._engine.connect() as conn:
            rows = conn.execute(sa.select(_segment_t).where(clause)).fetchall()
        return [
            s
            for s in self._rows_to_segments(rows)
            if s.source_id == source_id and s.modality == modality and s.segment_id == segment_id
        ]

    def segments_for_source(self, source_id: str) -> list[RegisteredSegment]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.select(_segment_t).where(_segment_t.c.source_id == source_id)
            ).fetchall()
        return self._rows_to_segments(rows)

    def resolve_segment(self, segment_id: str) -> dict[str, Any] | None:
        """Resolve a segment id to its authoritative source + locator (P4-S8)."""
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    sa.select(_segment_t.c.source_id, _segment_t.c.locator).where(
                        _segment_t.c.id == segment_id
                    )
                ).first()
        except (ValueError, TypeError, sa.exc.DataError):
            # Non-UUID segment id -> treated as unknown (router surfaces 404, not 500).
            return None
        if row is None:
            return None
        return {"source_id": row.source_id, "locator": row.locator}

    # -- internals ---------------------------------------------------------

    def _rows_to_segments(self, rows: Any) -> list[RegisteredSegment]:
        """Map ``segment`` rows to :class:`RegisteredSegment` objects.

        Reconstruction is identical to the prior ``_all`` fold; callers push the
        ``source_id`` / modality predicates into SQL so we never scan the whole
        table into memory.
        """
        out: list[RegisteredSegment] = []
        for row in rows:
            parsed = parse_locator(row.locator)
            key = row.deterministic_key
            parts = key.split("#", 2)
            identity = parts[0]
            path = parts[2] if len(parts) == 3 else ""
            modality = parts[1] if len(parts) > 1 else parsed.modality
            out.append(
                RegisteredSegment(
                    source_id=row.source_id.hex,
                    deterministic_key=key,
                    segment_id=deterministic_segment_id(identity, modality, path),
                    segment_type=row.segment_type,
                    structural_path=path,
                    modality=modality,
                    version=parsed.version or PipelineVersion("unknown", "unknown", "unknown"),
                    locator=row.locator,
                    ordinal=row.ordinal,
                    is_new=False,
                )
            )
        return out


class PostgresSourceRepository:
    """SourceRepository backed by the ``source`` table (id = uuid hex)."""

    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    def get(self, source_id: str) -> SourceRecord | None:
        with self._engine.connect() as conn:
            row = conn.execute(sa.select(_source_t).where(_source_t.c.id == source_id)).first()
        if row is None:
            return None
        return SourceRecord(
            source_id=row.id.hex,
            ocfl_ref=row.ocfl_ref,
            sha512=row.sha512,
            size_bytes=row.size_bytes,
            media_kind=row.media_kind,
            work_id=row.work_id.hex if row.work_id else None,
            continuity_id=row.continuity_id.hex if row.continuity_id else None,
            edition_id=row.edition_id.hex if row.edition_id else None,
        )


class PostgresQuarantine:
    """QuarantineSink that records unresolved locators into the ``quarantine`` table."""

    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    def record(self, locator: str, reason: str, refs: list[str] | None = None) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                _quarantine_t.insert().values(
                    id=_uuid_hex(),
                    locator=locator,
                    reason=reason,
                    stage="resolution",
                    refs=refs or [],
                )
            )


class PostgresEvidenceRepository:
    """EvidenceRepository backed by the ``evidence`` table (CONTRACTS §Core).

    ``record(batch) -> EvidenceBatch`` idempotently inserts evidence rows. A row is
    considered a duplicate (``existing``) when another row already exists for the
    same ``(source_id, locator, evidence_kind, config_digest)``. Deduplication is
    DB-authoritative: the ``evidence`` table carries a UNIQUE constraint
    ``uq_evidence_identity`` on that quadruple, and inserts use ``ON CONFLICT DO
    NOTHING`` against it, so identical extraction output is never inserted twice
    — even across separate ``record`` calls or concurrent writers. All evidence
    rows carry the source locator, extraction stage, tool versions, config digest
    and confidence.
    """

    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    def record(self, batch: EvidenceBatch) -> RecordedEvidenceBatch:
        created: list[RecordedEvidence] = []
        existing: list[RecordedEvidence] = []
        seen: set[tuple[str, str, str, str]] = set()
        with self._engine.begin() as conn:
            for ev in batch.records:
                dedup_key = (
                    ev.source_id.hex if hasattr(ev.source_id, "hex") else str(ev.source_id),
                    ev.locator or "",
                    ev.evidence_kind.value
                    if hasattr(ev.evidence_kind, "value")
                    else str(ev.evidence_kind),
                    ev.config_digest or "",
                )
                if dedup_key in seen:
                    existing.append(self._to_recorded(ev, is_new=False))
                    continue
                seen.add(dedup_key)

                row_id = _uuid_hex()
                # The UNIQUE index ``uq_evidence_identity`` treats NULL and ''
                # alike only if we never store NULL in those columns, so coerce
                # empty locator/config_digest to '' (matching the in-memory dedup
                # key) to guarantee the DB-level duplicate check is authoritative.
                conf_digest = ev.config_digest or ""
                row = conn.execute(
                    pg_insert(_evidence_t)
                    .values(
                        id=row_id,
                        source_id=self._sid(ev.source_id),
                        segment_id=self._sid_opt(ev.segment_id),
                        evidence_kind=dedup_key[2],
                        locator=ev.locator or "",
                        language=ev.language,
                        track=ev.track,
                        raw_ref=ev.raw_ref,
                        normalized_ref=ev.normalized_ref,
                        artifact_ref=ev.artifact_ref,
                        extraction_stage=ev.extraction_stage,
                        tool_versions=ev.tool_versions or {},
                        config_digest=conf_digest,
                        confidence=ev.confidence,
                        quality=ev.quality or {},
                    )
                    .on_conflict_do_nothing(
                        index_elements=[
                            "source_id",
                            "locator",
                            "evidence_kind",
                            "config_digest",
                        ]
                    )
                    .returning(_evidence_t.c.id)
                )
                # ``inserted_primary_key`` is not reliable for validating a
                # conflict; ``returning(id)`` yields NULL exactly when the row was
                # deduplicated by the unique index (no row inserted).
                if row.scalar() is not None:
                    created.append(self._to_recorded(ev, is_new=True))
                else:
                    existing.append(self._to_recorded(ev, is_new=False))
        return RecordedEvidenceBatch(created=created, existing=existing, total=len(batch.records))

    def get_by_source(self, source_id: str) -> list[Evidence]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.select(_evidence_t).where(_evidence_t.c.source_id == source_id)
            ).fetchall()
        return self._rows_to_evidence(rows)

    def get_by_segment(self, segment_id: str) -> list[Evidence]:
        """Segment-scoped indexed evidence lookup (CONTRACTS §Query, P4-S8).

        Returns only evidence rows whose ``segment_id`` matches, never another
        segment's/source's evidence. Indexed via ``evidence.segment_id``.
        """
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.select(_evidence_t).where(_evidence_t.c.segment_id == segment_id)
            ).fetchall()
        return self._rows_to_evidence(rows)

    def get(self, locator_or_range: str) -> Evidence | None:
        """Resolve a single evidence row by id (locator/evidence-ref)."""
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.select(_evidence_t).where(_evidence_t.c.id == locator_or_range)
            ).first()
        if row is None:
            return None
        return self._rows_to_evidence([row])[0]

    def _rows_to_evidence(self, rows: Any) -> list[Evidence]:
        out: list[Evidence] = []
        for r in rows:
            out.append(
                Evidence(
                    id=r.id,
                    source_id=r.source_id,
                    segment_id=r.segment_id,
                    evidence_kind=r.evidence_kind,
                    locator=r.locator,
                    language=r.language,
                    track=r.track,
                    raw_ref=r.raw_ref,
                    normalized_ref=r.normalized_ref,
                    artifact_ref=r.artifact_ref,
                    extraction_stage=r.extraction_stage,
                    tool_versions=r.tool_versions or {},
                    config_digest=r.config_digest,
                    confidence=r.confidence,
                    quality=r.quality or {},
                )
            )
        return out

    @staticmethod
    def _to_recorded(ev: Evidence, *, is_new: bool) -> RecordedEvidence:
        return RecordedEvidence(
            id=str(getattr(ev, "id", None) or ""),
            source_id=PostgresEvidenceRepository._sid(ev.source_id),
            segment_id=PostgresEvidenceRepository._sid_opt(ev.segment_id),
            evidence_kind=(
                ev.evidence_kind.value
                if hasattr(ev.evidence_kind, "value")
                else str(ev.evidence_kind)
            ),
            locator=ev.locator,
            is_new=is_new,
        )

    @staticmethod
    def _sid(value: Any) -> str:
        return value.hex if hasattr(value, "hex") else str(value)

    @staticmethod
    def _sid_opt(value: Any) -> str | None:
        if value is None:
            return None
        return PostgresEvidenceRepository._sid(value)


class OcflByteSource:
    """ByteSource over the immutable OCFL SourceStore (fixity verified)."""

    def __init__(self, store: SourceStore) -> None:
        self._store = store

    def get_range(self, source_ref: str, start: int, length: int) -> bytes:
        rep = self._store.get_range(source_ref, start, length)
        return rep.data

    def verify(self, source_ref: str, _sha512: str, _size_bytes: int) -> bool:
        return self._store.verify_fixity(source_ref)


class SourceMembershipService:
    """Work membership for byte-different re-uploads (SourceAliased grouping).

    Groups byte-different re-uploads of the same work into shared work membership
    (role ``primary`` + ``alias`` / ``related``) without deduplicating — each
    source keeps its own content-derived segment keys.
    """

    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    def find_source_by_sha512(self, sha512: str) -> tuple[str, str | None] | None:
        """Content-addressed lookup: existing ``(source_id, work_id)`` for bytes."""
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.select(_source_t.c.id, _source_t.c.work_id).where(_source_t.c.sha512 == sha512)
            ).first()
        if row is None:
            return None
        wid = row.work_id.hex if row.work_id else None
        return (row.id.hex, wid)

    def ensure_source(
        self,
        *,
        source_id: str,
        ocfl_ref: str,
        sha512: str,
        size_bytes: int,
        media_kind: str,
        original_name: str,
        work_id: str | None,
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                _source_t.insert().values(
                    id=source_id,
                    ocfl_ref=ocfl_ref,
                    sha512=sha512,
                    size_bytes=size_bytes,
                    media_kind=media_kind,
                    original_name=original_name,
                    work_id=work_id,
                    descriptor={},
                )
            )

    def add_membership(self, *, source_id: str, work_id: str, role: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                _source_membership_t.insert().values(
                    id=_uuid_hex(), source_id=source_id, work_id=work_id, role=role
                )
            )

    def memberships(self, work_id: str) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.select(
                    _source_membership_t.c.source_id,
                    _source_membership_t.c.work_id,
                    _source_membership_t.c.role,
                ).where(_source_membership_t.c.work_id == work_id)
            ).fetchall()
        return [{"source_id": r.source_id, "role": r.role} for r in rows]

    def ensure_work(self, *, work_id: str, title: str, work_type: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(_work_t.insert().values(id=work_id, title=title, work_type=work_type))
