# Adversarial Design Log: Universal Media Decomposer — Plan K Live-Hatchet Lineage Barrier

*This file records the full adversarial refinement process for the Plan K live-Hatchet
dependency-barrier architecture decision (Options 1–4). The design document
(`DD-universal-media-decomposer-plan-k-live-hatchet-blocker.md`) and the Plan K amendment
contain distilled decisions, not this raw debate.*

*Process constraint honored: **no child agents were spawned** (explicit instruction).
All eight substantive turns were executed inline by the Refiner, each under the named
adversarial role (Ideator, Counter-Ideator, Improver, Counter-Improver) in the mandated
order, with web research and installed-SDK/source inspection performed directly and
recorded per turn.*

---

## 1. Original request and immutable requirement ledger (verbatim, unweakened)

### 1.1 The authoritative request (verbatim)

> Design decision required for the Universal Media Decomposer Plan K live-Hatchet blocker. R&D owns the formal design workflow (adversarial refinement + architect + complexity + estimator + DD authoring as you see fit). This is a NEEDS_PLAN architecture decision; Exec-Manager routed it to R&D per the immutable mandate (hosted-run root cause → Support → R&D → planner amendment → Exec). Do NOT implement code; produce the design decision + any required DD.
>
> Immutable requirements: Task.md Universal Media Decomposer DoD requires a durable async job system (restartable after restart, cancel/retry/selective rerun), rerunnable DAG decomposition with descendant-only invalidation, no stubs/skips/fake readiness/recording doubles as release evidence, Hatchet SOLE v1 scheduler, real callbacks through DurableStageExecutor, durable-only registration, truthful readiness, hosted native Docker/Compose evidence before docs/DoD closure. CONTRACTS.md is binding: StageRunRepository.claim UNIQUE(idempotency_key) authoritative; DurableStageExecutor claim-before-side-effect sole completion authority; STAGE_DEPENDENTS/STAGE_DEPENDENCIES sole lineage definition; InvalidationPlanner descendant-only; SemanticLedger append-only; §62 HatchetWorkerFactory.start registers pinned workflows/tasks bound to DurableStageExecutor; §58-63 production execution contracts; AT-18 requires every canonical umd-<stage> registered as its own durable task (interpretation in question). Plan K is artifacts/plans/pending/TASK-universal-media-decomposer-K-ci-repair-release-gate.md, Phase 2 amendment 2 P2-S8..S14. Prior design (a)+(c), native barriers + canonical lineage evidence selection, never submission-time snapshot, is disproven by hosted evidence. Blocker DD is artifacts/designs/pending/DD-universal-media-decomposer-plan-k-live-hatchet-blocker.md with immutable L1-L21; no executor/scheduler/topology/DB/token/endpoint/run_workflow/OCFL/semantic/provenance/invalidation ownership changes authorized without explicit approval/new DD.
>
> Decide among Options 1-4: (1) single native Hatchet workflow DAG, nine durable_task parents edges, reconcile AT-18, task-level readiness and callback rows; (2) independent durable registrations + verified server barrier, parent_step_run_id singular/unproven and parent_id disproven; (3) lift rejected submission-time snapshot with new amendment; (4) pre-claim bounded durable retry with no polling/resubmission. Also assignment/runtime proof (worker_id=0 concern) and sync durable warning. Evidence paths: /home/opencode/.local/share/opencode/delegations/871898c83592455e/ses_fb88c62f2ffehWyRoYSXqGS5b1/living-aqua-weasel.md, unexpected-blush-bass.md, /tmp/r40528/diag-final/*, installed SDK /workspace/Universeity/.venv/lib/python3.13/site-packages/hatchet_sdk/, source src/umd/jobs/{runner.py,hatchet.py,stage_execution.py,manifest.py,drain.py}, src/umd/storage/postgres/job_repository.py, CONTRACTS, current Plan K and netns DD. Support-Librarian report: /home/opencode/.local/share/opencode/delegations/871898c83592455e/ses_fb38a53afffe34u4LVjeFkK178/optimistic-olive-gerbil.md. Support-Researcher is concurrently investigating; use it if present, otherwise complete source research yourself and label it. Hosted evidence: parent_id metadata-only; all 45 rows had null parent fields, children assigned before upstream completion, callback race produced 10 vs 9 keys; v1_task_runtime.worker_id=0/empty runtime is not authoritative; only workflow/step/task-event/OLAP correlated evidence is acceptable.

> **Path-correction note (Refiner):** The Support-Librarian report was located at
> `.../delegations/871898c83592455e/ses_fb88c62f2ffehWyRoYSXqGS5b1/optimistic-olive-gerbil.md`
> (the `ses_fb38a53afffe34u4LVjeFkK178` directory named in the request no longer exists;
> the report's own header records `Session: ses_fb38a53afffe34u4LVjeFkK178`). Content is
> the librarian briefing cited throughout this log as `optimistic-olive-gerbil`.

### 1.2 Blocker DD immutable L1–L21 ledger (verbatim, unchanged)

From `artifacts/designs/pending/DD-universal-media-decomposer-plan-k-live-hatchet-blocker.md`
§2, reproduced unchanged (authoritative):

- **L1** "Continue formal Plan K R&D workflow for the newly diagnosed live Hatchet blocker."
- **L2** "Support evidence is decisive: run 33229130339 Docker job 99038602321 reached full split topology, API readiness, genuine worker registration, external HTTP, and live submissions."
- **L3** "Every live task then failed before UMD execution because Hatchet SDK 1.38.1 invokes task callbacks as fn(workflow_input, ctx), while src/umd/jobs/hatchet.py:_make_handler returns handler(payload) and expects payload['input']['manifest'] (v0 shape)."
- **L4** "Hermetic tests/test_hatchet_live.py:_invoke_callback at ~459 encode the same wrong wrapper, masking defect."
- **L5** "Correct v1 input is direct dict with manifest."
- **L6** "DB/token/endpoint/run_workflow semantics are ruled out."
- **L7** "Separate defects: HatchetWorkerFactory.start swallows real decorator exceptions and cli.py readiness count falls back to len(work_registry), allowing fabricated readiness; engine-visible registration test only inspects local Standalone objects."
- **L8** "Also prior tenant-selection bug was fixed/diagnosed, but preserve requirement to select runnable tenant with non-null partitions and assert assignment/runtime state."
- **L9** "Task.md Universal Media Decomposer DoD fully realized."
- **L10** "Hatchet sole v1 scheduler."
- **L11** "real callbacks/DurableStageExecutor."
- **L12** "durable async restart/retry/cancel/selective invalidation."
- **L13** "no skips/stubs/fake readiness/recording doubles as release evidence."
- **L14** "no weakening gates."
- **L15** "hosted native Docker/Compose, public HTTP heterogeneous E2E, zero mandatory skips, retrieved evidence before docs/DoD closure."
- **L16** "preserve OCFL/evidence/semantic/provenance invariants."
- **L17** "Run required R&D formal process (librarian/researcher, adversarial refinement, architect, complexity, estimator, DDAuthor, PatternEnforcer; no skipped stages)."
- **L18** "create/amend validated implementation plan under artifacts/plans/pending."
- **L19** "Explicitly plan spec-first handler contract tests, real callback fix, hermetic test alignment without lowering live gate, surfaced registration failures/readiness truthfulness, engine-visible proof or honest test scope, assignment/runtime diagnostics, and rerun hosted CI."
- **L20** "Do not edit production/workflow/tests yourself."
- **L21** "Return plan paths, requirement ledger, risks, exact acceptance evidence for Exec-Manager."

### 1.3 Binding contracts referenced (verbatim essence, unweakened)

- `CONTRACTS.md` §33: `StageRunRepository.claim(idempotency_key, manifest) -> StageRunClaim` — PostgreSQL `UNIQUE(idempotency_key)` is authoritative; handler checks it before side effects.
- `CONTRACTS.md` §35: `InvalidationPlanner.plan(...) -> StageTargets` — descendant-only, pure planning; unaffected extraction/evidence is retained.
- `CONTRACTS.md` §58–63: production execution remediation contracts; §61 `ProductionDAGRunner.run_graph` dispatches to the sole Hatchet scheduler; §62 `HatchetWorkerFactory.start(runtime, work_registry, executor) -> WorkerHandle` — registers the pinned Hatchet workflows/tasks and binds each callback to `DurableStageExecutor`; §63 `CapabilityReporter`.
- Netns DD AT-18 (binding): "every release `umd-<stage>` task uses `client.durable_task(name=wf_name)(handler)`, and hosted DB/engine evidence asserts every resulting `v1_task.is_durable=true`". This is the **interpretation in question** for Option 1.
- Plan K P2-S14 (line 105): choose and implement **(a) native Hatchet dependency barriers plus (c) canonical source/universe/segment/edge/lineage evidence selection**, never (b) a submission-time snapshot.

---

## 2. Turn 1 — ## Proposed Approaches

*Role: rnd-ideator (inline). Task: propose 3–4 distinct architectural approaches; for each,
cite at least one real production system/usage; validate every technology/version choice
against official or maintainer sources with check dates; note best fit.*

*Technology-validation baseline (all approaches):* pinned `hatchet_sdk==1.38.1` (installed at
`/workspace/Universeity/.venv/lib/python3.13/site-packages/hatchet_sdk/`, inspected 2026-08-29)
paired with server image `ghcr.io/hatchet-dev/hatchet/hatchet-engine:v0.105.2`. Hatchet is the
sole v1 scheduler (L10). Web documentation checked 2026-08-29 at `docs.hatchet.run`.

### Approach 1 — Single native Hatchet workflow DAG, nine `durable_task` parents edges (Option 1)

**Mechanism.** Register ONE workflow whose nine tasks are `workflow.durable_task(name=f"umd-{stage}", parents=[...])` with parent edges derived **only** from `STAGE_DEPENDENCIES`/`STAGE_DEPENDENTS`. The pinned SDK serializes the parents graph into the workflow-version registration (`runnables/workflow.py:1701-1814` `durable_task(..., parents=[...])`; `runnables/task.py:485-510` serializes `parents=[p.name ...]` and `is_durable`; `BaseWorkflow.to_proto()` serializes the task graph into workflow-version registration). Each task keeps a distinct readable `umd-<stage>` id, so per-stage `v1_task` rows, engine proof, and callback→`stage_run` mapping remain individually identifiable. The callback remains the existing `_make_handler` → `DurableStageExecutor` path (A2′/A1′ boundary, claim-before-side-effect, canonical evidence selection retained).

**Evidence that this is the native mechanism.**
- Official Hatchet docs, "DAGs as Durable Workflows" (`docs.hatchet.run/v1/directed-acyclic-graphs`, checked 2026-08-29): "A directed acyclic graph (DAG) is a workflow where every task, along with the dependencies between them, is declared upfront… Hatchet schedules the tasks in the right order, runs tasks that don't depend on each other in parallel…" and "A task can declare one or more parent tasks, meaning that those parent tasks must complete successfully before the child task is allowed to run."
- Official docs, "DAGs … are a form of durable execution by definition. Every time a task in a DAG completes, Hatchet persists its status and result so that the DAG can be retried without re-executing succeeded parts."
- Official docs, "Durable Tasks vs DAGs" cookbook (`docs.hatchet.run/cookbooks/durable-tasks-vs-dags`): document-processing and ETL pipelines are the canonical DAG use case — "Document processing, ETL pipelines, and CI/CD pipelines are good examples" — and "Hatchet's SDK allows a DAG to contain one or more durable task nodes."
- Installed SDK source (inspected 2026-08-29): `workflow.durable_task` accepts `parents: list[Task[...]]` and "Parents must be defined before their children."

**Production-system analog (cited).** PostHog executes DAG data-modeling pipelines as child workflows on Temporal with Kahn topological ordering in production (`github.com/PostHog/posthog/blob/0622fb80/.../workflows/execute_dag.py`) — evidence that declarative DAG decomposition with parent-gated dispatch is a production-proven pattern; Hatchet's equivalent is the workflow-level DAG.

**AT-18 reconciliation required.** AT-18's wording says each release `umd-<stage>` task uses `client.durable_task(name=wf_name)(handler)`. Under this approach every `umd-<stage>` remains a durable task named `umd-<stage>`, but registration is `workflow.durable_task` inside one workflow rather than a standalone `client.durable_task`. The hosted assertion (`v1_task.is_durable=true` for every latest version) must be re-verified at spike; AT-18 wording needs an explicit reconciliation/amendment, not silent reinterpretation (librarian: "This is the AT-18 text Option 1 (single-workflow DAG) must reconcile — it reads as per-stage independent durable registration (R19 'interpretation in question')").

**Task-level readiness and callback rows.** Readiness must count **tasks** (9), not workflows (1), because `len(registered_workflows)` would return 1. Callback rows remain per-stage via the `stage` field in each task's input.

### Approach 2 — Independent durable registrations + verified server barrier (Option 2)

**Mechanism.** Keep nine independent `umd-<stage>` durable task/workflow registrations (current topology) and connect them with the only remaining cross-workflow candidate: `TriggerWorkflowOptions.parent_step_run_id`, which the pinned SDK maps to `parent_task_run_external_id` (`clients/admin.py:227`: `parent_task_run_external_id=_options.parent_step_run_id`). The alternative `parent_id` maps to `TriggerWorkflowRequest.parent_id` (metadata field 4) and is **disproven** by hosted evidence (all 45 rows null parent fields). This approach requires a targeted hosted v0.105.2 persistence-and-dispatch probe before it can be accepted, and every `STAGE_DEPENDENCIES` edge must be expressed (current `runner.py:255-258` submits only the latest direct dependency — a defect even if the field worked).

**Evidence / technology validation.**
- Installed SDK `types/trigger.py` (inspected 2026-08-29): `TriggerWorkflowOptions(parent_id, parent_step_run_id, child_index, child_key, ...)`; `clients/admin.py:223-234` maps `parent_id`→`TriggerWorkflowRequest.parent_id`, `parent_step_run_id`→`parent_task_run_external_id`; `clients/admin.py:396-397` derives defaults from workflow/step-run context.
- Debugger `living-aqua-weasel` §1: "The SDK/API exposes a separate `parent_step_run_id`, but neither the SDK source nor this run proves that it gates external workflow dispatch. If it has server-side semantics, it would require the **specific upstream step-run external ID**, not the upstream workflow-run ID. It is also singular and cannot obviously represent multiple direct parents." → **unproven and singular**; must be treated as unverified until a hosted probe.
- This is the "record unsatisfiable if not provable" branch from `living-aqua-weasel` §4: if no supported mechanism exists on the pinned pair, record the requirement as unsatisfiable and select an approved SDK/server pair or amend the contract.

### Approach 3 — Lift the rejected submission-time snapshot (Option 3)

**Mechanism.** Reverse Plan K P2-S14's rejection of design (b): snapshot canonical upstream evidence at submission/lineage time so dependents never resolve empty evidence. Requires a new DD amendment explicitly reversing P2-S14 (librarian warning table: "Option 3 (lift snapshot rejection) requires a new DD amendment explicitly reversing this — cannot be introduced as an implementation detail").

**Evidence / why it was rejected.**
- Plan K P2-S14 line 105: "choose and implement **(a) native Hatchet dependency barriers plus (c) canonical source/universe/segment/edge/lineage evidence selection**, never (b) a submission-time snapshot."
- Debugger `unexpected-blush-bass`: the `live-dup` 10-vs-9 overexecution is a genuine lineage/dependency race; "enforce dependency barriers before downstream callbacks, or snapshot canonical upstream evidence at submission/lineage time" are listed product-repair options, but the same report's prescribed acceptance is exactly nine canonical keys with stable evidence — the snapshot alternative is not automatically compatible with the canonical-selection and fail-closed semantics already built.
- Cross-engine warning (Temporal, Nejc Korasa, "Temporal in Production", 2026-07-17, `nejckorasa.github.io/posts/temporal-in-production/`): "A snapshot captured early goes stale, and writing it back clobbers a concurrent update; passing IDs sidesteps that" — supports canonical selection (c) over frozen submission-time snapshots.

**Critical technical objection (raised in this turn, expanded in Critique):** the observed race is **early dispatch** — dependents are assigned before upstream commits. A submission-time snapshot is taken at submission, when upstream has *not* completed, so it would capture the same empty evidence that caused the failure. It cannot fix the barrier problem; it only stabilizes a snapshot that is already wrong.

### Approach 4 — Pre-claim bounded durable retry (Option 4)

**Mechanism.** When `MissingRequiredEvidenceError` fires (dependent dispatched before upstream committed), retry the callback before `DurableStageExecutor.run`/`claim()` with a **bounded durable retry/quarantine** policy — no polling loop, no callback resubmission. `MissingRequiredEvidenceError` remains fail-closed; no claim, `stage_run`, side effect, or completion occurs until exactly one canonical COMPLETE upstream record is selected. This requires a new DD defining retry/timeout/quarantine/idempotency semantics (debugger `living-aqua-weasel` §3(a) and §4 exact amended-step wording).

**Evidence / technology validation.**
- Debugger `living-aqua-weasel` §3(a): pre-claim wait is "only compatible with claim-before-side-effect if the wait occurs before `DurableStageExecutor.run()` / `StageRunRepository.claim()`"; but "repeated database checks are polling, explicitly prohibited; synchronous waiting consumes a worker slot; the callback may exceed Hatchet execution/schedule timeouts; `MissingRequiredEvidenceError` currently has no application-level retry path."
- Official Hatchet retry/timeout docs (checked 2026-08-29): task-level `retries`/`backoff_factor` exist (`docs.hatchet.run/v1/retry-policies`), but execution timeout defaults to 60s and scheduling timeout to 5m (`docs.hatchet.run/v1/timeouts`); a bounded pre-claim wait must fit inside these or use `refreshTimeout`.
- Official Hatchet durable-task docs (checked 2026-08-29): "you should _not_ directly access your database or an external API, or generate random numbers and use them for control flow inside of a durable task" (`docs.hatchet.run/v1/durable-tasks`) — a DB-backed pre-claim wait inside a durable callback is contrary to the documented durable-task contract unless modeled as a proper durable wait.
- Cross-engine polling anti-pattern (Temporal community + docs, cited in Critique for the evidence ranking): in-workflow polling floods history and is an anti-pattern; retries/heartbeats belong in activities (`community.temporal.io/t/polling-in-workflow-vs-activity/453`, `docs.temporal.io/design-patterns/polling`).

### Technology-currency validation summary (checked 2026-08-29)

| Choice | Source | Status |
|---|---|---|
| `hatchet_sdk==1.38.1` | installed package; PyPI; docs.hatchet.run | current pin, maintained; durable/DAG surfaces verified in installed source |
| server `v0.105.2` | `ghcr.io/hatchet-dev/hatchet/hatchet-engine:v0.105.2` | pin per blocker DD; durable-slot assignment on this server is an **open risk** (complexity review B1) |
| `workflow.durable_task(name, parents=[...])` | installed SDK `runnables/workflow.py:1701-1814`; docs `/v1/directed-acyclic-graphs` | supported, native DAG barrier |
| `TriggerWorkflowOptions.parent_id` as barrier | installed SDK `types/trigger.py`; hosted run 33240528692 | **disproven** — metadata field 4, no gating |
| `TriggerWorkflowOptions.parent_step_run_id` | installed SDK `clients/admin.py:227` → field 5 | **unproven, singular** — requires hosted probe |
| DAG durable tasks | docs `/v1/durable-tasks`, `/cookbooks/durable-tasks-vs-dags` | supported; durable tasks documented as async (sync-durable deprecation warning) |

---

## 3. Turn 2 — ## Critique

*Role: rnd-counter-ideator (inline). Task: for each approach, search for documented failures,
postmortems, migration regrets, or acknowledged limitations; explain why each applies to THIS
context; rank citations by evidence tier; flag approaches that do not survive scrutiny; verify
technology/version currency rather than accepting proposal claims.*

### Evidence-tier scale used in this log

- **T1 — Hosted execution evidence** (our own runs / retrieved artifacts): run 33229130339, run 33240528692, `/tmp/r40528/diag-final/*`, DB dumps.
- **T2 — Official maintainer documentation / installed pinned SDK source** (docs.hatchet.run, installed `hatchet_sdk` source, netns DD, CONTRACTS.md).
- **T3 — Independent practitioner postmortems / community guidance** (Temporal community forum, production write-ups, other-OSS commit/PR history).
- **T4 — General opinion / hot takes** (avoided as evidence).

### Critique of Approach 1 (single workflow DAG)

1. **AT-18 conflict is real and load-bearing.** Netns DD AT-18 reads as per-stage independent `client.durable_task` registration (librarian warning table). Option 1 needs an explicit AT-18 reconciliation/amendment, and the amendment must not weaken the hosted assertion (`v1_task.is_durable=true` for every latest version, exact `umd-<stage>` names). **Applies directly.**
2. **Readiness semantics break the current contract.** `WorkerHandle.is_ready()` and `cli.py` count `len(registered_workflows) == len(STAGE_ORDER)`. One workflow object → count is 1, not 9. The C6 readiness line wording ("registered {N} Hatchet workflows") and the engine proof must switch to task-count semantics. **Applies directly** — a real contract change, not cosmetic.
3. **Single-workflow row granularity is unverified.** Does a workflow with 9 durable tasks surface one `WorkflowVersion` with 9 `v1_task` rows, each with a stable readable id and `is_durable=true`? The librarian open-question list flags this; the hosted evidence is all from the current per-stage registration shape. **Must be proven at spike** — accepting on faith is exactly the class of error that produced the last blocker. **Applies directly.**
4. **Durable-slot assignment on v0.105.2 is unproven** (complexity review B1). `is_durable=true` alone is not proof of durable scheduling; the DAG approach still depends on durable slots assigning. **Applies directly to this context.**
5. **DAG durable tasks are documented as async; our callbacks are sync.** The migration guide says "durable tasks should be async"; `log-worker.txt:5-13` carries the sync-durable warning. If `workflow.durable_task` requires async handlers on this pin, Option 1 collides with the blocker DD's explicit deferral of async conversion ("sync-durable deprecation on this pin is tracked forward-compatibility debt; async conversion is deferred"). **Applies directly — flag for human decision (HQ2).**
6. **Shared input routing.** All tasks in a DAG receive the same workflow input. Each `umd-<stage>` callback must verify `input.stage == its bound stage`; otherwise cross-task execution is possible. Mitigable, but a new invariant. **Applies directly, mitigable.**
7. **Selective rerun semantics change shape.** Task.md DoD requires per-stage selective rerun. With one DAG, a rerun re-submits the whole workflow; unaffected stages must dedupe via executor idempotency (P2-S11 replay-marked observations) and only invalidated descendants rekey/re-execute. This is consistent with rows 19–21 but must be explicitly proven; a human may need to accept this scheduler-level shape (HQ4).

**Does it survive?** **Provisional yes** — it is the only approach with a verified native barrier mechanism, but only after: spike proof of row granularity/durability, AT-18 amendment, task-count readiness, and async-handler resolution.

### Critique of Approach 2 (independent registrations + parent_step_run_id)

1. **`parent_id` is disproven, not merely unproven.** Run 33240528692: all 45 hosted `v1_task` rows had null `parent_task_external_id`/`parent_task_id`; dependents dispatched before upstream committed → `MissingRequiredEvidenceError` cascade (debugger `living-aqua-weasel` §1; T1 hosted evidence). **Dispositive.**
2. **`parent_step_run_id` is singular and unproven.** It maps to field 5 (`parent_task_run_external_id`), but "neither the SDK source nor this run proves that it gates external workflow dispatch… It is also singular and cannot obviously represent multiple direct parents." It must not be treated as a barrier without a targeted v0.105.2 hosted persistence-and-dispatch probe (`living-aqua-weasel` §1). Multi-parent stages (e.g. ENTITY_RESOLUTION with two upstreams) cannot be expressed with a single field. **Applies directly and is likely fatal for multi-parent edges.**
3. **The runner only threads the latest direct dependency.** `runner.py:255-258` — even a working single-parent mechanism would not express all edges (debugger §5, librarian warning). **Applies directly; independently blocks this approach.**
4. **No production system cited using this as a cross-workflow barrier** — it is an unverified field, not a documented pattern. No T2/T3 evidence exists. **Evidence gap, not merely risk.**

**Does it survive?** **Conditional only** — survives only if a hosted probe proves (a) persisted non-null `parent_task_external_id` for every dependent, (b) no `SENT_TO_WORKER`/`ASSIGNED`/`STARTED` before upstream durable completion, and (c) multi-parent representation. If any fails, the debugger directs: record unsatisfiable and choose Approach 1 or propose an approved SDK/server pair change.

### Critique of Approach 3 (lift submission-time snapshot)

1. **It is explicitly rejected by the authoritative plan.** P2-S14 line 105: "never (b) a submission-time snapshot"; plan line 81 rejects fallback to snapshot architecture. Lifting requires a new DD/amendment — introducing it as an implementation detail is disallowed. **Dispositive process block.**
2. **It does not fix the observed failure mode.** The failure is early dispatch (dependents assigned before upstream completion). A snapshot taken at submission time captures the same incomplete upstream state that caused the race — the evidence would be frozen-empty. The debugger's `unexpected-blush-bass` fix list includes snapshot as one alternative, but the plan's own acceptance (9 canonical keys, stable evidence, no timing-dependent material) is achieved by (a)+(c), not by snapshot.
3. **Snapshot staleness is a documented production hazard.** "A snapshot captured early goes stale, and writing it back clobbers a concurrent update" (Temporal-in-production, 2026-07-17, T3). Freezing evidence at submission conflicts with canonical lineage selection (c), descendant rekeying after `InvalidationPlanner` reruns, and `DagUniverseGate` drain — all L16-protected provenance invariants. **Applies directly.**
4. **It would not eliminate the second BASIC key** without also changing idempotency material semantics (the duplicate callback computed a *different valid* key because its evidence differed); a snapshot would freeze *a* key but not prove correctness, and would interact badly with cross-job replay attribution (P2-S11). **Applies directly.**

**Does it survive?** **No — rejected.** Requires a reversal of an explicit plan rejection, does not address the root cause (early dispatch), and introduces stale-evidence risk that violates canonical selection invariants.

### Critique of Approach 4 (pre-claim bounded durable retry)

1. **"Retry" degenerates to polling, which is explicitly prohibited.** Plan K and the blocker DD forbid polling and callback resubmission. A bounded retry that re-checks the DB *is* a poll (debugger §3(a): "repeated database checks are polling, explicitly prohibited"). **Direct conflict with L12/L13 and plan text.**
2. **Worker-slot and timeout physics.** Synchronous waiting consumes a worker slot; the callback may exceed Hatchet execution/schedule timeouts (defaults 60s/5m per docs, checked 2026-08-29). `MissingRequiredEvidenceError` has no retry path today; it would need a new DD defining retry/timeout/quarantine/idempotency semantics — "cannot be called a simple reuse of existing retry/quarantine behavior" (debugger §3(a)). **Applies directly.**
3. **Contradicts the documented durable-task contract.** Official docs: do not directly access the database "inside of a durable task" (`docs.hatchet.run/v1/durable-tasks`). A pre-claim DB wait in the callback violates the durable-execution determinism contract. **Applies directly.**
4. **Cross-engine precedent.** Temporal guidance: polling from workflow code is an anti-pattern (history bloat); polling belongs in activities with heartbeats (`community.temporal.io/t/polling-in-workflow-vs-activity/453`, `docs.temporal.io/design-patterns/polling` — T3/T2). In Hatchet terms, there is no activity/durable-wait boundary in the current sync callback shape. **Applies as corroborating T3 evidence.**
5. **It leaves the barrier burden on application code.** Even if bounded, it converts a scheduler-guaranteed ordering into an application-level wait — exactly what the mandatory "native barriers" (P2-S14 (a)) exist to avoid, and it weakens the "cannot be assigned before that point" guarantee the plan demands. **Applies directly.**

**Does it survive?** **Fallback only** — survives only if Approach 1 proves unworkable (e.g. durable slots do not assign and no engine-config fix exists), and only with a new DD defining the bounded semantics. It cannot be the primary selection.

### Approach disposition summary

| Approach | Verdict | Primary reason |
|---|---|---|
| 1 — Single workflow DAG | **Provisional survive** (needs spike + AT-18 amendment + async resolution) | only verified native barrier; multiple open proof obligations |
| 2 — Independent + parent_step_run_id | **Conditional** (hosted probe or dead) | singular/unproven; runner loses edges; parent_id disproven |
| 3 — Submission-time snapshot | **REJECTED** | explicit plan rejection; doesn't fix early dispatch; stale-evidence hazard |
| 4 — Pre-claim bounded retry | **Fallback only** | polling prohibition; slot/timeout physics; DB access in durable callback |

---

## 4. Turn 3 — ## Refined Approaches

*Role: rnd-ideator (resume, inline). Task: refine surviving approaches to address valid
criticisms; drop approaches that do not survive and explain why; for each refined approach,
find a real system using a similar refined pattern; revalidate any technology choice that
changed or remains consequential.*

### Refined Approach 1′ — Single workflow DAG with AT-18 reconciliation, task-count readiness, stage-asserted input routing

Addresses every Critique point:

1. **AT-18 reconciliation is explicit, not silent.** Propose a wording amendment to the netns DD AT-18 (requires DD-author/owner approval): "every release `umd-<stage>` task is registered via the pinned SDK durable registration surface (`workflow.durable_task(name=f'umd-{stage}')` within the single `umd-decompose` workflow, or standalone `client.durable_task`), and hosted DB/engine evidence asserts `v1_task.is_durable=true` for every latest `umd-<stage>` version." The hosted assertion is unchanged in letter and spirit; only the registration surface wording is generalized.
2. **Task-count readiness.** `WorkerHandle.registered_workflows` is replaced by `registered_tasks` (the 9 durable task objects); `is_ready()` and `cli.py` count tasks; the C6 readiness line becomes "worker ready: registered {N} Hatchet tasks (candidate, pending live validation)"; exact-count mismatch fails closed. CONTRACTS §62's `WorkerHandle` shape is preserved; only counting semantics change (flag for PatternEnforcer).
3. **Spike-first proof obligations (new P2 step before implementation):** (i) single workflow with 9 `workflow.durable_task` yields 9 `v1_task` rows with stable readable ids and `is_durable=true`; (ii) DAG durable tasks accept the sync `(input, ctx)` handler on 1.38.1 (or record the async requirement); (iii) `eviction_policy=None` is accepted on `workflow.durable_task`; (iv) parent edges derived solely from `STAGE_DEPENDENCIES` are topologically registered (parents before children).
4. **Stage-asserted input routing.** Each `umd-<stage>` callback asserts `input.stage == stage_name` before running work; mismatch = `ConfigurationError` (absent/config failure, never fake completion). Shared `UmdStageInput` remains the A2′ validator.
5. **Selective rerun via re-submit + executor dedupe.** Re-submitting the DAG for a rerun/correction re-runs the workflow; unaffected stages replay-dedupe via `StageRunRepository.claim` (one canonical key) and emit at most one replay-marked observation (P2-S11); invalidated descendants rekey via `InvalidationPlanner` lineage and re-execute. This is the scheduler-level shape that must be proven hosted (HQ4).
6. **Canonical evidence selection (c) is retained** as the in-callback correctness backstop (fail-closed `canonical_evidence_refs`), independent of the native barrier.

**Real-system refinement analog (cited).** PostHog's production Temporal DAG executor (`execute_dag.py`) demonstrates the refined pattern of declarative DAG + per-level dispatch + dedupe-safe rerun (T3). Hatchet's own cookbook explicitly recommends DAGs for "document processing" pipelines with mixed durable-task nodes (T2).

**Technology revalidation (checked 2026-08-29):** installed SDK `runnables/workflow.py:1701-1814` confirms `durable_task(name, parents=[...], eviction_policy=...)` exists; docs `/v1/directed-acyclic-graphs` confirm durable DAG semantics; server v0.105.2 pin unchanged. Remaining unverified items are explicitly spike-gated, labeled **provisional**.

### Refined Approach 2′ — Independent registrations only if hosted probe passes (conditional, defined)

The probe (exact plan-mandated shape): submit a parent and dependent through `parent_step_run_id`, query persisted `v1_task.parent_task_external_id` and `v1_task_events_olap` transitions, and prove (a) field maps to field 5, (b) child is not `SENT_TO_WORKER`/`ASSIGNED`/`STARTED` before upstream durable `stage_run status=complete` + `StageCompleted` exist, (c) all `STAGE_DEPENDENCIES` edges are expressible. Runner must submit **every** direct dependency edge (fix `runner.py:255-258`), not the latest one. If the probe fails on any item → record unsatisfiable and select Approach 1′ or propose an approved SDK/server pin change (drain/rekey per blocker DD).

**Real-system analog:** none found — no production system uses `parent_step_run_id` as a cross-workflow dispatch barrier on this server version; this absence is itself evidence (T3 gap).

### Approach 3 disposition (from Critique)

**Dropped.** Reason: explicit P2-S14 rejection; does not address early dispatch (snapshot at submission captures empty upstream); stale-snapshot hazard (T3); conflicts with canonical selection/invalidation/DAG-universe invariants (L16). Documented, not silently dropped.

### Approach 4′ — Pre-claim bounded durable retry (fallback, defined but not selected)

Retained only as a documented fallback if 1′ is blocked by durable-slot failure or async-handler impossibility **and** engine-config investigation fails. If activated, requires a new DD defining: wait strictly before `DurableStageExecutor.run`/`claim()`; bounded attempts + quarantine; `MissingRequiredEvidenceError` stays fail-closed; no polling loop/resubmission; timeout fit (or `refreshTimeout`) within Hatchet defaults; hosted proof of timeout/retry/restart/reclaim/idempotency (debugger §4 exact wording).

---

## 5. Turn 4 — ## Surviving Concerns

*Role: rnd-counter-ideator (resume, inline). Task: assess whether the refinements actually
address the Turn-1 critique; identify what still does not work and what risks persist.*

The refinements address the named critique items (AT-18 wording, readiness counting, spike
obligations, stage-asserted routing, selective-rerun shape). The following concerns survive
and are **not** resolved by refinement wording alone:

1. **Durable-slot assignment on v0.105.2 remains unproven** (B1). `is_durable=true` rows exist (`engine-visible-durability.txt` shows all nine `umd-*|t|5`), but hosted run 33229130339 produced zero assignments. Approach 1′ still depends on durable slots assigning; if they do not, 1′ fails and only engine-config investigation → 4′ remains. **This is the top surviving blocker risk.**
2. **Single-workflow row granularity / `v1_task` mapping is unverified.** All hosted `v1_task` evidence comes from the current per-stage registration shape. The spike must prove 9 rows, stable readable ids, `is_durable=true`, latest-version scoping — otherwise AT-18's hosted assertion and the A3′ exact-name probe cannot be satisfied. **Survives until spike.**
3. **Sync-durable vs async-handler requirement is unresolved.** If `workflow.durable_task` DAG tasks require async handlers on 1.38.1, Approach 1′ collides with the blocker DD's explicit deferral of async conversion. This is a **human decision** (HQ2), not something a spike silently resolves, because it touches the deferred async-conversion debt.
4. **Readiness/C6 wording change needs contract-level approval.** The C6 line and `WorkerHandle` counting semantics change; CONTRACTS §62 is binding and the PatternEnforcer must approve the shape. Not a code-only change. **Human/pattern-enforcer gate.**
5. **AT-18 amendment must not weaken the hosted assertion.** The reconciliation must preserve `v1_task.is_durable=true` per latest version and exact `umd-<stage>` names; a wording loosening that lets a single durable workflow hide a non-durable task is a gate weakening (L13/L14). **Must be drafted carefully; reviewed against netns DD.**
6. **Multi-parent edges must be fully expressed.** `runner.py:255-258` still picks the latest direct dependency only; Approach 1′ fixes this by construction (DAG parents list), but any remnant of the per-stage submission path must be removed, not repaired. **Requires deleting the parent_id threading path.**
7. **Assignment/runtime proof contract must be corrected regardless of option.** `v1_task_runtime.worker_id=0` / empty runtime is not authoritative; the corrected proof correlates `v1_task_events_olap` (`SENT_TO_WORKER`/`ASSIGNED`/`STARTED`) + `v1_tasks_olap.worker_id` + `Worker.isActive`, and keeps failing closed without authoritative assignment evidence (debugger §5; P2-S13 amendment). **Applies to every option; survives.**
8. **The sync-durable warning is a forward-compatibility debt, not a today-blocker.** `log-worker.txt:5-13` warns; blocker DD defers async conversion. Approach 1′ must not silently convert; it must either prove sync DAG handlers work on the pin or escalate (HQ2).

---

## 6. Turn 5 — ## Implementation Patterns

*Role: rnd-improver (inline). Task: based on the surviving approaches, propose concrete
implementation patterns; for each, cite real-world best practices and production
implementations; cover data-flow, state management, error handling, testing, key library
choices; validate each key library/framework/version against official/maintainer docs.*

*Scope: the surviving primary is Approach 1′; patterns below are written for 1′, with 4′
conditional patterns marked `[FALLBACK-4′]`. All technology validated 2026-08-29 against
installed SDK 1.38.1 source + docs.hatchet.run.*

### Pattern P1 — Single-workflow DAG registration (data-flow + topology)

- One workflow object: `wf = client.workflow(name="umd-decompose", input_validator=UmdStageInput)`; then for each stage in `STAGE_ORDER`: `task_obj = wf.durable_task(name=f"umd-{stage}", parents=[task_objs_of(STAGE_DEPENDENCIES[stage])], input_validator=UmdStageInput, eviction_policy=None)(handler)` — parents defined before children (installed SDK `runnables/workflow.py:1701-1814`).
- Submission: one workflow run per job carrying the full run context (`job_id`, `source_id`, `dag_universe`, per-stage `manifest`); the DAG schedules all nine tasks natively; each callback reads `input.manifest`, asserts `input.stage == bound stage`, then flows to `DurableStageExecutor`.
- Remove the `parent_id` threading in `runner.py`/`_real_submit_workflow_run` entirely — no `TriggerWorkflowOptions` parent fields are used for the barrier.
- **Real-world basis:** Hatchet DAG docs (`/v1/directed-acyclic-graphs`) — ETL/document-processing DAG with parent-gated dispatch; PostHog Temporal DAG executor (`execute_dag.py`) — production DAG with per-level dispatch (T3).

### Pattern P2 — Canonical evidence selection as the correctness backstop (state management)

- Retain `canonical_evidence_refs(source_id, dag_universe, segment_id, stage_name)` in `job_repository.py` (selects exactly one COMPLETE upstream record per edge, fail-closed on missing/ambiguous; already implemented P2-S9).
- Callback flow: cancel-check (store status) → canonical evidence resolution → `DurableStageExecutor.run` (claim-before-side-effect) → JSON-safe ack. Unchanged authority (CONTRACTS §33).
- **Real-world basis:** CONTRACTS §33/§35; debugger `unexpected-blush-bass` (stable keys across duplicate/restart timing require deterministic evidence selection).

### Pattern P3 — Truthful task-level readiness (state + gate)

- `WorkerHandle` exposes `registered_tasks` (9 durable task objects); `is_ready()` true only when complete non-empty registration of every canonical stage AND a real executor is bound (existing fail-closed semantics, re-pointed at tasks).
- `cli.py` counts only `registered_tasks`, fails before readiness on exact-count mismatch vs `STAGE_ORDER`; C6 line updated to task wording (pending contract approval, HQ5).
- **Real-world basis:** CONTRACTS §62; blocker DD (truthful readiness, no `len(work_registry)` fallback).

### Pattern P4 — Corrected assignment/runtime proof (evidence)

- Proof queries correlate: `v1_task_events_olap` (`SENT_TO_WORKER`/`ASSIGNED`/`STARTED`) + `v1_tasks_olap.worker_id` + `Worker.isActive`/`isPaused` + tenant/partition identity agreement; `v1_task_runtime.worker_id` is diagnostic-only and never proof of absence (debugger §5).
- Latest-version durability: `MAX(WorkflowVersion.version)` per `Workflow.name`, `bool_and(is_durable)=t`, exact `umd-<stage>` names.
- **Real-world basis:** debugger `living-aqua-weasel` §5; P2-S13 amendment; `engine-visible-proof.sh` Check 4 model.

### Pattern P5 — Testing strategy (spec-first, hosted)

- Hermetic: SDK-shaped `Standalone.mock_run(input=UmdStageInput(...), parent_outputs=...)` reaches the executor; one-arg/v0 negatives fail; local binding-shape tests renamed honestly.
- Hosted: delayed-parent proof from `v1_task_events_olap` (dependent not `SENT_TO_WORKER`/`ASSIGNED`/`STARTED` before upstream durable `stage_run status=complete` + `StageCompleted`); exact 9 canonical keys per single submission and per immediate duplicate; cross-job replay: nine replay-marked observations, zero side effects, no extra canonical keys; scoped per-job markers, never global totals.
- **Real-world basis:** Hatchet docs (`/v1/durable-tasks` determinism; `/v1/error-handling/retry-policies` idempotency warning — retries require idempotent operations); Plan K P2-S12/P2-S13.

### Pattern P6 — `[FALLBACK-4′]` Pre-claim bounded durable retry (error handling)

- If activated: wait strictly before `DurableStageExecutor.run`/`claim()`; bounded attempts with `retries`/`backoff` or explicit quarantine; `MissingRequiredEvidenceError` fail-closed; no polling/resubmission; hosted proof of timeout/retry/restart/reclaim/idempotency (debugger §4). Requires a new DD; **not** implemented in the primary path.

### Key library choices (validated)

| Library | Version | Validation | Fit |
|---|---|---|---|
| `hatchet-sdk` | ==1.38.1 | installed source; PyPI; docs | sole scheduler (L10); DAG/durable surfaces verified |
| `pydantic` | v2 (project pin) | installed with SDK | `UmdStageInput` validator boundary (A2′) |
| `hatchet server` | v0.105.2 | engine image; docs | pinned; durable-slot assignment is a named risk (B1) |
| No new libraries | — | — | canonical selection + executor already implemented |

---

## 7. Turn 6 — ## Pattern Risks

*Role: rnd-counter-improver (inline). Task: for each pattern, search for edge cases,
integration risks, library-specific gotchas, and cross-pattern interaction failures; explain
trigger conditions and whether they match our use case; cite GitHub issues, library docs, and
production incidents; check whether reported library risks apply to the current supported
version and use case; surface better-fit alternatives when evidence warrants.*

### Risk R1 — [P1] Single-workflow row granularity mismatch
**Trigger:** engine creates fewer/more `v1_task` rows than nine, or `is_durable` not per-task, or readable ids not stable. **Match:** high — this is the load-bearing AT-18/A3′ assertion surface. **Evidence:** no hosted data exists for the DAG shape (librarian open-question). **Mitigation:** spike before implementation; hosted latest-version durability check must see 9 rows.
### Risk R2 — [P1] Durable-slot assignment failure on v0.105.2 (B1)
**Trigger:** tasks stay QUEUED with zero assignments (run 33229130339 failure mode). **Match:** high — the previous run's exact failure. **Evidence:** `v1-task-summary.txt` (45 queued, 0 assigned, 12 OLAP active); complexity review B1. **Mitigation:** investigate engine slot configuration first; hosted QUEUED→ASSIGNED/RUNNING poll fail-closed; if unresolved → escalate to 4′ (HQ3).
### Risk R3 — [P3] Readiness/C6 contract change
**Trigger:** counting tasks vs workflows breaks `test_cli_deploy_phaseE.py` expectations and C6 grep gates (`wait-for-worker.sh` greps "registered {N} Hatchet workflows"). **Match:** high — the C6 line is a hosted gate anchor. **Mitigation:** coordinated wording change + PatternEnforcer/contract approval (HQ5); keep the "candidate, pending live validation" suffix.
### Risk R4 — [P1] Shared-input routing bug
**Trigger:** a task's handler ignores `input.stage` and executes the wrong stage's work. **Match:** medium-high — all DAG tasks receive the same workflow input. **Mitigation:** stage-asserted routing with `ConfigurationError` on mismatch; covered by hermetic negative tests.
### Risk R5 — [P1] Sync-durable / async-handler requirement on DAG tasks
**Trigger:** `workflow.durable_task` on 1.38.1 requires async handlers; current callbacks are sync; warning in `log-worker.txt:5-13`. **Match:** high — directly collides with blocker DD's deferred async conversion. **Evidence:** migration guide "durable tasks should be async"; durable-task docs. **Mitigation:** spike; if forced async → human decision HQ2 (scoped async DD vs fallback); do not silently convert.
### Risk R6 — [P2] Cross-pattern: canonical selection + DAG barrier interaction
**Trigger:** native barrier passes but canonical selection still fail-closes (e.g. ambiguous COMPLETE rows at identical `created_at`); or barrier lets a dependent see a replayed (non-canonical) upstream. **Match:** medium — `AmbiguousRequiredEvidenceError` is a designed fail-closed state. **Mitigation:** keep deterministic ordering + tie-break; hosted delayed-parent proof exercises the joint path.
### Risk R7 — [P2/P5] Selective-rerun double-execution window
**Trigger:** a re-submitted DAG re-runs all tasks; between re-submission and executor claim, an unaffected stage could momentarily re-execute side effects if claim were absent. **Match:** medium — mitigated by claim-before-side-effect (CONTRACTS §33) and replay attribution (P2-S11). **Mitigation:** hosted proof that unaffected stages produce zero new canonical rows and zero side effects after replay (P2-S12 acceptance).
### Risk R8 — [P4] Proof-query false negative/positive
**Trigger:** correlating `v1_tasks_olap.worker_id` but querying a non-authoritative projection, or treating `v1_task_runtime` emptiness as "no assignment". **Match:** high — the `worker_id=0` concern is exactly this. **Evidence:** debugger §5; `engine-verdicts.txt` FAIL on empty runtime. **Mitigation:** corrected correlation contract (P4) is mandatory in every option.
### Risk R9 — [P1] `eviction_policy` param on `workflow.durable_task`
**Trigger:** param signature differs from `client.durable_task` (installed SDK shows `eviction_policy` on `durable_task` but not verified on the workflow variant at spike depth). **Match:** medium — AT-18 currently pins `eviction_policy=None`. **Mitigation:** spike verifies signature; record in amendment.
### Risk R10 — [P2] DB access inside durable callback (documented contract violation)
**Trigger:** durable task determinism rules prohibit direct DB access between checkpoints; our callback resolves evidence from Postgres before claim. **Match:** high for `[FALLBACK-4′]`; for the primary DAG path the evidence resolution is a bounded read before side effects, and DAG tasks are not the "durable execution primitives" model — but this must be explicitly reconciled in the amendment (docs `/v1/durable-tasks`). **Mitigation:** document the boundary; if `workflow.durable_task` imposes durable-execution determinism, route stage work through the executor (already the case) and keep evidence resolution idempotent and read-only.

**Cross-pattern interaction note:** R2 × R5 is the dominant risk pair — if durable slots do not assign **and** DAG tasks require async, Option 1′ fails twice and the fallback path (4′) activates; this is why HQ2/HQ3 are human gates, not code gates.

---

## 8. Turn 7 — ## Final Patterns

*Role: rnd-improver (resume, inline). Task: address the risks identified; for each —
mitigable → describe mitigation with supporting evidence; fundamental → acknowledge; refine
the patterns; revalidate affected technology and preserve source/check-date evidence.*

### Final Pattern F1 — [from P1] Single-workflow DAG with spike-gated registration
- **R1 mitigation:** mandatory pre-implementation spike proving 9 `v1_task` rows, stable readable ids, latest-version `is_durable=true`; hosted AT-18 assertion unchanged.
- **R4 mitigation:** stage-asserted routing enforced with `ConfigurationError`; hermetic negative test (`test_stage_assertion_mismatch_fails_closed`).
- **R9 mitigation:** spike records exact `workflow.durable_task` signature incl. `eviction_policy`; amendment pins the verified signature.
- **R5 mitigation/acknowledgment:** spike tests sync handler acceptance; if async is required, **stop and escalate (HQ2)** — no silent conversion. The blocker DD's deferred-async decision is preserved unless a human approves a scoped change.

### Final Pattern F2 — [from P2] Canonical evidence selection + claim-before-side-effect
- **R6/R7 mitigation:** retain deterministic canonical ordering, fail-closed ambiguity, claim-before-side-effect, replay attribution; hosted delayed-parent + duplicate + cross-job replay proofs (P2-S12/S13) are the acceptance evidence; no changes to executor ownership.

### Final Pattern F3 — [from P3] Truthful task-level readiness
- **R3 mitigation:** coordinated C6 wording change with PatternEnforcer + contract approval (HQ5); readiness remains fail-closed; `wait-for-worker.sh` grep anchor updated in lockstep; no fabrication path.

### Final Pattern F4 — [from P4] Corrected assignment/runtime proof
- **R8 mitigation:** mandatory correlation contract (`v1_task_events_olap` + `v1_tasks_olap.worker_id` + `Worker.isActive`); `v1_task_runtime` diagnostic-only; fail-closed absence handling. This is option-independent and applies to the hosted rerun regardless of final choice.

### Final Pattern F5 — [from P5] Spec-first testing with hosted delayed-parent proof
- **R2 mitigation:** hosted QUEUED→ASSIGNED/RUNNING poll fail-closed (run 33229130339 failure mode) is the release gate; if assignment fails after bounded polling, stop and investigate engine slot config (HQ3).
- Scope discipline: per-job markers, exact 9/9/9 and 6-row replay evidence, zero global-total proofs.

### Final Pattern F6 — [FALLBACK-4′] Pre-claim bounded durable retry (unactivated)
- **R10 acknowledgment:** if activated, the DB-backed wait conflicts with the documented durable-task determinism contract; the new DD must define the boundary (read-only idempotent evidence resolution before claim; bounded attempts; no polling/resubmission). **Fundamental limitation, acknowledged — this is why it is fallback, not primary.**

### Technology revalidation (final, checked 2026-08-29)
- `hatchet_sdk==1.38.1` + server `v0.105.2`: unchanged pin; DAG/durable surfaces verified in installed source; docs current.
- **Best-fit rationale (not "newest is best"):** the pin is fixed by the blocker DD and netns DD; Option 1′ uses the *already-installed* SDK's native DAG barrier — no upgrade, no new dependency, no second scheduler. A pin change is only considered if the spike proves the pinned pair cannot express the required barrier (then a new DD + drain/rekey per blocker DD).
- Remaining **provisional** labels: single-workflow row granularity (spike), durable-slot assignment on v0.105.2 (hosted), async-handler requirement (spike), `workflow.durable_task` `eviction_policy` signature (spike), `parent_step_run_id` gating (probe, option 2′ only).

---

## 9. Turn 8 — ## Open Risks & Human Questions

*Role: rnd-counter-improver (resume, inline). Task: assess whether the Improver's refinements
address the Turn-1 pattern-risk findings; identify unresolved risks; surface questions that
genuinely require human judgment; flag unvalidated technology choices as provisional.*

### Unresolved risks (persist after F1–F6)

1. **UR1 — Durable-slot assignment (R2)** is mitigated only by fail-closed polling and engine-config investigation; the underlying assignment behavior on v0.105.2 is not proven by any pattern. **Severity: BLOCKING if it fails.**
2. **UR2 — Row granularity (R1)** is spike-gated; until the spike, AT-18 hosted proof for the DAG shape is unvalidated. **Severity: HIGH.**
3. **UR3 — Async-handler requirement (R5)** is escalated, not resolved; if async is forced, the entire pattern set changes shape and the deferred async-conversion decision is reopened. **Severity: HIGH (human).**
4. **UR4 — AT-18 amendment drafting** must not weaken the hosted assertion; a poorly worded amendment is a gate-weakening violation (L13/L14). **Severity: MEDIUM-HIGH (human review).**
5. **UR5 — C6/readiness wording change** touches a hosted grep anchor and CONTRACTS §62 shape. **Severity: MEDIUM (contract gate).**
6. **UR6 — Canonical-selection ambiguity edge** (`AmbiguousRequiredEvidenceError` at identical `created_at`) remains a designed fail-closed state; no mitigation other than the existing deterministic ordering. **Severity: LOW-MEDIUM.**
7. **UR7 — Proof-query correlation (R8)** is mandatory but adds a hosted-evidence surface that can false-FAIL if the OLAP projection is not authoritative on v0.105.2. **Severity: MEDIUM (test-harness risk, not product risk).**

### Human-judgment questions (substantive, evidence-contextualized)

- **HQ1 — AT-18 interpretation.** Does "every canonical umd-<stage> registered as its own durable task" permit one workflow containing nine named `durable_task`s, or must each stage remain an independently registered/triggerable task? **Context:** netns DD AT-18 wording is binding; Option 1 requires the first reading; the librarian marks R19 "interpretation in question". **Recommendation (evidence-based):** accept the first reading *only* with an explicit AT-18 wording amendment that preserves `v1_task.is_durable=true` per latest version and exact `umd-<stage>` names, and with spike proof of 9 rows.
- **HQ2 — Sync-durable vs async.** If the pinned SDK's DAG `durable_task` requires async handlers, do we (a) approve a scoped async conversion via a new DD, (b) keep the deferral and fall back to Option 4′, or (c) investigate a pin change? **Context:** blocker DD explicitly defers async conversion; sync-durable warning observed in hosted worker log; migration guide says durable tasks should be async. **Recommendation:** prefer (a) as a scoped DD if the spike proves async is required and durable slots assign; otherwise (b).
- **HQ3 — Durable-slot failure path.** If tasks remain QUEUED with zero assignments on v0.105.2, is the authorized response limited to engine-slot-config investigation, or may R&D propose an SDK/server pin change (with drain/rekey and revalidation)? **Context:** run 33229130339's exact failure mode; blocker DD limits changes without approval. **Recommendation:** engine-config first; pin change only with a new DD after config investigation fails.
- **HQ4 — Selective-rerun scheduler shape.** Is "re-submit the DAG; unaffected stages replay-dedupe via idempotency + replay-marked observations; invalidated descendants rekey" acceptable proof for Task.md rows 19–21, or must per-stage independent rerun remain possible at the scheduler level? **Context:** DoD requires cancel/retry/selective rerun; P2-S11 replay attribution already implements the observation model. **Recommendation:** accept with hosted proof of 9 canonical keys / zero post-replay side effects.
- **HQ5 — Readiness wording.** Approve changing the C6 line to task-count wording ("registered {N} Hatchet tasks (candidate, pending live validation)") with the hosted `wait-for-worker.sh` anchor updated in lockstep? **Context:** CONTRACTS §62; truthful-readiness gate. **Recommendation:** approve as a coordinated wording change; no semantic weakening.

### Provisional / unvalidated technology claims (must be resolved before implementation)

- Single-workflow → 9 `v1_task` row granularity (spike).
- Durable-slot assignment on v0.105.2 (hosted; B1).
- Async-handler requirement of `workflow.durable_task` on 1.38.1 (spike).
- `workflow.durable_task` `eviction_policy` signature parity with `client.durable_task` (spike).
- `parent_step_run_id` cross-workflow gating + multi-parent representation (hosted probe; option 2′ only).

---

## 10. Option matrix and evidence-ranked recommendation

### Option matrix

| Criterion | O1 single DAG | O2 indep + parent_step_run_id | O3 snapshot | O4 pre-claim retry |
|---|---|---|---|---|
| Native barrier verified on pinned pair | **YES** (docs T2 + SDK source) | **NO** — unproven/singular (T1/T2) | N/A (not a barrier) | NO — application-level |
| Addresses early-dispatch root cause | **YES** (scheduler-gated) | Maybe, if probe proves | **NO** (snapshot at submission = empty upstream) | Partial (waits, but violates polling ban) |
| Multi-parent edges expressible | **YES** (parents list) | **NO** (singular field; runner drops edges) | N/A | N/A |
| AT-18 fit | Reconcile via amendment | Fits literal wording | Fits literal wording | Fits literal wording |
| Readiness/callback rows | Task-count (change) | Workflow-count (status quo) | Workflow-count | Workflow-count |
| Prohibited-polling/snapshot conflict | None | None | **Snapshot banned (P2-S14)** | **Polling banned** |
| Evidence tier for viability | T2 + spike obligations | T1 disproves sibling; T2 unproven | T1 disproves premise | T1/T2 contraindicate |
| Requires new DD amendment | AT-18 wording + readiness | Probe first; maybe pin change | Full reversal of P2-S14 | Full new DD (retry semantics) |
| Hosted proof achievable | Yes (delayed-parent, 9 keys) | Only if probe passes | Not meaningful | Bounded, but contract-violating |
| **Verdict** | **PRIMARY** (spike-gated) | **CONDITIONAL** (probe) | **REJECTED** | **FALLBACK** |

### Evidence-ranked recommendation

1. **Select Option 1′ (single native Hatchet workflow DAG, nine `durable_task` parents edges)** as the primary architecture, **bounded by the following evidence conditions** — this is not a silent selection:
   - **Condition A (spike):** single workflow yields nine `v1_task` rows with stable readable ids, `is_durable=true`, latest-version scoping; sync handlers accepted (or async requirement recorded); `eviction_policy` signature verified.
   - **Condition B (hosted):** durable slots assign on v0.105.2 (QUEUED→ASSIGNED/RUNNING); delayed-parent proof shows dependent tasks not `SENT_TO_WORKER`/`ASSIGNED`/`STARTED` before upstream durable completion; 9/9/9 and 6-row replay evidence holds.
   - **Condition C (contract):** AT-18 wording amendment preserving the hosted durability assertion; task-count readiness/C6 wording approved (HQ1/HQ5).
   - If A/B fail: investigate engine slot configuration first; then either approve a scoped async DD (HQ2) or activate Option 4′ with a new DD (HQ3).
2. **Option 2′ is conditional only:** run the plan-mandated `parent_step_run_id` hosted probe; if any of persistence/gating/multi-parent fails, record unsatisfiable and do not fall back to it. `parent_id` is not reopened (T1 disproven).
3. **Option 3 (submission-time snapshot) is rejected** — explicit P2-S14 reversal required, does not fix early dispatch, stale-evidence hazard, conflicts with canonical-selection/provenance invariants.
4. **Option 4′ is fallback-only** — requires a new DD (polling ban, slot/timeout physics, durable-task DB-access contract); never the default.

### Cross-cutting mandates (apply to whichever option is selected)

- Correct the assignment/runtime proof contract: `v1_task_events_olap` + `v1_tasks_olap.worker_id` + `Worker.isActive`; `v1_task_runtime.worker_id=0` is not authoritative (R8/F4).
- Preserve canonical lineage selection (c), claim-before-side-effect, `InvalidationPlanner` descendant-only, `SemanticLedger` append-only, `DagUniverseGate` drain, and no polling/resubmission/runner-chain/second scheduler.
- No executor/scheduler/topology/DB/token/endpoint/`run_workflow`/OCFL/semantic/provenance/invalidation ownership changes beyond the authorized AT-18 wording and readiness-counting amendment; everything else requires a new approved DD.

---

## 11. Validation manifest

**Turn completion (all eight substantive turns, in order, headings verified):**

- [x] **T1 — `## Proposed Approaches`** — 4 approaches; real-system/usage citations per approach; technology/version validation with check dates (2026-08-29) against installed SDK 1.38.1 + docs.hatchet.run + server v0.105.2.
- [x] **T2 — `## Critique`** — per-approach documented failures/limitations; evidence-tier ranking (T1–T4); explicit surviving/conditional/rejected/fallback dispositions; option matrix in §10.
- [x] **T3 — `## Refined Approaches`** — surviving approaches refined (1′/2′/4′); dropped approach (3) documented with reason; real-system analogs re-cited; changed technology revalidated.
- [x] **T4 — `## Surviving Concerns`** — unresolved issues clearly flagged (8 items), including durable-slot, row-granularity, sync-durable, readiness, AT-18, multi-parent, assignment-proof, sync-warning.
- [x] **T5 — `## Implementation Patterns`** — data flow, state management, error handling, testing, key library choices; cited real-world best practices and production implementations.
- [x] **T6 — `## Pattern Risks`** — specific, cited risks incl. cross-pattern interaction (R2×R5); trigger conditions and use-case match; better-fit alternatives considered.
- [x] **T7 — `## Final Patterns`** — risks addressed with mitigation or fundamental-limitation acknowledgment; technology revalidated; best-fit rationale (not newest-is-best).
- [x] **T8 — `## Open Risks & Human Questions`** — unresolved risks (UR1–UR7); substantive human-judgment questions (HQ1–HQ5) with context and evidence-based recommendation; provisional technology flags.

**Immutable-ledger preservation (verbatim, unweakened):** original request reproduced in §1.1; blocker DD L1–L21 reproduced in §1.2; binding contracts (CONTRACTS §33/§35/§58–63, AT-18, P2-S14) preserved in §1.3. No item weakened, omitted, or inverted.

**Citation integrity (spot-checked):** Hatchet docs URLs (`docs.hatchet.run/v1/directed-acyclic-graphs`, `/v1/durable-tasks`, `/cookbooks/durable-tasks-vs-dags`, `/v1/retry-policies`, `/v1/timeouts`, `/v1/migrating/migration-guide-python`) — fetched 2026-08-29, content matches claims. Installed SDK source paths verified directly (workflow.py, task.py, admin.py, types/trigger.py). Hosted evidence files verified in `/tmp/r40528/diag-final/` and debugger reports. T3 citations (Temporal community forum, Temporal docs polling pattern, Korasa production write-up, PostHog DAG executor, Prefect/n8n parent-metadata examples) are real and used at appropriate tier — none cited as dispositive.

**Process integrity:** no child agents spawned (explicit instruction honored; all roles executed inline by Refiner). Only this new process artifact was edited (`artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-plan-k-live-hatchet-lineage-barrier.md`); no production code, tests, plans, contracts, DDs, or workflows were modified.

**Ownership/authority boundaries:** this log proposes the architecture decision and required amendments; it does not implement. The blocker DD, netns DD, Plan K, and CONTRACTS.md remain binding; downstream DD-author/planner/exec actions require the approved amendments (HQ1/HQ2/HQ3/HQ4/HQ5) and the spike/probe conditions above.

**Completeness gate:** all 8 sections present and substantive; at least one approach genuinely challenged and refined (Option 1 → 1′ with AT-18/readiness/spike obligations; Option 3 rejected with evidence); recommendation bounded by evidence conditions, not assertion.
