# Complexity Review: Plan K Live-Hatchet Dependency-Barrier Decision (Options 1–4)

- **Agent:** rnd-complexity-advisor
- **Date:** 2026-08-29
- **Scope:** Read-only semantic-complexity and scope review of the R&D decision on stage
  dependency enforcement for the pinned `hatchet-sdk==1.38.1` / server `v0.105.2`, after
  hosted run `33240528692` disproved `TriggerWorkflowOptions.parent_id` as a dispatch
  barrier (Plan K P2-S8..S14 blocked). Evaluates Options 1–4 for unnecessary abstraction,
  scope inflation, operational complexity, hidden dual paths, and invariant risk.
  No production code, tests, contracts, plans, or DDs were edited.
- **Verdict:** ELEVATED — only one of the four options (Option 1) is machinery-minimal;
  the other three each re-introduce a previously rejected pattern (dual evidence path,
  snapshot authority, or polling/retry machinery) or depend on an unverified mechanism.
  Recommendation: Option 1, bounded by two explicit text/assertion reconciliations and one
  hosted probe. Two unresolved human decisions gate selection.
- **Status:** DONE

---

## 1. Inputs

| Input | Path / reference | Role |
|---|---|---|
| Support-Librarian briefing (fresh) | `optimistic-olive-gerbil.md` (delegations `871898c83592455e`), log `support-librarian.log.jsonl` L28 | Constraint set, option framing, decisive evidence |
| Support-Researcher report (fresh) | `presidential-pink-python.md`, log `support-researcher.log.jsonl` | v0.105.2 schema/assignment-proof facts (check 2026-08-29) |
| Support-Debugger reports (fresh) | `developing-yellow-iguana.md`, `stuck-brown-pig.md`, `living-aqua-weasel.md`, `unexpected-blush-bass.md`; log `support-debugger.log.jsonl` L20–L27 | Root cause, barrier mechanism verification, pre-claim semantics |
| Plan K | `artifacts/plans/pending/TASK-universal-media-decomposer-K-ci-repair-release-gate.md` (P2-S8..S14, amendment 2) | Blocker authority; P2-S14:105 `(a)+(c), never (b)` |
| Blocker DD (immutable L1–L21) | `artifacts/designs/pending/DD-universal-media-decomposer-plan-k-live-hatchet-blocker.md` | Requirement ledger; sync-durable deferral (line 126) |
| Netns DD (binding authority) | `artifacts/designs/pending/DD-universal-media-decomposer-plan-k-netns-workflow-amendment.md` (AT-16/17/18/19) | AT-18 per-stage `client.durable_task` wording (R19) |
| CONTRACTS.md | §33 (`StageRunRepository.claim` sole completion authority), §35 (`InvalidationPlanner` descendant-only, `STAGE_DEPENDENTS`/`STAGE_DEPENDENCIES` sole lineage) | Invariant authority |
| Prior complexity review (callback blocker) | `universal-media-decomposer-plan-k-hatchet-live-blocker-complexity-review.md` | Rejected patterns R1–R6, RA1–RA4, S1–S6, N2/Q5 that carry forward to every option |
| rnd-manager log | L50 (DD_REQUIRED lock), L57 (Option 1 leading condition) | Decision boundary |

### Coverage gaps (explicit nil results)

- **The named fresh eight-turn adversarial artifact
  `artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-plan-k-live-hatchet-lineage-barrier.md`
  does not exist on disk.** The only Plan K adversarial artifact present is
  `ADVERSARIAL-universal-media-decomposer-plan-k-live-hatchet-blocker.md` — the *prior*
  callback/registration round, which rnd-manager L51 explicitly rules out as a substitute
  for this decision. rnd-manager L53 records that a fresh refiner round
  (`deafening-moccasin-bass`) was dispatched; its artifact is either in flight or not yet
  committed. This review therefore evaluates Options 1–4 from the debugger/librarian/
  researcher evidence and the prior round's rejected-pattern ledger, not from a
  lineage-barrier adversarial log. If that log lands before final selection, it must be
  checked against §6 findings here.
- **No fresh architecture report exists for Options 1–4.** The architecture report on disk
  (`universal-media-decomposer-plan-k-hatchet-live-blocker-architecture-options.md`)
  covers the prior callback blocker (A2′/A1′/A3′/A4), not the dependency-barrier decision.
  The option set is framed in the librarian briefing and rnd-manager log only.

---

## 2. Option definitions and shared constraint surface

The four options as framed in the corpus:

| Option | Shape | Core mechanism |
|---|---|---|
| 1 | Single-workflow native DAG | `Workflow.durable_task(name, parents=[...])` (`runnables/workflow.py:1701-1814`); one `WorkflowVersion`, N `v1_task` rows, per-task `readable_id` |
| 2 | Cross-workflow barrier / pair upgrade | `parent_step_run_id` → `parent_task_run_external_id` (field 5), or an approved SDK/server pair change with drain/rekey |
| 3 | Submission-time snapshot | Reverse Plan K P2-S14:105 rejection of design `(b)`; snapshot evidence at submission |
| 4 | Bounded pre-claim retry | Durable wait/retry before `DurableStageExecutor.run()`/`StageRunRepository.claim()` |

**Shared constraints every option must preserve (unchanged):**

- L1–L21 immutable ledger: Hatchet sole v1 scheduler; real callbacks + `DurableStageExecutor`;
  durable async restart/retry/cancel/selective invalidation; no skips/stubs/fake readiness/
  recording doubles as release evidence; no weakened gates; hosted native Docker/Compose
  evidence before docs/DoD closure; OCFL/evidence/semantic/provenance invariants.
- AT-16/17/19 composed under AT-19 as non-skippable release gate.
- CONTRACTS §33: `UNIQUE(idempotency_key)` claim is sole completion authority; claim-before-side-effect.
- CONTRACTS §35: `InvalidationPlanner` descendant-only; `STAGE_DEPENDENCIES`/`STAGE_DEPENDENTS` sole lineage authority.
- Exactly nine canonical idempotency keys per submission (one per `STAGE_ORDER` stage);
  `live-dup` 9/9/9, `live-shape` 6 relevant rows/events (P2-S14 acceptance).
- No natural-key shortcut, no accepting 10 rows, no ignoring evidence, no job-scoped union
  (the live-dup 10-vs-9 defect must not be "fixed" that way).
- Prior rejected patterns R1–R6 / RA1–RA4 apply to every option unless a new DD explicitly overrides.
- Runner must express **all** `STAGE_DEPENDENCIES` edges, not only the latest direct
  dependency (`runner.py:255-258` today loses multi-parent edges).
- Sync-durable deprecation is **already decided** (blocker DD:126, complexity N2/Q5): defer
  async. Not re-opened unless an option changes the handler contract.

---

## 3. Findings — per option

### Option 1 — Single-workflow native DAG

| Dimension | Assessment |
|---|---|
| Unnecessary abstraction | **Low.** Uses the SDK's native `durable_task(..., parents=...)` graph — the *only* verified native mechanism in the corpus. No new service, no new abstraction layer; per-task callback wiring to `DurableStageExecutor` is unchanged. |
| Scope inflation | **Moderate, bounded to text/assertions.** Two reconciliation surfaces, both small: (a) AT-18 wording (see below), (b) readiness count semantics (`len(registered_workflows) == len(STAGE_ORDER)` would see 1 workflow, not 9). Neither requires new machinery — both are a contract-text clarification and one assertion change. Runner submission simplifies (one DAG submission instead of per-stage `parent_id` threading). |
| Operational complexity | **The real cost.** Single `WorkflowVersion` = single registration unit; stage identity moves to per-task `readable_id` + the `stage` field in each task's input. Readiness/engine proof/A3′ must switch from "count workflow objects" to "count tasks within the workflow" and key per-task `readable_id`. Hosted proof must show 9 independently identifiable durable `v1_task` rows (rnd-manager L57 leading condition). Loses per-stage independent versioning/restart granularity — acceptable because per-stage independent registration is exactly what cannot express barriers (`client.durable_task` hardcodes `parents=[]`). |
| Hidden dual paths | **Risk is containable.** Only if implementation keeps per-stage standalone registration *and* the single DAG as a runtime switch would this create a dual path — reject explicitly (mirror RA1 from the prior round). The `stage`-field data dispatch within one workflow is data routing, not a dual path. |
| Invariant risk | **Focused.** §33 claim authority untouched (callback still resolves canonical evidence before claim). §35 lineage untouched (parents derive only from `STAGE_DEPENDENCIES`). 9-key stability preserved by construction (one stable manifest per stage). The one genuine invariant tension is **AT-18 reconciliation (R19)** — see below. |

**AT-18 reconciliation (R19) — the core invariant question for Option 1.**

Netns DD AT-18 reads: "every release `umd-<stage>` task uses
`client.durable_task(name=wf_name)(handler)` … hosted DB/engine evidence asserts every
resulting `v1_task.is_durable=true`." Two defensible readings:

- **Surface reading (topology):** each `umd-<stage>` is an independently registered durable
  workflow/task. A single workflow contradicts this literally.
- **Property reading (durability):** every release `umd-<stage>` is registered as a durable
  task (`is_durable=true`) and individually identifiable. A single workflow with 9 durable
  tasks satisfies this — 9 `v1_task` rows each with `is_durable=true` and distinct
  `readable_id`, hosted-assertable.

The surrounding intent (AT-18's purpose was durable registration + hosted `is_durable=true`,
per the prior complexity review N1/K3) supports the **property reading**. But the literal
text says `client.durable_task` on the client for each `umd-<stage>` — a **different
registration surface** (`Workflow.durable_task`) and a **different topology** (one workflow).
This cannot be resolved by silent implementation: it requires an approved DD/contract-text
clarification. **This is a genuine unresolved human decision** (flagged by rnd-manager L51,
librarian R19). It is a *wording* change, not a new contract authority — bounded.

**Readiness task-count semantics.** The current readiness contract
`len(registered_workflows) == len(STAGE_ORDER)` (P2-S5, cli.py exact-count gate, C6 line)
counts workflow objects. One workflow object → count 1, gate fails. The contract must
change to count durable tasks (`9`) via per-task `readable_id`. This is one assertion change
plus one contract-wording change; the C6 line wording ("registered {N} Hatchet workflows")
also needs task-count alignment. Bounded, but must be written explicitly or the P2-S13/P3-S3
gates will fail on count semantics, not on barrier behavior.

**Complexity verdict: machinery-minimal; two bounded text/assertion reconciliations required.**

---

### Option 2 — Cross-workflow `parent_step_run_id` barrier / pair upgrade

| Dimension | Assessment |
|---|---|
| Unnecessary abstraction | **N/A — but built on an unproven primitive.** Not an abstraction; a field swap. However `parent_step_run_id` is **singular and unproven** (debugger living-aqua-weasel §1, librarian HIGH/MEDIUM): it cannot obviously represent multiple direct parents, and server-side gating on v0.105.2 requires a hosted probe that has not been run. `STAGE_DEPENDENCIES` has multi-parent edges; a singular parent field cannot express them without additional machinery (which would then *be* an abstraction: N submissions or a parent-mapping layer). |
| Scope inflation | **HIGH in the upgrade leg.** If the probe fails, the only remaining path is an approved SDK/server pair change with lockstep pins, new DAG universe, drain/rekey/rollback — a coordinated infrastructure change for a release-blocker repair. That is the largest blast radius of any option. |
| Operational complexity | **High.** Requires a new hosted persistence-and-dispatch probe before any implementation decision; the probe itself is a new evidence gate. If singular-parent limitation is confirmed, the option is unsatisfiable as specified. |
| Hidden dual paths | **High risk.** Keeping `parent_id` (metadata) alongside `parent_step_run_id` as a "belt and suspenders" submission would create two submission paths — exactly the pattern R5/RA1 killed in the prior round. Must be exactly one, or the debugger direction ("do not merely swap parent_id → parent_step_run_id without hosted proof") is violated. |
| Invariant risk | **Unverified.** Does not disturb §33/§35 on paper, but the 9-key evidence material stability is unproven for this path, and multi-parent edges are structurally unrepresentable in a singular field. If it cannot express all `STAGE_DEPENDENCIES` edges, it cannot satisfy P2-S8's "derive parents only from STAGE_DEPENDENCIES" — an invariant failure. |

**Complexity verdict: highest-risk, least-verified. Not a simplification of anything — it
either depends on an unproven singular field or escalates to an SDK/server migration.**
Recommendation: keep the hosted probe as a *diagnostic* to close the question, but do not
select this as the primary architecture unless the probe proves both (a) real server-side
gating on v0.105.2 and (b) expression of all multi-parent edges.

---

### Option 3 — Submission-time snapshot reversal

| Dimension | Assessment |
|---|---|
| Unnecessary abstraction | **Re-introduces a rejected second evidence path.** Design `(b)` was explicitly rejected in Plan K P2-S14:105 ("(a) native barriers + (c) canonical selection, **never (b)**"). A submission-time snapshot is a second evidence authority alongside callback-time canonical selection (P2-S9). |
| Scope inflation | **Requires reversing a deliberate prior decision.** Lifting the rejection needs a new DD amendment explicitly reversing P2-S14. That is process churn for a mechanism that is the *proven source* of the current defect: callback-time evidence snapshotting before upstream `FORMAT` committed produced the second `BASIC_SEGMENTATION` key (live-dup 10-vs-9, `unexpected-blush-bass`). A snapshot does not fix that — it freezes evidence *earlier*, which is worse, unless it is taken at exactly the right lineage point, which is precisely what canonical selection already does. |
| Hidden dual paths | **High.** Snapshot evidence and canonical-selection evidence would coexist unless snapshot fully replaces canonical selection. Full replacement conflicts with the deterministic current-lineage selection built in P2-S9 (evidence-sensitive rekeying after `InvalidationPlanner` descendant reruns and DAG-universe changes). A frozen snapshot goes **stale after descendant rekey or universe drain** — it would re-introduce exactly the empty/stale-evidence class of bug the canonical selection was built to eliminate. |
| Invariant risk | **HIGH.** CONTRACTS §33 (§35 lineage) is not directly touched, but the "select exactly one COMPLETE upstream per edge at callback time, never an in-flight row or job-scoped union" invariant is replaced by a submission-time freeze. Post-rekey correctness (§35, descendant-only invalidation) is only guaranteed by callback-time canonical selection; snapshot removes that guarantee. |

**Complexity verdict: rejects a deliberate, evidence-backed decision to re-enter the defect
class that caused the blocker. Do not recommend.**
This option should be treated as closed unless a new DD amendment explicitly justifies why
snapshotting is *more* correct than callback-time canonical selection after rekey — no
argument in the corpus supports that.

---

### Option 4 — Bounded pre-claim retry / polling

| Dimension | Assessment |
|---|---|
| Unnecessary abstraction | **Highest new-machinery cost of all options.** Requires a durable retry/quarantine/timeout/idempotency subsystem in the worker callback path — the exact "retry loop" pattern the prior review rejected (R4, S1′). The debugger is explicit that this is not "reuse of existing retry": it needs a DD defining durable retry, timeout, quarantine, and idempotency semantics. |
| Scope inflation | **Substantial new DD content + new hosted tests.** Must prove timeout, retry, restart, reclaim, and idempotency behavior hosted — a new evidence surface. |
| Operational complexity | **Direct conflicts.** (a) Repeating DB checks during the wait is **polling, explicitly prohibited** (librarian HIGH; plan: no polling). (b) Synchronous waiting consumes a worker slot during the wait. (c) The callback may exceed Hatchet schedule/execution timeouts. (d) `MissingRequiredEvidenceError` has no application-level retry path today. Every one of these is a *new* operational mechanism, not a repair. |
| Hidden dual paths | **Medium.** The only safe form is strictly pre-claim (wait → then claim → then side effect). If any retry occurs after claim, it violates CONTRACTS §33 claim-before-side-effect by holding a claimed idempotency key through an unresolved dependency. The bounded-wait loop must be provably pre-claim-only, which the current handler order (`hatchet.py:374-402`: resolve evidence → executor.run → claim inside) does not naturally give — it requires a reorder that is itself a contract-adjacent change. |
| Invariant risk | **Moderate-to-high.** Fail-closed `MissingRequiredEvidenceError` must remain fail-closed (no "wait until it appears then proceed" semantics that silently weaken the gate). §33 is preserved only under the strict pre-claim form. |

**Complexity verdict: most new machinery, direct conflict with the "no polling" and "no
retry loop" rejections, and the weakest invariant story. Acceptable only as a *fallback* if
a native barrier is proven inexpressible — and even then it needs a substantial new DD.**

---

## 4. Findings — shared / cross-cutting

### 4.1 Assignment-proof evidence complexity (affects every option)

The current proof contract (`engine-visible-proof.sh` treating empty `v1_task_runtime` as
"no assignment") is **diagnostically invalid** — `v1_task_runtime` is ephemeral/empty after
terminal callbacks. The researcher report (`presidential-pink-python`, check 2026-08-29)
fixes the schema facts:

- `v1_task` has **no `status` column**; status lives in `v1_tasks_olap.readable_status`
  (enum: QUEUED, RUNNING, CANCELLED, FAILED, COMPLETED, EVICTED — **no ASSIGNED**).
- **`ASSIGNED` is not a readable status**; it exists only as an event type in
  `v1_task_events_olap.event_type` (`v1_event_type_olap`: SENT_TO_WORKER, ASSIGNED,
  ACKNOWLEDGED, STARTED, …).
- Live assignment = `v1_task_runtime.worker_id` (ephemeral) or
  `v1_tasks_olap.latest_worker_id`.
- No `v1_worker`, no `v1_task_assign` table exist; `WorkerAssignEvent` is a v0-only log not
  written by v1 engine paths.

The corrected proof contract (already mandated by the plan amendment) is: correlate
`v1_task_events_olap` transitions (SENT_TO_WORKER/ASSIGNED/STARTED) + `v1_tasks_olap`
`readable_status`/`latest_worker_id`, scoped to submitted task IDs and time windows; never
infer absence from `v1_task_runtime.worker_id IS NULL`. **This is a diagnostic correction,
not new machinery** — but it must be specified **once and shared** by whichever option is
selected, not re-derived per option (re-derivation would create four subtly different proof
queries, each an independent maintenance surface and a new false-negative risk).

Complexity note: the prior blocker round's "QUEUED→ASSIGNED/RUNNING polling" phrasing should
be aligned to the schema fact that ASSIGNED is an event, not a status — otherwise the hosted
gate will assert against a nonexistent `readable_status='ASSIGNED'` and fail spuriously.

### 4.2 Sync-durable deprecation (R22 — already decided, no new decision)

Blocker DD:126 and prior complexity N2/Q5 already deferred async conversion; the librarian
confirms R22. **None of Options 1–4 changes the handler contract** (all keep the sync
`handler(input, ctx)` → `DurableStageExecutor` shape; Option 1 changes only the registration
object from `client.durable_task` to `Workflow.durable_task`, not the handler signature).
Therefore R22 stands unchanged under every option. The only re-open trigger would be an
option forcing an async handler — none does. No new decision or DD content is required here;
the review notes this so downstream does not treat Option 1's registration-surface change as
an excuse to revisit async.

### 4.3 `STAGE_DEPENDENCIES` edge completeness (all options)

`runner.py:255-258` submits only the **latest direct dependency** per dependent stage, so
multi-parent edges are already lost at submission time regardless of mechanism. Every option
must express **all** `STAGE_DEPENDENCIES` edges, or the "full-barrier" guarantee fails even
with a working barrier. Options 2 and 4 inherit this defect structurally (singular field /
wait-on-one-parent); Options 1 and 3 can express all edges (DAG parents list / snapshot of
all upstream refs) but only Option 1 does so with native scheduling semantics. This is a
pre-existing defect in scope that must be repaired regardless of option choice — it is not a
new abstraction, but it must be in the acceptance evidence.

---

## 5. Verdict

```yaml
status: DONE
target: "artifacts/designs/process/COMPLEXITY-universal-media-decomposer-plan-k-live-hatchet-lineage-barrier.md"

structure:
  options_evaluated: 4
  shared_reconciliations_required: 2   # AT-18 wording (R19), readiness task-count semantics
  cross_cutting_fixes: 2               # assignment-proof proof contract, multi-parent edge completeness
  prior_rejected_patterns_retriggered: 3  # snapshot (R-prior (b)), retry loop (R4/S1'), dual-path (R5/RA1)

comparison:
  prior_round_verdict: APPROPRIATE (callback blocker repair was defect-sized)
  this_round_verdict: ELEVATED
  delta: "Only Option 1 is machinery-minimal; Options 2/3/4 re-introduce rejected patterns or depend on unverified mechanisms"

findings:
  - location: "Option 1 — Workflow.durable_task(name, parents=[...])"
    concern: "AT-18 literal text ('client.durable_task per umd-<stage>') vs single-workflow topology"
    evidence: "Netns DD AT-18:80-88,185-188; rnd-manager L51 (R19); librarian briefing"
    alternative: "Approved DD/contract-text clarification adopting the property reading (every umd-<stage> a durable task, is_durable=true, individually identifiable); no new authority"
    confidence: HIGH (that reconciliation is required), MEDIUM (which reading wins — human decision)
  - location: "Option 1 — readiness count semantics"
    concern: "len(registered_workflows) == len(STAGE_ORDER) counts 1 workflow, not 9 tasks"
    evidence: "P2-S5 exact-count gate; cli.py C6 line; librarian open question"
    alternative: "Count durable tasks via per-task readable_id (9); update C6 wording; one assertion change"
    confidence: HIGH
  - location: "Option 2 — parent_step_run_id / pair upgrade"
    concern: "Singular, unproven field; cannot obviously express multiple direct parents; upgrade leg = coordinated SDK/server migration"
    evidence: "living-aqua-weasel §1; librarian warnings (HIGH/MEDIUM); runner.py:255-258"
    alternative: "Keep probe as diagnostic only; select Option 1 unless probe proves gating AND multi-parent expressibility"
    confidence: HIGH
  - location: "Option 3 — submission-time snapshot reversal"
    concern: "Reverses P2-S14:105 rejection; snapshot is the proven source of the 10-vs-9 key defect; goes stale after rekey/universe drain"
    evidence: "Plan K P2-S14:105; unexpected-blush-bass (live-dup 10-vs-9); librarian warning"
    alternative: "Do not adopt; requires explicit DD reversal with a correctness argument that does not exist in the corpus"
    confidence: HIGH
  - location: "Option 4 — bounded pre-claim retry"
    concern: "New retry/quarantine/timeout machinery; polling prohibition conflict; worker-slot consumption; Hatchet timeout risk; needs substantial new DD"
    evidence: "living-aqua-weasel §3a/§4; prior review R4/S1'; librarian HIGH"
    alternative: "Fallback only if native barrier proven inexpressible; strict pre-claim-only form; new DD mandatory"
    confidence: HIGH
  - location: "Assignment proof (shared)"
    concern: "v1_task_runtime.worker_id IS NULL treated as no-assignment; ASSIGNED is not a v1 readable status"
    evidence: "support-researcher presidential-pink-python (2026-08-29); debugger L24/L25"
    alternative: "Correlate v1_task_events_olap transitions + v1_tasks_olap latest_worker_id/readable_status, submission-scoped; one shared proof contract"
    confidence: HIGH

verdict:
  complexity_level: ELEVATED
  justified: false
  summary: "Option 1 is the only architecture that uses the verified native mechanism, expresses all STAGE_DEPENDENCIES edges, needs no polling/retry/snapshot machinery, and preserves the sync handler contract (R22 stands). Its costs are two bounded text/assertion reconciliations (AT-18 R19, readiness task-count) and one hosted probe. Options 2, 3, and 4 each either depend on an unproven primitive, reverse a deliberate evidence-backed rejection, or build the largest new machinery of the four — none is a simplification."
```

---

## 6. Recommendation

**Select Option 1 (single-workflow native DAG) as the primary architecture, bounded by:**

1. **One hosted probe** (mandatory, pre-implementation): prove the pinned SDK/server yields
   one `WorkflowVersion` with **9 individually identifiable durable `v1_task` rows**
   (distinct `readable_id`, `is_durable=true`), and that native `parents=[...]` edges gate
   child dispatch until all parent durable completions persist. This is rnd-manager L57's
   leading condition and the librarian's verified-mechanism claim; it must be proven hosted,
   not from SDK source.
2. **AT-18 reconciliation (R19) as an approved DD/contract-text clarification**, adopting
   the property reading: every release `umd-<stage>` is registered as a durable task with
   `is_durable=true` and individually identifiable `readable_id`, within the single
   canonical workflow; the hosted assertion becomes "every latest-version `umd-<stage>`
   task has `is_durable=true`" (unchanged) plus "9 distinct task rows". No new contract
   authority.
3. **Readiness task-count semantics**: change the exact-count gate from workflow objects to
   durable tasks (9) via `readable_id`; align C6 wording. One assertion + one wording change.
4. **One shared assignment-proof contract** (see §4.1): event/OLAP correlation, submission
   scoped, never `v1_task_runtime.worker_id`-only, never `readable_status='ASSIGNED'`.
5. **Multi-parent edge completeness**: Option 1's DAG expresses all `STAGE_DEPENDENCIES`
   edges; runner must stop truncating to the latest direct dependency. Include in acceptance.
6. **Explicit rejections carried into the DD/plan**: no dual registration path (single DAG
   *or* per-stage, never both — RA1); no `parent_id` fallback (metadata-only, disproven);
   no snapshot (Option 3 closed absent an evidence-backed reversal); no pre-claim retry
   unless the probe proves the native DAG inexpressible (Option 4 fallback, new DD required).

### Unresolved human decisions (must be answered before final selection)

- **H1 (gating): AT-18 reading.** Does the binding contract require per-stage *independent
  registration* (surface/topology reading) or per-stage *durable-task identity within one
  workflow* (property reading)? Option 1 is selected only under the property reading.
  This is a contract-authority question for the DD author + human sign-off, not an
  implementation detail.
- **H2: readiness count contract.** Count tasks (9) vs. workflows (1) — which does the
  release gate assert, and does the C6 line text change? Bounded, but must be decided
  explicitly or the P2-S13/P3-S3 gates will fail on semantics, not behavior.

### Non-negotiable keepers (do not simplify away)

- CONTRACTS §33 claim authority and claim-before-side-effect — unchanged under Option 1
  (canonical evidence resolution before `DurableStageExecutor.run`, as in P2-S9).
- CONTRACTS §35 descendant-only invalidation and `STAGE_DEPENDENCIES` sole lineage.
- 9-key canonical evidence material stability (single + duplicate submission).
- AT-16/17/19 composed under AT-19, non-skippable.
- Sync-durable handler — R22 deferral stands; no option changes the handler contract.

### What was NOT assessed here

The fresh eight-turn adversarial artifact for this specific decision was not present at
review time; its findings must be checked against §3/§6 before DD authoring. If the refiner
round lands before selection, re-read §3 option findings against it — the adversarial round
may add evidence that changes the Option 2 probe verdict (H1 is the only decision likely to
be resolved there).

---

## 7. Handoff

- **To:** RnD-DDAuthor (next in pipeline), then RnD-Estimator, then Support-PatternEnforcer,
  then Exec-Manager.
- **Key message:** select Option 1 with the two reconciliations (AT-18 R19 as a contract-text
  clarification; readiness task-count) and the mandated hosted probe; carry the rejections of
  Options 2/3/4 and the prior R1–R6/RA1–RA4 ledger into the DD; adopt one shared
  assignment-proof contract; do not reopen sync-durable deferral (R22); resolve H1/H2 as
  human decisions before the DD is finalized.
