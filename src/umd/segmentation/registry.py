"""Deterministic segment registry (Phase 2 / P2-S2).

Implements the binding contract ``SegmentRegistry.register(batch) -> SegmentBatch``
with deterministic stable segment IDs and versioned locators, and rejects
byte-offset-only locators.

Determinism: the segment id and DB ``deterministic_key`` derive from canonical
source/work *content identity* + modality + structural path — never a user
filename. The same (content, modality, path) always registers to the same key.
A byte-different re-upload (``SourceAliased``) produces a different sha512,
hence a distinct segment, without deduplicating the two sources.

Versioning: each registration carries a :class:`PipelineVersion` derived from
segmenter.decoder.renderer. Old ``@v...`` locators stay addressable; bare
resolution (P2-S3) selects the newest compatible version.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Protocol

from pydantic import BaseModel, Field

from umd.domain.ids import canonical_identity, deterministic_key, deterministic_segment_id
from umd.domain.locators import (
    ByteOffsetSelector,
    Locator,
    PipelineVersion,
    Selector,
    build_locator,
)


class SegmentInput(BaseModel):
    """A segment to register within a batch."""

    source_id: str = Field(max_length=256)
    source_sha512: str = Field(min_length=128, max_length=128)
    work_id: str | None = Field(default=None, max_length=256)
    modality: str = Field(max_length=32)
    structural_path: str = Field(max_length=512)
    segment_type: str = Field(max_length=64)
    version: PipelineVersion
    frag: Selector | None = None
    ordinal: int | None = None
    parent_path: str | None = None
    metadata_: dict[str, Any] = Field(default_factory=dict)


class RegisteredSegment(BaseModel):
    """A successfully registered segment with its canonical locator."""

    source_id: str
    deterministic_key: str
    segment_id: str
    segment_type: str
    structural_path: str
    modality: str
    version: PipelineVersion
    locator: str
    ordinal: int | None = None
    is_new: bool = True


class SegmentBatch(BaseModel):
    """Result of :meth:`SegmentRegistry.register`.

    ``created`` are newly registered segments; ``existing`` are deterministic
    duplicates already present (idempotent re-registration). ``total`` counts
    all accepted inputs.
    """

    created: list[RegisteredSegment] = Field(default_factory=list)
    existing: list[RegisteredSegment] = Field(default_factory=list)
    total: int = 0


class SegmentStore(Protocol):
    """Storage boundary for the registry (in-memory for unit tests;

    PostgreSQL-backed for production — see ``umd.storage.postgres.repositories``).
    """

    @abstractmethod
    def put(self, segment: RegisteredSegment) -> bool:
        """Persist a segment; return True if newly created, False if duplicate."""
        ...

    @abstractmethod
    def newest_version(
        self,
        _source_identity: str,
        modality: str,
        structural_path: str,
    ) -> PipelineVersion | None:
        """Newest compatible PipelineVersion registered for the path."""
        ...

    @abstractmethod
    def find_by_locator(
        self, source_id: str, modality: str, segment_id: str
    ) -> list[RegisteredSegment]:
        """All versions registered for a segment id (locator lookup)."""
        ...

    @abstractmethod
    def segments_for_source(self, source_id: str) -> list[RegisteredSegment]:
        """Every registered segment for a source."""
        ...


class InMemorySegmentStore:
    """Deterministic in-memory segment store for unit/property tests.

    Multiple pipeline versions of the same (source, deterministic_key) may coexist
    (one entry per ``@v`` tag) so explicit-vs-bare resolution and version drift
    can be exercised. The PostgreSQL store instead honors the DB uniqueness
    constraint ``(source_id, deterministic_key)`` (single row per key, newest wins).
    """

    def __init__(self) -> None:
        self._by_tag: dict[tuple[str, str, str], RegisteredSegment] = {}
        self._by_key: dict[tuple[str, str], list[RegisteredSegment]] = {}
        self._by_segid: dict[tuple[str, str, str], list[RegisteredSegment]] = {}

    def put(self, segment: RegisteredSegment) -> bool:
        key = (segment.source_id, segment.deterministic_key)
        tag = segment.version.tag if segment.version else ""
        tag_key = (segment.source_id, segment.deterministic_key, tag)
        is_new = tag_key not in self._by_tag
        if is_new:
            self._by_tag[tag_key] = segment
            if segment.version:
                self._by_key.setdefault(key, []).append(segment)
                self._by_key[key].sort(
                    key=lambda s: (s.version.version, s.version.tag), reverse=True
                )
            self._by_segid.setdefault(
                (segment.source_id, segment.modality, segment.segment_id), []
            ).append(segment)
        return is_new

    def newest_version(
        self,
        _source_identity: str,
        modality: str,
        structural_path: str,
    ) -> PipelineVersion | None:
        candidates = [
            s.version
            for segs in self._by_key.values()
            for s in segs
            if s.modality == modality and s.structural_path == structural_path
        ]
        return max(candidates, default=None)

    def find_by_locator(
        self, source_id: str, modality: str, segment_id: str
    ) -> list[RegisteredSegment]:
        return list(self._by_segid.get((source_id, modality, segment_id), []))

    def segments_for_source(self, source_id: str) -> list[RegisteredSegment]:
        return [seg for (sid, _k, _t), seg in self._by_tag.items() if sid == source_id]


class SegmentRegistry:
    """Registers deterministic segments with stable IDs and versioned locators."""

    def __init__(self, store: SegmentStore) -> None:
        self._store = store

    def register(self, batch: list[SegmentInput]) -> SegmentBatch:
        """Register a batch of segments, returning a ``SegmentBatch`` result.

        Each input is built into a :class:`RegisteredSegment` and persisted via
        the backing :class:`SegmentStore`; already-present ``(source_id,
        deterministic_key)`` keys are reported as ``existing`` (idempotent) and
        byte-different re-uploads yield distinct keys. Byte-offset-only locators
        are rejected before any side effect.

        :param batch: segment inputs to register.
        :return: ``SegmentBatch(created, existing, total)`` — ``created`` lists
            newly-registered segments, ``existing`` the idempotent duplicates.
        """
        created: list[RegisteredSegment] = []
        existing: list[RegisteredSegment] = []
        for inp in batch:
            seg = self._build(inp)
            if seg is None:
                continue
            is_new = self._store.put(seg)
            seg.is_new = is_new
            (created if is_new else existing).append(seg)
        return SegmentBatch(created=created, existing=existing, total=len(batch))

    def _build(self, inp: SegmentInput) -> RegisteredSegment | None:
        # Reject byte-offset-only locators before any registration side effect.
        if isinstance(inp.frag, ByteOffsetSelector) and not inp.structural_path:
            from umd.domain.locators import ByteOffsetLocatorError

            raise ByteOffsetLocatorError(
                f"byte-offset-only segment rejected: {inp.structural_path!r}"
            )

        identity = canonical_identity(inp.source_sha512, inp.work_id)
        segment_id = deterministic_segment_id(identity, inp.modality, inp.structural_path)
        key = deterministic_key(identity, inp.modality, inp.structural_path)
        locator = build_locator(
            source_id=inp.source_id,
            modality=inp.modality,
            structural_path=inp.structural_path,
            canonical_identity=identity,
            version=inp.version,
            frag=inp.frag,
        )
        return RegisteredSegment(
            source_id=inp.source_id,
            deterministic_key=key,
            segment_id=segment_id,
            segment_type=inp.segment_type,
            structural_path=inp.structural_path,
            modality=inp.modality,
            version=inp.version,
            locator=locator.canonical(),
            ordinal=inp.ordinal,
        )

    def resolve_newest_locator(
        self,
        source_id: str,
        modality: str,
        structural_path: str,
        source_sha512: str,
        work_id: str | None = None,
    ) -> Locator | None:
        """Canonical locator of the newest compatible version for a bare reference."""
        identity = canonical_identity(source_sha512, work_id)
        version = self._store.newest_version(identity, modality, structural_path)
        if version is None:
            return None
        return build_locator(
            source_id=source_id,
            modality=modality,
            structural_path=structural_path,
            canonical_identity=identity,
            version=version,
        )
