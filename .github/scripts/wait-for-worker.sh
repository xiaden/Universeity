#!/usr/bin/env sh
# wait-for-worker.sh <compose_file> [service] [timeout_seconds] [interval_seconds]
#
# Wait for the UMD worker to register with Hatchet and print its ready line
# ("worker ready: registered N Hatchet workflows"). This is the P2-S3 readiness
# gate: the job FAILS if the real worker never becomes ready.
#
# Failure detection (honest, not silently hidden):
#   * the worker container exits (state=exited/dead) before ready,
#   * the worker log reports an availability/configuration error
#     ("worker unavailable", "not configured", "refusing to register"),
#   * the bounded timeout elapses.
# In every case the relevant log tail is dumped as evidence before exit 1.
#
# The worker is a GATED subsystem (hatchet_sdk + UMD_HATCHET_SERVER_URL/TOKEN);
# whether it can become ready is driven by the repo state at runtime. This
# helper surfaces the truth rather than faking readiness.
set -eu

compose_file="${1:?usage: wait-for-worker.sh <compose_file> [service] [timeout] [interval]}"
service="${2:-worker}"
timeout="${3:-240}"
interval="${4:-5}"
elapsed=0

state_of() {
  docker compose -f "$compose_file" ps -a --format '{{.Service}} {{.State}}' "$service" 2>/dev/null \
    | awk -v s="$service" '$1 == s { print $2; exit }'
}

while [ "$elapsed" -lt "$timeout" ]; do
  state="$(state_of)"
  logs="$(docker compose -f "$compose_file" logs --no-color "$service" 2>/dev/null || true)"

  if printf '%s\n' "$logs" | grep -q 'worker ready: registered'; then
    echo "[wait-for-worker] $service READY (registered workflows bound with Hatchet)"
    exit 0
  fi

  if printf '%s\n' "$logs" | grep -Eq 'worker unavailable:|not configured|refusing to register'; then
    echo "[wait-for-worker] $service reported an availability/configuration error:" >&2
    printf '%s\n' "$logs" | tail -n 40 >&2
    exit 1
  fi

  if [ "$state" = "exited" ] || [ "$state" = "dead" ]; then
    echo "[wait-for-worker] $service container exited (state=$state) before becoming ready:" >&2
    printf '%s\n' "$logs" | tail -n 60 >&2
    exit 1
  fi

  sleep "$interval"
  elapsed=$((elapsed + interval))
done

echo "[wait-for-worker] TIMEOUT after ${timeout}s: $service never became ready" >&2
docker compose -f "$compose_file" logs --no-color "$service" >&2 2>/dev/null || true
exit 1
