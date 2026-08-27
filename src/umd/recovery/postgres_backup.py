"""Independent PostgreSQL ledger + Tier-0 ``current_state`` backup and restore.

Backup produces two portable JSONL artifacts (plus a tiny manifest):

* ``ledger.jsonl``         — every ``semantic_event`` row, preserving the full
  retained envelope (``seq``, ``event_type``, ``event_version``, ``schema_url``,
  ``tx_time``, ``valid_time``, ``authority``, ``confidence``, ``generated_by``,
  ``correlation_id``, ``causation_id``, ``payload``, ``idempotency_key``,
  ``created_by``) so causality and idempotency survive a restore.
* ``current_state.jsonl``  — the canonical Tier-0 rows (``entity_ref``,
  ``predicate``, ``object_ref``, ``confidence``, ``authority``, ``state``,
  ``seq``), sorted for determinism.

Restore reloads the ledger *preserving* ``seq`` (so ``causation_id`` foreign
keys and the append-only semantics are intact) and then REPLAYS Tier-0 from
``seq=0`` through the ONE shared pure :class:`CurrentStateReducer` — the exact
same code path as inline append and Tier-1 wipe-and-replay. Restore is verified
when the replayed ``current_state`` checksum equals the backed-up checksum (the
same deterministic digest used for cross-tier equivalence in
:func:`umd.projections.current.tier0_checksum`).

The mutation is ``TRUNCATE semantic_event, current_state`` then re-insert and
replay, all in ONE transaction; nothing ever ``UPDATE``/``DELETE``s ledger rows,
so the append-only guard trigger is preserved (it blocks UPDATE/DELETE, not
the INSERTs performed here).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from umd.storage.postgres.reducer import CurrentStateReducer
from umd.storage.postgres.tables import metadata as db_meta

#: Format name + version of the JSONL snapshot (bumped on a breaking layout change).
_FORMAT = "umd-ledger-snapshot"
_FORMAT_VERSION = 1

_event_t = db_meta.tables["semantic_event"]
_state_t = db_meta.tables["current_state"]

_LEDGER_FILE = "ledger.jsonl"
_STATE_FILE = "current_state.jsonl"
_MANIFEST_FILE = "manifest.json"


class RecoveryError(RuntimeError):
    """Raised when a backup or restore cannot be completed / verified."""


def _serialize_maybe_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:  # pragma: no cover - defensive parse guard
        raise RecoveryError(f"invalid datetime in snapshot: {value!r}") from exc


@dataclass(frozen=True)
class PostgresBackupManifest:
    """Metadata describing one PostgreSQL ledger/Tier-0 backup."""

    format: str
    version: int
    ledger_count: int
    state_count: int
    max_seq: int
    #: sha256 digests of the raw JSONL artifacts (self-integrity on restore).
    ledger_sha256: str
    state_sha256: str
    #: Deterministic Tier-0 ``current_state`` checksum at backup time (the same
    #: digest :func:`umd.projections.current.tier0_checksum` computes).
    current_state_checksum: str


@dataclass(frozen=True)
class RestoreReport:
    """Outcome of a PostgreSQL restore + replay verification."""

    restored_events: int
    replayed_state_rows: int
    max_seq: int
    current_state_checksum: str
    checksum_verified: bool


@dataclass
class _LedgerHeader:
    format: str
    version: int
    ledger_count: int
    max_seq: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(65536):
            h.update(chunk)
    return h.hexdigest()


def ledger_row_to_record(row: sa.Row[Any]) -> dict[str, Any]:
    """Serialize one ``semantic_event`` row to a portable JSON record."""
    return {
        "seq": int(row.seq),
        "event_type": row.event_type,
        "event_version": int(row.event_version),
        "schema_url": row.schema_url,
        "tx_time": _serialize_maybe_datetime(row.tx_time),
        "valid_time": _serialize_maybe_datetime(row.valid_time),
        "authority": row.authority,
        "confidence": row.confidence,
        "generated_by": dict(row.generated_by or {}),
        "correlation_id": str(row.correlation_id) if row.correlation_id is not None else None,
        "causation_id": int(row.causation_id) if row.causation_id is not None else None,
        "payload": dict(row.payload or {}),
        "idempotency_key": str(row.idempotency_key) if row.idempotency_key is not None else None,
        "created_by": row.created_by,
    }


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


def backup_postgres(engine: sa.Engine, dest: Path) -> PostgresBackupManifest:
    """Snapshot the semantic ledger + Tier-0 ``current_state`` to ``dest``.

    Writes ``ledger.jsonl``, ``current_state.jsonl`` and ``manifest.json`` under
    ``dest`` and returns the :class:`PostgresBackupManifest`. The delta is
    read-only against the database.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    with engine.connect() as conn:
        ledger_rows = conn.execute(sa.select(_event_t).order_by(_event_t.c.seq)).fetchall()
        state_rows = conn.execute(
            sa.select(
                _state_t.c.entity_ref,
                _state_t.c.predicate,
                _state_t.c.object_ref,
                _state_t.c.confidence,
                _state_t.c.authority,
                _state_t.c.state,
                _state_t.c.seq,
            ).order_by(_state_t.c.entity_ref, _state_t.c.predicate)
        ).fetchall()

    ledger_path = dest / _LEDGER_FILE
    state_path = dest / _STATE_FILE

    with ledger_path.open("w", encoding="utf-8") as fh:
        for row in ledger_rows:
            fh.write(json.dumps(ledger_row_to_record(row), sort_keys=True) + "\n")
    with state_path.open("w", encoding="utf-8") as fh:
        for r in state_rows:
            fh.write(
                json.dumps(
                    {
                        "entity_ref": r.entity_ref,
                        "predicate": r.predicate,
                        "object_ref": r.object_ref,
                        "confidence": r.confidence,
                        "authority": r.authority,
                        "state": r.state,
                        "seq": int(r.seq),
                    },
                    sort_keys=True,
                )
                + "\n"
            )

    # Canonical Tier-0 checksum (same deterministic digest as cross-tier checks).
    from umd.projections.current import tier0_checksum

    max_seq = int(ledger_rows[-1].seq) if ledger_rows else 0
    manifest = PostgresBackupManifest(
        format=_FORMAT,
        version=_FORMAT_VERSION,
        ledger_count=len(ledger_rows),
        state_count=len(state_rows),
        max_seq=max_seq,
        ledger_sha256=_file_sha256(ledger_path),
        state_sha256=_file_sha256(state_path),
        current_state_checksum=tier0_checksum(engine),
    )
    (dest / _MANIFEST_FILE).write_text(
        json.dumps(
            {
                "format": manifest.format,
                "version": manifest.version,
                "ledger_count": manifest.ledger_count,
                "state_count": manifest.state_count,
                "max_seq": manifest.max_seq,
                "ledger_sha256": manifest.ledger_sha256,
                "state_sha256": manifest.state_sha256,
                "current_state_checksum": manifest.current_state_checksum,
            },
            sort_keys=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest


# ---------------------------------------------------------------------------
# Restore + replay verification
# ---------------------------------------------------------------------------


def _read_records(path: Path, kind: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive
                raise RecoveryError(f"{kind} malformed JSON at line {lineno} of {path}") from exc
    return records


def restore_postgres(engine: sa.Engine, source: Path) -> RestoreReport:
    """Restore the ledger + replay Tier-0 from a :func:`backup_postgres` snapshot.

    In ONE transaction: ``TRUNCATE semantic_event, current_state``, re-insert the
    ledger rows *preserving ``seq``* (and advancing the sequence), then replay
    ``current_state`` from ``seq=0`` through the shared pure reducer and persist
    the canonical rows. Finally the replayed ``current_state`` checksum is
    compared to the backed-up checksum; a mismatch raises :class:`RecoveryError`
    (the restore never silently succeeds with divergent state).
    """
    source = Path(source)
    ledger_path = source / _LEDGER_FILE
    state_path = source / _STATE_FILE
    manifest_path = source / _MANIFEST_FILE
    for required in (ledger_path, state_path, manifest_path):
        if not required.is_file():
            raise RecoveryError(f"missing snapshot artifact: {required}")

    manifest_raw: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest_raw.get("format") != _FORMAT:
        raise RecoveryError(f"unsupported snapshot format: {manifest_raw.get('format')!r}")

    # Self-integrity: the JSONL artifacts must match the recorded digests.
    if _file_sha256(ledger_path) != manifest_raw.get("ledger_sha256"):
        raise RecoveryError(f"ledger snapshot integrity failed: {ledger_path}")
    if _file_sha256(state_path) != manifest_raw.get("state_sha256"):
        raise RecoveryError(f"current_state snapshot integrity failed: {state_path}")

    ledger_records = _read_records(ledger_path, "ledger")
    _ = _read_records(state_path, "current_state")  # integrity: parse-validates every line

    with engine.begin() as conn:
        conn.exec_driver_sql(
            "TRUNCATE TABLE semantic_event, current_state RESTART IDENTITY CASCADE"
        )
        # Re-insert ledger rows preserving seq (append-only INSERT path).
        for rec in ledger_records:
            values: dict[str, Any] = {
                "seq": int(rec["seq"]),
                "event_type": rec["event_type"],
                "event_version": int(rec["event_version"]),
                "schema_url": rec.get("schema_url"),
                "tx_time": _parse_datetime(rec.get("tx_time")),
                "valid_time": _parse_datetime(rec.get("valid_time")),
                "authority": rec.get("authority"),
                "confidence": rec.get("confidence"),
                "generated_by": dict(rec.get("generated_by") or {}),
                "correlation_id": (
                    uuid.UUID(str(rec["correlation_id"])) if rec.get("correlation_id") else None
                ),
                "causation_id": (
                    int(rec["causation_id"]) if rec.get("causation_id") is not None else None
                ),
                "payload": dict(rec.get("payload") or {}),
                "idempotency_key": (
                    uuid.UUID(str(rec["idempotency_key"])) if rec.get("idempotency_key") else None
                ),
                "created_by": rec.get("created_by"),
            }
            conn.execute(_event_t.insert().values(**values))
        if ledger_records:
            max_seq = max(int(r["seq"]) for r in ledger_records)
            conn.execute(
                sa.text("SELECT setval(pg_get_serial_sequence('semantic_event','seq'), :max_seq)"),
                {"max_seq": max_seq},
            )
        events = _load_all_events(conn)
        replayed = CurrentStateReducer().replay(events)
        _persist_replayed_state(conn, replayed)

    from umd.projections.current import tier0_checksum

    checksum = tier0_checksum(engine)
    expected = str(manifest_raw["current_state_checksum"])
    if checksum != expected:
        raise RecoveryError(
            f"replayed current_state does not match backup (got {checksum}, "
            f"expected {expected}); Tier-0 divergence after restore"
        )
    replayed_state_rows = sum(1 for key in replayed.rows if key[1] != "*LOCK*")
    return RestoreReport(
        restored_events=len(ledger_records),
        replayed_state_rows=replayed_state_rows,
        max_seq=manifest_raw.get("max_seq", 0),
        current_state_checksum=checksum,
        checksum_verified=True,
    )


def _load_all_events(conn: sa.Connection) -> list[Any]:
    """Load every ledger row in seq order as a :class:`SemanticEvent` for replay."""
    from umd.domain.events import SemanticEvent, upcast_payload

    rows = conn.execute(
        sa.select(
            _event_t.c.seq,
            _event_t.c.event_type,
            _event_t.c.event_version,
            _event_t.c.payload,
            _event_t.c.authority,
            _event_t.c.confidence,
            _event_t.c.created_by,
        ).order_by(_event_t.c.seq)
    ).fetchall()
    events: list[SemanticEvent] = []
    for r in rows:
        version, payload = upcast_payload(
            r.event_type, int(r.event_version or 1), dict(r.payload or {})
        )
        events.append(
            SemanticEvent(
                event_type=r.event_type,
                payload=payload,
                authority=r.authority,
                confidence=r.confidence,
                created_by=r.created_by,
                seq=int(r.seq),
            )
        )
    return events


def _persist_replayed_state(conn: sa.Connection, state: Any) -> None:
    """Persist the pure-replayed canonical state to the ``current_state`` table."""
    from umd.storage.postgres.reducer import LOCK_PREDICATE, STATE_UNLOCKED

    pg_insert = sa.dialects.postgresql.insert
    for _key, row in state.rows.items():
        if row.predicate == LOCK_PREDICATE and row.state == STATE_UNLOCKED:
            continue  # absence implies unlocked (mirror inline & Tier-1 paths)
        cols = row.scalar()
        stmt = pg_insert(_state_t).values(**cols)
        stmt = stmt.on_conflict_do_update(
            constraint="pk_current_state_tier0",
            set_={
                "object_ref": cols["object_ref"],
                "confidence": cols["confidence"],
                "authority": cols["authority"],
                "state": cols["state"],
                "seq": cols["seq"],
            },
        )
        conn.execute(stmt)


__all__ = [
    "PostgresBackupManifest",
    "RestoreReport",
    "RecoveryError",
    "backup_postgres",
    "restore_postgres",
]
