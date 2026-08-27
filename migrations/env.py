"""Alembic environment.

Resolves the database URL from ``UMD_POSTGRES__DSN`` (falling back to
``umd.config``) and targets the canonical typed-relational-core metadata that
lives in :mod:`umd.storage.postgres`.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from umd.config import get_settings
from umd.storage.postgres import metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_dsn = os.environ.get("UMD_POSTGRES__DSN") or get_settings().postgres.dsn
config.set_main_option("sqlalchemy.url", _dsn)

target_metadata = metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live connection (validation/CI)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
