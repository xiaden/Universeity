# Universal Media Decomposer CI Repair and Release-Gate Restoration

**Status:** Proposed  
**Author:** R&D  
**Date:** 2026-08-28  
**Scope:** Repair the production execution boundary and hosted validation exposed by GitHub Actions run `33164294061` on SHA `a6b1a62f8413655b9908b40e4fc7a484828364e0`. This document is a design, not an implementation plan, implementation claim, or release approval.

## Authoritative request and immutable ledger

The original request is preserved verbatim:

> Architectural repair required after failed GitHub Actions run 33164294061 on
> commit a6b1a62. Original user requirement: complete Task.md Universal Media
> Decomposer Definition of Done; do not trust contracts/docs/fixtures/stubs/
> green tests. Repair real production decomposition, durable async
> scheduling/restart/retry/cancel/selective rerun/invalidation, real
> modality/semantic work, public API heterogeneous correction E2E, and GitHub
> Actions Docker/Compose/container validation. No stubs, weakened gates, silent
> skips, or test doubles as release evidence. Preserve immutable OCFL source,
> provenance, evidence/semantic separation, append-only authority, stable
> locators, multilingual/adaptation individuality, selective descendant
> invalidation. Capability statuses must distinguish
> active/reference-only/configured-unavailable/gated/disabled. Docs only after
> behavior exists; final DoD classify PASS/FAIL/GATED with no unresolved FAIL.

The binding ledger is:

- **R1:** Complete Task.md's Universal Media Decomposer Definition of Done.
- **R2:** Do not trust contracts, docs, fixtures, stubs, or green tests as proof.
- **R3:** Repair real production decomposition, durable async scheduling,
  restart, retry, cancel, selective rerun/invalidation, real modality/semantic
  work, public heterogeneous correction E2E, and GitHub Actions Docker/Compose
  validation.
- **R4:** No stubs, weakened gates, silent skips, or test doubles as release
  evidence.
- **R5:** Preserve immutable OCFL source, provenance, evidence/semantic
  separation, append-only authority, stable locators, multilingual/adaptation
  individuality, and selective descendant invalidation.
- **R6:** Capability statuses distinguish `active`, `reference-only`,
  `configured-unavailable` (the repository contract also calls this
  `configured-but-unavailable`), `gated`, and `disabled`.
- **R7:** Documentation follows behavior; final DoD is classified PASS/FAIL/GATED
  with no unresolved mandatory FAIL.
- **R8:** Execute the complete formal workflow with no skipped stages.
- **R9:** Cross-check each repair against Task.md, the parent DD, contracts, and
  plans.
- **R10:** Produce a formal DD and implementation plan, explicitly separate
  product implementation from CI remediation, and identify exact live Hatchet
  topology/compatibility evidence.
- **R11:** This R&D stage edits design artifacts only; it does not edit
  production code.
- **R12:** Return paths, risks, and Exec-Manager gates.

### Ledger conformance commitments

| Ledger item | This DD preserves it by | Required closing evidence |
|---|---|---|
| R1 | Treating GitHub-hosted execution, not local checks, as the release authority. | Pushed SHA, retrieved logs/JUnit/diagnostics, and inspected release summary. |
| R2 | Repairing dependencies, deployment, runtime wiring, and gate mechanics; forbidding stubs, fake readiness, silent skips, and weakened assertions. | Failure-specific hosted evidence plus fail-closed live gate. |
| R3 | Mapping repairs to the complete Task.md DoD and retaining real modalities, async DAG, provenance, edits, invalidation, and public E2E. | DoD 1–35 matrix below and hosted heterogeneous correction scenario. |
| R4 | Making Hatchet the only v1 scheduler and requiring real callback execution. | Engine-visible registration and callback-owned Postgres/OCFL evidence. |
| R5 | Preserving Support → DD → plan → Exec-Manager → GitHub evidence routing. | Provenance paths and Exec-Manager handoff below. |
| R6 | Classifying local green/static results as context only. | Hosted reports on the pushed repair SHA. |
| R7 | Deferring docs until behavior is proven and requiring no unresolved mandatory FAIL at release. | Post-green docs commit and final matrix with no mandatory FAIL. |
| R8 | Requiring all formal stages and final review/rerun; no stage is silently omitted. | Complete process log, QA review, repair cycle, and rerun artifacts. |
| R9 | Cross-checking Task.md, parent DD, contracts, handoff, and Plans G/H/I/J. | Source-artifact list and per-item DoD evidence rows. |
| R10 | Separating product and CI streams while specifying exact Hatchet topology/proofs. | Path-scoped implementation review and same-stack compatibility evidence. |
| R11 | Limiting this deliverable to the formal DD artifact. | No production/test/workflow/plan/ADR edit by this authoring stage. |
| R12 | Defining risks, rollback/drain rules, and Exec-Manager gates. | Hosted release summary and final handoff acceptance. |

Additional binding constraints are C1–C8 from the design layer:

- **C1:** Hatchet is the sole v1 scheduler. Real worker callback registration and
  real stage execution are release gates; no second scheduler or in-process
  double may provide release evidence.
- **C2:** Release CI is managed by pushing to GitHub and retrieving its reports;
  local validation is context only.
- **C3:** `CapabilityReporter.report()` never reports `active` without verified
  live connectivity and an observed reason/version.
- **C4:** `hatchet-sdk==1.38.1` with server `v0.105.2` is CANDIDATE/PENDING.
  It may be promoted only after a real pull, connect, register, and execute
  test. Any upgrade changes both surfaces in lockstep, creates a new DAG
  universe, and drains old work.
- **C5:** The three live Hatchet shape tests must use a real executor and real
  SDK client. They may not be made green by weakened assertions or skips. The
  primary live evidence is the public HTTP-only duplicate/restart/retry/
  consistency scenario.
- **C6:** Worker readiness requires the real SDK loop and bound callbacks. The
  line `worker ready: registered N Hatchet workflows (candidate, pending Plan J
  live validation)` is emitted immediately before the blocking `start()` and
  remains candidate evidence until live proof.
- **C7:** `HATCHET_COOKIE_SECRET` and `HATCHET_MASTER_KEY` remain required
  `${VAR:?}` Compose interpolations; missing values fail configuration.
- **C8:** Product repair and CI/environment remediation are separate reviewable
  streams even when atomic landing is required.

## Problem statement and current evidence

Run `33164294061` is the authoritative baseline for what it actually executed:

| Surface | Result | Evidence |
|---|---|---|
| Ruff | PASS | Hosted job `98825909969` |
| strict mypy | PASS | 173 source files |
| Unit | FAIL: 1 | Job `98825910133`, artifact `9682936266` |
| PostgreSQL | FAIL: 14; 550 passed, 17 skipped | Job `98825910085`, artifact `9682972550` |
| Docker E2E | FAIL before startup | Job `98825909849`, artifact `9682930252` |

The concrete failures are independent: missing `python-multipart`, missing
FFmpeg, missing PostgreSQL-17 client tools, missing required Compose variables,
and denial of the top-level Hatchet image path. Independently, the API still
wires `DurableDAGRunner`, the worker has a duplicate/degraded runtime assembly,
the capability report has no live probe, and the Docker live path is opt-in.
The raw Docker step-6 log was unavailable during diagnosis; this DD does not
invent its contents. The hosted denial proves denial of that requested image
reference, while corrected topology boot and SDK/server compatibility remain
unproven until a new hosted run.

The current release state is **not release-ready**. Historical static/local
results, fixtures, recording clients, and synchronous seams identify defects or
provide hermetic coverage only; they do not close the live gate.

## Goals and non-goals

### Goals

1. Make the existing production API dispatch the real nine-stage DAG through
   Hatchet, with real modality work and callback-owned durable completion.
2. Preserve OCFL immutability, stable locators, evidence/semantic separation,
   append-only Postgres authority, provenance, multilingual and adaptation
   individuality, and descendant-only invalidation.
3. Prove durable asynchronous scheduling, retry, cancellation, duplicate
   idempotency, restart/resume, selective rerun, and consistency behavior.
4. Restore a native hosted Docker/Compose release gate that cannot pass by
   omission, skip, fake readiness, or test double.
5. Publish documentation and a final PASS/FAIL/GATED matrix only after behavior
   and hosted evidence exist.

### Non-goals

This repair does not redesign the parent UMD semantic architecture, add a
second scheduler, make Hatchet Lite the release topology, make the graph store
authoritative, or create an ADR. Split-job CI (B) is deferred until the single
mandatory live path is green.

## Selected architecture: A + minimal C, with B after green

### A — fail-closed commit-and-wire / prove-first (selected primary)

The repair lands the real product wiring and the environment fixes as one
reviewable release boundary. The API's release factory selects
`ProductionDAGRunner`; `DurableDAGRunner` remains a hermetic executor-facing
seam/test driver and is structurally unable to produce scheduler `active`.
One shared runtime assembly is consumed by both API and worker and includes the
Postgres repositories, OCFL store, semantic ledger/commands, real stage
registry, provider/modality bindings, sandbox, artifact store, replay/projection
builders, and observability.

The product flow is:

```text
HTTP /v1 mutation
  -> JobService command
  -> ProductionDAGRunner
  -> Hatchet adapter / engine queue (sole scheduler)
  -> registered umd-<stage> callback
  -> DurableStageExecutor claim-before-side-effect
  -> real StageWorkRegistry work
  -> OCFL/Postgres/semantic command ownership paths
  -> atomic stage_run + StageCompleted + audit
  -> HTTP status/query with provenance and consistency metadata
```

`StageWorkRegistryFactory.build(runtime)` must compose every stage in
`STAGE_ORDER`; an absent stage is `ConfigurationError`, never successful
completion. Text, raster, audio, video, and independent subtitle branches use
the existing real implementations and sandbox boundary. Provider-unavailable
paths emit an honest named capability/warning and do not fabricate evidence or
semantic identity.

### Minimal C — prove-then-run tripwire (folded into A)

Before Compose startup, CI runs `docker manifest inspect` (or equivalent exact
reference inspection) for each selected split image and records the reference
and digest where available. This is a fast diagnostic tripwire for the observed
403 class, not functional evidence, not a scheduler, and not a replacement for
pull, boot, callback execution, public E2E, retry, or restart proof.

### B — split-job CI (post-green complement only)

After A has a green hosted run, CI may separate fast lint/unit/Postgres
feedback from the full live job. The live job remains required and exhaustive:
no trigger-level path filter may suppress it on protected branches, and an
always-running aggregate gate must fail on live-job skip or failure. Shared
build caching may reduce duplicate startup cost. B is not a substitute for A.

### Rejected alternatives

- **CI-only provisioning / deferred product wiring:** rejected because it can
  leave the API on `DurableDAGRunner` while claiming a green release.
- **Opt-in, skip, recording-client, or weakened-assertion evidence:** rejected
  under R2/R4; a permitted local/provider gate cannot mask the mandatory live
  path.
- **Hatchet Lite in CI:** rejected as release evidence. Lite has different
  service topology, ports, configuration, auth, and operational behavior; it
  would prove a different scheduler surface than the full production stack.
- **Second scheduler, Dagster, Temporal, or a hand-rolled production queue:**
  rejected for v1 by C1. The repository DAG is lineage authority; Hatchet is
  scheduler authority.

## Exact Hatchet topology and compatibility obligations

The release target is one same-stack full topology, not the current single
`hatchet` service and not Lite:

```text
hatchet-migrate
  -> hatchet-admin / setup-config (shared generated config)
  -> hatchet-engine (gRPC engine; official split container defaults to 7070)
  +-> hatchet-dashboard (official split container port must be verified; host
      mapping may expose 8080)
  + UMD db (PostgreSQL), api, worker, sandbox-runner
```

The implementation must use the exact v0.105.2 sub-path image references
(`hatchet-migrate`, `hatchet-admin`, `hatchet-engine`, and
`hatchet-dashboard`) selected from the pinned release, shared config volume,
correct database/message-queue settings, health/order dependencies, required
secret interpolation, and a real tenant JWT. The exact tag-specific variable
names, token command, dashboard container port, broadcast address, and digest
are **PROVISIONAL** until the tag is booted on hosted CI; current official docs
and registry checks are reference evidence only.

The candidate SDK/server pair is:

```text
hatchet-sdk==1.38.1  <->  server v0.105.2
```

The adapter must pre-align to the documented SDK v1 surface: task handler
`(input, context)`, serializable `StageManifest` input, and the supported
`Workflow.run(input)` / `runs.create` submission shape. The live run must
observe and prove:

1. Both SDK and all split images pull, with exact digests recorded.
2. Migration/config generation and engine health succeed.
3. A valid JWT is minted after config generation and is accepted by API,
   worker, test runner, and probe.
4. `client.task(...)` bindings are non-empty and engine-visible; `umd-<stage>`
   names match submitted runs without unexpected namespace rewriting.
5. gRPC `host_port` routes from worker, in-network test runner, API probe, and
   submission path to the engine, not the dashboard.
6. The documented submission method accepts the manifest payload and invokes
   the two-argument handler on this exact pair.
7. A real submission produces callback-owned `stage_run`, `StageCompleted`, and
   operational audit rows; a readiness line or version ping alone does not.
8. Retry, cancellation, duplicate, restart, persistence, and DAG-universe
   drain/rekey behavior pass on the same stack.

Worker construction is explicit: register every canonical task, create
`client.worker("umd-worker", workflows=handle.registered_workflows)`, and call
the returned worker's blocking `start()` exactly once. Emit the candidate
readiness line immediately before that call with `flush=True`; validate
engine-visible registration and callback rows separately. Missing SDK, URL,
token, registry entries, or bound executors exits non-zero and never claims
ready.

## Durable state, retry, cancellation, restart, and invalidation

- **Submission:** `ProductionDAGRunner` submits one queued Hatchet run per
  canonical stage with job/source/stage/DAG-universe/causation and serialized
  manifest. Persist queued stage state (or an equivalent durable state record)
  before status reconciliation so a queued job cannot regress `RUNNING ->
  PENDING` merely because its callback has not arrived.
- **Completion:** only `DurableStageExecutor` may complete a stage. It claims
  the unique idempotency key before side effects and atomically persists
  artifact/evidence refs with `StageCompleted`; terminal `COMPLETE` is never
  inferred from submit response or a log line.
- **Retry:** executor `RetryPolicy` owns bounded transient retry/backoff and
  deterministic quarantine. Hatchet task retries are zero (or deterministic
  failures are explicitly non-retryable) to prevent multiplied attempts and
  duplicate quarantine records.
- **Cancel:** callbacks read persisted job/stage cancellation before work.
  Whole-job cancellation stops future scheduling; stage cancellation closes
  the transitive descendant set while retaining committed ancestors.
- **Restart/resume:** `stage_run`, `job_run_audit`, semantic events, projections,
  and OCFL bytes survive API/worker `stop`/`start`. A completed idempotency key
  returns replayed/no-op without repeating expensive work; claimed/incomplete
  work may be reclaimed; failed late stages retry without repeating successful
  ancestors.
- **Selective rerun/invalidation:** `STAGE_DEPENDENTS` and
  `InvalidationPlanner` are the sole lineage authority. Corrections invalidate
  only dependent descendants; unaffected segment/evidence/artifact IDs and
  source checksums remain stable. A changed SDK/server contract creates a new
  DAG universe, drains/cancels old in-flight runs, and prevents cross-universe
  aliasing.
- **Consistency:** mutation responses return read-your-writes tokens. Tokened
  reads wait only within the bounded budget; otherwise they return structured
  `503` with `Retry-After` and `x-consistency: transient-lag` or
  `rebuild-in-progress`, never stale post-correction data.

## Capability statuses and evidence tiers

The API exposes scheduler, worker, provider, and sandbox capability states as
`active`, `reference-only`, `configured-but-unavailable`/`configured-unavailable`,
`gated`, or `disabled`, with owner/reason/version. `active` for the scheduler
requires both the `ProductionDAGRunner` wiring and a successful cached,
background, hysteretic gRPC reachability probe. The probe is disclosure only;
real callback transitions and persisted rows prove execution. It must not be a
per-request blocking network call. Local no-server/no-SDK behavior is an honest
gated or configured-unavailable state, never release evidence.

Evidence authority is explicit:

1. **Hosted release evidence (authoritative):** pushed SHA, GitHub logs/JUnit,
   Compose/service/DB/OCFL observations, image digests, capability snapshots,
   and machine-readable release summary retrieved from GitHub.
2. **Local repository evidence (context):** source, tests, contracts, static
   checks, and local Postgres/provider runs used to diagnose and develop only.
3. **Technology/reference evidence (non-execution):** dated official docs,
   package metadata, registry probes, and research citations used to justify
   candidate choices only.

## Product and CI/remediation streams

The streams remain separate in plan ownership, review, and path-scoped commits;
they may land atomically where separation would otherwise commit a bypass.

### Product implementation stream

- Reuse one full runtime assembly for API and worker.
- Wire `ProductionDAGRunner` in the release API factory and preserve queued,
  callback-owned status.
- Align Hatchet v1 handler/submission/client surfaces and bind every callback
  to the real registry and executor.
- Add truthful capability probe and test status transitions.
- Preserve executor-only retry/quarantine, cancellation, idempotency, restart,
  provenance, semantic ledger, projections, and descendant invalidation.
- Switch live boundary tests to external HTTP; retain `TestClient` only for
  hermetic tests. No live test may instantiate `create_app()` or reach an
  internal repository/ledger/projection.

### CI/environment remediation stream

- Commit `python-multipart==0.0.32`, hosted FFmpeg/ffprobe, PGDG
  `postgresql-client-17` plus `UMD_PG_BIN`, and required Compose-secret exports.
- Replace the denied top-level image with the full split topology; preserve
  `${HATCHET_COOKIE_SECRET:?}` and `${HATCHET_MASTER_KEY:?}`.
- Build the worker-capable image (`.[worker]`) and smoke-test the SDK import;
  installing it does not promote the candidate pair.
- Mint a real JWT after config generation and pass canonical in-network engine
  routing to worker and test runner.
- Remove `UMD_VALIDATE_LIVE_WORKER` and any `db api`-only default. Start the
  full stack unconditionally on the mandatory live path.
- Run live tests in a test container on the Compose network (or a proven
  equivalent), with tests/dev dependencies and modality tools available.
- Capture diagnostics with `if: always()`, preserve named volumes through
  restart, and tear down with `down -v` only after evidence collection.

## Affected layers, APIs, dependencies, and migration

The repair changes wiring across the API/application layer (`app.py`,
`JobService`), scheduler adapter and worker (`runner.py`, `hatchet.py`,
`production.py`, `stage_execution.py`, `deploy/cli.py`), capability reporting,
the deployment layer (`compose.yaml`, `Dockerfile`, runtime pins), and hosted
workflow/scripts/tests. Semantic ownership does not change: OCFL owns immutable
source and derived bytes; PostgreSQL owns descriptors, stable segments,
evidence references, stage/job state, append-only semantic events, current
state, and audit; projection builders alone write projections.

The public `/v1` contract remains versioned REST: source ingest and metadata,
segments/evidence/locators, jobs/status/report, retry/cancel/rerun/invalidate,
entities/claims/overrides/locks, alignment, semantic and structured query,
search, audit, health/readiness/capabilities/version. Submission remains
asynchronous and returns identifiers plus consistency metadata; no internal
repository or ledger call is a release-test substitute. RFC 7807 errors,
pagination, stable IDs, and read-your-writes semantics remain in force.

The required durable schema path includes the existing idempotent migration
through `0007`, including `stage_run.evidence_refs`. Rollout must first deploy
the schema compatible with callback-owned completion, then deploy API/worker
wiring and the paired Hatchet topology. A new SDK/server pair is a coordinated
rollout, not a package-only update: freeze new work on the old DAG universe,
drain/cancel old runs, activate both pins, and verify rekey isolation before
accepting new work.

## Testing and verification strategy

Hermetic tests cover SDK surface shapes, registry completeness, queued-state
reconciliation, claim/idempotency, retry/quarantine, cancellation, restart
replay, capability hysteresis, and projection ownership. Public-boundary tests
use only HTTP in live mode and cover real TXT/Markdown, raster, audio, video,
and independent subtitle sources, multilingual/adaptation differences,
provenance, semantic/structured query, correction, descendant invalidation,
selective rerun, consistency, duplicate submission, retry, and restart.

The hosted gate runs lint/type/unit/Postgres checks, exact image preflight,
native Compose boot and migrations, worker registration, the live shape suite,
the HTTP-only scenario, stop/start persistence, and final artifact capture.
Optional provider/legal/platform gates are named and observable; they cannot
replace mandatory modality or scheduler proof. A skipped mandatory test is a
failure, not a pass.

## Hosted sequencing and release evidence

1. Exec-Manager scopes and implements the approved plan; review the exact diff
   and push a commit. Record SHA, run URL, job IDs, and attempt.
2. Run hosted lint, strict type, unit, and Postgres jobs with declared native
   dependencies; failures remain failures.
3. Run exact image preflight, record digests, build the worker-capable image,
   and verify the negative missing-SDK path remains honest.
4. Start migrate/config/admin/engine/dashboard plus UMD DB/API/worker/sandbox
   on the hosted runner's native Docker engine. No DinD or socket mount.
5. Wait for API and worker transport signals with bounded timeouts; additionally
   prove nonzero engine-visible registrations and warmed capability state.
6. Run live shape tests and the HTTP-only heterogeneous scenario. Require real
   text/image/audio/video/subtitle evidence, provenance, semantic and
   structured queries, correction, invalidation, selective rerun, duplicate,
   retry/quarantine, cancellation, and audit.
7. Perform API/worker `stop`/`start`, rerun restart assertions, and verify OCFL
   namaste/fixity, Postgres rows, no repeated committed ancestors, and DAG
   universe isolation.
8. Capture service logs, JUnit, coverage, DB dump, OCFL listing, capability and
   provider statuses, image digests, and `live-worker-gate: PASS|FAIL`.
9. Retrieve and inspect every GitHub artifact. A green check cannot override a
   failed/missing live summary or skipped mandatory evidence.
10. Only after behavior and hosted workflow pass, update docs and measured
    counts; then run final QA/adversarial review, repair findings through the
    same Support/design/plan/Exec route, and rerun the complete suite.

## DoD conformance matrix (current snapshot)

This matrix maps every Task.md §40 item. It is a release design and current
status report, not a claim that implementation is complete. Mandatory current
FAILs must be repaired and re-proven; they may not be converted to GATED by a
skip, stub, double, fake readiness, or weakened assertion.

| # | Requirement and closing evidence | Current status |
|---:|---|---|
| 1 | Adversarial technology/design process exists; T1–T8 artifact retrieved. | PASS |
| 2 | Implementation-ready DD and downstream plan exist. | PASS |
| 3 | Implemented service is identified by pushed Exec SHA and hosted reports. | GATED |
| 4 | Persistent OCFL source storage and fixity survive hosted restart. | GATED |
| 5 | Real text/book ingestion through public API yields segments/evidence. | FAIL |
| 6 | Real image ingestion yields OCR/regions/locators. | FAIL |
| 7 | Real audio ingestion yields timing/ASR/provider evidence or named permitted gate. | FAIL |
| 8 | Real video/container path runs with FFmpeg and preserves tracks/scenes. | FAIL |
| 9 | Stable addressable segments and locator retrieval work publicly. | GATED |
| 10 | Evidence resolves to immutable bytes and generated-by metadata. | GATED |
| 11 | Semantic assertions retain support, confidence, and uncertainty. | GATED |
| 12 | Multilingual realizations remain distinct in one work/graph. | GATED |
| 13 | Adaptation and continuity boundaries/differences remain explicit. | GATED |
| 14 | Many-to-many cross-source alignment is persisted and queryable. | GATED |
| 15 | Entity resolution is reversible with merge/split history. | GATED |
| 16 | User overrides have precedence and provenance. | GATED |
| 17 | Segment edit/split/merge is public and historied. | GATED |
| 18 | Semantic edit/override/invalidate/lock operations are public and historied. | GATED |
| 19 | Invalidation is descendant-only and preserves unaffected outputs. | GATED |
| 20 | Individual stages rerun through the durable path. | GATED |
| 21 | Async Hatchet jobs survive API/worker restart without repeating committed work. | FAIL |
| 22 | Structured locators resolve bounded source-native representations. | GATED |
| 23 | Semantic KG-style questions return typed provenance-bearing answers. | GATED |
| 24 | Structured graph/query API returns deterministic bounded results. | GATED |
| 25 | Answers expose retrievable supporting evidence/source references. | GATED |
| 26 | Audit/history explains current, prior, actor, evidence, and cause. | GATED |
| 27 | Model/provider interfaces are swappable and capability-reported. | GATED |
| 28 | Local/self-hostable model path is actually supported where required. | GATED |
| 29 | Hosted tests cover heterogeneous and contradictory multi-source media. | FAIL |
| 30 | Hosted HTTP-only correction → invalidation → selective rerun passes. | GATED |
| 31 | Native Docker/Compose deployment and full Hatchet topology work. | FAIL |
| 32 | Repair SHA passes lint/type/static checks. | GATED |
| 33 | Hosted automated suite passes with no hidden mandatory skips. | FAIL |
| 34 | Final adversarial code review covers all twelve specified risk areas. | GATED |
| 35 | Findings are repaired and complete validation is rerun. | GATED |

There is no release approval while any mandatory row is FAIL. Optional provider,
legal, platform, or model gates may remain GATED only with a named owner,
reason, status, proof command, and visible hosted summary.

## Risks, open questions, and mitigations

| Risk/open question | Mitigation or decision gate |
|---|---|
| v0.105.2 config/token env surface differs from current docs | Inspect the pinned tag; make migration, config generation, token minting, and engine startup separate hosted steps; fail closed. |
| SDK 1.38.1/server v0.105.2 incompatibility | Keep CANDIDATE; prove pull/connect/register/execute. On failure, lockstep bump, new DAG universe, drain old work, rerun. |
| Handler/submission/name/port mismatch | Add hermetic SDK-shape tests, then use same-stack live observations; do not weaken polling/assertions. |
| Invalid JWT or broadcast address | Mint after config generation, verify `ey` token and engine route from every client surface, reissue after address changes. |
| Queued status regresses to PENDING | Persist queued stage rows or equivalent durable state before refresh; terminal state remains callback-owned. |
| Hatchet and executor retry amplification | Hatchet retry zero; executor is sole retry/quarantine authority; assert effective-once completion. |
| Worker runtime differs from API runtime | One shared assembly; require every canonical stage and real modality dependency; absent work is configuration failure. |
| Live test container cannot reach services or lacks media tools | In-network runner, `.[dev,worker]`, tests mounted/copied, FFmpeg/sandbox profile verified before gate. |
| Capability probe flaps or claims execution | Cached background gRPC reachability with hysteresis; only persisted callback execution can close the gate. |
| Required gate is skipped by workflow conditions | No live-path opt-in or trigger path filter; always-run aggregate gate fails on skip; named allowlist only for permitted optional providers. |
| Product/CI changes become unreviewable | Explicit path-scoped commits and diff review; never `git add -A`. |
| Docs drift or claim unavailable behavior as active | Docs-after-behavior hard gate; derive counts/statuses only from retrieved hosted evidence. |

## Rollback, drain, and stop rules

Stop the release if a mandatory step is missing, skipped, log-only, double-only,
or failed; if the API falls back to the durable seam in hosted release; if
callbacks do not persist authoritative rows; if the worker has zero real
bindings; if volumes are wiped during restart; if live E2E constructs an
in-process app; or if required secrets/assertions are weakened. Preserve all
diagnostics before cleanup. Roll back or isolate a failing commit only after
capturing evidence, never by reintroducing an opt-in gate or converting failure
to skip.

Any SDK/server change is a coordinated migration: stop accepting new work on
the old universe, drain or cancel in-flight old-universe runs, persist the new
universe identifier, activate the paired versions, and prove no cross-universe
idempotency aliasing. During ordinary test restart use Compose `stop`/`start`,
not `down -v`; final teardown may remove volumes only after evidence upload.

## Exec-Manager gates and handoff

Exec-Manager must derive a bounded implementation plan from this DD, keep the
product and CI streams reviewable, and execute through the full QA/fixer cycle.
Before declaring completion it must:

1. Re-read the current source and Plans G/H/I/J; resolve stale handoff notes
   against the tree rather than trusting fixtures or comments.
2. Land the gate flip, probe, fail-on-skip mechanism, live HTTP transport, and
   product wiring together so no intermediate pushed state can be green by
   omission.
3. Push every candidate to GitHub, retrieve and inspect all reports/artifacts,
   and record exact image digests and candidate pin outcome.
4. Keep Hatchet as the only release scheduler and ensure `active` is impossible
   for the durable hermetic seam.
5. Preserve volumes during restart segments and collect failure evidence with
   `if: always()` before teardown.
6. Route every finding requiring behavior change through the plan/Exec path;
   do not use Exec-Fixer to hide architectural or gate defects.
7. Run docs only after behavior/workflow evidence passes, then complete fresh
   security, test, documentation, health, and adversarial review and full rerun.

The required handoff is:

```text
Support-Librarian/Researcher/Debugger
  -> this DD
  -> Exec-Planner implementation plan
  -> Exec-Manager + QA/fix cycles
  -> pushed GitHub SHA and hosted evidence
  -> final DoD matrix with no unresolved mandatory FAIL
```

## Provenance and source artifacts

The design was reconciled against these durable inputs:

- `Task.md` (complete §§1–41, especially §40 items 1–35).
- `artifacts/designs/pending/DD-universal-media-decomposer.md`.
- `artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-ci-repair.md`
  (complete Refiner T1–T8; agent `mid-gray-pigeon`).
- `artifacts/designs/process/universal-media-decomposer-ci-repair-librarian.md`
  (agent `promising-black-lemming`).
- `artifacts/designs/process/universal-media-decomposer-technology-research.md`
  (Researcher agent `critical-magenta-jackal`).
- `artifacts/designs/process/universal-media-decomposer-ci-repair-debugger.md`.
- `artifacts/designs/process/universal-media-decomposer-ci-repair-architect-stage.md`
  (agent `accused-aquamarine-antlion`).
- `artifacts/designs/process/universal-media-decomposer-ci-repair-complexity-review-t8.md`
  (agent `intact-brown-roundworm`).
- `artifacts/designs/process/universal-media-decomposer-ci-repair-final-estimate.md`
  (agent `crude-violet-koala`; LARGE, low confidence, plan required).
- `artifacts/designs/process/universal-media-decomposer-ci-repair-pattern-enforcer-approval.md`.
- `artifacts/designs/parts/universal-media-decomposer/CONTRACTS.md` §§58–63.
- `artifacts/designs/parts/universal-media-decomposer/HATCHET_LIVE_VALIDATION_HANDOFF.md` §§1–8.
- `artifacts/plans/pending/TASK-universal-media-decomposer-G-production-runner-api.md`.
- `artifacts/plans/pending/TASK-universal-media-decomposer-H-local-providers-modalities.md`.
- `artifacts/plans/pending/TASK-universal-media-decomposer-I-hatchet-worker-integration.md`.
- `artifacts/plans/pending/TASK-universal-media-decomposer-J-api-boundary-ci-release.md`.
- `artifacts/plans/handoff-G-to-I-J.md`.
- `.github/workflows/validation.yml` and `.github/scripts/{wait-for-http.sh,wait-for-worker.sh,capture-diagnostics.sh,record-release-summary.sh}`.
- `deploy/compose.yaml`, `deploy/Dockerfile`, `deploy/pins/runtime.txt`, and `pyproject.toml`.
- `src/umd/api/app.py`, `src/umd/application/jobs.py`, `src/umd/jobs/{runner,hatchet,capability,production,stage_execution}.py`, and `src/umd/deploy/cli.py`.
- `tests/test_api_boundary_e2e.py`, `tests/test_api_boundary_guardrails.py`,
  `tests/test_hatchet_live.py`, `tests/test_capability_transitions.py`,
  `tests/conftest.py`, `tests/fixtures.py`, and `tests/test_deployment_phaseE.py`.

Hosted baseline: <https://github.com/xiaden/Universeity/actions/runs/33164294061>,
jobs `98825909969`, `98825910133`, `98825910085`, `98825909849`, and artifacts
`9682936266`, `9682972550`, `9682930252`.

No production code, tests, workflow, configuration, implementation plan, or ADR
is created or changed by this DD authoring step.
