# Adversarial Design Log: Plan K Live Hatchet Blocker — SDK 1.38.1 v1 Callback Contract Repair

*This file records the full adversarial refinement process for the newly diagnosed live Hatchet blocker in Plan K (run 33229130339 / Docker job 99038602321). The downstream DD (produced by rnd-dd-author) and Plan K amendment (produced by exec-planner) distill decisions from this raw debate. This file is the shared scratch pad for the mandatory eight-turn adversarial sequence: Ideator ↔ Counter-Ideator, then Improver ↔ Counter-Improver.*

*Scope boundary: this artifact covers ONLY adversarial refinement of the live Hatchet blocker and its reconcilable obligations. It does NOT edit production code, tests, workflows, DDs, or implementation plans. It does NOT create a competing DD or duplicate gate authority — AT-16/AT-17/AT-18/AT-19 in `artifacts/designs/pending/DD-universal-media-decomposer-plan-k-netns-workflow-amendment.md` remain binding and must be reconciled, not duplicated.*

---

## 1. Original user request (verbatim, immutable)

> Continue formal Plan K R&D workflow for the newly diagnosed live Hatchet blocker. Support evidence is decisive: run 33229130339 Docker job 99038602321 reached full split topology, API readiness, genuine worker registration, external HTTP, and live submissions. Every live task then failed before UMD execution because Hatchet SDK 1.38.1 invokes task callbacks as fn(workflow_input, ctx), while src/umd/jobs/hatchet.py:_make_handler returns handler(payload) and expects payload['input']['manifest'] (v0 shape). Hermetic tests/test_hatchet_live.py:_invoke_callback at ~459 encode the same wrong wrapper, masking defect. Correct v1 input is direct dict with manifest. DB/token/endpoint/run_workflow semantics are ruled out. Separate defects: HatchetWorkerFactory.start swallows real decorator exceptions and cli.py readiness count falls back to len(work_registry), allowing fabricated readiness; engine-visible registration test only inspects local Standalone objects. Also prior tenant-selection bug was fixed/diagnosed, but preserve requirement to select runnable tenant with non-null partitions and assert assignment/runtime state.

> Original user/task constraints immutable: Task.md Universal Media Decomposer DoD fully realized; Hatchet sole v1 scheduler; real callbacks/DurableStageExecutor; durable async restart/retry/cancel/selective invalidation; no skips/stubs/fake readiness/recording doubles as release evidence; no weakening gates; hosted native Docker/Compose, public HTTP heterogeneous E2E, zero mandatory skips, retrieved evidence before docs/DoD closure; preserve OCFL/evidence/semantic/provenance invariants.

> Run required R&D formal process (librarian/researcher, adversarial refinement, architect, complexity, estimator, DDAuthor, PatternEnforcer; no skipped stages) and create/amend validated implementation plan under artifacts/plans/pending. Explicitly plan spec-first handler contract tests, real callback fix, hermetic test alignment without lowering live gate, surfaced registration failures/readiness truthfulness, engine-visible proof or honest test scope, assignment/runtime diagnostics, and rerun hosted CI. Do not edit production/workflow/tests yourself. Return plan paths, requirement ledger, risks, exact acceptance evidence for Exec-Manager.

## 2. Immutable requirement ledger (must be reproduced unchanged and checked every turn)

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

## 3. Decisive evidence (authoritative; do not rediscover blindly)

- **Live baseline:** GitHub Actions run `33229130339`, Docker job `99038602321`, SHA `6614b32`. Reached: full split Hatchet topology, API readiness, genuine worker registration (`umd-worker`, SDK 1.38.1, heartbeat, 9 `_ActionToWorker` links, exact `umd-*` action IDs), external HTTP, and 46 live submissions (46 `v1_task` / 46 `v1_run` rows, `readable_status=QUEUED`). **Zero** assignments, zero `v1_task_runtime`/`StepRun`/`WorkerAssignEvent` rows, zero callback-owned UMD rows (`stage_run`, `StageCompleted`, job audit). Do NOT misstate as successful execution.
- **Primary root cause (L3):** pinned SDK 1.38.1 invokes a task handler registered via `client.task(name=...)(fn)` as `fn(workflow_input, ctx)` — TWO positional args (SDK `Task.call`/`aio_call` in `sdks/python/hatchet_sdk/runnables/task.py`). `src/umd/jobs/hatchet.py:229` `_make_handler` returns `def handler(payload)` — ONE param, body `payload["input"]["manifest"]` (v0 full-payload wrapper). Every live dispatch raises `TypeError: handler() takes 1 positional argument but 2 were given`; retries=0 → task FAILED instantly → zero stage_run rows. Even with arity fixed, `payload["input"]` would `KeyError` — v1 passes the run input dict directly (`{job_id, source_id, dag_universe, stage, manifest}`), no `"input"` wrapper. Correct v1 input (L5) is a direct dict carrying `manifest`.
- **Hermetic mask (L4):** `tests/test_hatchet_live.py:459-464` `_invoke_callback` invokes `cb({"input": {"manifest": manifest.to_dict()}})`, encoding the same wrong v0 wrapper; hermetic tests pass while live fails.
- **Ruled out (L6):** DB mismatch (shared compose `umd` db via published 5432; dump shows same tenant-scoped rows), JWT/token (sync gRPC `run_workflow` succeeded; token accepted for registration), endpoint/gRPC routing (host→127.0.0.1:7070 and worker→hatchet-engine:7070 both work), `run_workflow` submission shape (SDK 1.38.1 `AdminClient.run_workflow(workflow_name, input, options=...)` accepts two positional args). See `artifacts/logs/support-debugger.log.jsonl:L12`, `artifacts/logs/support-researcher.log.jsonl:L9`.
- **Separate defects (L7):**
  1. `src/umd/jobs/hatchet.py:426` — `HatchetWorkerFactory.start` wraps real-SDK registration in `contextlib.suppress(Exception)`, so a real decorator failure is silently swallowed and `registered_workflows` can stay empty.
  2. `src/umd/deploy/cli.py:123` — readiness count `n_workflows = len(handle.registered_workflows) or (len(work_registry) if work_registry else 0)` falls back to `len(work_registry)`, so `worker ready: registered 9 Hatchet workflows` can print with an EMPTY registered list; `wait-for-worker.sh` greps the line, not the engine → fabricated readiness.
  3. `tests/test_hatchet_live.py:1035-1080` `test_live_hatchet_engine_visible_registration_exact_umd_stages` asserts only LOCAL `Standalone`/`Workflow` objects from `factory.start`; it never calls `worker.start()`, never contacts the engine → not engine-visible proof. Either make it genuinely engine-visible or rename/honestly scope it.
- **Tenant partition requirement (L8):** run 33229130339 diagnosed: `validation.yml` discovered first `Tenant` by `createdAt` = system `internal` tenant `8d420720-ef03-41dc-9c73-1c93f276db97` with `schedulerPartitionId=NULL`/`workerPartitionId=NULL`; the `Default` tenant `707d0855-80ab-4e1f-a156-f1c4546cbf52` has both partitions populated and is the only scheduler-eligible one. Requirement preserved: deterministically select a runnable tenant with non-null scheduler+worker partition IDs, assert JWT/worker/workflow/submitted-task tenant identity + assignment/runtime state, fail closed otherwise. (`support-debugger.log.jsonl:L10-L11`; netns DD AT-17.)
- **Durable task registration:** hosted dump shows `v1_task.is_durable=false` for all submitted tasks because `HatchetWorkerFactory.start` uses `client.task(name=wf_name)` not `client.durable_task(name=wf_name)`. Netns DD AT-18 requires `client.durable_task(...)` registration and hosted `v1_task.is_durable=true` assertion. This is a contract mismatch to be addressed in this adversarial process; do not conflate it with the dispatch blocker (L9 support-debugger observation). (`support-debugger.log.jsonl:L9`.)

## 4. Existing artifacts to reconcile (do not duplicate authority)

- **Plan K:** `artifacts/plans/pending/TASK-universal-media-decomposer-K-ci-repair-release-gate.md`. Phases 1–4 are historical implementation claims that must be revalidated by hosted evidence; Phase 5 (docs) and Phase 6 (QA/DoD) are pending. P2-S2/P2-S5 note lines describe `_make_handler`/`cli.worker()` as Done — those claims are falsified by run 33229130339 for live execution.
- **Netns DD (binding AT-16…AT-19):** `artifacts/designs/pending/DD-universal-media-decomposer-plan-k-netns-workflow-amendment.md`. AT-16 = pinned SDK 1.38.1 v1 `(input, ctx)` direct-input callback contract, real-SDK-shaped test fails on one-arg/v0 payload, callback-owned durable rows, hosted observed callback + rows; AT-17 = deterministic scheduler-eligible tenant (non-null partitions, tenant identity consistency, readiness alone fails); AT-18 = pinned `client.durable_task(name=wf_name)` registration + hosted `v1_task.is_durable=true`; AT-19 = pre-Phase-6 gate composition (AT-16+17+18 joined with AT-1…15, release-blocking on failure/skip/readiness-only). This adversarial scope must reconcile with AT-16/17/18/19 authority — implementable evidence, not a parallel gate set.
- **Product CI DD:** `artifacts/designs/pending/DD-universal-media-decomposer-ci-repair.md` — approved architecture A + minimal C; C1–C8 constraints (Hatchet sole scheduler; candidate pair; readiness line C6; no doubles as release evidence).
- **Binding contracts:** `artifacts/designs/parts/universal-media-decomposer/CONTRACTS.md` §§58–63 (`StageWorkRegistryFactory.build`, `ProductionDAGRunner.run_graph`, `HatchetWorkerFactory.start`, `CapabilityReporter.report`).
- **Handoff:** `artifacts/designs/parts/universal-media-decomposer/HATCHET_LIVE_VALIDATION_HANDOFF.md` — §6 is STALE about recording clients (trust current tree and support findings); §3 readiness signal contract remains relevant (ready line emitted immediately before blocking `worker.start()`; candidate until live proof).
- **Support logs (decisive):** `artifacts/logs/support-researcher.log.jsonl:L9`; `artifacts/logs/support-debugger.log.jsonl:L8, L9, L10, L11, L12`; `artifacts/logs/rnd-manager.log.jsonl:L35-L37`.

## 5. Technology-choice invariant (applies every turn)

Whenever a turn introduces, compares, upgrades, or relies on a technology, library, framework, SDK, platform, runtime, protocol, or version (especially `hatchet-sdk==1.38.1`, server `v0.105.2`, `client.task` vs `client.durable_task`, callback arity/input contract, worker registration surfaces), the responsible agent MUST validate it against current official or maintainer sources (PyPI, GitHub SDK source at the pinned tag, official Hatchet docs, server release notes). Check support status, compatibility, deprecations, security caveats, and relevant limitations, and explain best fit for THIS project's constraints. Record source and check date. Newest is not automatically best; unvalidated claims must be labeled provisional. Hosted runs remain the release authority; technology/reference evidence is non-execution.

## 6. Mandatory turn contract (T1–T8, sequential, substantive, cited)

All eight turns MUST be substantive, MUST cite evidence, MUST check the L1–L21 ledger, and MUST append under the exact section headings below. No skipped, merged, or generic turns. Prior sections must not be deleted or corrupted.

- **T1 Ideator** → append under `## Proposed Approaches`: 2–4 bounded architectural approaches to fix the live Hatchet blocker while preserving every ledger item; per approach, websearch evidence of a real production system using it; validate every technology/version choice.
- **T2 Counter-Ideator** → append under `## Critique`: per-approach documented failures/postmortems/limitations; explain why each criticism applies (or not) to THIS context; cover handler arity/input, durable_task/is_durable, factory exception visibility, readiness truthfulness, engine-visible proof, tenant partitions/runtime assignment, hermetic/live gate separation, overlap with netns DD; rank citations by evidence tier; flag approaches that don't survive; verify technology claims rather than accepting them.
- **T3 Ideator** → append under `## Refined Approaches`: refine surviving approaches into implementable candidate patterns + explicit test/evidence design; drop dead approaches with reasons; revalidate changed/consequential technology choices.
- **T4 Counter-Ideator** → append under `## Surviving Concerns`: assess whether refinements actually address the T2 critique; identify remaining failure modes and unresolvable questions; be honest about what is unresolved.
- **T5 Improver** → append under `## Implementation Patterns`: concrete implementation patterns (data flow, state management, error handling, testing approach, key library choices) for the surviving approaches; per-pattern real-world best-practice citations; validate each key library/version; exact phased plan obligations for code/tests/workflow/evidence (read-only design scope).
- **T6 Counter-Improver** → append under `## Pattern Risks`: per-pattern edge cases, integration risks, library-specific gotchas, cross-pattern interaction failures against the pinned SDK/server and hosted evidence; cite GitHub issues, docs, production incidents; check whether reported risks apply to the CURRENT supported version; find false positives, races, stale docs, gate bypasses.
- **T7 Improver** → append under `## Final Patterns`: final mitigated patterns with requirement-to-evidence mapping; reconcile AT-16/17/18/19 authority; revalidate affected technologies with source/check-date; label fundamental limitations.
- **T8 Counter-Improver** → append under `## Open Risks & Human Questions`: residual risks, human-judgment questions (substantive, well-contextualized tradeoffs), blockers, final recommendation; explicitly verify every L1–L21 survives.

---
*Sections below are appended by design agents during adversarial refinement.*
---

## Proposed Approaches

*(T1 Ideator, 2026-08-29. Scope: bounded architectural approaches to repair the live Hatchet v1 callback blocker (L3/L4/L5), the L7 sub-defects, and the durable-task contract (AT-18) while preserving L1–L21 and reconciling — not duplicating — AT-16/17/18/19 authority in the netns DD. Design-only: no production code, tests, workflows, DDs, or plans were edited this turn; only this log was appended.)*

### 0. Shared verified technology facts (checked 2026-08-29 against primary sources; §5 invariant)

| Claim | Primary source | Status |
|---|---|---|
| SDK 1.38.1 invokes a task handler as `fn(workflow_input, ctx)` — TWO positional args; direct input, no v0 `{"input": ...}` wrapper | `Task.call`/`aio_call` in `sdks/python/hatchet_sdk/runnables/task.py` at tag `py/1.38.1` (`self._fn(workflow_input, cast(Context, ctx), **dependencies)`); `BaseWorkflow._get_workflow_input` → `input_validator.validate_python(ctx._workflow_input)` in `runnables/workflow.py`; docs https://docs.hatchet.run/v1/tasks ("the arguments to the task are passed *positionally*") and https://docs.hatchet.run/v1/migrating/migration-guide-python | VERIFIED |
| Default `input_validator` is `EmptyModel` = Pydantic `BaseModel` with `ConfigDict(extra="allow", frozen=True)` and NO `__getitem__` → `input["manifest"]` FAILS on the default validator; dict-style access requires `input_validator=dict`, and attribute access requires a typed model | `runnables/types.py` at `py/1.38.1`; https://docs.hatchet.run/reference/python/pydantic | VERIFIED — this is a correction to prior analysis that implied `input["manifest"]` works with the default; every approach below fixes registration to supply a subscriptable/typed input |
| `client.durable_task(*, name=..., eviction_policy=...)` exists on `Hatchet` and returns `Standalone`; `Task.to_proto` emits `is_durable=self._is_durable`; a SYNC durable handler still runs in 1.38.1 but warns "Non-async durable tasks are deprecated and will be removed in v2.0.0" | `hatchet.py` + `task.py` at `py/1.38.1`; https://docs.hatchet.run/v1/durable-tasks | VERIFIED |
| `Hatchet.worker(name, workflows=[...])` requires `Workflow`/`Standalone` instances (TypeError otherwise); `Worker.start()` blocks and performs `register_workflows` → `admin.put_workflow(wf.to_proto())` — the ONLY engine-visible registration path (researcher L10) | `hatchet.py` at `py/1.38.1`; https://docs.hatchet.run/v1/workers ("When a worker starts, it registers each of its tasks and workflows with Hatchet. From that point on, Hatchet knows to route matching tasks to that worker.") | VERIFIED |
| `Standalone.mock_run(input=...)` / `aio_mock_run` exist for engine-free task tests; `_create_mock_context` serializes input ONLY from Pydantic models/dataclasses (`model_dump`/`asdict`) — a raw `dict` input is silently dropped to `{}` | `task.py` at `py/1.38.1` | VERIFIED — real-SDK-shaped hermetic tests must pass a Pydantic model to `mock_run`, or invoke the handler with two args directly |
| `hatchet-sdk==1.38.1` (PyPI current, Python `<4,>=3.10`) released 2026-08-25; server `v0.105.2` released 2026-08-25; pair stays the pinned CANDIDATE per CI DD C4 | https://pypi.org/project/hatchet-sdk/1.38.1/ ; https://github.com/hatchet-dev/hatchet/releases/tag/v0.105.2 ; https://github.com/hatchet-dev/hatchet/releases/tag/py/1.38.1 | VERIFIED |
| `TypeAdapter(dict)` works as `input_validator` and `TWorkflowInput` bound includes `dict[str, Any]`; REST `client.workflows.list(workflow_name=...)` (the `Workflow.id` surface) returns engine-visible workflows | pydantic TypeAdapter semantics; `runnables/workflow.py` at `py/1.38.1` | PROVISIONAL — confirm at implementation: strict-mypy overload acceptance of `input_validator=dict`/typed model, and the exact REST response shape for A3's durability metadata |

Production-pattern evidence (Tier 1, non-execution): Hatchet self-hosters running real positional-handler tasks at scale — Aevy (AI document pipelines, 50k docs/project, self-hosted; https://hatchet.run/customers/aevy), Distill (deep research over millions of records; https://hatchet.run/), Happenstance (hundreds of thousands of tasks/day). These validate the platform pattern (worker registers tasks → engine routes → `(input, ctx)` handler executes) at production scale; they are not evidence about this repository's wiring.

### Approach 1 — A1 "Direct-Dict Minimal Contract Repair" (conventional / minimal)

**What it changes (exact files/functions):**
- `src/umd/jobs/hatchet.py` `_make_handler` (line 209): return `def handler(input: Any, ctx: Any)` reading `StageManifest.from_dict(input["manifest"])`; delete the v0 `payload["input"]["manifest"]` read (line 230).
- Registration loop (lines 417-431): resolve `decorator = getattr(client, "durable_task", None) or getattr(client, "task", None) or getattr(client, "workflow", None)` and call `decorator(name=wf_name, input_validator=dict)(_make_handler(...))`.
- Lines 423-431: DELETE `contextlib.suppress(Exception)`; after the loop, `if len(registered_workflows) != len(STAGE_ORDER): raise ConfigurationError(...)` naming the missing `umd-<stage>` names. A real decorator failure now surfaces as a hard failure.
- `src/umd/deploy/cli.py` line 123: `n_workflows = len(handle.registered_workflows)` only; remove the `or (len(work_registry) if work_registry else 0)` fallback; if the count is not exactly `len(STAGE_ORDER)`, print to stderr and return non-zero BEFORE the ready line (which remains the C6 candidate wording).
- `tests/test_hatchet_live.py`: `_invoke_callback` (lines 459-464) → `cb(_direct_input(manifest), _FakeCtx())` where `_direct_input` mirrors the runner.py:232-245 submission shape `{job_id, source_id, dag_universe, stage, manifest}`; line 1393 → `cb(sub["input"], _FakeCtx())`; `_RecordingClient` (lines 175-203) gains a `durable_task` alias recording into `callbacks`/`workflows`; rename test at lines 1035-1080 to `test_hatchet_registration_surface_local_bindings` (honest scope, below).

**Handler arity/input contract (L3/L5):** `(input, ctx)` with the direct dict; `input_validator=dict` makes `_get_workflow_input` return a real dict, so `input["manifest"]` is exact and never KeyErrors on the v0 wrapper (verified in §0 — the default EmptyModel is not subscriptable).
**Surfaces registration failures (L7.1):** suppress removed; partial registration raises `ConfigurationError` listing missing stages; `cli.worker()` fails closed.
**Truthful readiness (L7.2):** count = actual registered `Standalone` objects; exact-count mismatch exits non-zero before the ready line; no fallback to `len(work_registry)`; `wait-for-worker.sh` no longer sees a fabricated count.
**Engine-visible proof (L7.3):** honest scoping — the local test is renamed because without `worker.start()` it can only prove local bindings (researcher L10); engine visibility is proven by the hosted gate's existing engine-side assertions (netns DD AT-16/17/18 DB-dump rows + callback-owned rows). No invented proof.
**durable_task/is_durable (AT-18):** `client.durable_task(name=wf_name, input_validator=dict)` → `v1_task.is_durable=true`; sync handler is accepted in 1.38.1 with a deprecation warning (v2.0.0 will require async) — recorded as a forward-compat note, not a weakening.
**Tenant eligibility (AT-17):** untouched — tenant selection stays in the workflow (`validation.yml` P2-S4); the worker uses the same env token as submission, preserving token-tenant == worker-tenant == task-tenant consistency; no code path changes tenant identity or partition assertions.
**Hermetic alignment without lowering the live gate (L4/L19):** hermetic fixtures move to the true v1 two-arg shape; a new real-SDK-shaped negative test asserts a one-arg handler and a v0-wrapped payload fail; the hosted gate (AT-16/17/18/19) is unchanged and remains release-blocking.

**Evidence:** https://docs.hatchet.run/v1/tasks ; https://github.com/hatchet-dev/hatchet/blob/py/1.38.1/sdks/python/hatchet_sdk/runnables/task.py ; production: https://hatchet.run/customers/aevy
**Feasibility: HIGH** — smallest diff, no concurrency change, all SDK surfaces verified.

### Approach 2 — A2 "Typed Pydantic Input Boundary" (extensible)

**What it changes (exact):** the A1 surfacing/readiness/durable/tenant mechanics, PLUS:
- New `UmdStageInput(BaseModel)` in `src/umd/jobs/hatchet.py` (fields `job_id`, `source_id`, `dag_universe`, `stage`, `manifest`, optional `causation_id`) registered as `input_validator` on `client.durable_task(name=wf_name, input_validator=UmdStageInput)`.
- `_make_handler` returns `def handler(input: UmdStageInput, ctx: Any)` reading `input.manifest` (attribute access; runtime-validated at the SDK boundary).
- Hermetic `_invoke_callback` passes `UmdStageInput(**direct_input)`; the real-SDK-shaped tests use `Standalone.mock_run(input=UmdStageInput(...))` — the only input form `_create_mock_context` serializes faithfully in 1.38.1 (verified §0).

**Distinct mechanism:** validation/typing authority moves to the SDK `input_validator` boundary — malformed payloads produce structured validation errors before UMD code, and the handler contract is statically checked (strict mypy) instead of ad-hoc dict subscripting. The engine still receives the same direct submission dict (L5 preserved; the validator is an internal transformation, not a v0 wrapper).
**Handler arity/input (L3/L5):** `(input, ctx)` with direct typed input; no wrapper, no EmptyModel-subscript failure.
**Surfacing / readiness / durable / tenant:** shared mechanics with A1 (fail-fast `ConfigurationError`; exact-count readiness; `client.durable_task`; token-tenant consistency untouched).
**Hermetic alignment:** same two-arg v1 shape; the `mock_run`-based contract test is the strongest real-SDK-shaped hermetic proof and satisfies AT-16's "real-SDK-shaped test fails on one-argument/v0" wording directly.

**Evidence:** https://docs.hatchet.run/reference/python/pydantic ; https://www.mintlify.com/hatchet-dev/hatchet/sdk/python/workflows-tasks ; https://docs.hatchet.run/v1/migrating/v1-sdk-improvements
**Feasibility: HIGH** — medium effort (new model + stricter typing); residual risk is strict-mypy acceptance of the typed overloads (PROVISIONAL).

### Approach 3 — A3 "Engine-Verified Registration & Readiness Proof" (proof-focused hybrid)

**What it changes (exact):** A1 (or A2-typed) base for handler/surfacing/readiness, PLUS:
- New helper in `src/umd/jobs/hatchet.py`: `verify_engine_registration(client, expected_names: set[str]) -> set[str]` polling `client.workflows.list(workflow_name="umd-")` — the same REST surface `Workflow.id` uses (`runnables/workflow.py` at `py/1.38.1`).
- `tests/test_hatchet_live.py` 1035-1080 split into (a) the renamed local-bindings test and (b) a `cluster+docker` hosted test that polls `verify_engine_registration` until all nine `umd-*` names are engine-visible (the compose worker performs the real `put_workflow`; no second worker is started) and asserts the exact name set + `v1_task.is_durable=true` (AT-18).
- `cli.py` readiness keeps the count-truthfulness fix; an engine post-check inside the blocked loop is PROVISIONAL and not required — the hosted workflow/test-container query is the authoritative engine check.

**Distinct mechanism:** proof authority moves from local `Standalone` objects to an engine query; readiness can no longer be fabricated because the gate asserts engine-side rows/REST results, matching researcher L10 (engine visibility happens only in `Worker.start()` → `put_workflow`).
**Handler arity/input / surfacing / durable / tenant:** inherited from A1/A2 (shared mechanics).
**Hermetic/live gate:** hermetic tests stay local and honestly scoped (no engine, so no engine claim); the live gate gains an explicit engine-visible assertion instead of log-grep-only.
**Evidence:** https://docs.hatchet.run/v1/workers ; SDK source `worker.py`/`runnables/workflow.py` (`Workflow.id` REST `workflows.list`) at `py/1.38.1`.
**Feasibility: MEDIUM** — heavier hosted machinery; REST response shape for task durability is PROVISIONAL; risk of coupling the gate to REST semantics the DB-dump evidence already covers more cheaply (do not let this replace the DB-dump gate).

### Approach 4 — A4 "Async Durable Handler" (v2.0-forward)

**What it changes (exact):** A2 typed model, PLUS:
- `_make_handler` returns `async def handler(input: UmdStageInput, ctx: DurableContext) -> dict[str, Any]` that runs `executor.run(...)` via `await asyncio.to_thread(executor.run, manifest, work)` and returns a JSON-safe dict (researcher L10 risk: SDK step-output validation rejects non-JSON `StageRunRecord` returns).
- Registration uses `client.durable_task(name=wf_name, input_validator=UmdStageInput)` with an async handler → the supported, non-deprecated durable path (no v2.0.0 debt; matches https://docs.hatchet.run/v1/durable-tasks which declares durable tasks async).
- Hermetic `_invoke_callback` becomes async (`await cb(...)`) or wraps with `asyncio.run`; async test plumbing; `_RecordingClient.durable_task` records the async fn.

**Distinct mechanism:** sync→async execution model; the durable task receives `DurableContext` (unused — UMD durability remains executor/Postgres-owned per L12), and the handler carries zero deprecation warnings, aligning with the SDK's v2.0.0 direction.
**Handler arity/input (L3/L5):** `(input, ctx)` direct typed input — same as A2.
**Surfacing / readiness / durable / tenant:** shared mechanics; `is_durable=true` is guaranteed AND future-proof.
**Hermetic alignment:** same v1 shape, async invocation; real-SDK path becomes `aio_mock_run` (PROVISIONAL: confirm `Standalone.aio_mock_run` in the installed 1.38.1 wheel).
**Evidence:** https://docs.hatchet.run/v1/durable-tasks ; https://github.com/hatchet-dev/hatchet/blob/main/examples/python/durable/worker.py (all durable examples async); deprecation warning source `task.py` at `py/1.38.1`.
**Feasibility: MEDIUM** — most invasive (async test plumbing, `to_thread` semantics, JSON-safe return), but the only approach with zero SDK-deprecation debt.

### Ranking, feasibility, recommendation

| # | Approach | Distinct mechanism | Feasibility | Effort | Primary risk |
|---|----------|--------------------|-------------|--------|--------------|
| 1 | A1 Direct-Dict Minimal Repair | raw dict + `input_validator=dict` | HIGH | LOW | `mock_run` drops raw-dict inputs, so SDK-shaped hermetic tests need a model wrapper |
| 2 | A2 Typed Input Boundary | Pydantic `UmdStageInput` validator | HIGH | MEDIUM | strict-mypy overload pinning (PROVISIONAL) |
| 3 | A3 Engine-Verified Proof | engine REST/DB assertion | MEDIUM | MEDIUM-HIGH | REST shape coupling; redundancy with DB-dump gate |
| 4 | A4 Async Durable Handler | async durable handler | MEDIUM | HIGH | async test churn; `to_thread` blocking semantics |

**Recommendation for refinement (T3):** A2 as primary — the typed boundary composes with real-SDK `mock_run`/`aio_mock_run` tests, gives runtime input validation, and satisfies AT-16/AT-18 cleanly — with A1 as the minimal fallback if strict mypy rejects the typed overloads. Adopt A3's engine-visible REST assertion as a test-only addition on top of the chosen base (A2+A3 package), keeping the DB-dump + callback-row gate as release authority (no gate weakening). Carry A4 into T3 as the deliberate forward-compat option for the sync-durable deprecation question; do not default to it for this repair.

### L1–L21 survival statement

All L1–L21 survive under every approach above. L3/L4/L5 are fixed by the handler contract repair + hermetic fixture alignment. L7.1 (suppress removal) and L7.2 (readiness count truthfulness) are addressed in all four approaches; L7.3 is addressed by honest scoping (A1/A2) or engine verification (A3). L8 is preserved: tenant selection stays workflow-side, worker token-tenant identity is untouched, partition/assignment assertions remain mandatory in the hosted gate. L12 is preserved: durability remains executor/Postgres-owned; Hatchet durable registration (AT-18) is additive, not a substitute. L13/L14 are not weakened — every approach removes a fabrication path and keeps the hosted gate release-blocking. L15 is unchanged (hosted native Docker/Compose, public HTTP E2E, zero skips). L16 is untouched (OCFL/evidence/semantic/provenance invariants live outside these files). L17–L21 are unaffected; this is the required T1 of the mandated adversarial sequence, and the downstream DD/plan will carry the acceptance evidence. AT-16/17/18/19 authority in the netns DD is reconciled, not duplicated — these approaches implement its contracts (v1 callback, tenant partition assertions, durable registration) rather than adding parallel gates. No production code, tests, workflows, DDs, or plans were edited this turn.


## Critique

*(T2 Counter-Ideator, 2026-08-29. Scope: white-hat adversarial critique of the T1 approaches A1–A4 against the pinned SDK 1.38.1 / server v0.105.2, the L1–L21 ledger, and the binding AT-16/17/18/19 authority. Every technology claim in the Ideator's §0 table was re-verified against primary sources by this agent, not accepted on faith. Evidence tiers used here: Tier 1 = production/postmortem/primary maintainer source; Tier 2 = official docs / engine+SDK source at pinned tag; Tier 3 = community issue reports; Tier 4 = in-repo code/tests/hosted run. Design-only: no production code, tests, workflows, DDs, or plans were edited; only this log was appended.)*

### 0. Technology-verification table (Counter-Ideator re-check, all checked 2026-08-29)

| # | Ideator §0 claim | Counter-Ideator verification | Status |
|---|---|---|---|
| 1 | SDK 1.38.1 invokes task handler as `fn(workflow_input, ctx)` — two positional args, direct input, no v0 wrapper | **CONFIRMED.** `Task.call` at `sdks/python/hatchet_sdk/runnables/task.py` (`py/1.38.1`): `return self._fn(workflow_input, cast(Context, ctx), **dependencies)`; `aio_call` identical. `_get_workflow_input` = `input_validator.validate_python(ctx._workflow_input, context=HATCHET_PYDANTIC_SENTINEL)` (`runnables/workflow.py`). Docs `v1/tasks` ("arguments to the task are passed *positionally*") and `v1/migrating/migration-guide-python` (two-arg `(input, context)`) agree. | VERIFIED |
| 2 | Default `input_validator` = `EmptyModel`, no `__getitem__`, so `input["manifest"]` fails; needs `input_validator=dict` or typed model | **CONFIRMED and important.** `EmptyModel(BaseModel)` with `ConfigDict(extra="allow", frozen=True)` — no `__getitem__` (`runnables/types.py`). `normalize_validator(None) → EmptyModel`. So even with arity fixed, the current default-validator registration would still fail on `input["manifest"]` with a `TypeError`, not just the arity `TypeError`. Every approach's validator change is therefore mandatory, not optional. | VERIFIED (strengthens Ideator's correction) |
| 3 | `client.durable_task` exists; sync durable handler warns "Non-async durable tasks are deprecated… v2.0.0" | **CONFIRMED.** `durable_task` on `Hatchet` (keyword-only `name`, returns `Standalone`); `Task.__init__` raises `DeprecationWarning` and logs `logger.warning` for `is_durable and not async`. `to_proto` emits `is_durable=self._is_durable` and `slot_requests={"durable": 1}`. Python SDK changelog (2026-08-25) lists "Non-async durable tasks are deprecated." Engine commit `a6650ab` ("[Python] Refactor: v2.0.0 Prep … durable tasks must be async") shows the removal is actively in motion. | VERIFIED |
| 4 | `mock_run`/`aio_mock_run` serialize input only from Pydantic models/dataclasses; raw dict silently dropped to `{}` | **CONFIRMED.** `_create_mock_context`: `if is_dataclass(input): asdict(input); elif isinstance(input, BaseModel): input.model_dump(...)`; anything else leaves `serialized_input = {}`. Consequence for A1: a `Standalone.mock_run(input={...direct dict...})` gives the handler `{}` → `KeyError: 'manifest'` — the Ideator's stated risk is real and must be encoded in the T3 test design (pass a model wrapper even in A1). | VERIFIED |
| 5 | `hatchet-sdk==1.38.1` (PyPI, 2026-08-25) and server `v0.105.2` (2026-08-25) are the pinned CANDIDATE pair (CI DD C4) | **CONFIRMED.** PyPI page for `hatchet-sdk/1.38.1` (checked 2026-08-29): released Aug 25, 2026, Python `<4,>=3.10`, wheel `py3-none-any`. GitHub release `v0.105.2` (checked 2026-08-29) confirms the same date. No newer SDK bump is implied or recommended by any finding here; C4's "promote only after real pull/connect/register/execute" remains binding. | VERIFIED |
| 6 | `TypeAdapter(dict)` works as `input_validator`; `TWorkflowInput` bound includes `dict[str, Any]`; `client.workflows.list` returns engine-visible workflows | **PARTIALLY CONFIRMED — two corrections.** (a) `_TWorkflowInputBound = BaseModel \| DataclassInstance \| dict[str, Any]` and `normalize_validator` passes `dict` through — confirmed. (b) `Workflow.id` → `self._client.workflows.list(workflow_name=self.name)` then a **client-side exact `==` name match** — confirmed. **Correction:** the REST `name` filter in `WorkflowsClient.list` (`features/workflows.py`) is passed straight to the generated `WorkflowApi.workflow_list`; nothing in the SDK source shows prefix/substring semantics, and `Workflow.id` defensively filters `==` after listing. **`workflow_name="umd-"` in A3 is therefore unverified and likely to return zero rows under exact-match semantics** — a false-negative gate. A3 must list without the name filter (or per exact `umd-<stage>` name) and match the exact set client-side. | PARTIALLY VERIFIED (A3 filter is HIGH-risk) |
| 7 | `Hatchet.worker(name, workflows=[...])` requires `Workflow`/`Standalone`; `Worker.start()` → `register_workflows` → `admin.put_workflow` is the only engine-visible registration path | **CONFIRMED, plus a readiness-ordering finding.** `worker()` raises `TypeError` for non-`BaseWorkflow` items. `Worker.start()` calls `register_workflows(self._workflows)` first, then raises `ValueError("no actions registered…")` if the registry is empty. `register_workflow` → `put_workflow`, and **on failure it logs and calls `sys.exit(1)`** (`worker.py`). Because cli.py prints the C6 ready line **before** `worker.start()`, a `put_workflow` failure kills the worker process *after* the ready line has already been emitted. The exact-count fix closes the local count-fabrication path but cannot, by itself, make the ready line engine-visible proof. This is precisely why AT-16/17/18 DB+callback assertions remain release authority (C6 stays "candidate"). | VERIFIED (+ finding) |
| 8 | Engine-visible registration happens only at `Worker.start()` (researcher L10) | **CONFIRMED** by `Worker.start() → register_workflows → admin.put_workflow` and the action-listener subprocess registration (`worker.py`); there is no other public surface that registers with the engine. Consequence: the renamed local test in A1/A2 can only assert local bindings; A3's engine query is the only *test-suite* surface that can see the engine — and per row 6, its filter must be corrected. | VERIFIED |

### 1. Approach A1 — "Direct-Dict Minimal Contract Repair"

- **Handler arity/input (L3/L5):** correct and minimal. Two-arg `handler(input, ctx)` + `input_validator=dict` is the smallest diff that satisfies the verified contract (table row 1, 2, 6a). **Source:** `runnables/task.py`, `runnables/types.py` at `py/1.38.1` [Tier 1].
- **Critique 1 — MEDIUM (AT-18 risk, must be fixed in T3):** the proposed registration resolution `decorator = getattr(client, "durable_task", None) or getattr(client, "task", None) or getattr(client, "workflow", None)` silently **degrades to `client.task` if `durable_task` is absent**. On the pinned 1.38.1 `durable_task` exists, so the fallback is dead code *today* — but it re-creates the swallow-defect pattern at the contract level: a mis-pinned or mis-installed SDK would silently register non-durable tasks and only fail later at the hosted AT-18 assertion (`v1_task.is_durable=false`). This is exactly the class of silent-contract-drift this adversarial process exists to kill. **Required change:** resolve `durable_task` by name and **hard-fail (`ConfigurationError`) if absent**; never fall back to `task`/`workflow`. The hosted `v1_task.is_durable=true` assertion (AT-18) is the only acceptable check. **Why it applies HERE:** this repo's release gate treats `is_durable=false` as a hard FAIL (netns DD AT-18); a silent fallback converts a guaranteed violation into a late failure with no diagnostic.
- **Critique 2 — MEDIUM (readiness ordering, L7.2):** removing the suppress + exact-count pre-check is correct and closes the local fabrication path, **but** the C6 line is still printed before `worker.start()`, and a `put_workflow` failure inside `start()` exits the process (`sys.exit(1)`, table row 7). Therefore the ready line can still be emitted with a subsequently-dead worker. This is not a defect in A1 (A1 explicitly defers to the hosted gate) — it must simply stay explicit: **after the count fix, the ready line is still candidate evidence, never engine-visible proof.** The hosted AT-16/17/18 assertions are the only release proof. [Tier 1/2]
- **Critique 3 — LOW (mock_run dict-drop):** A1's SDK-shaped hermetic tests must pass a model wrapper to `mock_run` (row 4). A1 already acknowledges this; the T3 pattern must make the negative tests unambiguous (a v0-wrapped payload via `mock_run` fails with `KeyError`, not with the real engine's contract error — label it as shape-check, not SDK-fidelity). [Tier 1]
- **Verdict:** **SURVIVES-WITH-CONDITIONS** — as the minimal fallback, provided (a) the fallback chain is replaced by a hard-fail on missing `durable_task`, (b) readiness is explicitly scoped as candidate-only, (c) `input_validator=dict` passes strict mypy (PROVISIONAL to be resolved at implementation).

### 2. Approach A2 — "Typed Pydantic Input Boundary"

- **Handler arity/input:** correct; typed `input_validator` gives runtime validation at the SDK boundary and attribute access. **Source:** `runnables/task.py` (`Task._validators = TaskIOValidator(workflow_input=...)`), `runnables/workflow.py` (`_get_workflow_input`), docs `v1/reference/python/pydantic` [Tier 1/2].
- **Critique 1 — MEDIUM (strict-mypy PROVISIONAL is real, not cosmetic):** the `task()`/`durable_task()` overloads bind `TWorkflowInput` to `BaseModel | DataclassInstance | dict[str, Any]`. `UmdStageInput(BaseModel)` should satisfy `type[TWorkflowInput]`, and `_make_handler`'s return type (`StageRunRecord`) must fall inside `R`'s bound (`BaseModel | Mapping[str, Any] | DataclassInstance | None`) for the `Callable[Concatenate[TWorkflowInput, Context, P], R | CoroutineLike[R]]` overload to accept the decorated callable. The existing live evidence (9 workflows registered with exact action IDs) proves the *current* decoration already type-checks at runtime, but under strict mypy the union overloads are a genuine pinning hazard. The Ideator's PROVISIONAL label is honest; T3 must pin this before committing to A2 as primary. [Tier 1]
- **Critique 2 — MEDIUM (return-type boundary):** the SDK validates step output against `R` (task.py `_validators.step_output = TypeAdapter(normalize_validator(return_type))`). If `StageRunRecord` is a dataclass this is fine; if it is a plain class or non-JSON-serializable, the runner's output validation can reject the result after successful executor work — the researcher's L10 "SDK step-output validation rejects non-JSON returns" risk. A2 should either confirm `StageRunRecord` is within the SDK's return bound or return a JSON-safe mapping from the handler (keeping `executor.run` results in the durable store, not the return value — consistent with L12). Not a new failure, but it must be verified in T3, not assumed. [Tier 1/4]
- **Critique 3 — LOW (durable + eviction policy):** `durable_task` defaults `eviction_policy=DEFAULT_DURABLE_TASK_EVICTION_POLICY`. UMD's handler never calls durable-context wait primitives, so eviction-between-checkpoints cannot trigger; and server v0.105.2 explicitly fixes "evicted tasks can now time out instead of hanging" (#4772) — the risk is low. Register explicitly with `eviction_policy=None` if the policy is unused, to avoid paying eviction semantics for a non-checkpointing handler. [Tier 1/2]
- **Verdict:** **SURVIVES-WITH-CONDITIONS** — strongest primary candidate; conditions: mypy PROVISIONAL resolved, `StageRunRecord`/return bound confirmed, A1's Critique 1 (hard-fail on missing `durable_task`) inherited.

### 3. Approach A3 — "Engine-Verified Registration & Readiness Proof"

- **Critique 1 — HIGH (the `workflow_name="umd-"` filter is likely broken):** `WorkflowsClient.list` passes `name=apply_namespace(workflow_name)` to the REST `workflow_list` endpoint, and the SDK's own `Workflow.id` defensively re-filters returned rows with an exact `==` (table row 6). There is **no evidence** the REST `name` parameter does prefix/substring matching. Under exact-match semantics, `workflow_name="umd-"` matches nothing (no workflow is named `"umd-"`), so A3's poll would always time out — a false-*negative* gate that fails a healthy stack. **Required correction:** call `client.workflows.list()` with no name filter and match the exact `umd-<stage>` set client-side, or call `list(workflow_name=<exact>)` per stage. This must be re-verified against the actual `WorkflowApi.workflow_list` server handler in T3 before the pattern is adopted. [Tier 1]
- **Critique 2 — MEDIUM (what the query actually proves vs. what AT-16/AT-19 require):** `workflows.list` returns workflow *declaration* rows (metadata.id/name). It does **not** prove: (a) a callback was observed (requires `v1_task_runtime` transitions or callback-owned UMD rows), or (b) durable registration (`is_durable` lives on `v1_task`, not on the Workflow REST model). If A3's test is used to claim "engine-visible → callback executed" or "engine-visible → durable", it becomes a **false-positive gate** — precisely the L13/L14 failure this process forbids. A3's own text guards against replacing the DB-dump gate; the T3 pattern must keep that guard structural (the REST assertion is *additive* and *scoped to declaration visibility only*). [Tier 1/2]
- **Critique 3 — LOW-MEDIUM (redundancy/authority):** the DB-dump gate (hosted `v1_task`/`v1_run`/`v1_task_runtime` + callback rows) is cheaper and strictly stronger than the REST query for the AT-16/17/18 claims. A3's marginal value is limited to an *in-test* engine-side assertion in `cluster+docker` (vs. workflow-log-grep). That is legitimate for C5's "real SDK client" live shape tests, but A3 must not be framed as the proof mechanism — the Ideator's own feasibility note already says this; keep it. [Tier 1/2/4]
- **Verdict:** **SURVIVES-WITH-CONDITIONS (test-only addition), DEAD as a standalone proof mechanism.** Survives only as an additive hosted assertion with the corrected filter and precisely scoped claims; it cannot prove AT-16 (observed callback) or AT-18 (`is_durable=true`) by itself.

### 4. Approach A4 — "Async Durable Handler"

- **Critique 1 — MEDIUM (blast radius vs. repair risk):** the repair's objective (L1/L3–L7) is to unblock live execution with minimal risk. A4 is the most invasive option: async handler + `asyncio.to_thread` + async test plumbing + event-loop interplay with the CLI's blocking `worker.start()`. Server v0.105.2 is *fresh* and its durable path is churny — this exact release carries `refactor(engine): pub messages to mq to trigger child runs from durable tasks` (#4702), `fix(engine): durable dag child spawning breaks downstream steps` (#4768), `fix(engine): duplicate event-to-run records, increase durable dag slots` (#4758), and `fix(engine): add ordering + for update lock` (#4752). Choosing the async durable path now deliberately increases surface area *at the moment of the repair*. For this repo (L12: durability is executor/Postgres-owned; Hatchet durable registration is additive), the async conversion buys nothing functionally and costs event-loop/thread semantics. [Tier 1/2]
- **Critique 2 — LOW (aio_mock_run verified):** the Ideator marked `Standalone.aio_mock_run` PROVISIONAL; this agent verified `async def aio_mock_run` exists in `task.py` at `py/1.38.1` — upgrade that claim to VERIFIED. The async test plumbing is real work but mechanically sound. [Tier 1]
- **Critique 3 — LOW (deprecation debt framing):** the sync-durable deprecation is a `DeprecationWarning`, not an error; v2.0.0 is not scheduled. Carrying sync durable with a recorded forward-compat note (A1/A2) is tracked debt, not a release blocker — A4's "zero debt" premise is true but does not justify expanding the repair. [Tier 1]
- **Verdict:** **SURVIVES-WITH-CONDITIONS as a deliberate forward-compat option only** — do not default to it for this repair (agreeing with the Ideator's own recommendation). If adopted later, it must be a separate coordinated change (CI DD C4 lockstep + new DAG universe), not part of this blocker fix.

### 5. Cross-cutting findings

- **AT-18 achievability and falsifiers:** `client.durable_task(name=..., input_validator=...)` → `Standalone` with `task.is_durable=True` → `to_proto` emits `is_durable=true` + `slot_requests={"durable": 1}` → `put_workflow` persists `v1_task.is_durable=true` (engine `is_durable` column, migration `3b6e982`/#3707). So AT-18 is **achievable** with the pinned pair. What can still falsify it: (a) A1's silent fallback to `client.task` (Critique A1-1) → `is_durable=false`; (b) asserting on a stale workflow *version* — repeated `put_workflow` with the same name creates new workflow versions; the hosted assertion must scope `is_durable=true` to the latest version's tasks, not any historical row; (c) worker slot derivation — `Hatchet.worker` derives slot config from workflows' `slot_requests`; with all-durable workflows the worker's slot_config is `{"durable": N}` and the engine must assign durable slots (`ListAvailableSlotsForWorkersAndTypes`, engine `scheduler_assignment.go`). The hosted gate must assert not only `is_durable=true` but also that tasks **transition to ASSIGNED/RUNNING** (L8's assignment/runtime requirement) — durable slot type matching is exactly the kind of thing a queue stays stuck on if mismatched.
- **Readiness truthfulness (L7.2, C6):** with the fallback removed, the C6 count is truthful *for the local handle*, and the C6 wording remains honest as candidate evidence. It must not be re-worded into an engine claim; the CI DD C6 owns that wording (out of scope to change here). `wait-for-worker.sh` will still see the line; the hosted gate's AT-16/17/18 assertions are what make readiness non-fabricated.
- **Hermetic/live separation (L4/L19):** two-arg hermetic fixtures with `_FakeCtx()` align to the v1 contract, and the handler ignores `ctx` today, so the fake context is safe — but it is a **divergence point**: if a future handler touches `ctx`, hermetic and live contracts silently split again. The T3 pattern should add a comment/invariant on `_FakeCtx` ("handler must not consume ctx; re-verify on change") and prefer `mock_run`/`aio_mock_run`-based tests (real SDK shape) for contract tests over the recording-client path. The negative tests (one-arg handler / v0 payload) should live on the real SDK surface so the hermetic suite exercises the actual SDK call path (AT-16's "real-SDK-shaped test fails on one-argument/v0" wording).
- **Tenant partitions (L8/AT-17):** no approach touches tenant selection (correct — it stays workflow-side in validation.yml P2-S4), and none changes token-tenant identity. Engine source confirms the mechanism: the scheduler lists tenants per `schedulerPartitionId` (`pkg/repository/tenant.go`, `internal/services/scheduler/v1/scheduler.go`); the `internal` tenant's NULL partition means its queue items are never in any scheduler partition's tenant set — exactly the observed queued-but-unassigned state. AT-17's "non-null scheduler+worker partition IDs, exactly one eligible tenant, fail closed" is the correct gate and remains untouched by A1–A4. One note: the hosted gate must record the *selected* tenant's partition IDs and assert assignment/runtime state (L8) — the approaches defer this correctly, but the T3/T5 evidence design must keep it.
- **Overlap with netns DD:** A1/A2/A4 implement AT-16 (v1 callback + hermetic/real-SDK-shaped negatives) and AT-18 (durable registration) in product code/tests; AT-17 stays workflow-side; A3 adds a *new* hosted test to `test_hatchet_live.py`. That is implementation of the binding contracts, not duplication of gate authority — acceptable, with the caveat that A3's new test must be composed under AT-19 (joined with AT-1…15, release-blocking), not a parallel gate set.

### 6. Verdicts

| Approach | Verdict | Sharpest unresolved risk |
|---|---|---|
| A1 Direct-Dict Minimal Repair | **SURVIVES-WITH-CONDITIONS** (minimal fallback) | Silent `client.task` fallback can falsify AT-18 (must hard-fail on missing `durable_task`); `input_validator=dict` mypy PROVISIONAL |
| A2 Typed Input Boundary | **SURVIVES-WITH-CONDITIONS** (recommended primary) | Strict-mypy overload pinning + `StageRunRecord` return-bound must be verified, not assumed |
| A3 Engine-Verified Proof | **SURVIVES-WITH-CONDITIONS as test-only addition; DEAD as standalone proof** | `workflow_name="umd-"` filter semantics unverified (likely exact-match → false-negative gate); query proves declaration visibility only, not callback or durability |
| A4 Async Durable Handler | **SURVIVES-WITH-CONDITIONS as forward-compat option only** | Expands repair blast radius into the churny v0.105.2 durable path for zero functional gain (L12 durability is executor-owned) |

### 7. Summary

- **Surviving:** A2 (primary, with mypy/return-bound verification), A1 (minimal fallback, with the durable_task hard-fail fix), A3 (additive hosted assertion only, with the filter correction and scoped claims), A4 (deferred forward-compat).
- **Dead:** none outright — but A3 as a *proof mechanism* and A4 as *this repair's default* are rejected; the Ideator's T1 recommendation (A2 primary + A1 fallback + A3 additive test, A4 deferred) survives scrutiny *provided* the conditions above are adopted.
- **Sharpest unresolved risk per survivor:** A1/A2 — the `durable_task` resolution must fail hard, never degrade; A2 — strict mypy must actually accept the typed overloads and the return type must be in the SDK's `R` bound; A3 — the REST name-filter semantics must be confirmed (or the filter dropped) before the test is written.
- **Technology verdict:** the Ideator's §0 table is accurate; the one materially unverified claim is A3's `workflow_name="umd-"` prefix-style filter, which this critique flags HIGH and requires re-verification in T3.

### 8. L1–L21 risk note

No L item is at hard risk under the surviving approaches **if** the T3 refinements adopt: (a) hard-fail (never fallback) on missing `durable_task` — otherwise **AT-18/L13** (durable registration, no fake contracts) is at risk; (b) explicit candidate-only scope for the readiness line — otherwise **L7.2/L14** (fabricated readiness, weakened gates) can regress; (c) corrected A3 filter and scoped claims — otherwise **L7.3/L19** ("engine-visible proof or honest test scope") is at risk of a false-negative or false-positive gate. L3/L4/L5 (handler contract, hermetic mask, v1 direct input), L8 (tenant eligibility/assignment assertions), L12 (executor/Postgres-owned durability), L16 (OCFL/provenance invariants), and L20 (no edits by design agents) are preserved by all four approaches as proposed.

## Refined Approaches

*(T3 Ideator, 2026-08-29. Scope: refine the T1 approaches A1–A4 against the T2 critique; adopt every sharpest unresolved risk as a hard requirement; drop dead variants with reasons; revalidate changed/consequential technology choices. Design-only: no production code, tests, workflows, DDs, or plans were edited; only this log was appended.)*

### 1. T2 critique disposition (what T3 changes and why)

- **A2 adopted as primary, A1 as fallback, A3 as additive test-only, A4 deferred** — matches the T2 verdicts (§6) and the T1 recommendation; no verdict is contested.
- **All six sharpest unresolved risks are adopted as hard requirements, not notes:** (a) `durable_task` resolution hard-fails when absent — never falls back to `client.task`; (b) strict-mypy overload acceptance and `StageRunRecord` return-bound are verified before A2 is committed; (c) A3's REST filter is corrected (no prefix filter; exact-set client-side match); (d) readiness line stays candidate-only; (e) `_FakeCtx` divergence is guarded by an invariant; (f) tenant partition assertions remain workflow-side with assignment/runtime state.
- **AT-18 falsifier guards adopted:** latest-version scoping for `is_durable=true` and durable-slot assignment matching (T2 §5) become explicit hosted-gate assertions.

### 2. Refined Approach A2′ — Typed Input Boundary (PRIMARY, hardened per T2)

**What it changes (exact):**
- New `UmdStageInput(BaseModel)` in `src/umd/jobs/hatchet.py` (fields `job_id`, `source_id`, `dag_universe`, `stage`, `manifest`, optional `causation_id`) registered as `input_validator` on `client.durable_task(name=wf_name, input_validator=UmdStageInput)`.
- `_make_handler` returns `def handler(input: UmdStageInput, ctx: Any) -> dict[str, Any]` reading `input.manifest` (attribute access, runtime-validated at the SDK boundary).
- **Hard-fail registration (T2 A1-C1 inherited):** `durable_task = getattr(client, "durable_task", None)`; `if durable_task is None: raise ConfigurationError("hatchet-sdk 1.38.1 required: client.durable_task missing — refusing to register non-durable tasks (AT-18)")`. No `or getattr(client, "task", ...)` fallback chain. The `contextlib.suppress(Exception)` block at hatchet.py:426 is deleted; after the loop `if len(registered_workflows) != len(STAGE_ORDER): raise ConfigurationError(...)` naming missing `umd-<stage>` names.
- **Return boundary (T2 A2-C2):** the handler returns a JSON-safe mapping `{"idempotency_key": ..., "state": record.state, "attempts": record.attempts}`; the durable `StageRunRecord` stays in the store (`executor.run` persists `stage_run`/`StageCompleted`/audit — L12), never in the SDK return value. This keeps the SDK's step-output `TypeAdapter` from rejecting non-JSON returns after successful executor work.
- **Eviction policy (T2 A2-C3):** register with `eviction_policy=None` (or the SDK default constant) since the handler never calls durable-context wait primitives; recorded as an explicit choice, not a default.
- **Hermetic alignment:** `_invoke_callback` passes `UmdStageInput(**direct_input)`; real-SDK-shaped contract tests use `Standalone.mock_run(input=UmdStageInput(...))` (the only input form `_create_mock_context` serializes faithfully in 1.38.1 — T2 §0 row 4). Negative tests (one-arg handler, v0-wrapped payload) live on the real SDK surface (AT-16 wording).
- **Mypy verification obligation:** the PROVISIONAL strict-mypy acceptance of the typed overloads is resolved at implementation time against the installed 1.38.1 wheel; if the union overloads cannot be pinned, the fallback is A1′ (below) — recorded, not assumed.

**Evidence:** same primary sources as T1 §0 (SDK `task.py`/`workflow.py`/`types.py` at `py/1.38.1`; docs `v1/tasks`, `v1/durable-tasks`, `reference/python/pydantic`), re-verified by T2 §0; production pattern: maintainer examples (`github.com/hatchet-dev/hatchet` `examples/python/durable/worker.py`) all use typed input + two-arg async durable handlers (checked 2026-08-29).
**Feasibility: HIGH** — with the mypy PROVISIONAL resolved as the single gate.

### 3. Refined Approach A1′ — Direct-Dict Minimal Fallback (hardened per T2)

**What it changes (exact):** identical mechanics to A2′ (hard-fail `durable_task`, delete suppress, exact-count `ConfigurationError`, JSON-safe return, `eviction_policy=None`, hermetic v1 fixtures) EXCEPT `input_validator=dict` and `def handler(input: dict[str, Any], ctx: Any)` reading `input["manifest"]`.

- **T2 A1-C1 adopted:** no fallback chain; `durable_task` missing ⇒ `ConfigurationError`.
- **T2 row 4 adopted:** SDK-shaped tests still pass a Pydantic model wrapper (not a raw dict) to `mock_run`, because `_create_mock_context` drops raw dicts to `{}`.
- **Why keep as fallback:** if strict mypy cannot pin A2′'s typed overloads, A1′ with `input_validator=dict` is the smallest verified diff that still satisfies L3/L5, L7, AT-18, and AT-16's shape requirements. It is NOT preferred: it loses the SDK-boundary runtime validation and attribute access.

**Evidence:** same sources as A2′; `input_validator=dict` verified by T2 §0 row 6a (`_TWorkflowInputBound` includes `dict[str, Any]`).
**Feasibility: HIGH.**

### 4. Refined Approach A3′ — Engine-Visible Registration Assertion (additive, test-only, corrected per T2)

**What it changes (exact):** a new `cluster+docker` hosted test in `tests/test_hatchet_live.py` that polls `client.workflows.list()` — **with NO name filter** — and matches the exact `umd-<stage>` set client-side (T2 A3-C1 correction: the SDK's `Workflow.id` defensively re-filters with `==`; prefix semantics are unverified). The compose worker performs the real `put_workflow`; no second worker is started.

- **Scoped claims (T2 A3-C2):** the assertion proves engine-visible **declaration** rows only — it never claims an observed callback, durable registration, or execution. Those remain the DB-dump + callback-owned rows gate (AT-16/17/18), unchanged and release-blocking.
- **Composed under AT-19:** the new test is an additional hosted check joined with AT-1…15/16/17/18, not a parallel gate set.

**Evidence:** SDK `runnables/workflow.py` (`Workflow.id` → `client.workflows.list` + client-side `==`); docs `v1/workers` ("When a worker starts, it registers each of its tasks and workflows with Hatchet"); checked 2026-08-29. Server-side `WorkflowApi.workflow_list` filter semantics remain an implementation-time verification (T2 A3-C1).
**Feasibility: MEDIUM.**

### 5. Approach A4 — Async Durable Handler: DEFERRED (not this repair's default)

**Reasons (adopting T2 §4):** the repair's objective (L1/L3–L7) is to unblock live execution with minimal risk. A4 expands blast radius into the churny v0.105.2 durable path (engine commits #4702/#4768/#4758/#4752 — T2 §4) for zero functional gain, because L12 keeps durability executor/Postgres-owned and the handler never uses durable-context primitives. The sync-durable deprecation (`DeprecationWarning`, removal planned for v2.0.0; engine commit `a6650ab` "durable tasks must be async" — T2 §0 row 3) is tracked forward-compat debt, not a release blocker. If adopted later, it must be a separate coordinated change (CI DD C4 lockstep + new DAG universe).

### 6. Readiness, gate hardening, and evidence design (cross-cutting, mandatory in all refined approaches)

- **Readiness truthfulness (L7.2/C6):** `cli.py:123` reports `len(handle.registered_workflows)` ONLY (no `or len(work_registry)` fallback); exact-count mismatch exits non-zero BEFORE the ready line; the ready line remains candidate-only (CI DD C6 wording), never an engine claim — the hosted AT-16/17/18 assertions are the release proof (T2 §5).
- **Durable-slot assignment (T2 §5, L8):** with all-durable registration, `Hatchet.worker` derives slot_config `{"durable": N}`; the hosted gate must assert submitted tasks transition to **ASSIGNED/RUNNING** (not merely `is_durable=true`), because durable-slot type mismatch is a real stuck-queue mechanism — the same observable as the queued-but-unassigned run `33229130339` (`support-debugger.log.jsonl:L8`). Engine source: `ListAvailableSlotsForWorkersAndTypes`, `scheduler_assignment.go` (T2 §5).
- **Latest-version scoping (T2 §5):** repeated `put_workflow` creates new workflow versions; the hosted assertion scopes `is_durable=true` to the **latest** version's tasks, not any historical row.
- **Tenant eligibility (L8/AT-17):** stays workflow-side (`validation.yml` P2-S4); the hosted gate records the selected tenant + both partition IDs and asserts JWT == worker == workflow == submitted-task tenant, plus assignment/runtime state, failing closed on zero/multiple/null. No approach changes token-tenant identity.
- **Hermetic/live separation (L4/L19):** hermetic fixtures are v1-shaped (`cb(UmdStageInput(**direct_input), _FakeCtx())`); `_FakeCtx` carries an invariant comment ("handler must not consume ctx; re-verify on change"); contract tests prefer `mock_run`/`aio_mock_run` (real SDK shape) over the recording-client path; the hosted observed-callback + durable-rows gate is unchanged and release-blocking.

### 7. Technology revalidation (all checked 2026-08-29)

| Claim (changed/consequential) | Source | Status |
|---|---|---|
| `client.durable_task` exists and sync-durable warns (removal planned v2.0.0) | SDK `hatchet.py`/`task.py` at `py/1.38.1`; Python SDK changelog 2026-08-25; engine commit `a6650ab` | VERIFIED — A2′/A1′ use it with recorded forward-compat debt |
| `input_validator=dict` / `TypeAdapter(dict)` satisfies `_TWorkflowInputBound` | SDK `runnables/types.py` at `py/1.38.1`; T2 §0 row 6a | VERIFIED — A1′ fallback |
| `mock_run` drops raw dicts; requires model wrapper | SDK `task.py` at `py/1.38.1`; T2 §0 row 4 | VERIFIED — test design constraint |
| `aio_mock_run` exists | SDK `task.py` at `py/1.38.1`; T2 §4 (upgraded from PROVISIONAL) | VERIFIED — A4 deferred |
| REST `workflows.list` name-filter prefix semantics | SDK `features/workflows.py` + `Workflow.id` at `py/1.38.1`; T2 §0 row 6b | PARTIALLY VERIFIED — A3′ drops the filter, matches exact set client-side; server handler re-verified at implementation |
| Server v0.105.2 durable-slot scheduling + evicted-task timeout fix (#4772) | GitHub release notes / engine source; T2 §3/§5 | VERIFIED — supports durable registration + explicit eviction policy |

### 8. Ranked recommendation (T3)

1. **A2′** (typed input boundary, hardened) — primary.
2. **A1′** (direct-dict fallback, hardened) — only if strict mypy rejects A2′'s typed overloads.
3. **A3′** (engine-visible declaration assertion) — additive hosted test on top of A2′/A1′.
4. **A4** — deferred forward-compat, not part of this repair.

The refined set is a single coherent package: A2′ (or A1′) implements the handler contract + durable registration + honest readiness; A3′ adds the only in-test engine-visible surface; the hosted AT-16/17/18/19 gate remains release authority. No approach is left dead without a reason — A4 is the only deferred one and its reason is recorded (repair blast radius vs. zero functional gain under L12).

## Surviving Concerns

*(T4 Counter-Ideator, 2026-08-29. Scope: assess whether the T3 refinements actually address the T2 critique; identify remaining failure modes and unresolvable questions honestly; no rubber-stamping. Design-only: no production code, tests, workflows, DDs, or plans were edited; only this log was appended.)*

### 1. Did T3 address the T2 sharpest risks? Item-by-item disposition

| T2 sharpest risk | T3 response | Verdict |
|---|---|---|
| A1/A2: `durable_task` must hard-fail, never degrade to `client.task` | A2′/A1′ both raise `ConfigurationError` when `durable_task` is absent; fallback chain deleted | **ADDRESSED** — the silent-contract-drift pattern is killed at the resolution site |
| A2: strict mypy must accept typed overloads; `StageRunRecord` return must be in SDK `R` bound | A2′ makes JSON-safe dict return mandatory (record stays in store); mypy PROVISIONAL resolved at implementation, with A1′ fallback recorded | **ADDRESSED with honest residual** — mypy acceptance cannot be proven until implementation; the fallback path is explicit, so the risk is contained, not eliminated |
| A3: `workflow_name="umd-"` filter likely exact-match → false-negative gate | A3′ drops the name filter entirely; exact `umd-<stage>` set matched client-side | **ADDRESSED** — the false-negative mechanism is removed; server-side `workflow_list` semantics remain an implementation-time verification |
| Readiness line must stay candidate-only | A3′/A2′/A1′ all keep the ready line candidate-only (CI DD C6 wording); hosted AT-16/17/18 remain release proof | **ADDRESSED** — no wording change to C6 is proposed |
| `_FakeCtx` divergence guard | `_FakeCtx` invariant comment adopted; contract tests prefer `mock_run` | **ADDRESSED** — as a test-design discipline, not a structural guarantee (acceptable) |
| Tenant partitions/assignment (L8/AT-17) | Stay workflow-side; partition IDs + four-way identity + assignment/runtime assertions recorded | **ADDRESSED** — untouched product-side, gate strengthened |

### 2. What still does not work / what persists

- **S1 (unresolvable at design time): strict-mypy overload pinning for A2′.** The SDK 1.38.1 `task()`/`durable_task()` overloads bind `TWorkflowInput` to `BaseModel | DataclassInstance | dict[str, Any]`; whether the installed wheel's overloads accept `UmdStageInput` + a JSON-safe `Mapping[str, Any]` return under strict mypy is a fact about the installed type stubs, provable only by compiling against the wheel. This is why A1′ is the recorded fallback — a design decision, not a hidden risk. **The human/execution decision point is: attempt A2′ first and fall back on mypy failure, or pin A1′ and skip the typed model?** (Carried to T8 Q.)
- **S2 (persists, must be proven hosted): durable-slot assignment.** T3 correctly identified `slot_requests={"durable": 1}` → worker slot_config `{"durable": N}` → engine must assign durable slots (`ListAvailableSlotsForWorkersAndTypes`). This is a real stuck-queue mechanism and cannot be proven by any local/hermetic test — only by a hosted run that shows `v1_task` rows transitioning to ASSIGNED/RUNNING and callback-owned UMD rows. Until that run exists, the design cannot claim the L8 assignment requirement is met. **This is the single biggest remaining execution risk.**
- **S3 (persists): engine-visible registration assertion is declaration-only.** A3′ proves `WorkflowVersion`/declaration rows exist engine-side; it does not prove callback execution, durability, or assignment. The DB-dump + callback-owned rows gate remains the only release authority — this separation is correct but means A3′ adds test-suite visibility only, with the real proof living in the workflow gate. No design change can move that proof into a unit test.
- **S4 (persists, low): `input_validator` semantics divergence between `mock_run` and real dispatch.** `mock_run` serializes from the Pydantic model; real dispatch validates the raw dict through `_get_workflow_input`. If the two ever disagree on a field (e.g., `causation_id` optionality), hermetic tests could pass while live fails — the exact class of the original L4 mask, on a smaller scale. Mitigation exists (spec-first contract test asserting `UmdStageInput.model_validate(direct_input)` equals the fixture input; hosted gate unchanged) but is discipline-dependent.
- **S5 (persists, low): sync-durable deprecation debt.** v2.0.0 will require async durable handlers (engine commit `a6650ab`). This repair ships sync-durable with a recorded forward-compat note. Not a blocker; must be revalidated at every SDK bump (CI DD C4).

### 3. Unresolvable questions (honest, for human judgment)

1. **Typed vs dict input boundary (S1).** A2′ gives runtime validation and attribute access but depends on strict-mypy accepting the SDK's union overloads. A1′ is guaranteed-verifiable but loses the boundary validation. The tradeoff is real; evidence cannot decide it until mypy is run against the wheel. → T8 Q.
2. **Durable-slot assignment acceptance (S2).** Whether the pinned server v0.105.2 reliably assigns durable slots to a worker whose entire workflow set is durable is proven only by the hosted run. If the hosted run shows stuck-queued tasks with `is_durable=true`, the design must pivot to mixed standard/durable registration or investigate engine slot config — that pivot cannot be fully specified in advance. → T8 Q (what to do if durable slots don't assign).
3. **A3′ value vs. cost (S3).** A3′ is an additive hosted assertion that cannot prove the release-relevant facts; its marginal value is in-test engine visibility. A human could reasonably decide to skip it and rely on the DB-dump gate alone — but that loses the "engine-visible proof or honest test scope" (L19) in-suite surface. → T8 Q.

### 4. Ledger check (L1–L21)

All L1–L21 survive the refined set. L3/L4/L5 (handler contract, hermetic mask, v1 input) — addressed by A2′/A1′ + fixtures. L7.1/L7.2/L7.3 — addressed (hard-fail, exact-count readiness, A3′/honest scope). L8 — preserved workflow-side with partition + assignment assertions. L12 — preserved: executor/Postgres-owned durability; JSON-safe handler return keeps the SDK from double-owning state. L13/L14 — not weakened: no fabrication path survives; hosted gate release-blocking. L15 — unchanged. L16 — untouched (OCFL/evidence invariants outside these files). L17–L21 — unaffected; the downstream DD/plan carries acceptance evidence. AT-16/17/18/19 are implemented, not duplicated. No production code, tests, workflows, DDs, or plans were edited this turn.

## Implementation Patterns

*(T5 Improver, 2026-08-29. Scope: concrete implementation patterns for the surviving A2′/A1′+A3′ package: data flow, state management, error handling, testing approach, key library choices; per-pattern real-world best-practice citations; validate each key library/version against official sources; exact phased plan obligations for code/tests/workflow/evidence (read-only design scope). Design-only: no production code, tests, workflows, DDs, or plans were edited; only this log was appended.)*

### IP-1 — V1 typed handler contract pattern (data flow)

**Pattern:** the SDK dispatches `fn(input, ctx)` positionally; `input_validator` normalizes the raw dict at the boundary; the handler converts input → `StageManifest` → `DurableStageExecutor.run` → store-persisted rows → JSON-safe return.

```
Hatchet engine dispatch
  → Task.call(workflow_input, ctx)            (SDK task.py @ py/1.38.1)
  → _get_workflow_input: input_validator.validate_python(ctx._workflow_input)
  → UmdStageInput (A2′) or dict (A1′)          (boundary validation)
  → _make_handler(input, ctx)
      → StageManifest.from_dict(input.manifest)  (or input.manifest attr access)
      → store cancel check (CANCELLED/PAUSED/partial) → no-op replay (durable cancel)
      → committed_evidence_refs resolution      (stable idempotency keys)
      → work = work_registry.get(stage); ConfigurationError if absent
      → executor.run(manifest, work)            (persists stage_run/StageCompleted/audit)
  → JSON-safe {"idempotency_key", "state", "attempts"} returned to SDK (never StageRunRecord)
```

**Best-practice citations:** Hatchet's own examples (`github.com/hatchet-dev/hatchet` `examples/python/durable/worker.py` — typed input + two-arg handler, checked 2026-08-29); official docs `v1/tasks` ("arguments passed positionally") and `v1/migrating/migration-guide-python` (two-arg `(input, context)`); SDK source `runnables/task.py`/`workflow.py` at `py/1.38.1` (primary).
**Key validation:** `hatchet-sdk==1.38.1` (PyPI 2026-08-25; Python `<4,>=3.10`); handler contract verified by T2 §0 row 1–2.

### IP-2 — Durable registration + hard-fail pattern (state management)

**Pattern:** resolve `client.durable_task` by name; **hard-fail if absent**; delete `contextlib.suppress`; register each stage `client.durable_task(name=f"umd-{stage.lower()}", input_validator=UmdStageInput, eviction_policy=None)(handler)`; after the loop assert `len(registered_workflows) == len(STAGE_ORDER)` and raise `ConfigurationError` naming missing stages.

**State ownership:** durable state remains executor/Postgres-owned (`stage_run`, `StageCompleted`, job audit — L12); the SDK return value is a JSON-safe acknowledgement only; `is_durable=true` is engine-persisted via `to_proto` (AT-18) but Hatchet durable-context primitives (`aio_wait_for`/`aio_sleep_for`) are never used, so eviction/checkpoint semantics do not apply (explicit `eviction_policy=None`).
**Best-practice citations:** official docs `v1/durable-tasks` (durable task constraints: deterministic, no direct DB/external calls — our handler delegates to the executor precisely so the durable-task body stays thin); SDK `task.py`/`hatchet.py` at `py/1.38.1` (`durable_task` keyword-only `name`, returns `Standalone`, `is_durable` in `to_proto`); Python changelog 2026-08-25 (sync-durable deprecation).
**Key validation:** `client.durable_task` presence on 1.38.1 VERIFIED (T2 §0 row 3); v2.0.0 removal planned but not scheduled — recorded forward-compat debt.

### IP-3 — Truthful readiness pattern (error handling)

**Pattern:** `cli.py:123` → `n_workflows = len(handle.registered_workflows)` ONLY; if `n_workflows != len(STAGE_ORDER)`, print the missing names to stderr and return non-zero **before** printing the C6 ready line. Keep the ready line candidate-only (CI DD C6 owns wording; out of scope). Registration errors propagate (no suppress) so a decorator failure is a hard worker failure, never a silent empty registry.

**Best-practice citations:** Python docs `contextlib.suppress` (suppresses all exceptions — must never wrap registration whose failure is the gate signal); `wait-for-worker.sh` greps the C6 line — the count fix closes the local fabrication path (L7.2); hosted AT-16/17/18 remain the release proof (T2 §5: `put_workflow` failure can still kill the worker after the line prints — ready line is candidate evidence, never engine proof).
**Key validation:** no new library; behavior verified against current tree `cli.py:95-133` and `hatchet.py:417-448`.

### IP-4 — Engine-visible declaration assertion pattern (testing approach, A3′)

**Pattern:** new `cluster+docker` test polls `client.workflows.list()` (NO name filter — T2 A3-C1 correction) and asserts the exact `umd-<stage>` set client-side; scoped claims: declaration visibility only, never callback/durability/execution; the compose worker does the real `put_workflow`; no second worker started; composed under AT-19.
**Best-practice citations:** SDK `runnables/workflow.py` (`Workflow.id` → `workflows.list` + client-side `==`); docs `v1/workers` ("When a worker starts, it registers each of its tasks and workflows with Hatchet"); T2 §0 row 6b correction.
**Key validation:** REST filter semantics remain implementation-time (server `WorkflowApi.workflow_list` handler); the pattern is robust to either semantics because it filters client-side.

### IP-5 — Hermetic/live contract test pattern (testing approach)

**Pattern:** hermetic fixtures invoke `cb(UmdStageInput(**direct_input), _FakeCtx())` where `direct_input` mirrors `runner.py:232-245` submission shape `{job_id, source_id, dag_universe, stage, manifest, [causation_id]}`; real-SDK-shaped contract tests use `Standalone.mock_run(input=UmdStageInput(...))` (only faithful serialization in 1.38.1 — T2 §0 row 4); negative tests (one-arg handler, v0-wrapped payload) live on the real SDK surface (AT-16 wording); `_FakeCtx` carries an invariant comment ("handler must not consume ctx; re-verify on change"); hosted observed-callback + durable-rows gate unchanged and release-blocking.
**Best-practice citations:** spec-first contract testing — the L4 defect is the canonical example of a test double encoding the wrong contract; AT-16 requires real-SDK-shaped failure tests. Maintainer corpus: Hatchet's SDK test suite drives real callbacks, not recording doubles.
**Key validation:** `mock_run` dict-drop behavior VERIFIED (T2 §0 row 4); `aio_mock_run` exists (T2 §4).

### IP-6 — Tenant eligibility + assignment assertion pattern (evidence/workflow)

**Pattern:** validation.yml P2-S4 tenant discovery → deterministic scheduler-eligible selection (exactly one setup-created tenant OR exactly one tenant with non-null `schedulerPartitionId`+`workerPartitionId`; zero/multiple/null → fail closed with diagnosable output listing discovered tenants + partition states); record selected tenant + both partition IDs; mint JWT; before live execution assert JWT == worker == workflow == submitted-task tenant; assert tasks transition to ASSIGNED/RUNNING and callback-owned UMD rows appear (L8/AT-17); scope `is_durable=true` to the **latest** workflow version (T2 §5).
**Best-practice citations:** netns DD AT-17 (binding contract); `support-debugger.log.jsonl:L10-L11` (run `33229130339` falsifier: internal tenant with NULL partitions); engine source `pkg/repository/tenant.go`, `internal/services/scheduler/v1/scheduler.go` (scheduler lists tenants per `schedulerPartitionId`); plan P3-S3 notes (goose mixed-case schema discovery).
**Key validation:** no new library; psql discovery facts already documented in the Plan K P3-S3 notes.

### IP-7 — Error handling and observability pattern

**Pattern:** registration failures are loud (ConfigurationError, no suppress); ready line only after exact-count success; worker `put_workflow` failure may still exit after the line (SDK behavior) — the hosted gate is the arbiter; handler errors propagate to the executor's existing retry/quarantine paths (metrics `umd_stage_failures`, `umd_stage_attempts` — current tree hatchet.py:269-284); JSON-safe return keeps SDK step-output validation from rejecting post-executor results.
**Best-practice citations:** current tree error/metrics paths (hatchet.py:258-285) unchanged; SDK step-output `TypeAdapter` behavior (T2 A2-C2); T2 §5 readiness-ordering finding.
**Key validation:** no new library; all behavior verified against pinned SDK source + current tree.

### Testing approach summary

1. **Spec-first contract tests** (new, hermetic): `(input, ctx)` two-arg shape; one-arg handler fails; v0-wrapped payload fails; `UmdStageInput.model_validate(direct_input)` equals fixture input (guards S4 divergence).
2. **Real-SDK-shaped tests**: `Standalone.mock_run(input=UmdStageInput(...))` for contract fidelity; negative tests on the real SDK surface.
3. **Hosted gate** (unchanged, release authority): observed callback + durable UMD rows + `v1_task.is_durable=true` (latest version) + ASSIGNED/RUNNING transitions + tenant identity consistency (AT-16/17/18/19).
4. **Engine-visible declaration test** (A3′, additive): `workflows.list()` exact-set match, scoped to declaration rows.

### Key library choices (validated)

| Library | Version | Validation (2026-08-29) |
|---|---|---|
| `hatchet-sdk` | `==1.38.1` (pinned) | PyPI 2026-08-25; Python `<4,>=3.10`; wheel py3-none-any; primary source @ `py/1.38.1` |
| `pydantic` (v2) | existing pin | `UmdStageInput(BaseModel)` uses v2 `model_validate`/`model_dump`; SDK's `EmptyModel` is v2 `BaseModel` — compatible |
| `python-multipart` | `==0.0.32` | already pinned for API (researcher L3); not part of this change |
| server image | `ghcr.io/hatchet-dev/hatchet/hatchet-engine:v0.105.2` | release 2026-08-25; sub-path images verified HTTP 200 (researcher L4) |

### Mapping to Plan K phases (read-only design scope; plan amendment is Exec-Planner's job)

| Pattern | Plan K obligation | Gate |
|---|---|---|
| IP-1/IP-2 | P2-S5 handler + `durable_task` registration; P2-S4 tenant/JWT | AT-16, AT-18 |
| IP-3 | P2-S5/P3-S3 readiness count truthfulness; C6 candidate-only | L7.2, AT-19 |
| IP-4 | P3-S3 hosted engine-visible declaration test | AT-19 (additive) |
| IP-5 | P2-S5 hermetic fixtures + real-SDK contract tests | AT-16 |
| IP-6 | P2-S4/P3-S3 tenant selection + partition/assignment assertions | AT-17, L8 |
| IP-7 | P2-S5 error/observability unchanged | L7.1, L12 |
| Evidence | umd-evidence/ DB dump + callback rows + JUnit | AT-8/14, AT-16/17/18/19 |

## Pattern Risks

*(T6 Counter-Improver, 2026-08-29. Scope: adversarial risk assessment of the T5 patterns IP-1…IP-7 against the pinned SDK 1.38.1 / server v0.105.2 and the hosted evidence: edge cases, integration risks, library-specific gotchas, cross-pattern interaction failures. Each risk states trigger conditions, whether it matches THIS use case, and cites GitHub issues / docs / production incidents where available. Design-only: no production code, tests, workflows, DDs, or plans were edited; only this log was appended.)*

### PR-1 — Durable-slot assignment mismatch can reproduce the exact queued-but-unassigned failure (BLOCKING if unproven)

**Pattern at risk:** IP-2/IP-6 — all-durable registration → worker slot_config `{"durable": N}` → engine must assign durable slots.
**Trigger:** if the pinned engine v0.105.2 does not match durable slot requests to the worker (type mismatch, insufficient durable slot capacity, or a partition without the worker), `v1_task` rows stay QUEUED with zero `v1_task_runtime`/`WorkerAssignEvent` rows — the **identical observable** as run `33229130339` (`support-debugger.log.jsonl:L8`). This is not a theoretical edge case: it is the exact failure signature this whole adversarial process exists to prevent, on the *durable* axis instead of the *tenant* axis.
**Evidence:** engine `ListAvailableSlotsForWorkersAndTypes` / `scheduler_assignment.go` (T2 §5); v0.105.2 durable fixes in-flight (#4758 duplicate event-to-run, #4752 ordering + for update lock — T2 §4) show the durable assignment path is fresh and has had correctness bugs in this exact release.
**Applies here? YES — highest priority.** **Mitigation:** IP-6's ASSIGNED/RUNNING assertion is not optional; the first hosted run after the fix must show assignment + callback rows. If durable slots do not assign, the recorded pivot is mixed standard/durable registration or explicit engine slot config — a human decision (T8 Q). **Do not treat `is_durable=true` as proof of scheduling.**

### PR-2 — Strict-mypy overload rejection silently forces A1′ at the worst moment (MEDIUM)

**Pattern at risk:** IP-1/IP-2 — `UmdStageInput` typed decorator under strict mypy.
**Trigger:** if the installed 1.38.1 wheel's union overloads reject the typed callable, CI type-check fails late in the repair cycle. This is a *known* PROVISIONAL (T2 A2-C1, T4 S1), so it is not a surprise — but the risk is that the team discovers it after writing A2′ code and tests, then flips to A1′ under time pressure, silently dropping the boundary-validation benefit.
**Applies here? YES.** **Mitigation:** resolve the mypy question in the FIRST implementation step (a minimal typed registration spike + strict mypy run) before building fixtures/tests on the typed path; the A1′ fallback is fully specified so the flip is mechanical, not emergent.

### PR-3 — `input_validator` semantics divergence between `mock_run` and real dispatch re-creates a mini-L4 mask (MEDIUM)

**Pattern at risk:** IP-5 — hermetic `mock_run(UmdStageInput(...))` vs live `validate_python(ctx._workflow_input)`.
**Trigger:** if a field is optional in `UmdStageInput` but always present in `runner.py` submissions (or vice versa), `mock_run`-based tests can pass with a fixture shape that never occurs live — the same class of mask as the original v0-wrapper defect (L4), on a smaller scale.
**Applies here? YES.** **Mitigation:** IP-5's spec-first guard (`UmdStageInput.model_validate(direct_input)` equals the fixture input) plus the hosted observed-callback gate. Also add a *hosted* shape assertion: the first live callback's `input` must `model_validate` cleanly against `UmdStageInput` — this directly kills the mask class.

### PR-4 — JSON-safe return loses failure information if the executor result is the only record (MEDIUM)

**Pattern at risk:** IP-1/IP-7 — handler returns `{"idempotency_key", "state", "attempts"}`; the full `StageRunRecord` lives only in the store.
**Trigger:** if a stage's executor.run succeeds but store persistence fails (DB hiccup), the SDK sees a success acknowledgement while the durable row is absent — the hosted gate would catch this (callback-owned rows assertion), but the window between "SDK success" and "row present" is where a false-pass could hide if the gate polls too early.
**Applies here? YES (gate timing).** **Mitigation:** the hosted gate must poll for the durable rows (bounded, fail-closed) rather than accepting the callback ack; `_poll_until` pattern already exists in the live suite (`tests/test_hatchet_live.py:920-1006`). No design change to IP-1; an explicit gate-ordering note.

### PR-5 — Engine-visible REST assertion can still be a false negative on a HEALTHY stack (MEDIUM)

**Pattern at risk:** IP-4 — `client.workflows.list()` with no filter + client-side exact match.
**Trigger:** if the SDK's `WorkflowsClient.list` applies `apply_namespace(workflow_name)` to a `None` filter and the generated REST client still sends a query the server interprets as a filter, or if listing is paginated and the client only returns the first page, the exact-set match could fail on a healthy stack.
**Applies here? YES (SDK/API-shape uncertainty — T2 row 6b marked server handler re-verification required).** **Mitigation:** implementation step verifies `workflows.list()` with no args against the pinned engine (one probe in the first hosted run); the A3′ test is additive, so a failure here must NOT block the AT-16/17/18 gate — scope it as diagnostic with explicit non-authority framing.

### PR-6 — Latest-version scoping of `is_durable=true` is easy to get wrong (MEDIUM)

**Pattern at risk:** IP-6 — assert `is_durable=true` on the latest workflow version's tasks.
**Trigger:** repeated `put_workflow` (every worker start re-registers) creates new `WorkflowVersion` rows; a naive query (`WHERE is_durable=true LIMIT 1` or an aggregate over all versions) can pass on a stale historical row while the live version is non-durable — a false positive.
**Applies here? YES.** **Mitigation:** hosted assertion keys on the latest `WorkflowVersion` for each `umd-<stage>` name and checks its tasks' `is_durable`; the submitted `v1_task` rows must reference that version. This is a SQL-scoping discipline; record the exact query in the plan.

### PR-7 — Hermetic `_FakeCtx` divergence is discipline-dependent (LOW, guarded)

**Pattern at risk:** IP-5 — `_FakeCtx()` vs real `Context`.
**Trigger:** a future handler change that consumes `ctx` (logging, cancellation, task output) silently diverges hermetic from live behavior again.
**Applies here? LOW today (handler ignores ctx); HIGH as a maintenance hazard.** **Mitigation:** the invariant comment (IP-5) + prefer `mock_run` (real SDK `Context`) for contract tests over the recording-client path, which already reduces exposure.

### PR-8 — Sync-durable deprecation / v2.0.0 removal is tracked debt, not a release blocker (LOW, recorded)

**Pattern at risk:** IP-2 — sync durable handler with `DeprecationWarning`.
**Trigger:** a future SDK bump to a version where sync-durable is removed would fail registration at import/decorator time.
**Applies here? NO for this pin (1.38.1 warns only); YES at next bump.** **Mitigation:** CI DD C4 lockstep revalidation; the A4 forward-compat note is the recorded path (async conversion as a separate coordinated change).

### PR-9 — Cross-pattern interaction: IP-3 readiness + IP-4 engine assertion can double-claim readiness (MEDIUM)

**Pattern at risk:** `cli.py` ready line (IP-3) + engine-visible test (IP-4) both named "readiness" in prose.
**Trigger:** a reviewer or downstream consumer conflates the C6 candidate line (local handle truthfulness) with the A3′ engine-visible declaration (engine rows), reading the combination as "engine-visible readiness" — a false claim per T2 §5 (put_workflow can still fail after the line; declaration rows don't prove callback/durability).
**Applies here? YES (naming/claims discipline).** **Mitigation:** terminology contract — "candidate readiness" (C6 line) vs "engine-visible declaration" (A3′ test) vs "release proof" (AT-16/17/18 hosted gate) are three distinct concepts; the DD/plan must not collapse them.

### PR-10 — Ruled-out scope must not be silently re-opened (LOW)

**Pattern at risk:** none of IP-1…IP-7 touch DB/token/endpoint/`run_workflow` semantics (L6).
**Trigger:** an over-eager implementer "fixes" submission shape or token handling while touching the worker path.
**Applies here? LOW.** **Mitigation:** plan amendment explicitly lists L6 as out-of-scope-unchanged; any change to those files requires a separate R&D decision.

### L1–L21 check

No L item is at hard risk under the T5 patterns **if** PR-1 (durable-slot assignment) is proven hosted, PR-2 is resolved in the first implementation step, PR-3/PR-6 are guarded by the specified assertions, and PR-9's terminology contract is honored. L3/L4/L5, L7, L8, L12, L13/L14, L15, L16, L17–L21 all remain satisfied by the pattern set as designed. AT-16/17/18/19 remain implemented, not duplicated.

## Final Patterns

*(T7 Improver, 2026-08-29. Scope: final mitigated patterns with requirement-to-evidence mapping; reconcile AT-16/17/18/19 authority; revalidate affected technologies with source/check-date; label fundamental limitations. Each T6 PR is dispositioned: mitigated (with evidence) or acknowledged (fundamental). Design-only: no production code, tests, workflows, DDs, or plans were edited; only this log was appended.)*

### F-1 — Durable registration + hard-fail + explicit slot posture (mitigates PR-1, PR-8)

**Final pattern:** register every `umd-<stage>` via `client.durable_task(name=wf_name, input_validator=UmdStageInput, eviction_policy=None)(handler)`; `durable_task` missing ⇒ `ConfigurationError` (never fall back to `task`/`workflow`); delete `contextlib.suppress`; exact-count `len(registered_workflows) == len(STAGE_ORDER)` with missing-name diagnostics.
**PR-1 mitigation (structural, not cosmetic):** the hosted gate asserts (a) `is_durable=true` on the **latest** workflow version's tasks (PR-6), (b) submitted `v1_task` rows transition to **ASSIGNED/RUNNING** with `v1_task_runtime`/`WorkerAssignEvent` rows, and (c) callback-owned UMD rows (`stage_run`, `StageCompleted`, job audit) appear. PR-1 is only *resolved* by a hosted run showing (b)+(c); if durable slots do not assign, the recorded pivot (mixed standard/durable or engine slot config) is a human decision (T8 Q). **Evidence:** engine `ListAvailableSlotsForWorkersAndTypes`/`scheduler_assignment.go`; v0.105.2 durable fixes #4758/#4752 (checked 2026-08-29 via release notes/SDK changelog).
**PR-8 mitigation:** sync-durable `DeprecationWarning` recorded as forward-compat debt; revalidated at every SDK bump under CI DD C4.

### F-2 — V1 typed input boundary with JSON-safe return (mitigates PR-2, PR-3, PR-4)

**Final pattern:** `UmdStageInput(BaseModel)` fields `job_id`, `source_id`, `dag_universe`, `stage`, `manifest`, optional `causation_id`; `handler(input: UmdStageInput, ctx)` → `StageManifest.from_dict(input.manifest)` → executor; handler returns JSON-safe `{"idempotency_key", "state", "attempts"}`; full `StageRunRecord` stays in the store (L12).
**PR-2 mitigation:** first implementation step is a minimal typed-registration spike under strict mypy; A1′ (dict boundary) is the fully-specified mechanical fallback — the flip is a decision, not an emergency.
**PR-3 mitigation:** spec-first guard `UmdStageInput.model_validate(direct_input) == fixture input` (hermetic) AND a hosted shape assertion that the first live callback's input `model_validate`s cleanly (kills the mini-L4 mask class).
**PR-4 mitigation:** hosted gate polls for durable rows (bounded, fail-closed) via the existing `_poll_until` pattern (`tests/test_hatchet_live.py:920-1006`), never accepts the SDK callback ack alone.

### F-3 — Truthful candidate readiness (mitigates PR-9)

**Final pattern:** `cli.py` count = `len(handle.registered_workflows)` only; exact-count mismatch exits non-zero before the C6 line; C6 wording stays candidate-only (CI DD C6 owns it). Terminology contract in the DD/plan: **candidate readiness** (C6 line) ≠ **engine-visible declaration** (A3′ test) ≠ **release proof** (AT-16/17/18 hosted gate).
**PR-9 mitigation:** the three concepts are explicitly separated in all downstream documents; `wait-for-worker.sh`'s grep remains a startup signal, never a release gate.

### F-4 — Engine-visible declaration assertion, additive + scoped (mitigates PR-5)

**Final pattern:** `cluster+docker` test polls `client.workflows.list()` (no filter) and matches the exact `umd-<stage>` set client-side; claims declaration visibility ONLY; composed under AT-19; explicitly non-authority (a failure here is diagnostic, not release-blocking).
**PR-5 mitigation:** first hosted run includes a one-probe `workflows.list()` shape check against the pinned engine; the test's non-authority framing is structural (separate marker/step), so an SDK/API-shape surprise cannot block AT-16/17/18.

### F-5 — Tenant eligibility + identity + assignment evidence block (implements AT-17, L8)

**Final pattern (unchanged from IP-6):** deterministic scheduler-eligible tenant discovery (exactly one setup-created tenant or exactly one with non-null scheduler+worker partition IDs; zero/multiple/null → fail closed with diagnosable tenant list); record selected tenant + both partition IDs; mint JWT; assert JWT == worker == workflow == submitted-task tenant; assert ASSIGNED/RUNNING + callback rows. Scoped `is_durable=true` to the latest version (PR-6).
**Evidence:** netns DD AT-17; `support-debugger.log.jsonl:L10-L11` (run `33229130339` falsifier); engine tenant/partition source (T2 §5).

### F-6 — Hermetic/live contract tests with real-SDK shape (mitigates PR-7)

**Final pattern:** hermetic fixtures v1-shaped (`cb(UmdStageInput(**direct_input), _FakeCtx())`); contract tests prefer `Standalone.mock_run(input=UmdStageInput(...))`; negative tests (one-arg, v0-wrapped) on the real SDK surface; `_FakeCtx` invariant comment; hosted observed-callback + durable-rows gate unchanged.
**PR-7 mitigation:** `mock_run` uses the real SDK `Context`, so contract tests already exercise the real call path; the recording-client path is only for the non-contract seam tests.

### F-7 — Error handling + observability (unchanged, verified)

**Final pattern:** no suppress; loud registration failures; existing executor retry/quarantine/metrics paths unchanged (`hatchet.py:258-285`); JSON-safe return keeps SDK step-output validation from rejecting post-executor results.

### Requirement-to-evidence mapping (final)

| Requirement | Final pattern | Evidence / gate |
|---|---|---|
| L3/L5 (v1 direct-input contract) | F-2 handler `(input, ctx)` direct manifest | SDK `task.py` @ `py/1.38.1`; docs `v1/tasks` (2026-08-29) |
| L4 (hermetic mask) | F-6 v1 fixtures + real-SDK negatives + hosted shape assertion | AT-16; `test_hatchet_live.py:459-464` current-mask source |
| L7.1 (suppress) | F-1 hard-fail registration, no suppress | current tree `hatchet.py:426` removed |
| L7.2 (readiness truthfulness) | F-3 exact-count, candidate-only C6 | `cli.py:123` fallback removed; CI DD C6 |
| L7.3 / L19 (engine-visible or honest scope) | F-4 additive engine-visible declaration + renamed local test | AT-19; `workflows.list` exact-set |
| L8 (tenant eligibility + assignment) | F-5 partition/identity/assignment block | AT-17; run `33229130339` falsifier |
| L12 (durable async restart/retry/cancel) | F-1 durable registration + executor/Postgres durability + JSON-safe return | AT-18; store rows; v1_task ASSIGNED/RUNNING |
| L13/L14 (no skips/fake readiness/weak gates) | F-3/F-4/F-5 fail-closed everywhere; hosted gate release-blocking | AT-19 composition |
| L15 (hosted native Docker/Compose, zero skips) | unchanged | workflow validation |
| L16 (OCFL/evidence/provenance) | untouched | outside these files |
| AT-16 | F-2/F-6 | real-SDK-shaped contract tests + hosted observed callback + rows |
| AT-17 | F-5 | deterministic tenant + partitions + identity + assignment |
| AT-18 | F-1 | durable_task registration + latest-version `is_durable=true` |
| AT-19 | F-1…F-6 composed | joined with AT-1…15, release-blocking |

### Technology revalidation (source / check date)

- `hatchet-sdk==1.38.1` — PyPI 2026-08-25 (checked 2026-08-29); primary source `py/1.38.1` tag; handler contract + `durable_task` + `mock_run` behavior all VERIFIED (T2 §0).
- Server `v0.105.2` — GitHub release 2026-08-25 (checked 2026-08-29); sub-path images verified (researcher L4); durable-slot assignment must be proven hosted (F-1).
- `UmdStageInput` pydantic v2 model — compatible with SDK `EmptyModel`/validator semantics (T2 §0 row 2).
- No other library changes; `python-multipart==0.0.32` and existing pins untouched.

### Fundamental limitations (labeled, not hidden)

1. **PR-1 (durable-slot assignment) cannot be fully verified at design time** — only a hosted run with ASSIGNED/RUNNING + callback rows resolves it; the pivot (mixed registration / slot config) is a human decision.
2. **PR-2 (strict-mypy overload acceptance) is a fact about the installed wheel** — provable only by compiling; the A1′ fallback is the recorded path.
3. **PR-5 (REST list shape) is a fact about the server handler** — the A3′ test is explicitly non-authority until probed.
4. **Sync-durable deprecation is tracked debt** — revalidated at every SDK bump, not a release blocker for this pin.

## Open Risks & Human Questions

*(T8 Counter-Improver, 2026-08-29. Scope: residual risks, substantive human-judgment questions (tradeoffs evidence cannot decide), blockers, and the final adversarial recommendation. Explicitly verify every L1–L21 survives and AT-16/17/18/19 authority is reconciled, not duplicated. Design-only: no production code, tests, workflows, DDs, or plans were edited; only this log was appended.)*

### 1. Residual risks (final register)

| # | Risk | Severity | Status / mitigation |
|---|---|---|---|
| R1 | Durable-slot assignment mismatch reproduces queued-but-unassigned on the durable axis | **BLOCKING until hosted-proven** | F-1 gate asserts ASSIGNED/RUNNING + callback rows; pivot (mixed registration / slot config) is Q1 below |
| R2 | Strict-mypy rejects `UmdStageInput` typed overloads | MEDIUM | First-step spike; A1′ mechanical fallback (Q2) |
| R3 | `input_validator` divergence between `mock_run` and live dispatch re-creates a mini-L4 mask | MEDIUM | Spec-first guard + hosted shape assertion (F-2) |
| R4 | Hosted gate accepts SDK ack before durable rows exist | MEDIUM | `_poll_until` for rows; never ack-only (F-2/PR-4) |
| R5 | Engine REST list shape surprises (pagination/filter semantics) | MEDIUM | A3′ non-authority; one-probe on first hosted run (F-4) |
| R6 | `is_durable=true` scoped to a stale workflow version | MEDIUM | Latest-version keying in hosted SQL (F-5/PR-6) |
| R7 | `_FakeCtx` divergence on future `ctx` use | LOW | Invariant comment + `mock_run` preference (F-6) |
| R8 | Sync-durable deprecation becomes removal at next SDK bump | LOW (this pin) | CI DD C4 revalidation; A4 forward-compat (F-1) |
| R9 | Terminology conflation (candidate vs engine-visible vs release proof) | MEDIUM | F-3 terminology contract in DD/plan |
| R10 | Ruled-out scope (L6) re-opened by implementer | LOW | Plan lists L6 as out-of-scope-unchanged (PR-10) |

### 2. Human questions requiring judgment (substantive tradeoffs; evidence alone cannot decide)

- **Q1 (blocks the next hosted run decision): durable-slot posture.** Should the repair ship **all-durable** registration (AT-18 literal: every release task `client.durable_task`) and prove durable-slot assignment hosted, or ship **mixed standard/durable** (durable registration for release tasks, standard for others) to reduce the engine-assignment surface? **Stakes:** AT-18 requires `v1_task.is_durable=true` for release tasks, but the scheduler must actually assign durable slots or tasks stay queued — the exact failure we are eliminating. **Evidence-based recommendation:** ship all-durable per AT-18's literal contract, with the hosted ASSIGNED/RUNNING assertion as the gate; if the first hosted run shows stuck-queued `is_durable=true` tasks, the recorded pivot is to investigate engine slot config before considering mixed registration (a separate DD decision, not an on-the-fly change).
- **Q2: typed vs dict input boundary.** Adopt **A2′** (`UmdStageInput`, runtime validation, attribute access) and accept the strict-mypy spike risk, or pin **A1′** (`input_validator=dict`, guaranteed-verifiable) and lose boundary validation? **Stakes:** A2′ gives the strongest contract enforcement (AT-16) but depends on the installed wheel's overloads; A1′ is the safe floor. **Recommendation:** spike A2′ first (one step, strict mypy); if rejected, adopt A1′ mechanically — do not spend the repair cycle fighting type stubs.
- **Q3: engine-visible declaration test (A3′).** Keep the additive `cluster+docker` `workflows.list()` exact-set assertion (in-suite engine visibility, declaration-only), or drop it and rely solely on the DB-dump + callback-rows gate? **Stakes:** L19 asks for "engine-visible proof or honest test scope"; A3′ is the in-suite engine surface but cannot prove execution/durability. **Recommendation:** keep A3′ as a non-authority diagnostic (separate marker), because losing it removes the only in-suite engine visibility and invites log-grep-only drift.
- **Q4: `eviction_policy=None` explicit choice.** Confirm registering durable tasks with an explicit no-eviction policy (handler never uses durable wait primitives), or accept the SDK default `DEFAULT_DURABLE_TASK_EVICTION_POLICY`? **Stakes:** the default exists for checkpointing durable tasks; UMD's handler delegates work to the executor and never checkpoints, so eviction semantics are dead weight. **Recommendation:** explicit `eviction_policy=None`, recorded in the plan.
- **Q5: sync-durable debt acceptance.** Accept the `DeprecationWarning` on sync durable handlers for this pin (tracked forward-compat debt, v2.0.0 removal un-scheduled), or pull A4 (async handler) into this repair now? **Stakes:** A4 expands blast radius into the churny v0.105.2 durable path for zero functional gain (L12 durability is executor-owned). **Recommendation:** ship sync-durable with the recorded note; schedule A4 as a separate coordinated change (CI DD C4 lockstep).

### 3. Blockers

- **B1 (pre-Phase-6):** the hosted run must show `v1_task` rows transitioning to ASSIGNED/RUNNING with callback-owned UMD rows (F-1/F-5) before Phase 6 may begin. A ready line, registration rows, or `is_durable=true` alone is insufficient (AT-19).
- **B2 (pre-implementation):** the strict-mypy typed-registration spike (Q2) must be resolved before building A2′ fixtures/tests; A1′ is the recorded fallback.
- **B3 (pre-finalization):** `client.workflows.list()` shape probe on the first hosted run (F-4/PR-5) must be captured as evidence.

### 4. Final recommendation (adversarial verdict)

**Adopt the F-1…F-7 final pattern package** — A2′ typed input boundary with A1′ as the specified fallback, hard-fail `durable_task` registration, truthful candidate-only readiness, additive scoped engine-visible declaration assertion (A3′), tenant eligibility + identity + assignment evidence block, and hermetic/live contract tests with real-SDK shape. The hosted AT-16/17/18/19 gate remains release authority; nothing in this design weakens or duplicates it. A4 is deferred forward-compat. This package directly repairs the primary root cause (L3/L4/L5), removes the L7 fabrication paths, preserves L8's tenant/assignment requirement, and satisfies L12 durability through executor/Postgres ownership with the JSON-safe handler return.

### 5. L1–L21 survival verification (explicit, per item)

- **L1** — adversarial R&D continues this artifact; downstream DD/plan amendment follows. **SURVIVES.**
- **L2** — run `33229130339` evidence reproduced exactly in T1/T2/T3. **SURVIVES.**
- **L3** — v1 callback contract repaired by F-1/F-2. **SURVIVES.**
- **L4** — hermetic mask removed by F-6 + hosted shape assertion. **SURVIVES.**
- **L5** — direct dict with manifest is the handler input. **SURVIVES.**
- **L6** — DB/token/endpoint/run_workflow ruled out, never re-opened. **SURVIVES.**
- **L7** — suppress removed, readiness truthful, engine-visible or honest scope. **SURVIVES.**
- **L8** — tenant eligibility + partition IDs + identity + assignment/runtime assertions. **SURVIVES.**
- **L9–L16** — Task.md DoD, Hatchet sole scheduler, real callbacks/DurableStageExecutor, durable async restart/retry/cancel/invalidation, no skips/fake readiness/doubles, no weakened gates, hosted native Docker/Compose + public HTTP E2E + zero skips + evidence-before-closure, OCFL/evidence/semantic/provenance invariants — all preserved; no pattern removes or weakens them. **SURVIVE.**
- **L17** — this artifact is the adversarial refinement stage; librarian/researcher evidence is the corpus; architect/complexity/estimator/DDAuthor/PatternEnforcer remain downstream stages per the mandated sequence (this scope covers only the adversarial stage; the run's formal-process obligation is tracked by the Manager). **SURVIVES within scope.**
- **L18** — plan amendment under `artifacts/plans/pending` is the downstream Exec-Planner obligation, not this design scope. **SURVIVES (handoff).**
- **L19** — spec-first contract tests, real callback fix, hermetic alignment without lowering the live gate, surfaced registration failures/readiness truthfulness, engine-visible proof or honest scope, assignment/runtime diagnostics, rerun hosted CI — all mapped in F-1…F-7. **SURVIVES.**
- **L20** — no production code, tests, workflows, DDs, or plans edited by any turn in this artifact. **SURVIVES.**
- **L21** — this section, the Validation Manifest, and the Refiner's output carry plan paths, ledger, risks, and acceptance evidence for Exec-Manager. **SURVIVES.**

**AT-16/17/18/19 authority:** implemented by F-2/F-6 (AT-16), F-5 (AT-17), F-1 (AT-18), F-1…F-6 composed under AT-19 — reconciled, not duplicated; the netns DD remains binding.

---

## Validation Manifest

*(Refiner, 2026-08-29. Eight-turn adversarial sequence complete. This manifest records the source ranges, canonical heading order, technology validation, unresolved risks, human questions, verdict, and mandatory-item check. No production code, tests, workflows, DDs, or plans were edited by this artifact; the prelude/ledger (lines 1–82) is immutable and was preserved unchanged.)*

### Source ranges (this artifact)

| Section | Heading | Lines |
|---|---|---|
| Prelude + immutable ledger | lines 1–82 | preserved verbatim |
| T1 | `## Proposed Approaches` | 84–177 |
| T2 | `## Critique` | 180–253 |
| T3 | `## Refined Approaches` | appended |
| T4 | `## Surviving Concerns` | appended |
| T5 | `## Implementation Patterns` | appended |
| T6 | `## Pattern Risks` | appended |
| T7 | `## Final Patterns` | appended |
| T8 | `## Open Risks & Human Questions` | appended |
| Validation Manifest | this section | appended |

### Canonical heading order (structural check)

- [x] `## Proposed Approaches` (T1)
- [x] `## Critique` (T2)
- [x] `## Refined Approaches` (T3)
- [x] `## Surviving Concerns` (T4)
- [x] `## Implementation Patterns` (T5)
- [x] `## Pattern Risks` (T6)
- [x] `## Final Patterns` (T7)
- [x] `## Open Risks & Human Questions` (T8)

All eight mandated headings are present in exact order; no turn was skipped, merged, or replaced with a generic acknowledgment.

### Technology validation summary (all checked 2026-08-29)

- `hatchet-sdk==1.38.1` / server `v0.105.2` — VERIFIED (PyPI / GitHub release / SDK source at `py/1.38.1`; docs.hatchet.run).
- Handler contract `fn(input, ctx)` direct-input — VERIFIED (T2 §0 row 1; docs `v1/tasks`, `reference/python/context`).
- `client.durable_task` + sync-durable deprecation — VERIFIED (T2 §0 row 3; Python SDK changelog 2026-08-25; engine commit `a6650ab`).
- `mock_run` dict-drop — VERIFIED (T2 §0 row 4).
- REST `workflows.list` filter semantics — PARTIALLY VERIFIED (T2 §0 row 6b; server handler re-verification required at implementation).
- Durable-slot assignment — VERIFIED at mechanism level; **hosted proof required** (F-1, R1).

### Unresolved risks (final register)

R1 (durable-slot assignment, BLOCKING until hosted), R2 (strict-mypy spike), R3 (validator divergence), R4 (gate polling), R5 (REST shape probe), R6 (latest-version scoping), R7 (`_FakeCtx`), R8 (deprecation debt), R9 (terminology), R10 (L6 scope). All have mitigations or recorded decisions; none is silently waived.

### Human questions (T8 Q1–Q5)

Q1 durable-slot posture (all-durable vs mixed) — recommended all-durable per AT-18 with hosted ASSIGNED/RUNNING gate; Q2 typed vs dict boundary — spike A2′ first, A1′ fallback; Q3 A3′ additive test — keep as non-authority diagnostic; Q4 `eviction_policy=None` — explicit; Q5 sync-durable debt — ship with recorded note, defer A4.

### Verdict

**PASS — adversarial refinement complete.** The refined package (F-1…F-7) directly repairs the L3/L4/L5 root cause, removes the L7 fabrication paths, preserves L8/L12, and keeps the hosted AT-16/17/18/19 gate release-authority and release-blocking. No gate was weakened, no fabrication path survived, no citation was invented (all citations trace to the recorded evidence corpus: `support-debugger.log.jsonl:L8-L12`, `support-researcher.log.jsonl:L3,L4,L9,L10`, netns DD AT-16/17/18/19, SDK source at `py/1.38.1`, docs.hatchet.run, GitHub releases/changelog — all checked 2026-08-29).

### Mandatory-item check

- [x] All 8 turns completed with substantive, cited output.
- [x] At least one approach genuinely challenged (T2 A3 filter HIGH correction; T2 A1 fallback-chain defect; T4/T6 durable-slot BLOCKING finding — each addressed in T3/T7).
- [x] Every citation follows to a recorded real source (support logs, netns DD, SDK primary source, official docs, GitHub release/changelog).
- [x] Adversarial log contains the full fight; DD `DD-universal-media-decomposer-plan-k-live-hatchet-blocker.md` remains a skeleton (only Manager input) for DDAuthor.
- [x] No turn skipped, merged, or replaced with a generic acknowledgment.
- [x] L1–L21 survival verified explicitly (T8 §5).
- [x] AT-16/17/18/19 reconciled, not duplicated.
- [x] No production/workflow/test/DD/plan edits (L20) — only this log was appended.

**Final status: DONE** — all eight turns physically present, substantively cited, and validated. Handoff: DDAuthor distills the decisions into the DD; Exec-Planner amends Plan K (P2-S4/P2-S5/P3-S3, Phase 6 gate) per the F-1…F-7 mappings and T8 Q1–Q5; Exec-Manager executes with the hosted run as the release arbiter.

## Refined Approaches (T3 Ideator verification resubmission — 2026-08-29)

> **Preamble (append nature, L20 honored):** This file already contains a complete T1–T8 adversarial record. The canonical T3 `## Refined Approaches` section (lines 255–331) predates this run and is preserved **untouched**. This section is the Ideator's independent T3 verification resubmission: every T2 mandatory condition re-checked against primary sources on 2026-08-29, two empirically confirmed findings not previously cited (F-A/F-B), and the exact refined code shapes for A1′/A2′/A3′/A4′. Heading intentionally distinct from the canonical T3 heading to preserve the file's canonical heading order (see Validation Manifest §"Canonical heading order").

### 0. New empirical findings this run (both drive the JSON-safe return requirement)

- **F-A — `TypeAdapter(StageRunRecord)` fails at decoration time.** `Task.__init__` (runnables/task.py, tag py/1.38.1) builds `step_output=TypeAdapter(normalize_validator(get_type_hints(_fn).get("return")))`. `StageRunRecord` is a `@dataclass` (src/umd/jobs/stage_execution.py:153-165) whose first field `claim: StageRunClaim` is a **plain class** (`__slots__` + custom `__init__`, src/umd/storage/postgres/stage_repository.py:64-89) — not a BaseModel, not a dataclass. Empirically confirmed in this repo (pydantic installed): `TypeAdapter(Rec)` where `Rec` is a dataclass holding such a class raises `PydanticSchemaGenerationError` immediately (`arbitrary_types_allowed` defaults to False). **Consequence: the handler must NOT be annotated `-> StageRunRecord`** — the decoration itself would raise.
- **F-B — even the current permissive `-> Any` return fails at runtime serialization.** The runner's `serialize_output` (worker/runner/runner.py, py/1.38.1) accepts the StageRunRecord (it passes the `is_dataclass(output)` check) but then calls `validator.dump_json(output)`; empirically confirmed: `TypeAdapter(Any).dump_json(dataclass_with_plain_class_field)` raises `PydanticSerializationError: Unable to serialize unknown type: StageRunClaim`, wrapped by the runner as `IllegalTaskOutputError` → `STEP_EVENT_TYPE_FAILED` → **the task fails AFTER executor work committed**. `dataclasses.asdict(record)` leaves `StageRunClaim` as-is (also empirically confirmed `json.dumps` TypeError), so even asdict does not rescue the return path.
- **Consequence for both A1′ and A2′:** the handler's return MUST be a flat, JSON-safe mapping projection of the record; executor results stay in the durable store (L12). The return is an acknowledgment, not the record (L10). This is a **latent second live blocker** that the arity fix alone would not cure — it was never observed live because the arity TypeError fired first, and the hermetic suite never exercised `serialize_output` (the recording-client path bypasses it — a masked-path instance of the L4 pattern).

### 1. Refined A1′ — Direct-Dict Minimal (fallback candidate; hardened per T2 conditions 1, 7, 8)

**Handler (src/umd/jobs/hatchet.py `_make_handler`, ~line 229):**
```python
def handler(workflow_input: dict[str, Any], ctx: Any) -> dict[str, Any]:
    manifest = workflow_input["manifest"]           # v1 direct input; NO v0 {"input": ...} wrapper
    ...                                             # existing executor wiring unchanged
    record = executor.run(...)
    return _record_to_json_safe(record)             # F-A/F-B: flat JSON-safe mapping, results stay in durable store (L12)
```
`_record_to_json_safe(record)` returns only JSON-safe scalars: `{"claim_status", "claim_id", "idempotency_key", "stage_name", "job_id", "state", "attempts", "completion_seq", "replayed", "error"}` — never the `StageRunClaim` object.

**durable_task resolution with hard-fail (replaces `getattr(client, "task", None) or getattr(client, "workflow", None)` inside `contextlib.suppress(Exception)` at hatchet.py:417-431; condition 1):**
```python
decorator = getattr(client, "durable_task", None)
if decorator is None:
    raise ConfigurationError(   # repo's own error type (hatchet.py:82-87); NEVER client.task/client.workflow fallback
        "hatchet-sdk 1.38.1 must expose client.durable_task (AT-18); "
        "refusing to register non-durable tasks. A silent fallback would convert "
        "a guaranteed AT-18 violation into a late, undiagnosed failure."
    )
decorator(name=wf_name, input_validator=dict, eviction_policy=None)
```
The `input_validator=dict` satisfies the SDK input bound (`_TWorkflowInputBound = BaseModel | DataclassInstance | dict[str, Any]`, runnables/types.py py/1.38.1). `eviction_policy=None` per condition 9 (see §4). The hermetic fake client (`dict_client` branch) must also expose a `durable_task` attribute so the same resolution path executes in tests — the fake records `workflows[wf_name]` + `callbacks[wf_name]` as today, plus records the `eviction_policy` argument.

**Readiness count (src/umd/deploy/cli.py:123):** `n_workflows = len(handle.registered_workflows) or (len(work_registry) if work_registry else 0)` stays, but the ready line must be emitted **before** `worker.start()` and use the C6 candidate wording: `"worker ready: registered {n_workflows} Hatchet workflows (candidate, pending Plan J live validation)"`. Exact count = number of durable registrations that actually succeeded; a partial registration (decorator raised after some registrations) must surface as failure, not a lower count (L7).

**AT-18 falsifier design (condition 7):**
- (7a) Version scoping: hosted assertion must scope `is_durable=true` to the **latest version's** tasks. Endpoint `GET /api/v1/workflows/{workflow}/versions` verified present in the generated SDK client (workflow_api.py py/1.38.1, resource_path line 8231). Falsifier: an older version carries `is_durable=true` while the latest does not → fail.
- (7b) Durable-slot matching: `is_durable=true` alone is insufficient — worker durable slots derive from task `slot_requests` (`{"durable": 1}` in `to_proto`, task.py py/1.38.1), and the runner registers runs with `durable_eviction_manager.register_run(eviction_policy=action_func.eviction_policy)`. The gate must additionally assert a live task transitions to **ASSIGNED/RUNNING** (L8 assignment/runtime state) on the scheduler-eligible tenant (AT-17). Falsifier: `is_durable=true` present but the run remains QUEUED-without-ASSIGNED → fail (this is the exact queued-but-unassigned failure class).

**Hermetic fixture + negative-test design (condition 8):**
- Two-arg hermetic fixture: `_invoke_callback` becomes `cb(direct_input, _FakeCtx())` where `direct_input` is the v1 direct input dict (not `{"input": {...}}`). `_FakeCtx()` carries the invariant docstring: *"handler must not consume ctx; re-verify on change"*.
- mock_run-based contract tests (real SDK shape): `Task.call`/`aio_mock_run` invoke `self._fn(workflow_input, cast(Context, ctx))` with `workflow_input` built by `_create_mock_context`. Because mock_run drops raw dicts to `{}` (verified: `_create_mock_context` serializes only dataclass via `asdict` and BaseModel via `model_dump`; dict → `serialized_input = {}`), **A1′'s mock_run contract test must pass a minimal BaseModel wrapper** (per condition 8) — e.g., the shared `UmdStageInput` — so the input round-trips; the real-dict path is covered by the direct `_invoke_callback` two-arg fixture.
- Negative tests on the real SDK surface (per AT-16 wording "real-SDK-shaped test fails on one-argument/v0"): (a) a one-arg handler `def fn(payload)` decorated via `client.durable_task(...)` → invoking real `Task.call` raises TypeError (arity) — assert on the real SDK call path; (b) the v0-payload test is **labeled as a shape-check, not SDK-fidelity** — the hermetic suite asserts the handler raises KeyError/validation error on `{"input": {...}}`-shaped payloads, while the real-SDK-surface test proves the SDK itself never builds that shape.

### 2. Refined A2′ — Typed Pydantic Input Boundary (PRIMARY; hardened per T2 conditions 1–3, 9)

**Handler + model:**
```python
class UmdStageInput(BaseModel):
    """Direct v1 input contract (AT-16). Typed access; validated at the task boundary."""
    manifest: StageManifest
    stage: str
    job_id: str
    ...

def handler(workflow_input: UmdStageInput, ctx: Any) -> dict[str, Any]:
    manifest = workflow_input.manifest            # typed access, never ["input"]["manifest"]
    ...
    record = executor.run(...)
    return _record_to_json_safe(record)           # F-A/F-B: JSON-safe mapping; results in durable store (L12)
```
Registration: `client.durable_task(name=wf_name, input_validator=UmdStageInput, eviction_policy=None)`.

**Strict-mypy overload pinning (condition 2; source-verified at tag py/1.38.1, checked 2026-08-29):** From runnables/types.py: `_TWorkflowInputBound: TypeAlias = BaseModel | DataclassInstance | dict[str, Any]`; `R = TypeVar("R", bound=ValidTaskReturnType)` with `ValidTaskReturnType = BaseModel | Mapping[str, Any] | DataclassInstance | None`. `UmdStageInput(BaseModel)` satisfies the input bound; the handler's `dict[str, Any]` return satisfies the `R` bound via `Mapping[str, Any]`. The decorated callable `Callable[Concatenate[TWorkflowInput, Context, P], R | CoroutineLike[R]]` accepts the sync `(UmdStageInput, Any) -> dict[str, Any]` handler (`Any` is compatible with `Context`). **PROVISIONAL:** the actual `mypy --strict` run against the pinned SDK must execute at implementation time (hatchet_sdk is not installed in this environment); the type contracts above are verified from source, the tool result is not yet.

**Return-type boundary (condition 3; L10 SDK step-output validation):** Resolved by the F-A/F-B findings: `StageRunRecord` passes the type-level bound (`@dataclass` ⇒ `DataclassInstance`) but **fails at runtime** — `TypeAdapter(StageRunRecord)` raises `PydanticSchemaGenerationError` at decoration (F-A) and even the permissive validator fails `dump_json` on the embedded `StageRunClaim` (F-B). Correct design: annotate `-> dict[str, Any]` and return the JSON-safe projection; executor results stay in the durable store (L12). `TypeAdapter(dict[str, Any])` builds cleanly.

**Eviction policy (condition 9; source-verified, checked 2026-08-29):** `Hatchet.durable_task(..., eviction_policy: EvictionPolicy | None = DEFAULT_DURABLE_TASK_EVICTION_POLICY)` (root hatchet.py:950). `DEFAULT_DURABLE_TASK_EVICTION_POLICY = EvictionPolicy(ttl=timedelta(minutes=15), allow_capacity_eviction=True, priority=0)` (runnables/eviction.py py/1.38.1) — the default makes runs capacity-evictable. The EvictionPolicy docstring: "Setting the durable task's eviction params to `None` means the task run is never eligible for eviction." UMD's handler never calls durable-context wait primitives, so register `eviction_policy=None` explicitly; the server v0.105.2 #4772 fix (T2 citation) addresses the durable-run eviction path further.

**AT-18 falsifiers:** identical to A1′ (7a latest-version-scoped `is_durable=true`; 7b ASSIGNED/RUNNING transition assertion). **Hermetic/negative tests:** two-arg `_FakeCtx()` invariant fixture; contract tests via `mock_run`/`aio_mock_run` — here the BaseModel round-trips correctly through `_create_mock_context` (`model_dump`); negative tests on the real SDK surface: one-arg handler → real `Task.call` TypeError; v0 payload → `UmdStageInput.model_validate({"input": {...}})` raises ValidationError (missing `manifest`) — shape-check labeled.

### 3. Refined A3′ — engine-visible registration assertion (test-only, additive; corrected per conditions 4, 5, 7)

**Corrected filter semantics (condition 4; checked 2026-08-29):** The REST `name` filter is **not contractually exact**:
- OpenAPI spec `api-contracts/openapi/paths/workflow/workflow.yaml` (v0.105.2): the `name` parameter of `workflow:list` is documented only as *"Search by name"* — no exact/prefix/substring semantics defined.
- SDK client `WorkflowsClient.list` forwards `name=self.client_config.apply_namespace(workflow_name)` straight to `GET /api/v1/tenants/{tenant}/workflows` (features/workflows.py py/1.38.1) — no client-side filtering.
- The SDK's own `Workflow.id` then **re-filters client-side with exact `==`** (`if workflow.name == self.name`, runnables/workflow.py py/1.38.1) — proof the SDK itself does not trust the filter for exact matching.
**Therefore `workflow_name="umd-"` is a false-negative trap (T2 HIGH confirmed):** list **without** the name filter and match the exact `umd-<stage>` set client-side:
```python
rows = client.workflows.list().rows                    # no name= filter
registered = {w.name for w in rows}
missing = EXPECTED_UMD_STAGES - registered             # exact string match
assert not missing, f"engine does not see declared workflows: {missing}"
```
**Scoped claims (condition 5):** the query proves **declaration visibility ONLY** — that the engine's tenant-visible workflow list contains the registered names. It proves **neither** callback execution **nor** durability. Keep it additive; the DB-dump + callback-row gate stays the release authority under AT-19. Label the test honestly (L7.3/L19).
**Version scoping (condition 7a):** the `is_durable=true` assertion must scope to the latest version's tasks via `GET /api/v1/workflows/{workflow}/versions` (endpoint verified in the SDK client).
**Slot/ASSIGNED (condition 7b):** declaration visibility does not imply durable-slot assignment; the hosted gate must assert a live run transitions to ASSIGNED/RUNNING on the scheduler-eligible tenant (L8, AT-17). A3′ is a diagnostic, not a durability proof.

### 4. A4 — Async durable handler: DEFERRED forward-compat with tracked debt (condition 6)

Keep A4 deliberately deferred; **do not make it the default for this repair.** The SDK already emits `DeprecationWarning` for sync-durable handlers ("Non-async durable tasks are deprecated and will be removed in v2.0.0", verified task.py py/1.38.1). Record the sync-durable deprecation as tracked debt: surface the DeprecationWarning in worker logs, note v2.0.0 is **unscheduled**, and revisit A4 only when the SDK actually removes sync-durable support. No code change this repair.

### 5. Explicit TEST/EVIDENCE DESIGN per candidate

- **Spec-first handler contract tests (L19):** both A1′ and A2′ rework `_invoke_callback` to the two-arg `(direct_input, _FakeCtx())` shape; the contract test asserts the `fn(input, ctx)` signature directly (spec-first), covering the direct-dict path (A1′) and the typed path (A2′).
- **Hermetic alignment without lowering the live gate (L4/L13/L14):** hermetic suite (fake client + fake `durable_task`) proves wiring and the hard-fail resolution; real-SDK `mock_run`/`aio_mock_run` tests prove the SDK call path with real `Task.call` semantics; the hosted live suite remains the release authority (L15 rerun). The hermetic suite never pretends to prove durability — that stays hosted.
- **Surfaced registration failures and readiness truthfulness (L7):** missing `durable_task` → `ConfigurationError` at startup (not a suppressed fallback); readiness count is the exact durable-registration count, emitted before `start()` with C6 candidate wording.
- **Engine-visible proof or honest test scope (L7.3/L19):** A3′ is labeled declaration-visibility-only; durability/execution proof is the DB-dump + callback-row gate under AT-19.
- **Tenant partitions + assignment/runtime diagnostics (L8):** hosted assertion runs on the scheduler-eligible tenant with non-null partitions (AT-17) and asserts task runs transition to ASSIGNED/RUNNING — the falsifier for durable-slot matching (condition 7b).
- **Rerun of hosted CI (L15):** after the repair, rerun the full hosted connect/register/execute suite on the pinned CANDIDATE pair (hatchet-sdk==1.38.1 ↔ server v0.105.2) per C4's promote gate; the engine-visible assertion (A3′) and the DB-dump/callback-row gate must both pass before release.

### 6. Technology revalidation (all checked 2026-08-29; §5 invariant)

| Technology / version | Source | Check date | Best-fit statement |
|---|---|---|---|
| hatchet-sdk 1.38.1 | tag `py/1.38.1`: runnables/task.py, runnables/types.py, runnables/eviction.py, runnables/workflow.py, worker/runner/runner.py, root hatchet.py | 2026-08-29 | Pinned CANDIDATE per CI DD C4. Not "newest" — 1.38.1 is the pinned pair member; its `durable_task` + v1 `(input, ctx)` contract is what AT-16/18 require. Verified: two-arg call arity; mock-run dict-drop; `durable_task` kw-only `name` + `eviction_policy` default; TypeVar bounds; step_output TypeAdapter; serialize_output; sync-durable DeprecationWarning. |
| hatchet engine v0.105.2 | tag `v0.105.2`: api-contracts/openapi/paths/workflow/workflow.yaml; generated client endpoint paths | 2026-08-29 | Pinned server per C4. `name` param documented only as "Search by name" (no exact-match contract) → A3′ lists unfiltered. #4772 durable-eviction fix per T2 citation. |
| pydantic (installed) | direct empirical execution in this repo | 2026-08-29 | F-A/F-B confirmed by execution: plain-class field in a dataclass fails TypeAdapter schema generation; Any-validator dump_json fails on plain objects. Drives the JSON-safe mapping return in both candidates. |
| `mypy --strict` acceptance of the decorated handler | runnables/types.py + runnables/task.py overloads | 2026-08-29 (contract), tool run PENDING | PROVISIONAL — type contracts verified from source; the actual strict-mypy run against the pinned SDK must execute at implementation time (SDK not installed in this env). |
| worker runner output-serialization ordering | worker/runner/runner.py at py/1.38.1 | 2026-08-29 (source read) | PROVISIONAL — source-read, not executed; serialize_output behavior independently confirmed by the F-B empirical test of the underlying TypeAdapter call. |

No approach claims a durability/execution proof from the hermetic suite; everything hinges on the hosted gate (AT-19) — unchanged.

### 7. L1–L21 survival statement (after refinement)

- **A1′ SURVIVES** as the minimal fallback candidate: two-arg direct-dict handler; hard-fail `durable_task` resolution by name with `ConfigurationError` (no client.task/workflow fallback — condition 1); JSON-safe return projection (F-A/F-B); exact-count readiness before start() (C6); two-arg `_FakeCtx()` invariant fixture; mock_run with model wrapper even in A1′ (condition 8); negative tests on the real SDK surface; AT-18 falsifiers version-scoped (7a) + ASSIGNED/RUNNING (7b).
- **A2′ SURVIVES** as the recommended primary: typed `UmdStageInput` boundary; mypy pinning verified against SDK source (mypy tool run PROVISIONAL); return-type boundary resolved via JSON-safe mapping (L10/L12); `eviction_policy=None` (condition 9); all A1′ falsifiers and hermetic/negative-test designs carry over.
- **A3′ SURVIVES ONLY** as a test-only additive declaration-visibility assertion: `workflow_name="umd-"` filter removed (server semantics undocumented/inexact; SDK re-filters exact client-side); claims scoped to declaration visibility; `is_durable=true` version-scoped; ASSIGNED/RUNNING falsifier lives in the hosted gate.
- **A4 SURVIVES ONLY** as deferred forward-compat with tracked debt (DeprecationWarning surfaced; v2.0.0 unscheduled).
- **No approach survives as a durability/execution proof** without the DB-dump + callback-row release authority under AT-19. All nine T2 mandatory conditions adopted — none refuted; every one was verified against primary sources (SDK source at py/1.38.1, engine OpenAPI at v0.105.2, empirical pydantic runs).
