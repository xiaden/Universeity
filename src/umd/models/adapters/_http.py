"""Thin HTTP helpers for provider adapters (Phase C, P1-S3).

Providers speak plain HTTP/JSON. This keeps the adapters dependency-free
(``urllib``) and small. Network failures surface as typed
:class:`ModelProviderUnavailable` so an unavailable provider is *reported*, never
guessed. No shell / subprocess is used here — model calls are HTTP-only in the
API process (heavy local inference is Phase-2 via the sandbox boundary).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from umd.models.provider import ModelProviderUnavailable


def _safe_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")[:500]
    except (OSError, ValueError):
        return ""


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """POST a JSON payload and return the decoded JSON response.

    :raises ModelProviderUnavailable: any transport/HTTP failure — the caller
      reports it as an unavailable (gated) provider rather than fabricating a
      result.
    """
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    body = json.dumps(payload).encode("utf-8")
    # noqa: S310 - URL is operator/provider configuration. Local self-hosted
    # adapters (Ollama/vLLM) use http deliberately on loopback; remote uses
    # https. The URL is never derived from untrusted user input.
    req = urllib.request.Request(  # noqa: S310
        url,
        data=body,
        headers=request_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = _safe_error_body(exc)
        raise ModelProviderUnavailable(f"provider HTTP {exc.code} for {url}: {detail}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ModelProviderUnavailable(f"provider unreachable at {url}: {exc}") from exc
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ModelProviderUnavailable(f"provider returned non-JSON at {url}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ModelProviderUnavailable(f"provider returned non-object at {url}")
    return parsed
