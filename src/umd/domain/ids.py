"""Deterministic stable IDs (Phase 2 / P2-S2).

Segment IDs MUST be deterministic from canonical source/work content identity +
modality + structural path, collision-resistant (sha512), and URL-safe. The same
(canonical_identity, modality, structural_path) always yields the same ID and
the same ``deterministic_key`` (the DB uniqueness atom). A user filename never
participates; only content identity does.
"""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Iterable

#: URL-safe alphabet without padding, so the token is safe in every path position.
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"


def sha512_b32url(data: bytes) -> str:
    """sha512 digest encoded in URL-safe base32 (no padding).

    base32's alphabet (A-Z, 2-7) is a subset of URL-safe unreserved characters,
    so no translation is needed; padding is stripped.
    """
    digest = hashlib.sha512(data).digest()
    return base64.b32encode(digest).decode("ascii").rstrip("=")


def canonical_identity(sha512: str, work_id: str | None = None, kind: str = "source") -> str:
    """Canonical content identity for a source.

    Prefer the content digest (sha512); a work id is included only when bytes
    are not the sole identity anchor. Never a user filename.
    """
    if not re.fullmatch(r"[0-9a-f]{128}", sha512):
        raise ValueError("sha512 must be a 128-char lowercase hex digest")
    if work_id:
        return f"{kind}:{work_id}:{sha512}"
    return f"{kind}:{sha512}"


def canonical_entity_ref(member_ids: Iterable[str]) -> str:
    """Deterministic, source-independent canonical ENTITY ref (Plan S P1-S2).

    Replaces the old source-bound ``entity:canonical:<source_id>:<digest>`` form:
    the returned ref carries NO source-bound prefix and no filename input. The
    digest is derived solely from the *accepted identity anchor* — the sorted
    member mention ids of the accepted canonical cluster:

      * reruns over the same accepted cluster converge to the SAME ref;
      * same-name text in different contexts yields distinct member ids and thus
        distinct (separate or reviewable) identities — same-name text alone
        never merges;
      * the ref does not embed a source id, so sources are only joined through
        explicit supported correspondence or human-confirmed identity evidence.

    :param member_ids: the mention ids accepted as members of the canonical
        cluster (the deterministic identity anchor for that scope).
    """
    members = sorted(set(str(m) for m in member_ids))
    material = "\x1f".join(members)
    digest = hashlib.sha256(material.encode()).hexdigest()[:16]
    return f"entity:canonical:{digest}"


def _norm_structural_path(path: str) -> str:
    """Stable, canonical structural path: lowercase, stripped, collapsed slashes."""
    p = re.sub(r"\s+", "", path).strip("/")
    p = re.sub(r"/{2,}", "/", p)
    return p.lower()


def deterministic_segment_id(
    canonical_identity: str,
    modality: str,
    structural_path: str,
) -> str:
    """URL-safe deterministic segment id (collision-resistant hash).

    Computed over content identity + modality + structural path. The structural
    path is normalized first so equivalent paths collide deterministically.
    """
    modality = modality.strip().lower()
    path = _norm_structural_path(structural_path)
    if not modality:
        raise ValueError("modality must be non-empty")
    material = f"{canonical_identity}\x1f{modality}\x1f{path}".encode()
    return sha512_b32url(material)[:43]  # 256 bits of entropy, URL-safe


def deterministic_key(
    canonical_identity: str,
    modality: str,
    structural_path: str,
) -> str:
    """Canonical DB ``deterministic_key`` (source_id-independent uniqueness atom).

    Distinct from the URL segment id: this is the collision-safe full encoding
    used for the ``segment`` uniqueness constraint, including the resolved
    source/work id when available.
    """
    return f"{canonical_identity}#{modality}#{_norm_structural_path(structural_path)}"


def is_url_safe(s: str) -> bool:
    """True if ``s`` contains only URL-safe unreserved characters."""
    return bool(s) and all(c in _ALPHABET for c in s)
