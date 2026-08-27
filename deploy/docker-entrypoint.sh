#!/usr/bin/env sh
# UMD container entrypoint (Plan E, P2-S2 migration-startup ordering).
#
# 1. If UMD_RUN_MIGRATIONS_ON_START=1 (recommended for dev/CI; in production a
#    dedicated migration job runs this) apply the Alembic chain to the DSN in
#    UMD_POSTGRES__DSN. Idempotent: `upgrade head` is a no-op already-head.
#    Migration runs under the runtime DSN/credentials from environment — never
#    baked into the image.
# 2. Then exec the role command (api | worker | migrate) so signals reach the
#    real process (no lean-on-shell zombie).
set -eu

role="${1:-api}"
umd_migrations="${UMD_RUN_MIGRATIONS_ON_START:-0}"

if [ "$role" = "migrate" ] || [ "$umd_migrations" = "1" ]; then
  # Mask to the first '@' to honor docs/observability.md ("logs never embed
  # secrets"). A standard DSN `postgresql+psycopg://umd:PASS@db:5432/umd` carries
  # the password between the first '//' and the first '@'; removing the shortest
  # prefix up to and including the FIRST '@' leaves only host/port/db, never the
  # credential.
  _masked_dsn="${UMD_POSTGRES__DSN#*@}"
  echo "[umd] applying migrations to ${_masked_dsn}..."
  python -m umd.deploy.cli migrate
fi

case "$role" in
  api)
    exec python -m uvicorn umd.api.entrypoints:app_factory --factory \
      --host "${UMD_API_HOST:-0.0.0.0}" --port "${UMD_API_PORT:-8080}"
    ;;
  worker)
    exec python -m umd.deploy.cli worker
    ;;
  migrate)
    echo "[umd] migrations complete"
    ;;
  *)
    echo "[umd] unknown role: $role" >&2
    exit 2
    ;;
esac