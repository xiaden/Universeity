"""Plan E (P2-S3/P2-S4): independent backup/restore + replay recovery.

Two authorities are backed up/restored independently and VERIFIED:

* PostgreSQL — the append-only ``semantic_event`` ledger and Tier-0
  ``current_state`` snapshot to portable JSONL; restore reloads the ledger
  (preserving ``seq``/``causation_id``), replays ``current_state`` from ``seq=0``
  through the ONE shared pure reducer, and asserts the replayed Tier-0 is
  checksum-equivalent to the backup (the deterministic digest reused for
  cross-tier equivalence), and that a subsequent append continues past the
  restored ``max_seq``.
* OCFL — the immutable byte store is copied (declaration + layout + each
  object's inventory + content), restored to a fresh root, and validated with
  ``SourceStore.verify_fixity`` on every object; a tampered byte yields an
  honest ``ok=False`` (fixity is proven, never assumed).

Also covers: old locators/events remain readable after version changes, the
OCFL local-spool read (and its failure/remote-spool analog) is exercised, and
the sandbox argv for untrusted media stages never requests privileges.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest
import sqlalchemy as sa

from umd.domain.events import SemanticEvent
from umd.storage.ocfl.store import SourceDescriptor, SourceStore, StoreError
from umd.storage.postgres.ledger import SemanticLedger
from umd.storage.postgres.reducer import (
    STATE_USER_CONFIRMED,
    USER_OVERRIDE,
    CurrentStateReducer,
)
from umd.storage.postgres.tables import metadata as db_meta

pytestmark = pytest.mark.postgres

_se = db_meta.tables["semantic_event"]
_cs = db_meta.tables["current_state"]


def _assertion(seq: int, ref: str, value: str, *, scope: str = "CONTINUITY") -> SemanticEvent:
    return SemanticEvent(
        event_type="SemanticAsserted",
        seq=seq,
        authority="machine",
        payload={
            "predicate_code": "SPEAKS",
            "subject_ref": ref,
            "object_ref": value,
            "authority": "machine",
            "confidence": 0.6,
            "state": "PROBABLE",
            "scope": scope,
        },
    )


def _sha256(path: Path) -> str:
    """sha256 of a file's bytes (matches the snapshot manifest digest)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_events(engine: sa.Engine) -> list[SemanticEvent]:
    """Load every ledger row in seq order (seq preserved for re-insertion)."""
    with engine.connect() as conn:
        rows = conn.execute(
            sa.select(
                _se.c.seq,
                _se.c.event_type,
                _se.c.event_version,
                _se.c.payload,
                _se.c.authority,
                _se.c.created_by,
            ).order_by(_se.c.seq)
        ).fetchall()
    return [
        SemanticEvent(
            event_type=r.event_type,
            payload=dict(r.payload or {}),
            authority=r.authority,
            created_by=r.created_by,
            seq=int(r.seq),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# PostgreSQL backup / restore / replay
# ---------------------------------------------------------------------------


def test_independent_pg_backup_restore_replay_equals_inline(
    umd_db: sa.Engine, tmp_path: Path
) -> None:
    """Restore replays Tier-0 from seq=0 to a checksum identical to inline append."""
    from umd.projections.current import tier0_checksum
    from umd.recovery.postgres_backup import RestoreReport, backup_postgres, restore_postgres

    ledger = SemanticLedger(umd_db)
    ledger.append(
        [
            _assertion(0, "e:1", "utter:1"),
            _assertion(0, "e:2", "utter:9"),
        ]
    )
    ledger.append(
        [
            SemanticEvent(
                event_type="OverrideApplied",
                authority=USER_OVERRIDE,
                payload={"subject_ref": "e:1", "predicate": "SPEAKS", "object_ref": "u:truth"},
            )
        ]
    )
    ledger.append([_assertion(0, "e:1", "utter:should-not-win")])

    inline_checksum = tier0_checksum(umd_db)
    manifest = backup_postgres(umd_db, tmp_path / "backup")
    assert manifest.current_state_checksum == inline_checksum

    # Simulate a full ledger + Tier-0 loss (authority gone), then restore.
    with umd_db.begin() as conn:
        conn.exec_driver_sql(
            "TRUNCATE TABLE semantic_event, current_state RESTART IDENTITY CASCADE"
        )

    report: RestoreReport = restore_postgres(umd_db, tmp_path / "backup")
    assert report.checksum_verified is True
    assert report.restored_events == 4
    assert report.current_state_checksum == inline_checksum

    # Replay-from-seq=0 reproduced the inline Tier-0 EXACTLY (checksum + rows).
    replayed = CurrentStateReducer().replay(_load_events(umd_db))
    assert replayed.rows[("e:1", "SPEAKS")].object_ref == "u:truth"
    assert replayed.rows[("e:1", "SPEAKS")].authority == USER_OVERRIDE
    assert replayed.rows[("e:1", "SPEAKS")].state == STATE_USER_CONFIRMED

    # The restored ledger is appendable and the sequence advanced past max_seq:
    # a fresh append yields a seq strictly greater than the restored head.
    after = ledger.append([_assertion(0, "e:3", "utter:new")])
    assert after.seq > report.max_seq
    assert after.read_your_writes_token == after.seq
    with umd_db.connect() as conn:
        n = conn.execute(sa.select(sa.func.count()).select_from(_se)).scalar()
    assert n == 5  # 4 restored + 1 new append


def test_restore_rejects_tampered_backup_recovery(umd_db: sa.Engine, tmp_path: Path) -> None:
    """A corrupted snapshot is refused (self-integrity), never silently restored."""
    from umd.recovery.postgres_backup import RecoveryError, backup_postgres, restore_postgres

    SemanticLedger(umd_db).append([_assertion(0, "e:1", "utter:1")])
    snapshot = tmp_path / "backup"
    backup_postgres(umd_db, snapshot)
    path = snapshot / "ledger.jsonl"
    data = bytearray(path.read_bytes())
    data[0] ^= 0xFF
    path.write_bytes(bytes(data))

    with pytest.raises(RecoveryError):
        restore_postgres(umd_db, snapshot)
    # Integrity guard fires BEFORE any TRUNCATE, so the live ledger is untouched.
    with umd_db.connect() as conn:
        n = conn.execute(sa.select(sa.func.count()).select_from(_se)).scalar()
    assert n == 1


def test_old_locator_and_event_readable_after_version_change(
    umd_db: sa.Engine, tmp_path: Path
) -> None:
    """After backup/restore, OLD (v1/no-scope) events and locators stay readable.

    Restore must not require every event to be at the newest schema version: a
    v1 ``SemanticAsserted`` (no ``scope``) is upcast during replay (GLOBAL) but
    the original event row (old version, old payload) remains in the ledger and
    the entity locator remains resolvable to its persisted value.
    """
    from umd.recovery.postgres_backup import backup_postgres, restore_postgres

    ledger = SemanticLedger(umd_db)
    ledger.append([_assertion(0, "old:1", "utter:legacy")])
    with umd_db.connect() as conn:
        row = conn.execute(
            sa.select(_se.c.event_version, _se.c.payload).where(_se.c.seq == 1)
        ).one()
    assert int(row.event_version) == 2  # stored at the current (v2) schema

    snapshot = tmp_path / "backup"
    backup_postgres(umd_db, snapshot)

    # Simulate a legacy snapshot written under the PREVIOUS schema: rewrite the
    # single ledger record to event_version 1 with ``scope`` removed, as it would
    # have been persisted before the SemanticAsserted scope-upcast shipped.
    ledger_path = snapshot / "ledger.jsonl"
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[0])
    rec["event_version"] = 1
    rec["payload"].pop("scope", None)
    lines[0] = json.dumps(rec, sort_keys=True)
    ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    mang = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    mang["ledger_sha256"] = _sha256(ledger_path)
    (snapshot / "manifest.json").write_text(json.dumps(mang, sort_keys=True), encoding="utf-8")

    restore_postgres(umd_db, snapshot)

    # Old event row preserved verbatim (still v1, old payload readable).
    with umd_db.connect() as conn:
        rows = conn.execute(
            sa.select(_se.c.seq, _se.c.event_type, _se.c.event_version, _se.c.payload)
        ).fetchall()
    assert len(rows) == 1
    assert rows[0].event_type == "SemanticAsserted"
    assert int(rows[0].event_version) == 1
    assert "scope" not in (rows[0].payload or {})

    # The locator resolves through the upcaster (v1 -> v2 adds GLOBAL scope):
    # old:1 remains readable and reproducible after the version change.
    replayed = CurrentStateReducer().replay(_load_events(umd_db))
    assert replayed.rows[("old:1", "SPEAKS")].object_ref == "utter:legacy"


# ---------------------------------------------------------------------------
# OCFL backup / restore / fixity
# ---------------------------------------------------------------------------


def test_ocfl_backup_restore_fixity_and_readback(tmp_path: Path) -> None:
    """OCFL authority round-trips: copy, restore to a fresh root, fixity + bytes."""
    from umd.recovery.ocfl_backup import backup_ocfl, restore_ocfl

    root = tmp_path / "ocfl_live"
    store = SourceStore.create(root=root, max_upload_bytes=1024 * 1024)
    payload = b"The immutable, content-addressed source bytes \x00\x01\x02."
    man = store.put_immutable(io.BytesIO(payload), SourceDescriptor(logical_name="src.bin"))

    snapshot = tmp_path / "ocfl_backup"
    report = backup_ocfl(root, snapshot)
    assert report.objects_found == 1
    assert report.ok is True  # fixity validated ON the copy in the same step

    restored_root = tmp_path / "ocfl_restored"
    restored_report = restore_ocfl(snapshot, restored_root)
    assert restored_report.objects_found == 1
    assert restored_report.ok is True

    restored = SourceStore(root=restored_root)
    assert restored.has_object(man.object_id) is True
    rep = restored.get_range(man.object_id)
    assert rep.data == payload
    assert rep.sha512 == man.sha512  # fixity metadata matches original digest


def test_ocfl_fixity_detects_tampered_bytes(tmp_path: Path) -> None:
    """Fixity validation is real: a flipped content byte makes verification fail."""
    from umd.recovery.ocfl_backup import backup_ocfl, verify_ocfl

    root = tmp_path / "ocfl_live"
    store = SourceStore.create(root=root, max_upload_bytes=1024 * 1024)
    man = store.put_immutable(io.BytesIO(b"aaaa bbbb cccc"), SourceDescriptor(logical_name="a.txt"))
    assert store.verify_fixity(man.object_id) is True

    snapshot = tmp_path / "snap"
    assert backup_ocfl(root, snapshot).ok is True

    # Corrupt an object's content bytes in the snapshot.
    target = next(snapshot.rglob("content/*"))
    original = target.read_bytes()
    target.write_bytes(original[:-1] + bytes([original[-1] ^ 0xFF]))

    report = verify_ocfl(snapshot)
    assert report.objects_found == 1
    assert report.ok is False  # fixity must catch the tamper
    assert report.entries[0].ok is False


def test_ocfl_local_spool_read_and_failure(tmp_path: Path) -> None:
    """OCFL local-spool read returns correct bytes; a vanished object surfaces failure.

    The OCFL spool/remote-FUSE failure mode (DD U7) demands the read path FAIL
    loudly rather than return silently corrupted/garbage data when the backing
    bytes are gone. With no FUSE bridge in this environment, the identical
    boundary is exercised against the local filesystem store: a missing object
    raises ``StoreError`` and fixity of a deleted object is ``False``.
    """
    from umd.recovery.ocfl_backup import verify_ocfl

    root = tmp_path / "ocfl_live"
    store = SourceStore.create(root=root, max_upload_bytes=1024 * 1024)
    man = store.put_immutable(
        io.BytesIO(b"42 bytes of authoritative content"), SourceDescriptor(logical_name="x.bin")
    )
    # Local spool read returns the exact bytes.
    assert store.get_range(man.object_id).data == b"42 bytes of authoritative content"

    # Remote/spool-failure analog: content bytes removed => every read/verify FAILS
    # loudly (never silently returns corrupted/garbage data).
    content = next(root.rglob("content/*"))
    content.unlink()
    with pytest.raises((StoreError, OSError)):
        store.get_range(man.object_id)
    with pytest.raises((StoreError, OSError)):
        store.verify_fixity(man.object_id)
    # verify_ocfl also reports the degraded object honestly (not a pass).
    assert any(not e.ok for e in verify_ocfl(root).entries)


# ---------------------------------------------------------------------------
# Sandbox posture (never privileged)
# ---------------------------------------------------------------------------


def test_sandbox_bwrap_argv_never_privileged() -> None:
    """Building the media-stage bwrap argv never requests privileges."""
    from umd.security.bwrap import build_bwrap_argv

    argv = build_bwrap_argv(["ffprobe", "-i", "/spool/in"], read_only_binds=["/spool"])
    assert "--privileged" not in argv
    assert "--cap-add" not in argv  # no capability grant
    assert "--share-net" not in argv
    # It is a genuinely confined profile.
    assert "--unshare-all" in argv
    assert "--die-with-parent" in argv
    assert "--ro-bind" in argv
