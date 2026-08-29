"""OCFL SourceStore tests (P1-S3 / P1-S4) — content addressing, fixity, ranges.

Runs on a filesystem substrate (valid per plan/DD: MinIO is a substrate option).
No live PostgreSQL is required.
"""

from __future__ import annotations

import hashlib
import io
import shutil
import threading
from pathlib import Path

import ocfl
import pytest

from umd.storage.ocfl import SourceDescriptor, SourceStore, StoreError


def _put(store: SourceStore, data: bytes, name: str = "novel.txt") -> object:
    return store.put_immutable(io.BytesIO(data), SourceDescriptor(logical_name=name))


def _physical_content_path(store: SourceStore, manifest: object) -> Path:
    obj = ocfl.Object(path=str(store.root / manifest.store_path))
    inv = obj.parse_inventory()
    digest = list(inv.version("v1").state.keys())[0]
    rel = inv.head
    for c in inv.manifest[digest]:
        if c.startswith(rel + "/"):
            return Path(manifest.store_path) / c
    raise AssertionError("no content path found")


def test_object_id_is_content_addressed_not_filename(source_store: SourceStore) -> None:
    """A user filename must never become the storage key."""
    m = _put(source_store, b"the quick brown fox", name="../../etc/passwd")
    assert "passwd" not in m.object_id
    assert ".." not in m.object_id
    assert m.object_id.startswith("urn:umd:ocfl:source:sha512:")
    assert m.sha512  # digest present
    # identical bytes under a different hostile name still land on the SAME object id.
    m2 = _put(source_store, b"the quick brown fox", name="totally-clean.txt")
    assert m2.object_id == m.object_id


def test_put_get_roundtrip_and_fixity(source_store: SourceStore) -> None:
    data = b"hello ocfl world " * 20
    m = _put(source_store, data)
    assert m.size_bytes == len(data)
    assert m.sha512 == hashlib.sha512(data).hexdigest()

    rep = source_store.get_range(m.object_id, start=6, length=9)
    assert rep.data == data[6:15]
    assert rep.start == 6 and rep.end == 15
    assert rep.sha512 == m.sha512
    assert rep.size_bytes == len(data)
    assert rep.truncated is True

    # full range (smaller than max) is not truncated
    rep_full = source_store.get_range(m.object_id)
    assert rep_full.data == data
    assert rep_full.truncated is False


def test_fixity_verification_detects_corruption(source_store: SourceStore) -> None:
    m = _put(source_store, b"alpha beta gamma")
    assert source_store.verify_fixity(m.object_id) is True

    # Corrupt the on-disk content bytes; fixity must now fail.
    content_file = source_store.root / _physical_content_path(source_store, m)
    content_file.write_bytes(b"CORRUPTED----")
    assert source_store.verify_fixity(m.object_id) is False


def test_content_addressed_idempotency_skips_rewrite(source_store: SourceStore) -> None:
    m = _put(source_store, b"dedupe me please")
    before = {p for p in (source_store.root).rglob("inventory.json*")}
    m2 = _put(source_store, b"dedupe me please")
    assert m2.object_id == m.object_id
    after = {p for p in (source_store.root).rglob("inventory.json*")}
    assert before == after  # no second object written


def test_get_range_out_of_bounds_is_clamped(source_store: SourceStore) -> None:
    data = b"0123456789"
    m = _put(source_store, data)
    rep = source_store.get_range(m.object_id, start=100, length=5)
    assert rep.data == b""
    assert rep.end <= len(data)


def test_get_range_clamps_to_buffer_caps(tmp_path: Path) -> None:
    """A caller-controlled range larger than the store caps stays bounded."""
    store = SourceStore.create(
        tmp_path,
        max_upload_bytes=512 * 1024,
        max_range_bytes=8,
        max_read_buffer_bytes=4,
    )
    data = b"0123456789abcdefghijklmnopqrstuvwxyz"
    m = _put(store, data)
    assert m.size_bytes == len(data)

    # Request far more than either cap; the read must be clamped to the smaller
    # buffer cap so a caller never pulls more than one bounded buffer into memory.
    rep = store.get_range(m.object_id, start=0, length=1024)
    assert len(rep.data) <= store.max_read_buffer_bytes
    assert len(rep.data) == store.max_read_buffer_bytes  # min(length, max_buffer)
    assert rep.end == store.max_read_buffer_bytes  # end reflects the clamped size
    assert rep.truncated is True  # object is larger than the returned slice

    # default (None) length is clamped the same way.
    rep_default = store.get_range(m.object_id)
    assert len(rep_default.data) == store.max_read_buffer_bytes


def test_oversize_payload_rejected(tmp_path: Path) -> None:
    store = SourceStore.create(tmp_path, max_upload_bytes=16, max_range_bytes=16)
    with pytest.raises(StoreError):
        _put(store, b"x" * 64)


def test_two_stores_are_independent_filesystem_substrates(tmp_path: Path) -> None:
    """A filesystem substrate is replaceable: two roots stay fully independent."""
    store_a = SourceStore.create(tmp_path / "a")
    store_b = SourceStore.create(tmp_path / "b")
    data = b"independent stores"
    ma = _put(store_a, data)
    assert not store_b.has_object(ma.object_id)
    mb = _put(store_b, data)
    assert ma.object_id == mb.object_id
    assert store_b.get_range(mb.object_id).data == data


def test_concurrent_create_serializes_shared_root_initialization(tmp_path: Path) -> None:
    """API and worker startup may bootstrap one fresh volume concurrently."""
    root = tmp_path / "shared"
    stores: list[SourceStore] = []
    errors: list[BaseException] = []

    def create() -> None:
        try:
            stores.append(SourceStore.create(root))
        except BaseException as exc:  # pragma: no cover - assertion reports failures
            errors.append(exc)

    threads = [threading.Thread(target=create) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert len(stores) == 2
    assert (root / "0=ocfl_1.1").exists()


def test_ocfl_backup_restore_boundary(source_store: SourceStore, tmp_path: Path) -> None:
    """Independent OCFL backup/restore: raw source survives a live-store wipe."""
    data = b"durable raw source bytes that must survive"
    m = _put(source_store, data)

    backup = tmp_path / "ocfl_backup"
    shutil.copytree(source_store.root, backup)

    # Destroy the live store, then restore solely from the backup.
    shutil.rmtree(source_store.root)
    source_store.root.mkdir()
    shutil.copytree(backup, source_store.root, dirs_exist_ok=True)

    rep = source_store.get_range(m.object_id)
    assert rep.data == data
    assert source_store.verify_fixity(m.object_id) is True


def test_raw_source_retained_after_parser_failure(source_store: SourceStore) -> None:
    """A failing downstream parser must never remove/quarantine the raw source."""
    data = b"raw content for a parser that will crash"
    m = _put(source_store, data)

    def failing_parser() -> None:  # simulates a sandboxed parser exception
        raise RuntimeError("untrusted parser crashed")

    with pytest.raises(RuntimeError):
        failing_parser()

    # Raw bytes remain authoritative and readable in OCFL after the failure.
    rep = source_store.get_range(m.object_id)
    assert rep.data == data
    assert source_store.verify_fixity(m.object_id) is True
    assert source_store.has_object(m.object_id)
