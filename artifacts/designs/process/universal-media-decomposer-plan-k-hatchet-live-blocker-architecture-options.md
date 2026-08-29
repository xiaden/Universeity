# Universal Media Decomposer — Plan K LIVE HATCHET BLOCKER Architecture Options

**Status:** DONE — bounded architecture/options report  
**Date:** 2026-08-29  
**Scope:** The live Hatchet blocker exposed by run `33229130339`, Docker job
`99038602321`, SHA `6614b32`.  This is a distinct architecture report for the
callback/registration/readiness/tenant-proof defect set.  It does not replace
the netns report or create a second gate authority.

## Verdict

```yaml
status: DONE
verdict: SELECTED_BOUNDED_PACKAGE
selected_approach: "A2' typed v1 boundary + A1' mechanical fallback + A3' additive declaration check"
release_authority: "Netns DD AT-16/17/18/19 composed with AT-1..15"
implementation_scope: "Existing Hatchet adapter, CLI readiness, live-test contract seams, and Plan K hosted evidence"
production_tests_workflows_dds_plans_edited_by_this_report: false
confidence: HIGH
```

The bounded package is the final F-1–F-7 pattern set in the completed
adversarial artifact: first attempt the typed Pydantic input boundary; if the
pinned SDK's strict-mypy overloads reject it, mechanically use the direct-dict
fallback. In either case, use `client.durable_task` with no fallback to
`client.task`, surface registration failures, remove fabricated readiness, and
prove the scheduler-eligible tenant and actual assignment/callback execution
in the hosted gate. Keep the optional engine declaration check additive and
explicitly non-authoritative.

The primary evidence is not a readiness line, local `Standalone` object, task
submission, or `is_durable=true` alone. Release proof requires assigned/running
tasks, an observed real callback, callback-owned durable UMD rows, tenant
identity/partition agreement, and the existing hosted evidence set.

## Evidence and current failure boundary

Run `33229130339` / job `99038602321` reached the full split topology, API
readiness, genuine `umd-worker` registration, external HTTP, and 46 live
submissions. The dump showed 46 queued `v1_task`/`v1_run` rows, but zero
assignments, runtimes, worker-assign events, `stage_run`, `StageCompleted`, or
job-audit rows. This is recorded in the adversarial artifact at
`artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-plan-k-live-hatchet-blocker.md:41-52`
and independently in `artifacts/logs/support-debugger.log.jsonl:L8-L12`.

The diagnosed source defect is concrete:

* `src/umd/jobs/hatchet.py:209-230` returns a one-argument handler reading the
  v0 path `payload["input"]["manifest"]`.
* SDK `hatchet-sdk==1.38.1` invokes callbacks as `fn(workflow_input, ctx)` and
  passes the submitted input directly. The submission shape is visible at
  `src/umd/jobs/runner.py:232-245`.
* The hermetic wrapper at `tests/test_hatchet_live.py:459-464` repeats the v0
  wrapper, so local tests mask the live defect.
* `src/umd/jobs/hatchet.py:417-431` currently permits the non-durable
  registration path and suppresses decorator exceptions.
* `src/umd/deploy/cli.py:122-132` can count `work_registry` when no workflows
  were registered, then print the candidate readiness line.
* `tests/test_hatchet_live.py:1035-1080` calls the factory but does not start a
  worker or query the engine; its current “engine-visible” claim is therefore
  too broad.

Support research confirms the pinned SDK source behavior, durable facade,
worker registration path, and caller map in
`artifacts/logs/support-researcher.log.jsonl:L10`. The tenant falsifier is
`artifacts/logs/support-debugger.log.jsonl:L10-L11`: the selected `internal`
tenant had null scheduler/worker partitions, while the runnable tenant had both.
DB, token, endpoint, and `run_workflow` semantics were ruled out by
`artifacts/logs/support-debugger.log.jsonl:L12`; they are not reopened here.

Technology validation is inherited from the completed adversarial artifact
(`artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-plan-k-live-hatchet-blocker.md:88-100,312-321,586-598`), checked
2026-08-29 against the `py/1.38.1` SDK source, official Hatchet documentation,
PyPI, and the v0.105.2 release. The SDK/server pair remains a candidate until
the hosted pull/connect/register/execute proof passes.

## Options

### Option A — A2′ typed v1 input boundary (selected bounded implementation)

**Architecture:**

* **Adapter layer:** `src/umd/jobs/hatchet.py:_make_handler` accepts
  `(input: UmdStageInput, ctx)` and reads `input.manifest`.
* **Boundary model:** add `UmdStageInput(BaseModel)` for the direct submission
  fields `job_id`, `source_id`, `dag_universe`, `stage`, `manifest`, and optional
  `causation_id`; register it with
  `client.durable_task(name=wf_name, input_validator=UmdStageInput,
  eviction_policy=None)`.
* **Execution layer:** convert the manifest, preserve cancellation and
  committed-evidence resolution, then call the existing
  `DurableStageExecutor.run`; return only a JSON-safe acknowledgement while
  the authoritative `StageRunRecord`, completion event, and audit remain in
  Postgres.
* **Registration/error layer:** remove `contextlib.suppress(Exception)`, hard
  fail if `durable_task` is absent, require all canonical `umd-<stage>` bindings,
  and make readiness depend on actual registered objects as well as bound work.
* **Test/evidence layer:** use real-SDK-shaped `Standalone.mock_run` with a
  Pydantic input model; keep hosted callback/row/assignment evidence as the
  authority.

**Data flow:** Hatchet direct input → SDK validator → `UmdStageInput` →
`StageManifest` → persisted cancellation/evidence lookup → real stage work →
`DurableStageExecutor` → callback-owned Postgres/OCFL/evidence/audit → JSON-safe
acknowledgement.

**Pros:** strongest input contract; catches malformed shape at the SDK boundary;
attribute access is explicit; matches AT-16 and AT-18; avoids returning a
potentially non-serializable `StageRunRecord`; keeps the change within existing
adapter/executor ownership.

**Cons:** the SDK 1.38.1 overload acceptance under strict mypy is a real
implementation-time uncertainty; model fields must remain exactly aligned with
the runner submission shape; sync durable handlers carry a forward-compatible
deprecation warning on this pin.

**Choose when:** strict mypy accepts the pinned SDK overloads and the model's
return/input boundaries are verified before broad fixture changes.

### Option B — A1′ direct-dict v1 boundary (mechanical fallback)

**Architecture:** retain Option A's hard-fail registration, exact-count
readiness, JSON-safe return, durable registration, tenant evidence, and hosted
gate, but use `input_validator=dict` and
`handler(input: dict[str, Any], ctx)` reading `input["manifest"]`.

Real-SDK-shaped tests still pass a Pydantic/dataclass wrapper to `mock_run`,
because SDK 1.38.1's mock-context serializer drops raw dictionaries. Direct
dict means the engine-facing contract remains v1 direct input; it does not mean
tests may reintroduce the v0 wrapper.

**Pros:** smallest verified production change; accepted by the SDK's dictionary
workflow-input bound; mechanical fallback if strict mypy rejects Option A.

**Cons:** no typed field validation or attribute access at the boundary; more
ad-hoc shape discipline; `mock_run` serialization is easy to misuse; malformed
input can reach handler code before failing.

**Choose when:** the first typed-registration spike fails strict mypy or the
installed pinned wheel exposes an incompatible typed overload. Do not choose it
silently: record the fallback and run the same hosted AT-16–19 evidence.

### Option C — A3′ additive engine-visible declaration assertion

This is an evidence enhancement layered on Option A or B, not a standalone
repair or release authority.

The hosted test polls `client.workflows.list()` without a prefix filter and
matches the exact `umd-<stage>` set client-side. The existing compose worker is
the only worker started. A local registration test is renamed and scoped to
local binding shape. The declaration assertion proves only that workflow
declarations are visible to the engine; it does not prove callback execution,
durability, assignment, or persisted UMD completion.

**Pros:** supplies an honest in-suite engine-side declaration observation;
guards against local-only registration claims; no new scheduler or service.

**Cons:** REST response shape, pagination, and filter behavior add test coupling;
it is weaker than the DB/callback evidence for release; a failure must not be
allowed to mask or replace AT-16–19. The adversarial critique specifically
rejects `workflow_name="umd-"` prefix assumptions
(`artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-plan-k-live-hatchet-blocker.md:213-218,486-490`).

**Choose when:** retaining a diagnostic engine-visible surface is valuable and
the test is structurally marked additive/non-authoritative under AT-19.

### Option D — A4 async durable handler (deferred alternative)

Convert the typed handler to `async`, use the durable context, and execute the
existing synchronous executor through a thread boundary. Expand hermetic tests
to `aio_mock_run` and return a JSON-safe result.

**Pros:** removes the sync-durable deprecation debt and aligns with the SDK's
future async-only direction.

**Cons:** largest blast radius; introduces event-loop/thread and output
serialization behavior into a repair whose functional durability remains
executor/Postgres-owned; the v0.105.2 durable path is active and changing; it
does not address the tenant assignment proof by itself. The adversarial record
therefore defers it as a separate coordinated SDK/server/DAG-universe change
(`artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-plan-k-live-hatchet-blocker.md:300-303,593-598`).

**Choose when:** a separately approved forward-compatibility migration is being
run, not for this blocker repair.

## Tradeoff matrix

| Criterion | A: typed boundary | B: direct dict | C: engine declaration check | D: async durable |
|---|---:|---:|---:|---:|
| Primary role | implementation | fallback implementation | additive evidence | deferred migration |
| Files touched (estimate) | 3–4 | 3–4 | 1 test file plus hosted evidence | 3–5 |
| New production abstraction | one input model | none | none | async execution boundary |
| SDK input validation | high | medium/handler-level | inherited | high |
| Strict-mypy risk | medium, must spike | low | low | medium |
| Test plumbing | medium | low/medium | medium hosted | high |
| Hosted coupling | existing gate | existing gate | additional REST shape | existing gate plus async runtime |
| Durable registration | explicit, hard-fail | explicit, hard-fail | inherited | explicit, async |
| Assignment proof | hosted only | hosted only | does not prove it | hosted only |
| Regression risk | low after spike | low | medium diagnostic-only | medium/high |
| Future flexibility | high | medium | medium | high |
| This repair | **selected** | **fallback** | **selected additive** | **rejected/deferred** |

## Selected bounded approach and implementation boundaries

### Selected package

1. Attempt **A2′** in a minimal typed-registration/mypy spike.
2. If that spike fails, switch mechanically to **A1′**; do not weaken the live
   gate to preserve the typed model.
3. Apply the common registration and readiness corrections to either path:
   `durable_task` only, no fallback chain, no exception suppression, exact
   registered-workflow count, and no ready line after a local registration
   mismatch.
4. Apply **A3′** only as an additive, declaration-only hosted diagnostic. The
   DB/engine dump plus callback-owned rows remains the release proof.
5. Preserve the existing sync executor and defer A4.

### Allowed implementation surface

| Path | Allowed responsibility | Required boundary |
|---|---|---|
| `src/umd/jobs/hatchet.py` | v1 handler input, durable registration, registration errors, readiness object, JSON-safe callback result | no scheduler replacement, no executor rewrite, no DB/token/endpoint changes |
| `src/umd/deploy/cli.py` | count actual registered workflows and fail before candidate readiness on mismatch | candidate readiness is not engine proof |
| `tests/test_hatchet_live.py` | v1 hermetic/SKD-shaped contract fixtures, negative shape tests, honest local registration naming, additive engine declaration test if retained | recording client is hermetic only; no fake release evidence |
| Plan K hosted evidence | tenant eligibility, identity, assignment/runtime, latest-version durability, callback rows, artifact capture | reference AT-16–19; do not duplicate their authority |

### Explicitly out of bounds

* No netns retry, Compose topology, seccomp, image, API, DB, token, endpoint, or
  `run_workflow` redesign; those belong to the separate netns/CI work and the
  ruled-out hypotheses remain closed.
* No v0/v1 compatibility adapter. There is one producer shape in
  `runner.py:232-245`; accepting both shapes would hide contract drift.
* No `task`/`durable_task` environment switch, capability fallback, or
  registration retry loop.
* No new readiness subsystem and no second worker/scheduler.
* No direct completion in the callback, serializer authority, or changes to
  `DurableStageExecutor`, OCFL, semantic ledger, provenance, invalidation, or
  projection ownership.
* No async conversion in this repair.

## AT-16/17/18/19 reconciliation

The netns DD remains binding. This report describes implementation choices that
fulfil its contracts; it does not create parallel acceptance criteria.

| Binding contract | Reconciliation in this report | Authority and exact proof |
|---|---|---|
| **AT-16** v1 `(input, ctx)`, direct manifest, real executor and callback-owned rows | A2′ or A1′ handler; real-SDK-shaped `mock_run`; v0/one-arg negatives; JSON-safe ack; hosted observed callback and persisted rows | Netns DD `artifacts/designs/pending/DD-universal-media-decomposer-plan-k-netns-workflow-amendment.md:49-67,174-178`; adversarial F-2/F-6 at `artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-plan-k-live-hatchet-blocker.md:536-542,558-584` |
| **AT-17** deterministic runnable tenant and identity/assignment | Preserve workflow-side discovery; require exactly one tenant with non-null scheduler and worker partitions; record IDs; assert JWT = worker = workflow = submitted task tenant and assigned/running state | Netns DD `artifacts/designs/pending/DD-universal-media-decomposer-plan-k-netns-workflow-amendment.md:69-78,180-183`; falsifier `artifacts/logs/support-debugger.log.jsonl:L10-L11`; adversarial F-5 `artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-plan-k-live-hatchet-blocker.md:553-556` |
| **AT-18** durable registration | Every release action uses `client.durable_task`; missing facade is a configuration failure; hosted latest-version task rows assert `is_durable=true`; durable rows do not substitute for callback rows | Netns DD `artifacts/designs/pending/DD-universal-media-decomposer-plan-k-netns-workflow-amendment.md:80-88,185-188`; current mismatch `src/umd/jobs/hatchet.py:417-428`; adversarial F-1 `artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-plan-k-live-hatchet-blocker.md:530-535` |
| **AT-19** composition and release blocking | Join AT-16/17/18 with AT-1–15; any failure, skip, readiness-only result, configured-unavailable outcome, stale-version assertion, or missing evidence blocks Phase 6 | Netns DD `artifacts/designs/pending/DD-universal-media-decomposer-plan-k-netns-workflow-amendment.md:109-122,190-193`; adversarial final authority statement `artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-plan-k-live-hatchet-blocker.md:637-655` |

Terminology is mandatory: **candidate readiness** is the CLI line;
**engine-visible declaration** is the optional A3′ diagnostic;
**release proof** is the hosted AT-16/17/18 evidence composed under AT-19.
They must not be conflated.

## Exact acceptance evidence

The implementation is not accepted on local green tests. Exec-Manager must
produce and retrieve evidence from a successor hosted run on the pushed repair
SHA, including the exact run URL, job ID, attempt, logs, JUnit, diagnostics,
database dump, and release summary.

### Pre-hosted contract evidence

1. Strict-mypy spike against the installed pinned `hatchet-sdk==1.38.1` either
   passes A2′ or records the mechanical A1′ fallback.
2. Contract tests invoke the handler with exactly two arguments and direct
   top-level input containing `manifest`.
3. Real-SDK-shaped tests prove a one-argument callback and a v0-wrapped payload
   fail; no hermetic callback fixture contains the old `{"input": ...}` shape.
4. `Standalone.mock_run(input=UmdStageInput(...))` (or the documented A1′
   model-wrapper equivalent) reaches the handler and executor; the callback
   does not directly write completion.
5. A forced decorator failure raises visibly; no `contextlib.suppress(Exception)`
   remains around registration.
6. A client without `durable_task` fails closed; no `client.task` fallback is
   accepted for `umd-<stage>`.
7. A zero/partial registration cannot make `WorkerHandle.is_ready()` true or
   print a fabricated exact-count readiness line.
8. The local registration test name/docstring says local binding shape, not
   engine visibility.

### Hosted release evidence

1. The pinned split stack pulls, boots, and records image digests; the worker
   uses the real JWT and engine gRPC route.
2. Tenant discovery produces exactly one scheduler-eligible tenant with
   non-null scheduler and worker partition IDs. The selected tenant and both
   IDs are in `umd-evidence/`; zero, multiple, or null matches fail closed.
3. JWT tenant, worker tenant, workflow tenant, and submitted-task tenant are
   identical.
4. Every latest `umd-<stage>` workflow version has `v1_task.is_durable=true`;
   the query is latest-version scoped and does not pass on a stale historical
   row.
5. Submitted tasks transition from queued to **ASSIGNED/RUNNING**, with
   worker/assignment/runtime evidence. `QUEUED` with no assignment after the
   bounded polling window is a hard failure.
6. At least one real callback is observed on the compose worker and callback-
   owned `stage_run`, `StageCompleted`, and operational job-audit rows appear.
   The gate polls for rows and never accepts a callback acknowledgement alone.
7. The optional A3′ check, if retained, polls `workflows.list()` without a
   prefix assumption and records the exact declaration set. Its result is
   marked diagnostic-only and cannot replace items 4–6.
8. The full AT-1–15 evidence remains present; AT-16–19 are joined, mandatory,
   non-skippable, and release-blocking. JUnit has zero mandatory skips.
9. Existing public HTTP heterogeneous ingestion, restart, retry, cancellation,
   duplicate, selective invalidation, OCFL/provenance, semantic, and audit
   evidence remains present; no in-process app or recording transport is used
   as release evidence.
10. Diagnostics and the machine-readable release summary are uploaded before
    teardown. Missing evidence, absent verdict, skip, readiness-only result,
    or any mandatory failure is a release failure.

The decisive falsifier is the prior run's exact state: all tasks queued, no
assignment/runtime rows, and no callback-owned UMD rows. A green worker log,
non-empty local registration list, successful submission, or durable flag alone
does not satisfy this report.

## Rejected alternatives

| Alternative | Rejection reason |
|---|---|
| Accept both v0 and v1 payloads through a compatibility adapter | No v0 producer exists; it would preserve the original mask and hide future contract drift. |
| Fall back from `durable_task` to `task`/`workflow` | Violates AT-18 and turns SDK drift into a late, opaque hosted failure. |
| Treat the candidate readiness line as engine proof | SDK worker start can fail after the line; the line is explicitly candidate-only. |
| Keep the local test named engine-visible | It never starts the worker or queries the engine; rename honestly or add the scoped A3′ diagnostic. |
| Use `workflows.list(workflow_name="umd-")` as a prefix query | Prefix semantics are unverified and likely exact-match; it risks a healthy-stack false negative. |
| Make A3′ the release proof | Declaration rows do not prove assignment, callback execution, durability, or Postgres completion. |
| Convert to async durable handlers now | Unnecessary for the sync executor-owned durability contract; increases repair blast radius and durable-path churn. |
| Change DB/token/endpoint/submission semantics | Support evidence rules these out; reopening them would be scope churn without causal evidence. |
| Add another scheduler, worker, or topology | Contradicts Hatchet-as-sole-v1-scheduler and the approved full split topology. |

These rejections are consistent with the complexity review's required
simplifications S1–S6 and rejected abstractions R1–R6 in
`artifacts/designs/process/universal-media-decomposer-plan-k-hatchet-live-blocker-complexity-review.md:57-108`.

## Handoff

* This report is the architecture/options input for the existing Plan K
  amendment; it is not the implementation plan.
* Exec-Planner must map the selected package into the existing P2-S4/P2-S5/P3-S3
  work and Phase 6 gate without duplicating AT-16–19.
* Exec-Manager must resolve the typed spike before expanding fixtures, run the
  hosted successor to `33229130339`/`99038602321`, retrieve evidence, and stop
  on any assignment, callback-row, tenant, durable, skip, or evidence failure.
* Documentation/DoD closure remains forbidden until the hosted evidence is
  retrieved and the complete mandatory matrix has no unresolved FAIL.

**Exact report path:** `artifacts/designs/process/universal-media-decomposer-plan-k-hatchet-live-blocker-architecture-options.md`  
**Final verdict:** `DONE — SELECTED_BOUNDED_PACKAGE; hosted release remains BLOCKED until the exact acceptance evidence above passes.`
