"""ASGI runtime wiring for the UMD API service.

:func:`app_factory` is the zero-argument ASGI entrypoint uvicorn's ``--factory``
mode expects: it builds the configured Postgres engine and OCFL ``SourceStore``
from environment-driven settings and returns the fully wired app. Keeping this
separate from :func:`umd.api.app.create_app` lets unit tests inject engines/stores
explicitly while containers use the same wiring.
"""

from __future__ import annotations

from typing import Any

from umd.api.app import create_app, engine_from_settings
from umd.config import Settings, get_settings
from umd.storage.ocfl.store import SourceStore


def build_source_store(settings: Settings) -> SourceStore:
    """Construct and, on first deployment, bootstrap the configured OCFL root."""
    return SourceStore.create(root=settings.ocfl.root)


def app_factory() -> Any:
    """Zero-arg ASGI app factory bound to the configured runtime resources."""
    settings = get_settings()
    engine = engine_from_settings(settings)
    source_store = build_source_store(settings)
    return create_app(
        engine=engine,
        source_store=source_store,
        settings=settings,
    )


__all__ = ["app_factory", "build_source_store"]
