#!/usr/bin/env sh
# wait-for-http.sh <url> [timeout_seconds] [interval_seconds]
#
# Poll <url> until it returns HTTP 200 (curl --fail) or the timeout elapses.
# Used to gate the API readiness endpoints (/v1/health, /v1/ready) after the
# Compose stack is up and after an API/worker restart.
#
# Exit 0 on success; exit 1 with a diagnostic on timeout. This is a hosted-
# runner helper; it is validated statically (sh -n) here and proven at runtime
# by GitHub Actions.
set -eu

url="${1:?usage: wait-for-http.sh <url> [timeout_seconds] [interval_seconds]}"
timeout="${2:-180}"
interval="${3:-5}"
elapsed=0

while [ "$elapsed" -lt "$timeout" ]; do
  if curl -fsS --max-time 15 "$url" >/dev/null 2>&1; then
    echo "[wait-for-http] ready: $url"
    exit 0
  fi
  sleep "$interval"
  elapsed=$((elapsed + interval))
done

echo "[wait-for-http] TIMEOUT after ${timeout}s: $url never returned HTTP 200" >&2
exit 1
