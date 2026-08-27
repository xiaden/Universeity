"""Shared pytest fixtures.

Two fixture families:

* ``ocfl_root`` / ``source_store`` — filesystem-substrate OCFL fixtures that need
  no live database.
* ``live_postgres``-family — session fixtures that bootstrap a throwaway
  PostgreSQL database, apply the full Alembic migration chain, and return an
  engine. These require a live PostgreSQL server and the ``UMD_TEST_POSTGRES``
  env var; otherwise the ``postgres``-marked tests are skipped.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig

from umd.storage.ocfl import SourceStore

# Recommended Postgres 17 client tools (server-side binaries are not on $PATH).
PG_BIN = os.environ.get("UMD_PG_BIN", "/usr/lib/postgresql/17/bin")
PG_HOST = os.environ.get("UMD_PG_HOST", "127.0.0.1")
PG_PORT = os.environ.get("UMD_PG_PORT", "5432")

ADMIN_DSN = f"postgresql+psycopg://umd:umd@{PG_HOST}:{PG_PORT}/postgres"


def _postgres_available() -> bool:
    if os.environ.get("UMD_TEST_POSTGRES") != "true":
        return False
    try:
        engine = sa.create_engine(ADMIN_DSN, poolclass=sa.pool.NullPool)
        with engine.connect():
            return True
    except Exception:
        return False


_POSTGRES = _postgres_available()


@pytest.fixture(scope="session")
def postgres_available() -> bool:
    return _POSTGRES


@pytest.fixture(scope="session")
def ocfl_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return Path(tmp_path_factory.mktemp("ocfl_root"))


@pytest.fixture(scope="session")
def source_store(ocfl_root: Path) -> SourceStore:
    return SourceStore.create(
        root=ocfl_root,
        max_upload_bytes=512 * 1024,
        max_range_bytes=4096,
    )


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[sa.Engine]:
    """Bootstrap a throwaway migrated PostgreSQL database (session scope)."""
    if not _POSTGRES:
        pytest.skip("live PostgreSQL unavailable; set UMD_TEST_POSTGRES=true and start a server")

    dbname = f"umd_p1test_{uuid.uuid4().hex[:8]}"
    admin = sa.create_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT", poolclass=sa.pool.NullPool)
    with admin.connect() as conn:
        conn.exec_driver_sql(f'CREATE DATABASE "{dbname}"')
    test_dsn = f"postgresql+psycopg://umd:umd@{PG_HOST}:{PG_PORT}/{dbname}"

    # Apply the full Alembic migration chain to the fresh database. env.py reads
    # UMD_POSTGRES__DSN first, so pin it for the duration of the migration.
    cfg = AlembicConfig("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", test_dsn)
    _prev = os.environ.get("UMD_POSTGRES__DSN")
    os.environ["UMD_POSTGRES__DSN"] = test_dsn
    try:
        alembic_command.upgrade(cfg, "head")
    finally:
        if _prev is None:
            os.environ.pop("UMD_POSTGRES__DSN", None)
        else:
            os.environ["UMD_POSTGRES__DSN"] = _prev

    engine = sa.create_engine(test_dsn, poolclass=sa.pool.NullPool)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            # noqa: S608 (dbname is an internally-generated uuid, not user input)
            conn.exec_driver_sql(
                f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{dbname}' AND pid <> pg_backend_pid()"
            )  # noqa: S608
            conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{dbname}"')  # noqa: S608


@pytest.fixture()
def settings_clean():
    """Force a fresh settings object for config tests."""
    from umd.config import Settings

    return Settings


@pytest.fixture(scope="session")
def pg_bin() -> Path:
    return Path(PG_BIN)


# ---------------------------------------------------------------------------
# Phase-3 isolation: app tables are truncated before AND after each postgres test
# so tests that count ledger/Tier-0/source rows never pollute the shared session DB
# (and never break the Phase-1/2 tests that assume an empty ledger, e.g.
# test_migrations.test_ledger_is_append_only counting semantic_event == 1).
# ---------------------------------------------------------------------------

_UMD_APP_TABLES = (
    "semantic_event",
    "current_state",
    "current_entity_map",
    "source",
    "source_membership",
    "segment",
    "evidence",
    "entity",
    "entity_mention",
    "semantic_assertion",
    "alignment",
    "stage_run",
    "job_run_audit",
    "embedding",
    "projection_checkpoint",
    "quarantine",
    "locator_rebase",
    "work",
    "edition",
    "continuity",
    "artifact",
    "predicate",
    "search_document",
    "projection_generation",
)


def _truncate(engine: sa.Engine) -> None:
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "TRUNCATE TABLE " + ", ".join(_UMD_APP_TABLES) + " RESTART IDENTITY CASCADE"
        )


@pytest.fixture()
def umd_db(migrated_db: sa.Engine) -> Iterator[sa.Engine]:
    """Isolated, clean set of app tables for a Phase-3 postgres test."""
    _truncate(migrated_db)
    yield migrated_db
    _truncate(migrated_db)
