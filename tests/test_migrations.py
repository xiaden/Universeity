"""Structural-migration tests (P1-S2) + ledger/ownership constraints (P1-S4).

DB-dependent tests are marked ``postgres`` and need a live server with
``UMD_TEST_POSTGRES=true``. The offline-generation test runs without a DB.
"""

from __future__ import annotations

import os
import uuid

import pytest
import sqlalchemy as sa

from umd.storage.postgres import metadata

pytestmark = pytest.mark.postgres

# Envelope columns mandated by the DD for ``semantic_event``.
ENVELOPE = [
    "seq",
    "event_type",
    "event_version",
    "schema_url",
    "tx_time",
    "valid_time",
    "authority",
    "confidence",
    "generated_by",
    "correlation_id",
    "causation_id",
    "payload",
    "idempotency_key",
    "created_by",
]

CORE_TABLES = [
    "work",
    "continuity",
    "source",
    "source_membership",
    "edition",  # work/continuity/edition/membership
    "segment",
    "evidence",
    "artifact",  # segments + evidence/artifact refs
    "entity",
    "entity_mention",
    "predicate",  # entities/mentions + predicates
    "semantic_assertion",
    "semantic_event",  # semantic ledger envelope
    "current_state",
    "current_entity_map",  # Tier-0 projections
    "alignment",
    "stage_run",
    "job",
    "job_run_audit",
    "embedding",
    "projection_checkpoint",  # stage/job/embedding/projection
    "quarantine",
    "locator_rebase",
]


def test_metadata_maps_all_core_tables() -> None:
    """The canonical SQLAlchemy metadata covers every DD core table."""
    for t in CORE_TABLES:
        assert t in metadata.tables, f"missing core table {t}"
    assert metadata.tables["semantic_event"].c.seq.autoincrement is True


def test_offline_migration_sql_generates() -> None:
    """Alembic offline mode produces compilable DDL without a live DB."""
    import subprocess
    import sys
    from pathlib import Path

    alembic_bin = Path(sys.executable).parent / "alembic"
    result = subprocess.run(
        [str(alembic_bin), "upgrade", "head", "--sql"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        env=dict(
            os.environ,
            UMD_POSTGRES__DSN="postgresql+psycopg://u:p@localhost/db",
        ),
    )
    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE semantic_event" in result.stdout
    assert "CREATE TABLE source" in result.stdout
    assert "block_semantic_event_mutate" in result.stdout


def test_all_core_tables_exist_after_upgrade(migrated_db: sa.Engine) -> None:
    inspector = sa.inspect(migrated_db)
    names = set(inspector.get_table_names())
    assert set(CORE_TABLES) <= names
    assert "alembic_version" in names


def test_double_upgrade_head_is_idempotent(migrated_db: sa.Engine) -> None:
    """Re-running ``upgrade head`` is a clean no-op preserving the schema.

    Exercises the idempotency guards on 0002 (``job`` table, already created by
    0001's ``metadata.create_all`` on a fresh bootstrap) and 0003 (the
    ``uq_evidence_identity`` index), plus the Alembic no-op path when the chain
    is already at head — a second pass must never error or drop schema.
    """
    import os

    import alembic.command as alembic_command
    from alembic.config import Config as AlembicConfig

    dsn = migrated_db.url.render_as_string(hide_password=False)
    cfg = AlembicConfig("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", dsn)
    _prev = os.environ.get("UMD_POSTGRES__DSN")
    os.environ["UMD_POSTGRES__DSN"] = dsn
    try:
        alembic_command.upgrade(cfg, "head")  # second pass — must not raise
    finally:
        if _prev is None:
            os.environ.pop("UMD_POSTGRES__DSN", None)
        else:
            os.environ["UMD_POSTGRES__DSN"] = _prev

    inspector = sa.inspect(migrated_db)
    names = set(inspector.get_table_names())
    assert set(CORE_TABLES) <= names
    assert "alembic_version" in names
    # 0003's unique index survives the second pass.
    assert "uq_evidence_identity" in {i["name"] for i in inspector.get_indexes("evidence")}


def test_semantic_event_envelope_columns(migrated_db: sa.Engine) -> None:
    inspector = sa.inspect(migrated_db)
    cols = {c["name"] for c in inspector.get_columns("semantic_event")}
    assert set(ENVELOPE) <= cols
    # seq must be a bigint identity backing a BIGSERIAL sequence.
    seq_type = next(c for c in inspector.get_columns("semantic_event") if c["name"] == "seq")
    assert "BIGINT" in str(seq_type["type"]).upper() or "BIGSERIAL" in str(seq_type["type"]).upper()


def test_ledger_is_append_only(migrated_db: sa.Engine) -> None:
    """No in-place UPDATE on the semantic-event ledger (DD invariant)."""
    # Commit the insert in its own transaction first.
    with migrated_db.begin() as conn:
        res = conn.execute(
            sa.text(
                "INSERT INTO semantic_event "
                "(event_type,event_version,schema_url,payload,idempotency_key) "
                "VALUES ('SourceIngested',1,'s','{}'::jsonb,:k) RETURNING seq"
            ),
            {"k": str(uuid.uuid4())},
        )
        seq = res.scalar()
    # Attempted in-place UPDATE must be blocked by the append-only trigger.
    with pytest.raises(sa.exc.DBAPIError), migrated_db.begin() as conn:
        conn.execute(
            sa.text("UPDATE semantic_event SET event_type='HACKED' WHERE seq=:s"), {"s": seq}
        )
    # Trigger blocked the update: the row is unchanged and still present.
    with migrated_db.connect() as conn:
        val = conn.execute(
            sa.text(
                "SELECT count(*) FROM semantic_event WHERE seq=:s AND event_type='SourceIngested'"
            ),
            {"s": seq},
        ).scalar()
        # DELETE must also be blocked.
        with pytest.raises(sa.exc.DBAPIError):
            conn.execute(sa.text("DELETE FROM semantic_event WHERE seq=:s"), {"s": seq})
    assert val == 1
    assert _count(migrated_db, "semantic_event") == 1


def test_embedding_is_append_only(migrated_db: sa.Engine) -> None:
    """embedding rows are immutable: UPDATE and DELETE are denied by trigger."""
    sid = "00000000-0000-0000-0000-000000000001"
    seg_id = "00000000-0000-0000-0000-000000000002"
    emb_id = "00000000-0000-0000-0000-000000000003"
    with migrated_db.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO source (id, ocfl_ref, sha512, size_bytes, media_kind, original_name)"
                " VALUES (:id, 'urn:ocfl:e', :sha, 3, 'text', 'e.txt')"
            ),
            {"id": sid, "sha": "d" * 128},
        )
        conn.execute(
            sa.text(
                "INSERT INTO segment (id, source_id, segment_type, deterministic_key)"
                " VALUES (:id, :sid, 'text', 'seg:1')"
            ),
            {"id": seg_id, "sid": sid},
        )
        conn.execute(
            sa.text(
                "INSERT INTO embedding (id, segment_id, model, model_version, evidence_ref,"
                " sequence_no)"
                " VALUES (:id, :sid, 'test-model', '1', 'ev:1', 1)"
            ),
            {"id": emb_id, "sid": seg_id},
        )
    # In-place UPDATE must be blocked by the immutable-row trigger.
    with pytest.raises(sa.exc.DBAPIError), migrated_db.begin() as conn:
        conn.execute(sa.text("UPDATE embedding SET model='HACKED' WHERE id=:id"), {"id": emb_id})
    # DELETE must also be blocked.
    with pytest.raises(sa.exc.DBAPIError), migrated_db.begin() as conn:
        conn.execute(sa.text("DELETE FROM embedding WHERE id=:id"), {"id": emb_id})
    # Row unchanged and still present.
    with migrated_db.connect() as conn:
        val = conn.execute(
            sa.text("SELECT count(*) FROM embedding WHERE id=:id AND model='test-model'"),
            {"id": emb_id},
        ).scalar()
    assert val == 1


def _count(engine: sa.Engine, table: str) -> int:
    with engine.connect() as conn:
        # noqa: S608 (single internal call with a static table literal)
        return int(conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar())  # noqa: S608


def test_source_content_addressed_unique(migrated_db: sa.Engine) -> None:
    """A duplicate sha512 (same raw bytes) must be rejected — content addressing."""
    sha = "a" * 128
    with migrated_db.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO source (ocfl_ref,sha512,size_bytes,media_kind,original_name)"
                " VALUES (:ref,:sha,3,'text','a.txt')"
            ),
            {"ref": "urn:ocfl:a", "sha": sha},
        )
        with pytest.raises(sa.exc.DBAPIError):
            conn.execute(
                sa.text(
                    "INSERT INTO source (ocfl_ref,sha512,size_bytes,media_kind,original_name)"
                    " VALUES (:ref,:sha,3,'text','b.txt')"
                ),
                {"ref": "urn:ocfl:b", "sha": sha},
            )


def test_idempotency_key_unique(migrated_db: sa.Engine) -> None:
    key = str(uuid.uuid4())
    with migrated_db.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO semantic_event (event_type,event_version,payload,idempotency_key)"
                " VALUES ('SegmentCreated',1,'{}'::jsonb,:k)"
            ),
            {"k": key},
        )
        with pytest.raises(sa.exc.DBAPIError):
            conn.execute(
                sa.text(
                    "INSERT INTO semantic_event (event_type,event_version,payload,idempotency_key)"
                    " VALUES ('SegmentCreated',1,'{}'::jsonb,:k)"
                ),
                {"k": key},
            )
