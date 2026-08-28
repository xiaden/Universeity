#!/usr/bin/env sh
# =============================================================================
# validate_hatchet_live.sh — Plan I P4-S1 live Hatchet shape validation (Plan J).
#
# Runs the live scheduler shape suite against the pinned Compose stack on a
# runner with NATIVE Docker/Compose (hosted GitHub Actions). This is the Plan I
# release gate: it MUST fail if the pinned scheduler does not perform real work.
#
# This script is executed by Plan J's hosted workflow, NOT in the local dev
# sandbox (no Docker daemon there). It is validated statically (sh -n) locally.
#
# Requirements:
#   * Docker + docker compose (native engine).
#   * UMD_HATCHET_TOKEN (and optionally UMD_HATCHET_SERVER_URL) exported.
#     HATCHET_COOKIE_SECRET / HATCHET_MASTER_KEY are REQUIRED by compose
#     (${VAR:?}); generate them if not set (never commit secrets).
#
# See the full handoff: artifacts/designs/parts/universal-media-decomposer/
#   HATCHET_LIVE_VALIDATION_HANDOFF.md (pin, worker command, readiness probe,
#   persistent volumes, failure artifacts, and the DEFECT REPORT on the three
#   dedicated test_live_hatchet_* shape tests).
# =============================================================================
set -eu

COMPOSE="${COMPOSE:-deploy/compose.yaml}"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

HATCHET_SERVER_URL="${UMD_HATCHET_SERVER_URL:-http://hatchet:8080}"
HATCHET_TOKEN="${UMD_HATCHET_TOKEN:?UMD_HATCHET_TOKEN must be set}"
: "${HATCHET_COOKIE_SECRET:=$(python3 -c 'import secrets;print(secrets.token_hex(32))')}"
: "${HATCHET_MASTER_KEY:=$(python3 -c 'import secrets;print(secrets.token_hex(32))')}"
export HATCHET_COOKIE_SECRET HATCHET_MASTER_KEY UMD_HATCHET_SERVER_URL="$HATCHET_SERVER_URL" UMD_HATCHET_TOKEN="$HATCHET_TOKEN"

PYTEST=".venv/bin/pytest"
if [ ! -x "$PYTEST" ]; then PYTEST="pytest"; fi

echo "==> [1/6] Start pinned Compose stack (db + hatchet first, then api+worker)"
docker compose -f "$COMPOSE" up -d db hatchet
bash .github/scripts/wait-for-http.sh http://127.0.0.1:8080/v1/health 240 5 || true
docker compose -f "$COMPOSE" up -d --build api worker

echo "==> [2/6] Wait for API readiness and worker/scheduler readiness (gate)"
bash .github/scripts/wait-for-http.sh http://127.0.0.1:8080/v1/ready 240 5
# NOTE: the probe greps 'worker ready: registered' (the exact P2-S3 readiness
# line emitted by cli.py before the blocking worker.start()).
bash .github/scripts/wait-for-worker.sh "$COMPOSE" worker 240 5

echo "==> [3/6] Run the live shape suite against the stack"
UMD_TEST_POSTGRES=true UMD_HATCHET_SERVER_URL="$HATCHET_SERVER_URL" UMD_HATCHET_TOKEN="$HATCHET_TOKEN" \
  "$PYTEST" tests/test_hatchet_live.py -m "cluster or docker" -q \
  --junitxml=hatchet-live-junit.xml 2>&1 | tee hatchet-live.log

echo "==> [4/6] Restart api+worker (persistent volumes must survive); re-verify"
docker compose -f "$COMPOSE" stop api worker
docker compose -f "$COMPOSE" start api worker
bash .github/scripts/wait-for-http.sh http://127.0.0.1:8080/v1/ready 240 5
bash .github/scripts/wait-for-worker.sh "$COMPOSE" worker 240 5

echo "==> [5/6] Re-run the duplicate/restart shape test after restart (no repeated committed stages)"
UMD_TEST_POSTGRES=true UMD_HATCHET_SERVER_URL="$HATCHET_SERVER_URL" UMD_HATCHET_TOKEN="$HATCHET_TOKEN" \
  "$PYTEST" tests/test_hatchet_live.py \
  -m "cluster" -k "duplicate_and_restart" -q 2>&1 | tee hatchet-live-after-restart.log

echo "==> [6/6] Success — pinned scheduler performed real work against the live stack"
