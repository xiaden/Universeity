"""PostgreSQL-backed membership + locator resolution (P2-S3/P2-S4).

Requires a live PostgreSQL server and ``UMD_TEST_POSTGRES=true`` (``postgres``
marker). Verifies:
  * source alias / re-upload membership: byte-different re-uploads of one work
    coexist as distinct sources on the same work membership (no dedup), and a
    user filename is never used as a key;
  * the PostgreSQL-backed segment store addresses segments via the deterministic
    key and versioned locator;
  * the resolver quarantines ``PATH_UNRESOLVED`` lucators (never silently drops)
    and traverses provenance back to immutable OCFL bytes.
"""

from __future__ import annotations

import io
import uuid

import pytest
import sqlalchemy as sa

from umd.domain.locators import PipelineVersion
from umd.resolution.locator_resolver import LocatorResolver, VersionPolicy
from umd.segmentation.registry import SegmentInput, SegmentRegistry
from umd.storage.ocfl import SourceDescriptor
from umd.storage.postgres.repositories import (
    OcflByteSource,
    PostgresQuarantine,
    PostgresSegmentStore,
    PostgresSourceRepository,
    SourceMembershipService,
)

pytestmark = pytest.mark.postgres


def _wid() -> str:
    return uuid.uuid4().hex


def test_source_alias_reupload_membership(migrated_db: sa.Engine, source_store) -> None:
    svc = SourceMembershipService(migrated_db)
    work_id = _wid()
    svc.ensure_work(work_id=work_id, title="Novel", work_type="book")

    # Two byte-different re-uploads of the same logical work.
    s1 = source_store.put_immutable(
        io.BytesIO(b"version one bytes"), SourceDescriptor(logical_name="novel_v1.txt")
    )
    s2 = source_store.put_immutable(
        io.BytesIO(b"version two bytes different"), SourceDescriptor(logical_name="novel_v2.txt")
    )
    id1, id2 = _wid(), _wid()
    svc.ensure_source(
        source_id=id1,
        ocfl_ref=s1.object_id,
        sha512=s1.sha512,
        size_bytes=s1.size_bytes,
        media_kind="text",
        original_name="novel_v1.txt",
        work_id=work_id,
    )
    svc.ensure_source(
        source_id=id2,
        ocfl_ref=s2.object_id,
        sha512=s2.sha512,
        size_bytes=s2.size_bytes,
        media_kind="text",
        original_name="novel_v2.txt",
        work_id=work_id,
    )
    # alias semantics: both are members, distinct (no dedup). Two distinct memberships.
    svc.add_membership(source_id=id1, work_id=work_id, role="primary")
    svc.add_membership(source_id=id2, work_id=work_id, role="alias")
    memberships = svc.memberships(work_id)
    assert len(memberships) == 2
    assert {m["role"] for m in memberships} == {"primary", "alias"}

    # Distinct content => distinct segment keys (bytes never conflated).
    store = PostgresSegmentStore(migrated_db)
    reg = SegmentRegistry(store)
    batch = reg.register(
        [
            SegmentInput(
                source_id=id1,
                source_sha512=s1.sha512,
                modality="text",
                structural_path="page/1",
                segment_type="page",
                version=PipelineVersion("text", "pandoc22", "epub3", version=2),
            ),
            SegmentInput(
                source_id=id2,
                source_sha512=s2.sha512,
                modality="text",
                structural_path="page/1",
                segment_type="page",
                version=PipelineVersion("text", "pandoc22", "epub3", version=2),
            ),
        ]
    )
    assert len(batch.created) == 2
    assert batch.created[0].deterministic_key != batch.created[1].deterministic_key
    # user original_name is metadata-only, never part of any stored key
    assert "novel_v1" not in batch.created[0].deterministic_key
    persisted = store.segments_for_source(id1)
    assert len(persisted) == 1 and persisted[0].locator.startswith("source://")


def test_resolver_provenance_and_quarantine_pg(migrated_db: sa.Engine, source_store) -> None:
    data = b"Immutable body for provenance."
    man = source_store.put_immutable(io.BytesIO(data), SourceDescriptor(logical_name="prov.txt"))
    source_id = _wid()
    # Register the immutable source FIRST so the segment row's FK is satisfied.
    svc = SourceMembershipService(migrated_db)
    svc.ensure_source(
        source_id=source_id,
        ocfl_ref=man.object_id,
        sha512=man.sha512,
        size_bytes=man.size_bytes,
        media_kind="text",
        original_name="prov.txt",
        work_id=None,
    )
    seg_store = PostgresSegmentStore(migrated_db)
    reg = SegmentRegistry(seg_store)
    seg = reg.register(
        [
            SegmentInput(
                source_id=source_id,
                source_sha512=man.sha512,
                modality="text",
                structural_path="chapter/1/paragraph/1",
                segment_type="paragraph",
                version=PipelineVersion("text", "pandoc22", "plain", version=1),
            )
        ]
    ).created[0]

    parts = seg.deterministic_key.split("#")
    assert len(parts) == 3  # identity#modality#path

    quarantine = PostgresQuarantine(migrated_db)
    resolver = LocatorResolver(
        segment_store=seg_store,
        source_repo=PostgresSourceRepository(migrated_db),
        byte_source=OcflByteSource(source_store),
        quarantine=quarantine,
        max_range_bytes=4096,
    )
    rng = resolver.resolve(seg.locator, VersionPolicy.BARE)
    assert rng.sha512 == man.sha512  # authoritative immutable fixity
    assert rng.provenance["ocfl_ref"] == man.object_id

    # Unresolvable path lands in the quarantine table, never silently dropped.
    resolver.resolve(f"source://{source_id}/text/garbage@vtext.x.y?frag=paragraph/9")
    with migrated_db.connect() as c:
        q = c.execute(
            sa.text("SELECT reason FROM quarantine WHERE reason=:r"),
            {"r": "PATH_UNRESOLVED"},
        ).scalar()
    assert q == "PATH_UNRESOLVED"
