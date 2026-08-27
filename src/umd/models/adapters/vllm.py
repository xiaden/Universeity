"""Optional vLLM path (Phase C, P1-S3) — GATED.

vLLM is the higher-throughput self-hosted inference option. It serves an
OpenAI-compatible HTTP API, so this adapter is a thin, explicit extension of the
provider-neutral :class:`OpenAICompatProvider` with a vLLM-typical default
endpoint and a named gate.

**Gate honesty:** vLLM is a heavy runtime (CUDA/deps) that is deliberately NOT
installed in this environment. Activation is controlled by the ``VLLM_ENABLED``
flag (off by default). When disabled — or when the server is unreachable — the
adapter raises the typed :class:`ModelProviderUnavailable`, which capability
reporting surfaces as a *gated/unavailable* enhancement. It never fabricates a
result or a false "active" capability.
"""

from __future__ import annotations

import os

from umd.models.adapters.remote import OpenAICompatProvider
from umd.models.provider import (
    ModelProviderUnavailable,
    ModelRequest,
    StructuredModelResult,
)

#: Named gate controlling the optional vLLM path (heavy runtime, not installed).
VLLM_ENABLED = os.environ.get("UMD_VLLM_ENABLED", "").strip().lower() in {"1", "true", "yes"}


class VLLMProvider(OpenAICompatProvider):
    """Optional vLLM self-hosted adapter (OpenAI-compatible), gated on ``VLLM_ENABLED``.

    Behaves like the provider-neutral remote adapter but defaults the endpoint to
    vLLM's ``/v1`` prefix and raises :class:`ModelProviderUnavailable` whenever
    the feature is gated off or the server is absent.
    """

    name = "vllm"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        default_model: str | None = None,
        default_model_version: str | None = None,
        timeout: float = 120.0,
        enabled: bool | None = None,
    ) -> None:
        self.enabled = VLLM_ENABLED if enabled is None else enabled
        super().__init__(
            base_url=base_url or "http://127.0.0.1:8000/v1",
            api_key=api_key,
            default_model=default_model,
            default_model_version=default_model_version,
            timeout=timeout,
        )

    def invoke(self, request: ModelRequest) -> StructuredModelResult:
        if not self.enabled:
            raise ModelProviderUnavailable(
                "vLLM path is GATED (UMD_VLLM_ENABLED not set); heavy runtime not installed"
            )
        return super().invoke(request)
