# Architecture Report: Plan K Live Hatchet Lineage Barrier

**Status:** Architecture options report (read-only)
**Date:** 2026-08-29
**Author:** `rnd-architect`
**Scope:** Decide how Plan K replaces the disproven cross-workflow `parent_id` assumption while preserving the UMD execution, lineage, durability, and hosted-release contracts.
**Required downstream consumers:** final DD author and PatternEnforcer.

This report creates no source, test, contract, plan, or pending-DD changes. It is the
architecture input for those later artifacts.

## Executive conclusion

The evidence-ranked architecture is **Option 1: one native Hatchet workflow DAG with
nine individually named durable tasks and all parents derived from
`STAGE_DEPENDENCIES`**. It is the only option that uses a native multi-parent scheduling
mechanism available in the pinned SDK without adding a second scheduler, a submission
snapshot, or callback polling. It is **conditional**, not yet release-approved: a real
hosted probe must prove the pinned `hatchet_sdk==1.38.1` / Hatchet server `v0.105.2`
registration shape, parent persistence, dispatch ordering, durable-slot assignment,
and callback-owned rows.

Two bounded contract reconciliations are prerequisites, not implementation details:

1. Reconcile AT-18 from literal standalone `client.durable_task` topology to the
   approved property that every canonical `umd-<stage>` is an individually identifiable
   durable task (`is_durable=true`) in the canonical workflow, without weakening the
   hosted assertion.
2. Change readiness from counting workflow objects to counting the nine registered
   durable tasks, and align the C6 readiness text and wait script.

`parent_id` is disproven on the pin. Option 2 is unsatisfiable on the pin unless a
targeted probe proves a real multi-parent barrier, or an explicitly approved SDK/server
pair change supplies one. Option 3 remains rejected. Option 4 is rejected as the
current architecture and may be reconsidered only as a separately approved fallback
with a new DD.

## Evidence and constraints

### Evidence ranking

* **T1 — hosted evidence:** run `33240528692` / job evidence and its database dump.
  Forty-five `v1_task` rows had null persisted parent fields; task events show
  dependents assigned before upstream durable completion. The earlier live-duplicate
  evidence produced 10 rather than 9 keys when callback-time evidence raced upstream
  commits.
* **T2 — pinned source and maintainer documentation:** installed SDK source confirms
  `Workflow.durable_task(..., parents=[...])` serializes named intra-workflow parents;
  Hatchet DAG documentation states that parent tasks complete before children run.
  Installed `TriggerWorkflowOptions` maps `parent_id` to request metadata and
  `parent_step_run_id` to a singular `parent_task_run_external_id` field.
* **T3 — independent operational evidence:** the adversarial record cites production
  DAG usage and documented polling/snapshot failure modes. This is corroboration, not
  a substitute for hosted proof on this exact pin.

### Binding invariants

The following remain unchanged under every option:

* Hatchet is the sole v1 scheduler; no runner chain, callback resubmission, polling
  scheduler, or second scheduler is permitted.
* `DurableStageExecutor` and `StageRunRepository.claim` remain the only completion
  authority. The Postgres unique `idempotency_key` claim occurs before side effects.
* `STAGE_DEPENDENCIES` / `STAGE_DEPENDENTS` are the sole lineage definition and
  `InvalidationPlanner` remains descendant-only.
* Callback-time `canonical_evidence_refs` remains job-independent, deterministic,
  and fail-closed on missing or ambiguous required evidence. It must not become a
  submission-time snapshot or job-scoped union.
* Semantic ledger, OCFL, provenance, cancellation, retry/quarantine, restart/reclaim,
  and DAG-universe drain ownership do not move.
* Hosted release evidence is native split Docker/Compose evidence with real JWT,
  truthful readiness, real callbacks, zero mandatory skips, and AT-16/17/18 composed
  under the non-skippable AT-19 gate.

## Options

### Option 1 — Single native Hatchet workflow DAG (conditional primary)

#### Architecture

* **Registration layer:** `src/umd/jobs/hatchet.py`, principally
  `build_hatchet_workflows` and `HatchetWorkerFactory.start`, builds one canonical
  `Workflow` and registers nine `workflow.durable_task` nodes named exactly
  `umd-{stage}`. Each node receives `parents` containing every direct parent task
  from `STAGE_DEPENDENCIES`; parents are defined before children in `STAGE_ORDER`.
* **Submission layer:** `src/umd/jobs/runner.py:submit_workflow_runs` submits one
  workflow run per job. It removes all `parent_id` threading. The durable input
  contains the job context and a stage-addressable manifest representation; each task
  must select only its own stage manifest and assert its bound stage identity.
* **Callback layer:** `_make_handler` remains a direct `(input, ctx)` callback. A
  closure is bound to each stage task. It performs persisted cancellation checks,
  resolves canonical committed evidence, obtains that stage's work from the registry,
  and calls `DurableStageExecutor.run`.
* **Persistence:** the executor creates or replays the stage's canonical
  `stage_run`, `StageCompleted`, and operational audit records. The callback returns
  only a JSON-safe acknowledgement; acknowledgement is not completion authority.
* **Readiness:** `WorkerHandle` and `src/umd/deploy/cli.py:worker` count the nine
  durable task identities, not the one workflow object. Exact names and exact count
  are required before the single blocking worker loop starts.

#### Per-stage callback to `stage_run` mapping

The mapping is one-to-one and stable:

| Hatchet task | Callback binding | Durable manifest identity | Authoritative rows |
|---|---|---|---|
| `umd-ingest` | handler closure bound to `INGEST` | `job_id`, source, universe, segment/root, `stage_name=INGEST` | one canonical `stage_run`, completion event, audit |
| `umd-format_analysis` | closure bound to `FORMAT_ANALYSIS` | same fields, `stage_name=FORMAT_ANALYSIS` | same row classes |
| `umd-basic_segmentation` | closure bound to `BASIC_SEGMENTATION` | same fields, stage-specific input/evidence | same row classes |
| `umd-low_level_extraction` | closure bound to `LOW_LEVEL_EXTRACTION` | same fields, stage-specific input/evidence | same row classes |
| `umd-structural_analysis` | closure bound to `STRUCTURAL_ANALYSIS` | same fields, stage-specific input/evidence | same row classes |
| `umd-entity_resolution` | closure bound to `ENTITY_RESOLUTION` | same fields, all canonical parent edges | same row classes |
| `umd-cross_source_alignment` | closure bound to `CROSS_SOURCE_ALIGNMENT` | same fields, all canonical parent edges | same row classes |
| `umd-semantic_reconciliation` | closure bound to `SEMANTIC_RECONCILIATION` | same fields, all canonical parent edges | same row classes |
| `umd-current_search_projection` | closure bound to `CURRENT_SEARCH_PROJECTION` | same fields, stage-specific input/evidence | same row classes |

The table is a mapping contract, not permission to create nine independent workflow
runs. The `stage_name` assertion prevents shared-input routing mistakes. Native parent
outputs may be available to a child, but canonical Postgres evidence selection remains
the correctness authority and the input to the executor's idempotency material.

#### Task-level readiness count

One `Workflow` object must not make readiness report `1/9` or fabricate `9` from the
work registry. The registration adapter should expose the nine actual durable task
objects or their nine actual `readable_id`s as `registered_tasks`. Readiness is true
only when:

* all and only the canonical `umd-{stage}` names are present;
* there are exactly `len(STAGE_ORDER) == 9` task identities;
* each task has a real callback and the real executor is bound; and
* registration did not return a partial or suppressed result.

`cli.py` must count these task identities, print task wording (for example,
`worker ready: registered 9 Hatchet tasks ...`), flush before
`client.worker(...).start()`, and fail before the line on any mismatch. The
`wait-for-worker.sh` marker must be updated in the same downstream change. The count
is a readiness assertion only; it never substitutes for hosted assignment or callback
proof.

#### Required hosted native DAG proof

The local recording client and SDK-shaped hermetic tests are shape coverage only. The
following must be proven against the actual pinned server before implementation is
accepted and again in the release run:

1. **Registration probe:** register a two-node parent/child DAG, then the full nine
   node DAG. Prove one workflow version contains individually identifiable task rows,
   stable `step_readable_id` values, `is_durable=true`, a `v1_dag` row, and persisted
   parent relationships. Verify the exact `workflow.durable_task` signature and the
   accepted handler arity/`eviction_policy` behavior.
2. **Ordering probe:** delay the parent. The child must have no
   `SENT_TO_WORKER`, `ASSIGNED`, or `STARTED` event before every authoritative parent
   has a durable `stage_run status=complete` and `StageCompleted` row. Compare event
   and completion timestamps; do not infer ordering from readiness or task insertion.
3. **Full graph proof:** every direct edge in `STAGE_DEPENDENCIES`, including
   multi-parent stages, is represented. No stage is silently reduced to the latest
   direct dependency.
4. **Execution proof:** all nine tasks are assigned and execute real callbacks. The
   `live-dup` submission and immediate duplicate converge to exactly nine canonical
   stage keys, nine `StageCompleted` rows, and nine complete job-audit rows. The
   `live-shape` replay has exactly six relevant replay rows/events and no new
   canonical rows for the replayed stages.
5. **Rerun proof:** selective descendant rerun may resubmit the DAG, but unaffected
   stages must claim no new side effects and emit only the approved replay observation;
   invalidated descendants must rekey through canonical lineage. Restart, reclaim,
   cancellation, and retry remain covered.
6. **Release composition:** the proof is scoped to the live job IDs and submission
   marker, joined to tenant/partition identity and AT-16/17/18. Zero mandatory skips,
   missing evidence, readiness-only evidence, or queued-only evidence is a hard fail.

#### Pros and cons

**Pros:** native scheduler barrier; all multi-parent edges are representable; no new
dependency or scheduler; preserves canonical evidence and executor authority; removes
the false external-run parent chain.

**Cons:** AT-18 wording and readiness semantics must be approved; one workflow loses
independent per-stage registration/versioning; shared input requires stage assertions;
single-workflow row granularity and durable-slot assignment are unproven on the pin;
the existing synchronous durable-task warning remains visible.

### Option 2 — Independent registrations with cross-workflow barrier or pair change

Keep nine standalone registrations and attempt `parent_step_run_id`, which maps to
`parent_task_run_external_id`. This is distinct from `parent_id`.

`parent_id` is **disproven**, not merely untested: run `33240528692` persisted null
parent fields across all 45 tasks, empty parent envelopes, and concurrent dependent
dispatch. `parent_step_run_id` is **singular and unproven**. It cannot obviously
represent stages with multiple direct parents, and the current runner submits only the
latest direct dependency (`runner.py:255-258`). A belt-and-suspenders use of both
fields would create a forbidden dual path.

Therefore Option 2 is **unsatisfiable on the pinned pair unless** a targeted hosted
probe proves persisted relationships, dispatch gating, and representation of every
multi-parent edge, **or** an explicitly approved SDK/server pair change supplies those
properties. A pair change is a separate architecture and migration decision requiring
`DagUniverseGate` drain/cancel, rekey, rollback, and fresh hosted proof; it is not a
small adapter substitution.

**Pros:** preserves standalone task naming and current workflow-count readiness if the
primitive works; independent task registration remains familiar.

**Cons:** no current proof of gating; singular field cannot express the repository DAG;
`parent_id` already failed; a pin change has the largest operational blast radius; the
hosted probe can diagnose the question but cannot make an unsupported field safe.

### Option 3 — Submission-time canonical-evidence snapshot

Freeze upstream evidence during submission and pass it to each later callback. This is
explicitly rejected by Plan K P2-S14, which requires native barriers plus canonical
lineage selection and says never to use the submission-time snapshot.

The snapshot is taken precisely while upstream work may still be incomplete, so it can
freeze the empty evidence that caused the blocker. It also makes idempotency timing
dependent: `evidence_refs` is part of `StageManifest.idempotency_material` while
`job_id` is deliberately excluded. A duplicate after upstream completion can therefore
rekey; descendant invalidation and DAG-universe drain can leave a frozen reference
stale. Replacing callback-time canonical selection would violate the lineage and
provenance invariants; retaining both creates competing evidence paths.

**Disposition: rejected.** Reconsideration would require an explicit new DD reversing
P2-S14 and a correctness argument absent from the evidence. It is not an implementation
fallback.

### Option 4 — Pre-claim bounded durable retry/quarantine

When canonical evidence is missing, raise before `DurableStageExecutor.run` and let a
bounded scheduler retry/backoff policy invoke the callback again. On exhaustion,
remain fail-closed. This can avoid a synchronous polling loop if modeled entirely as
durable task retries, but it adds retry/quarantine/timeout semantics to the callback
boundary and leaves a worker slot or timeout budget exposed while the dependency is
not ready. Direct database access in a durable callback also requires an explicit
determinism boundary under the maintainer guidance.

**Disposition: rejected as the current architecture; fallback only.** It may be
activated only if the native DAG is proven inexpressible or unusable after engine-slot
investigation, and only through a new DD defining bounded attempts, quarantine,
restart/reclaim behavior, timeout limits, strict pre-claim placement, fail-closed
exhaustion, and hosted proof. It must never become callback polling, post-claim retry,
or callback resubmission.

## Weighted tradeoff matrix

Scores are 1 (poor) through 5 (strong). Weights reflect this release blocker: a real
multi-parent barrier and preservation of lineage authority outweigh registration
convenience. The total is a fit score, not hosted proof.

| Criterion | Weight | O1 native DAG | O2 cross-workflow field/pair | O3 snapshot | O4 pre-claim retry |
|---|---:|---:|---:|---:|---:|
| Native dispatch barrier | 25% | 4 | 1 | 1 | 2 |
| All multi-parent edges | 15% | 5 | 1 | 4 | 3 |
| Lineage/idempotency invariants | 20% | 5 | 4 | 1 | 3 |
| Scope and migration cost | 10% | 4 | 2 | 2 | 2 |
| Hosted proofability | 10% | 4 | 1 | 1 | 2 |
| Operational simplicity | 10% | 4 | 2 | 3 | 1 |
| Rerun/restart flexibility | 5% | 4 | 3 | 1 | 2 |
| Regression risk | 5% | 4 | 1 | 1 | 2 |
| **Weighted total (/5)** | **100%** | **4.35** | **1.90** | **1.75** | **2.25** |

## Shared proof corrections and warnings

### Assignment proof

`v1_task_runtime.worker_id` is ephemeral and empty in the supplied v0.105.2 dump after
terminal execution; `WorkerAssignEvent` is a legacy/non-authoritative path. A null
runtime row must not be reported as absence of assignment, and `ASSIGNED` is an event
type, not a `v1_tasks_olap.readable_status` value.

The shared hosted proof must correlate, within the submitted task/job and time window:

* `v1_task_events_olap` `SENT_TO_WORKER`, `ASSIGNED`, and `STARTED` events carrying the
  actual `umd-worker` ID;
* `v1_tasks_olap.readable_status` and `latest_worker_id` as corroborating projection;
* active, unpaused worker identity and tenant/partition agreement;
* task/workflow/run IDs and callback-owned `stage_run`, `StageCompleted`, and audit rows.

The event table is authoritative when OLAP `latest_worker_id` is null on a terminal
failure. No readiness line, local registration object, accepted submission, global
row count, or empty `v1_task_runtime` table can close the gate.

### Synchronous durable-task warning

The worker log records synchronous durable-task deprecation warnings (including the
warning region at `log-worker.txt:5-13`; the SDK warning sites include `hatchet.py` and
`task.py`). Existing callbacks executed on the pin, and the blocker DD defers async
conversion. Option 1 must probe whether the workflow DAG surface accepts the existing
`(input, ctx)` handler and must not silently convert it. If the DAG surface requires
async handlers, stop for an explicit human decision/new DD; do not hide the warning or
introduce an unapproved compatibility path.

## Exact affected surfaces

The following are the expected downstream implementation and proof surfaces. They are
listed for handoff only; this report does not edit them.

| Surface | Required change or proof |
|---|---|
| `src/umd/jobs/hatchet.py` — `build_hatchet_workflows` | Represent one workflow with nine task nodes and all parent lists from the canonical DAG. |
| `src/umd/jobs/hatchet.py` — `HatchetWorkerFactory.start` | Register the single workflow, expose/count actual task identities, preserve surfaced decorator failures and one worker loop. |
| `src/umd/jobs/hatchet.py` — `_make_handler` and submission shim | Bind each callback to one stage, validate direct v1 input, remove external `parent_id`, preserve cancellation/evidence/executor/JSON-ack behavior. |
| `src/umd/jobs/runner.py` — `submit_workflow_runs` | Submit one job-level DAG run; express no parent chain; retain queued-only asynchronous status and rerun causation. |
| `src/umd/jobs/manifest.py` | Only if required by the validated shared-input shape: provide stage-addressable extraction without changing idempotency material or excluding canonical evidence. |
| `src/umd/deploy/cli.py` — `worker` | Count nine durable tasks, fail closed on mismatch, print task wording before the blocking start. |
| `tests/test_hatchet_live.py` | Update recording shape; add stage-routing/direct-input negatives, DAG parent shape, duplicate/replay and hosted-scoped expectations. Recording tests remain non-release evidence. |
| `.github/scripts/engine-visible-proof.sh` | Replace standalone-workflow assumptions with task/readable-id and registration-edge proof; use event/OLAP assignment evidence; add parent/child timestamp proof and exact job scoping. |
| `.github/scripts/wait-for-worker.sh` | Update the readiness marker wording from workflows to tasks without weakening the exact-count gate. |
| `.github/workflows/validation.yml` | Run the native split topology, pre-marker submissions, hosted probe/release checks, and always-capture diagnostics with zero mandatory skips. |
| `.github/scripts/capture-diagnostics.sh` | Capture DAG rows, parent edges, task events, worker/tenant identity, callback rows, and pre-teardown state. |
| `.github/scripts/record-release-summary.sh` | Surface task-level readiness, assignment/barrier verdicts, and missing/FAIL verdicts as release-blocking. |
| `CONTRACTS.md` §62 and netns DD AT-18 | Downstream approval must reconcile task property versus standalone registration wording; hosted `is_durable=true` and exact names remain mandatory. |
| Plan K P2-S8..S14 and Phase 5/6 gates | Downstream planner must map the selected architecture, probe, canonical evidence, replay, and AT-19 acceptance. |

Explicitly unchanged: `DurableStageExecutor`, `StageRunRepository.claim`,
`canonical_evidence_refs`, `InvalidationPlanner`, semantic-ledger authority, OCFL,
tenant-selection ownership, and the Hatchet/server topology. Any change to those
owners requires a separate approved DD.

## Risks

1. **Blocking — durable-slot assignment:** the prior hosted run had durable-looking
   rows but no assignments. Investigate engine slot/configuration behavior first;
   `is_durable=true` alone is insufficient.
2. **High — row granularity:** the single workflow has not yet been hosted-proven to
   yield nine stable, individually assertable `v1_task` rows.
3. **High — AT-18 mismatch:** a literal standalone-registration interpretation would
   reject Option 1; silent reinterpretation would weaken process authority.
4. **High — handler contract:** the sync warning may become a hard incompatibility on
   the workflow DAG surface; async conversion is not authorized implicitly.
5. **Medium — shared input:** a missing stage assertion could route a task to the
   wrong manifest and stage.
6. **Medium — selective rerun:** resubmitting one DAG necessarily presents unaffected
   tasks again; only claim-before-side-effect and replay attribution make this safe.
7. **Medium — proof drift:** OLAP projections and event schemas can disagree; queries
   must use authoritative event transitions and state their tie-break rules.
8. **Medium — edge completeness:** any remaining latest-parent logic in the runner
   would silently violate multi-parent lineage even if the DAG registration is right.
9. **Medium — timeout/ordering:** native barrier proof must compare durable completion
   to worker event timestamps, not insertion time or callback acknowledgements.

## Approval questions and gates

These questions belong to the DD/contract owners and must be answered before the
implementation plan is amended:

1. **AT-18 (H1):** Does “every canonical `umd-<stage>` registered as its own durable
   task” permit nine named durable tasks inside one canonical workflow? Approval must
   preserve exact names, nine task identities, and hosted `is_durable=true` for every
   latest task; otherwise Option 1 cannot proceed.
2. **Readiness (H2):** Is the release count explicitly nine durable tasks rather than
   one workflow object, with C6 and `wait-for-worker.sh` wording changed in lockstep?
3. **Hosted DAG gate:** Does the two-node probe and full nine-node run prove persisted
   parent edges, child-after-parent dispatch, durable assignment, and all callback rows
   on v0.105.2? A local SDK or recording-client pass is insufficient.
4. **Sync warning (H3):** If the DAG surface requires async handlers, will the owner
   approve a scoped async DD, change the approved pin, or deliberately route to the
   separately defined fallback? No silent conversion is permitted.
5. **Rerun semantics (H4):** Is whole-DAG resubmission with executor dedupe accepted
   as selective rerun, provided hosted evidence proves nine canonical keys, zero
   unaffected side effects, and approved replay observations?
6. **Assignment evidence:** Does the release gate adopt `v1_task_events_olap` plus
   `v1_tasks_olap` corroboration and remove any inference from empty
   `v1_task_runtime`? This is a shared gate correction for every option.
7. **Fallback authority:** If native durable slots fail after configuration
   investigation, is a new DD authorized for Option 4's strictly pre-claim bounded
   retry semantics, or must the release remain blocked for a separately approved
   pair change?

## Single evidence-ranked recommendation

**Proceed with Option 1 conditionally, subject to the hosted probe and the two explicit
AT-18/readiness approvals.** This is the sole recommendation in this report. The
evidence rank is: T1 disproves `parent_id`; T2 supplies the only available native
multi-parent mechanism (`Workflow.durable_task(parents=[...])`); the adversarial and
complexity reviews find Options 3 and 4 reintroduce rejected evidence/polling machinery,
while Option 2 remains singular and unproven. If the probe fails, do not silently
fall back: record the failure, investigate durable-slot configuration, and route either
an explicitly approved SDK/server pair change or the separately DD-gated Option 4
through Support → R&D → planner → Exec.

## Source index

* `artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-plan-k-live-hatchet-lineage-barrier.md` — complete eight-turn refinement, evidence tiers, risks, and option dispositions.
* `artifacts/designs/process/COMPLEXITY-universal-media-decomposer-plan-k-live-hatchet-lineage-barrier.md` — elevated complexity review and shared proof correction.
* `artifacts/designs/process/ESTIMATE-universal-media-decomposer-plan-k-live-hatchet-lineage-barrier.md` — MEDIUM/top-of-band estimate, approximately 9 implementation surfaces and 38K raw characters for the leading candidate.
* Fresh Support-Researcher report:
  `/home/opencode/.local/share/opencode/delegations/871898c83592455e/ses_fb88c62f2ffehWyRoYSXqGS5b1/encouraging-emerald-mandrill.md`
  — pinned source/dump findings, assignment proof, callback mapping, and hosted
  acceptance evidence.
* `src/umd/jobs/hatchet.py:309-331,334-426,517-597`; `src/umd/jobs/runner.py:202-275`; `src/umd/jobs/stage_execution.py:204-269`; `src/umd/jobs/manifest.py:167-184`.
* `artifacts/designs/parts/universal-media-decomposer/CONTRACTS.md:58-67` and pending netns DD AT-18/AT-19 wording.
* Hosted run `33240528692` and the pinned installed SDK under `.venv/lib/python3.13/site-packages/hatchet_sdk/`; maintainer documentation checked 2026-08-29.
