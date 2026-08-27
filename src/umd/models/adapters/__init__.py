"""Model provider adapters (Phase C, P1-S3): local Ollama, remote, optional vLLM."""

from umd.models.adapters.ollama import OllamaProvider
from umd.models.adapters.remote import OpenAICompatProvider
from umd.models.adapters.vllm import VLLM_ENABLED, VLLMProvider

__all__ = ["OllamaProvider", "OpenAICompatProvider", "VLLMProvider", "VLLM_ENABLED"]
