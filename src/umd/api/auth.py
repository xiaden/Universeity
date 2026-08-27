"""API authentication/authorization (API key + bearer) — Phase 3.

Working auth usable by the contract tests: a request authenticates with
``Authorization: Bearer <key>`` OR ``X-API-Key: <key>``. Keys are configured via
:class:`umd.config.AuthSettings` and read from the app context. A principal is an
authenticated key bound to the request; write-sensitive routes additionally check
the key is in ``write_keys``.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from fastapi import Request

from umd.api.errors import ForbiddenError, UnauthorizedError
from umd.config import AuthSettings


@dataclass(frozen=True)
class Principal:
    """An authenticated API key bound to a request."""

    key: str
    can_write: bool


def _extract_key(request: Request) -> str | None:
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-api-key")


def authenticate(request: Request, settings: AuthSettings) -> Principal:
    """Authenticate ``request`` against ``settings`` and return a :class:`Principal`.

    When ``settings.api_keys`` is empty, auth is disabled (an anonymous principal
    that may read and write). Otherwise the presented key must match a configured
    key, and ``can_write`` requires membership in ``write_keys`` (empty = any
    valid key may write).
    """
    if not settings.api_keys:
        return Principal(key="anon", can_write=True)
    presented = _extract_key(request)
    if presented is None:
        raise UnauthorizedError("missing bearer/API key")
    valid = [k for k in settings.api_keys if secrets.compare_digest(str(k), presented)]
    if not valid:
        raise UnauthorizedError("invalid API key")
    key = valid[0]
    can_write = (not settings.write_keys) or any(
        secrets.compare_digest(key, w) for w in settings.write_keys
    )
    return Principal(key=key, can_write=can_write)


def require_write(principal: Principal) -> Principal:
    """Authorization gate for mutating routes."""
    if not principal.can_write:
        raise ForbiddenError("this API key cannot perform writes")
    return principal


__all__ = [
    "Principal",
    "authenticate",
    "require_write",
]
