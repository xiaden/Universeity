"""Deployment CLI subcommands (Plan E, P2-S1/S2): ``migrate``, ``worker``.

Invoked by the container entrypoint (``python -m umd.deploy.cli <role>``) and by
operators for the ``migrate`` role. Every command reads its configuration from
environment (never from source), and never fabricates a running subsystem it
cannot actually start.
"""

from __future__ import annotations

import importlib
import os
import sys

from umd.config import get_settings
from umd.deploy.startup import run_migrations


def migrate() -> int:
    """Apply the Alembic chain against the configured Postgres DSN."""
    settings = get_settings()
    run_migrations(settings.postgres.dsn)
    print("migrations applied")
    return 0


def worker() -> int:
    """Start the durable DAG worker (Hatchet), honestly.

    The Hatchet worker is a real subsystem with its own server/pin requirements.
    Starting it requires the optional ``hatchet_sdk`` to be installed AND the
    Hatchet server reachable via ``UMD_HATCHET_SERVER_URL`` / ``UMD_HATCHET_TOKEN``. If
    either is absent this exits non-zero with an actionable message rather than
    silently registering nothing — a worker that reports ready while running zero
    executors would be a lie.
    """
    try:
        sdk = importlib.import_module("hatchet_sdk")
    except ImportError:
        print(
            "worker unavailable: hatchet_sdk not installed (install the opt-in "
            "worker extras; Hatchet is a GATED dependency).",
            file=sys.stderr,
        )
        return 2

    server_url = os.environ.get("UMD_HATCHET_SERVER_URL")
    token = os.environ.get("UMD_HATCHET_TOKEN")
    if not server_url or not token:
        print(
            "worker unavailable: UMD_HATCHET_SERVER_URL / UMD_HATCHET_TOKEN not "
            "configured (refusing to register a worker against an unknown server).",
            file=sys.stderr,
        )
        return 2

    from umd.jobs.hatchet import HatchetRunner

    client = sdk.Hatchet(
        api_url=server_url,
        token=token,
    )
    runner = HatchetRunner(client=client)
    workflows = runner.build_workflows()
    print(f"worker ready: registered {len(workflows)} Hatchet workflows (GATED)")
    client.worker.start()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    role = args[0] if args else "api"
    if role == "migrate":
        return migrate()
    if role == "worker":
        return worker()
    print(f"unknown role: {role}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
