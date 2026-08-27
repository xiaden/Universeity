"""Local Ollama provider adapter (Phase C, P1-S3).

The *local self-hosting path* for :class:`ModelProvider`. Talks to a locally
running Ollama server (default ``http://127.0.0.1:11434``) over HTTP for both
``completion`` (``/api/generate``) and ``embedding`` (``/api/embed``) modes.

The adapter is written to the :class:`ModelProvider` contract and is fully
interchangeable with the remote/vLLM adapters. It never writes semantic state.
If the server is unreachable (or a mode is unsupported), it raises the typed
:class:`ModelProviderUnavailable` — which capability reporting surfaces as a
gated/unavailable enhancement rather than a fabricated result.
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


class OllamaProvider:
    """Local Ollama adapter (completion + embedding)."""

    name = "ollama"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        *,
        default_model: str | None = None,
        default_model_version: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.default_model_version = default_model_version
        self.timeout = timeout

    def invoke(self, request: ModelRequest) -> StructuredModelResult:
        model = request.model or (self.default_model or "")
        if not model:
            raise ModelProviderUnavailable("ollama: no model specified and no default configured")
        if request.mode == ModelMode.EMBEDDING:
            return self._embed(model, request)
        return self._complete(model, request)

    def _complete(self, model: str, request: ModelRequest) -> StructuredModelResult:
        if not request.prompt:
            raise ModelProviderUnavailable("ollama completion requires a prompt")
        payload: dict[str, Any] = {"model": model, "prompt": request.prompt, "stream": False}
        data = post_json(
            f"{self.base_url}/api/generate",
            payload,
            timeout=self.timeout,
        )
        text = str(data.get("response") or "")
        cost = ModelCost(
            input_tokens=int(data.get("prompt_eval_count") or 0),
            output_tokens=int(data.get("eval_count") or 0),
        )
        return StructuredModelResult(
            mode=ModelMode.COMPLETION,
            model=model,
            model_version=self.default_model_version,
            provider=self.name,
            prompt_version=request.prompt_version,
            output={"text": text},
            input_refs=request.input_refs,
            stage=request.stage,
            cost=cost,
        )

    def _embed(self, model: str, request: ModelRequest) -> StructuredModelResult:
        if request.input is None:
            raise ModelProviderUnavailable("ollama embedding requires input")
        data = post_json(
            f"{self.base_url}/api/embed",
            {"model": model, "input": request.input},
            timeout=self.timeout,
        )
        embeddings = data.get("embeddings") or []
        return StructuredModelResult(
            mode=ModelMode.EMBEDDING,
            model=model,
            model_version=self.default_model_version,
            provider=self.name,
            output={"embeddings": embeddings},
            input_refs=request.input_refs,
            stage=request.stage,
            cost=ModelCost(input_tokens=int(data.get("prompt_eval_count") or 0)),
        )
