# Universal Media Decomposer CI Repair — Architecture and Tradeoff Options

**Status:** `BLOCKED_FOR_ADVERSARIAL_COMPLETENESS` (provisional options report)  
**Date:** 2026-08-28  
**Author:** `rnd-architect`  
**Scope:** Repair strategies for hosted validation run `33164294061` and restoration of the release gate. This is **not** the original Universal Media Decomposer system architecture.  
**Implementation status:** Read-only analysis. No production, test, workflow, plan, or documentation implementation was performed by this report.

## Completeness block

The required adversarial input is incomplete. `artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-ci-repair.md` contains the eight-turn process description and T1 material, but no material sections for T2, T3, T4, T5, T6, T7, or T8. A repository search finds only the T1 approach section and references to the planned turns. Therefore this report cannot claim a completed T1–T8 adversarial gate or final architectural approval.

The options and provisional combination below are grounded in the debugger, technology research, pending repair DD, support-librarian briefing, existing plans/handoff/contracts, and the available T1 analysis. They must be re-checked after T2–T8 is restored or explicitly accepted as a process blocker.

## Immutable user request

> "instead of running a fixer, given the depth of issues found in CI, you should have made the decision to invoke support and then RnD to plan the repairs needed, then passed to Exec. fixer will make the CI green by stubbing. support will identify that something doesn't actually exist, RnD will plan it's implementation. this should all also be getting cross checked against task.md"

## Immutable repair ledger

| ID | Binding requirement | Design consequence |
|---|---|---|
| **R1** | Hosted GitHub push and hosted reports are mandatory. | Local checks can select or diagnose work, but cannot close the release gate. |
| **R2** | Repair real missing implementation/dependencies; no stubs, unconditional skips, fake readiness, or weakened assertions. | Every option must fail closed when the real path is unavailable. |
| **R3** | Cross-check every repair against the full `Task.md` DoD. | CI topology is subordinate to product behavior, provenance, restart, correction, and review obligations. |
| **R4** | Hatchet is the sole v1 scheduler; live callbacks and real stage execution are release gates. | `DurableDAGRunner` and recording clients remain hermetic seams only; they cannot produce release evidence. |
| **R5** | Support → R&D design → implementation plan → Exec-Manager. | This report creates no plan. The next artifact transition is a plan derived from the selected/approved strategy, then Exec-Manager execution. |
| **R6** | Local results are context only. | The authoritative evidence set is a pushed commit, a new hosted run, its logs/artifacts, and its release summary. |

## Evidence baseline

### What run 33164294061 actually proves

The debugger classifies the run as `DIAGNOSED` with `fixComplexity: NEEDS_PLAN`; it explicitly says this is not a single assertion typo and that fixer-only routing is unsafe (`universal-media-decomposer-ci-repair-debugger.md:11-15,162-172`). The hosted results were:

| Hosted surface | Result | Exact evidence |
|---|---:|---|
| Ruff lint | PASS | Job `98825909969` (`...-debugger.md:19-22`) |
| Strict mypy | PASS | `Success: no issues found in 173 source files` (`...-debugger.md:21-23`) |
| Unit tests | 1 failure | Job `98825910133`, artifact `unit-test-results` `9682936266` (`...-debugger.md:23-27`) |
| PostgreSQL integration | 14 failures | Job `98825910085`, artifact `postgres-test-results` `9682972550`; report `14 failed, 550 passed, 17 skipped` (`...-debugger.md:23-27`) |
| Docker E2E | Failed before startup | Job `98825909849`, artifact `docker-e2e-evidence` `9682930252` (`...-debugger.md:24-27,66-78`) |

The independent failure classes are:

1. **Runtime package/tool provisioning:** Starlette's exact `python-multipart` assertion, missing `ffmpeg`, and missing `/usr/lib/postgresql/17/bin/pg_dump` (`...-debugger.md:43-51`).
2. **Compose environment:** required `HATCHET_COOKIE_SECRET` interpolation failed because the variables were not exported in the jobs collecting the Compose test (`...-debugger.md:53-64`; `deploy/compose.yaml:101-111`).
3. **Registry/deployment:** the hosted daemon received `denied` while pulling `https://ghcr.io/v2/hatchet-dev/hatchet/manifests/v0.105.2`, before services became available (`...-debugger.md:66-78`). This proves a pull denial, not its underlying registry cause.
4. **Production integration:** `src/umd/api/app.py:52-54,167-168` injects `DurableDAGRunner`, while `src/umd/jobs/runner.py:263-296` defines the production Hatchet runner contract (`...-debugger.md:101-108`).
5. **Capability/release proof:** the capability reporter has no actual connectivity probe, and the public boundary test skips unless the live API reports an active scheduler/worker (`...-debugger.md:101-108`; `src/umd/jobs/capability.py:46-84`; `tests/test_api_boundary_e2e.py:108-137`).

There is an important evidence reconciliation: the handoff describes an earlier `_RecordingClient`/`executor=None` defect (`HATCHET_LIVE_VALIDATION_HANDOFF.md:184-202`), while the current committed `tests/test_hatchet_live.py:920-1006` uses a real client, a real executor, and polling. The current test shape is still unproven because no hosted live execution has passed. The strategy must not silently treat either a recording test or an unexecuted cluster-marked test as release evidence.

## Repair architecture common to all viable options

The repair is a coordinated boundary restoration, not a new media-system architecture. All viable options retain these ownership and execution boundaries:

```text
GitHub hosted runner
  ├─ static/package/native dependency jobs
  └─ native Docker/Compose release job
       ├─ API -> ProductionDAGRunner -> Hatchet
       ├─ worker -> real Hatchet task callbacks -> DurableStageExecutor
       ├─ Postgres stage_run/job_run_audit/semantic state
       └─ OCFL source/artifact volumes
```

Relevant existing surfaces and responsibilities are:

| Surface | Responsibility in the repair architecture |
|---|---|
| `.github/workflows/validation.yml` | Hosted job orchestration, native Compose execution, dependency provisioning, fail-closed evidence collection, and artifact upload. |
| `deploy/compose.yaml` | Pullable, explicitly pinned Hatchet topology; required secret interpolation remains required; API/worker/DB/OCFL volume relationships remain visible. |
| `deploy/Dockerfile` and `pyproject.toml` | Runtime image composition, including the worker's actual SDK/package requirements; host-only tools cannot be assumed to exist inside the image. |
| `src/umd/api/app.py` | Production application assembly. The release path must use the production scheduler seam rather than an interim synchronous runner. |
| `src/umd/jobs/runner.py` | `DAGRunner` seam and `ProductionDAGRunner.run_graph`; submission returns queued/durable state, never fabricated completion. |
| `src/umd/jobs/hatchet.py` | Pinned SDK adapter, workflow/task registration, callback binding to `DurableStageExecutor`, and submission-shape compatibility. |
| `src/umd/deploy/cli.py` | Worker assembly and the SDK worker loop; readiness is meaningful only after real callback registration and the actual loop starts. |
| `src/umd/jobs/capability.py` | Honest active/unavailable/gated status based on verified connectivity, not env-var presence alone. |
| `tests/test_hatchet_live.py` | Registration, callback, retry, cancel, duplicate, restart, late-failure, and DAG-universe evidence. Cluster tests are evidence only when executed against the real stack. |
| `tests/test_api_boundary_e2e.py` | HTTP-only heterogeneous ingestion, provenance, semantic query, correction, descendant invalidation, selective rerun, restart, and no-stale-read evidence. |
| `tests/conftest.py` and deployment tests | Matching PostgreSQL client/tooling and required Compose configuration checks. |
| `CONTRACTS.md:58-63` | Binding production runner, worker, registry, and capability contracts. |

No option may introduce a second scheduler, make a test-only double authoritative, remove a required secret, convert a mandatory test to an unconditional skip, or report `active` without a live reachable scheduler.

## Options

### Option A — Coordinated commit-and-wire repair

**Summary:** Restore the missing runtime/environment prerequisites and connect the existing production API, worker, capability, and hosted release surfaces as one coherent repair.

#### Architecture and data flow

1. The hosted jobs provision the dependencies exercised by their selected tests; the Compose-test jobs receive generated required secrets without changing the `${VAR:?}` contract.
2. The deployable API/worker image contains the dependencies required by each role, with worker packaging treated as a real image contract rather than inferred from the host test environment.
3. API submission enters `ProductionDAGRunner.run_graph`; it submits stage work to Hatchet and reports queued/running state. A worker task callback deserializes the stage manifest and invokes the real `DurableStageExecutor`.
4. Capability status is derived from a real scheduler connectivity check. The public HTTP E2E proceeds only when the API can honestly report the live production path.
5. The hosted Docker job starts the full required path by default, waits for real worker registration, runs the HTTP boundary and live scheduler assertions, preserves volumes during restart, captures evidence, and tears down only after evidence collection.

#### Integration surfaces

| Existing surface | Architectural role | Risk |
|---|---|---|
| Workflow + package/tool jobs | Make known dependencies reproducible at the test boundary | Medium: duplicate environment setup can drift between jobs. |
| Compose/Dockerfile/worker packaging | Make the stack that is tested the stack that can actually run | High: host success does not prove container composition. |
| `app.py` + `runner.py` | Replace interim release-path execution with the Hatchet submission seam | High: asynchronous status semantics must remain honest. |
| `hatchet.py` + `cli.py` | Bind every canonical stage to the durable executor and start the real SDK worker | High: SDK method/constructor/registration mismatches are live-only risks. |
| `capability.py` + boundary E2E | Prevent capability-gated skips from masking a missing production path | Medium: probe behavior must not create false readiness. |

#### Pros

- Repairs all confirmed defect classes in one causal architecture rather than making CI green around a missing product path.
- Minimizes topology changes; the existing contracts, production registry, durable executor, and HTTP-only E2E remain the center of gravity.
- Gives the strongest direct fit to R1–R4 and the `CONTRACTS.md:60-63` production execution contracts.
- Makes later hosted failures attributable: dependency, image, worker registration, callback, persistence, or API boundary.

#### Cons

- Highest coordination risk because workflow, image, API, worker, capability, and test evidence must agree in one hosted run.
- A single large release job may be slower and harder to diagnose than a split topology.
- It cannot prove the Hatchet SDK/server pair until a real pull, connect, callback, and restart cycle succeeds.
- A capability probe that is too broad or too eager could create a new false-positive readiness surface.

#### Choose when

Choose this as the base when the primary goal is to restore the actual release path with the fewest semantic seams and no change to what “release evidence” means.

### Option B — Split baseline and live jobs

**Summary:** Keep a fast hermetic/baseline validation job separate from a mandatory full-stack live release job, while retaining Option A's product and dependency repair inside the live path.

#### Architecture and data flow

- **Baseline job:** validates package installation, static checks, migration/Compose configuration, and tests that do not require a live scheduler.
- **Live job:** starts DB, API, Hatchet, worker, and required sandbox/provider surfaces; runs the real scheduler/callback tests and the public HTTP boundary; performs the explicit API/worker stop/start without deleting named volumes.
- Both jobs upload independent logs/JUnit/coverage/diagnostic artifacts. The live job remains a required status check; baseline green never substitutes for it.
- The same production runner, worker callback, capability probe, exact pins, and API evidence are shared across both surfaces.

#### Integration surfaces

| Existing surface | Architectural role | Risk |
|---|---|---|
| `validation.yml` | Introduce separate evidence ownership and required-check semantics | Medium: branch/path filters can accidentally make live proof optional. |
| Option A repair surfaces | Supply the actual application/runtime repair | High: B alone cannot repair API wiring or image validity. |
| Release summary/artifact naming | Keep baseline and live evidence distinct | Low/Medium: operators may read the wrong green job. |

#### Pros

- Faster feedback for ordinary changes and clearer attribution between baseline and live failures.
- Makes the release gate explicit: baseline is useful feedback; live is the non-substitutable proof.
- Reduces pressure to weaken the live job merely to preserve developer feedback speed.

#### Cons

- More workflow policy and duplicated setup.
- Path filters and required-check configuration can create a bypass if not fail-closed for API/jobs/worker/Compose changes.
- It is not a standalone repair: without Option A's real wiring and packaging, the live job still fails honestly.
- Two jobs can observe different dependency/image state unless pins and setup are centrally constrained.

#### Choose when

Choose this as a delivery refinement after the live architecture is understood, or when the repository needs fast baseline feedback without changing the mandatory live release definition.

### Option C — Prove-then-run registry/SDK preflight

**Summary:** Add a cheap, explicit preflight proof of the exact Hatchet image surfaces and SDK/server pair before invoking Compose, then run the same fail-closed live path.

#### Architecture and data flow

1. A hosted preflight resolves the exact pinned image references, checks registry pullability/authorization, and records immutable image-digest evidence before stack startup.
2. A dependency probe checks that the worker image and the declared SDK surface agree with the selected pair; it does not promote a pair to validated merely because versions are numerically contemporaneous.
3. Only after preflight passes does native Compose start. The live worker must register real callbacks and execute stages through the durable executor.
4. A failed preflight is a named release failure, not a skipped E2E or a passed baseline.

#### Integration surfaces

| Existing surface | Architectural role | Risk |
|---|---|---|
| `deploy/pins/runtime.txt`, Compose, worker package, adapter | One pair-agreement evidence set | Medium: textual agreement cannot prove protocol compatibility. |
| Hosted Docker job | Fail early on registry or pin errors | Low: reduces wasted startup time; does not fix a bad pin by itself. |
| Live shape and boundary tests | Prove runtime behavior after preflight | High: preflight can never replace callback/execution evidence. |

#### Pros

- Turns the observed GHCR denial into an early, attributable failure.
- Preserves R1/R2/R4 while preventing a wrong image path from being discovered only after a long build.
- Produces useful release evidence: exact reference, digest, SDK declaration, server declaration, and runtime result.
- Composes cleanly with A and optionally B without changing semantic ownership.

#### Cons

- Cannot make an inaccessible or nonexistent image pullable; it only fails sooner and more clearly.
- Registry metadata success does not prove the image starts or that the SDK protocol works.
- A package-index version check can be misleading if it does not inspect the built worker image and actual SDK constructor/registration surface.
- Adds another gate that must itself avoid network-dependent flaky behavior and must upload its diagnostics.

#### Choose when

Choose this as a guardrail whenever hosted registry failure is a release blocker. It is a complement, not a substitute for real application/worker repair.

### Option D — Hatchet Lite topology for CI

**Summary:** Use the official single-container Hatchet Lite topology for CI while retaining a multi-service Hatchet topology for production.

#### Architecture and data flow

- A CI-specific Compose overlay substitutes the Lite scheduler container while keeping the UMD API/worker image, callback registration, stage executor, Postgres application state, and HTTP boundary unchanged.
- Production remains on the full Hatchet topology. Both are pinned to the same nominal Hatchet release and must still use real callbacks and real execution.
- Full production Compose is statically validated; Lite is the topology that creates hosted release evidence.

#### Integration surfaces

| Existing surface | Architectural role | Risk |
|---|---|---|
| Compose overlay and pin tests | Represent two Hatchet deployment surfaces | High: topology skew can invalidate the “same stack” proof. |
| Worker/client configuration | Verify Lite exposes the same API/gRPC/task behavior required by the worker | High: official product identity does not guarantee identical operational behavior. |
| Handoff release gate | Decide whether Lite evidence is acceptable for production | Critical: current handoff requires real work against the same Compose/CI stack (`HATCHET_LIVE_VALIDATION_HANDOFF.md:10-13,232-241`). |

#### Pros

- Fewer scheduler services and less CI startup surface.
- May avoid the exact top-level image path that was denied.
- Keeps Hatchet as the only scheduler; Lite is not a second scheduling system.
- Potentially improves hosted-run reliability and teardown time.

#### Cons

- The release evidence would be produced by a different topology than production, weakening restart, auth, migration, networking, and operational proof.
- Same version tag does not establish same topology semantics, persistence behavior, or gRPC routing.
- Requires an explicit policy decision to redefine the validated deployment surface; static validation of full Compose is not equivalent to running it.
- It can hide a defect in the production multi-service topology while CI is green.

#### Choose when

Only choose D if the project explicitly declares Lite as the release deployment surface or accepts a separate full-topology hosted gate. Under the current handoff, D is rejected as a standalone release strategy.

## Fit and tradeoff matrix

Scores are architectural judgments from 1 (poor) to 5 (strong), not measured runtime results. A “release fit” score of 1 or 2 means the option cannot independently satisfy the current release contract.

| Criterion | A: coordinated repair | B: split jobs | C: prove-then-run | D: Hatchet Lite |
|---|---:|---:|---:|---:|
| Repairs real product wiring | **5** | 2 | 2 | 2 |
| Repairs dependency/image attribution | 4 | 4 | **5** | 4 |
| Preserves same-stack release evidence | **5** | **5** | **5** | 2 |
| Hatchet-only scheduler compliance | **5** | **5** | **5** | **5** |
| Fail-closed/no fake readiness | 5 | 5 | **5** | 4 |
| Full Task.md DoD fit | **5** | 4 | 4 | 3 |
| Hosted diagnostic clarity | 4 | **5** | **5** | 4 |
| Workflow/operations simplicity | 3 | 3 | 4 | **5** |
| Regression/topology risk (higher is safer) | 3 | 4 | **5** | 2 |
| Standalone viability | **5** | 2 | 2 | 2 |
| **Disposition** | Base candidate | Complement only | Guardrail complement | Reject standalone |

### Non-negotiable rejection rule

An option is rejected, regardless of speed or green-job value, if it does any of the following:

- leaves `app.py` on a synchronous/interim release path while calling the release gate complete;
- makes live worker validation opt-in or excludes Hatchet/worker from the mandatory release job;
- treats a recording client, in-process callback, or local no-server result as scheduler evidence;
- converts missing implementation into a stub, fake completion, unconditional skip, weakened assertion, or invented capability;
- removes or relaxes required Compose secret interpolation;
- proves only Lite while claiming the full production topology is validated, without a separately accepted full-topology gate;
- omits any `Task.md` mandatory DoD behavior from the final evidence matrix.

## Provisional selected combination

**Provisional combination: A + C, with B optional after the first repaired live run; D excluded.**

This is a combination of repair architecture and evidence guardrail, not an implementation plan or final approval. A is necessary because B and C cannot repair the missing production runner/capability/application path. C is added because the observed failure is a registry/image failure and early exact-reference proof improves attribution without weakening the gate. B may later separate baseline feedback from live release evidence, but only if the live job remains a required, fail-closed check. D is excluded because the current handoff makes same-stack live execution a release condition; using Lite alone creates topology-skewed evidence.

The combination is **blocked from approval** until the adversarial artifact has substantive T2–T8 sections and the next hosted run proves the actual pair and topology. The combination does not promote `hatchet-sdk==1.38.1` / server `v0.105.2` from candidate to validated merely from textual agreement.

## Hosted evidence gates

These are release evidence gates, not a task plan. They describe what the hosted run must prove and what must remain unavailable on failure.

| Gate | Required hosted evidence | Fail-closed condition |
|---|---|---|
| 1. Commit identity | New run is attached to the pushed repair commit; GitHub run URL, job IDs, and commit SHA are recorded. | Any local-only result is excluded from release evidence. |
| 2. Static/package baseline | Ruff, strict mypy, unit, and PostgreSQL suites run with the dependencies their tests exercise; JUnit/log/coverage artifacts are uploaded. | Missing package/tool is a real failure, not a skip. |
| 3. Compose configuration | `docker compose config` succeeds with generated required secrets; required `${VAR:?}` interpolation remains required. | Missing secret or invalid interpolation fails the job. |
| 4. Exact registry/pin preflight | Exact image references are pullable/inspectable and digests are recorded; SDK/server declarations agree per surface. | Denied, missing, mutable, or mismatched reference fails before E2E. |
| 5. Container composition | API and worker images build with the dependencies used by their roles; migrations and health/readiness execute against the configured DB/OCFL volumes. | Host package availability cannot substitute for image proof. |
| 6. Real worker readiness | Worker binds the complete canonical registry to real Hatchet callbacks and starts the actual SDK worker loop; logs and scheduler capability evidence are captured. | Zero callbacks, exited worker, or env-only readiness fails. |
| 7. Real execution | HTTP submission reaches `ProductionDAGRunner`, Hatchet accepts runs, callbacks invoke `DurableStageExecutor`, and Postgres records authoritative stage/audit completion. | Queued-only, recording-only, or fabricated completion is insufficient. |
| 8. Boundary behavior | `tests/test_api_boundary_e2e.py` runs over HTTP for heterogeneous real-format sources, provenance, semantic answers, source retrieval, correction, invalidation, selective rerun, and consistency. | Capability gating may describe an unavailable local environment, but the hosted mandatory path must not be vacuously skipped. |
| 9. Restart/dedup | API/worker stop/start preserves named volumes; duplicate, retry, late failure, and DAG-universe behavior show one authoritative completion and no repeated committed ancestors. | `down -v` between restart segments invalidates this evidence. |
| 10. Release summary | Failure diagnostics, worker/Hatchet/API/DB logs, JUnit artifacts, image digests, provider gate statuses, and the final matrix are uploaded with `if: always()`. | Missing artifacts or stale counts keep the gate open. |
| 11. Final review | Complete QA/adversarial review runs after behavior and workflow evidence; findings are repaired through the required plan/Exec path and the complete suite is rerun. | No release publication with unresolved mandatory FAIL or unreviewed drift. |

## Full `Task.md` DoD cross-check

The current failed run cannot satisfy these items; the listed proof is the minimum evidence the selected combination must preserve. The authoritative list is `Task.md:1641-1692` (items 1–35), with behavioral requirements in `Task.md:1-1639`.

| DoD item | Repair-release proof obligation |
|---:|---|
| 1 | The repair design, later plan, and final review exist; this artifact is blocked until T1–T8 is complete. |
| 2 | A plan derived from this design is implementation-ready; this report deliberately does not create it. |
| 3 | Hosted evidence may claim implementation only from the pushed Exec result, never from this report or local state. |
| 4 | Persistent source storage remains exercised through OCFL and named-volume evidence. |
| 5 | Text/book ingestion executes in the hosted representative flow. |
| 6 | Image ingestion executes in the hosted representative flow. |
| 7 | Audio ingestion executes in the hosted representative flow. |
| 8 | Video ingestion executes with the real FFmpeg/media path; missing FFmpeg is fixed as provisioning, not skipped. |
| 9 | Stable addressable segments are retrieved through the public API. |
| 10 | Evidence-to-locator-to-source provenance is asserted over HTTP and persisted records. |
| 11 | Semantic assertions retain evidence, confidence/uncertainty, and generated-by metadata. |
| 12 | Multilingual/translated realizations remain distinct under one work. |
| 13 | Adaptation/continuity boundaries remain represented rather than collapsed. |
| 14 | Cross-source alignment is exercised and remains many-to-many/explicit where applicable. |
| 15 | Entity resolution remains reversible and auditable. |
| 16 | User overrides are applied through the public boundary and reflected in audit/current state. |
| 17 | Segment editing is not removed or bypassed by the CI repair. |
| 18 | Semantic editing/override behavior remains covered. |
| 19 | Invalidation is descendant-only and does not re-run unaffected extraction. |
| 20 | Individual stages can be rerun through the durable job path. |
| 21 | Jobs survive API/worker restart and late-stage failure without repeating committed work. |
| 22 | Structured source references resolve bounded source-native material. |
| 23 | Semantic KG-style questioning runs through the typed API and carries support. |
| 24 | Structured graph-like querying remains covered; CI repair must not replace it with opaque RAG. |
| 25 | Answers expose source/evidence references and required metadata. |
| 26 | Audit/history explains current, prior, actor, and change cause. |
| 27 | Provider interfaces remain swappable; deployment repair cannot hard-code a provider as semantic authority. |
| 28 | At least one local/self-hostable model path remains honestly reported and gated when unavailable. |
| 29 | Heterogeneous and contradictory multi-source fixtures execute in the hosted path. |
| 30 | Public correction → invalidation → selective rerun E2E passes with unaffected IDs/checksums stable. |
| 31 | Docker deployment works on the hosted native engine; static-only local Compose checks do not close this item. |
| 32 | Ruff, strict mypy, and other static checks pass on the pushed repair commit. |
| 33 | Automated unit, integration, live scheduler, and boundary tests pass; permitted gates are named and observable. |
| 34 | Final adversarial correctness review probes provenance, conflation, merge/split, invalidation, stale semantics, locators, language/adaptation, races, restart, storage, and media safety. |
| 35 | Findings are repaired through the support/design/plan/Exec process and the complete validation suite is rerun, with hosted reports attached. |

### Cross-check of the non-DoD Task sections most directly at risk

| `Task.md` sections | Risk in run 33164294061 | Required preservation |
|---|---|---|
| §§1–2, 7, 11, 15, 21–22 | A synchronous or recording path cannot prove provenance, correction, audit, or ownership. | Keep source/evidence/semantic separation and Postgres/OCFL ownership; do not make CI green by bypassing these paths. |
| §§6, 16, 23 | Docker never started and the release scheduler path is not proven. | Hatchet remains sole scheduler; durable restart and descendant-only rerun must be observed live. |
| §§8–9, 19 | Local/host-only success does not prove source-native retrieval in the image. | Verify stable segments and bounded locator retrieval over the running service. |
| §§12–14, 26–31 | Missing native tooling prevented modality paths; capability gates can hide them. | Run representative text/image/audio/video/subtitle flows and preserve uncertainty, adaptation, time, and space semantics. |
| §§24–25, 32–33 | API-only boundary and sandbox/observability are release surfaces. | Retain HTTP-only E2E, safe parser boundaries, structured diagnostics, and honest capability states. |
| §§34–35, 38–40 | Static green was mistaken for release readiness. | Require complete hosted matrix, final adversarial review, repair, rerun, and measured release decision. |

## Technology and version claims

No new technology is selected by this report. The following claims are carried from the supplied research/adversarial evidence and remain provisional until the hosted gate validates the actual deployment:

| Claim | Supplied source | Check date/status |
|---|---|---|
| Hatchet released images use sub-paths such as `hatchet-engine`, `hatchet-admin`, `hatchet-migrate`, and `hatchet-lite`, rather than assuming the denied top-level path. | `ADVERSARIAL-universal-media-decomposer-ci-repair.md:96-103`, citing Hatchet self-hosting docs | Checked 2026-08-28 in the supplied research; **provisional until `docker manifest inspect`/pull succeeds in hosted CI**. |
| `hatchet-sdk==1.38.1` and server `v0.105.2` are contemporaneous candidate releases, not a validated compatibility pair. | `...ADVERSARIAL...md:100-103`; `HATCHET_LIVE_VALIDATION_HANDOFF.md:18-38` | Candidate/PENDING; live callback/retry/restart evidence required. |
| `python-multipart==0.0.32` is the appropriate declared runtime package for the Starlette/FastAPI form path. | `...ADVERSARIAL...md:104`; debugger `:43-51` | Checked 2026-08-28; package claim is still subordinate to a clean hosted install and multipart test. |
| Ubuntu hosted runners require explicit FFmpeg and matching PostgreSQL 17 client provisioning for the exercised tests. | `...ADVERSARIAL...md:108-110`; debugger `:43-49` | Checked 2026-08-28; hosted job installation and test results are authoritative. |
| Hatchet Lite is intended for development/low-volume use and differs operationally from full self-hosting. | `...ADVERSARIAL...md:67-75`, citing official Hatchet Lite/full Compose docs | Checked 2026-08-28; **provisional for release use and not accepted under the current same-stack gate**. |

Claims about current action majors, image availability, registry permissions, SDK method shapes, and Lite/full-topology equivalence must not be presented as permanent facts without a fresh official-source check and the hosted run. The report therefore uses no unverified “optimal/current” technology claim as a reason to weaken a requirement.

## Required process handoff

The evidence supports the immutable routing request:

```text
Support diagnosis (complete)
  -> R&D architecture/tradeoff report (this file; adversarial-completeness blocked)
  -> implementation plan (not created here)
  -> Exec-Manager execution
  -> push to GitHub
  -> retrieve and inspect a new hosted run/artifacts
  -> final QA/adversarial DoD matrix
```

The support debugger explicitly identifies `NEEDS_PLAN` and says no `suggestedFix` is supplied because the scope is not `SIMPLE` (`universal-media-decomposer-ci-repair-debugger.md:162-172`). Existing Plan J is dependency-blocked until prerequisites and hosted evidence exist (`TASK-universal-media-decomposer-J-api-boundary-ci-release.md:38-49`; `artifacts/logs/exec-manager.log.jsonl:L57`). This report does not convert that blocked plan into an implementation plan and does not route the work to a fixer.

## Exact evidence index

- Hosted run: <https://github.com/xiaden/Universeity/actions/runs/33164294061>
- Docker job: <https://github.com/xiaden/Universeity/actions/runs/33164294061/job/98825909849>
- PostgreSQL job: <https://github.com/xiaden/Universeity/actions/runs/33164294061/job/98825910085>
- Unit job: <https://github.com/xiaden/Universeity/actions/runs/33164294061/job/98825910133>
- `artifacts/designs/process/universal-media-decomposer-ci-repair-debugger.md:11-15,43-108,110-172,174-186`
- `artifacts/designs/process/universal-media-decomposer-technology-research.md:91-95,205-212,239-253,356-360`
- `artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-ci-repair.md:7-12,18-112` (T1 material; T2–T8 substantive sections absent)
- `artifacts/designs/pending/DD-universal-media-decomposer-ci-repair.md:3-45`
- `artifacts/designs/parts/universal-media-decomposer/CONTRACTS.md:58-67`
- `artifacts/designs/parts/universal-media-decomposer/HATCHET_LIVE_VALIDATION_HANDOFF.md:10-38,64-97,101-120,154-241`
- `artifacts/plans/pending/TASK-universal-media-decomposer-I-hatchet-worker-integration.md:1-8,24-70`
- `artifacts/plans/pending/TASK-universal-media-decomposer-J-api-boundary-ci-release.md:24-55`
- `Task.md:1-9,331-382,792-832,1047-1068,1375-1420,1641-1692`
