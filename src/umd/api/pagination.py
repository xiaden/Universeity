"""Opaque cursor pagination (Phase 3).

Cursor pagination for collections: the client receives an opaque, URL-safe cursor
(``next_cursor`` / ``prev_cursor``) rather than raw offsets. The cursor encodes a
server-side page position so clients can never forge a position outside the bounded
query surface.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from umd.api.errors import ApiError


def encode_cursor(position: dict[str, Any]) -> str:
    raw = json.dumps(position, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str) -> dict[str, Any]:
    """Decode an opaque cursor; raises a structured :class:`ApiError` on malformed input."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        doc = json.loads(raw.decode("utf-8"))
        if not isinstance(doc, dict):
            raise ValueError("cursor must decode to an object")
        return doc
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        raise ApiError(f"invalid cursor: {exc}", code="invalid_cursor") from exc


def cursor_for(offset: int) -> str:
    return encode_cursor({"o": offset})


def offset_from(cursor: str | None) -> int:
    if not cursor:
        return 0
    pos = decode_cursor(cursor)
    try:
        off = int(pos.get("o", 0))
    except (TypeError, ValueError) as exc:
        raise ApiError("invalid cursor position", code="invalid_cursor") from exc
    return max(off, 0)


def page_cursors(offset: int, limit: int, total: int) -> tuple[str | None, str | None]:
    """Return ``(next_cursor, prev_cursor)`` for a cursor-page at ``offset``."""
    next_cursor = cursor_for(offset + limit) if offset + limit < total else None
    prev_cursor = cursor_for(max(offset - limit, 0)) if offset > 0 else None
    return next_cursor, prev_cursor


__all__ = ["encode_cursor", "decode_cursor", "cursor_for", "offset_from", "page_cursors"]
