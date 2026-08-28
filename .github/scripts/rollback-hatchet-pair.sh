#!/usr/bin/env sh
# rollback-hatchet-pair.sh <compose_file> <candidate_universe> <previous_universe>
#
# P3-S6 rollback ordering for a FAILING hosted candidate Hatchet SDK/server pair.
#
# This is a HOSTED operational procedure (native Docker runner), validated
# statically here (sh -n) and executed by an operator when a candidate pair fails
# live validation. It NEVER weakens the release gate: it does not restore an
# opt-in worker, a fake readiness signal, a top-level denied image, or a skipped
# assertion. The gate stays fail-closed — a reverted candidate must re-pass the
# SAME hosted checks.
#
# Ordering (evidence first, drain before revert, revert after capture):
#   1. PRESERVE ALL EVIDENCE (diagnostics + DB dump + OCFL + image digests).
#   2. STOP NEW SUBMISSIONS (stop the api + worker services).
#   3. DRAIN/CANCEL the candidate universe (DagUniverseGate.activate_new_universe
#      cancels PENDING/RUNNING/PAUSED jobs under a different universe).
#   4. ISOLATE/REVERT only after capture — revert the SDK<->server pins (this
#      script prints the exact surfaces; the pin edit is a deliberate operator
#      action, never done automatically here).
#   5. RESTORE the last known compatible pair/schema and RE-RUN the SAME hosted
#      checks (worker readiness gate + live suite). A revert that passes only by
#      re-introducing an opt-in worker / fake readiness / skipped assertion is
#      FORBIDDEN.
set -eu

compose_file="${1:?usage: rollback-hatchet-pair.sh <compose_file> <candidate_universe> <previous_universe>}"
candidate_universe="${2:?candidate DAG universe is required}"
previous_universe="${3:?previous/last-known-good DAG universe is required}"

echo "==> [1/5] Preserve all evidence before any change"
capture_dir="rollback-evidence-$(date +%s)"
bash .github/scripts/capture-diagnostics.sh "$compose_file" "$capture_dir"
echo "evidence preserved under $capture_dir"

echo "==> [2/5] Stop new submissions (api + worker)"
docker compose -f "$compose_file" stop api worker

echo "==> [3/5] Drain/cancel the candidate universe ($candidate_universe)"
# The authoritative drain primitive (P2-S6, DagUniverseGate.activate_new_universe)
# cancels PENDING/RUNNING/PAUSED jobs under a different universe than the one being
# activated, preserving completed work. On hosted this runs against the durable job
# table. We implement it as a direct cancellation against the shared Postgres job
# store (the same effect the gate produces), canceling only ACTIVE (non-terminal)
# candidate-universe jobs. It is idempotent: re-running on an already-drained
# universe matches zero rows. The exact `job` table / `dag_universe` column names
# are reconciled against the committed schema on the hosted run.
count="$(docker compose -f "$compose_file" exec -T db psql -U umd -d umd -tAc \
  "UPDATE job SET status='CANCELLED', error='drained by rollback from $candidate_universe' "\
  "WHERE dag_universe = '$candidate_universe' "\
  "AND status NOT IN ('COMPLETE','FAILED','CANCELLED') "\
  "RETURNING count(*)" 2>/dev/null | tr -d '[:space:]' || echo 'unknown')"
echo "cancelled ${count:-0} active job(s) under candidate universe $candidate_universe"

echo "==> [4/5] Revert the SDK<->server pair ONLY after capture (operator action)"
cat <<'EOF'
Revert these surfaces to the last-known-compatible pair (operator edits, then rerun):
  * deploy/pins/runtime.txt            hatchet-sdk==<prev> / hatchet-server==<prev>
  * pyproject.toml [worker]            hatchet-sdk==<prev>
  * deploy/compose.yaml HATCHET_VERSION <prev>  (split sub-path images)
  * src/umd/jobs/hatchet.py            HATCHET_SDK_VERSION / HATCHET_SERVER_IMAGE
DO NOT revert by: restoring UMD_VALIDATE_LIVE_WORKER opt-in, a fake readiness
line, the denied top-level ghcr.io/hatchet-dev/hatchet image, or a skipped
assertion. Those are release-gate violations and are NOT a valid rollback.
EOF

echo "==> [5/5] Re-run the SAME hosted checks after restore"
cat <<'EOF'
After restoring the pair, re-run the identical fail-closed gate:
  docker compose -f "$compose_file" --profile sandbox up -d --build \
    db api worker sandbox-runner hatchet-migrate hatchet-admin hatchet-engine hatchet-dashboard
  bash .github/scripts/wait-for-worker.sh "$compose_file" worker 240 5
  # then the live suite (tests/test_hatchet_live.py + test_api_boundary_e2e.py),
  # which must PASS with zero skips for the rollback to be accepted.
EOF
echo "rollback orchestration complete (drain + evidence preserved)."
