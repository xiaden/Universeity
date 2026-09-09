"""Boundary normalization for public UUID-like ids (Plan U P4-S1).

One canonical DASHED-UUID wire representation for every public UUID-like id
(source, work, continuity). Internal storage keeps whatever form it uses (the
relational UUID columns read back as dashed); the API boundary normalizes
request filters and response serializers to the standard dashed form so every
public UUID id round-trips unchanged. Opaque non-UUID values (entity canonical
refs, OCFL refs, job ids, locators, provenance markers) pass through unchanged,
so opaque refs never get mangled at the boundary.
"""

from __future__ import annotations

import uuid


def dashed_uuid(value: str | None) -> str | None:
    """Normalize a UUID-like public id to the standard dashed form.

    Accepts a dashed or dashless 32-hex UUID and returns the canonical dashed
    ``str(uuid.UUID(...))``. Returns ``None`` for ``None``; any non-UUID opaque
    value (canonical ref, locator, job id, media id) is returned unchanged so it
    round-trips exactly. Idempotent: a value already in dashed form is unchanged.
    """
    if value is None:
        return None
    s = str(value).strip()
    try:
        return str(uuid.UUID(s))
    except (ValueError, TypeError, AttributeError):
        return s
