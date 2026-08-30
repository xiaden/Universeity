# Effort Estimate — Plan K Live Hatchet Dependency-Barrier (leading: single-workflow DAG)

- **Agent:** rnd-estimator
- **Date:** 2026-08-29
- **Scope sized:** The **leading candidate** for the live Hatchet dependency-barrier decision (new round, distinct from the already-completed callback/registration/readiness repair). Per the debugger `living-aqua-weasel` and the Support-Librarian briefing, the leading architecture is **Option 1 — a single native Hatchet workflow DAG**: register all nine canonical stages as `durable_task(..., parents=[...])` inside **one** `Workflow` object, with edges derived only from `STAGE_DEPENDENCIES`/`STAGE_DEPENDENTS`, replacing the disproven `TriggerWorkflowOptions.parent_id` chain.
- **Decision status:** No architecture/complexity/adversarial report exists yet for this round; **no option has been selected** (rnd-manager locked **DD_REQUIRED** for this decision; Options 1–4 all on the table). This estimate sizes Option 1 as the leading candidate and flags the alternatives it would trade against. Sizing only — **does not alter DD_REQUIRED and cannot weaken AT-16/17/18/19 or L1–L21.**
- **Status:** DONE — sizing only. No source/test/workflow/plan/DD edits made.

---

## Verdict

```yaml
size: MEDIUM            # top of band; architecturally novel => dd_needed=true regardless
confidence: MEDIUM

scope:
  files:
    modify: 9            # hatchet.py, runner.py, cli.py, test_hatchet_live.py,
                         # validation.yml, engine-visible-proof.sh, capture-diagnostics.sh,
                         # record-release-summary.sh, Plan K (plan amendment; non-implementation)
    create: 0            # UmdStageInput already exists (hatchet.py:159-176)
    delete: 0
    total: 9
  sections: 22           # distinct edit locations (see breakdown)
  char_count: 38000      # estimated chars in edit scope, rounded up (conservative)
  cognitive_weight: 1.77 # 1 + 0.03*(22-1) + 0.015*(9-1)
  weighted_chars: 67260  # 38000 × 1.77

pipeline:
  plan_needed: true       # weighted 67.3K >= 32K (MEDIUM) — plan required
  dd_needed: true         # architecturally NOVEL (no prior single-workflow-DAG design) AND
                          # requirements incomplete (AT-18 reconciliation open, R19/Q2) —
                          # this axis triggers regardless of size; DD_REQUIRED already locked
```

---

## Scope (measured, not guessed)

The prior `...-plan-k-hatchet-live-blocker-final-estimate.md` (MEDIUM, 41.4K weighted) sized the **already-done** callback/registration/readiness repair (A2′/A1′/A3′) — that work is complete at HEAD `f99c556`. This round sizes the **dependency-barrier replacement** for the disproven `parent_id` design (hosted run `33240528692`). It is a **registration-model change** plus **submission change** plus **gate rework** plus **test re-scope** — materially larger than the defect-set repair, still bounded to the Hatchet adapter/runner/cli/hosted-gate/tests layer.

### Measured surface (traced at HEAD `f99c556`)

| File | Section | Change | Est. chars |
|---|---|---|---|
| `src/umd/jobs/hatchet.py` | `build_hatchet_workflows` (309-331) | Rewrite: build ONE `Workflow` containing 9 `durable_task(name, parents=[...])` bindings (parents from `STAGE_DEPENDENCIES`), not 9 standalone specs | 3,000 |
| `src/umd/jobs/hatchet.py` | `HatchetWorkerFactory.start` (539-597) | Register via `client.workflow(...)`/Workflow object with per-task `durable_task(..., parents=[...])`; `registered_workflows` becomes a single Workflow (task-count semantics); keep hard-fail/no-suppress | 4,000 |
| `src/umd/jobs/hatchet.py` | `_real_submit_workflow_run` (212-265) + `_SDKSubmissionShim` (268-288) | Remove/repurpose the `parent_id` barrier chain (now expressed intra-workflow); submit ONE job-level workflow run carrying full job context | 2,500 |
| `src/umd/jobs/hatchet.py` | `_make_handler` (334-426) | Handler dispatch per task (stage field selects work_registry entry) unchanged in shape; confirm single-workflow input boundary | 1,500 |
| `src/umd/jobs/hatchet.py` | `WorkerHandle` readiness (467-514) | `registered_workflows`/`is_ready` semantics → count tasks, not workflow objects | 1,000 |
| `src/umd/jobs/runner.py` | `submit_workflow_runs` (202-275) | Replace per-stage independent submission + parent_id threading with single job-level submission; keep `queued` events, drop the transitive-parent assumption (255-258) | 4,500 |
| `src/umd/deploy/cli.py` | `worker()` (28-144) | Readiness count: `len(handle.registered_workflows) != len(STAGE_ORDER)` (127-134) breaks under one workflow (count 1 ≠ 9) → count tasks within the workflow; `worker.start()` workflows arg passes the single Workflow | 1,200 |
| `tests/test_hatchet_live.py` | fixtures + live tests | `_RecordingClient` single-workflow/durable_task-with-parents shape; registration-shape re-scope; new single-workflow DAG/barrier/ordering tests; `live-dup` now expects exactly 9 keys (native barrier kills 2nd BASIC); `live-shape` replay; `_poll_until` job-scoped diagnostic (351-357) | 8,000 |
| `.github/workflows/validation.yml` + `engine-visible-proof.sh` (308) + `capture-diagnostics.sh` + `record-release-summary.sh` | hosted gate | Barrier evidence: single-WorkflowVersion registration exposes all 9 `v1_task` rows with `is_durable=true`; parent edges present in registration; no child `SENT_TO_WORKER`/`ASSIGNED`/`STARTED` before parent durable `stage_run status=complete` + `StageCompleted`; latest-version scoping; assignment via `v1_task_events_olap` + `v1_tasks_olap.worker_id` (never empty `v1_task_runtime`); callback-row polling | 4,500 |
| `artifacts/plans/pending/TASK-...-K-...md` + new DD (`pending`) | plan/DD amendment | Map the chosen architecture into P2-S8..S14, P4, Phase 5/6 gate; reconcile AT-18 (per-stage standalone durable vs single-workflow DAG); exec-planner + design work (counted lightly, non-implementation) | 3,000 |

**Total ≈ 38,000c**, 22 sections, 9 files, plus the DD/plan amendment. This is a **cross-cutting, multi-layer** change (registration layer + submission layer + readiness + hosted gate + tests + contract reconciliation).

**Explicitly NOT in scope** (per librarian/debugger constraints): no executor/`DurableStageExecutor`/OCFL/ledger/provenance/invalidation-ownership changes; no `StageRunRepository.claim` authority change; `InvalidationPlanner`/`STAGE_DEPENDENTS` remain sole lineage authority (CONTRACTS §35); no polling/callback-resubmission/runner-chain/second-scheduler/submission-time-snapshot; no DB/token/endpoint/`run_workflow`-semantics reopening. **Option 3 (lift the snapshot rejection) and Option 4 (pre-claim retry) are separate, and each requires its own new DD amendment** — not this scope.

---

## Weighted context / effort

- **Raw char count:** 38,000 (rounded up per conservative-measurement principle)
- **Cognitive weight:** 1.77 (`1 + 0.03×(22−1) + 0.015×(9−1)`)
- **Weighted chars:** **67,260** (≈ 16.8K weighted tokens at ~4 chars/token)
- **Size band:** **MEDIUM** (32K–80K), top of band. Cross-cutting but confined to the Hatchet adapter/runner/cli/gate/tests layer; no executor/ledger/semantic/provenance changes in scope.

**Why not LARGE:** the change stays within one ownership layer (the Hatchet scheduling/registration/evidence surface). The executor, repository claim authority, canonical lineage selector (`job_repository.canonical_evidence_refs`), semantic ledger, and projection ownership are untouched. What drives it high within MEDIUM is the registration-model change (single workflow DAG vs nine standalone) and the hosted-gate rework, not added machinery.

---

## Hosted probe and release-gate effort (called out separately)

1. **Single-workflow registration probe (pre-implementation, B2/B3 axis):** a targeted spike against the pinned `hatchet-sdk==1.38.1` / server `v0.105.2` must verify that one `Workflow` containing 9 `durable_task(name, parents=[...])` bindings registers **one `WorkflowVersion` with 9 distinct `v1_task` rows** (each with stable readable_id, individually identifiable for readiness/engine-proof), and that `len(registered_workflows)` task-count semantics survive. This is an open sub-question (librarian open_questions; exec-manager L125). If the probe fails, Option 1 is not viable without a **new DD** or an SDK/server pair change — see the separated alternative below.
2. **Hosted release gate (blocking):** the gate currently asserts non-null `parent_task_external_id` per dependent (P3-S3 / engine-visible-proof.sh). Under Option 1 the barrier evidence changes shape: parent edges live in the **workflow registration** (the `parents=[...]` list), so the gate must prove the single-WorkflowVersion registration exposes all nine `v1_task` rows with `is_durable=true` AND that no child is dispatched before its parent's durable `stage_run status=complete`/`StageCompleted` — via `v1_task_events_olap` transitions + `v1_tasks_olap.worker_id` (never empty `v1_task_runtime`), latest-version scoped, job-ID+marker scoped (the live-dup/live-shape evidence). This gate rework is a mandatory, release-blocking part of the scope.
3. **AT-18 reconciliation:** the single-workflow DAG conflicts with the literal per-stage standalone `client.durable_task(name=wf_name)(handler)` wording of netns DD AT-18 (lines 80–88, 185–188). This is a **contract/DD decision**, not an implementation detail — it is exactly why DD_REQUIRED stands and why this estimate does not change it. The DD must decide whether a single workflow of nine durable tasks satisfies AT-18 or whether AT-18 must be amended.

---

## Separated alternative: SDK/server pair upgrade (if Option 1 rejected)

The librarian/debugger route for Option 2 ("if no supported barrier exists on the pinned pair, record unsatisfiable and select an approved SDK/server pair change") and the blocker DD's sync-durable deprecation / forward-compatibility debt both point to a **SDK/server pair change** as a separate path. This is **explicitly separated and NOT part of this MEDIUM estimate**:

- It triggers the blocker DD's drain/rekey/rollback implications (forward-compatibility debt is deferred, per complexity review N2/Q5).
- It is a **coordinated SDK/server/DAG-universe change** (the deferred A4 async-durable path is part of this family), with the largest blast radius of any option.
- **If pursued, it must be re-estimated separately** after a new architecture/DD decision; it is not a bolt-on to this scope. This estimate does not size it.

---

## Risks / uncertainty

**Confidence: MEDIUM** — the code surface is well-traced and the DAG/lineage structure is fully understood, but three genuine uncertainties preclude HIGH, and one is architectural (no design report exists yet):

| # | Risk | Nature | Resolution |
|---|---|---|---|
| A1 | **No architecture selected yet** — this sizes the leading candidate (Option 1). If Options 2/3/4 are selected instead, the scope shifts materially (Option 3 lifts the snapshot rejection; Option 4 adds pre-claim retry/quarantine DD content). | HIGH, decision-level | Options report must select before Exec-Planner plans; estimate re-validated at that point |
| A2 | **Single-workflow registration granularity unproven** — does one `Workflow` with 9 `durable_task(parents=...)` surface 9 distinct `v1_task` rows with stable readable_id, and does `len(registered_workflows)` task-count readiness survive? | BLOCKING until spike | Targeted hosted/`mock_run` spike first (probe effort above) |
| A3 | **AT-18 reconciliation open (R19/Q2)** — single-workflow DAG vs per-stage standalone durable wording is a binding-contract question | MEDIUM, design | New DD must resolve; cannot be decided in implementation |
| A4 | **Barrier-evidence shape change** — gate must prove parent edges via registration + event-transition ordering, not `parent_task_external_id`; ordering proof is subtle | MEDIUM | engine-visible-proof.sh rework + hosted validation |
| B1 | Durable-slot assignment on v0.105.2 (carried from prior round) — all-durable may reproduce queued-but-unassigned | BLOCKING until hosted-proven | First hosted run shows ASSIGNED/RUNNING + callback-owned rows; `is_durable=true` alone is not proof |
| B2 | Strict-mypy overload acceptance of typed `UmdStageInput` (carried; already in tree) | MEDIUM | Existing A1′ fallback; not a size driver here |
| B5 | Gate polling accepts SDK ack before durable rows exist | MEDIUM | `_poll_until` for rows; never ack-only |
| R | live-dup 10-vs-9 / replay semantics under native barrier (unexpected-blush-bass) | MEDIUM | Barrier should collapse to exactly 9 keys; `_poll_until` job-scoped fix is SIMPLE |

The largest uncertainty is **hosted-outcome** (whether the successor run proves the native barrier on v0.105.2), not implementation size. If B1/A2 fails on the hosted axis, remediation may exceed this bounded set — that is a **new scope decision** through Support → R&D → plan → Exec, not a bolt-on.

---

## Recommended sequencing

1. **Architecture selection (prerequisite):** Options report + new DD resolving A1/A3 (single-workflow DAG vs alternatives; AT-18 reconciliation). DD_REQUIRED is locked; this estimate does not alter it.
2. **Pre-implementation probe (A2):** single-workflow registration spike against pinned pair → confirm 9 `v1_task` rows + task-count readiness; also re-confirm B2 typed-boundary.
3. **Production edits (registration first):** `hatchet.py` single-workflow registration + `_make_handler` dispatch → `runner.py` single job-level submission (drop parent_id chain) → `cli.py` task-count readiness.
4. **Test edits:** `_RecordingClient` single-workflow shape → registration-shape re-scope → new DAG/barrier/ordering tests → `live-dup`/`live-shape` assertions + `_poll_until` scoping.
5. **Hosted-gate evidence:** `validation.yml` + `engine-visible-proof.sh` + `capture-diagnostics.sh` + `record-release-summary.sh` rework to the new barrier-evidence shape.
6. **Plan K amendment** (exec-planner) mapping the chosen architecture into P2-S8..S14/P4 + Phase 5/6, then **Exec-Manager** pushes the SHA and runs the successor hosted run.
7. **Release gate (blocking):** hosted evidence per AT-16/17/18/19 composed with AT-1–15 must pass before any docs/DoD closure. Stop on any assignment, barrier-ordering, callback-row, tenant, durable, skip, or evidence failure.

---

## Gate authority (non-negotiable)

- **DD_REQUIRED is unchanged** — it was locked for this decision (rnd-manager L50) and this estimate cannot downgrade it. The single-workflow DAG is architecturally novel and AT-18 reconciliation is an open contract question; `dd_needed: true` is consistent with (not causing) DD_REQUIRED.
- **No gate weakening:** AT-16/17/18/19 composition (non-skippable, release-blocking), L1–L21, CONTRACTS §33 (claim authority) and §35 (descendant-only invalidation) all remain fully binding. No polling, snapshot, runner-chain, second scheduler, fake readiness, or recording-double-as-release-evidence is permitted.
- **Plan K Phases 5–6** cannot be reached until the retrieved hosted evidence passes.

---

## Blocker(s)

1. **A1 — no architecture selected.** This estimate sizes the leading candidate only. The options/DD decision must land before Exec-Planner can produce a faithful plan. (Not a size blocker — a sequencing prerequisite.)
2. **A2 — single-workflow registration granularity unproven** on the pinned pair: one `Workflow` × 9 `durable_task(parents=...)` must surface 9 distinct `v1_task` rows with stable readable_id and task-count readiness. If it does not, Option 1 is not viable without a new DD or an SDK/server pair change.
3. **A3 — AT-18 reconciliation open.** Whether the single-workflow DAG satisfies per-stage durable registration is a binding-contract decision for the new DD, not implementation.
4. **B1 — durable-slot assignment on v0.105.2** (carried): the successor hosted run must show ASSIGNED/RUNNING + callback-owned `stage_run`/`StageCompleted`/audit rows; QUEUED-with-no-assignment after the bounded window is a hard failure.

---

## Deliverable

**Exact report path:** `artifacts/designs/process/ESTIMATE-universal-media-decomposer-plan-k-live-hatchet-lineage-barrier.md`
**Size / confidence:** MEDIUM (top of band) / MEDIUM — weighted context ≈ 67,260 chars (≈16.8K weighted tokens); plan required; **new DD required** (architecturally novel + AT-18 reconciliation open + DD_REQUIRED already locked).
**Blocker(s):** A1 architecture selection (prerequisite), A2 single-workflow registration probe, A3 AT-18 reconciliation, B1 durable-slot hosted proof.
