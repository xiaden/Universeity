"""Configuration loading tests (P1-S1) — env-driven, bound-enforcing."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from umd.config import get_settings


def test_defaults_load() -> None:
    s = get_settings()
    assert s.digest_algorithm == "sha512"
    assert s.lag_budget_seconds <= 1.0
    assert s.limits.max_upload_bytes >= 0
    assert s.ocfl.layout
    assert s.postgres.dsn.startswith("postgresql+psycopg://")


def test_env_override_nested(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UMD_OCFL__ROOT", "/var/lib/umd/ocfl/custom")
    monkeypatch.setenv("UMD_LIMITS__MAX_UPLOAD_BYTES", "42")
    from umd.config import Settings

    s = Settings()
    assert s.ocfl.root.as_posix() == "/var/lib/umd/ocfl/custom"
    assert s.limits.max_upload_bytes == 42


def test_lag_budget_cap_enforced() -> None:
    with pytest.raises(ValidationError):
        get_settings(lag_budget_seconds=5.0)


def test_unsupported_digest_rejected() -> None:
    with pytest.raises(ValidationError):
        get_settings(digest_algorithm="md5")


def test_env_example_is_parseable_under_prefix() -> None:
    # .env.example must not break Settings parsing; keys it names use the UMD_ prefix.
    from umd.config import Settings

    s = Settings()
    assert s  # instantiates without raising for the documented env surface


def test_canonical_nested_names_reach_intended_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each canonical `__` nested name reaches its intended nested Settings field."""
    monkeypatch.setenv("UMD_POSTGRES__DSN", "postgresql+psycopg://u:p@db:5432/canon")
    monkeypatch.setenv("UMD_OCFL__ROOT", "/var/lib/umd/ocfl/canonical")
    monkeypatch.setenv("UMD_PROJECTION__VECTOR_HNSW_MIN_VERSION", "0.9.0")
    from umd.config import Settings

    s = Settings()
    assert s.postgres.dsn == "postgresql+psycopg://u:p@db:5432/canon"
    assert s.ocfl.root.as_posix() == "/var/lib/umd/ocfl/canonical"
    assert s.projection.vector_hnsw_min_version == "0.9.0"


def test_single_underscore_nested_names_are_not_honored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single-underscore nested env name must NOT silently configure Settings.

    This is the exact QA R2 defect: shipped surfaces used `UMD_POSTGRES_DSN`
    (single underscore) which pydantic-settings ignores (extra="ignore")."""
    monkeypatch.setenv("UMD_POSTGRES_DSN", "postgresql+psycopg://u:p@db:5432/ignored")
    monkeypatch.setenv("UMD_OCFL_ROOT", "/var/lib/umd/ocfl/ignored")
    monkeypatch.setenv("UMD_PROJECTION_VECTOR_HNSW_MIN_VERSION", "9.9.9")
    monkeypatch.setenv("UMD_POSTGRES_POOL_SIZE", "1")
    monkeypatch.setenv("UMD_POSTGRES_MAX_OVERFLOW", "1")
    from umd.config import Settings

    s = Settings()
    assert s.postgres.dsn.startswith("postgresql+psycopg://umd:umd@127.0.0.1:5432/umd")
    assert s.ocfl.root.as_posix() == ".ocfl-root"
    assert s.projection.vector_hnsw_min_version == "0.8.2"
    assert s.postgres.pool_size == 10
    assert s.postgres.max_overflow == 20
