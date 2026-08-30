# Universeity — Adversarial Architecture Review

**Status:** COMPLETE — architecture review only; no application implementation changes  
**Date:** 2026-08-31  
**Reviewed ref:** `main` = `124f092b2f36ca8e990c9dd9d8841392eba81d28`  
**Validation control:** GitHub Actions run `33312774348` — fully green  
**Authority:** `Task.md` first, then `artifacts/designs/pending/DD-universal-media-decomposer.md`, then prior design/process artifacts; implementation is evidence, not authority.

---

## 1. Executive conclusion

### Verdict

The **core architecture is sound**, but the production execution boundary is overbuilt and partially duplicated.

Universeity's durable domain model is substantially simpler than its current deployed topology suggests. The parts that carry the hard requirements are already concentrated in four places:

1. **OCFL** owns immutable source/derived bytes and fixity.
2. **PostgreSQL** owns source/segment/evidence metadata, the append-only semantic ledger, Tier-0 current state, job/stage records, quarantine, audit, and projection checkpoints.
3. **The in-repository UMD DAG + `JobService`** own dependency semantics, invalidation, selective rerun, cancellation intent, expected-stage sets, and aggregate lifecycle interpretation.
4. **`DurableStageExecutor` + `StageRunRepository`** own claim-before-side-effect, effective-once completion, idempotency, transient retry policy, deterministic quarantine, and crash/replay behavior.

Hatchet is correctly integrated at the current baseline: the live workflow is registered, submitted, executed by a real worker, and proved by the hosted validation suite. That answers **“is Hatchet correctly implemented?”** with **yes**.

It does **not** answer **“is Hatchet the right architectural choice?”**. The answer to that second question is **no for the current requirements**.

Hatchet currently provides mostly **durable dispatch, worker assignment/wakeup, and multi-worker coordination**, while UMD/PostgreSQL retain nearly every business-relevant execution decision. To fit selective rerun into Hatchet's static nine-task DAG, UMD submits a complete native workflow plus a full manifest set and a selected-stage marker, while its own lineage, idempotency, execution selection, and completion authority remain authoritative. This is adapter complexity created by overlapping orchestration models.

### Top three sources of accidental complexity

1. **Duplicate orchestration models — UMD/PostgreSQL + Hatchet.**  
   UMD owns the canonical stage lineage, rerun closure, durable stage identity, retry/quarantine semantics, completion authority, and job aggregate. Hatchet independently owns a native task graph and scheduler state. The adapter translates one execution model into another rather than delegating a missing business capability.

2. **Duplicate public/application command paths.**  
   `src/umd/application/ingestion.py` defines the application ingestion command, but `src/umd/api/routers/sources.py` reimplements OCFL storage, source/work creation, ledger append, and dispatch. The two paths already differ: the application handler writes explicit `source_membership`; the router path does not. Similar lifecycle knowledge leaks into rerun routers.

3. **Security topology that does not match the runtime boundary.**  
   The DD requires a hardened sandbox for genuinely untrusted parsers. Production runtime assembly wires `SubprocessSandboxRunner`, whose own contract explicitly says it provides bounded-failure containment but **not OS isolation**. `BubblewrapSandboxRunner` implements the required isolation but is not production-wired. Meanwhile the Compose `sandbox-runner` profile starts the generic worker role rather than a clearly isolated parser-execution transport.

### Hatchet disposition

**REPLACE.**

Replace Hatchet with a **small PostgreSQL durable work queue/lease layer** that drives the existing UMD DAG and `DurableStageExecutor`.

This is not a recommendation to replace working durable execution with ad-hoc threads. PostgreSQL must gain the small set of scheduler capabilities Hatchet currently supplies: durable pending work, atomic worker leasing, lease expiry/reclaim, wakeup, durable `available_at` retry timing, concurrency/backpressure controls, worker drain, and queue observability.

Temporal should be **DEFERRED**, not selected. It is a stronger general workflow platform than Universeity currently needs, but adopting it cleanly would require either duplicating UMD's execution state again or moving significant UMD lifecycle authority into Temporal. Both are larger changes than filling the narrow scheduler gap already exposed by the current architecture.

### Smallest recommended target architecture

```text
                           +-------------------+
HTTP /v1 ---------------->| application cmds  |
 routers: auth, schema,    | ingest/correct/job|
 limits, serialization     +---------+---------+
                                     |
                  +------------------+------------------+
                  |                                     |
                  v                                     v
        +--------------------+                +--------------------+
        | OCFL               |                | PostgreSQL         |
        | immutable bytes    |                | sole durable state |
        | + fixity           |                | - source/segment   |
        +--------------------+                | - semantic ledger  |
                                              | - Tier-0 state     |
                                              | - job/stage/gen    |
                                              | - work queue/lease |
                                              | - audit/quarantine |
                                              | - proj checkpoints |
                                              +---------+----------+
                                                        |
                                              lease eligible work
                                                        |
                                                        v
                                              +--------------------+
                                              | UMD worker         |
                                              | canonical DAG      |
                                              | DurableStageExecutor|
                                              | StageWorkRegistry  |
                                              +---------+----------+
                                                        |
                                        untrusted parser/extractor
                                                        |
                                                        v
                                              +--------------------+
                                              | hardened sandbox   |
                                              | bwrap/OS isolation |
                                              +--------------------+

semantic_event -------------------------------------> Tier-1 replay builders
                                                     current/search/vector
```

Steady-state core deployment becomes **PostgreSQL + API + worker**, with a real hardened sandbox execution role/boundary wherever untrusted parser work cannot safely be isolated inside the worker process. Ollama/MinIO remain optional capability profiles. The current Hatchet engine/dashboard/migrate/admin services, Hatchet tenant/token/config machinery, and Hatchet-specific CI proof surface disappear.

---

## 2. Current architecture — code-derived

### Actual authority and data flow

```text
Client
  |
  v
FastAPI routers
  |-- sources.py ----------------------------+
  |     currently performs business ingest  |
  |                                         |
  |-- jobs.py --> JobService ---------------+--------------------+
  |-- correction/rerun routes --> commands / JobService          |
  |                                                              |
  v                                                              v
OCFL SourceStore                                      Postgres authorities
immutable source/derived bytes                        - source/work/segment/evidence
                                                      - semantic_event
                                                      - current_state Tier-0
                                                      - job
                                                      - stage_run
                                                      - job_run_audit
                                                      - quarantine
                                                      - projection_checkpoint
                                                              |
                                                              |
JobService                                                     |
  | owns expected stages, cancel/retry/rerun/invalidation      |
  |                                                            |
  v                                                            |
ProductionDAGRunner                                            |
  |                                                            |
  | full 9-task Hatchet workflow + selected_stages             |
  v                                                            |
Hatchet engine/dashboard <------ scheduler state --------------+
  |
  v
Hatchet worker callback
  |
  +--> selected-stage gate / manifest reconstruction
  |
  v
DurableStageExecutor
  |-- StageRunRepository.claim() --> Postgres UNIQUE idempotency_key
  |-- StageWorkRegistry --> actual stage implementation
  |-- retry/backoff
  |-- quarantine
  `-- SemanticLedger.complete_and_append()
        atomically:
        - StageCompleted semantic event
        - stage_run authoritative completion/artifact refs

semantic_event
  |
  v
ReplayDriver + ProjectionCheckpointStore
  |-- CurrentTierOneBuilder
  |-- SearchProjectionBuilder
  `-- vector/search projection machinery
```

### Execution ownership today

| Responsibility | Current owner(s) | Assessment |
|---|---|---|
| DAG topology | `umd.jobs.dag` **and** Hatchet native task parents | **Duplicated** |
| Dependency eligibility | UMD lineage/invalidation + Hatchet parent graph | **Duplicated** |
| Task scheduling / worker assignment | Hatchet | Unique Hatchet value |
| Durable stage claim | PostgreSQL `stage_run` / `StageRunRepository` | Clear UMD authority |
| Idempotency | `StageManifest` + PostgreSQL UNIQUE key | Clear UMD authority |
| Execution selection | `JobService.expected_stages` / selected stage set | UMD authority |
| Execution generation | Implicit through rerun causation in manifest digest | **Insufficiently first-class** |
| Retry policy | `DurableStageExecutor` | UMD authority; worker sleeps during backoff |
| Completion authority | PostgreSQL `stage_run` + `semantic_event` atomic commit | Clear UMD authority |
| Cancellation intent | PostgreSQL job/cancelled-stage state via `JobService` | UMD authority |
| Quarantine | PostgreSQL quarantine + executor policy | UMD authority |
| Restart/reclaim | Stage-run claim/replay semantics + Hatchet redelivery/worker scheduling | Split responsibility |
| Selective rerun/invalidation | `JobService` + `InvalidationPlanner` + UMD lineage | UMD authority |
| Job aggregate status | `JobService` over PostgreSQL job/stage state | UMD authority |
| Worker wakeup/backpressure | Hatchet | Unique Hatchet value |

### Current deployment topology

`deploy/compose.yaml` declares:

- Core UMD: `db`, `api`, `worker`.
- Hatchet: `hatchet-migrate` and `hatchet-admin` one-shot services; `hatchet-engine` and `hatchet-dashboard` long-lived services.
- Profile-gated: `sandbox-runner`, `ollama`, `minio`.

After one-shot initialization, the ordinary live stack therefore has **five long-lived core/Hatchet services** (`db`, `api`, `worker`, `hatchet-engine`, `hatchet-dashboard`) plus two Hatchet initialization jobs. Hosted validation additionally starts the sandbox profile.

The green validation run proves this topology works. It does not establish that every service is required by the product invariants.

---

## 3. Requirements-to-implementation matrix

| Required capability | Current owner | Current implementation | Duplicate? | Recommendation |
|---|---|---|---|---|
| Immutable source bytes / fixity | OCFL | `storage/ocfl/store.py` content-addressed SHA-512 OCFL | No | **KEEP** |
| Source/work/segment/evidence metadata | PostgreSQL | typed repositories/tables | No | **KEEP** |
| Exact provenance | PostgreSQL + OCFL refs | evidence rows, locators, artifact refs, generated-by metadata | No | **KEEP** |
| Append-only semantic history | PostgreSQL | `SemanticLedger` + immutable event table | No | **KEEP** |
| Tier-0 immediate current state | PostgreSQL | same transaction as accepted semantic event through shared reducer | No | **KEEP** |
| Tier-1 replayability | PostgreSQL projections | `ReplayDriver`, checkpoints, builders | No material duplicate | **KEEP** |
| Projection consistency token | PostgreSQL | ledger seq/checkpoints + API consistency guards | No | **KEEP** |
| Deterministic segment/evidence identity | UMD + PostgreSQL | deterministic keys + unique constraints | No | **KEEP** |
| One canonical stage lineage | UMD + Hatchet | UMD `STAGE_*` maps mirrored as native Hatchet parents | **Yes** | **REPAIR** to UMD-only lineage |
| Durable dispatch | Hatchet | native workflow submission | No equivalent production queue | **Replace mechanism** | **REPLACE** with PG queue |
| Worker leasing / coordination | Hatchet | Hatchet scheduler/worker | No | **REPLACE** with PG leases |
| Durable stage records | PostgreSQL | `stage_run` | Hatchet also retains engine run state | Partly | **KEEP PG**, remove second lifecycle |
| Effective-once completion | UMD/PostgreSQL | claim + atomic ledger/stage completion | No | **KEEP** |
| Retry/backoff | UMD executor | bounded retry + in-worker sleep | Hatchet can also retry transport/workflow | Potential overlap | **REPAIR** durable timer placement |
| Deterministic quarantine | UMD/PostgreSQL | executor classification + quarantine table | No | **KEEP** |
| Cancellation | UMD/PostgreSQL + scheduler reality | job state checked by UMD; Hatchet may already have dispatched callback | Partial | **REPAIR** queue cancellation/lease checks |
| Crash/restart recovery | PG stage claim/replay + Hatchet redelivery | split across two systems | **Yes** | **REPAIR** into PG queue + stage state |
| Selective descendant invalidation | UMD | `InvalidationPlanner` + `JobService` | Hatchet needs selected-stage translation | **Yes at adapter** | **KEEP UMD**, delete translation |
| Unaffected ancestor preservation | UMD/PostgreSQL | deterministic idempotency + committed refs | No | **KEEP** |
| Rerun generations | implicit manifest causation | no explicit generation authority | No duplicate; **missing guarantee** | **REPAIR** first-class generation |
| Untrusted parser isolation | security subsystem | production wires bounded subprocess; bwrap implementation exists but is not wired | No | **REPAIR** |
| Self-hosted Compose | Compose | UMD + Hatchet split topology | N/A | **SIMPLIFY** |
| Public HTTP behavior | FastAPI | live boundary E2E | N/A | **KEEP contract** |

---

## 4. Architecture findings — ranked

### F-01 — Two durable orchestration models own one execution lifecycle

- **Severity:** HIGH
- **Classification:** DUPLICATE AUTHORITY; ACCIDENTAL COMPLEXITY; TEST-COUPLED COMPLEXITY
- **Files:**
  - `src/umd/jobs/dag.py`
  - `src/umd/jobs/runner.py`
  - `src/umd/jobs/hatchet.py`
  - `src/umd/application/jobs.py`
  - `src/umd/jobs/stage_execution.py`
  - `src/umd/storage/postgres/job_repository.py`
  - `src/umd/storage/postgres/stage_repository.py`
  - `deploy/compose.yaml`
  - `tests/test_hatchet_live.py`
  - `.github/workflows/validation.yml`
- **Requirement/design relationship:** Task §§6, 16, 23 require durable, independent, restartable stages, retries, cancellation, recovery, and selective descendant invalidation. The DD selected Hatchet as a v1 implementation choice but separately defines UMD/PostgreSQL stage authority.
- **Problem:** The actual implementation has one UMD execution state machine and one Hatchet workflow state machine. UMD owns the canonical lineage, execution subset, idempotency, retry/quarantine semantics, cancellation state, completion, and aggregate status. Hatchet owns another native DAG and dispatch state. Selective rerun is translated by submitting the **full static native workflow** with full manifests plus `selected_stages`; unaffected tasks must be recognized/deduplicated/skipped through UMD state.
- **Operational consequence:** Two recovery models, two representations of the DAG, more deployment state, more upgrade/migration work, and a large proof surface whose main purpose is demonstrating that the adapter really traversed Hatchet before reaching the UMD executor.
- **Recommendation:** **REPLACE** Hatchet with a PostgreSQL durable queue/lease layer; retain `DAGRunner` as a transport seam if useful, but make PostgreSQL the only durable execution state machine.
- **Confidence:** HIGH

### F-02 — Public source ingestion duplicates the application command

- **Severity:** HIGH
- **Classification:** DUPLICATE COMMAND PATH; IMPLEMENTATION DRIFT
- **Files:**
  - `src/umd/application/ingestion.py`
  - `src/umd/api/routers/sources.py`
  - `src/umd/storage/postgres/repositories.py`
- **Requirement/design relationship:** DD module map assigns transaction boundaries/idempotency to `application`; routers are API adapters.
- **Problem:** `IngestionCommandHandler` already defines OCFL write -> source/work membership -> `SourceIngested` append. `sources.py::_submit_source` independently repeats the same lifecycle and then adds job dispatch. The paths already diverge: the application handler explicitly calls `add_membership(..., role="primary")`; the router implementation does not.
- **Operational consequence:** Entry-point-dependent behavior, duplicated validation/persistence rules, and future fixes must be applied twice. The router has become a business-service implementation.
- **Recommendation:** **REPAIR.** Make one application ingestion command authoritative. Router responsibilities should end at auth, request decoding/bounds, and response/error mapping. The application command should own dedup, work/source membership, ledger append, and durable job enqueue.
- **Confidence:** HIGH

### F-03 — Required OS sandbox isolation is implemented but not production-wired

- **Severity:** HIGH
- **Classification:** MISSING GUARANTEE; IMPLEMENTATION DRIFT
- **Files:**
  - `src/umd/api/app.py`
  - `src/umd/security/sandbox.py`
  - `src/umd/security/bwrap.py`
  - `src/umd/security/capabilities.py`
  - `deploy/compose.yaml`
  - `tests/test_sandbox_boundary.py`
- **Requirement/design relationship:** Task §32 and DD sandbox posture require hardened isolation for dangerous/untrusted parser execution.
- **Problem:** Production runtime assembly uses `SubprocessSandboxRunner`. Its own module contract explicitly states that it supplies rlimits/timeouts/policy/read-only spool but **not OS-level isolation**. `BubblewrapSandboxRunner` implements the stronger gated boundary, but repository search shows it instantiated in sandbox tests rather than production runtime. The Compose `sandbox-runner` profile starts the normal worker role and does not itself establish stage-class routing to a hardened parser boundary.
- **Operational consequence:** Capability reporting can truthfully describe the host, while actual dangerous parser work still executes through a weaker containment seam than the DD requires. A separate container can exist without being the authority through which untrusted parser calls actually pass.
- **Recommendation:** **REPAIR**, not delete. Make hardened sandbox routing structural: either (a) a dedicated sandbox executor consumes only untrusted-parser work items, or (b) the ordinary worker invokes `BubblewrapSandboxRunner` fail-closed on supported hosts. Do not count the current generic `sandbox-runner` service as proof until task routing makes it the real boundary.
- **Confidence:** HIGH

### F-04 — Rerun generation is not a first-class durable concept

- **Severity:** HIGH
- **Classification:** MISSING GUARANTEE
- **Files:**
  - `src/umd/jobs/manifest.py`
  - `src/umd/jobs/runner.py`
  - `src/umd/application/jobs.py`
  - `src/umd/api/routers/segments.py`
  - `src/umd/api/routers/sources.py`
  - PostgreSQL job/stage schema
- **Requirement/design relationship:** Required behavior includes rerun generations, selective invalidation, unaffected ancestor preservation, and effective-once completion within an execution generation.
- **Problem:** Fresh rerun identity is produced indirectly by adding `rerun_causation` to the stage input manifest. Public commands use stable causation labels such as `api:segment-rerun`. Repeating the same command with otherwise identical inputs therefore recreates the same stage idempotency material and can replay the old completed key instead of establishing a distinct execution generation.
- **Operational consequence:** “rerun again” and “replay the same rerun request” are not durably distinguishable. Audit can describe a causation string but not a first-class monotonically/uniquely identifiable execution generation.
- **Recommendation:** **REPAIR.** Add a PostgreSQL-owned execution generation (`job_execution` row or equivalent). Put its generation ID into idempotency material only for stages selected to re-execute; reused ancestors retain their existing canonical keys. Persist selected stages and causation on the generation.
- **Confidence:** HIGH

### F-05 — Segment rerun leaks identity/scope semantics into the HTTP adapter

- **Severity:** MEDIUM
- **Classification:** IMPLEMENTATION DRIFT; DUPLICATE COMMAND PATH
- **Files:** `src/umd/api/routers/segments.py`, `src/umd/application/jobs.py`
- **Requirement/design relationship:** one command path per business operation; exact source/segment identity and selective rerun semantics.
- **Problem:** `/v1/segments/{segment_id}/rerun` calls `JobService.rerun_stage` with `source_id=segment_id`. The application service expects a source identity and builds stage manifests from it. The router also chooses the root stage and causation directly.
- **Operational consequence:** The API adapter must understand execution internals and can produce manifests scoped to the wrong durable identity.
- **Recommendation:** **REPAIR.** Add a canonical application rerun command accepting a typed target (`source|segment|claim`), resolve target -> source/segment identity once, create an execution generation, plan descendants, and enqueue them. Routers should not choose stage-manifest identity.
- **Confidence:** HIGH

### F-06 — Production retry backoff occupies a worker instead of being a durable timer

- **Severity:** MEDIUM
- **Classification:** IMPLEMENTATION CHOICE; ACCIDENTAL COMPLEXITY under multi-worker scheduling
- **Files:** `src/umd/jobs/stage_execution.py`, `src/umd/api/app.py`
- **Requirement/design relationship:** durable retry/backoff, worker capacity, crash recovery.
- **Problem:** `RealBackoff.sleep()` calls `time.sleep()`, and the executor loops retries in the same callback. This satisfies bounded retry shape but makes retry delay process-local and consumes a worker slot. A crash during the sleep relies on later reclaim rather than a durable retry timestamp.
- **Operational consequence:** Low current risk because delays are short, but this becomes the wrong primitive once PostgreSQL owns dispatch and concurrency.
- **Recommendation:** **REPAIR during queue migration.** Keep `RetryPolicy`, but persist `available_at`/attempt state on the work item and release the lease between attempts. The queue, not a sleeping worker, should implement time.
- **Confidence:** HIGH

### F-07 — Hatchet-specific release proof has become part of the production complexity budget

- **Severity:** MEDIUM
- **Classification:** TEST-COUPLED COMPLEXITY
- **Files:**
  - `.github/workflows/validation.yml`
  - `.github/scripts/*hatchet*`
  - `tests/test_hatchet_live.py`
  - engine-visible proof scripts/artifacts
- **Requirement/design relationship:** Task requires product behavior and trustworthy release proof, not a particular scheduler brand.
- **Problem:** Current CI correctly proves a real Hatchet deployment, but image preflight, config generation, tenant JWT minting, worker registration, live Hatchet shape tests, engine-visible SQL/runtime proof, and aggregate engine gates exist specifically because Hatchet is an implementation choice.
- **Operational consequence:** Removing or upgrading the scheduler affects a large release pipeline even when product-level behavior is unchanged.
- **Recommendation:** **DELETE/REPLACE** backend-specific proof if Hatchet is replaced. Keep backend-neutral public-boundary, restart/persistence, stage idempotency, retry/quarantine/cancel, and recovery tests. Add small PostgreSQL queue conformance tests in place of the Hatchet adapter suite.
- **Confidence:** HIGH

### F-08 — Projection replay/locking is complexity that earns its keep

- **Severity:** N/A — positive finding
- **Classification:** FAITHFUL NECESSITY; IMPLEMENTATION CHOICE
- **Files:** `src/umd/storage/postgres/ledger.py`, `src/umd/projections/base.py`, `src/umd/projections/checkpoint.py`
- **Requirement/design relationship:** immediate current-state semantics, replayable disposable Tier-1, consistency checkpoints.
- **Assessment:** The ledger updates Tier-0 in the same transaction as semantic append through the shared reducer. Tier-1 replay uses ordered events, the same reducer, one builder-owned checkpoint, and a projection-name PostgreSQL advisory transaction lock. The locking is narrowly scoped to preventing concurrent rebuild/checkpoint regression, not a second semantic authority.
- **Recommendation:** **KEEP.** Do not simplify away event immutability, shared reducer, checkpointing, or per-projection rebuild serialization.
- **Confidence:** HIGH

### F-09 — OCFL byte ownership is clean

- **Severity:** N/A — positive finding
- **Classification:** FAITHFUL NECESSITY
- **Files:** `src/umd/storage/ocfl/store.py`, `src/umd/storage/postgres/repositories.py`, ingestion paths
- **Requirement/design relationship:** immutable source bytes, exact provenance, one byte authority.
- **Assessment:** Object IDs derive from content SHA-512 rather than filenames; fixity is verified; reads are bounded; PostgreSQL stores descriptors/references rather than becoming the only byte store.
- **Recommendation:** **KEEP.** Repair ingestion command duplication around it, not the OCFL boundary itself.
- **Confidence:** HIGH

---

## 5. Execution-engine comparison

### Required capabilities first

Universeity actually needs:

- durable dispatch and multi-worker claim/lease;
- crash reclaim;
- bounded concurrency/backpressure;
- durable retry timers;
- cancellation before newly leased work and cooperative cancellation of running work;
- worker wakeup/scheduling;
- queue/worker observability;
- no loss of UMD's deterministic stage identity, selective invalidation, generation semantics, PostgreSQL completion authority, or self-hosted Compose posture.

It does **not** need a second source of truth for semantic state, DAG lineage, stage completion, or invalidation decisions.

### Compact comparison

| Capability / cost | Hatchet today | PostgreSQL queue + existing UMD | Temporal |
|---|---|---|---|
| Durable dispatch | Strong, working | **Must add** small queue table/loop | Strong |
| Worker leasing/coordination | Strong | **Must add** lease/heartbeat/reclaim | Strong |
| Crash recovery | Hatchet + UMD split | UMD stage replay exists; queue lease expiry needed | Strong |
| Concurrency/backpressure | Supplied by engine | **Must add** resource/class limits | Strong |
| Retry timers | Engine capability exists, but UMD currently retries internally | **Must add durable `available_at`; reuse RetryPolicy** | Strong |
| Cancellation | Platform + UMD state overlap | UMD state exists; lease/worker checks needed | Strong |
| Scheduling/wakeup | Supplied | **Must add LISTEN/NOTIFY + polling fallback** | Supplied |
| Multi-worker | Supplied | `SKIP LOCKED`/lease pattern required | Supplied |
| Observability | Dashboard + engine proof | queue depth/age/lease metrics required | Rich platform |
| UMD DAG duplication | **Yes** | **No** | Would duplicate unless authority is moved |
| Stage-state duplication | Hatchet engine + PG | **One PG model** | Temporal history + PG unless redesigned |
| Selective rerun fit | Adapter translation through static full DAG | **Native to existing planner** | Possible, but requires workflow modeling change |
| Deployment burden | 2 long-lived + 2 init Hatchet services, config/token lifecycle | **No new datastore/service** beyond existing worker | Dedicated workflow service/control plane + persistence operations |
| Upgrade/migration burden | Hatchet schema + SDK/server compatibility + UMD schema | UMD/Postgres schema only | Temporal server/SDK/persistence compatibility + UMD schema |
| Amount of existing UMD reused | High, but behind translation layer | **Highest** | Moderate if done correctly |
| Net fit to current requirements | Correct but overpowered/duplicative | **Best fit** | Overpowered today |

### A. Current Hatchet architecture

Hatchet is **functionally successful**. Hosted run `33312774348` proves genuine worker registration, live workflow execution, public E2E, persistence across restart, and engine-visible execution.

Its architectural weakness is not missing capability; it is **capability overlap**. `ProductionDAGRunner` submits a static native workflow for every execution. UMD still determines the selected stages. Worker callbacks return through `DurableStageExecutor`, where the durable claim and authoritative completion occur. Hatchet therefore schedules work whose business lifecycle is already modeled elsewhere.

**Disposition: REPLACE**, after a backend-neutral parity run proves the PostgreSQL queue preserves the control-group behavior.

### B. PostgreSQL durable work queue

This option is not “build a workflow engine from scratch.” Most of the workflow engine already exists in UMD.

**Already implemented today:**

- canonical stage DAG and descendant lineage;
- invalidation planner;
- deterministic stage manifests/idempotency;
- durable jobs and stage runs;
- claim-before-side-effect;
- atomic effective-once completion;
- committed evidence/artifact chaining;
- cancellation state;
- retry classification/policy;
- quarantine;
- completed-run replay;
- incomplete-run reclaim semantics;
- job aggregate status;
- operational audit;
- production worker process and stage registry.

**Actually missing if Hatchet vanished tomorrow:**

1. a durable work-item row for eligible selected stages;
2. atomic lease claim + lease owner/expiry + heartbeat/reclaim;
3. durable retry `available_at` and attempt scheduling;
4. worker wakeup/poll fallback;
5. concurrency/resource-class/backpressure controls;
6. queue depth/age/lease observability and drain semantics.

That is a scheduler/queue, not another workflow authority.

A suitable design is a PostgreSQL row claim using transactional locking (`FOR UPDATE SKIP LOCKED` or equivalent atomic UPDATE/RETURNING), with a bounded polling fallback even when `LISTEN/NOTIFY` is used for low-latency wakeup. Eligibility remains computed from the canonical UMD DAG and the execution generation's selected-stage set. The queue row points at a serialized `StageManifest`; it does not own semantic state.

**Disposition: SELECT.**

### C. Temporal

Temporal cleanly supplies durable workflows, worker task queues, timers, retry policy, cancellation/signals, and recovery. It is the strongest option if Universeity grows into long-running cross-service workflows whose orchestration history should itself become the dominant execution model.

That is not the current system. To use Temporal without repeating the Hatchet problem, Universeity would need to move meaningful lifecycle authority out of `JobService`/PostgreSQL and into Temporal workflows. That is an architecture rewrite, not a transport replacement. Keeping current PostgreSQL execution authority while adding Temporal would again produce two durable state machines.

**Disposition: DEFER.** Reconsider only if requirements add workflow capabilities that are genuinely difficult to express with the small PostgreSQL scheduler: long-duration human signals, many dynamic child workflows, complex cross-service sagas, or durable timers measured in days/months with substantial orchestration branching.

### Decision

**PostgreSQL queue + existing UMD DAG/executor is the smallest architecture that preserves every required capability while deleting the most duplicated state.**

---

## 6. Complexity / deletion analysis

| Candidate | Modules that disappear/simplify | Persistent state removed | Containers / services removed | Operational concepts removed | New machinery | Migration risk |
|---|---|---|---|---|---|---|
| Keep Hatchet | none | none | none | none | generation + sandbox repairs still required | Low immediate / continuing ops tax |
| **PostgreSQL queue** | delete `jobs/hatchet.py`; simplify `jobs/runner.py`, `deploy/cli.py`, capability probe; remove Hatchet SDK integration/tests/scripts | Hatchet workflow/task/run/config state; retain UMD job/stage state; add one queue/generation model | remove `hatchet-engine`, `hatchet-dashboard`, `hatchet-migrate`, `hatchet-admin`; keep UMD worker | tenant/JWT minting, SDK/server compatibility, native DAG registration, engine-visible proof | queue item + lease/reclaim + durable retry timer + wakeup + concurrency metrics | **Medium**, reversible with dual adapter parity |
| Temporal | replace Hatchet integration but add Temporal workflow code | Hatchet state removed; Temporal workflow history added; PG state must be reduced or duplicated | Hatchet services removed, Temporal services added | Hatchet-specific ops replaced by Temporal ops | workflow definitions/adapters/migration of lifecycle authority | High |

### Deletion estimate for the PostgreSQL target

The deletion is meaningful even without counting generated/vendor code:

- `src/umd/jobs/hatchet.py` disappears as a production module.
- Hatchet submission machinery in `src/umd/jobs/runner.py` disappears; the canonical DAG and runner protocol remain.
- SDK/tenant/host-port setup and workflow registration in `src/umd/deploy/cli.py` simplify to a queue worker loop.
- `hatchet-sdk` optional dependency disappears.
- Four Hatchet Compose service definitions and Hatchet config/cert volumes disappear.
- Hatchet image preflight, tenant JWT minting, worker registration probes, live scheduler shape tests, and engine-visible Hatchet proof disappear or are replaced by small queue conformance checks.
- The static-native-DAG/full-manifest/selected-stage translation disappears.

The target adds one small durable scheduler concept instead of a second workflow platform:

```text
work_item(
  id,
  job_id,
  execution_generation,
  stage_name,
  manifest,
  state,
  available_at,
  lease_owner,
  lease_until,
  attempt,
  priority,
  created_at,
  updated_at
)
```

Exact schema is an implementation decision. The invariant is more important: **the queue owns only delivery/lease state; `stage_run` + semantic completion remain the completion authority.**

---

## 7. Target architecture

### Authority rules

1. **OCFL is the only byte authority.** PostgreSQL stores content identity, descriptors, and immutable references.
2. **PostgreSQL semantic ledger is the only semantic write authority.** Tier-0 updates remain in the append transaction; Tier-1 remains replayable/disposable.
3. **`umd.jobs.dag` is the only DAG definition.** No scheduler-native mirror is authoritative.
4. **PostgreSQL is the only durable execution state machine.** Jobs, generations, queue leases, stage runs, cancellation, audit, and completion live in one transactional system.
5. **Application commands are the only business command paths.** HTTP, CLI, and future transports adapt to the same commands.

### Target command path

```text
POST /v1/sources
  -> router: auth + bounded decode + schema
  -> IngestSource command
       -> OCFL put/reuse
       -> source/work/membership transaction(s)
       -> SourceIngested append / Tier-0
       -> create job + generation 0 + queue eligible root work
  -> response
```

Corrections/reruns follow the same pattern:

```text
HTTP correction/rerun
  -> typed application command
       -> resolve target identity
       -> append correction/invalidation if applicable
       -> create new execution generation
       -> compute selected descendant closure from ONE DAG
       -> enqueue selected work only
       -> retain unaffected ancestor stage outputs
```

### Target worker path

```text
worker loop
  -> atomically lease one eligible work_item
  -> re-check job/generation cancellation
  -> DurableStageExecutor.run(manifest, stage_work)
       -> StageRunRepository.claim
       -> work
       -> atomic StageCompleted + stage_run completion
  -> mark delivery complete
  -> enqueue newly eligible selected children

transient failure
  -> persist attempt + available_at
  -> release lease
  -> later worker lease

deterministic failure
  -> quarantine
  -> terminal work item
```

### Sandbox boundary

Untrusted decoding/parsing must cross a structural execution boundary. Two acceptable shapes preserve the DD invariant:

- **Dedicated sandbox executor:** queue work items carry a required capability/resource class; only the sandbox worker can lease parser-class work. The sandbox worker runs Bubblewrap/other validated OS isolation and has the minimal filesystem/network privileges required.
- **Fail-closed local isolation:** if the ordinary worker itself can reliably invoke validated Bubblewrap on the supported deployment target, parser work may remain in that container but must instantiate the hardened runner, not the weaker subprocess containment seam.

The current generic `sandbox-runner` Compose profile should not survive merely as a named service. It should either become the actual security executor or disappear in favor of a provably equivalent hardened boundary.

### Target deployment count

**Core steady state:**

- `db`
- `api`
- `worker`

**Security capability:**

- `sandbox-runner` only when implemented as a real isolated parser executor; for the DD's untrusted-media posture this will normally be part of the supported production topology.

**Optional capability profiles remain:** Ollama, MinIO/S3 bridge.

No Hatchet engine/dashboard/init services are required.

---

## 8. Migration sequence — architecture level only

All steps are reversible until the final Hatchet deletion.

### M1 — Make behavior proofs backend-neutral

Retain the green `124f092` run as control. Label tests explicitly:

- product invariant;
- execution-adapter conformance;
- implementation-specific proof.

Do not weaken public-boundary, restart/persistence, idempotency, retry/quarantine/cancellation, selective-rerun, consistency, or provenance assertions.

### M2 — Repair command boundaries and generation model before changing transport

Introduce one application ingestion path and one typed rerun/invalidation path. Add first-class execution generation semantics while Hatchet is still present. This prevents scheduler migration from being mixed with business-lifecycle repair.

### M3 — Add PostgreSQL delivery/lease scheduler behind the existing runner seam

Implement queue item, lease/reclaim, durable retry timing, wakeup/polling, concurrency/backpressure, drain, and observability. Keep `DurableStageExecutor` and stage completion untouched.

### M4 — Run both dispatch adapters against the same backend-neutral acceptance suite

Use separate test deployments/databases, not dual execution of the same production job. Require equivalent externally visible behavior and durable rows for the same scenarios. Hatchet remains the rollback path until parity is demonstrated.

### M5 — Flip production dispatch; then delete Hatchet-specific machinery

Make PostgreSQL queue the sole production scheduler. Run the complete release gate, including restart/persistence and public HTTP behavior. Only after parity is green remove Hatchet SDK, services, config/token scripts, native DAG adapter, and implementation-specific proofs.

Sandbox hardening should be repaired independently and must not be weakened during this sequence.

---

## 9. Explicit disposition table

| Component / concern | Disposition | Reason |
|---|---|---|
| OCFL immutable store/fixity | **KEEP** | Correct single byte authority |
| PostgreSQL source/segment/evidence metadata | **KEEP** | Correct typed authority |
| Semantic ledger + shared Tier-0 reducer | **KEEP** | Required append-only semantic authority / RYW |
| Tier-1 replay/checkpoint machinery | **KEEP** | Required disposable/replayable projections; locking is scoped correctly |
| Canonical `umd.jobs.dag` lineage | **KEEP** | Required single DAG definition |
| `DurableStageExecutor` claim/completion/quarantine | **KEEP** | Carries effective-once/product semantics |
| In-executor sleeping retry | **REPAIR** | Move timer to durable queue while retaining policy |
| PostgreSQL job/stage/audit authority | **KEEP** | Already authoritative for product lifecycle |
| Execution generation | **REPAIR** | Make first-class durable identity |
| Hatchet production scheduler | **REPLACE** | Supplies narrow dispatch capability while duplicating orchestration/state |
| Hatchet native DAG/full-manifest adapter | **DELETE** after migration | Translation layer no longer needed |
| Hatchet engine/dashboard/admin/migrate topology | **DELETE** after migration | No product authority remains there |
| Hatchet-specific CI/engine proof | **DELETE/REPLACE** | Implementation-specific, replace with queue conformance |
| Application ingestion handler | **REPAIR/KEEP as canonical** | Correct layer; extend to own durable dispatch |
| Router-owned ingestion lifecycle | **DELETE** | Duplicate command path |
| Router-owned rerun target/stage construction | **DELETE** | Business semantics belong in application command |
| `SubprocessSandboxRunner` | **KEEP for bounded containment only** | Useful primitive, insufficient as DD security boundary |
| `BubblewrapSandboxRunner` / hardened isolation | **REPAIR into production** | Required security guarantee exists but is not wired |
| Generic Compose `sandbox-runner` role | **REPAIR or DELETE** | Keep only if it becomes the actual isolated execution route |
| Temporal | **DEFER** | Stronger than needed; would require moving lifecycle authority or duplicating it |
| Optional Ollama / MinIO profiles | **DEFER/KEEP optional** | Capability-dependent, not core authority |

---

## 10. Open questions

Only three unresolved answers could materially change this recommendation:

1. **Required scheduler scale:** Is the supported production target expected to sustain enough concurrent workers/queued stages that a single PostgreSQL queue becomes an independently demonstrated bottleneck? No evidence in Task/DD/current validation establishes that threshold. If future measured load exceeds it, reevaluate the transport rather than pre-optimizing now.

2. **Long-lived orchestration semantics:** Will Universeity require human signals, workflows suspended for days/months, large dynamic child-workflow trees, or cross-service sagas as first-class requirements? If yes, Temporal becomes materially more attractive because it would supply capabilities the current UMD state machine does not already provide.

3. **Supported sandbox host posture:** Is bare-metal/VM Bubblewrap still the first-class production posture, or must the exact same hardened parser isolation be guaranteed inside an unprivileged Docker/Kubernetes worker? This changes the sandbox deployment shape, but **not** the requirement to keep a real isolation boundary.

None of these questions justify retaining Hatchet solely because it is already green.

---

## Appendix A — Test/proof classification

| Proof | Classification | Survives scheduler replacement? |
|---|---|---|
| Ruff / strict mypy | Tooling quality gate | Yes |
| Unit tests | Product/internal contract | Yes |
| PostgreSQL integration | Product authority/invariants | Yes |
| Public-boundary HTTP E2E | **Product invariant** | **Yes, unchanged** |
| Restart/persistence E2E | **Product invariant** | **Yes, unchanged** |
| Duplicate/effective-once/reclaim tests over real PG | **Product invariant** | **Yes** |
| Retry/quarantine/cancel/selective rerun | **Product invariant** | **Yes** |
| Consistency-token / projection replay | **Product invariant** | **Yes** |
| Native Hatchet task-parent graph | Adapter conformance | No; replace with single-DAG queue eligibility test |
| Hatchet worker registration | Adapter conformance | No |
| Live Hatchet suite | Adapter conformance | No |
| Hatchet SQL/schema proof | Implementation-specific proof | No |
| Engine-visible assignment/runtime/callback proof | Implementation-specific proof | No; replace with lease/worker callback proof |
| Hatchet image/tag/JWT/config gates | Implementation-specific deployment proof | No |

The acceptance rule during migration is simple: **backend-specific tests may disappear only after every product-invariant row above remains green through the replacement backend.**

---

## Appendix B — Evidence index

Primary implementation evidence reviewed:

- `Task.md`
- `artifacts/designs/pending/DD-universal-media-decomposer.md`
- `artifacts/designs/process/universal-media-decomposer-architecture-options.md`
- `artifacts/designs/process/universal-media-decomposer-complexity-review.md`
- `src/umd/jobs/dag.py`
- `src/umd/jobs/runner.py`
- `src/umd/jobs/hatchet.py`
- `src/umd/jobs/stage_execution.py`
- `src/umd/jobs/manifest.py`
- `src/umd/jobs/invalidation.py`
- `src/umd/application/jobs.py`
- `src/umd/application/ingestion.py`
- `src/umd/storage/postgres/job_repository.py`
- `src/umd/storage/postgres/stage_repository.py`
- `src/umd/storage/postgres/ledger.py`
- `src/umd/storage/postgres/repositories.py`
- `src/umd/storage/ocfl/store.py`
- `src/umd/projections/base.py`
- `src/umd/projections/checkpoint.py`
- `src/umd/api/app.py`
- `src/umd/api/routers/sources.py`
- `src/umd/api/routers/jobs.py`
- `src/umd/api/routers/segments.py`
- `src/umd/security/sandbox.py`
- `src/umd/security/bwrap.py`
- `src/umd/deploy/cli.py`
- `deploy/compose.yaml`
- `pyproject.toml`
- `tests/test_hatchet_live.py`
- `tests/test_api_boundary_e2e.py`
- `.github/workflows/validation.yml`
- hosted validation run `33312774348`

---

## Final recommendation

**Keep the core. Remove the duplicate scheduler.**

Universeity should converge on **OCFL for bytes + PostgreSQL for all semantic and execution authority + one UMD DAG + one worker/executor path + a real hardened sandbox boundary**.

Replace Hatchet with a narrowly scoped PostgreSQL durable queue/lease scheduler. Repair command boundaries and first-class execution generations before the transport cutover. Preserve the existing fully green public behavior as the control group and delete Hatchet-specific infrastructure only after the backend-neutral release gate passes unchanged.

That is the smallest system this repository would reasonably be designed as today with full knowledge of what the working implementation actually needs.