"""Provider-neutral remote adapter (Phase C, P1-S3).

A provider-neutral, OpenAI-compatible HTTP adapter used for remote model
providers (and, by config, any OpenAI-shaped service). It is interchangeable
with the local :class:`OllamaProvider` and the optional
:class:`VLLMProvider` behind the single :class:`ModelProvider` contract.

The adapter is *typed and genuine*: it requires an explicit ``base_url`` (and
optionally an API key), never guesses credentials, and raises
:class:`ModelProviderUnavailable` when unconfigured or unreachable. It emits
structured results and records model-call evidence; it never writes semantic
state or a projection.
"""

from __future__ import annotations

from typing import Any

from umd.models.adapters._http import post_json
from umd.models.provider import (
    ModelCost,
    ModelMode,
    ModelProviderUnavailable,
    ModelRequest,
    StructuredModelResult,
)


class OpenAICompatProvider:
    """Provider-neutral OpenAI-compatible HTTP adapter (completion + embedding)."""

    name = "remote"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        default_model: str | None = None,
        default_model_version: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        if not base_url:
            raise ModelProviderUnavailable("remote provider requires a configured base_url (GATED)")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model
        self.default_model_version = default_model_version
        self.timeout = timeout

    def invoke(self, request: ModelRequest) -> StructuredModelResult:
        model = request.model or (self.default_model or "")
        if not model:
            raise ModelProviderUnavailable("remote: no model specified and no default configured")
        if request.mode == ModelMode.EMBEDDING:
            return self._embed(model, request)
        return self._complete(model, request)

    def _headers(self) -> dict[str, str]:
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}

    def _complete(self, model: str, request: ModelRequest) -> StructuredModelResult:
        if not request.prompt:
            raise ModelProviderUnavailable("remote completion requires a prompt")
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.prompt_version:
            payload["prompt_version"] = request.prompt_version
        data = post_json(
            f"{self.base_url}/chat/completions",
            payload,
            timeout=self.timeout,
            headers=self._headers(),
        )
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelProviderUnavailable(f"remote: unexpected response shape: {exc}") from exc
        usage = data.get("usage") or {}
        return StructuredModelResult(
            mode=ModelMode.COMPLETION,
            model=model,
            model_version=self.default_model_version,
            provider=self.name,
            prompt_version=request.prompt_version,
            output={"text": str(text)},
            input_refs=request.input_refs,
            stage=request.stage,
            cost=ModelCost(
                input_tokens=int(usage.get("prompt_tokens") or 0),
                output_tokens=int(usage.get("completion_tokens") or 0),
            ),
        )

    def _embed(self, model: str, request: ModelRequest) -> StructuredModelResult:
        if request.input is None:
            raise ModelProviderUnavailable("remote embedding requires input")
        data = post_json(
            f"{self.base_url}/embeddings",
            {"model": model, "input": request.input},
            timeout=self.timeout,
            headers=self._headers(),
        )
        out = data.get("data") or []
        return StructuredModelResult(
            mode=ModelMode.EMBEDDING,
            model=model,
            model_version=self.default_model_version,
            provider=self.name,
            output={"embeddings": [item.get("embedding") for item in out]},
            input_refs=request.input_refs,
            stage=request.stage,
            cost=ModelCost(input_tokens=int((data.get("usage") or {}).get("prompt_tokens") or 0)),
        )
