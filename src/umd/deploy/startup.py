"""Deployment startup helpers: Alembic migration execution + readiness probe.

Plan E (P2-S2) makes migrations a first-class startup concern. Two seams:

* :func:`run_migrations` applies the Alembic chain to the configured Postgres
  DSN (the same programmatic call the tests and the container entrypoint use). It
  is idempotent (``upgrade head`` is a no-op at the current head) and only ever
  moves the schema forward.
* :func:`readiness_probe` performs the startup ordering check the DD asks for:
  Postgres reachable, structural migrations at head, and the OCFL root present
  and valid (supports fixity) — the dependencies ``/health`` and ``/ready``
  surface. It reports an honest, componentwise ``ok``/``degraded`` state and
  never claims a dependency is ready that a probe did not verify.

Secrets are never embedded: the DSN is read from configuration/environment at
process start, not from source.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from alembic.util.exc import CommandError

from umd.storage.ocfl.store import SourceStore
from umd.storage.postgres.tables import metadata as db_meta

_state_t = db_meta.tables["current_state"]


class StartupError(RuntimeError):
    """Raised when a startup migration/probe cannot be satisfied."""


def default_alembic_ini() -> Path:
    """Repo-relative ``alembic.ini`` (override with ``UMD_ALEMBIC_INI``)."""
    env = os.environ.get("UMD_ALEMBIC_INI")
    return Path(env) if env else Path(__file__).resolve().parents[2] / "alembic.ini"


def run_migrations(dsn: str, alembic_ini: str | Path | None = None) -> str:
    """Apply the full Alembic migration chain to ``dsn``; return the resulting head.

    Mirrors the migration bootstrap used across the test suite; safe to call on
    every container start (``upgrade head`` is idempotent at the current head and
    only ever moves forward). ``alembic_ini`` defaults to ``UMD_ALEMBIC_INI`` or
    the repo root ``alembic.ini``.
    """
    ini = Path(alembic_ini) if alembic_ini is not None else default_alembic_ini()
    if not ini.is_file():
        raise StartupError(f"alembic.ini not found: {ini}")
    cfg = AlembicConfig(str(ini))
    cfg.set_main_option("sqlalchemy.url", dsn)
    # ``migrations/env.py`` resolves the URL from ``UMD_POSTGRES__DSN`` (or
    # settings) at migrate time, so pin the env var to the requested ``dsn`` for
    # the duration of the migration (same approach the test bootstrap uses) and
    # restore the previous value afterwards.
    _prev = os.environ.get("UMD_POSTGRES__DSN")
    os.environ["UMD_POSTGRES__DSN"] = dsn
    try:
        alembic_command.upgrade(cfg, "head")
    except CommandError as exc:
        raise StartupError(f"alembic upgrade failed: {exc}") from exc
    finally:
        if _prev is None:
            os.environ.pop("UMD_POSTGRES__DSN", None)
        else:
            os.environ["UMD_POSTGRES__DSN"] = _prev
    return _current_head(dsn)


def _current_head(dsn: str) -> str:
    """The schema-version head row(s) currently recorded in ``alembic_version``."""
    with sa.create_engine(dsn, poolclass=sa.pool.NullPool).connect() as conn:
        try:
            rows = conn.execute(sa.text("SELECT version_num FROM alembic_version")).fetchall()
        except sa.exc.DBAPIError:
            return "(no alembic_version table)"
        return ",".join(sorted(str(r[0]) for r in rows))


@dataclass(frozen=True)
class ProbeComponent:
    """One readiness component: ``ok``/``degraded`` + human detail."""

    name: str
    status: str  # "ok" | "degraded"
    detail: str

    def to_meta(self) -> dict[str, str]:
        return {"status": self.status, "detail": self.detail}


def readiness_probe(
    *,
    dsn: str,
    ocfl_root: str | Path,
    alembic_ini: str | Path | None = None,
) -> list[ProbeComponent]:
    """Componentwise startup ordering check (Postgres -> migrations -> OCFL).

    Runs the minimum real checks a container entrypoint performs before declaring
    ready: (1) Postgres reachable and responsive, (2) the Alembic chain is applied
    (a drift / unapplied-migration database reports ``degraded``), and (3) the
    OCFL root exists and can list inventory objects (fixity-supporting). Each
    component reports its own honest status; nothing is implied ready that was
    not probed.
    """
    components: list[ProbeComponent] = []

    # -- 1) Postgres reachability ------------------------------------------
    try:
        with sa.create_engine(dsn, poolclass=sa.pool.NullPool).connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        db_status = "ok"
        db_detail = "Postgres reachable"
    except sa.exc.DBAPIError as exc:
        db_status = "degraded"
        db_detail = f"Postgres unreachable: {exc}"
    components.append(ProbeComponent("postgres", db_status, db_detail))

    if db_status != "ok":
        return components  # don't probe migrations against an unreachable DB

    # -- 2) migrations at head ---------------------------------------------
    try:
        ok, migrations_detail = _migrations_at_head(dsn, alembic_ini)
        migrations_status = "ok" if ok else "degraded"
    except (StartupError, OSError) as exc:
        migrations_status = "degraded"
        migrations_detail = f"migrations not at head: {exc}"
    components.append(ProbeComponent("migrations", migrations_status, migrations_detail))

    # -- 3) OCFL root present / readable -----------------------------------
    root = Path(ocfl_root)
    try:
        if not (root / "0=ocfl_1.1").exists():
            raise StartupError("no OCFL namaste declaration in root")
        store = SourceStore(root=root)
        objects = [
            p
            for p in root.rglob("inventory.json")
            if not (p.parent.name.startswith("v") and p.parent.name[1:].isdigit())
        ]
        ocfl_status = "ok"
        ocfl_detail = f"OCFL root valid; {len(objects)} object(s)"
        del store
    except Exception as exc:  # noqa: BLE001 - component probe reports broadly
        ocfl_status = "degraded"
        ocfl_detail = f"OCFL root problem: {exc}"
    components.append(ProbeComponent("ocfl", ocfl_status, ocfl_detail))

    return components


def _migrations_at_head(dsn: str, alembic_ini: str | Path | None) -> tuple[bool, str]:
    """Whether the database records exactly the Alembic script heads.

    Compares the ``alembic_version`` row(s) against the script directory's heads
    (``ScriptDirectory.get_heads``). This answers "are migrations applied?" — it
    deliberately does NOT autogenerate-diff the model metadata, which would flag
    pre-existing model drift unrelated to migration application.
    """
    from alembic.script import ScriptDirectory

    ini = Path(alembic_ini) if alembic_ini is not None else default_alembic_ini()
    if not ini.is_file():
        raise StartupError(f"alembic.ini not found: {ini}")
    cfg = AlembicConfig(str(ini))
    cfg.set_main_option("sqlalchemy.url", dsn)
    script = ScriptDirectory.from_config(cfg)
    script_heads = set(script.get_heads())

    _prev = os.environ.get("UMD_POSTGRES__DSN")
    os.environ["UMD_POSTGRES__DSN"] = dsn
    try:
        recorded = _current_head(dsn)
    finally:
        if _prev is None:
            os.environ.pop("UMD_POSTGRES__DSN", None)
        else:
            os.environ["UMD_POSTGRES__DSN"] = _prev

    if recorded == "(no alembic_version table)":
        return False, "no alembic_version table (migrations not applied)"
    recorded_heads = set(p for p in recorded.split(",") if p.strip())
    if recorded_heads == script_heads:
        return True, f"migrations at head ({recorded})"
    missing = script_heads - recorded_heads
    return False, f"recorded {recorded}; missing heads {sorted(missing)}"


def all_ready(components: list[ProbeComponent]) -> bool:
    """True when every probe component reports ``ok`` (the ``/ready`` gate)."""
    return all(c.status == "ok" for c in components)


__all__ = [
    "ProbeComponent",
    "StartupError",
    "run_migrations",
    "readiness_probe",
    "all_ready",
]
