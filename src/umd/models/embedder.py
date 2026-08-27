"""Embedder — a typed wrapper, not a parallel authority (Phase C, P1-S3).

The DD / CONTRACTS define ``Embedder = ModelProvider(mode=embedding)``. Rather
than a second, independent provider hierarchy (which would risk divergent
authority), :class:`Embedder` is a thin typed wrapper that *delegates* to an
underlying :class:`ModelProvider` with the mode pinned to ``embedding``. There is
exactly one model-interface authority; the wrapper only narrows its mode.
"""

from __future__ import annotations

from umd.models.provider import (
    ModelMode,
    ModelProvider,
    ModelProviderUnavailable,
    ModelRequest,
    StructuredModelResult,
)


class Embedder:
    """Typed embedding wrapper over a :class:`ModelProvider` (mode=embedding)."""

    def __init__(self, provider: ModelProvider) -> None:
        self._provider = provider

    @property
    def provider(self) -> ModelProvider:
        return self._provider

    def embed(
        self,
        text: str | list[str],
        *,
        model: str,
        input_refs: list[str] | None = None,
        stage: str | None = None,
        config_digest: str | None = None,
    ) -> StructuredModelResult:
        """Embed ``text`` via the wrapped provider (mode pinned to embedding)."""
        return self.invoke(
            ModelRequest(
                mode=ModelMode.EMBEDDING,
                model=model,
                input=text,
                input_refs=input_refs or [],
                stage=stage,
                config_digest=config_digest,
            )
        )

    def invoke(self, request: ModelRequest) -> StructuredModelResult:
        """Force an embedding-mode call; reject completion requests."""
        if request.mode != ModelMode.EMBEDDING:
            raise ModelProviderUnavailable(
                "Embedder is mode=embedding only; use ModelProvider for completion"
            )
        return self._provider.invoke(request)
