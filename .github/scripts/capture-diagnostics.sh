#!/usr/bin/env sh
# capture-diagnostics.sh <compose_file> <out_dir>
#
# P3-S5 fail-safe-but-non-masking diagnostics: dump `docker compose ps`, per-service
# logs, live endpoint probes, a DB logical dump, OCFL listing/fixity, image digests,
# and the live-worker-gate verdict into <out_dir> for artifact upload. Runs under
# `if: always()` in the workflow so failure evidence is captured even when a prior
# step failed. Every command is guarded so this helper itself never fails the job
# (diagnostics must not mask the real result).
set -eu

compose_file="${1:?usage: capture-diagnostics.sh <compose_file> <out_dir>}"
out_dir="${2:?usage: capture-diagnostics.sh <compose_file> <out_dir>}"
mkdir -p "$out_dir"

docker compose -f "$compose_file" ps -a > "$out_dir/compose-ps.txt" 2>&1 || true
docker compose -f "$compose_file" ps --volumes > "$out_dir/compose-volumes.txt" 2>&1 || true

# P3-S3/P3-S5: the split Hatchet topology (no single `hatchet` service anymore)
# plus the UMD services and the optional sandbox profile.
for svc in db api worker hatchet-migrate hatchet-admin hatchet-engine hatchet-dashboard sandbox-runner ollama minio; do
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

port="${UMD_API_PORT:-8080}"
probe health   "http://127.0.0.1:${port}/v1/health"
probe ready    "http://127.0.0.1:${port}/v1/ready"
probe version  "http://127.0.0.1:${port}/v1/version"
probe capabilities "http://127.0.0.1:${port}/v1/capabilities"

# P3-S5: logical Postgres dump captures stage_run / job_run_audit / semantic_event
# state (the durable completion evidence) before teardown.
if docker compose -f "$compose_file" ps -q db >/dev/null 2>&1; then
  docker compose -f "$compose_file" exec -T db pg_dump -U umd -d umd > "$out_dir/umd-dump.sql" 2>"$out_dir/pg_dump.err" || true
fi

# P3-S5: OCFL listing + namaste fixity marker on the named volume.
if docker compose -f "$compose_file" ps -q api >/dev/null 2>&1; then
  docker compose -f "$compose_file" exec -T api sh -c \
    'find /data/ocfl -maxdepth 2 2>/dev/null | head -200; echo "namaste:"; cat /data/ocfl/0=ocfl_1.1 2>/dev/null || echo "NO NAMASTE"' \
    > "$out_dir/ocfl-listing.txt" 2>&1 || true
fi

# P3-S5: image digests from the preflight (P3-S4) + per-image inspect.
if [ -f image-digests.txt ]; then
  cp image-digests.txt "$out_dir/image-digests.txt" 2>/dev/null || true
fi
docker compose -f "$compose_file" config --images 2>/dev/null | sort -u | while read -r name; do
  [ -z "$name" ] && continue
  {
    printf '%s ' "$name"
    docker image inspect --format '{{if index .RepoDigests 0}}{{index .RepoDigests 0}}{{else}}<no repo digest> (local build: {{.Id}}){{end}}' "$name" 2>/dev/null || echo "unavailable"
  } >> "$out_dir/image-digests.txt" || true
done

# P3-S5: the live-worker-gate verdict (PASS/FAIL), preserved even on failure.
if [ -f live-worker-gate.txt ]; then
  echo "live-worker-gate: $(cat live-worker-gate.txt 2>/dev/null || echo FAIL)" > "$out_dir/live-worker-gate.txt"
else
  echo "live-worker-gate: FAIL (no verdict recorded)" > "$out_dir/live-worker-gate.txt"
fi

# P3-S2/P3-S3: bundle the hosted tenant-selection identity + engine-visible
# machine-readable verdicts and the optional A3' declaration probe into the bundle
# (captured BEFORE teardown so the evidence survives). The per-check diag files
# (v1-task-summary, engine-visible-durability, callback-owned-rows,
# identity-agreement, engine-visible-schema, v1-task-transition-history) are already
# written into $out_dir by engine-visible-proof.sh's diag_dir argument.
for f in tenant-identity.txt engine-visible-proof.txt engine-verdicts.txt a3-declaration-probe.txt; do
  if [ -f "$f" ]; then
    cp "$f" "$out_dir/" 2>/dev/null || true
  fi
done

# P3-S5: JUnit / coverage artifacts produced by earlier test steps, if present.
for f in live-junit.xml live-tests.log boundary-junit.xml boundary-tests.log \
         boundary-after-restart-junit.xml boundary-after-restart.log \
         unit-junit.xml unit-coverage.xml unit-tests.log \
         postgres-junit.xml postgres-coverage.xml postgres-tests.log; do
  if [ -f "$f" ]; then
    cp "$f" "$out_dir/" 2>/dev/null || true
  fi
done

echo "[capture-diagnostics] wrote diagnostics to $out_dir"
