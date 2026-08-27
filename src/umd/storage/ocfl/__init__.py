"""OCFL object storage package.

Ownership contract: OCFL bytes are the *sole authority* for raw source bytes and
fixity. The substrate (local filesystem or MinIO-compatible object store) is
replaceable behind :class:`ocfl.storage_root.StorageRoot`. Raw source bytes are
content-addressed by ``sha512``; a user-provided filename is never used as a
storage key (see ``SourceStore.put_immutable``).
"""

from .store import (
    NativeRepresentation,
    SourceDescriptor,
    SourceManifest,
    SourceStore,
    StoreError,
)

__all__ = [
    "NativeRepresentation",
    "SourceDescriptor",
    "SourceManifest",
    "SourceStore",
    "StoreError",
]
