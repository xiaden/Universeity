"""LocatorResolver tests (P2-S3): bare vs explicit resolution, drift, quarantine,
source-native retrieval, provenance back to immutable OCFL bytes."""

from __future__ import annotations

import io

import pytest

from umd.domain.ids import canonical_identity
from umd.domain.locators import PipelineVersion, StructuralSelector, build_locator
from umd.resolution.locator_resolver import (
    DriftKind,
    InMemoryQuarantine,
    LocatorResolver,
    SourceRecord,
    VersionPolicy,
)
from umd.segmentation.registry import (
    InMemorySegmentStore,
    SegmentInput,
    SegmentRegistry,
)
from umd.storage.postgres.repositories import (
    OcflByteSource,
)

_SHA = "a" * 128


class _InMemorySources:
    def __init__(self) -> None:
        self._s: dict[str, SourceRecord] = {}

    def add(self, rec: SourceRecord) -> None:
        self._s[rec.source_id] = rec

    def get(self, source_id: str) -> SourceRecord | None:
        return self._s.get(source_id)


class _Bytes:
    def __init__(self, data: dict[str, bytes]) -> None:
        self._data = data

    def get_range(self, source_ref: str, start: int, length: int) -> bytes:
        return self._data[source_ref][start : start + length]

    def verify(self, source_ref: str, _sha512: str, _size_bytes: int) -> bool:
        return source_ref in self._data


def _identity(src_sha: str) -> str:
    return canonical_identity(src_sha)


def _seed_two_versions(store: InMemorySegmentStore) -> tuple[SegmentRegistry, str]:
    """Register an 'old' and a 'new' pipeline version for the same path."""
    reg = SegmentRegistry(store)
    identity = _identity(_SHA)
    old = SegmentInput(
        source_id="src1",
        source_sha512=_SHA,
        modality="text",
        structural_path="chapter/4/paragraph/18",
        segment_type="paragraph",
        version=PipelineVersion("text", "pandocJAD1", "epub3", version=1),
    )
    new = SegmentInput(
        source_id="src1",
        source_sha512=_SHA,
        modality="text",
        structural_path="chapter/4/paragraph/18",
        segment_type="paragraph",
        version=PipelineVersion("text", "pandoc22", "epub3", version=2),
    )
    reg.register([old, new])
    locator = build_locator(
        source_id="src1",
        modality="text",
        structural_path="chapter/4/paragraph/18",
        canonical_identity=identity,
        version=new.version,
    )
    return reg, locator.canonical()


def _make_resolver(store: InMemorySegmentStore, src: SourceRecord, burl: _Bytes) -> LocatorResolver:
    return LocatorResolver(
        segment_store=store,
        source_repo=_repo(src),
        byte_source=burl,
        quarantine=InMemoryQuarantine(),
        max_range_bytes=4096,
    )


def _repo(src: SourceRecord) -> _InMemorySources:
    r = _InMemorySources()
    r.add(src)
    return r


def test_bare_resolves_newest_compatible() -> None:
    store = InMemorySegmentStore()
    _, raw = _seed_two_versions(store)
    locator = raw.split("@")[0]  # drop the @v...
    src = SourceRecord(
        source_id="src1", ocfl_ref="ocfl:1", sha512=_SHA, size_bytes=64, media_kind="text"
    )
    resolver = _make_resolver(store, src, _Bytes({"ocfl:1": b"x" * 64}))
    rng = resolver.resolve(locator, VersionPolicy.BARE)
    assert rng.resolved_version is not None
    assert rng.resolved_version.tag == "vtext.pandoc22.epub3"  # newest


def test_explicit_resolves_exactly_and_old_stays_addressable() -> None:
    store = InMemorySegmentStore()
    _, raw = _seed_two_versions(store)
    old_locator = raw.replace("pandoc22", "pandocJAD1")
    src = SourceRecord(
        source_id="src1", ocfl_ref="ocfl:1", sha512=_SHA, size_bytes=64, media_kind="text"
    )
    resolver = _make_resolver(store, src, _Bytes({"ocfl:1": b"q" * 64}))
    rng = resolver.resolve(old_locator, VersionPolicy.EXPLICIT)
    assert rng.resolved_version is not None
    assert rng.resolved_version.tag == "vtext.pandocJAD1.epub3"


def test_version_drift_is_reported_not_repaired() -> None:
    store = InMemorySegmentStore()
    _, raw = _seed_two_versions(store)
    old_locator = raw.replace("pandoc22", "pandocJAD1")
    src = SourceRecord(
        source_id="src1", ocfl_ref="ocfl:1", sha512=_SHA, size_bytes=64, media_kind="text"
    )
    resolver = _make_resolver(store, src, _Bytes({"ocfl:1": b"q" * 64}))
    rng = resolver.resolve(old_locator, VersionPolicy.EXPLICIT)
    assert rng.drift.kind == DriftKind.VERSION
    assert rng.drift.had is not None and rng.drift.had.tag == "vtext.pandocJAD1.epub3"
    # it still resolved (old @vN remains addressable) -> not quarantined / not edited
    assert rng.resolved_version is not None


def test_unresolved_path_goes_to_path_unresolved_quarantine() -> None:
    store = InMemorySegmentStore()
    q = InMemoryQuarantine()
    src = SourceRecord(
        source_id="missing", ocfl_ref="ocfl:nope", sha512=_SHA, size_bytes=10, media_kind="text"
    )
    repo = _repo(src)
    resolver = LocatorResolver(
        segment_store=store,
        source_repo=repo,
        byte_source=_Bytes({"ocfl:nope": b"0123456789"}),
        quarantine=q,
    )
    rng = resolver.resolve("source://missing/text/doesnotexist@vtext.x.y?frag=paragraph/1")
    assert rng.drift.kind == DriftKind.UNRESOLVED
    assert any(e["reason"] == "PATH_UNRESOLVED" for e in q.entries)
    assert q.entries and "doesnotexist" in q.entries[0]["locator"]


def test_text_retrieval_returns_bounded_body_with_neighbors() -> None:
    body = b"Para one\n\nPara two target\n\nPara three"
    src = SourceRecord(
        source_id="src1", ocfl_ref="ocfl:t", sha512=_SHA, size_bytes=len(body), media_kind="text"
    )
    store = InMemorySegmentStore()
    reg = SegmentRegistry(store)
    inp = SegmentInput(
        source_id="src1",
        source_sha512=_SHA,
        modality="text",
        structural_path="chapter/1/paragraph/2",
        segment_type="paragraph",
        version=PipelineVersion("text", "pandoc22", "epub3", version=2),
        frag=StructuralSelector(path="paragraph/2"),
    )
    seg = reg.register([inp]).created[0]
    resolver = LocatorResolver(
        segment_store=store,
        source_repo=_repo(src),
        byte_source=_Bytes({"ocfl:t": body}),
        quarantine=InMemoryQuarantine(),
    )
    rng = resolver.resolve(seg.locator, VersionPolicy.BARE)
    assert rng.data == b"Para two target"
    assert rng.sha512 == _SHA  # full-source immutable fixity
    assert rng.neighbor_context["prev"] == "Para one"


# ---------------------------------------------------------------------------
# Provenance traversal back to immutable bytes (OCFL-backed)
# ---------------------------------------------------------------------------


@pytest.fixture()
def _prov_resolver(source_store):
    data = b"The beginning of a novel.\n\nSecond paragraph here."
    from umd.storage.ocfl import SourceDescriptor

    man = source_store.put_immutable(io.BytesIO(data), SourceDescriptor(logical_name="novel.txt"))
    store = InMemorySegmentStore()
    reg = SegmentRegistry(store)
    inp = SegmentInput(
        source_id="novel",
        source_sha512=man.sha512,
        modality="text",
        structural_path="chapter/1/paragraph/1",
        segment_type="paragraph",
        version=PipelineVersion("text", "pandoc22", "plain", version=1),
    )
    reg.register([inp])
    src = SourceRecord(
        source_id="novel",
        ocfl_ref=man.object_id,
        sha512=man.sha512,
        size_bytes=man.size_bytes,
        media_kind="text",
    )
    resolver = LocatorResolver(
        segment_store=store,
        source_repo=_repo(src),
        byte_source=OcflByteSource(source_store),
        quarantine=InMemoryQuarantine(),
        max_range_bytes=4096,
    )
    return resolver, data, man


def test_provenance_to_immutable_ocfl_bytes(_prov_resolver) -> None:
    resolver, data, man = _prov_resolver
    seg = resolver._segments.segments_for_source("novel")[0]
    rng = resolver.resolve(seg.locator, VersionPolicy.BARE)
    # resolved range's fixity is the authoritative full-source sha512 from OCFL
    assert rng.sha512 == man.sha512
    assert rng.provenance["ocfl_ref"] == man.object_id
    # confirm the immutable bytes back it up via the OCFL store
    assert resolver._bytes.verify(man.object_id, man.sha512, man.size_bytes) is True
