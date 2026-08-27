"""Models: ModelProvider (completion|embedding), registry, adapters, Embedder.

Phase C (P1-S3) implements the :class:`ModelProvider` contract from CONTRACTS.md
(``ModelProvider.invoke(request{mode, model, prompt, input_refs}) ->
StructuredModelResult``) with local Ollama, provider-neutral remote, and optional
gated vLLM adapters; a :class:`ProviderRegistry`; structured model-call records
assembled as **evidence** (never semantic state / never a projection write); and
an :class:`Embedder` typed wrapper (not a parallel authority).
"""

from umd.models.embedder import Embedder
from umd.models.provider import (
    ModelCallRecord,
    ModelCost,
    ModelMode,
    ModelProvider,
    ModelProviderUnavailable,
    ModelRequest,
    StructuredModelResult,
)
from umd.models.registry import ProviderRegistry

__all__ = [
    "Embedder",
    "ModelCallRecord",
    "ModelCost",
    "ModelMode",
    "ModelProvider",
    "ModelProviderUnavailable",
    "ModelRequest",
    "ProviderRegistry",
    "StructuredModelResult",
]
