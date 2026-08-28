# Librarian Artifact Briefing: Universal Media Decomposer GitHub CI Repair

**Producer:** support-librarian
**Date:** 2026-08-28
**Purpose:** Durable artifact briefing for the CI-repair design work (the design that flows from the debugger diagnosis into an implementation plan and Exec-Manager execution, per R5). Read-only corpus navigation — no source/test/workflow/plan/production-doc edits, no ADRs created.

**Task echo:** Repair the UMD hosted GitHub CI (workflow `validation`, run 33164294061 on commit a6b1a62) for real missing implementation and dependency defects — not with stubs, unconditional skips, fake readiness, or weakened assertions — and restore the mandatory live Hatchet worker / real-stage release gate.

---

## 1. Immutable user request — preserved verbatim

The governing specification is the repository root file **`Task.md`** (1738 lines, git HEAD `a6b1a62`). Its binding requirements for this repair:

- **§40 Definition of Done (items 21, 23–24, 26, 29–35):** durable asynchronous jobs survive restart (21); semantic KG questioning (23); structured graph querying (24); first release must implement real representative text/image/audio/video decomposition, not merely interfaces (26); tests cover heterogeneous and contradictory multi-source media (29); the end-to-end correction → invalidation → selective-rerun test passes (30); Docker deployment works (31); lint/type/static checks pass (32); automated tests pass (33); final adversarial code correctness review (34); repair findings and rerun the complete validation suite (35).
- **§23 Background processing:** durable restartable job system; a failed late-stage analysis must not repeat expensive successful early extraction; jobs restartable after process/container restart.
- **§16 Rerun / invalidation engine:** selective recomputation; descendant-only invalidation; the dependency system determines what becomes stale.
- **§32 Security and isolation:** uploaded media is untrusted; no shell interpolation; sandbox dangerous parsers; bounded subprocess execution.
- **§2, §7, §11, §15, §21:** provenance is never lost; user overrides are first-class provenance-bearing data with precedence; evidence vs canonical semantics never collapsed; semantic editing retains history; audit explains change.
- **§9, §19:** stable structured locators; source-native retrieval.
- **§41 Agent authority:** agents choose technologies, frameworks, databases, migrations, containers; may replace poor architectural choices; do not ask the user to pick routine implementation details.

**§26/§32-35 context:** Hatchet is not named in Task.md; the "sole v1 scheduler / live worker = release gate" constraint originates in the design/plan layer (CONTRACTS.md, DD, Plan I, the handoff), not the user request.

---

## 2. R1–R6 ledger (immutable constraints for the CI-repair design) — preserved verbatim

Recorded in **`artifacts/designs/pending/DD-universal-media-decomposer-ci-repair.md`** §Constraints. These are the non-negotiable gates any repair design/plan must respect:

- **R1:** CI is managed by pushing to GitHub and retrieving CI reports once run there (mandatory).
- **R2:** CI failures must be diagnosed for real missing implementation/dependencies; do not make CI green with stubs, unconditional skips, fake readiness, or weakened assertions (mandatory).
- **R3:** Every repair must be cross-checked against Task.md's full Universal Media Decomposer Definition of Done: source/evidence/semantic separation, immutable provenance, real representative text/image/audio/video decomposition, durable asynchronous restartable DAG, selective invalidation/rerun, public API-only correction E2E, honest capability reporting, final adversarial review (mandatory).
- **R4:** Hatchet is the sole v1 scheduler; live worker callback registration and real stage execution are a release gate. Do not add a second scheduler or treat in-process doubles as release evidence (mandatory).
- **R5:** Support findings must flow into design, design must flow into implementation plan, and implementation must be delegated to Exec-Manager (mandatory process).
- **R6:** Existing local validation evidence (before CI): git diff --check, Ruff, strict mypy passed; local suite 392 passed/189 skipped, with Docker/Postgres/providers gated by environment — context only, not release evidence.

---

## 3. Corpus map (exact paths)

### Design documents (process + pending)
- **`artifacts/designs/pending/DD-universal-media-decomposer-ci-repair.md`** — distilled CI-repair design (Problem Statement, Constraints R1–R6, Preferences, Anti-Patterns). **Untracked in git.**
- **`artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-ci-repair.md`** — raw 8-turn adversarial refinement (T1 Ideator → T8 Counter-Improver). Contains the four repair approaches (A Commit-and-Wire, B Split-Job CI, C Prove-Then-Run, D Single-Container Scheduler), the ranking table, and the technology-validation table (all checked 2026-08-28). **NOTE:** T1 records the debugger report as "MISSING from disk" at ideation time; the file now exists (see §7).
- **`artifacts/designs/process/universal-media-decomposer-ci-repair-debugger.md`** — **the authoritative diagnosis** of run 33164294061 (status `DIAGNOSED`, `NEEDS_PLAN`). **Untracked in git.** Primary evidence base for any repair design.
- **`artifacts/designs/process/universal-media-decomposer-architecture-options.md`**, **`...-technology-research.md`**, **`...-complexity-review.md`**, **`...-final-estimate.md`**, **`...-pattern-enforcer-approval.md`**, **`...-adversarial-log.md`** — upstream design-history artifacts (parent UMD DD process).
- **`artifacts/designs/pending/DD-universal-media-decomposer.md`** — parent DD (API, jobs, provider/security gates, deployment, testing, acceptance). Cited by Plan J.
- **`artifacts/designs/parts/universal-media-decomposer/CONTRACTS.md`** — cross-plan binding contracts. **§58-63 "Production execution remediation contracts"** define `ProductionDAGRunner.run_graph` (sole-Hatchet dispatch), `HatchetWorkerFactory.start` (real callback registration = readiness), `CapabilityReporter.report` (never represents unavailable as active). §61 is the `ProductionDAGRunner` contract.
- **`artifacts/designs/parts/universal-media-decomposer/HATCHET_LIVE_VALIDATION_HANDOFF.md`** — Plan I→J scheduler handoff + **hard release gate** (§8: fail if pinned scheduler does no real work, worker never ready, volumes wiped mid-restart, or the three dedicated shape tests are treated as passed while defective/vacuously skipped). **§6 is the DEFECT REPORT on the three `test_live_hatchet_*` shape tests.**
- **`artifacts/designs/parts/universal-media-decomposer/README.md`** — parts overview.

### Plans
- **`artifacts/plans/pending/TASK-universal-media-decomposer-J-api-boundary-ci-release.md`** — **Plan J** (the CI-repair/API-boundary/release plan; see §6).
- **`artifacts/plans/pending/TASK-universal-media-decomposer-I-hatchet-worker-integration.md`** — Plan I (Hatchet worker; prereq of J).
- **`artifacts/plans/pending/TASK-universal-media-decomposer-H-local-providers-modalities.md`** — Plan H (prereq of J).
- **`artifacts/plans/pending/TASK-universal-media-decomposer-G-production-runner-api.md`** — Plan G (prereq of J).
- **`artifacts/plans/handoff-G-to-I-J.md`** — Plan G→I/J handoff; §5 startup assumptions for J (canonical `__` env names, migrations through 0007, `app_factory()`, bounded upload, sandbox seam); §6 concurrency note (H/I/J edit the shared tree concurrently).

### Logs (artifacts/logs/)
- `exec-manager.log.jsonl` (L50–L87: Plan G/H/I/J orchestration + CI run coordination; L57 Plan J dependency block; L79/L82/L87 terminals)
- `exec-fixer.log.jsonl` (L1–L10: prior fixer work, incl. Plan I live-Hatchet wiring fixes)
- `qa-reviewer.log.jsonl` (L14–L24: Plan G/H/I/J review rounds; L20/L22 real-SDK worker-loop-start defects; L18 python-multipart gap)
- `support-debugger.log.jsonl` (L1–L3: CI 33164294061 root-cause diagnosis; L2 Plan J still blocked by hosted evidence; L3 CI-only hypothesis eliminated)
- `rnd-ideator.log.jsonl`, `rnd-refiner.log.jsonl`, `rnd-counter-ideator.log.jsonl`, `rnd-counter-improver.log.jsonl` (adversarial CI-repair turns)
- `support-researcher.log.jsonl` (evidence basis for the adversarial log)

### Workflow / scripts / deploy
- **`.github/workflows/validation.yml`** — the Plan J hosted workflow (5 jobs: lint, typecheck, test-unit, test-postgres, docker-e2e). **Modified (uncommitted) in working tree.**
- `.github/scripts/wait-for-http.sh`, **`.github/scripts/wait-for-worker.sh`** (readiness gate; greps `worker ready: registered` at line 35), `.github/scripts/capture-diagnostics.sh`, `.github/scripts/record-release-summary.sh`.
- **`deploy/compose.yaml`** — Hatchet image at line 104 uses top-level path `ghcr.io/hatchet-dev/hatchet:${HATCHET_VERSION:-v0.105.2}` (the pull that 403s); `HATCHET_COOKIE_SECRET`/`HATCHET_MASTER_KEY` required `${VAR:?}` interpolation at 101–111.
- **`deploy/Dockerfile`** — installs Python deps only (line 32 `pip install .` without the `worker` extra); no ffmpeg/PG-client inside container.
- **`deploy/pins/runtime.txt`** — Hatchet candidate pin (SDK 1.38.1 / server v0.105.2), lines 47–63, PENDING live validation.
- **`deploy/pins/asr-runtime.md`** — faster-whisper model pin (Plan H).
- **`pyproject.toml`** — `[project.optional-dependencies] worker` = `hatchet-sdk==1.38.1` (line 75–81); `python-multipart` pin (lines 42–45, uncommitted).

### Source files implicated by the diagnosis (all in `src/umd/`)
- `api/app.py` (52–54, 167–168: wires `DurableDAGRunner`, NOT `ProductionDAGRunner` — the product integration gap)
- `application/jobs.py` (90–116: `JobService.submit` invokes runner + immediately refreshes status)
- `jobs/runner.py` (263–296: `ProductionDAGRunner` contract; 276–296 submits to Hatchet)
- `jobs/hatchet.py` (`HatchetWorkerFactory`, `worker_ready_line`, SDK 1.38.1 wiring)
- `jobs/capability.py` (46–84: never claims `active` without verified live connectivity — but no actual connectivity probe)
- `jobs/production.py` (real stage bindings; Plan G/H product)
- `api/routers/sources.py` (259: `await request.form()` — needs python-multipart)
- `deploy/cli.py` (worker role; readiness line)

### Tests implicated
- `tests/test_api_boundary_e2e.py` (108–137: skips unless `/v1/capabilities` reports active scheduler/worker)
- `tests/test_hatchet_live.py` (920–1006: the three `test_live_hatchet_*` shape tests)
- `tests/conftest.py` (28–46: `pg_dump` resolution contract)
- `tests/test_deployment_phaseE.py` (248: Compose-config test requiring Hatchet secrets)
- `tests/fixtures.py` (478: ffmpeg-generated video fixture)

---

## 4. Prior decisions (constraints the repair must respect)

| Decision | Source | Impact on repair |
|---|---|---|
| Hatchet is the **sole v1 scheduler**; real callback registration + real stage execution = release gate; no second scheduler, no in-process doubles as release evidence | CONTRACTS.md:60-63; DD-ci-repair R4; HATCHET_LIVE_VALIDATION_HANDOFF §8 | Repair must wire `ProductionDAGRunner` into `app.py` and prove real live execution on a hosted run; durable-in-process runner is acceptable as a hermetic/test seam only, never release evidence. |
| Interim synchronous `DurableDAGRunner`-in-submit is **acceptable as a truthful interim path** but MUST be replaced by Hatchet submission for release evidence | exec-manager L21/L51/L75; handoff-G-to-I-J §4 | Plan J coordination note: `app.py:167-168` still wires `DurableDAGRunner`; rewire to `ProductionDAGRunner` is REQUIRED before release evidence. |
| Candidate pin SDK `1.38.1` ↔ server `v0.105.2`, recorded as **CANDIDATE/PENDING live validation**, not validated | deploy/pins/runtime.txt:56-58; handoff §1 | Must not be promoted to validated until a real pull/connect/execute test succeeds (the 403 denial proves the pin is unproven). Upgrade = bump both in lockstep + new DAG universe + drain. |
| The three `test_live_hatchet_*` shape tests are **defective as written** (RecordingClient + executor=None; no `stage_run` rows ever written) and must be **repaired**, not made green by changing assertions/skips | HATCHET_LIVE_VALIDATION_HANDOFF §6; exec-manager L82(b) | Plan J release gate must treat them as needing repair. **Nuance (ADVERSARIAL log, verified):** the current committed `test_hatchet_live.py` uses a real `HatchetWorkerFactory.start(... executor=executor, client=_real_client())` and `_poll_until`; the handoff §6 describes the Plan-I P4-S1 state. What remains unproven is **live execution itself** (SDK-surface mismatches: task-name namespacing, `run_workflow` payload shape, gRPC `host_port` routing). |
| `CapabilityReporter` must never report `active` without verified live connectivity | CONTRACTS.md:63; capability.py | **Gap:** no real connectivity probe exists in code (ADVERSARIAL T1 verified). `_require_production_path` (test_api_boundary_e2e.py ~108) skips even against a fully live stack. A connectivity probe must be added for the E2E to run honestly. |
| `python-multipart` is an undeclared-but-runtime-required dep for multipart ingest; starlette imports `python_multipart` (0.0.14 broke the namespace, 0.0.16 fixed it; pin 0.0.32 correct) | qa-reviewer L18; pyproject:42-45; ADVERSARIAL tech table | The CI failure was the missing (uncommitted) package — commit the pin; the multipart failure is NOT an import-name mismatch. |
| FFmpeg and PG-17 client tools must be provisioned in CI (ubuntu-latest has no ffmpeg; ships PG-16 client; PGDG `noble-pgdg` + `postgresql-client-17` is the fix) | validation.yml:163-178 (already added, uncommitted); ADVERSARIAL tech table | test-postgres job installs ffmpeg + postgresql-client-17 + sets `UMD_PG_BIN`; this was absent at the tested SHA. |
| Readiness line contract: `worker ready: registered {N} Hatchet workflows (candidate, pending Plan J live validation)`, printed **BEFORE** the blocking `client.worker(...).start()` with flush; `wait-for-worker.sh` greps `worker ready: registered`; literal `worker ready` absent from cli.py | HATCHET_LIVE_VALIDATION_HANDOFF §3; exec-manager L80/L82; wait-for-worker.sh:35 | The P2-S3 "print after start() returns" clause was unsatisfiable on SDK 1.38.1 (start() blocks forever) — corrected to print-before. wait-for-worker.sh:35 was modified (manager-accepted deviation) to match. |
| No Docker-in-Docker, no host socket mount, no containerised-setup action; native hosted-runner Compose engine only | DD-ci-repair R2/preferences; validation.yml header | docker-e2e drives the host runner's native engine; teardown `down -v` in `if: always()` + `continue-on-error`. |
| `HATCHET_COOKIE_SECRET`/`HATCHET_MASTER_KEY` stay **required** (`${VAR:?}`) — do not weaken the test or remove the interpolation | qa-reviewer L18; debugger H3; R2 | The Compose-test failure in unit/postgres jobs is a setup mismatch (secrets only exported in the docker job); fix is to export the secrets in the jobs that collect the Compose test — not to weaken the assertion. |
| Actions pinned: checkout@v4, setup-python@v5, upload-artifact@v4 (v3 deprecated 2024-11-30) | validation.yml; ADVERSARIAL tech table | Not defects; optional bumps only. |
| Canonical nested env names (`UMD_POSTGRES__DSN`, `UMD_OCFL__ROOT`, `UMD_PROJECTION__VECTOR_HNSW_MIN_VERSION`) via pydantic `env_nested_delimiter="__"`; single-underscore names silently ignored | exec-manager L38-L44; qa-reviewer L11-L13 | Established in Plan E; the workflow/compose surface must use `__` form. |

---

## 5. Known failures / dead ends (do NOT repeat)

1. **Run 33164294061 (commit a6b1a62) — the failing run.** Hosted evidence: Ruff lint PASS, strict mypy PASS (173 files), **Unit FAIL 1**, **PostgreSQL FAIL 14**, **Docker E2E FAIL before startup**. JUnit: Postgres `14 failed, 550 passed, 17 skipped`; unit `1 failed, 364 passed, 16 skipped, 200 deselected`. (debugger report §Run-level evidence; artifacts `unit-test-results` 9682936266, `postgres-test-results` 9682972550, `docker-e2e-evidence` 9682930252.)
2. **Multipart: `AssertionError: The \`python-multipart\` library must be installed to use form parsing.`** — six failures at `test_api_contract.py:967/:997` + `test_phase4_heterogeneous_ingestion.py`; traceback terminates at `starlette/requests.py:276`. **Root cause:** dep undeclared + not installed at tested SHA (not an import-name mismatch). (debugger H2.)
3. **Media: `FileNotFoundError: 'ffmpeg'`** — six failures (generated video fixture + video integration/production paths). **Root cause:** no ffmpeg install step in test-postgres job at tested SHA. (debugger H2.)
4. **Backup: `FileNotFoundError: '/usr/lib/postgresql/17/bin/pg_dump'`** — PG-17 client not installed; ubuntu-latest ships PG-16 client which aborts against a PG-17 server. Fix = PGDG `postgresql-client-17`. (debugger H2; ADVERSARIAL tech table.)
5. **Compose test: `required variable HATCHET_COOKIE_SECRET is missing a value`** — two failures (unit + postgres jobs) at `test_deployment_phaseE.py:248`. **Root cause:** secrets only exported in the docker job, not the jobs collecting the Compose test. Do NOT remove `${VAR:?}`. (debugger H3; R2.)
6. **Docker E2E: `Hatchet ... ghcr.io/v2/hatchet-dev/hatchet/manifests/v0.105.2: denied`** at `2026-08-28T10:41:47Z` before any service up; all later steps skipped. **Root cause open:** the log proves only the denial — do NOT infer private/tag/auth without a separate live pull check. The top-level image path is suspect (real images are sub-paths `hatchet-engine`/`hatchet-admin`/`hatchet-migrate`/`hatchet-lite`). (debugger H4; ADVERSARIAL tech table.)
7. **Product gap (the reason a CI-only fixer is unsafe):** `src/umd/api/app.py` imports/instantiates `DurableDAGRunner` (52-54, 167-168) instead of `ProductionDAGRunner`, so the API executes the in-process synchronous runner, not the required Hatchet path (R4). (debugger §3.1.)
8. **Dedicated live-Hatchet shape tests not release evidence** — see §4 (RecordingClient defect + `CapabilityReporter` has no connectivity probe). (debugger §3.2/3.3; ADVERSARIAL T1.)
9. **CI-only hypothesis ELIMINATED** (support-debugger L3): failures span missing runtime packaging, missing native binaries, missing Compose vars, an inaccessible image, and an application scheduler wiring defect. Lint+mypy passing cannot establish deployment/runtime correctness.
10. **Prior fixer dead-ends worth knowing** (exec-fixer log): monkeypatching/venv-inspection stalls (L71 fixer timeout — SDK not installable into shared .venv); `client.submit_workflow_run` does not exist on real SDK (needs adapter; L7/L8/L71); `Hatchet.worker` is a **method** requiring a name (not a property) and `Worker.start()` blocks forever (L8/L80/L81); `sdk.Hatchet(api_url=, token=)` raises TypeError in 1.38.1 — use `sdk.ClientConfig(token=...)` + `host_port` from `urlsplit(...).hostname:7070` (L7); `runs.admin_client().run_workflow(name, str(input))` is the public submit route (L7).

---

## 6. Plan J status (the CI-repair plan)

**`artifacts/plans/pending/TASK-universal-media-decomposer-J-api-boundary-ci-release.md`** — 4 phases / 16 steps.

- **Phase 1 (spec-first public-boundary E2E): DONE.** `tests/test_api_boundary_e2e.py` (HTTP-only; heterogeneous sources; correction→invalidation→selective rerun; restart/duplicate/retry/consistency) + `tests/test_api_boundary_guardrails.py` (4 PASS).
- **Phase 2 (hosted Docker workflow): DONE (static only).** `.github/workflows/validation.yml` + 4 scripts; native engine; worker readiness as hard gate. Container behavior NOT yet proven (no local Docker daemon; proven by hosted GitHub Actions only).
- **Phase 3 (docs + capability/release matrix): NOT STARTED** — hard-gates on "behavior and workflow pass".
- **Phase 4 (final QA + adversarial release review): NOT STARTED.**

**Blocked status (exec-manager L57; support-debugger L2):** Phases 3–4 are dependency-blocked until (a) prereq plans G/H/I complete (all now complete per L79/L82/L87), AND (b) a hosted CI run is green. No hosted run has succeeded yet; the only hosted run (33164294061) failed. Local green results are NOT release evidence under R1/R4/R6.

**Plan J coordination notes for a resumed session** (exec-manager L57, L82):
- (a) `app.py:167-168` still wires `DurableDAGRunner` interim path — rewire to `ProductionDAGRunner` REQUIRED before release evidence.
- (b) The three `test_live_hatchet_*` dedicated tests are defective — repair or exclude honestly (see §4 nuance).
- (c) Named volumes must persist across restart segments (restart uses `stop`/`start`, teardown `down -v` only at the very end).
- (d) Worker readiness must be verified via real SDK loop start (`worker ready: registered` line emitted before blocking start).
- (e) `/v1/capabilities` must expose the scheduler/worker capability under a shape the boundary gate probes (`scheduler`/`worker` dict entries with `status|state|active` in `('active','ready',True)` or `scheduler_active`/`worker_active` booleans), or the E2E gate never flips.
- (f) Plan G P3-S4 binary multipart upload contract (source_id/work_id/job_id/consistency_token per source) is a hard dependency of the boundary ingest path.

---

## 7. Open questions (unresolved, from prior work)

1. **Hatchet image pull denial — root cause.** Whether `ghcr.io/hatchet-dev/hatchet:v0.105.2` is private, the tag is unavailable, the path is wrong, or GHCR auth is required is UNDETERMINED (debugger H4, verdict "CONFIRMED for this run; the underlying registry cause remains open"). A separate live pull check (or `docker manifest inspect` pre-flight per Approach C) is required. The top-level path is suspect — real images are sub-paths.
2. **Candidate pin validity.** SDK 1.38.1 ↔ server v0.105.2 remain CANDIDATE until live shape tests pass on a real cluster. No run has ever executed against a live cluster, so SDK-surface mismatches (task-name namespacing, `run_workflow` payload shape, gRPC `host_port` routing) are untested (ADVERSARIAL T1; exec-manager L81/L82).
3. **Worker image/package composition.** `pyproject.toml:75-81` puts `hatchet-sdk==1.38.1` in the optional `worker` extra, but `deploy/Dockerfile:32` runs `pip install .` without the worker extra. Whether the worker image actually contains the SDK is an explicit packaging decision/plan (debugger §2.2 item 3).
4. **Capability connectivity probe.** `CapabilityReporter` has no reachability check (ADVERSARIAL T1). The design must add one for the boundary E2E to run honestly against a live stack.
5. **`DurableDAGRunner` vs `ProductionDAGRunner` reconciliation of async status semantics.** `ProductionDAGRunner.run_graph` submits queued Hatchet work; current `JobService.submit` refreshes status immediately. Queued/running/complete observation must be reconciled with callback-owned `DurableStageExecutor` completion without substituting synchronous execution or fabricating completion (debugger §3.4).
6. **Whether the repair adopts Approach A/B/C/D** (from the adversarial log) is a design decision, not a corpus fact. Top pick was A (Commit-and-Wire) with C's pre-flight `docker manifest inspect` folded in.
7. **`_RecordingClient`/executor=None shape tests** — confirmed defective in the handoff §6, but the current committed file uses a real-client shape (ADVERSARIAL T1). Whether the release gate treats them as needing repair or as superseded by the boundary E2E is an open design/release-gate decision (exec-manager L82(b)).

---

## 8. no_relevant_artifacts / corpus health

- **No ADRs exist** (`artifacts/decisions/` absent) and **no ASRs exist** (`artifacts/requirements/` absent). Decision capture in this corpus is via design docs, logs, and CONTRACTS.md. ADR/ASR workflows were correctly skipped.
- **Adversarial-log "missing artifact" note is now resolved** — `universal-media-decomposer-ci-repair-debugger.md` exists on disk (untracked); it was absent only at T1 ideation time (logged by this librarian as L14).
- **No earlier dead-end/failed CI-repair attempt exists** — this is the first repair cycle; the only prior hosted run is 33164294061. No prior plan proposed a second scheduler.
- Working tree has many uncommitted changes relevant to the repair (validation.yml, pyproject.toml python-multipart + worker extra, deploy/pins, production.py, tests/conftest.py, test_deployment_phaseE.py, plus the untracked DD-ci-repair/ADVERSARIAL/debugger artifacts). These were NOT present at the tested SHA a6b1a62 and therefore cannot explain run 33164294061 — but must be committed and re-run on GitHub to prove the repair.

---

## 9. Suggested reading order for the repair designer

1. `artifacts/designs/process/universal-media-decomposer-ci-repair-debugger.md` (authoritative diagnosis)
2. `artifacts/designs/pending/DD-universal-media-decomposer-ci-repair.md` (R1–R6 + anti-patterns)
3. `artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-ci-repair.md` (approaches A–D + tech validation)
4. `artifacts/designs/parts/universal-media-decomposer/HATCHET_LIVE_VALIDATION_HANDOFF.md` (release gate §8, defect report §6)
5. `artifacts/plans/pending/TASK-universal-media-decomposer-J-api-boundary-ci-release.md` (plan + blocker notes)
6. `.github/workflows/validation.yml` + `.github/scripts/wait-for-worker.sh`
7. `artifacts/plans/handoff-G-to-I-J.md` §5 (startup assumptions)
