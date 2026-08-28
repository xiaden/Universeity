# UMD Failed-Run Repair — Architect Stage

**Status:** `DONE` — read-only architecture analysis  
**Date:** 2026-08-28  
**Agent:** `rnd-architect`  
**Scope:** Architectural repair after hosted GitHub Actions run `33164294061` at SHA `a6b1a62`; this report does not claim implementation or release readiness.

## Inputs and evidence boundary

This analysis cross-checked:

- `Task.md` Definition of Done items 1–35 and the surrounding product constraints.
- Parent DD: `artifacts/designs/pending/DD-universal-media-decomposer.md`.
- Repair DD: `artifacts/designs/pending/DD-universal-media-decomposer-ci-repair.md`.
- Completed adversarial artifact: `artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-ci-repair.md` (T1–T8).
- Support-Librarian report `promising-black-lemming` and Support-Researcher report `critical-magenta-jackal`.
- `artifacts/designs/parts/universal-media-decomposer/CONTRACTS.md` §58–63 and `HATCHET_LIVE_VALIDATION_HANDOFF.md`.
- Plans G, H, I, J and `artifacts/plans/handoff-G-to-I-J.md`.
- The final PatternEnforcer approval, which reports the repair DD internally consistent and approved, without treating it as implementation or release approval.

The failed hosted run is the authoritative baseline: Ruff and strict mypy passed; Unit failed once; PostgreSQL failed 14 times from missing runtime/native dependencies and required Compose variables; Docker E2E failed before startup on the denied top-level Hatchet image reference. Local green tests, static contracts, fixtures, stubs, and no-server skips are context only.

## Architectural constraints

All options below must preserve these invariants:

1. Hatchet is the sole v1 scheduler. `DurableDAGRunner`, recording clients, and synchronous seams remain hermetic/test-only and cannot supply release evidence.
2. `ProductionDAGRunner.run_graph` submits durable stage work; `DurableStageExecutor` owns claim-before-side-effect, idempotency, retries/quarantine, and atomic `StageCompleted`/artifact/evidence persistence.
3. `StageWorkRegistryFactory.build(runtime)` must compose every canonical `STAGE_ORDER` stage with real modality/semantic work; an absent stage is `ConfigurationError`, never successful completion.
4. OCFL source/artifact bytes remain immutable; PostgreSQL remains authoritative for descriptors, segments, evidence references, stage/job state, append-only semantic events, current state, and audit. Projection builders alone write projections.
5. Multilingual realizations, adaptations, subtitles, contradictions, stable locators, evidence/semantic separation, and descendant-only invalidation remain explicit and individual.
6. Capabilities use exactly `active`, `reference-only`, `configured-unavailable`, `gated`, and `disabled`; `active` requires a real reachable scheduler and observed version/reason.
7. Required Compose secrets remain `${HATCHET_COOKIE_SECRET:?}` / `${HATCHET_MASTER_KEY:?}`. Missing values fail configuration; they are not weakened or defaulted silently.
8. Release documentation follows behavior and hosted evidence. A mandatory missing or failed gate is `FAIL`, not a silent skip.

## Common production data flow

The viable options share the following product boundary; they differ in deployment and CI evidence topology:

```text
HTTP /v1 source or job mutation
  -> JobService.submit/retry/rerun/invalidate
  -> ProductionDAGRunner.run_graph
  -> submit_workflow_runs / Hatchet SDK adapter
  -> Hatchet engine durable queue
  -> registered worker task (one task per STAGE_ORDER stage)
  -> DurableStageExecutor.run
  -> StageWorkRegistryFactory stage implementation
  -> OCFL/Postgres/semantic-ledger ownership paths
  -> stage_run + StageCompleted + job audit
  -> HTTP status/report/query with provenance and consistency metadata
```

The current tree has two required product corrections before this flow is real:

- `src/umd/api/app.py:167` wires `DurableDAGRunner`; the release factory must wire `ProductionDAGRunner` by default.
- `src/umd/jobs/runner.py` submits queued events but does not create queued stage rows. `JobService._refresh_status` can therefore overwrite `RUNNING` to `PENDING` until the first callback. The implementation plan must choose and test an explicit queued-state representation (prefer persisted queued `stage_run` rows or an equivalent durable job-state contract), without fabricating completion.

## Options

### Option A — Commit-and-wire, fail-closed, prove-first (primary selected direction)

**Summary:** Repair the actual product/runtime boundary and restore the existing Docker job as a mandatory full-topology release gate; fold a small exact-image preflight into that path.

#### Architecture

- **Product layer:** extract one shared runtime assembly from `app.py` and use it in `cli.worker`; construct `ProductionDAGRunner` over the real Hatchet client in the release factory. Keep `DurableDAGRunner` only for explicit hermetic/dev construction and prohibit it from reporting scheduler `active`.
- **Scheduler adapter:** in `src/umd/jobs/hatchet.py`, align the real SDK boundary before hosted discovery: v1 two-argument handler `(input, ctx)`, serialized `StageManifest` mapping, and the documented `Workflow.run`/`runs.create` submission surface. Bind each callback to `DurableStageExecutor`; set Hatchet task retries to zero so executor retry/quarantine is the sole retry authority.
- **Worker:** `src/umd/deploy/cli.py` builds the full Postgres/OCFL/semantic/provider/sandbox/replay/registry runtime, creates `client.worker("umd-worker", workflows=handle.registered_workflows)`, and owns the single blocking SDK loop. The exact readiness line is emitted immediately before blocking start, remains marked candidate until proof, and is never treated as execution proof.
- **Capabilities:** inject a lightweight gRPC reachability probe into `CapabilityReporter`, with cached/hysteretic disclosure state and observed reason/version. The probe proves reachability only; live stage transitions prove execution.
- **Deployment:** replace the non-functional `hatchet` service with the full split topology: `hatchet-migrate` → config-generating `hatchet-admin` → `hatchet-engine` + `hatchet-dashboard`, shared config volume, exact v0.105.2 environment surface, and a real per-run JWT token. Worker/test-runner gRPC routing uses the engine service and the topology's actual container port.
- **CI:** retain one Docker E2E job, add a short `docker manifest inspect` tripwire, start the complete stack unconditionally, wait for API/worker/probe readiness, run live shape tests and HTTP-only boundary E2E in a Compose-network test container, preserve volumes across stop/start, capture evidence with `if: always()`, and fail closed on missing live evidence.

#### Integration points and new work

| Surface | Change | Risk |
|---|---|---|
| `src/umd/api/app.py`, `src/umd/jobs/runner.py` | Production runner selection and explicit queued-state reconciliation | High; async status must remain callback-owned |
| `src/umd/jobs/hatchet.py`, `src/umd/deploy/cli.py` | v1 SDK adapter, real callback binding, full worker runtime | High; live SDK/name/routing behavior |
| `src/umd/jobs/capability.py` | Injected bounded reachability disclosure | Medium; reachability is not execution |
| `deploy/compose.yaml`, `deploy/Dockerfile` | Full split Hatchet topology and worker-capable image | High; v0.105.2 env contract is provisional |
| `.github/workflows/validation.yml`, scripts, live tests | Fail-closed hosted proof and evidence capture | High; hosted-only arbiter |
| `pyproject.toml`, `runtime.txt`, `tests/conftest.py` | Multipart, FFmpeg, PG17 client, and pin agreement | Low/medium; hosted package drift |

**Estimated size:** approximately 17 existing files, 2 possible support artifacts, ~41K edit-scope characters, weighted estimate ~87K; `LARGE`, low confidence because live iteration count is unknown. No new scheduler or semantic store is introduced.

#### Pros

- Directly satisfies the selected adversarial direction and the same-stack release contract.
- Repairs real product wiring instead of merely making CI green.
- Keeps Hatchet, Postgres, OCFL, ledger, registry, and projection ownership boundaries intact.
- Makes every failure attributable to package, image/topology, registration, callback, persistence, or public API behavior.

#### Cons

- Largest coordinated change and longest first hosted feedback loop.
- Full split topology has unresolved v0.105.2 config/token details until booted.
- A single Docker job is slower and less independently attributable than a later split-job arrangement.
- Shared worker-capable image increases API image size and supply-chain surface; installing the candidate SDK does not validate the SDK/server pair.

#### Choose when

Use when release evidence must prove the deployed full Hatchet topology and real public behavior, as required by the current handoff. This is the supplied selected direction, not a claim that its candidate pins are validated.

---

### Option B — Split baseline and mandatory live jobs (post-green complement)

**Summary:** Keep fast package/unit/Postgres feedback separate from a full-stack live job, while retaining Option A's product and topology repairs in the live job.

#### Architecture

- Baseline job runs Ruff, mypy, unit/Postgres suites, Compose configuration, and dependency checks.
- Live job builds the same image, starts the same full split topology, runs the worker and API, executes the in-network live shape suite plus the HTTP boundary E2E, and proves restart/dedup/persistence.
- An always-running gate job uses `needs` and `always()` to fail if the live job is skipped or fails. No trigger-level path filter may suppress the live proof on protected branches; optional internal filtering must still fail on skip.
- Both jobs use the same pins, runtime assembly, token policy, and artifact naming conventions.

#### Pros

- Faster ordinary feedback and clearer failure attribution.
- Reduces pressure to disable the expensive live gate.
- Separates CI environment remediation evidence from live scheduler evidence.

#### Cons

- Does not repair any product defect by itself; it is not a standalone architecture.
- Duplicates setup and can drift in environment, image, or pin handling.
- Path filters and required-check settings can silently create a green-without-live-proof state unless the gate job is configured correctly.
- Two cold stack boots increase hosted cost and duration.

#### Disposition

Viable only after Option A has produced a green live run. It is a CI ergonomics complement, not the initial repair path and never a substitute for full-stack evidence.

---

### Option C — Prove-then-run evidence guardrail

**Summary:** Add exact-reference registry and package/image tripwires before the same mandatory live repair path.

#### Architecture

- `.github/workflows/validation.yml` checks the exact split image references with `docker manifest inspect`, records references/digests, and fails immediately on denial or mutable/mismatched references.
- The worker image performs an import/version smoke check for the declared candidate SDK.
- Compose still performs migration, config generation, token minting, engine/dashboard startup, worker registration, callbacks, and public E2E. The preflight cannot be the release proof.

#### Pros

- Detects the observed top-level GHCR path failure quickly and with useful attribution.
- Keeps registry failures distinct from application failures.
- Adds little runtime complexity and composes with either A or B.

#### Cons

- A manifest proves neither layer pull completion nor runtime compatibility.
- Package/version agreement cannot prove protocol behavior, name matching, or callbacks.
- Network-dependent preflight can itself be flaky and must upload diagnostics.
- If treated as a conditional gate, it can accidentally become a green-without-execution bypass.

#### Disposition

Required as a small tripwire folded into Option A; not a standalone implementation approach. Do not add retry taxonomies, `allow-failure`, or a second scheduler around it.

---

### Option D — Hatchet Lite in CI, split topology in production

**Summary:** Use a real single-container Lite scheduler for hosted CI while statically or separately validating full production Compose.

#### Architecture

- CI overlay uses `hatchet-lite`; API/worker still use Hatchet callbacks and `DurableStageExecutor`.
- Production retains split migrate/admin/engine/dashboard services.
- Client routing and secrets differ: Lite's gRPC/dashboard ports and configuration are not the split topology's ports/config contract.

#### Pros

- Fewer CI services and potentially faster startup.
- Still uses Hatchet rather than a second scheduler.
- Could avoid the denied top-level image path.

#### Cons

- Hosted proof is for a different scheduler topology than the deployed one, weakening migration, auth, queue, routing, restart, and persistence evidence.
- Lite uses materially different ports/configuration and can hide defects in full production Compose.
- Conflicts with the handoff's same-stack release requirement and the required split-secret contract.
- A nominally equal version tag does not establish equivalent operational behavior.

#### Disposition

Rejected as a release-evidence surface under the current requirements. It may be documented as a local convenience only after routing/configuration are independently honest; it cannot close DoD 31 or the Hatchet live gate.

## Tradeoff matrix

Scores are architectural judgments, not measured runtime results. `5` is strongest fit/safest; `1` is weakest. Option B/C scores assume the required Option A product repair is also present; their standalone scores are lower.

| Criterion | A: commit-and-wire | B: split jobs | C: preflight guardrail | D: Lite CI |
|---|---:|---:|---:|---:|
| Repairs real product wiring | **5** | 2 | 2 | 2 |
| Preserves full same-stack release evidence | **5** | **5** | **5** | 2 |
| Hatchet-only scheduler compliance | **5** | **5** | **5** | **5** |
| Fail-closed/no fake readiness | **5** | 5 | **5** | 4 |
| Full Task.md DoD fit | **5** | 4 | 4 | 3 |
| Diagnostic clarity | 4 | **5** | **5** | 4 |
| CI topology simplicity | 3 | 3 | **5** | **5** |
| New files/maintenance | 3 | 2 | **5** | 2 |
| Standalone viability | **5** | 2 | 2 | 2 |
| Release disposition | Base | Post-green complement | Fold into A | Reject |

**Selection context:** the user-supplied T7 direction selects A-refined as primary, folds C into it, and permits B only after a green live run. This report preserves that selection while exposing its costs and unresolved arbiters.

## Exact recommended architecture and stream split

### Product remediation stream

1. **One runtime assembly:** factor the full `build_context` production dependencies into a shared assembly consumed by API and worker. It must include Postgres repositories, OCFL store, semantic ledger/commands, real `StageWorkRegistry`, provider registry, sandbox, artifact store, replay/projection builders, observability, and capability dependencies.
2. **Production runner:** construct `ProductionDAGRunner` in the release API factory. It submits one `umd-<stage>` workflow per canonical stage and returns queued events only. Add the queued-state reconciliation contract needed to prevent `RUNNING → PENDING` regression before callbacks; terminal `COMPLETE` remains callback-committed only.
3. **SDK surface:** pre-align and hermetically test the candidate SDK boundary: handler `(input, ctx)`, typed/serializable manifest mapping, `Workflow.run` or `runs.create`, and `client.worker(name, workflows=...).start()`. The first hosted run then observes only namespacing, routing, and live protocol behavior.
4. **Worker callbacks:** bind every stage to the real registry and `DurableStageExecutor`; resolve committed upstream evidence refs immediately before execution; preserve cancellation, retry, quarantine, replay, idempotency, DAG-universe isolation, and descendant-only rerun.
5. **Retry authority:** executor retry/backoff/quarantine is the sole application retry authority; Hatchet task retries are explicitly zero (or deterministic failures are non-retryable at the boundary). Avoid amplified attempts and duplicate quarantine records.
6. **Capability honesty:** inject one bounded reachability-only gRPC probe with cached/hysteretic disclosure. `active` requires the `ProductionDAGRunner` backend and a successful probe; it does not claim stage execution. The live E2E remains the execution authority.

### CI/environment remediation stream

1. Commit the real `python-multipart==0.0.32`, FFmpeg/ffprobe, PGDG PostgreSQL 17 client plus `UMD_PG_BIN`, and required-secret job exports. These fix the observed 14 PostgreSQL/unit failures; no assertion or skip changes are substitutes.
2. Replace the top-level Hatchet image with the full split sub-path services and preserve exact required secret interpolation. Read the v0.105.2-tag configuration surface before finalizing env names; current docs and GHCR probes remain provisional.
3. Install the worker extra in the image actually used by API/worker/test-runner, while keeping SDK/server status `CANDIDATE` until live proof.
4. Provision a real tenant JWT after config generation; never use `umd-ci-token`. Pass canonical worker URL and engine gRPC host/port through the same topology source.
5. Make the existing Docker job unconditional and fail closed. Keep the manifest preflight as a fast tripwire only. Run live tests inside the Compose network, after API/worker readiness and capability warm-up; never call `create_app()` in live mode.
6. Preserve named volumes through API/worker stop/start, then capture Compose/service/DB/OCFL/JUnit/release-summary evidence with `if: always()`. Teardown volumes only after all evidence is collected.
7. If B is later adopted, add a required always-run aggregate gate that fails on live-job skip/failure; never rely on trigger-level path filters.

The streams are separate for review, ownership, and failure attribution. They may land atomically where necessary to prevent a weakened gate from being committed (for example, do not commit `UMD_VALIDATE_LIVE_WORKER=false` before the live wiring exists), but they must not be conflated into an unreviewable `git add -A` change.

## Compatibility and proof gates

The following are provisional until observed on the same hosted full split stack:

1. Pullability and digest of `hatchet-engine`, `hatchet-admin`, `hatchet-migrate`, and `hatchet-dashboard` at `v0.105.2`.
2. `hatchet-sdk==1.38.1` ↔ server `v0.105.2` registration and execution compatibility.
3. Exact v0.105.2 config-generation envs, secret forms, Postgres-only message queue behavior, dashboard container port, and token-minting command.
4. JWT broadcast address and `host_port` routing from API, worker, in-network test-runner, and capability probe.
5. `umd-<stage>` name matching and non-empty engine-visible workflow registration.
6. Submission payload and handler invocation on the actual pair.
7. Cold-start timing and bounded poll budgets.

### Mandatory hosted closure sequence

```text
Exec implementation commit
  -> push to GitHub and record SHA/run/jobs
  -> hosted lint/type/unit/Postgres reports
  -> exact image preflight + digest
  -> build worker-capable image and smoke import
  -> migrate/config/token/engine/dashboard startup
  -> API readiness
  -> real worker callback registration and engine-visible nonzero bindings
  -> /v1/capabilities active with observed reason/version
  -> live shape tests: duplicate/restart, retry/quarantine, universe drain/rekey
  -> public HTTP-only heterogeneous E2E
  -> correction/invalidation/selective rerun and consistency checks
  -> stop/start restart with OCFL/Postgres preservation
  -> final diagnostics, machine-readable live-worker-gate PASS
  -> retrieve and inspect every GitHub report/artifact
  -> final QA/adversarial review, repairs, complete rerun
```

No single readiness log line, manifest, capability probe, green checkmark, or local test closes the gate alone. The primary proof is real callback-owned stage persistence plus the HTTP-only public scenario against the same running Compose stack.

## Risks and mitigations

| Risk | Severity | Mitigation/gate |
|---|---|---|
| SDK/server candidate pair fails live | High | Keep candidate status; run same-stack proof; if failure, lockstep bump SDK/server, assign new DAG universe, drain in-flight work, repeat hosted validation |
| v0.105.2 env/token surface differs from current docs | High | Inspect tag-specific surface; boot migration/config/token as separate attributable steps; fail closed |
| Handler/submission/name/port mismatch | High | Pre-align documented SDK shapes and add hermetic surface tests; hosted run proves namespacing/routing |
| Worker line appears before actual registration | High | Treat line as transport signal only; require engine-visible bindings and callback rows; retain candidate suffix |
| `RUNNING` regresses to `PENDING` | High | Add persisted queued stage state or equivalent durable status contract and test submit-before-callback behavior |
| Double retry amplification | Medium-high | Explicit Hatchet retries zero; executor owns retry/quarantine; assert one effective stage completion |
| Test-runner network/volume race | Medium | Use one in-network runner after stack readiness; `--no-deps` only after explicit startup; tests never start a second worker |
| Fail-on-skip rejects permitted provider gates or misses production skip | Medium | Allowlist only named optional-provider gates; production-path skip is forbidden in release; record all skips |
| Worker image silently degrades modality work | High | Shared full runtime assembly; in-image SDK/tool smoke checks; representative heterogeneous HTTP E2E and real stage evidence |
| Hosted runner apt/image drift | Low-medium | Version assertions for FFmpeg/pg_dump; exact image references/digests; retain failure artifacts |
| Stream mixing commits unrelated changes | Medium | Explicit path-scoped commits and review; do not use `git add -A` |

## DoD and release classification

The current state is **not release-ready**. The correct pre-implementation classification is:

- **PASS:** adversarial process artifact exists; repair DD and cross-plan contracts exist; prior static checks passed on their historical scopes.
- **GATED:** real Hatchet pair/topology, worker registration, callback execution, durable restart, public heterogeneous correction E2E, Docker deployment, and hosted rerun.
- **FAIL until repaired/proven:** production API still wires `DurableDAGRunner`; capability `active` is unreachable without a probe; current Compose Hatchet service is non-functional; live gate/token/test transport are not yet proven; Plan J Phases 3–4 and final QA remain outstanding.

Before release, every mandatory Task.md item 1–35 must have a hosted evidence row. Optional provider/legal/platform conditions may remain `GATED` only with an explicit status, reason, owner, and proof command. No unresolved mandatory `FAIL`, skipped live evidence, recording/in-process proof, weakened secret/assertion, stale documentation count, or unilateral pin change is acceptable.

## Handoff

This Architect stage is complete and read-only. The next transition is:

```text
this durable architecture report
  -> validated implementation plan(s), explicitly split product vs CI
  -> Exec-Manager implementation and QA/fix cycles
  -> pushed GitHub commit
  -> retrieved hosted reports/artifacts
  -> final DoD matrix and adversarial release review
```

No production code, DD, or existing plan was edited by this stage.
