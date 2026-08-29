# Complexity Review: Plan K Live Hatchet Blocker — SDK 1.38.1 v1 Callback Contract Repair

- **Agent:** rnd-complexity-advisor (quiet-violet-caribou)
- **Date:** 2026-08-29 (amended after the full T1–T8 adversarial sequence completed)
- **Scope:** Review the proposed solution for the newly diagnosed live Hatchet blocker for unnecessary abstraction, accidental complexity, and scope inflation. Read-only; no production/workflow/test/DD/plan edits.
- **Verdict:** APPROPRIATE — the repair scope is evidence-justified and bounded. Six implementation-time abstractions are explicitly rejected and six simplifications are prescribed so the DD/Plan K amendment stays as small as the defect set. The completed adversarial package (F-1…F-7) is confirmed defect-sized; four residual abstraction risks (RA1–RA4) and five blocking risks (B1–B5) are enforced in §12.
- **Status:** DONE

---

## 1. Inputs table

| Input | Path / reference | Role |
|---|---|---|
| User request (verbatim intent, immutable L1–L21 preserved) | session task brief | Scope authority; overrides DD/plan/code on conflict |
| Existing netns DD (already carries AT-16–19) | `artifacts/designs/pending/DD-universal-media-decomposer-plan-k-netns-workflow-amendment.md` | Reconcile, do not duplicate |
| Plan K | `artifacts/plans/pending/TASK-universal-media-decomposer-K-ci-repair-release-gate.md` (P1–P4 complete; P5–P6 pending) | Amendment target |
| Support evidence | `artifacts/logs/support-researcher.log.jsonl:L9`, `support-debugger.log.jsonl:L8–L12`, `support-librarian.log.jsonl:L37/L22` | Defect authority |
| Refiner artifact | `artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-plan-k-live-hatchet-blocker.md` | T1–T8 complete (2026-08-29); final pattern package F-1…F-7, human questions Q1–Q5, risk register R1–R10; §12 assesses that outcome |
| Architect artifact | `artifacts/designs/process/universal-media-decomposer-plan-k-netns-architecture-options.md` (Option D adopted) | Boundary precedent |
| Prior complexity review (template) | `artifacts/designs/process/universal-media-decomposer-plan-k-netns-complexity-review.md` | Format/verdict precedent |
| Pinned SDK source, tag `py/1.38.1` | `sdks/python/hatchet_sdk/runnables/task.py`, `hatchet_sdk/hatchet.py` (fetched from GitHub raw, checked 2026-08-29) | Contract verification |

## 2. Verified SDK facts (check date 2026-08-29, source `hatchet-dev/hatchet` tag `py/1.38.1`)

| Fact | Evidence |
|---|---|
| Task callbacks are invoked as `fn(workflow_input, ctx)` — two positional args | `task.py` `Task.call()` → `self._fn(workflow_input, cast(Context, ctx), **dependencies)`; `aio_call()` same |
| The input is the run input passed directly (no `{"input": ...}` wrapper) | `workflow_input = self._workflow._get_workflow_input(ctx)`; submission site `src/umd/jobs/runner.py:232-239` emits top-level `{job_id, source_id, dag_universe, stage, manifest[, causation_id]}` |
| `client.task(...)` registers non-durable tasks | `task.py` `Task.to_proto()` emits `is_durable=self._is_durable`; `Hatchet.task` (hatchet.py) does not set it; `durable_task` (hatchet.py) exists and hands `DurableContext` |
| Durable handler must accept `DurableContext` as second arg; sync durable handlers are accepted but deprecated (warning) | `hatchet.py` `durable_task` overloads `Callable[Concatenate[TWorkflowInput, DurableContext, P], ...]`; `task.py` deprecation warning |

All three prior claims from support evidence are confirmed directly against the pinned tag. The `durable_task` facade surface, previously only cited via debugger/researcher, is now verified first-hand.

## 3. Defect set being repaired (all verified at HEAD 6614b32)

1. **Handler contract mismatch (the live blocker).** `_make_handler` returns `def handler(payload)` reading `payload["input"]["manifest"]` (`src/umd/jobs/hatchet.py:229-230`) — one arg, v0 shape. SDK 1.38.1 calls `fn(workflow_input, ctx)` with a direct dict. Every live task of run `33229130339` / job `99038602321` failed before UMD execution. Fix surface: two lines (signature + manifest read).
2. **Hermetic masking.** `tests/test_hatchet_live.py:459-464` `_invoke_callback` invokes `cb({"input": {"manifest": manifest.to_dict()}})`, encoding the wrong contract locally. Fix surface: one line.
3. **Suppressed registration failures.** `HatchetWorkerFactory.start` wraps the real-SDK decorator in `contextlib.suppress(Exception)` (`hatchet.py:426`) with a misdirected "deferred registration" comment (`:423-425`). Decoration-time registration is not deferred; the suppress hides real errors (e.g. the TypeError the wrong arity would raise). Fix surface: deletion + comment correction.
4. **Fabricated readiness.** `src/umd/deploy/cli.py:123` falls back to `len(work_registry)` when `registered_workflows` is empty; `WorkerHandle._ready = callbacks_bound` (`hatchet.py:446`) is True even when registration produced zero objects. `worker_ready_line` (`hatchet.py:165-181`) prints a count that `wait-for-worker.sh` greps. Fix surface: delete fallback; tighten `_ready`.
5. **Local-only registration test.** `tests/test_hatchet_live.py:1035-1080` claims "engine-visible" but inspects only local `Standalone`/`Workflow` objects; it never starts the worker loop or queries the engine. Fix surface: honest re-scope (rename + docstring) — engine-visible proof already owned by AT-18 hosted assertion.
6. **Tenant selection (prior defect, must be preserved).** Run minted a JWT for the `internal` tenant with null partition IDs (`8d420720-…`); the `Default` tenant `707d0855-…` has both partitions. AT-17 mandates scheduler-eligible selection, fail-closed discovery, and tenant agreement plus assignment/runtime state. Already carried by the netns DD — reconcile, do not duplicate.

## 4. Mandatory-item disposition table

| Mandatory item | Disposition |
|---|---|
| v1 `handler(input, ctx)` direct-input contract (AT-16) | KEEP — real defect; two-line fix + spec-first negative tests |
| Tenant partition eligibility + agreement + assignment/runtime state (AT-17) | KEEP — actual L10 root cause; small fail-closed filter + assertions |
| `client.durable_task` for every release `umd-<stage>`, hosted `v1_task.is_durable=true` (AT-18) | KEEP — requirement-grounded (durable async, sole v1 scheduler); one-line surface change + one hosted assertion; see N1 |
| AT-16/17/18 mandatory non-skippable pre-Phase-6 gate composition (AT-19) | KEEP — no weakening; joined with AT-1–15 |
| No skips/stubs/fake readiness/recording doubles as release evidence | KEEP — recording double stays a hermetic dev surface only; hosted gate stays real |
| Reconcile with netns DD, do not duplicate | KEEP — amend Plan K referencing existing AT-16–19; no new DD for these contracts |
| Hatchet sole v1 scheduler; no topology/architecture redesign | KEEP — Option D boundary; ruled-out infra causes not reopened (debugger L12) |
| Durable async restart/retry/cancel/selective invalidation | KEEP — satisfied by DurableStageExecutor + AT-16/18; no new executor work |

## 5. Unnecessary abstractions to REJECT

| # | Abstraction | Location risk | Evidence | Alternative | Confidence |
|---|---|---|---|---|---|
| R1 | v0→v1 payload adapter / compat shim ("accept both shapes") | `_make_handler` rewrite | No v0 producer exists anywhere (`runner.py:232-239` emits top-level dict only); run `33229130339` proves engine delivers direct input | One-way v1 handler (`payload["manifest"]`); hermetic negative test asserts a v0-wrapped payload raises | HIGH |
| R2 | Fake `Context`/`DurableContext` class hierarchy in hermetic tests | `test_hatchet_live.py` fixtures | Handler never reads `ctx` (`hatchet.py:229-285`) | Trivial placeholder second arg (`object()` / `SimpleNamespace`); contract test asserts arity/shape, not ctx contents | HIGH |
| R3 | Engine-visible registration machinery inside the local cluster test (worker-loop spawn, gRPC/REST engine query in-test) | `test_live_hatchet_engine_visible_...` | Test already overclaims (inspects local `Standalone` only, `:1066-1080`); hosted engine-visible proof is AT-18's `v1_task.is_durable=true` | Honest re-scope (rename + docstring); hosted gate owns engine-visible proof | HIGH |
| R4 | Registration-failure retry/backoff loop in `HatchetWorkerFactory.start` | `hatchet.py:415-431` | Registration is deterministic decoration-time work (Workflow init + task() run immediately); failures are config/programming errors, not transient | Fail fast: propagate; `cli.worker()` exits non-zero before printing readiness | HIGH |
| R5 | `task`↔`durable_task` dual-path switch (env flag / capability detection) | registration branch | AT-18 fixes the surface; a fallback creates two unverified registration paths | Single surface `client.durable_task(name=wf_name)(handler)`; negative: any `client.task` for `umd-<stage>` fails | HIGH |
| R6 | New readiness abstraction (HealthState enum, probe object, readiness subsystem) | `cli.worker()` / `WorkerHandle` | Only two consumers exist: cli exit gate and `worker_ready_line` count | Tighten the existing boolean: `_ready = callbacks_bound and bool(registered_workflows)`; delete `cli.py:123` fallback | HIGH |

## 6. Simplifications to APPLY

| # | Finding | Concern | Evidence | Alternative | Confidence |
|---|---|---|---|---|---|
| S1 | Remove `contextlib.suppress(Exception)` and the "deferred registration" comment (`hatchet.py:423-431`) | Swallows real decorator exceptions; its premise is wrong — the decorator's `inner()` executes registration work immediately; only engine-side registration is deferred (owned by `worker.start()`) | SDK `task`/`durable_task` decorators run `Workflow.__init__` + `workflow.task(...)` at application time; the wrong-arity TypeError would have been surfaced here | Let exceptions propagate to `cli.worker()` → exit 2 | HIGH |
| S2 | Delete `cli.py:123` fallback `or (len(work_registry) if work_registry else 0)` | Fabricates the readiness count when registration produced nothing; `work_registry` is non-empty by construction at that point, so the fallback only ever masks failure | `n_workflows` feeds `worker_ready_line` which `wait-for-worker.sh` greps | `n_workflows = len(handle.registered_workflows)`; zero-with-bound-executors ⇒ fail | HIGH |
| S3 | Tighten `WorkerHandle._ready` to include actual registration success | `_ready = callbacks_bound` is True with zero registered objects (suppressed error path) | `hatchet.py:446`; `is_ready()` gate at `cli.worker()` | `_ready = callbacks_bound and bool(registered_workflows)` | HIGH |
| S4 | Align `_invoke_callback` one line (`test_hatchet_live.py:464`) | v0 wrapper masks the defect in every hermetic callback test | DD:61-64, AT-16; submission emits top-level dict | `cb(manifest.to_dict(), ctx_placeholder)` | HIGH |
| S5 | Handler two-line fix (`hatchet.py:229-230`) | Wrong arity + v0 shape; SDK calls `fn(workflow_input, ctx)` with direct dict | SDK task.py; `runner.py:232-239`; DD:54-59 | `def handler(payload, ctx)` + `StageManifest.from_dict(payload["manifest"])`; tolerate absent `causation_id` (existing conditional key) | HIGH |
| S6 | Re-scope the local registration test honestly (`test_hatchet_live.py:1035-1080`) | Docstring claims "engine-visible"; test inspects local `Standalone` objects only, never starts the loop or queries the engine | `:1055-1080` | Rename to local-registration-shape test; engine-visible proof is AT-18 hosted assertion | HIGH |

## 7. Necessary complexity (justified keep-list)

| # | Item | Justification |
|---|---|---|
| K1 | Spec-first handler contract tests (AT-16) | Converts first-run discovery into hermetic failure (precedent F1 from ci-repair); two-to-three tests, no machinery |
| K2 | Tenant partition-eligibility discovery + fail-closed + recorded IDs + tenant agreement + assignment/runtime state (AT-17) | The actual L10 root cause; small WHERE-clause filter + assertions on existing evidence; assignment assertion is "submitted tasks get a worker assignment (worker_id non-null) and reach a terminal state" — QUEUED-with-no-assignment after a bounded window is a hard failure |
| K3 | `durable_task` surface + hosted `v1_task.is_durable=true` assertion (AT-18) | Requirement-grounded durable-flag; one-line surface + one hosted SQL/engine check. See N1 for the interpretation caveat |
| K4 | Honest readiness semantics (S1–S3) | Ledger requirement "no fake readiness"; pure deletions + one boolean tightening |
| K5 | Hosted rerun of the existing full path with retrieved evidence before docs/DoD closure | Ledger requirement; no new job/topology — rerun the same compose path |
| K6 | `durable_task` registration through `HatchetWorkerFactory.start` real-SDK branch | Replaces `client.task` at the existing decorator selection (`hatchet.py:417`) — change is `task`→`durable_task` preference, nothing else |

## 8. Residual risks (flag, do not build around)

| # | Risk | Note |
|---|---|---|
| N1 | `durable_task` is a requirement-interpretation decision, not a proven dispatch blocker | Debugger L9 flagged `is_durable=false` as contract mismatch; the actual dispatch blocker was tenant partitions (L10). AT-18's mandate is a defensible reading of "durable async"; keep it, but do not expand it (no eviction-policy tuning, no async conversion) |
| N2 | Sync handler via `durable_task` triggers an SDK deprecation warning ("non-async durable tasks deprecated") | Not a blocker at 1.38.1; keep the handler sync (`executor.run` is sync). Do NOT convert to async — that would touch the executor contract (out of scope) |
| N3 | SDK output serialization of the handler return (`StageRunRecord`) | The SDK coerces the returned value; completion authority is the persisted rows (AT-16). Verify `StageRunRecord` round-trips through the SDK output path during implementation; do not add a serializer layer speculatively |
| N4 | `causation_id` is a conditional input key | Handler must default it to `None`; existing behavior, keep |
| N5 | Q1/Q2 remain open and blocking | Q1 blocks the next hosted run (sandbox-runner env parity); Q2 blocks finalization (R18 tier-1 retrieval). Neither is a complexity decision |

## 9. Scope guardrails

1. Fix only the diagnosed defects: callback contract (AT-16), tenant selection/proof (AT-17), durable registration (AT-18), registration-failure surfacing, readiness truthfulness, hermetic alignment, honest local-test re-scope. Rerun the existing hosted path.
2. No redesign: split topology (8 services), Hatchet as sole scheduler, semantic architecture, execution authority, DurableStageExecutor contract.
3. Do not reopen ruled-out infrastructure causes: DB / token / endpoint / `run_workflow` semantics (support-debugger L12 eliminated these).
4. Reconcile, do not duplicate: the netns DD already carries AT-16–19; the live-blocker DD/plan amendment references them and extends only the four separate defects (suppress, readiness fallback, local-only test, assignment diagnostics).
5. No new machinery: no adapters, no dual-paths, no retry loops, no readiness abstractions, no engine-query test tooling, no new services.
6. No ledger or gate weakening: L1–L21, AT-1–15 unchanged; AT-16–19 join and are mandatory; Q1/Q2 gates remain.
7. Production stream edits are bounded to the diagnosed lines: `hatchet.py` (handler signature/manifest read, decorator selection → `durable_task`, suppress removal, `_ready` tightening), `cli.py` (fallback deletion), `tests/test_hatchet_live.py` (`_invoke_callback`, re-scope, new contract tests). Nothing else in `src/`, `deploy/`, or `.github/`.

## 10. Requirement-preservation check (L1–L21 + immutable constraints)

| Requirement | Status |
|---|---|
| Task.md DoD fully realized | Preserved — repair is additive; no DoD row weakened |
| Hatchet sole v1 scheduler | Preserved — no second scheduler; rejections R3/R5 keep the single registration path |
| Real callbacks / DurableStageExecutor | Preserved — the fix makes real callbacks actually fire (AT-16) |
| Durable async restart/retry/cancel/selective invalidation | Preserved — DurableStageExecutor + AT-16/18; no executor changes |
| No skips/stubs/fake readiness/recording doubles as release evidence | Preserved — S1–S3 remove fake-readiness paths; recording double remains hermetic-only |
| No weakening gates | Preserved — AT-19 composes AT-16–18 with AT-1–15, non-skippable |
| Hosted native Docker/Compose, public HTTP heterogeneous E2E, zero mandatory skips | Preserved — rerun existing path; no new skip |
| Retrieved evidence before docs/DoD closure | Preserved — K5 |
| OCFL / evidence / semantic / provenance invariants | Untouched — no semantic/evidence code changes in scope |
| Tenant: runnable tenant with non-null partitions; assert assignment/runtime state | Preserved — AT-17 (already in DD); the live-blocker amendment must keep it and extend assignment diagnostics only |

## 11. Acceptance criteria (for Exec-Manager)

- **AC1** Hermetic spec-first handler contract tests pass: `handler(payload, ctx)` two-arg; direct dict with top-level `manifest`; v0-wrapped payload raises; one-argument call raises `TypeError`; `ctx` placeholder unused; `DurableStageExecutor` invoked.
- **AC2** No v0 wrapper remains in tests: `_invoke_callback` and every hermetic callback fixture invoke `(manifest.to_dict(), ctx)`; a grep for `{"input":` in `tests/test_hatchet_live.py` fails.
- **AC3** Registration failures surface: `HatchetWorkerFactory.start` no longer swallows; a negative test forcing a decorator error raises; `cli.worker()` exits non-zero and does not print a readiness line.
- **AC4** Readiness truthfulness: `is_ready()` is False when zero workflows actually registered; `cli.py:123` fallback removed; ready line counts only `registered_workflows`; `wait-for-worker.sh` gate and `test_no_fake_gated_ready_claim` still pass.
- **AC5** Local registration test re-scoped honestly (name + docstring reflect local-shape proof); engine-visible proof owned by AT-18 hosted assertion.
- **AC6** Every release `umd-<stage>` registered via `client.durable_task(name=wf_name)(handler)`; no `client.task` for `umd-<stage>`; hosted DB/engine evidence asserts every submitted `v1_task.is_durable=true`.
- **AC7** Tenant: discovery yields exactly one setup-created or scheduler-eligible tenant with non-null `schedulerPartitionId` AND `workerPartitionId`; zero/multiple/null fail closed; selected tenant + both partition IDs recorded; JWT/worker/workflow/submitted-task tenants identical; submitted tasks receive worker assignment (`worker_id` non-null) and reach a terminal state — QUEUED-with-no-assignment after the bounded window is a hard failure.
- **AC8** Hosted rerun (successor to `33229130339`/`99038602321`) succeeds on the full 8-service split topology: real worker registration, live submissions execute callbacks to durable `stage_run`/`StageCompleted`/audit rows, zero mandatory skips, evidence (SHA/run URL/jobs/attempts/logs/JUnit/diagnostics) retrieved before docs/DoD closure, AT-1–19 joined, no fabricated readiness line, Q1/Q2 resolved per their gates.
- **AC9** Plan K diff is bounded: workflow/release-gate steps + the four fix contracts only; production stream edits limited to the diagnosed lines (§9.7); no topology/scheduler/semantic changes.

## 12. Post-adversarial assessment (T1–T8 complete)

*Amendment 2026-08-29, after the full eight-turn adversarial sequence concluded. The refiner artifact (header-only when this review was first written) now contains T1–T8 with the final pattern package F-1…F-7, human questions Q1–Q5, and risk register R1–R10. This section re-assesses that final package for necessity/scope, abstraction rejection, immutable-requirement preservation, blocking risks, and acceptance evidence. All in-tree claims re-verified at HEAD `6614b32` on 2026-08-29.*

### 12.1 Necessity/scope of the final package

Every element of F-1…F-7 traces to a diagnosed defect or binding contract; nothing is speculative future-proofing:

| Final pattern | Traces to | Necessity |
|---|---|---|
| F-1 durable registration + hard-fail + slot posture | L7.1 (suppress), AT-18 (`durable_task`/`is_durable`) | REQUIRED — deletes a fabrication path; one surface change (`hatchet.py:417-431`) |
| F-2 typed input boundary + JSON-safe return | L3/L5 (v1 contract), L12 (executor-owned durability), AT-16 | REQUIRED in shape; boundary decision in §12.2 RA1 |
| F-3 truthful candidate readiness | L7.2 (`cli.py:123` fallback) | REQUIRED — pure deletion + boolean tightening |
| F-4 engine-visible declaration assertion (A3′) | L7.3/L19 ("engine-visible proof or honest test scope") | OPTIONAL — test-only; Q3 keeps or drops it; must stay non-authority |
| F-5 tenant eligibility + identity + assignment block | L8/AT-17 (run 33229130339 root cause) | REQUIRED — workflow-side, fail-closed |
| F-6 hermetic/live contract tests | L4 (hermetic mask), AT-16 | REQUIRED — fixtures + real-SDK negative tests |
| F-7 error handling/observability | unchanged | REQUIRED — no new machinery |

Scope is bounded to: `hatchet.py` (handler signature/manifest read, decorator selection → `durable_task`, suppress deletion, `_ready` tightening), `cli.py` (fallback deletion), `tests/test_hatchet_live.py` (fixtures, re-scope, new contract tests), plus workflow/gate evidence steps. No topology, scheduler, executor, or semantic changes. The deferred A4 (async handler) stays deferred — the correct non-expansion.

### 12.2 Abstractions to reject in the final package

The adversarial process already killed the worst offenders: A4 deferred, and the `client.task` fallback chain replaced with hard-fail on missing `durable_task`. Four residual abstraction risks remain that the DD/plan must enforce:

| # | Abstraction | Rejection reason | Guard |
|---|---|---|---|
| RA1 | Ship BOTH A2′ (typed `UmdStageInput`) and A1′ (dict) as a runtime-selectable dual path | A2′ and A1′ are mutually exclusive *decisions*, not a switch. A production flag/capability detection re-creates the R5 dual-path pattern the adversarial process killed in the registration branch | Exactly ONE ships, chosen by the Q2 mypy spike; the other is a fully-specified fallback, never a runtime branch |
| RA2 | Mixed durable/standard registration as the default posture | Q1's "mixed" option splits registration into two paths and expands the engine-assignment surface; all-durable is the literal AT-18 contract and the single-path default | Ship all-durable; if hosted ASSIGNED/RUNNING fails, investigate engine slot config first — mixed registration is a separate DD decision, never an on-the-fly change |
| RA3 | JSON-safe return as a serializer/response layer | `StageRunRecord` is a `@dataclass` (`stage_execution.py:153`) — the SDK's step-output `TypeAdapter` handles dataclasses, so the "non-JSON rejection" risk is smaller than the adversarial doc implies. F-2's return is a one-line dict extraction, fine; a serializer layer is not | Keep the return as `{"idempotency_key", "state", "attempts"}` or the record itself — whichever the Q2 spike confirms; no schema/response model |
| RA4 | A3′ growing into a proof mechanism / gating authority | `workflows.list()` proves declaration rows only — never callback, durability, or assignment. As a release gate it would be a false-positive (L13/L14) | A3′ stays a non-authority diagnostic composed under AT-19; DB-dump + callback-rows gate remains release authority; Q3's "drop it" option is legitimate if REST shape proves brittle |

### 12.3 Simplifications confirmed (post-T8)

The final package confirms the six simplifications S1–S6 from §6 verbatim, and the adversarial process removed three further constructs the earlier review flagged as risk:

- **S1' (kills R4 in §5):** the registration branch hard-fails on missing `durable_task` — no retry loop, no capability detection, no `getattr` fallback chain. Simplest correct behavior.
- **S2' (kills R5 in §5):** single registration surface `client.durable_task(name=wf_name)(handler)` — the dual `task`/`durable_task` switch is deleted, not introduced.
- **S3' (kills R3 in §5):** the local test is renamed to honest local scope; A3′ is a separate *hosted* additive test, so no engine-query machinery was added to the local cluster test.
- **S4' (kills R2 in §5):** `_FakeCtx()` is a placeholder with an invariant comment, not a context class hierarchy; contract tests prefer real-SDK `mock_run` where the handler shape matters.
- **N1 update (§8):** the earlier "no eviction-policy tuning" caution is superseded by Q4's explicit `eviction_policy=None` — a one-keyword explicitness (the handler never uses durable wait primitives), not tuning machinery. Async conversion (N2) remains correctly deferred.

### 12.4 Immutable requirements — all preserved

- **L1–L21:** T8 §5 verifies each item explicitly; this review independently confirms no pattern weakens any ledger item. L6 (ruled-out infra) is explicitly out-of-scope-unchanged (PR-10/R10 guard).
- **AT-16/17/18/19:** implemented (F-2/F-6, F-5, F-1, composition) not duplicated — the netns DD remains binding authority.
- **L16 (OCFL/evidence/provenance):** untouched — no semantic/evidence code in scope.
- **L20 (no production edits by design agents):** the adversarial artifact appended only; this review writes only this report.

### 12.5 Blocking risks (do not build around — resolve or fail closed)

| # | Risk | Nature | Resolution gate |
|---|---|---|---|
| B1 | **Durable-slot assignment (R1/PR-1)** — all-durable registration may not get durable slots from v0.105.2, reproducing queued-but-unassigned on the durable axis | BLOCKING until hosted-proven | First hosted run must show `v1_task` ASSIGNED/RUNNING + `v1_task_runtime`/`WorkerAssignEvent` + callback-owned rows before Phase 6 (AT-19); `is_durable=true` alone is NOT proof |
| B2 | **Strict-mypy overload acceptance (R2/PR-2)** — `UmdStageInput` typed overloads may be rejected by the installed wheel | MEDIUM, pre-implementation | Minimal typed-registration spike FIRST; A1′ is the recorded mechanical fallback (Q2) |
| B3 | **REST `workflows.list()` shape (R5/PR-5)** — pagination/filter semantics unverified | MEDIUM | One-probe on the first hosted run; A3′ is non-authority so it cannot block AT-16/17/18 |
| B4 | **Latest-version scoping (R6/PR-6)** — `is_durable=true` on a stale workflow version | MEDIUM | Hosted SQL keys the latest `WorkflowVersion` per `umd-<stage>` |
| B5 | **Gate polling (R4/PR-4)** — SDK ack accepted before durable rows exist | MEDIUM | `_poll_until` for rows; never ack-only |

### 12.6 Human questions with complexity framing (Q1–Q5)

- **Q1 (durable posture):** all-durable is the single-path default and the literal AT-18 contract — complexity-correct. Mixed registration is a dual path; reject as default (RA2).
- **Q2 (typed vs dict):** A2′ adds one small model mirroring `runner.py:232-245`; it is the only faithful `mock_run` serialization in 1.38.1. Acceptable complexity IF the spike passes; A1′ is the simpler floor. Never ship both (RA1).
- **Q3 (A3′ keep/drop):** keep as non-authority diagnostic (in-suite engine visibility) or drop — both acceptable; do NOT let it acquire gate authority (RA4).
- **Q4 (`eviction_policy=None`):** explicit one-arg choice; correct because the handler never uses durable wait primitives.
- **Q5 (sync-durable debt):** ship sync-durable with the recorded deprecation note; A4 deferred is the correct non-expansion.

### 12.7 Acceptance evidence mapping (post-T8)

The §11 AC1–AC9 list stands. Post-T8 additions/clarifications:

- **AC1′** (covers F-2): handler `(input, ctx)` with direct input — typed `UmdStageInput` (A2′) OR `dict` (A1′), exactly one; v0-wrapped and one-arg shapes fail; `UmdStageInput.model_validate(direct_input)` equals the fixture input (kills the mini-L4 mask).
- **AC4′** (covers F-3): candidate readiness (C6 line) ≠ engine-visible declaration (A3′) ≠ release proof (AT-16/17/18) — terminology contract in the DD/plan.
- **AC6′** (covers F-1/F-5): `durable_task` present ⇒ hard-fail registration; all release tasks durable; hosted `v1_task.is_durable=true` scoped to the latest version AND tasks transition to ASSIGNED/RUNNING (B1).
- **AC8′** (covers B1/B3): the first hosted run's evidence includes assignment transitions, callback rows, and the A3′ one-probe REST shape capture.

## 13. Verdict (amended post-T8)

```yaml
status: DONE
target: "artifacts/designs/process/universal-media-decomposer-plan-k-hatchet-live-blocker-complexity-review.md"

structure:
  defects_diagnosed: 5        # handler contract, hermetic masking, suppressed registration, fabricated readiness, local-only test
  prior_defect_preserved: 1   # tenant selection / AT-17
  sdk_facts_verified: 4       # fn(input, ctx) arity; direct input; is_durable; durable_task facade (tag py/1.38.1)
  rejected_abstractions: 6    # R1-R6
  prescribed_simplifications: 6  # S1-S6
  residual_risks: 5           # N1-N5
  post_t8_rejected_abstractions: 4  # RA1-RA4 (A2'/A1' dual path, mixed durable, serializer layer, A3' as gate)
  post_t8_blocking_risks: 5         # B1-B5 (durable-slot, mypy spike, REST shape, latest-version, gate polling)

findings:
  - location: "src/umd/jobs/hatchet.py:229-230 (handler)"
    concern: "Wrong arity and v0 payload shape for SDK 1.38.1"
    evidence: "SDK task.py invokes fn(workflow_input, ctx); runner.py:232-239 emits top-level dict; run 33229130339 all tasks failed pre-UMD"
    alternative: "def handler(payload, ctx) reading payload['manifest']"
    confidence: HIGH
  - location: "src/umd/jobs/hatchet.py:423-431 (suppress)"
    concern: "contextlib.suppress hides real registration/decoration errors"
    evidence: "Decorative registration executes immediately; suppression left registered_workflows empty while _ready stayed True"
    alternative: "Remove suppress; propagate to cli.worker() exit 2"
    confidence: HIGH
  - location: "src/umd/deploy/cli.py:123 + hatchet.py:446 (_ready)"
    concern: "Fabricated readiness count and readiness boolean"
    evidence: "n_workflows falls back to len(work_registry); _ready=callbacks_bound True with zero registrations"
    alternative: "Count only registered_workflows; _ready = callbacks_bound and bool(registered_workflows)"
    confidence: HIGH
  - location: "tests/test_hatchet_live.py:459-464 (_invoke_callback)"
    concern: "Hermetic fixtures encode the wrong v0 contract, masking the defect"
    evidence: "cb({'input': {'manifest': ...}}) vs SDK fn(input, ctx)"
    alternative: "cb(manifest.to_dict(), ctx_placeholder)"
    confidence: HIGH
  - location: "tests/test_hatchet_live.py:1035-1080 (registration test)"
    concern: "'engine-visible' name overclaims; inspects local Standalone objects only"
    evidence: "No worker loop, no engine query; getattr(wf, 'name') on local objects"
    alternative: "Honest re-scope; engine-visible proof via AT-18 hosted v1_task.is_durable=true"
    confidence: HIGH
  - location: "AT-18 durable_task mandate (netns DD:80-88,185-188)"
    concern: "Requirement-interpretation decision, not proven dispatch blocker (L10 was tenant partitions)"
    evidence: "Debugger L9 flagged is_durable=false; L10 root-caused dispatch to tenant partitions"
    alternative: "Keep AT-18 (requirement-grounded, one line + one assertion); do not expand (N1/N2)"
    confidence: MEDIUM

verdict:
  complexity_level: APPROPRIATE
  justified: true
  summary: "The proposed repair is bounded to the diagnosed callback/registration/readiness/tenant-proof defects and reruns the existing hosted path. Six implementation-time abstractions (R1-R6) must be rejected and six simplifications (S1-S6) applied to keep the DD/Plan K amendment exactly defect-sized. Necessary complexity (AT-16/17/18, honest readiness, hosted rerun) is evidence-justified. Post-T8: the final adversarial package (F-1...F-7) is confirmed defect-sized; enforce RA1-RA4 guards and treat B1 (durable-slot assignment) as the blocking pre-Phase-6 proof per §12."

recommendation: |
  Hand to RnD-Refiner / RnD-DDAuthor:
  1. Reference the netns DD AT-16-19 as the fix contracts; extend Plan K with the four separate defects (suppress, readiness fallback, local-only test re-scope, assignment diagnostics) — do not create a parallel DD for these contracts.
  2. Apply S1-S6 exactly as written; reject R1-R6 in the design/plan.
  3. Keep AT-17 tenant-partition eligibility + assignment/runtime state assertions verbatim (prior defect preservation).
  4. Keep the handler sync; flag N2/N3 in the implementation notes; do not add serializers or async conversion.
  5. Acceptance = AC1-AC9, with the hosted rerun (AC8) as the release gate evidence before docs/DoD closure.
  6. Post-T8: adopt F-1...F-7 with the RA1-RA4 guards (§12.2) — exactly ONE of A2′/A1′ ships (Q2 spike decides); all-durable default (Q1); A3′ non-authority (Q3); no serializer layer (RA3).
  7. Blocking gates before Phase 6: B1 durable-slot assignment proven hosted (ASSIGNED/RUNNING + callback rows), B2 mypy spike resolved before fixtures, B3/B4/B5 evidence captured per §12.5.
```

## 14. Citations / check dates

- Hatchet SDK source, tag `py/1.38.1`: `sdks/python/hatchet_sdk/runnables/task.py` (`Task.call`/`aio_call`, `to_proto`, `mock_run`), `sdks/python/hatchet_sdk/hatchet.py` (`Hatchet.task`, `Hatchet.durable_task`, `Hatchet.worker`), `sdks/python/hatchet_sdk/__init__.py`. Fetched from `https://raw.githubusercontent.com/hatchet-dev/hatchet/py/1.38.1/...` on 2026-08-29.
- Local repo: `src/umd/jobs/hatchet.py`, `src/umd/jobs/runner.py`, `src/umd/deploy/cli.py`, `tests/test_hatchet_live.py` at HEAD `6614b32`.
- Artifacts: netns DD (`AT-16:174-178`, `AT-17:180-183`, `AT-18:185-188`, `AT-19:190-193`, `Additional hosted evidence:247`); Plan K; `artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-plan-k-live-hatchet-blocker.md` (header only at review time).
- Logs: `support-researcher.log.jsonl:L9`, `support-debugger.log.jsonl:L8-L12`, `support-librarian.log.jsonl:L37/L22`.
- Hosted: run `33229130339`, job `99038602321` (decisive live blocker).

## 15. Handoff

- **To:** RnD-Refiner (sore-salmon-kite), then RnD-DDAuthor, then RnD-Estimator, then Support-PatternEnforcer, then Exec-Manager via the formal pipeline.
- **Key message:** the fix surface is the diagnosed defects only; reject R1–R6, apply S1–S6, preserve AT-16–19 and the tenant-proof requirement verbatim, rerun the existing hosted path (AC8), and keep the handler sync (N2/N3 flagged, not built around). Post-T8: adopt F-1…F-7 with the RA1–RA4 guards; B1 (durable-slot assignment) is the blocking pre-Phase-6 proof; the Q2 spike chooses A2′/A1′ — one, never both.
