"""Safe, allowlisted archive member validation / extraction (Phase C, P1-S2).

Archive contents are untrusted. This module enforces the archive-security half
of the DD security contract *before* any member is written to disk:

  * **absolute-path rejection** — a member whose path is absolute is denied;
  * **traversal rejection** — a member whose path escapes its extraction root
    (``..`` segments, or resolution outside the root) is denied;
  * **symlink / hardlink / device-node rejection** — link and special members
    are denied so a decompressor cannot plant a link that later redirects
    a read/write outside the root;
  * **allowlist** — when ``policy.archive_allow_extensions`` is declared, a
    member's suffix must be in it (a real allowlist, not just a hint);
  * **count + decompressed-size limits** — a zip/tar with too many entries or
    whose total uncompressed size exceeds ``limits.max_files`` /
    ``max_decompressed_bytes`` is denied, bounding zip-bomb / descriptor-fork
    risk.

This validation runs *inside* the sandbox boundary (see CONTRACTS.md) — it is
defense in the extraction path, never a substitute for the OS-isolation layer.
"""

from __future__ import annotations

import posixpath
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from umd.security.sandbox import SandboxLimits, SandboxPolicy


class ArchiveDenial(Exception):  # noqa: N818 - stable public name used across stages
    """An archive member (or the archive as a whole) was rejected."""

    def __init__(self, reason: str, *, member: str | None = None) -> None:
        self.reason = reason
        self.member = member
        msg = (
            f"archive denied: {reason}"
            if member is None
            else f"archive denied {member!r}: {reason}"
        )
        super().__init__(msg)


@dataclass
class ArchiveMember:
    """A validated, safely-normalized member path that may be written."""

    path: str  # normalized relative path (posix separators)
    size: int  # uncompressed size in bytes
    is_dir: bool = False


@dataclass
class ArchivePlan:
    """Result of validating an archive's members before any extraction."""

    members: list[ArchiveMember] = field(default_factory=list)
    total_decompressed: int = 0

    @property
    def ok(self) -> bool:
        return True


def _safe_relpath(name: str, *, reject_absolute: bool, reject_traversal: bool) -> str | None:
    """Normalize a member path to a safe relative posix path, or ``None`` if unsafe."""
    if not name:
        return None
    # Windows-style backslashes are treated as separators too (defense against
    # "..\\.." style traversal disguised as a filename).
    name = name.replace("\\", "/")
    if reject_absolute and (name.startswith("/") or _is_windows_abs(name)):
        return None
    # Normalize and enforce traversal. posixpath.normpath collapses '..' but we
    # must reject any path that would *escape* the root.
    norm = posixpath.normpath(name)
    if norm == ".." or norm.startswith("../"):
        return None
    if reject_traversal and ".." in name.split("/"):
        return None
    return norm


def _is_windows_abs(name: str) -> bool:
    # Drive-letter absolute paths (e.g. "C:/x", "C:\\x").
    return len(name) >= 3 and name[1:3] == ":/"


def _allowed(relpath: str, policy: SandboxPolicy) -> bool:
    if not policy.archive_allow_extensions:
        return True
    allowed = {f".{e.lower()}" for e in policy.archive_allow_extensions}
    suffix = posixpath.splitext(relpath)[1].lower()
    return suffix in allowed


def sanitize_zip(
    zf: zipfile.ZipFile,
    *,
    policy: SandboxPolicy,
    limits: SandboxLimits | None = None,
) -> ArchivePlan:
    """Validate every member of ``zf``; raise :class:`ArchiveDenial` on any breach.

    Returns an :class:`ArchivePlan` of safe members. No member is extracted
    until the whole archive passes, so a single malicious entry cannot leak a
    partial write before rejection.
    """
    limits = limits or SandboxLimits()
    plan = ArchivePlan()
    for info in zf.infolist():
        if info.filename.endswith("/"):
            continue  # directory entries carry no payload; not counted
        # Symlink detection for zip: a member whose target is stored via the
        # external-attrs unix mode (S_IFLNK = 0o120000).
        if policy.reject_symlinks and (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise ArchiveDenial("symlink member", member=info.filename)
        relpath = _safe_relpath(
            info.filename,
            reject_absolute=policy.reject_absolute,
            reject_traversal=policy.reject_traversal,
        )
        if relpath is None:
            raise ArchiveDenial("unsafe path (absolute/traversal)", member=info.filename)
        if not _allowed(relpath, policy):
            raise ArchiveDenial("member extension not allowlisted", member=relpath)
        if len(plan.members) >= limits.max_files:
            raise ArchiveDenial(f"archive exceeds max_files={limits.max_files}")
        plan.total_decompressed += info.file_size
        if plan.total_decompressed > limits.max_decompressed_bytes:
            raise ArchiveDenial(
                f"archive exceeds max_decompressed_bytes={limits.max_decompressed_bytes}"
            )
        plan.members.append(ArchiveMember(path=relpath, size=info.file_size))
    return plan


def sanitize_tar(
    tf: Any,
    *,
    policy: SandboxPolicy,
    limits: SandboxLimits | None = None,
) -> ArchivePlan:
    """Validate every member of a ``tarfile`` object; raise on any breach."""
    limits = limits or SandboxLimits()
    plan = ArchivePlan()
    for member in tf:
        if policy.reject_symlinks and (member.issym() or member.islnk() or member.isdev()):
            raise ArchiveDenial("link/device member", member=member.name)
        relpath = _safe_relpath(
            member.name,
            reject_absolute=policy.reject_absolute,
            reject_traversal=policy.reject_traversal,
        )
        if relpath is None:
            raise ArchiveDenial("unsafe path (absolute/traversal)", member=member.name)
        if member.isdir():
            continue
        if not _allowed(relpath, policy):
            raise ArchiveDenial("member extension not allowlisted", member=relpath)
        if len(plan.members) >= limits.max_files:
            raise ArchiveDenial(f"archive exceeds max_files={limits.max_files}")
        size = int(member.size or 0)
        plan.total_decompressed += size
        if plan.total_decompressed > limits.max_decompressed_bytes:
            raise ArchiveDenial(
                f"archive exceeds max_decompressed_bytes={limits.max_decompressed_bytes}"
            )
        plan.members.append(ArchiveMember(path=relpath, size=size, is_dir=member.isdir()))
    return plan


def extract_zip(
    zf: zipfile.ZipFile,
    dest: Path,
    *,
    policy: SandboxPolicy,
    limits: SandboxLimits | None = None,
) -> ArchivePlan:
    """Validate then extract ``zf`` into ``dest`` under ``policy``+``limits``.

    Validation is all-or-nothing: extraction begins only after every member
    passes, and members are written via the already-normalized safe path (never
    the raw member name), so no member can escape ``dest``.
    """
    plan = sanitize_zip(zf, policy=policy, limits=limits)
    for m in plan.members:
        target = dest / m.path
        target.parent.mkdir(parents=True, exist_ok=True)
        if m.is_dir:
            target.mkdir(parents=True, exist_ok=True)
        else:
            with zf.open(m.path) as src, open(target, "wb") as out:
                out.write(src.read())
    return plan
