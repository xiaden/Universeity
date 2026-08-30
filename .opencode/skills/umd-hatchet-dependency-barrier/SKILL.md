---
name: umd-hatchet-dependency-barrier
description: How UMD stage dependency barriers work (or fail) on the pinned hatchet-sdk==1.38.1/server v0.105.2 pair. Covers the P2-S8 parent_id no-op, the only verified native barrier (intra-workflow durable_task DAG), the authoritative assignment/execution proof tables (v1_task_events_olap, v1_tasks_olap.latest_worker_id) vs dead tables (v1_task_runtime, WorkerAssignEvent), and the live-dup/live-shape race root cause.
---

# UMD Hatchet Dependency Barriers (pinned pair)

## Mental Model
UMD submits every canonical stage (`umd-ingest` … `umd-current_search_projection`) to Hatchet as a separate workflow via `client.durable_task(...)` on the Hatchet object — which registers **9 standalone single-task workflows** (proven by dump: 9 Workflow rows, 9 WorkflowVersion rows kind=DAG each with ONE Task `{Parents: [], isDurable: true}`). The P2-S8 design tried to chain them via `TriggerWorkflowOptions(parent_id=...)`, but the server **never persists nor gates on it** on this pin: all 45 captured `v1_task` rows have `parent_task_id`/`parent_task_external_id`/`dag_id` NULL, `WorkflowRunTriggeredBy` (v0) is empty, and every task-input envelope carries `"parents": {}`. All 9 stages of a round dispatch concurrently and dependents fail pre-claim with `MissingRequiredEvidenceError` (canonical_evidence_refs has no COMPLETE upstream row yet). The only native mechanism that persists parent edges is an **intra-workflow task DAG**: `workflow.durable_task(name=..., parents=[...])` on ONE Workflow object (server side: v1_dag.parent_task_external_id, _StepOrder, Step.isDagOrchestrator, WorkflowVersion.isUsingDagOperator/dagShape — all dormant in the evidence because never exercised).

## Coverage
**Documented:** P2-S8 parent_id disproven; registration shape (9 single-task workflows); pre-claim fail-closed evidence resolution (hatchet.py:387 → job_repository.py:254); assignment proof tables; live-dup/live-shape race mechanism; Option 4 retry viability.
**Not yet documented:** a hosted probe run of the durable-task-in-DAG path (run-entry/eviction wiring, v1_task_events_olap population on that path); server-side behavior of parent_id on other versions; 2 FAILED tasks with `v1_tasks_olap.latest_worker_id=NULL` despite assigned events (tasks 18, 45 — projection quirk, events table authoritative). **Closed 2026-08-29:** intra-workflow DAG parent gating VERIFIED at engine source level (finding 2 — match conditions, children not inserted until parents complete); parent_step_run_id DISPROVEN as dispatch gate (queue pop has no parent-completion predicate).
**Last extended:** 2026-08-29

## Key Findings

### 1. TriggerWorkflowOptions.parent_id is a no-op dispatch barrier on pinned pair (DISPROVEN)
- **Location:** `.venv/.../hatchet_sdk/types/trigger.py:10-27`, `clients/admin.py:223-234` (→ TriggerWorkflowRequest.parent_id), `admin.py:371-412` (defaults from contextvars; None outside callback), `src/umd/jobs/runner.py:229-261` (threads `run_ids.get(max(deps, key=STAGE_ORDER.index))` as parent_id), `src/umd/jobs/hatchet.py:212-265` (`_real_submit_workflow_run`).
- **Evidence (run 33240528692, umd-dump.sql):** 45/45 v1_task rows parent_task_id/parent_task_external_id/dag_id = NULL; v1_runs_olap.parent_task_external_id NULL 45/45; WorkflowRunTriggeredBy COPY empty; v1_dag COPY empty; every TASK_INPUT payload `"parents": {}`; all 9 stages of each round inserted within ~400ms and ASSIGNED/STARTED concurrently (v1_task_events_olap 07:21:10.40–10.90).
- **Why it matters:** the plan's P2-S8 claim ("native parent-task barriers … no polling") is empirically false on the pin; dependent callbacks run before upstream stage_run commits → deterministic MissingRequiredEvidenceError cascade (12 COMPLETED / 33 FAILED; COMPLETED only when upstream COMPLETE rows pre-existed from prior rounds).

### 2. Only verified native multi-parent barrier = intra-workflow DAG (ENGINE-VERIFIED at v0.105.2)
- **Location:** `.venv/.../runnables/workflow.py:1701-1814` (`durable_task(..., parents: list[Task]|None, eviction_policy)`), `runnables/task.py:485-510` (`to_proto` → CreateTaskOpts parents=[p.name…], is_durable), `task.py:465/481` (`fn(workflow_input, ctx, **dependencies)` — parent outputs passed as kwargs).
- **Server side:** v1_task DDL parent_task_external_id/parent_task_id/dag_id (8313-8359); v1_dag.parent_task_external_id + idempotency_key; _StepOrder; WorkflowVersion.isUsingDagOperator/dagShape/kind=DAG. All present in the dump but unused (v1_dag empty).
- **Engine verification (v0.105.2):** triggerWorkflowsCore (pkg/repository/trigger.go:790-1648): `isDag := len(regularSteps) > 1` (1082); root steps (1217) inserted QUEUED; steps WITH parents (default branch 1388-1498) NOT inserted — only V1MatchKindTRIGGER match conditions per parent via getParentInDAGGroupMatch (1422, helper 2059-2196); child v1_task created only when the match fires (all parents reached required state). createDAGs (1727-1842) writes v1_dag + v1_dag_to_task with parent_task_external_id (dags.sql:23,33,43). Child input carries TaskInput.DagParentTaskRunIds (input.go:11-28, 50-75). Completion release: handleTaskCompleted (internal/services/controllers/task/controller.go:499-545) -> notifyQueuesOnCompletion (1007-1066) -> SchedulerPartitionTopic NotifyTaskReleased.
- **Caveat:** parent_task_external_id is task-to-task (intra-DAG), NOT workflow-run-to-workflow-run. Remaining probe: one workflow with 2 DURABLE tasks + parent edge -> submit once -> observe child v1_task row ABSENT until parent terminal event, then created with dag_parent_task_run_ids populated; verify durable run-entry/eviction wiring for match-created durable children (separate DurableEvents machinery).

### 3. Assignment/execution proof: v1_task_runtime.worker_id is the WRONG table on this pin
- **Location:** v1_task_runtime DDL 8730-8742 (COPY 12578 EMPTY); v1_tasks_olap 8853-8881 (latest_worker_id, readable_status, is_durable default false); v1_task_events_olap 12275+ (event_type QUEUED/ASSIGNED/STARTED/SENT_TO_WORKER/FINISHED/FAILED, worker_id); WorkerAssignEvent 5437-5441 (COPY EMPTY — v0 legacy).
- **Evidence:** engine-verdicts.txt `engine-visible-proof=FAIL reason=no v1_task_runtime rows` — the proof query used the empty table. Real assignment evidence: v1_task_events_olap ASSIGNED/STARTED/SENT_TO_WORKER/FINISHED/FAILED rows all carry worker_id=acf81bc6-cf62-46ca-a005-75e0a9bbe0d8 (umd-worker, isActive=t, sdkVersion 1.38.1); v1_tasks_olap latest_worker_id non-null on 43/45. FAILED events embed the full callback traceback; COMPLETED events embed the base64 flat ack.
- **Proof contract (adopted from living-aqua-weasel):** correlate workflow_run_id, step_id, task-event assignment/start events, OLAP status, runtime rows, WorkerAssignEvent. Do NOT infer absence of assignment solely from v1_task_runtime.worker_id IS NULL. Fail closed when no authoritative assignment or execution evidence exists.

### 4. live-dup extra stage_run = genuine lineage race, not global-count pollution
- **Location:** `src/umd/jobs/manifest.py:167-194` — idempotency_material includes evidence_refs but DELIBERATELY excludes job_id (rerun dedup); `src/umd/jobs/job_repository.py:181-266` — canonical_evidence_refs is job-independent, per-edge, status='complete', ORDER BY created_at DESC, idempotency_key DESC LIMIT 2, raises MissingRequiredEvidenceError/AmbiguousRequiredEvidenceError.
- **Mechanism (unexpected-blush-bass):** two callbacks for the same stage with different upstream evidence compute different keys → duplicate execution (live-dup BASIC 81c3 vs 95bb). Fix must enforce barrier OR stable evidence semantics; do NOT accept 10, weaken assertions, or add natural-key constraints.

### 5. Option 3 (submission-time snapshot) cannot work
- manifest evidence_refs=[] at submission; resolving at submission time freezes evidence before upstream completion → keys unstable across duplicate/restart timing (recreates live-dup at submission layer); descendant rerun rekeying (InvalidationPlanner descendant-only) requires CURRENT lineage, not frozen lineage. Keep rejected.

### 6. Option 4 (bounded pre-claim retry) is viable without polling
- Server-side durable-task retries (retries=N, backoff_factor/backoff_max_seconds; v1_retry_queue_item exists) re-invoke the callback; each attempt re-resolves canonical_evidence_refs pre-claim (hatchet.py:387) before executor.run/claim (stage_execution.py:219); failed attempts record no stage_run and no audit (audit at :234 is post-claim). Requires: retries bounded under schedule_timeout 5m; MissingRequiredEvidenceError stays fail-closed on exhaustion; no multiplication with executor's internal retry; hosted timeout/retry/restart/reclaim/idempotency tests. Does not need registration change.

### 7. Sync-durable deprecation is benign on pin (defer)
- 9 startup warnings "handler is defined as a synchronous, durable task…" (log-worker.txt); DeprecationWarnings at hatchet.py:569 (durable_task), hatchet.py:235, task.py:235. Tasks execute correctly. Defer as forward-compat debt; decide only if pin changes.

## Critical Invariants
- Claim-before-side-effect: DurableStageExecutor.claim is sole completion authority; MissingRequiredEvidenceError raised pre-claim must leave NO stage_run/audit rows (verified fail-closed in dump: FAILED tasks have no UMD rows).
- Fail-closed gates: missing evidence → MissingRequiredEvidenceError; ambiguous top-2 tie → AmbiguousRequiredEvidenceError; zero/multiple/null eligible tenant → TenantSelectionError before JWT minting.
- No polling, no resubmission, no snapshot fallback; skipped=0; machine-readable verdicts; AT-19 join before Phase 6.
- Idempotency material excludes job_id; includes evidence_refs — any barrier design must keep duplicate/restart convergence to exactly-one canonical key per (stage, lineage).

## Sources
- /tmp/r40528/diag-final/umd-dump.sql (v1_task 12154-12206, v1_tasks_olap 12627-12671, v1_task_events_olap 12276-12330, v1_payload 11481-11578, Workflow 10095, WorkflowVersion 10201, Worker 10070, v1_runs_olap 11999-12043, v1_dag 10798)
- /tmp/r40528/diag-final/{log-worker.txt, v1-task-transition-history.txt, v1-task-summary.txt, engine-verdicts.txt, live-tests.log}
- src/umd/jobs/{hatchet.py:212-597, runner.py:202-275, manifest.py:167-194, job_repository.py:181-266, stage_execution.py:204-299, drain.py:32-70}
- .venv/lib/python3.13/site-packages/hatchet_sdk/{runnables/workflow.py:1412-1457,1701-1814,1960-1993, runnables/task.py:465-510, clients/admin.py:223-234,371-412,414-457, types/trigger.py:10-27}
- Delegations living-aqua-weasel (run 33240528692) and unexpected-blush-bass (run 33237228740)
- artifacts/designs/pending/DD-universal-media-decomposer-plan-k-live-hatchet-blocker.md, DD-universal-media-decomposer-plan-k-netns-workflow-amendment.md, artifacts/designs/parts/universal-media-decomposer/CONTRACTS.md
