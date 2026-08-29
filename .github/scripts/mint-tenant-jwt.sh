#!/usr/bin/env sh
# mint-tenant-jwt.sh <compose_file>
#
# P3-S2 hosted tenant setup + JWT minting with partition-eligible selection and
# identity agreement. Replaces the historical inline "mint real tenant JWT" step:
#   * starts config generation (db + hatchet-migrate + hatchet-admin) and waits
#     for hatchet-admin quickstart to populate the shared /hatchet/config,
#   * discovers the mixed-case goose "Tenant" table case-insensitively,
#   * selects EXACTLY ONE non-deleted runnable tenant with non-null
#     "schedulerPartitionId" AND "workerPartitionId"; fails closed on zero /
#     multiple / deleted / null-partition candidates BEFORE any JWT is minted
#     (never the null-partition internal tenant),
#   * mints a REAL tenant JWT for the eligible tenant only, decodes its tenant
#     claim and asserts it equals the selected tenant id,
#   * records the identity agreement into tenant-identity.txt (the worker /
#     workflow / submitted-task tenant fields are completed by
#     engine-visible-proof.sh, which asserts they all agree),
#   * exports HATCHET_TENANT_TOKEN / UMD_HATCHET_TOKEN to $GITHUB_ENV.
#
# Guards preserved: bounded 30x2s poll, visible psql stderr (no 2>/dev/null on
# discovery/query), no SET search_path (schema-qualified quoted query), no
# hardcoded UUID, fail-closed exit 1 with a clear message.
# Maintenance facts: schema = public / table = "Tenant" / id = lowercase unquoted /
# partition cols = quoted camelCase "schedulerPartitionId" "workerPartitionId" /
# "deletedAt".
set -eu

compose_file="${1:?usage: mint-tenant-jwt.sh <compose_file>}"

# --- config generation (db + migrate + admin) and /hatchet/config poll ----
docker compose -f "$compose_file" up -d db hatchet-migrate hatchet-admin
ok=""
for i in $(seq 1 60); do
  if docker compose -f "$compose_file" run --rm --no-deps hatchet-admin \
      sh -c 'test -n "$(ls -A /hatchet/config 2>/dev/null)"' 2>/dev/null; then
    ok=1
    break
  fi
  sleep 5
done
if [ -z "$ok" ]; then
  echo "hatchet-admin did not generate /hatchet/config within timeout" >&2
  exit 1
fi

# --- partition-eligible tenant selection (bounded 30x2s poll, fail-closed) ----
# goose creates MIXED-CASE quoted tables in the public schema (CREATE TABLE
# public."Tenant") with a lowercase unquoted `id` and quoted camelCase partition
# columns. We discover schema+table case-insensitively, then read EVERY tenant
# row through the discovered schema + EXACT-CASED quoted table and select exactly
# ONE non-deleted tenant with non-null "schedulerPartitionId" AND
# "workerPartitionId". psql stderr is intentionally NOT silenced (no 2>/dev/null).
S=""
T=""
selected_id=""
selected_sched=""
selected_worker=""
for i in $(seq 1 30); do
  TS="$(docker compose -f "$compose_file" exec -T db psql -U umd -d umd -tAc \
    "SELECT table_schema, table_name FROM information_schema.tables WHERE lower(table_name) = 'tenant' ORDER BY 1 LIMIT 1" | tr -d '[:space:]')"
  if [ -n "$TS" ]; then
    S="${TS%%|*}"
    T="${TS#*|}"
    # Every tenant row: id, both partition ids, deletedAt (all quoted/exact-case).
    ROWS="$(docker compose -f "$compose_file" exec -T db psql -U umd -d umd -tAc \
      "SELECT id::text, \"schedulerPartitionId\"::text, \"workerPartitionId\"::text, \"deletedAt\"::text FROM \"$S\".\"$T\"")"
    total=0
    eligible_count=0
    cur_id=""
    cur_sched=""
    cur_worker=""
    while IFS='|' read -r id sched worker deleted; do
      id="$(printf '%s' "$id" | tr -d '[:space:]')"
      sched="$(printf '%s' "$sched" | tr -d '[:space:]')"
      worker="$(printf '%s' "$worker" | tr -d '[:space:]')"
      deleted="$(printf '%s' "$deleted" | tr -d '[:space:]')"
      [ -z "$id" ] && continue
      total=$((total + 1))
      # deleted tenant (deletedAt non-null) => ineligible
      [ -n "$deleted" ] && continue
      # null partition => ineligible (the internal-tenant shape, never selected)
      [ -z "$sched" ] && continue
      [ -z "$worker" ] && continue
      eligible_count=$((eligible_count + 1))
      cur_id="$id"
      cur_sched="$sched"
      cur_worker="$worker"
    done <<EOF
$ROWS
EOF
    if [ "$eligible_count" -gt 1 ]; then
      echo "multiple scheduler-eligible Hatchet tenants found ($eligible_count); refusing to mint a JWT (ambiguous)" >&2
      exit 1
    fi
    if [ "$eligible_count" -eq 1 ]; then
      selected_id="$cur_id"
      selected_sched="$cur_sched"
      selected_worker="$cur_worker"
      break
    fi
    # eligible_count == 0: keep polling (the eligible tenant may still be
    # bootstrapping); a bounded 30x2s timeout below fails closed.
  fi
  sleep 2
done
if [ -z "$selected_id" ]; then
  echo "could not select exactly one non-deleted scheduler-eligible Hatchet tenant (non-null schedulerPartitionId AND workerPartitionId) after polling; refusing to mint a JWT for a null-partition tenant" >&2
  exit 1
fi

# --- mint a REAL tenant JWT bound to the eligible tenant only ----
TOKEN="$(docker compose -f "$compose_file" run --rm --no-deps hatchet-admin \
  /hatchet/hatchet-admin token create --config /hatchet/config --tenant-id "$selected_id")"
if [ -z "$TOKEN" ]; then
  echo "token minting produced no JWT" >&2
  exit 1
fi

# --- decode the JWT tenant claim and assert it equals the selected tenant ----
jwt_tenant="$(python3 - "$TOKEN" <<'PY'
import base64, json, sys
tok = sys.argv[1]
payload = tok.split('.')[1]
payload += '=' * (-len(payload) % 4)
claims = json.loads(base64.urlsafe_b64decode(payload))
print(claims.get('tenant_id') or claims.get('sub') or '')
PY
)"
jwt_tenant="$(printf '%s' "$jwt_tenant" | tr -d '[:space:]')"
if [ -z "$jwt_tenant" ]; then
  echo "could not decode a tenant claim from the minted JWT; cannot assert identity agreement" >&2
  exit 1
fi
if [ "$jwt_tenant" != "$selected_id" ]; then
  echo "JWT tenant claim ($jwt_tenant) does not equal selected tenant ($selected_id); refusing to proceed" >&2
  exit 1
fi

# --- record the identity agreement (worker/workflow/submitted-task are completed
#     by engine-visible-proof.sh, which asserts they all equal tenant_id) ---
{
  echo "# UMD hosted tenant identity agreement (mint-tenant-jwt.sh)"
  echo "schema: $S"
  echo "table: $T"
  echo "tenant_id: $selected_id"
  echo "scheduler_partition_id: $selected_sched"
  echo "worker_partition_id: $selected_worker"
  echo "jwt_tenant: $jwt_tenant"
  echo "worker_tenant: PENDING"
  echo "workflow_tenant: PENDING"
  echo "submitted_task_tenant: PENDING"
} > tenant-identity.txt

# --- export the token to subsequent steps ----
echo "HATCHET_TENANT_TOKEN=$TOKEN" >> "$GITHUB_ENV"
echo "UMD_HATCHET_TOKEN=$TOKEN" >> "$GITHUB_ENV"
echo "[mint-tenant-jwt] selected eligible tenant $selected_id (sched=$selected_sched worker=$selected_worker); JWT tenant claim $jwt_tenant; identity recorded to tenant-identity.txt"
