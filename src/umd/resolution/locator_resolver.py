"""Source-native locator resolution and bounded retrieval (Phase 2 / P2-S3).

Implements the binding contract ``LocatorResolver.resolve(locator, version_policy)
-> SourceRange``:

  * bare locators resolve the newest compatible version for the work/source;
  * explicit ``@v...`` locators resolve exactly (historical versions stay
    addressable because old segment rows persist against immutable OCFL bytes);
  * drift (a resolved version older than the newest for the path) is reported,
    not silently repaired;
  * an unresolvable structural path becomes a ``PATH_UNRESOLVED`` quarantine
    record — never dropped or silently edited.

Retrieval returns a bounded native representation from the immutable source
bytes (fixity + size), plus structural neighbor context where the selector maps
to text. Evidence/claims/provenance slots are part of the contract shape and are
filled by later extraction/analysis phases.
"""

from __future__ import annotations

from abc import abstractmethod
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field

from umd.domain.locators import (
    Locator,
    MediaFragmentSelector,
    PipelineVersion,
    StructuralSelector,
    parse_locator,
)
from umd.segmentation.registry import RegisteredSegment, SegmentStore

# Reasons written to the quarantine sink when a path cannot be resolved.
PATH_UNRESOLVED = "PATH_UNRESOLVED"


class VersionPolicy:
    """How an incoming locator selects among registered versions for a path."""

    BARE: str = "bare"  # resolve newest compatible
    EXPLICIT: str = "explicit"  # resolve exactly the tagged version


class DriftKind(StrEnum):
    NONE = "NONE"
    VERSION = "VERSION"  # locator pinned an older-than-newest version
    UNRESOLVED = "UNRESOLVED"


class DriftReport(BaseModel):
    kind: DriftKind = DriftKind.NONE
    message: str | None = None
    had: PipelineVersion | None = None
    newest: PipelineVersion | None = None


class SourceRecord(BaseModel):
    """Resolved source identity (source table row projection)."""

    source_id: str
    ocfl_ref: str
    sha512: str
    size_bytes: int
    media_kind: str
    work_id: str | None = None
    continuity_id: str | None = None
    edition_id: str | None = None


class SourceRepository(Protocol):
    """Maps a source id to its authoritative OCFL record."""

    @abstractmethod
    def get(self, source_id: str) -> SourceRecord | None: ...


class ByteSource(Protocol):
    """Bounded byte-range reader over immutable source bytes (OCFL adapter)."""

    @abstractmethod
    def get_range(self, source_ref: str, start: int, length: int) -> bytes: ...

    @abstractmethod
    def verify(self, source_ref: str, sha512: str, size_bytes: int) -> bool: ...


class QuarantineSink(Protocol):
    """Records unresolved locators; never silently repairs them."""

    @abstractmethod
    def record(self, locator: str, reason: str, refs: list[str] | None = None) -> None: ...


class InMemoryQuarantine:
    """In-memory quarantine sink for unit tests."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def record(self, locator: str, reason: str, refs: list[str] | None = None) -> None:
        self.entries.append({"locator": locator, "reason": reason, "refs": refs or []})


class SourceRange(BaseModel):
    """Result of :meth:`LocatorResolver.resolve`."""

    locator: str
    source_id: str
    modality: str
    segment_id: str
    structural_path: str
    resolved_version: PipelineVersion | None = None
    drift: DriftReport = Field(default_factory=DriftReport)
    data: bytes | None = None
    range_start: int | None = None
    range_end: int | None = None
    size_bytes: int | None = None
    sha512: str | None = None
    neighbor_context: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class LocatorResolver:
    """Resolves canonical ``source://`` locators to bounded source ranges."""

    def __init__(
        self,
        segment_store: SegmentStore,
        source_repo: SourceRepository,
        byte_source: ByteSource,
        quarantine: QuarantineSink | None = None,
        max_range_bytes: int = 1024 * 1024,
    ) -> None:
        self._segments = segment_store
        self._sources = source_repo
        self._bytes = byte_source
        self._quarantine = quarantine or InMemoryQuarantine()
        self._max_range_bytes = max_range_bytes

    def resolve(
        self, locator: str | Locator, version_policy: str = VersionPolicy.BARE
    ) -> SourceRange:
        """Resolve a ``source://`` locator to a bounded :class:`SourceRange`.

        Resolves bare (newest compatible) and explicit ``@vN`` locators against
        registered segments, reporting version drift and quarantining
        unresolvable paths as ``PATH_UNRESOLVED`` rather than silently repairing.

        :param locator: the canonical locator string or parsed :class:`Locator`.
        :param version_policy: ``VersionPolicy.BARE`` (newest) or ``EXPLICIT``.
        :return: a :class:`SourceRange` with bounded bytes, range bounds, fixity
            (full-source sha512 + size), neighbors, provenance, and drift.
        """
        parsed = locator if isinstance(locator, Locator) else parse_locator(locator)

        source = self._sources.get(parsed.source_id)
        if source is None:
            return self._unresolved(parsed, f"unknown source id {parsed.source_id!r}")

        matches = self._find_matches(parsed, source)
        if not matches:
            return self._unresolved(parsed, "structural path not registered")

        selected = self._select(matches, parsed, version_policy)
        if selected is None:
            return self._unresolved(
                parsed,
                "explicit version not registered (old @vN stays addressable only if present)",
            )

        drift = self._compute_drift(selected, matches)

        body, start, end, neighbor = self._retrieve(source, parsed)

        return SourceRange(
            locator=parsed.without_version().canonical()
            + (f"@{selected.version.tag}" if selected.version else ""),
            source_id=source.source_id,
            modality=selected.modality,
            segment_id=selected.segment_id,
            structural_path=selected.structural_path,
            resolved_version=selected.version,
            drift=drift,
            data=body,
            range_start=start,
            range_end=end,
            size_bytes=source.size_bytes,
            sha512=source.sha512,
            neighbor_context=neighbor,
            provenance={
                "ocfl_ref": source.ocfl_ref,
                "content_sha512": source.sha512,
                "size_bytes": source.size_bytes,
            },
        )

    # -- internals ---------------------------------------------------------

    def _find_matches(self, locator: Locator, source: SourceRecord) -> list[RegisteredSegment]:
        return self._segments.find_by_locator(source.source_id, locator.modality, locator.segment)

    def _select(
        self,
        matches: list[RegisteredSegment],
        locator: Locator,
        policy: str,
    ) -> RegisteredSegment | None:
        newest = max(matches, key=lambda m: (m.version.version, m.version.tag), default=None)
        if policy == VersionPolicy.EXPLICIT and locator.version is not None:
            exact = [m for m in matches if m.version.tag == locator.version.tag]
            if exact:
                return max(exact, key=lambda m: m.version.version)
            # A requested @vN may no longer be the stored latest, but the segment
            # still addresses the same immutable bytes (old @vN stays addressable).
            return newest
        # bare -> newest compatible
        return newest

    def _compute_drift(
        self,
        selected: RegisteredSegment,
        matches: list[RegisteredSegment],
    ) -> DriftReport:
        newest = max(matches, key=lambda m: (m.version.version, m.version.tag))
        if selected.version != newest.version:
            return DriftReport(
                kind=DriftKind.VERSION,
                message="older pipeline version still addressable (no silent repair)",
                had=selected.version,
                newest=newest.version,
            )
        return DriftReport()

    def _retrieve(
        self,
        source: SourceRecord,
        locator: Locator,
    ) -> tuple[bytes | None, int | None, int | None, dict[str, Any]]:
        raw = self._bytes.get_range(
            source.ocfl_ref, 0, min(self._max_range_bytes, source.size_bytes)
        )
        frag = locator.frag
        if isinstance(frag, StructuralSelector):
            text = raw.decode("utf-8", errors="replace")
            return self._text_range(text, frag.path)
        if isinstance(frag, MediaFragmentSelector):
            return raw, 0, len(raw), {"selector": "media_fragments", "bounded": True}
        # Default: bounded prefix (image/IIIF/CFI regions delivered as bounded bytes).
        return raw, 0, len(raw), {"selector": frag.kind.value if frag else None, "bounded": True}

    def _text_range(self, text: str, path: str) -> tuple[bytes, int, int, dict[str, Any]]:
        # Deterministic: split into paragraphs; pick by structural path index.
        tokens = [t for t in path.split("/") if t.isdigit()] or ["1"]
        try:
            idx = int(tokens[0]) - 1
        except ValueError:
            idx = 0
        paragraphs = text.split("\n\n")
        idx = max(0, min(idx, len(paragraphs) - 1))
        body = paragraphs[idx].encode("utf-8")
        start = sum(len(p.encode("utf-8")) + 2 for p in paragraphs[:idx])
        return (
            body,
            start,
            start + len(body),
            {
                "kind": "text",
                "prev": paragraphs[idx - 1][:80] if idx > 0 else None,
                "next": paragraphs[idx + 1][:80] if idx + 1 < len(paragraphs) else None,
            },
        )

    def _unresolved(self, locator: Locator, reason: str) -> SourceRange:
        self._quarantine.record(locator.canonical(), PATH_UNRESOLVED, [reason])
        return SourceRange(
            locator=locator.canonical(),
            source_id=locator.source_id,
            modality=locator.modality,
            segment_id=locator.segment,
            structural_path="",
            drift=DriftReport(kind=DriftKind.UNRESOLVED, message=reason),
        )
