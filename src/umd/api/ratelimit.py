"""Real per-key/per-IP rate limiting (token bucket, in-process) — Phase 3.

Not a stub: each (authenticated key, client IP) bucket is a token bucket refilled
continuously in wall-clock time, with bounded burst. Exceeding the bucket raises a
:class:`RateLimitedError` carrying a ``Retry-After`` header. Buckets are keyed by
the authenticated principal when present, else the client IP, so authenticated
callers are never throttled on raw IP alone.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from umd.api.errors import RateLimitedError
from umd.config import RateLimitSettings


@dataclass
class _Bucket:
    tokens: float
    last_refill: float = field(default_factory=time.monotonic)


class TokenBucketRateLimiter:
    """Thread-safe token-bucket limiter keyed by str bucket ids."""

    def __init__(self, settings: RateLimitSettings) -> None:
        self._settings = settings
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def _rate_per_second(self) -> float:
        return self._settings.requests_per_window / max(self._settings.window_seconds, 1e-3)

    def allow(self, bucket_id: str) -> tuple[bool, float]:
        """Consume one token from ``bucket_id``; ``(allowed, retry_after)``."""
        if not self._settings.enabled:
            return True, 0.0
        capacity = float(self._settings.requests_per_window + self._settings.burst)
        rate = self._rate_per_second()
        now = time.monotonic()
        with self._lock:
            b = self._buckets.get(bucket_id)
            if b is None or now - b.last_refill > self._settings.window_seconds * 2:
                b = _Bucket(tokens=capacity, last_refill=now)
                self._buckets[bucket_id] = b
            elapsed = now - b.last_refill
            b.tokens = min(capacity, b.tokens + elapsed * rate)
            b.last_refill = now
            if b.tokens < 1.0:
                retry_after = (1.0 - b.tokens) / rate
                return False, max(retry_after, 0.1)
            b.tokens -= 1.0
            return True, 0.0


class RateLimitGuard:
    """Applies rate limiting to an incoming request (nerve dependency)."""

    def __init__(self, limiter: TokenBucketRateLimiter) -> None:
        self._limiter = limiter

    def bucket_id(self, *, client_ip: str, key: str | None) -> str:
        return f"{key or 'ip'}::{client_ip}"

    def check(self, *, client_ip: str, key: str | None) -> None:
        allowed, retry_after = self._limiter.allow(self.bucket_id(client_ip=client_ip, key=key))
        if not allowed:
            raise RateLimitedError(
                "rate limit exceeded; retry after Retry-After",
                extra={"retry_after": retry_after},
            )


__all__ = ["TokenBucketRateLimiter", "RateLimitGuard"]
