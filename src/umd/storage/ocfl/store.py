"""OCFL 1.1-compatible object-store adapter: immutable source/derived bytes.

Design rules (Phase 1 / P1-S3):
  * source bytes are content-addressed by ``sha512``; the OCFL object identifier
    is derived from the digest, never from a user-provided filename;
  * ``sha512`` fixity is verified against the OCFL inventory manifest;
  * retrieval is range/bound-bounded (no unbounded reads into memory);
  * the filesystem/MinIO-compatible substrate is replaceable via ``StorageRoot``.

OCFL 1.1 conformance via ``ocfl-py`` 2.1.0.
"""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

import ocfl
from pydantic import BaseModel, Field

try:  # ocfl-py subtypes the storage-root error
    from ocfl.storage_root import StorageRootException
except Exception:  # pragma: no cover - defensive import path
    StorageRootException = OSError


class StoreError(RuntimeError):
    """Raised when a source cannot be written to or read from OCFL."""


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


class SourceDescriptor(BaseModel):
    """Metadata carried on the first write of a source object.

    ``logical_name`` is *metadata only*: it is recorded but never used to
    derive a storage path or object identifier. ``kind`` namespaces the OCFL
    object id so source vs. derived objects never collide.
    """

    logical_name: str
    media_kind: str = "unknown"
    format: str = "unknown"
    kind: str = Field(default="source", pattern=r"^(source|derived|artifact)$")
    content_type: str = "application/octet-stream"


class SourceManifest(BaseModel):
    """Result of an immutable ``put`` of a raw source/derived object."""

    object_id: str
    store_path: str
    logical_name: str
    sha512: str
    size_bytes: int
    version: str = "v1"


class NativeRepresentation(BaseModel):
    """A bounded byte-range read from an immutable OCFL source object."""

    object_id: str
    logical_name: str
    version: str
    sha512: str
    size_bytes: int
    start: int
    end: int
    data: bytes
    content_type: str
    truncated: bool


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


@dataclass
class SourceStore:
    """Content-addressed immutable source store over an OCFL 1.1 storage root.

    Use :meth:`create` to bootstrap a brand-new root at a filesystem path; a
    plain ``SourceStore(root=...)`` assumes an existing initialized root.
    """

    root: Path
    layout: str = "0003-hash-and-id-n-tuple-storage-layout"
    spec_version: str = "1.1"
    digest_algorithm: str = "sha512"
    max_upload_bytes: int = 1024 * 1024 * 1024
    max_range_bytes: int = 1024 * 1024
    #: Hard cap on a single ``get_range`` read into memory (never exceeded).
    max_read_buffer_bytes: int = 1024 * 1024

    _sr: ocfl.StorageRoot = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self._sr = ocfl.StorageRoot(
            root=str(self.root),
            layout_name=self.layout,
        )

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def create(cls, root: Path, **kwargs: Any) -> SourceStore:
        """Bootstrap a brand-new OCFL storage root (idempotent).

        Tolerates a pre-existing but *empty* root directory. A non-empty
        directory without an OCFL declaration is rejected.
        """
        store = cls(root=Path(root), **kwargs)
        namaste = store.root / ("0=ocfl_" + store.spec_version)
        if not namaste.exists():
            store.root.parent.mkdir(parents=True, exist_ok=True)
            if store.root.exists():
                if any(store.root.iterdir()):
                    raise StoreError(
                        f"OCFL root {store.root} exists and is non-empty; refusing to bootstrap"
                    )
                # ocfl-py requires the root dir to be absent before initialize().
                store.root.rmdir()
            store._sr.initialize(spec_version=store.spec_version)
        return store

    # -- public API --------------------------------------------------------

    def put_immutable(
        self,
        stream: BinaryIO,
        descriptor: SourceDescriptor,
    ) -> SourceManifest:
        """Persist an immutable source/derived object, content-addressed by sha512.

        The object identifier derives from the content digest — a user-provided
        filename is never used as a key. Raises :class:`StoreError` if the
        payload exceeds ``max_upload_bytes``.
        """
        sha512, size, spool = self._spool_and_digest(stream)
        try:
            object_id = self._object_id(descriptor.kind, sha512)
            store_path = self.object_path(object_id)

            if self._exists(object_id):
                if not self.verify_fixity(object_id):
                    raise StoreError(
                        f"OCFL object {object_id} exists but failed fixity verification"
                    )
            else:
                self._write_object(object_id, descriptor, spool)

            return SourceManifest(
                object_id=object_id,
                store_path=store_path,
                logical_name=descriptor.logical_name,
                sha512=sha512,
                size_bytes=size,
            )
        finally:
            spool.unlink(missing_ok=True)

    def get_range(
        self,
        source_ref: str,
        start: int = 0,
        length: int | None = None,
        *,
        version: str | None = None,
    ) -> NativeRepresentation:
        """Return a bounded byte range from an immutable source object.

        ``length`` defaults to ``max_range_bytes`` and is capped by it. Fixity
        metadata (full-object sha512 + size) is returned alongside the slice so
        callers can verify integrity of the parent object.
        """
        obj = self._open_object(source_ref)
        inventory = obj.parse_inventory()
        rel = version or inventory.head
        logical_name = self._single_logical_name(inventory, rel)
        content_path = self._resolve_logical_content(inventory, rel, logical_name)
        if content_path is None:
            raise StoreError(f"no content path for {source_ref}:{logical_name}")
        full_path = self.root / self.object_path(source_ref) / content_path

        # Bounded streaming read: ``length`` is capped to ``max_range_bytes`` and
        # ``max_read_buffer_bytes`` so a caller-controlled request never reads more
        # than one bounded buffer into memory, regardless of object size.
        length = length if length is not None else self.max_range_bytes
        length = min(length, self.max_range_bytes, self.max_read_buffer_bytes)
        start = max(0, start)
        total = full_path.stat().st_size
        data = self._read_bounded(full_path, start, length)
        end = min(start + len(data), total)
        truncated = end < total
        return NativeRepresentation(
            object_id=source_ref,
            logical_name=logical_name,
            version=rel,
            sha512=self._state_digest(inventory, rel, logical_name),
            size_bytes=total,
            start=start,
            end=end,
            data=data,
            content_type="application/octet-stream",
            truncated=truncated,
        )

    def verify_fixity(self, source_ref: str) -> bool:
        """Recompute sha512 of on-disk bytes and compare to the inventory manifest."""
        try:
            obj = self._open_object(source_ref)
            inventory = obj.parse_inventory()
        except Exception:
            return False
        rel = inventory.head
        for name in self._logical_names(inventory, rel):
            content_path = self._resolve_logical_content(inventory, rel, name)
            if content_path is None:
                return False
            h = hashlib.sha512()
            with (self.root / self.object_path(source_ref) / content_path).open("rb") as fh:
                while chunk := fh.read(65536):
                    h.update(chunk)
            if h.hexdigest() != self._state_digest(inventory, rel, name):
                return False
        return True

    def object_path(self, object_id: str) -> str:
        """Storage-relative path of an object per the configured layout."""
        return str(self._sr.object_path(object_id))

    def has_object(self, object_id: str) -> bool:
        return self._exists(object_id)

    # -- internals ---------------------------------------------------------

    def _exists(self, object_id: str) -> bool:
        return (self.root / self.object_path(object_id)).exists()

    def _object_id(self, kind: str, sha512: str) -> str:
        return f"urn:umd:ocfl:{kind}:sha512:{sha512}"

    def _spool_and_digest(self, stream: BinaryIO) -> tuple[str, int, Path]:
        """Single-pass bounded spool writing to a temp file while hashing."""
        h = hashlib.sha512()
        size = 0
        spool = Path(tempfile.mkstemp(prefix="umd_spool_")[1])
        with spool.open("wb") as fh:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > self.max_upload_bytes:
                    fh.close()
                    spool.unlink(missing_ok=True)
                    raise StoreError(f"payload exceeds max_upload_bytes={self.max_upload_bytes}")
                h.update(chunk)
                fh.write(chunk)
        return h.hexdigest(), size, spool

    def _write_object(
        self,
        object_id: str,
        descriptor: SourceDescriptor,
        spool: Path,
    ) -> None:
        """Build the object in temp staging then add it at the layout path."""
        with tempfile.TemporaryDirectory() as staging_d, tempfile.TemporaryDirectory() as src_d:
            staging = Path(staging_d)
            src = Path(src_d)
            # Logical content file carries a safe, sanitized name (metadata only).
            safe_name = _sanitize_name(descriptor.logical_name)
            (src / safe_name).write_bytes(spool.read_bytes())

            obj = ocfl.Object(
                identifier=object_id,
                path=str(staging),
                create=True,
                digest_algorithm=self.digest_algorithm,
                content_directory="content",
            )
            nv = ocfl.NewVersion.first_version(
                srcdir=str(src),
                identifier=object_id,
                metadata=ocfl.VersionMetadata(
                    message="immutable source put",
                    name="umd-source-store",
                    address="umd@localhost",
                ),
            )
            nv.add(safe_name, safe_name)
            obj.write_new_version(nv)
            try:
                self._sr.add(str(staging))
            except StorageRootException:
                # Clear, actionable failure for the write path.
                raise StoreError(f"failed to register OCFL object {object_id}") from None

    @staticmethod
    def _read_bounded(full_path: Path, start: int, length: int) -> bytes:
        """Read ``start``..``start+length`` from ``full_path`` into memory.

        Only the requested window is loaded: the file is opened, seeked to
        ``start``, and at most ``length`` bytes are read. ``length`` is already
        capped by the caller to ``max_read_buffer_bytes``, so this never performs
        an unbounded read into memory.
        """
        if length <= 0:
            return b""
        with full_path.open("rb") as fh:
            fh.seek(start)
            return fh.read(length)

    def _open_object(self, object_id: str) -> ocfl.Object:
        path = self.root / self.object_path(object_id)
        if not path.exists():
            raise StoreError(f"OCFL object not found: {object_id}")
        return ocfl.Object(path=str(path))

    # -- inventory helpers -------------------------------------------------

    def _logical_names(self, inventory: ocfl.Inventory, rel: str) -> list[str]:
        names: list[str] = []
        for paths in inventory.version(rel).state.values():
            names.extend(paths)
        return names

    def _single_logical_name(self, inventory: ocfl.Inventory, rel: str) -> str:
        names = self._logical_names(inventory, rel)
        if not names:
            raise StoreError("OCFL object head has no content files")
        return names[0]

    def _state_digest(self, inventory: ocfl.Inventory, rel: str, name: str) -> str:
        for digest, paths in inventory.version(rel).state.items():
            if name in paths:
                return str(digest)
        raise StoreError(f"resolve failed: {name} not in state of {rel}")

    def _resolve_logical_content(
        self, inventory: ocfl.Inventory, rel: str, name: str
    ) -> str | None:
        digest = self._state_digest(inventory, rel, name)
        content = inventory.manifest.get(digest) or []
        for c in content:
            if str(c).startswith(rel + "/"):
                return str(c)
        return str(content[0]) if content else None


def _sanitize_name(name: str) -> str:
    """Produce a safe logical path component for OCFL (no path traversal)."""
    base = Path(name).name  # strip any upstream directory components
    return base if base not in ("", ".", "..") else "content.bin"
