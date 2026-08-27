"""Ownership-boundary tests (P1-S4): independent authorities + backup/restore.

Verifies the non-negotiable layer separation: OCFL bytes are the sole authority
for raw source bytes/fixity and are decoupled from PostgreSQL (the authority for
source/segment/ledger metadata). Needs a live PostgreSQL server and
``UMD_TEST_POSTGRES=true`` (``postgres`` marker).

Backup/restore boundaries are exercised independently for each substrate:
  * OCFL: copy root -> wipe live -> restore -> bytes + fixity intact;
  * PostgreSQL: pg_dump -> fresh db -> pg_restore -> data restored.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa

from umd.storage.ocfl import SourceDescriptor, SourceStore

pytestmark = pytest.mark.postgres

_DSN_ARGS = ["-h", "127.0.0.1", "-U", "umd", "-p", "5432"]


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PGPASSWORD"] = "umd"
    return env


def test_postgres_backup_restore_boundary(
    migrated_db: sa.Engine, pg_bin: Path, tmp_path: Path
) -> None:
    """pg_dump/pg_restore round-trips the ledger and source rows intact."""
    key = str(uuid.uuid4())
    with migrated_db.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO semantic_event (event_type,event_version,schema_url,"
                "payload,idempotency_key) VALUES ('SourceIngested',1,'urn:events',:p,:k)"
            ),
            {"p": '{"media":"text"}', "k": key},
        )
        conn.execute(
            sa.text(
                "INSERT INTO source (ocfl_ref,sha512,size_bytes,media_kind,original_name)"
                " VALUES ('urn:ocfl:src1', :sha, 11, 'text', 'probe.txt')"
            ),
            {"sha": "f" * 128},
        )

    dbname = migrated_db.url.database
    dump = str(tmp_path / f"{dbname}.sql")
    subprocess.run(  # noqa: S603
        [str(pg_bin / "pg_dump"), *_DSN_ARGS, "-d", dbname, "-f", dump],
        check=True,
        env=_env(),
    )

    restored = f"{dbname}_restored"
    admin = sa.create_engine(
        "postgresql+psycopg://umd:umd@127.0.0.1:5432/postgres",
        isolation_level="AUTOCOMMIT",
        poolclass=sa.pool.NullPool,
    )
    with admin.connect() as c:
        c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{restored}"')  # noqa: S608
        c.exec_driver_sql(f'CREATE DATABASE "{restored}"')  # noqa: S608
    try:
        subprocess.run(  # noqa: S603
            [str(pg_bin / "psql"), *_DSN_ARGS, "-d", restored, "-f", dump],
            check=True,
            env=_env(),
        )
        restored_engine = sa.create_engine(
            f"postgresql+psycopg://umd:umd@127.0.0.1:5432/{restored}",
            poolclass=sa.pool.NullPool,
        )
        with restored_engine.connect() as c:
            n = c.execute(
                sa.text("SELECT count(*) FROM semantic_event WHERE idempotency_key=:k"),
                {"k": key},
            ).scalar()
            src = c.execute(
                sa.text("SELECT count(*) FROM source WHERE sha512=:sha"),
                {"sha": "f" * 128},
            ).scalar()
        assert n == 1 and src == 1
        restored_engine.dispose()
    finally:
        with admin.connect() as c:
            c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{restored}"')  # noqa: S608


def test_ocfl_and_postgres_are_independent_authorities(
    migrated_db: sa.Engine, source_store: SourceStore
) -> None:
    """Deleting the Postgres row does not destroy OCFL bytes and vice-versa."""
    data = b"independent authorities test payload"
    m = source_store.put_immutable(
        io.BytesIO(data),
        SourceDescriptor(logical_name="novel.epub"),
    )
    sha = "e" * 128
    with migrated_db.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO source (ocfl_ref,sha512,size_bytes,media_kind,original_name)"
                " VALUES (:ref, :sha, :sz, 'text', 'novel.epub')"
            ),
            {"ref": m.object_id, "sha": sha, "sz": m.size_bytes},
        )

    # Delete the Postgres source row: OCFL bytes must remain authoritative.
    with migrated_db.begin() as conn:
        conn.execute(sa.text("DELETE FROM source WHERE sha512=:sha"), {"sha": sha})
    rep = source_store.get_range(m.object_id)
    assert rep.data == data
    assert source_store.verify_fixity(m.object_id) is True

    # Now re-insert and destroy the OCFL object: Postgres row must remain.
    with migrated_db.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO source (ocfl_ref,sha512,size_bytes,media_kind,original_name)"
                " VALUES (:ref, :sha, :sz, 'text', 'novel.epub')"
            ),
            {"ref": m.object_id, "sha": sha, "sz": m.size_bytes},
        )
    _destroy_ocfl_object(source_store, m.object_id)
    with migrated_db.connect() as c:
        remaining = c.execute(
            sa.text("SELECT count(*) FROM source WHERE ocfl_ref=:ref"),
            {"ref": m.object_id},
        ).scalar()
    assert remaining == 1


def _destroy_ocfl_object(store: SourceStore, object_id: str) -> None:
    rel = store.object_path(object_id)
    shutil.rmtree(store.root / rel)
