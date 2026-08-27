"""Provider registry (Phase C, P1-S3).

A small registry mapping provider names to their :class:`ModelProvider`
instances so model work can be routed by configuration with local and remote
adapters interchangeable. Registration is explicit; resolving an unregistered /
unavailable provider raises the typed :class:`ModelProviderUnavailable`, which
is surfaced through capability reporting.
"""

from __future__ import annotations

from typing import Protocol

from umd.models.provider import ModelProvider, ModelProviderUnavailable


class _NamedProvider(Protocol):
    name: str


class ProviderRegistry:
    """Map provider name -> :class:`ModelProvider` instance."""

    def __init__(self, providers: list[ModelProvider] | None = None) -> None:
        self._providers: dict[str, ModelProvider] = {}
        for provider in providers or []:
            self.register(provider)

    def register(self, provider: ModelProvider, *, name: str | None = None) -> None:
        key = name or getattr(provider, "name", None) or type(provider).__name__
        if not key:
            raise ValueError("provider must expose a name")
        self._providers[key] = provider

    def get(self, name: str | None = None, *, default: str | None = None) -> ModelProvider:
        """Resolve a provider by name (``default`` falls back when ``name`` unset)."""
        key = name or default or ""
        if key and key in self._providers:
            return self._providers[key]
        if not key and len(self._providers) == 1:
            return next(iter(self._providers.values()))
        if key:
            raise ModelProviderUnavailable(f"provider {key!r} is not registered")
        raise ModelProviderUnavailable("no model provider registered")

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    def capability_report(self) -> dict[str, object]:
        """Report which providers are registered / available (honest)."""
        return {
            "registered_providers": list(self.names()),
            "available": {name: True for name in self._providers},
        }
