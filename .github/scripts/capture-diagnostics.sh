#!/usr/bin/env sh
# capture-diagnostics.sh <compose_file> <out_dir>
#
# Dump `docker compose ps`, per-service logs, and live endpoint probes into
# <out_dir> for artifact upload (P2-S5). Runs under `if: always()` in the
# workflow so failure evidence is captured even when a prior step failed.
# Every command is guarded so this helper itself never fails the job.
set -eu

compose_file="${1:?usage: capture-diagnostics.sh <compose_file> <out_dir>}"
out_dir="${2:?usage: capture-diagnostics.sh <compose_file> <out_dir>}"
mkdir -p "$out_dir"

docker compose -f "$compose_file" ps -a > "$out_dir/compose-ps.txt" 2>&1 || true
docker compose -f "$compose_file" ps --volumes > "$out_dir/compose-volumes.txt" 2>&1 || true

for svc in db api worker hatchet sandbox-runner ollama minio; do
  docker compose -f "$compose_file" logs --no-color "$svc" > "$out_dir/log-$svc.txt" 2>&1 || true
done

probe() {
  name="$1"
  url="$2"
  if curl -fsS -m 10 "$url" > "$out_dir/$name.json" 2>&1; then
    :
  else
    echo "endpoint not ready: $url" > "$out_dir/$name.json"
  fi
}

probe health   http://127.0.0.1:8080/v1/health
probe ready    http://127.0.0.1:8080/v1/ready
probe version  http://127.0.0.1:8080/v1/version
probe capabilities http://127.0.0.1:8080/v1/capabilities

echo "[capture-diagnostics] wrote diagnostics to $out_dir"
