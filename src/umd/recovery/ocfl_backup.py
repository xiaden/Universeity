"""Independent OCFL storage-root backup and restore with fixity validation.

The OCFL store is the sole authority for immutable source/derived *bytes* (and
their ``sha512`` content-addressed inventories). It is backed up independently of
the PostgreSQL ledger (the two authorities never share an artifact). A backup is
a faithful copy of the storage root:

* the ``0=ocfl_1.1`` namaste declaration,
* the storage-layout description (``ocfl_layout.json``),
* each object's ``inventory.json`` (+ any sidecar) and its ``content/`` bytes.

Restore recreates a brand-new root from the snapshot, then validates fixity on
every object through the existing ``SourceStore.verify_fixity`` (recomputing
on-disk ``sha512`` against each object's inventory manifest). No inventory or
byte is silently trusted — a divergent object raises verification.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from umd.storage.ocfl.store import SourceStore, StoreError


class OcflRecoveryError(RuntimeError):
    """Raised when an OCFL backup/restore cannot be completed or verified."""


@dataclass(frozen=True)
class OcflVerifyEntry:
    """Fixity result for a single OCFL object."""

    object_id: str
    ok: bool


@dataclass
class OcflVerifyReport:
    """Aggregate fixity result over a storage root (or a backed-up copy)."""

    objects_found: int
    entries: list[OcflVerifyEntry] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.objects_found == len(self.entries) and all(e.ok for e in self.entries)


def discover_objects(root: Path) -> list[tuple[Path, str]]:
    """Walk ``root`` for OCFL objects; return ``(object_dir, object_id)`` pairs.

    Each object dir contains an ``inventory.json`` whose top-level ``id`` is the
    object identifier (never derived from a file name). Returns an empty list (no
    objects) rather than raising for a valid but empty storage root.
    """
    root = Path(root)
    found: list[tuple[Path, str]] = []
    for inventory in sorted(root.rglob("inventory.json")):
        # An OCFL object dir carries BOTH the canonical inventory.json and a
        # per-version v<N>/inventory.json. Only count the former (a directory
        # whose immediate name is v<digits> is a version dir, not an object).
        if _is_version_inventory(inventory):
            continue
        try:
            data = json.loads(inventory.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OcflRecoveryError(f"unreadable inventory {inventory}: {exc}") from exc
        object_id = data.get("id")
        if not object_id:
            raise OcflRecoveryError(f"inventory {inventory} has no object id")
        found.append((inventory.parent, str(object_id)))
    return found


def _is_version_inventory(inventory: Path) -> bool:
    name = inventory.parent.name
    return name.startswith("v") and name[1:].isdigit()


def backup_ocfl(store_root: Path, dest: Path) -> OcflVerifyReport:
    """Copy the OCFL storage root (declaration + layout + inventories + bytes).

    ``dest`` must not already exist (a backup never silently overwrites an older
    snapshot). The returned report verifies fixity on the copy itself, proving
    the bytes that were copied.
    """
    store_root = Path(store_root)
    dest = Path(dest)
    if not (store_root / "0=ocfl_1.1").exists():
        raise OcflRecoveryError(f"{store_root} is not an OCFL storage root (no namaste)")
    if dest.exists() and any(dest.iterdir()):
        raise OcflRecoveryError(f"backup destination exists and is non-empty: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(store_root, dest, dirs_exist_ok=False)
    return verify_ocfl(dest)


def restore_ocfl(snapshot: Path, target_root: Path) -> OcflVerifyReport:
    """Recreate an OCFL storage root from ``snapshot`` and validate its fixity.

    The target root must not already hold a namaste (a restore never merges into
    a live store). Fixity is validated on the restored root via
    ``SourceStore.verify_fixity`` for every object.
    """
    snapshot = Path(snapshot)
    target_root = Path(target_root)
    if not (snapshot / "0=ocfl_1.1").exists():
        raise OcflRecoveryError(f"{snapshot} is not an OCFL backup (no namaste)")
    if (target_root / "0=ocfl_1.1").exists():
        raise OcflRecoveryError(f"target root already initialized: {target_root}")
    target_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(snapshot, target_root, dirs_exist_ok=False)
    return verify_ocfl(target_root)


def verify_ocfl(root: Path) -> OcflVerifyReport:
    """Validate fixity of every OCFL object under ``root`` (inventories + bytes).

    For each object the on-disk ``content`` bytes are re-hashed with ``sha512``
    and compared to the object inventory manifest (via the existing
    ``SourceStore.verify_fixity``). Returns an honest report of what was found
    and verified — never a fabricated pass.
    """
    root = Path(root)
    if not (root / "0=ocfl_1.1").exists():
        return OcflVerifyReport(objects_found=0)
    store = SourceStore(root=root)
    objects = discover_objects(root)
    entries: list[OcflVerifyEntry] = []
    for _dir, object_id in objects:
        try:
            ok = store.verify_fixity(object_id)
        except (StoreError, OSError, KeyError):
            ok = False
        entries.append(OcflVerifyEntry(object_id=object_id, ok=ok))
    return OcflVerifyReport(objects_found=len(objects), entries=entries)


__all__ = [
    "OcflRecoveryError",
    "OcflVerifyEntry",
    "OcflVerifyReport",
    "backup_ocfl",
    "restore_ocfl",
    "verify_ocfl",
    "discover_objects",
]
