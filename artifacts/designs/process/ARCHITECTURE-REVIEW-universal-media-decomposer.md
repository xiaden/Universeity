# Adversarial Architecture Review — Universal Media Decomposer

**Status:** Complete review (read-only)  
**Reviewed state:** `main` at `124f092b2f36ca8e990c9dd9d8841392eba81d28`  
**Validation floor:** hosted run `33312774348` (green release validation)  
**Authority:** `Task.md`, `artifacts/designs/pending/DD-universal-media-decomposer.md`, `CONTRACTS.md`, and process/adversarial artifacts.  
**Scope:** architecture and implementation review only; no application code was changed.

## Executive conclusion

The product authority model is coherent and should be retained: OCFL owns immutable bytes; PostgreSQL owns typed source/segment data, the append-only semantic ledger, Tier-0 current state, durable stage records, and audit; projections are disposable; the in-repository DAG is the one lineage definition; and the sandbox is a security boundary rather than a business microservice. The green run is a useful regression floor, not evidence that every authority and command boundary is correct.

The current implementation's highest risks are not a need for Neo4j, RDF, Dagster, or Temporal. They are incomplete/duplicated boundaries around an otherwise sound core:

1. The live ingestion route duplicates and bypasses `IngestionCommandHandler`, omits membership creation, and spreads one logical command across OCFL plus several independent transactions.
2. Correction/invalidation APIs append events but do not invoke the implemented descendant-rerun/pause chain; the segment rerun route passes a segment id as a source id and is production-broken.
3. Stage semantic events and some side effects are emitted outside the atomic stage-completion transaction and without deterministic event keys.
4. `current_entity_map` is a non-replayable side-effect table, while `semantic_assertion` is a phantom schema surface; both contradict the claimed single/replayable authority model.
5. Tier-1 current projection is globally wiped/rebuilt from individual job work, creating a concurrency and crash window.
6. The native nine-task Hatchet topology is the correct current adapter shape, but its value is concentrated in the engine barrier, lease/dispatch, and restart delivery. Selective reruns resubmit all nine callbacks, and the proof/tenant/runtime surface is materially larger than the product core.
7. The sandbox seam is well-designed but incompletely wired: text/EPUB/PDF paths can parse in-process.

**Recommendation:** retain Hatchet as the v1 scheduler, conditionally on continuing hosted proof of the single native workflow and parent barrier. Repair the command, transaction, reducer/replay, projection, segment-rerun, and sandbox wiring gaps before expanding the architecture. Do not introduce Temporal or a second scheduler. If Hatchet later fails its pin-level proof, replace it only through an explicit DD amendment with a PostgreSQL dispatcher that owns queue, lease, dependency gating, and restart-redrive semantics; do not pretend the existing executor alone is a queue.

## Current architecture and authority/data flow

```text
HTTP /v1 routes
  sources.py::_submit_source             claims/entities/segments/jobs routes
       |                                        |
       | OCFL put + source/work rows          SemanticCommandService
       |                                        |
       +-------------------------------> SemanticLedger.append
                                            |  validate/upcast, idempotency
                                            |  same-tx CurrentStateReducer
                                            v
             OCFL immutable objects     PostgreSQL semantic_event + current_state
             (sha512/fixity)                 |             |
                    |                         |             +--> ReplayDriver
                    v                         |                    | checkpoints/poison
             source/descriptor/segment        |                    v
             evidence/artifact refs           |              Tier-1 search/vector/current
                                              |
             JobService.submit/rerun/invalidate
                    |
                    +--> InvalidationPlanner (DAG descendants only)
                    +--> ProductionDAGRunner
                              |
                    Hatchet: one workflow, nine durable tasks,
                    native parents from STAGE_DEPENDENCIES
                              |
                    worker callback (cancel check; canonical evidence lookup)
                              |
                    DurableStageExecutor
                    claim UNIQUE(stage idempotency key) before side effects
                       | retry/backoff; quarantine; crash resume/replay
                       v
                    stage work / providers / modality branches
                       | evidence + segments + semantic events
                       v
                    StageRunRepository + ledger.complete_and_append
                    stage_run + StageCompleted + artifact refs + audit
```

### Ownership matrix

| Concern | Actual authority | Evidence | Assessment |
|---|---|---|---|
| Bytes and fixity | OCFL `SourceStore` | `src/umd/storage/ocfl/store.py:88-190,238-256` | Faithful; derived-byte writer gap remains |
| Source/work/segments/locators | PostgreSQL typed repositories | `src/umd/storage/postgres/repositories.py`; DD ownership table | Intended, but live ingestion bypasses application command and membership |
| Semantic history | `semantic_event` via `SemanticLedger` only | `src/umd/storage/postgres/ledger.py:62-213`; append-only trigger | Faithful necessity |
| Tier-0 current state | Ledger transaction + shared reducer | `ledger.py:210-303`; `reducer.py:201-242` | Faithful for `current_state`; entity map is not |
| Tier-1 | Replay builders/checkpoints | `src/umd/projections/base.py:157-220`; `checkpoint.py:65-114` | Correct mechanism, unsafe global wipe usage |
| DAG/lineage | `STAGE_DEPENDENCIES` / dependents | `src/umd/jobs/dag.py:30-117` | Faithful single authority |
| Dispatch/barrier | Hatchet native workflow | `src/umd/jobs/hatchet.py:363-380`; `runner.py:202-293` | Implementation choice, currently mandated by DD |
| Claim/completion/retry/quarantine | PostgreSQL executor path | `stage_repository.py:98-156`; `stage_execution.py:204-357` | Faithful necessity; scheduler-independent |
| Cancel/rerun/status | JobService + durable job/stage rows | `src/umd/application/jobs.py:90-367` | Mostly present; API wiring incomplete |
| Untrusted execution | Sandbox subprocess seam | `src/umd/security/sandbox.py:1-31,169-182`; bwrap module | Faithful necessity; incomplete call coverage |

## Requirements matrix

| Requirement / invariant | Current evidence | Verdict |
|---|---|---|
| Immutable source bytes and fixity | OCFL content-addressing and verification | **PASS** for sources |
| Source/evidence/interpretation/knowledge separation | typed tables, evidence refs, ledger/reducer | **PASS with authority gaps** |
| One semantic writer, append-only history | ledger API and DB trigger | **PASS** |
| Atomic Tier-0 update and replayable reducer | `append` and `CurrentStateReducer` | **PASS** for `current_state` |
| Deterministic segments/locators/provenance | segment registry, manifests, evidence refs | **PASS in tested paths** |
| Durable restartable stages | claim, retry, completion, replay | **PASS behind dispatch** |
| Effective-once completion | unique manifest key, atomic completion | **PASS**; unkeyed stage events remain a gap |
| Descendant-only invalidation | pure BFS planner and JobService | **IMPLEMENTED, API not wired** |
| User correction/override and audit | routes and command service | **PARTIAL**; correction does not schedule descendants |
| Cancellation/quarantine | durable job checks, deterministic quarantine | **PASS in worker path** |
| Tier-1 replay/checkpoints/consistency | ReplayDriver/checkpoint/guards | **PARTIAL**; global wipe per job is unsafe |
| Dangerous parser isolation | audio/video/subtitle seams; bwrap capability gate | **PARTIAL**; text/EPUB/PDF bypass |
| Public HTTP behavior | boundary E2E and RFC7807 responses | **Regression green; segment rerun contract false** |
| Self-hosted Compose | DB/API/worker/Hatchet split and optional services | **PASS, operationally heavy** |
| General-purpose extensibility | protocols/providers/modality metadata | **PASS, with premature surfaces below** |

## Ranked findings

### F1 — IMPLEMENTATION DRIFT / DUPLICATE COMMAND PATH: ingestion

**Evidence:** `src/umd/application/ingestion.py:75-155` is test-only and calls `add_membership` at line 128. The live `src/umd/api/routers/sources.py:164-252` reimplements storage, membership-adjacent rows, ledger append, and dispatch, but never adds membership and uses a UUID5 ingest key plus `job-{source_id[:12]}`.  
**Requirement relationship:** DD assigns command validation, transaction, and idempotency to application; Task source/work grouping requires membership.  
**Consequence:** two behaviors drift; live sources have no membership row; OCFL/source/event/job operations are not one command transaction. Duplicate concurrent uploads can lose the `find_source_by_sha512`/insert race at `repositories.py:396-430`.  
**Confidence:** High. **Disposition: REPAIR** — route through one canonical handler, make source insert conflict-safe, and define one job/idempotency contract.

### F2 — MISSING GUARANTEE / IMPLEMENTATION DRIFT: correction and invalidation API

**Evidence:** `JobService.invalidate` at `src/umd/application/jobs.py:274-321` records, plans descendants, schedules, and returns projection pause policy. `src/umd/api/routers/claims.py:76-91` calls only `ctx.commands.invalidate`; override/correction routes similarly stop at event append. `segments.py:79-97` passes `segment_id` as `source_id`.  
**Requirement relationship:** Task §16 and DoD §40 require correction → invalidation → selective rerun → changed answer and audit.  
**Consequence:** live user corrections leave dependent semantics stale; segment rerun returns 202 for work that production cannot resolve, generally failing closed on missing evidence/source.  
**Confidence:** High. **Disposition: REPAIR** — resolve segment-to-source/lineage and route all correction commands through the existing JobService chain; add public-boundary coverage.

### F3 — MISSING GUARANTEE / TRANSACTION DRIFT: stage side effects

**Evidence:** production stage work calls `commands.entity_resolve`, `record_alignment`, and `assert_semantic` (`src/umd/jobs/production.py:1084-1147`) before `_complete`; these use standalone ledger transactions, and alignment creates a UUID4 row. Evidence/segment repositories also commit independently before `stage_execution.py:273-333` invokes `complete_and_append`.  
**Requirement relationship:** DD requires deterministic stage completion and durable provenance; `complete_and_append` exists specifically for same-transaction side effects.  
**Consequence:** a crash after event/evidence commit but before completion causes unkeyed semantic duplicates or orphan evidence on retry; Tier-0 LWW can hide the defect while ledger/audit growth and random alignment identity reveal it. Split quarantine has a similar separate transaction (`resolution.py:384-398`).  
**Confidence:** High for events/evidence; medium for quarantine crash window. **Disposition: REPAIR** — make stage outputs deterministic and anchor authoritative stage side effects to the completion transaction, or explicitly define and reconcile a directional orphan policy.

### F4 — DUPLICATE AUTHORITY / MISSING GUARANTEE: `current_entity_map`

**Evidence:** sole writer is resolver alias side effect (`src/umd/resolution/resolution.py:331-348`); `reducer.py` and `ledger.py` do not derive it; `CurrentTierOneBuilder` only persists `current_state` (`src/umd/projections/current.py:47-83`).  
**Requirement relationship:** DD promises shared-reducer/replayable Tier-0 winners and entity map.  
**Consequence:** MERGE/SPLIT and machine resolution have inconsistent map behavior; wipe/replay cannot restore aliases, so Tier-0/Tier-1 and provenance answers diverge.  
**Confidence:** High. **Disposition: REPAIR** — derive map rows from ledger events in the shared reducer/replay, or explicitly downgrade the map to a disposable projection and remove its authority claim.

### F5 — ACCIDENTAL COMPLEXITY / MISSING GUARANTEE: global Tier-1 wipe per job

**Evidence:** `src/umd/jobs/production.py:1149-1160` calls `replay.run(builder, wipe=True)`; `CurrentTierOneBuilder.wipe` deletes all `current_state` (`current.py:47-48`).  
**Requirement relationship:** DD requires single-writer, checkpointed, replayable projections and distinct consistency failure classes.  
**Consequence:** concurrent source jobs can erase each other's current state; a crash during rebuild leaves a partial shared table; every job recomputes state already maintained atomically by Tier-0.  
**Confidence:** High. **Disposition: REPAIR** — run one serialized projection job or incremental checkpoint application; never global-wipe as an ordinary per-source terminal stage.

### F6 — IMPLEMENTATION DRIFT / MISSING GUARANTEE: sandbox coverage

**Evidence:** media branches use `SandboxRunner` (`src/umd/audio/runner.py`, `video/runner.py`, `subtitle/runner.py`), but production text/format paths call `normalize_txt` and format parsing in-process (`src/umd/jobs/production.py:313-317,896-938`); `extractors/dispatch.py:98-138` provides a seam with no production callers.  
**Requirement relationship:** DD security section and Task §32 require dangerous parsers/decoders never run in the API process.  
**Consequence:** untrusted EPUB/PDF and related parser input can execute under the application process despite a strong sandbox implementation.  
**Confidence:** High. **Disposition: REPAIR** — route risky parsers through the existing bounded/bwrap seam; keep safe normalization explicitly separated only if the accepted threat model says so.

### F7 — IMPLEMENTATION DRIFT / PHANTOM AUTHORITY: schema surfaces

**Evidence:** `semantic_assertion` is defined in tables/models but has no insert writer in `src/umd`; semantic writes live in event payload/current state. `SourceStore` supports `derived`/`artifact` kinds (`store.py:42-54,158-190`) but production writes only source objects.  
**Requirement relationship:** DD says semantic ledger is authority and derived evidence bytes have OCFL ownership; Task §2 requires provenance-to-bytes.  
**Consequence:** future readers may assume an empty second authority; derived evidence cannot be retrieved/fixity-verified from bytes.  
**Confidence:** High on absent writers, medium on intended policy. **Disposition: DELETE** `semantic_assertion` after reader verification; **DEFER or REPAIR** derived OCFL writes according to an explicit provenance policy.

### F8 — IMPLEMENTATION CHOICE with TEST-COUPLED COMPLEXITY: Hatchet surface

**Evidence:** `deploy/compose.yaml:136-222` adds migrate/admin/engine/dashboard; `hatchet.py` is the adapter/registration/probe surface; `engine-visible-proof.sh:164-198` checks the nine-task graph and `:200-299` checks engine assignment/identity/callback rows. Selective reruns in `runner.py:217-227` submit all nine tasks; unselected stages replay/dedup.  
**Requirement relationship:** DD and Plan K explicitly mandate Hatchet as sole v1 scheduler; green run 33312774348 is the regression floor.  
**Consequence:** four services, SDK/server pin, JWT tenant selection, and engine schema proof are operational cost; each selective rerun creates O(9) dispatch/callback traffic. The current shape is justified only by real native parent gating, dispatch, and leases.  
**Confidence:** High. **Disposition: KEEP** conditionally; stop adding scheduler-like logic and reprove the native barrier after every pin change.

### F9 — DUPLICATE AUTHORITY / IMPLEMENTATION DRIFT: status and evidence selection

**Evidence:** production callback uses lineage-scoped `canonical_evidence_refs` (`job_repository.py:204-289`), while hermetic runner seeds prior refs (`stage_execution.py:478-508`, `runner.py:132-145`). Status is separately interpreted by executor rows, repository `_STATUS_RANK`, aggregate status, and JSON `expected_stages`/causation (`job_repository.py:137-182`, `application/jobs.py:348-367`). Submission also has two input builders (`runner.py:202-257`, `hatchet.py:443-462`).  
**Requirement relationship:** exact provenance, deterministic keys, and one dedup authority.  
**Consequence:** future changes can reintroduce the prior evidence race or make queued/status observations disagree.  
**Confidence:** High. **Disposition: REPAIR** — one canonical manifest/evidence builder and one explicit status fold; keep engine state advisory.

### F10 — PREMATURE INFRASTRUCTURE / TEST-COUPLED COMPLEXITY: unwired operations

**Evidence:** complexity review identifies approximately 1,965 source lines in backup/vector/operations/publish/drain machinery with no production callers, plus tests that directly exercise them.  `SimpleUniverseGate` is not instantiated by production.  
**Requirement relationship:** Task asks for operational resilience, but does not make every Phase E control a live API; DD says builders should be driven by measured need.  
**Consequence:** maintenance and false confidence: green tests can certify facilities that deployment never invokes.  
**Confidence:** High for no callers, medium for deletion intent. **Disposition: DEFER**, then **DELETE** only after confirming no runbook/restore consumer; retain the invariant tests for components actually wired.

## Execution-engine comparison

| Capability | Current Hatchet | PostgreSQL durable queue | Temporal |
|---|---|---|---|
| Existing UMD authority | Reuses all Postgres authority | Reuses all Postgres authority | Must still reuse Postgres authority |
| DAG barrier | Native intra-workflow parents on pinned pair; `parent_id` is not a barrier | Must implement transactional runnable-parent query | Workflow/child/activity orchestration |
| Dispatch/leases | External worker assignment and recovery | Must add queue rows, leases, heartbeat/reclaim, worker loop | Native task queues and worker lifecycle |
| Retry/backoff | Adapter plus executor retry | Executor retry plus queue redrive | Native activity retry/timers, but duplicate policy surface |
| Cancellation | Persisted UMD cancel check plus delivery | Same, plus worker shutdown semantics | Signals/cancellation, still reconcile UMD state |
| Selective rerun | Full static nine-task run; target markers; other callbacks replay | Can enqueue only descendant closure | Workflow version/signals/child design required |
| Proof cost | SDK/server pins, tenant/schema and engine-visible proof | DB queue and callback-owned proof | New workflow replay/worker/deployment proof |
| Current policy fit | **Approved v1** | Requires DD amendment | Future trigger only |

If Hatchet disappears, the existing `DurableDAGRunner` is not by itself a production queue: it executes synchronously when driven, but does not provide durable dispatch, leases, parent release, worker assignment, or automatic restart redrive. A PostgreSQL replacement must add those capabilities and become the explicitly approved scheduler. Temporal is technically capable but heavier and duplicates retry/cancel/recovery semantics already intentionally owned by PostgreSQL.

## Complexity and deletion analysis

### Keep

- OCFL + fixity; PostgreSQL ledger/reducer; `stage_run` unique claims; atomic completion; audit outside semantic replay.
- One in-repository DAG and descendant planner; plugin/provider protocols; PostgreSQL search/vector; sandbox subprocess and capability honesty.
- Hatchet only as dispatch/barrier/lease adapter while native-DAG hosted proof remains green.

### Repair

- Canonicalize ingestion and all correction/invalidation command paths.
- Unify manifest/evidence selection and status interpretation.
- Make stage side effects deterministic and transactionally anchored.
- Make entity map replayable; serialize/incrementalize projection rebuilds.
- Wire parser sandbox coverage, OCFL readiness, and segment rerun resolution.
- Remove shared `UMD_RUN_MIGRATIONS_ON_START` from long-lived API/worker roles; use a one-shot migration gate to avoid three concurrent boot migrations.

### Delete or defer

- `semantic_assertion` phantom table after reader audit.
- Unwired Phase E operational controls until a real caller exists.
- Dagster/Neo4j/RDF/XTDB/dedicated vector database in v1; none is required by current bounded relational requirements.
- Hatchet-specific proof and pin apparatus only if an approved scheduler replacement occurs; preserve its callback-owned invariant assertions in backend-neutral form.

## Target architecture

1. **Command boundary:** routes validate/authenticate and call application commands. One ingestion handler owns OCFL write, conflict-safe source/work/membership transaction, `SourceIngested`, and dispatch intent. Corrections call one command that appends the event, computes descendant invalidation, schedules the generation, and records audit/pause state.
2. **Authority:** OCFL is the only byte store. PostgreSQL is the only semantic and operational authority. Entity maps are reducer/replay outputs, not resolver side effects. Derived objects either become OCFL objects with Postgres refs or are explicitly documented as reconstructible refs-only evidence.
3. **Execution:** keep `StageManifest` and deterministic keys excluding `job_id`; claim before side effect; retain bounded retry/quarantine/cancel/reclaim; make stage-produced semantic events part of the deterministic completion transaction or deterministic keyed sub-events.
4. **Lineage:** retain the nine logical stages and one `STAGE_DEPENDENCIES` source. Hatchet registers one native workflow with nine durable tasks and exact parents. Static selective rerun may remain initially, but measure O(9) replay cost before adding dynamic workflow variants.
5. **Projection:** Tier-0 remains same-transaction. Tier-1 uses one writer per projection, durable checkpoint and blue/green/incremental rebuild; no ordinary per-job global wipe. Consistency tokens distinguish transient lag from rebuild-in-progress.
6. **Security/deployment:** API/worker image remains one product image; sandbox remains a bounded subprocess/optional hardened role. Route all genuinely untrusted parsers through it. Wire OCFL health/readiness. Keep optional model/object-store profiles out of the base path.

## Migration sequence

1. Repair and test one ingestion command path, membership insertion, conflict-safe dedup, and OCFL readiness.
2. Wire correction/override/invalidate APIs to `JobService`; repair segment-to-source rerun and add HTTP-only selective-rerun E2E.
3. Define stage side-effect atomicity/keying and make quarantine/evidence/artifact ownership explicit.
4. Convert entity-map state to reducer-derived replay output; verify Tier-0/Tier-1 checksums including maps.
5. Replace global projection wipes with serialized or incremental checkpointed rebuilds.
6. Route EPUB/PDF/text-risk parsing through the sandbox and prove capability/readiness behavior.
7. Deduplicate manifest builders/status folds; split backend-neutral contract tests from Hatchet adapter tests.
8. Re-run hosted native-DAG proof: exact nine tasks/parents, delayed-parent ordering, assignment, callback-owned rows, duplicate convergence, restart/reclaim, cancel/retry/quarantine, selective rerun, and identity agreement.
9. Only then consider removing/deprecating unwired infrastructure or changing the scheduler through a separately approved architecture decision.

## Explicit disposition table

| Finding / subsystem | Category | Disposition |
|---|---|---|
| OCFL source bytes/fixity | FAITHFUL NECESSITY | KEEP |
| Semantic ledger + append-only trigger | FAITHFUL NECESSITY | KEEP |
| Shared Tier-0 reducer | FAITHFUL NECESSITY | KEEP |
| In-repo DAG and invalidation planner | FAITHFUL NECESSITY | KEEP |
| Hatchet native nine-task adapter | IMPLEMENTATION CHOICE | KEEP conditionally |
| Hatchet four-service/proof apparatus | TEST-COUPLED COMPLEXITY | KEEP while Hatchet is approved; contain |
| Dead `IngestionCommandHandler` vs live route | DUPLICATE COMMAND PATH | REPAIR to one path |
| Event-only correction/invalidation routes | MISSING GUARANTEE | REPAIR |
| Segment rerun id mismatch | IMPLEMENTATION DRIFT | REPAIR |
| Unkeyed stage events / separate transactions | MISSING GUARANTEE | REPAIR |
| `current_entity_map` side-effect authority | DUPLICATE AUTHORITY | REPAIR |
| `semantic_assertion` no-writer schema | ACCIDENTAL COMPLEXITY | DELETE after audit |
| OCFL derived/artifact no production writer | MISSING GUARANTEE | DEFER or REPAIR by policy |
| Per-job global projection wipe | ACCIDENTAL COMPLEXITY | REPAIR |
| Text/EPUB/PDF sandbox bypass | MISSING GUARANTEE | REPAIR |
| Runtime Hatchet schema tenant discovery | IMPLEMENTATION DRIFT | CONTAIN / move to adapter proof |
| Unwired Phase E operations | PREMATURE INFRASTRUCTURE | DEFER, then DELETE if no consumer |
| Dagster/Neo4j/RDF/XTDB v1 additions | PREMATURE INFRASTRUCTURE | DELETE/DEFER |
| Temporal | IMPLEMENTATION CHOICE | DEFER |
| PostgreSQL queue | IMPLEMENTATION CHOICE | DEFER pending explicit DD amendment |

## Material open questions

1. Does hosted run `33312774348` prove delayed-parent dispatch ordering, or only registration/assignment/callback completion? The release gate must retain a direct ordered-parent probe.
2. Is derived evidence required to be byte-retrievable from OCFL, or is refs-only evidence an accepted v1 policy? Decide before deleting or implementing the derived writer.
3. Are any hidden readers/runbooks dependent on `semantic_assertion`, `current_entity_map`, or unwired Phase E operations? Complete a reader/runbook audit before deletion.
4. Should stage-produced semantic events be included in the single completion transaction, or use deterministic child keys plus an orphan reconciler? The choice must preserve exact provenance and effective-once semantics.
5. What is the accepted concurrency model for a shared Tier-1 current projection: incremental application, serialized rebuild, or blue/green generation swap?
6. Are worker and profile-gated `sandbox-runner` ever started together? If so, both registering the same workflow must be intentional and included in assignment/concurrency proof.
7. Can tenant eligibility and Hatchet internal-schema discovery be moved entirely to deployment-time, leaving the application adapter independent of third-party schema details?

## Final recommendation

**Keep the current authority architecture and retain Hatchet as the conditional v1 dispatch/barrier layer; do not replace it with Temporal or add a second scheduler.** Treat the green hosted run as the regression floor and continue requiring native-DAG proof. Spend the next architecture/implementation effort repairing the live command and transaction boundaries, making all state replayable, eliminating global projection rebuild races, and completing the sandbox boundary. Preserve a documented PostgreSQL-queue fallback, but activate it only through an explicit DD amendment if Hatchet's proven native barrier/lease contract cannot be maintained.
