#!/usr/bin/env sh
# engine-visible-proof.sh <compose_file> <diag_dir>
#
# P3-S3 engine-visible, assignment/runtime, and callback-owned diagnostics for the
# hosted live-worker release gate. Runs AFTER the live suite + boundary E2E
# submissions and queries the shared `umd` Postgres directly (docker compose exec
# -T db psql -U umd -d umd). A readiness line / declaration probe / accepted
# submission / local registration object alone is NEVER release proof; this gate
# requires real engine rows and FAILS CLOSED on:
#   1. v1_task rows never leaving QUEUED (zero assignments) — the exact hosted
#      failure mode of run 33229130339,
#   2. latest-version v1_task.is_durable != true for every canonical umd-<stage>,
#   3. missing worker / assignment / runtime rows,
#   4. missing real callback-owned rows (stage_run, semantic_event
#      event_type='StageCompleted', job_run_audit operational audit),
#   5. missing required tables/columns (never silently degrades to "release proof
#      not required"),
#   6. identity disagreement (JWT == worker == workflow == submitted-task tenant).
# All captured rows are written into <diag_dir> BEFORE teardown and the verdict is
# recorded to engine-visible-proof.txt (PASS/FAIL) for the aggregate gate.
#
# Schema (v0.105.2): Hatchet v1 tables are lowercase unquoted (v1_task,
# v1_task_runtime, v1_tasks_olap); worker/workflow are legacy quoted mixed-case
# public."Worker" / public."Workflow" / public."WorkflowVersion". Status is NOT on
# v1_task: the readable status lives on v1_tasks_olap.readable_status and the live
# assignment is v1_task_runtime.worker_id IS NOT NULL. "umd-<stage>" workflow names
# live on public."Workflow"."name". UMD callback-owned tables: stage_run,
# semantic_event, job_run_audit.
set -eu

compose_file="${1:?usage: engine-visible-proof.sh <compose_file> <diag_dir>}"
diag_dir="${2:?usage: engine-visible-proof.sh <compose_file> <diag_dir>}"
mkdir -p "$diag_dir"

psql() {
  docker compose -f "$compose_file" exec -T db psql -U umd -d umd "$@"
}

fail() {
  echo "engine-visible-proof: FAIL: $*" >&2
  echo "FAIL" > engine-visible-proof.txt
  exit 1
}

# tenant selected by mint-tenant-jwt.sh (single source of truth for agreement)
identity_file="tenant-identity.txt"
if [ ! -f "$identity_file" ]; then
  fail "tenant-identity.txt missing (mint-tenant-jwt.sh must run first)"
fi
selected_tenant="$(sed -n 's/^tenant_id: //p' "$identity_file" | tr -d '[:space:]')"
if [ -z "$selected_tenant" ]; then
  fail "tenant-identity.txt has no tenant_id"
fi

# canonical stages -> workflow names umd-<stage.lower()>
UMD_STAGES="ingest format_analysis basic_segmentation low_level_extraction structural_analysis entity_resolution cross_source_alignment semantic_reconciliation current_search_projection"

# --- required tables; discover + require each (fail closed if missing) ----
require_table() {
  want="$1"
  found="$(psql -tAc "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND lower(table_name) = lower('$want') ORDER BY 1 LIMIT 1" | tr -d '[:space:]')"
  if [ -z "$found" ]; then
    fail "required table public.\"$want\" not found in the umd database (v0.105.2 schema regression?)"
  fi
  printf '%s' "$found"
}

V1_TASK="$(require_table v1_task)"
V1_TASK_RUNTIME="$(require_table v1_task_runtime)"
V1_TASKS_OLAP="$(require_table v1_tasks_olap)"
WORKER="$(require_table Worker)"
WORKFLOW="$(require_table Workflow)"
WORKFLOW_VERSION="$(require_table WorkflowVersion)"
STAGE_RUN="$(require_table stage_run)"
SEMANTIC_EVENT="$(require_table semantic_event)"
JOB_RUN_AUDIT="$(require_table job_run_audit)"

# --- required columns (fail closed naming any missing) ---
require_column() {
  tbl="$1"
  col="$2"
  c="$(psql -tAc "SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name = lower('$tbl') AND lower(column_name) = lower('$col') LIMIT 1" | tr -d '[:space:]')"
  if [ "$c" != "1" ]; then
    fail "required column \"$col\" missing on table public.\"$tbl\""
  fi
}
require_column v1_task tenant_id
require_column v1_task is_durable
require_column v1_task workflow_version_id
require_column v1_task_runtime worker_id
require_column v1_task_runtime tenant_id
require_column v1_tasks_olap readable_status
require_column v1_tasks_olap latest_worker_id
require_column v1_tasks_olap tenant_id
require_column Worker tenantId
require_column Workflow name
require_column Workflow tenantId
require_column WorkflowVersion workflowId
require_column semantic_event event_type
require_column job_run_audit id

# --- capture the discovered schema for the evidence bundle ---
{
  echo "discovered tables (schema public):"
  psql -tAc "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND (lower(table_name) IN ('v1_task','v1_task_runtime','v1_tasks_olap') OR lower(table_name) IN ('worker','workflow','workflowversion','stage_run','semantic_event','job_run_audit')) ORDER BY 1"
} > "$diag_dir/engine-visible-schema.txt"

# ============================================================================
# Check 1: v1_task QUEUED -> ASSIGNED/RUNNING (bounded 30x2s poll, fail closed)
#   Assignment evidence = v1_task_runtime.worker_id IS NOT NULL; active evidence
#   = v1_tasks_olap.readable_status IN ('RUNNING','COMPLETED'). ASSIGNED is not a
#   v1 readable status (it is a v1_task_events_olap event_type / the assignment
#   marker is worker_id); we treat worker_id-assigned as the ASSIGNED transition.
# ============================================================================
total_tasks=0
assigned=0
active=0
: > "$diag_dir/v1-task-transition-history.txt"
for i in $(seq 1 30); do
  total_tasks="$(psql -tAc "SELECT count(*) FROM v1_task WHERE tenant_id = '$selected_tenant'" | tr -d '[:space:]')"
  assigned="$(psql -tAc "SELECT count(*) FROM v1_task_runtime WHERE tenant_id = '$selected_tenant' AND worker_id IS NOT NULL" | tr -d '[:space:]')"
  active="$(psql -tAc "SELECT count(*) FROM v1_tasks_olap WHERE tenant_id = '$selected_tenant' AND readable_status IN ('RUNNING','COMPLETED')" | tr -d '[:space:]')"
  total_tasks="${total_tasks:-0}"
  assigned="${assigned:-0}"
  active="${active:-0}"
  echo "poll_$i total=$total_tasks assigned=$assigned active=$active" >> "$diag_dir/v1-task-transition-history.txt"
  if [ "$total_tasks" -gt 0 ] && { [ "$assigned" -gt 0 ] || [ "$active" -gt 0 ]; }; then
    break
  fi
  sleep 2
done
{
  echo "total v1_task rows (tenant $selected_tenant): $total_tasks"
  echo "v1_task_runtime rows with worker_id (ASSIGNED): $assigned"
  echo "v1_tasks_olap readable_status RUNNING/COMPLETED: $active"
} > "$diag_dir/v1-task-summary.txt"
if [ "$total_tasks" -le 0 ]; then
  fail "no v1_task rows exist for tenant $selected_tenant; live suite produced no engine-visible submissions"
fi
if [ "$assigned" -le 0 ] && [ "$active" -le 0 ]; then
  fail "v1_task rows never left QUEUED for tenant $selected_tenant (assigned=$assigned active=$active); zero assignments — the hosted run 33229130339 failure mode"
fi

# ============================================================================
# Check 2: latest-version v1_task.is_durable=true for every canonical umd-<stage>
#   Submitted tasks belong to the current registered workflow version; every task
#   for a canonical umd-<stage> workflow must be durable. bool_and(true,...)=t and
#   count>0 required per stage.
# ============================================================================
DUR_OUT="$(psql -tAc "SELECT w.\"name\", bool_and(t.is_durable), count(*) FROM v1_task t JOIN \"WorkflowVersion\" wv ON wv.\"id\" = t.workflow_version_id JOIN \"Workflow\" w ON w.\"id\" = wv.\"workflowId\" WHERE t.tenant_id = '$selected_tenant' AND w.\"name\" LIKE 'umd-%' GROUP BY w.\"name\" ORDER BY w.\"name\"")"
printf '%s\n' "$DUR_OUT" > "$diag_dir/engine-visible-durability.txt"
for stage in $UMD_STAGES; do
  wf="umd-$stage"
  line="$(printf '%s\n' "$DUR_OUT" | grep -F "$wf|" | head -n1 || true)"
  if [ -z "$line" ]; then
    fail "no v1_task rows for canonical workflow $wf (latest-version durability unproven)"
  fi
  all_durable="$(printf '%s\n' "$line" | awk -F'|' '{print $2}')"
  n="$(printf '%s\n' "$line" | awk -F'|' '{print $3}')"
  n="${n:-0}"
  if [ "$all_durable" != "t" ] || [ "$n" -le 0 ]; then
    fail "workflow $wf latest-version tasks are not durably registered (is_durable=$all_durable, tasks=$n); AT-18 durability unproven"
  fi
done

# ============================================================================
# Check 3: worker registration / assignment / runtime rows exist
# ============================================================================
worker_count="$(psql -tAc "SELECT count(*) FROM \"$WORKER\" WHERE \"tenantId\" = '$selected_tenant'" | tr -d '[:space:]')"
runtime_rows="$(psql -tAc "SELECT count(*) FROM v1_task_runtime WHERE tenant_id = '$selected_tenant'" | tr -d '[:space:]')"
{
  echo "registered Worker rows (tenant $selected_tenant): ${worker_count:-0}"
  psql -tAc "SELECT \"id\", \"name\", \"tenantId\", \"status\" FROM \"$WORKER\" WHERE \"tenantId\" = '$selected_tenant'"
  echo "v1_task_runtime rows (tenant $selected_tenant): ${runtime_rows:-0}"
} > "$diag_dir/worker-assignment-runtime.txt"
if [ "${worker_count:-0}" -le 0 ]; then
  fail "no registered Worker rows for tenant $selected_tenant (worker never registered durably)"
fi
if [ "${runtime_rows:-0}" -le 0 ]; then
  fail "no v1_task_runtime rows for tenant $selected_tenant (no assignment/runtime evidence)"
fi

# ============================================================================
# Check 4: real callback-owned rows (created by the actual callback execution,
#   never by seeding): stage_run rows, semantic_event event_type='StageCompleted',
#   and job_run_audit operational-audit rows.
# ============================================================================
stage_run_rows="$(psql -tAc "SELECT count(*) FROM stage_run" | tr -d '[:space:]')"
completed_events="$(psql -tAc "SELECT count(*) FROM semantic_event WHERE event_type = 'StageCompleted'" | tr -d '[:space:]')"
audit_rows="$(psql -tAc "SELECT count(*) FROM job_run_audit" | tr -d '[:space:]')"
{
  echo "stage_run rows: ${stage_run_rows:-0}"
  echo "semantic_event event_type=StageCompleted: ${completed_events:-0}"
  echo "job_run_audit rows: ${audit_rows:-0}"
  echo "semantic_event event_type distribution:"
  psql -tAc "SELECT event_type, count(*) FROM semantic_event GROUP BY event_type ORDER BY 1"
} > "$diag_dir/callback-owned-rows.txt"
if [ "${stage_run_rows:-0}" -le 0 ]; then
  fail "no stage_run rows; the durable callback never created stage-run evidence"
fi
if [ "${completed_events:-0}" -le 0 ]; then
  fail "no semantic_event event_type='StageCompleted' rows; the durable callback never emitted StageCompleted"
fi
if [ "${audit_rows:-0}" -le 0 ]; then
  fail "no job_run_audit rows; the durable callback never wrote operational audit evidence"
fi

# ============================================================================
# Check 6: identity agreement — worker == workflow == submitted-task == selected
# ============================================================================
worker_tenants="$(psql -tAc "SELECT DISTINCT \"tenantId\" FROM \"$WORKER\" WHERE \"status\" = 'ACTIVE'" | tr -d '[:space:]')"
workflow_tenants="$(psql -tAc "SELECT DISTINCT \"tenantId\" FROM \"$WORKFLOW\" WHERE \"name\" LIKE 'umd-%'" | tr -d '[:space:]')"
task_tenants="$(psql -tAc "SELECT DISTINCT t.tenant_id FROM v1_task t JOIN \"WorkflowVersion\" wv ON wv.\"id\" = t.workflow_version_id JOIN \"Workflow\" w ON w.\"id\" = wv.\"workflowId\" WHERE t.tenant_id = '$selected_tenant' AND w.\"name\" LIKE 'umd-%'" | tr -d '[:space:]')"
agree=1
[ -z "$worker_tenants" ] && { echo "no ACTIVE worker tenant"; agree=0; }
[ -z "$workflow_tenants" ] && { echo "no umd-% workflow tenant"; agree=0; }
[ -z "$task_tenants" ] && { echo "no submitted-task tenant"; agree=0; }
# every distinct tenant must be the selected one (and non-empty)
for v in $worker_tenants $workflow_tenants $task_tenants; do
  if [ -z "$v" ] || [ "$v" != "$selected_tenant" ]; then
    echo "identity disagreement: saw tenant '$v' (expected '$selected_tenant')"
    agree=0
  fi
done
{
  echo "worker_tenant: $worker_tenants"
  echo "workflow_tenant: $workflow_tenants"
  echo "submitted_task_tenant: $task_tenants"
  echo "selected_tenant: $selected_tenant"
  echo "agreement: $([ "$agree" -eq 1 ] && echo OK || echo FAIL)"
} > "$diag_dir/identity-agreement.txt"
if [ "$agree" -ne 1 ]; then
  fail "identity agreement failed: worker/workflow/submitted-task tenant(s) do not all equal selected tenant $selected_tenant"
fi

# --- complete the shared identity record (P3-S2 asserts all agree) ---
{
  echo "worker_tenant: $worker_tenants"
  echo "workflow_tenant: $workflow_tenants"
  echo "submitted_task_tenant: $task_tenants"
} >> "$identity_file"

echo "PASS" > engine-visible-proof.txt
echo "[engine-visible-proof] PASS: assignments, durable latest-version umd-<stage>, worker/runtime rows, callback-owned rows, and identity agreement all verified for tenant $selected_tenant"
