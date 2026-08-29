# Universal Media Decomposer — Plan K Live Hatchet Blocker Amendment

**Status:** Proposed  
**Author:** rnd-dd-author  
**Date:** 2026-08-29  
**Route:** `DD_REQUIRED`  

> This is a blocker-specific amendment DD. It reconciles, and does not
> duplicate, the binding netns DD contracts AT-16/17/18/19 or Plan K authority.
> It is design-only and does **not authorize implementation**, documentation
> closure, DoD closure, or release approval. No source, test, workflow,
> configuration, or plan file is edited by this DD.

## Original request and authority

The verbatim authoritative request is the user-supplied request preserved in
the adversarial artifact §1; the quoted text below is its blocker-specific
opening and constraints. The complete unchanged request must remain the source
of truth.

The authoritative request is preserved verbatim in
`artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-plan-k-live-hatchet-blocker.md` §1. It is:

> Continue formal Plan K R&D workflow for the newly diagnosed live Hatchet blocker. Support evidence is decisive: run 33229130339 Docker job 99038602321 reached full split topology, API readiness, genuine worker registration, external HTTP, and live submissions. Every live task then failed before UMD execution because Hatchet SDK 1.38.1 invokes task callbacks as fn(workflow_input, ctx), while src/umd/jobs/hatchet.py:_make_handler returns handler(payload) and expects payload['input']['manifest'] (v0 shape). Hermetic tests/test_hatchet_live.py:_invoke_callback at ~459 encode the same wrong wrapper, masking defect. Correct v1 input is direct dict with manifest. DB/token/endpoint/run_workflow semantics are ruled out. Separate defects: HatchetWorkerFactory.start suppresses real decorator exceptions; cli.py readiness falls back to len(work_registry) and can fabricate readiness; the “engine-visible registration” test only checks local Standalone objects. Preserve deterministic selection of a runnable tenant with non-null scheduler/worker partitions and assignment/runtime assertions. Immutable constraints: fully realize Task.md DoD; Hatchet is sole v1 scheduler; use real callbacks and DurableStageExecutor; durable async restart/retry/cancel/selective invalidation; no skips/stubs/fake readiness/recording doubles as release evidence; no weakened gates; hosted native Docker/Compose, public heterogeneous HTTP E2E, zero mandatory skips, retrieved evidence before docs/DoD closure; preserve OCFL/evidence/semantic/provenance invariants. Required formal process and validated Plan K amendment remain mandatory; DDAuthor must not implement.

The unchanged immutable L1–L21 ledger is authoritative at the exact reference
above, §2, lines 17–39. For auditability it is reproduced here unchanged:

- **L1** “Continue formal Plan K R&D workflow for the newly diagnosed live Hatchet blocker.”
- **L2** “Support evidence is decisive: run 33229130339 Docker job 99038602321 reached full split topology, API readiness, genuine worker registration, external HTTP, and live submissions.”
- **L3** “Every live task then failed before UMD execution because Hatchet SDK 1.38.1 invokes task callbacks as fn(workflow_input, ctx), while src/umd/jobs/hatchet.py:_make_handler returns handler(payload) and expects payload['input']['manifest'] (v0 shape).”
- **L4** “Hermetic tests/test_hatchet_live.py:_invoke_callback at ~459 encode the same wrong wrapper, masking defect.”
- **L5** “Correct v1 input is direct dict with manifest.”
- **L6** “DB/token/endpoint/run_workflow semantics are ruled out.”
- **L7** “Separate defects: HatchetWorkerFactory.start swallows real decorator exceptions and cli.py readiness count falls back to len(work_registry), allowing fabricated readiness; engine-visible registration test only inspects local Standalone objects.”
- **L8** “Also prior tenant-selection bug was fixed/diagnosed, but preserve requirement to select runnable tenant with non-null partitions and assert assignment/runtime state.”
- **L9** “Task.md Universal Media Decomposer DoD fully realized.”
- **L10** “Hatchet sole v1 scheduler.”
- **L11** “real callbacks/DurableStageExecutor.”
- **L12** “durable async restart/retry/cancel/selective invalidation.”
- **L13** “no skips/stubs/fake readiness/recording doubles as release evidence.”
- **L14** “no weakening gates.”
- **L15** “hosted native Docker/Compose, public HTTP heterogeneous E2E, zero mandatory skips, retrieved evidence before docs/DoD closure.”
- **L16** “preserve OCFL/evidence/semantic/provenance invariants.”
- **L17** “Run required R&D formal process (librarian/researcher, adversarial refinement, architect, complexity, estimator, DDAuthor, PatternEnforcer; no skipped stages).”
- **L18** “create/amend validated implementation plan under artifacts/plans/pending.”
- **L19** “Explicitly plan spec-first handler contract tests, real callback fix, hermetic test alignment without lowering live gate, surfaced registration failures/readiness truthfulness, engine-visible proof or honest test scope, assignment/runtime diagnostics, and rerun hosted CI.”
- **L20** “Do not edit production/workflow/tests yourself.”
- **L21** “Return plan paths, requirement ledger, risks, exact acceptance evidence for Exec-Manager.”

## Context and evidence

Run `33229130339`, Docker job `99038602321`, SHA `6614b32` is decisive hosted
evidence, not a success claim. It reached the full split topology, API
readiness, genuine `umd-worker` registration (SDK 1.38.1, heartbeat, nine
`_ActionToWorker` links and exact `umd-*` action IDs), external HTTP, and 46
submissions. It produced 46 `v1_task` and 46 `v1_run` rows, all readable as
`QUEUED`, but zero assignments, `v1_task_runtime`/`StepRun`/
`WorkerAssignEvent` rows, or callback-owned `stage_run`, `StageCompleted`, and
job-audit rows.

The primary failure is `TypeError: handler() takes 1 positional argument but 2
were given`. Even after arity repair, the v0 `payload["input"]` access would
fail because SDK input is direct. Submission shape is
`src/umd/jobs/runner.py:232–245`. The pinned SDK source at tag `py/1.38.1`
confirms `Task.call`/`aio_call` invokes `_fn(workflow_input, ctx)`. Its default
`EmptyModel` is not subscriptable, so a typed model or `input_validator=dict` is
required. `Standalone.mock_run` serializes Pydantic/dataclass input but drops a
raw dict to `{}`.

Independent defects are `src/umd/jobs/hatchet.py:426` (suppressed decorator
exceptions), `src/umd/deploy/cli.py:123` (readiness count fallback), and
`tests/test_hatchet_live.py:1035–1080` (local objects mislabeled engine
visibility). Tenant evidence shows internal tenant
`8d420720-ef03-41dc-9c73-1c93f276db97` with null scheduler/worker partitions,
while Default tenant `707d0855-80ab-4e1f-a156-f1c4546cbf52` has both. AT-17
therefore remains mandatory: exactly one scheduler-eligible tenant, recorded
IDs, fail-closed ambiguity/null handling, identity agreement, and assignment /
runtime evidence. DB, token, endpoint, and `run_workflow` semantics are ruled
out and are not reopened.

Support-Librarian evidence is `artifacts/logs/support-librarian.log.jsonl` L21
and L22; Support-Researcher evidence is
`artifacts/logs/support-researcher.log.jsonl` L9 and L10; debugger evidence is
`artifacts/logs/support-debugger.log.jsonl` L8–L12. Technology validation was
checked 2026-08-29 against the official SDK tag `py/1.38.1`, Hatchet docs,
PyPI, and server release `v0.105.2`. Reference evidence is not hosted
execution evidence.

## Selected architecture

Adopt the bounded package **A2′ typed v1 input boundary + A1′ mechanical
fallback + A3′ additive declaration check**, selected by the architecture
report and complete T1–T8 adversarial log.

1. First run a minimal strict-mypy spike against installed
   `hatchet-sdk==1.38.1`. If it passes, ship exactly A2′. Add
   `UmdStageInput(BaseModel)` with direct fields `job_id`, `source_id`,
   `dag_universe`, `stage`, `manifest`, and optional `causation_id`; register
   it as the input validator; use sync `handler(input, ctx)` and
   `input.manifest`.
2. If the spike fails, ship exactly A1′: `input_validator=dict` and
   `handler(input, ctx)` reading `input["manifest"]`. Record the fallback.
   A2′ and A1′ are mutually exclusive decisions, never a runtime-selectable
   dual path, and never a v0/v1 compatibility adapter.
3. Register every canonical `umd-<stage>` with
   `client.durable_task(name=wf_name, input_validator=<chosen validator>,
   eviction_policy=None)`. Missing `durable_task` is `ConfigurationError`;
   there is no `task`/`workflow` fallback, retry loop, or exception suppression.
4. The callback invokes existing `DurableStageExecutor`, preserves cancellation,
   committed-evidence resolution, claim-before-side-effect, Postgres/OCFL/
   semantic/audit ownership, idempotency, executor retry/quarantine, restart /
   reclaim, and descendant-only invalidation. It returns only a flat JSON-safe
   acknowledgement; `StageRunRecord` and authoritative rows remain in the
   durable store.
5. `_ready` requires callbacks and non-empty actual registration. CLI counts
   only `registered_workflows` and fails before the C6 line on an exact-count
   mismatch. The C6 line is **candidate readiness**, not proof.
6. A3′ may perform one hosted `client.workflows.list()` probe without a prefix
   assumption and exact-match `umd-<stage>` names client-side. It proves only
   **engine-visible declaration** and is diagnostic/non-authoritative.

Hatchet remains the sole v1 scheduler. All-durable registration is the default
required by AT-18. If durable slots do not assign, investigate engine slot
configuration first; a mixed-registration pivot requires a new DD. Sync-durable
deprecation on this pin is tracked forward-compatibility debt; async conversion
is deferred.

The tenant rule is intentionally stricter than merely selecting the tenant
created by setup: the hosted gate must discover exactly one
scheduler-eligible tenant, and that tenant must have non-null
`schedulerPartitionId` and `workerPartitionId`. A setup-created tenant counts
only when it satisfies both partition checks. Zero, multiple, or
null-partition candidates fail closed before JWT minting or live submission.

## AT-16/17/18/19 reconciliation

The netns DD at
`artifacts/designs/pending/DD-universal-media-decomposer-plan-k-netns-workflow-amendment.md`
is binding authority. This DD implements and clarifies its contracts without
creating parallel acceptance criteria:

| Authority | This amendment | Proof authority |
|---|---|---|
| AT-16 | One chosen A2′/A1′ direct-input `(input, ctx)` boundary; real executor; JSON-safe ack; v0/one-arg negatives; callback-owned rows. | Netns DD AT-16; hosted observed callback plus `stage_run`, `StageCompleted`, and job-audit rows. |
| AT-17 | Exactly one eligible tenant with non-null scheduler and worker partitions; recorded IDs; JWT/worker/workflow/submitted-task agreement; assigned/running state. | Netns DD AT-17; hosted tenant, partition, assignment, and runtime evidence. |
| AT-18 | `durable_task` for every `umd-<stage>`, hard failure if absent, explicit `eviction_policy=None`, latest-version `is_durable=true`. | Netns DD AT-18; hosted task rows, with assignment and callback proof separately required. |
| AT-19 | Join AT-16/17/18 with AT-1–15 before Phase 6; any failure, skip, missing evidence, readiness-only result, or configured-unavailable mandatory outcome blocks release. | Netns DD AT-19 and Plan K Phase 6. |

The three terms are not interchangeable: **candidate readiness** is the C6
line; **engine-visible declaration** is A3′; **release proof** is hosted
AT-16/17/18 composed under AT-19.

## Implementation obligations and affected surfaces

The downstream validated Plan K amendment must map these obligations into
existing P2-S4/P2-S5/P3-S3 and Phase 6, without new authority:

- `src/umd/jobs/hatchet.py`: selected direct-input boundary, two-argument
  callback, real executor, JSON-safe acknowledgement, durable-only registration,
  surfaced failures, exact stage registration, and truthful `_ready`.
- `src/umd/deploy/cli.py`: actual-registration count only; fail closed before
  candidate readiness; one blocking worker start with canonical C6 wording.
- `tests/test_hatchet_live.py`: direct v1 two-argument fixtures; model/dataclass
  input for `mock_run`; one-arg and v0 negatives; missing-durable-task and
  decorator-failure tests; honest local-registration naming. Recording clients
  remain hermetic only.
- Hosted validation/evidence: eligible tenant and partition proof; identity
  agreement; latest-version durability; QUEUED→ASSIGNED/RUNNING polling;
  callback-owned rows; worker/assignment/runtime diagnostics; optional A3′ probe;
  artifact capture before teardown. The rerun must invoke the real `(input, ctx)`
  callback through the real worker and prove `DurableStageExecutor` ownership;
  a direct test invocation is necessary contract coverage but cannot satisfy
  hosted callback proof.

No executor, scheduler, topology, DB, token, endpoint, `run_workflow`, OCFL,
semantic, provenance, or invalidation ownership changes are authorized here.

## Exact acceptance evidence

Local green tests, readiness text, local `Standalone` objects, successful
submission, or `is_durable=true` alone do not accept this repair.

**Before hosted rerun:**

1. Strict-mypy spike selects A2′ or records A1′ fallback.
2. Contract tests use exactly `(input, ctx)` and direct top-level `manifest`;
   one-arg and v0-wrapped shapes fail; no test fixture retains `{"input": ...}`.
3. Real-SDK-shaped `Standalone.mock_run(input=UmdStageInput(...))` (or the
   model-wrapper equivalent for A1′) reaches the existing executor; callback
   does not directly complete.
4. Forced decorator failure is visible and no registration suppress remains.
5. A client without `durable_task` fails closed; no `task` fallback.
6. Zero/partial registration cannot make `is_ready()` true or print a
   fabricated exact-count line.
7. Local registration test says local binding shape, not engine visibility.

### Full AT-1–AT-19 hosted rerun (mandatory, no-skip)

The successor validation is one native hosted Docker/Compose release rerun,
not a collection of locally substituted checks. It must execute the complete
AT-1 through AT-19 set on the pinned split topology, including AT-11's
per-step Bash/pipefail audit (AT-11 is not conditional for this rerun). The
public heterogeneous scenario must use external versioned HTTP against the
running Compose API; no in-process app, recording transport, local scheduler,
or hermetic-only result can satisfy a hosted AT item. Every mandatory test
must execute with `skipped=0`; workflow omission, conditional skip,
configured-unavailable mandatory surface, missing JUnit row, or missing
machine-readable verdict is a hard failure. Retrieved artifacts must show the
full AT-1–AT-19 verdicts, native Compose/service evidence, public HTTP
heterogeneous/restart/retry/cancel/selective-invalidation evidence, and the
AT-16/17/18 proof composed under AT-19. This complete rerun must pass before
Phase 5 documentation, the §40 matrix is closed, or any DoD/release claim is
published.

**Hosted successor to run 33229130339:**

8. Native pinned split Docker/Compose stack pulls and boots; exact image
   digests, SHA, run URL, job/attempt, logs, JUnit, diagnostics, DB dump,
   OCFL/fixity, and machine-readable summary are uploaded before teardown.
9. Exactly one scheduler-eligible tenant with non-null scheduler and worker
   partitions is discovered and recorded; a setup-created tenant counts only
   when it satisfies both non-null partition checks; zero/multiple/null fails
   closed; JWT, worker, workflow, and submitted-task tenants match; real JWT
   and engine gRPC route are used.
10. Every latest `umd-<stage>` workflow version has `v1_task.is_durable=true`;
    stale historical versions cannot satisfy it.
11. Tasks transition from QUEUED to **ASSIGNED/RUNNING** with worker,
    assignment, runtime evidence. Queued without assignment after bounded
    polling is a hard failure.
12. A real worker observes a real callback producing callback-owned `stage_run`,
    `StageCompleted`, and operational job-audit rows. SDK acknowledgement is
    insufficient.
13. If retained, A3′ uses one no-filter `workflows.list()` probe, exact client
    matching, and diagnostic-only recording.
14. AT-1–15 remain present; AT-16–19 are joined, mandatory, non-skippable, and
    release-blocking. The native hosted rerun executes every AT-1–AT-19 item,
    including the AT-11 Bash/pipefail audit, with no mandatory skips or
    configured-unavailable substitution. Public HTTP heterogeneous ingestion,
    restart, retry, cancellation, duplicate, selective invalidation,
    OCFL/provenance/semantic/audit evidence remains present. JUnit has
    `skipped=0` for the mandatory suite.
15. Documentation and DoD closure occur only after retrieved hosted evidence
    passes. Missing evidence, readiness-only/configured-unavailable outcome,
    skip, or mandatory failure fails release.

## Task.md §40 conformance matrix

This DD does not close or weaken any DoD item. Statuses are the current honest
Plan K snapshot; `FAIL` and unresolved mandatory `GATED` evidence remain release
blocking. Evidence owners must revalidate them after implementation.

| # | §40 implication | Status | Evidence owner / required proof |
|---:|---|---|---|
| 1 | Adversarial technology/design process | PASS | R&D Manager; complete T1–T8 log and manifest |
| 2 | Implementation-ready DD/plan | GATED | DDAuthor + Exec-Planner; this DD and validated Plan K amendment |
| 3 | Implemented service | GATED | Exec-Manager; pushed SHA and hosted identity |
| 4 | Persistent OCFL source storage | GATED | Exec/QA; fixity and volume persistence across restart |
| 5 | Text/book ingestion | FAIL | Hosted public HTTP TXT/Markdown/EPUB/PDF evidence |
| 6 | Image ingestion | FAIL | Hosted public HTTP raster/OCR/locator evidence |
| 7 | Audio ingestion | FAIL | Hosted public HTTP timing/ASR/provider evidence |
| 8 | Video ingestion | FAIL | Hosted public HTTP container/tracks/scenes evidence |
| 9 | Stable addressable segments | GATED | Public locators, segments, retrieval, restart |
| 10 | Exact provenance | GATED | OCFL/source/evidence refs and generated-by metadata |
| 11 | Evidence/confidence assertions | GATED | Evidence and semantic metadata assertions |
| 12 | Multilingual coexistence | GATED | Independent language realizations in one work/graph |
| 13 | Adaptation/continuity boundaries | GATED | Explicit continuity and difference evidence |
| 14 | Cross-source alignment | GATED | Many-to-many alignment evidence |
| 15 | Reversible entity resolution | GATED | Merge/split/history/reference evidence |
| 16 | User overrides | GATED | Public override/lock/provenance evidence |
| 17 | Segment editing | GATED | Append-only segment edit/split/merge evidence |
| 18 | Semantic editing | GATED | Append-only semantic edit/override/invalidate/lock evidence |
| 19 | Descendant-only invalidation | GATED | InvalidationPlanner/STAGE_DEPENDENTS and unchanged ancestors |
| 20 | Individual stage reruns | GATED | Selective rerun and stage evidence |
| 21 | Durable restartable asynchronous jobs | FAIL | Hosted stop/start/reclaim/replay, assignment, callback rows |
| 22 | Structured locators | GATED | Source-native locator round trips |
| 23 | KG-style questioning | GATED | Typed public semantic answers |
| 24 | Structured graph querying | GATED | Bounded typed graph-query responses |
| 25 | Supporting evidence | GATED | Answer support references and retrieval |
| 26 | Audit/history | GATED | Current/prior/actor/cause explanation |
| 27 | Swappable providers | GATED | Capability/provider matrix and interfaces |
| 28 | Local/self-hostable model path | GATED | Named local/self-hostable capability evidence |
| 29 | Heterogeneous/contradictory tests | FAIL | Hosted HTTP heterogeneous/contradictory suite |
| 30 | Correction→invalidation→selective rerun E2E | GATED | Public HTTP correction and descendant-only rerun |
| 31 | Docker deployment | FAIL | Native hosted Docker/Compose full split stack |
| 32 | Lint/type/static checks | GATED | Pushed-SHA checks, including selected input spike |
| 33 | Automated tests | FAIL | Hosted JUnit with zero mandatory skips |
| 34 | Final adversarial code review | GATED | QA/security/adversarial review of all specified risks |
| 35 | Repair findings and rerun complete validation | GATED | Retrieved complete hosted rerun and final matrix |

Every row preserves immutable OCFL, evidence/semantic separation, append-only
authority, stable locators, multilingual/adaptation individuality,
descendant-only invalidation, honest provider capability, durable
restart/retry/cancel, public HTTP E2E, Docker/Compose validation, and no fake
readiness or hidden skips. This matrix is not a release approval.

The §40 matrix is a coverage/status ledger, not a substitute for the complete
hosted AT-1–AT-19 rerun. Before Phase 5 or DoD closure, the retrieved rerun
must contain a machine-readable result for every AT item (including AT-11's
Bash/pipefail audit), execute the native eight-service Docker/Compose stack and
public heterogeneous HTTP path, and report zero mandatory skips. Any omitted,
skipped, configured-unavailable, or unproven AT item keeps the corresponding
§40 row open and blocks release.

## Risks, open questions, and rejected alternatives

Blocking risks are durable-slot assignment on v0.105.2; strict-mypy overload
acceptance; validator/mock-run divergence; REST declaration shape;
latest-version scoping; acknowledgement-before-row polling; tenant identity or
partition mismatch; and future sync-durable removal. Resolve them with the
spike, one hosted REST probe, bounded row polling, latest-version SQL, and the
hosted AT-19 gate. If durable assignment fails, investigate engine slot
configuration before proposing mixed registration; that proposal requires a
new DD.

Rejected: accepting v0 and v1 through an adapter; falling back to
`task`/`workflow`; treating candidate readiness as engine proof; retaining the
local test's engine-visible name; assuming `workflows.list(workflow_name="umd-")`
is a prefix query; making A3′ release authority; converting to async now; or
changing DB/token/endpoint/`run_workflow` semantics. Also rejected are a second
scheduler/worker/topology, registration retry, a readiness subsystem, a
serializer layer, mixed durable default, and shipping A2′ plus A1′ together.
These dispositions follow the architecture report and complexity review's
S1–S6 and RA1–RA4.

## Dependencies, rollout, and plan handoff

Dependencies are the netns DD AT-16–19, approved CI-repair DD C1–C8, existing
Plan K P2-S4/P2-S5/P3-S3 and Phase 6, `CONTRACTS.md` §§58–63,
`HATCHET_LIVE_VALIDATION_HANDOFF.md`, `handoff-G-to-I-J.md`, the runner
submission shape, `DurableStageExecutor`, pinned SDK/server, real tenant JWT,
native Docker/Compose, retrieved hosted artifacts, PatternEnforcer, and a
validated implementation-plan amendment.

Rollout is: typed spike; select exactly one boundary; bounded adapter/CLI
changes; hermetic and SDK-shaped tests; hosted evidence additions; validated
Plan K amendment; pushed hosted rerun; AT-19; QA/security/test/docs review;
documentation and DoD only after evidence. SDK/server changes require lockstep
pins, a new DAG universe, drain/cancel, and revalidation. Ordinary restart is
Compose stop/start with named volumes; teardown follows evidence upload.

Exec-Planner must amend the existing
`artifacts/plans/pending/TASK-universal-media-decomposer-K-ci-repair-release-gate.md`
only, mapping F-1–F-7 into P2-S4/P2-S5/P3-S3 and Phase 6. Existing “Done” notes
for handler/CLI/live registration are stale against run 33229130339 and must be
revalidated. Do not create a competing plan or duplicate AT-16–19.

Exec-Manager implements only after the validated amendment and PatternEnforcer
gate, then pushes a path-scoped SHA and retrieves exact hosted evidence. Stop on
any one-arg/v0 callback, absent callback rows, queued-without-assignment,
ineligible tenant, identity mismatch, stale durability row, fake readiness,
mandatory skip, missing evidence, or Task.md FAIL.

## Traceability

Required upstream artifacts used unchanged:

- `Task.md` §40 and §§1–41;
- `artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-plan-k-live-hatchet-blocker.md` (complete T1–T8 and Validation Manifest);
- `artifacts/designs/process/universal-media-decomposer-plan-k-hatchet-live-blocker-architecture-options.md`;
- `artifacts/designs/process/universal-media-decomposer-plan-k-hatchet-live-blocker-complexity-review.md`;
- `artifacts/designs/process/universal-media-decomposer-plan-k-hatchet-live-blocker-final-estimate.md`;
- `artifacts/designs/pending/DD-universal-media-decomposer-plan-k-netns-workflow-amendment.md`;
- `artifacts/designs/pending/DD-universal-media-decomposer-ci-repair.md`;
- `artifacts/plans/pending/TASK-universal-media-decomposer-K-ci-repair-release-gate.md`;
- `artifacts/designs/parts/universal-media-decomposer/CONTRACTS.md`;
- `artifacts/designs/parts/universal-media-decomposer/HATCHET_LIVE_VALIDATION_HANDOFF.md`;
- `artifacts/plans/handoff-G-to-I-J.md`;
- `artifacts/logs/support-librarian.log.jsonl` L21/L22;
- `artifacts/logs/support-researcher.log.jsonl` L9/L10;
- `artifacts/logs/support-debugger.log.jsonl` L8–L12;
- `src/umd/jobs/hatchet.py`, `src/umd/jobs/runner.py`, `src/umd/deploy/cli.py`, and `tests/test_hatchet_live.py`.

Official Hatchet SDK tag `py/1.38.1`, docs, PyPI package, and server release
`v0.105.2` were checked 2026-08-29. `workflows.list()` filter semantics remain
partially verified; A3′ is therefore unfiltered, exact-match, and diagnostic.
Hosted execution remains the only proof of assignment, callback execution,
durability, and release readiness.
