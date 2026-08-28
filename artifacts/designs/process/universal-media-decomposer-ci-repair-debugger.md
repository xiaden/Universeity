# Universal Media Decomposer CI Repair Diagnosis

**Run:** [GitHub Actions run 33164294061](https://github.com/xiaden/Universeity/actions/runs/33164294061)  
**Repository:** `xiaden/Universeity`  
**Commit tested:** `a6b1a62f8413655b9908b40e4fc7a484828364e0`  
**Workflow:** `validation`  
**Observed:** 2026-08-28  
**Status:** `DIAGNOSED`  
**Scope:** Read-only support diagnosis. No source, test, workflow, plan, or documentation implementation was performed.

## Executive diagnosis

This is not one fixable test typo. The run exposed independent workflow/environment defects and a product integration gap at the production scheduler boundary. The release gate is therefore **`NEEDS_PLAN`**. A fixer-only pass would be unsafe: it could make the jobs green while leaving the required Hatchet execution path absent or unproven.

The correct process is Support diagnosis (this report) -> R&D design/repair plan cross-checked against `Task.md` -> Exec-Manager implementation -> push to GitHub -> retrieve and inspect a new hosted run. No local green result is release evidence under R1/R4.

## Run-level evidence

| Job | Result | Evidence |
|---|---:|---|
| Ruff lint | PASS | Run metadata: job `98825909969` |
| Strict mypy | PASS | Run log: `Success: no issues found in 173 source files` |
| Unit tests | FAIL: 1 | Job `98825910133`; artifact `unit-test-results` (`9682936266`) |
| PostgreSQL integration | FAIL: 14 | Job `98825910085`; artifact `postgres-test-results` (`9682972550`) |
| Docker E2E | FAIL before startup | Job `98825909849`; artifact `docker-e2e-evidence` (`9682930252`) |

The complete hosted JUnit report records `14 failed, 550 passed, 17 skipped` for PostgreSQL and the unit report records `1 failed, 364 passed, 16 skipped, 200 deselected` (`/tmp` copies were downloaded from the GitHub artifacts during diagnosis). The raw failure text was retrieved from those artifacts/logs; no error text below is invented.

## Hypotheses and evidence

### H1 — The run has only a test assertion regression

**Likelihood:** LOW  
**Verdict:** ELIMINATED.

The failures span missing Python runtime packaging, missing native binaries, missing Compose interpolation variables, an inaccessible container image, and an application scheduler wiring defect. Lint and strict mypy passed, but that does not validate deployment or runtime integration.

### H2 — CI jobs do not provision the runtime dependencies exercised by the tests

**Likelihood:** HIGH  
**Verdict:** CONFIRMED.

Hosted PostgreSQL logs show:

* Six multipart tests fail at `tests/test_api_contract.py:967`, `:997`, and the multipart-backed cases in `tests/test_phase4_heterogeneous_ingestion.py` because Starlette raises exactly: `AssertionError: The \`python-multipart\` library must be installed to use form parsing.` The traceback terminates at `starlette/requests.py:276`.
* Six media tests fail with `FileNotFoundError: [Errno 2] No such file or directory: 'ffmpeg'` (the generated video fixture and video integration/production paths).
* The backup test fails with `FileNotFoundError: [Errno 2] No such file or directory: '/usr/lib/postgresql/17/bin/pg_dump'`.

At the tested commit, the PostgreSQL job proceeds from checkout/setup directly to `pip install` and pytest; it has no FFmpeg or PostgreSQL-client installation step. The target run's installed-package output also does not contain `python-multipart`. The current worktree contains an uncommitted `pyproject.toml:42-45` addition and workflow installation changes, but those were not present in the GitHub checkout at the tested SHA and therefore cannot explain or repair run 33164294061.

Relevant source contracts are `src/umd/api/routers/sources.py:_ingest_source` (multipart form parsing), `tests/conftest.py:28-46` (the `pg_dump` resolution contract), and `tests/fixtures.py:478` (FFmpeg-generated video fixture).

### H3 — Compose validation/startup is misconfigured independently of the application

**Likelihood:** HIGH  
**Verdict:** CONFIRMED.

The unit and PostgreSQL JUnit reports both contain the exact failure:

```text
AssertionError: docker compose config failed: error while interpolating services.hatchet.environment.SERVER_AUTH_COOKIE_SECRET: required variable HATCHET_COOKIE_SECRET is missing a value
```

The failure is at `tests/test_deployment_phaseE.py:248` in the tested checkout. The Compose contract is explicit at `deploy/compose.yaml:101-111`: `HATCHET_COOKIE_SECRET` and `HATCHET_MASTER_KEY` use required `${VAR:?}` interpolation. The workflow creates those variables only in the Docker job (`.github/workflows/validation.yml:224-235` in the current file), not in the unit/PostgreSQL jobs where the Compose test is collected. Thus the test is correctly exposing an environment/setup mismatch, not a product assertion problem. A required secret must remain required; removing `${VAR:?}` or weakening the test would violate R2.

### H4 — The Docker E2E failed because the candidate Hatchet image could not be pulled

**Likelihood:** HIGH  
**Verdict:** CONFIRMED for this run; the underlying registry cause remains open.

The Docker job's failed startup step (`Build API/worker image and start pinned Compose stack`) records the exact daemon response:

```text
hatchet Error Head "https://ghcr.io/v2/hatchet-dev/hatchet/manifests/v0.105.2": denied
Error response from daemon: Head "https://ghcr.io/v2/hatchet-dev/hatchet/manifests/v0.105.2": denied
```

This occurred at `2026-08-28T10:41:47Z`, before any service became available. The subsequent readiness, HTTP, public-boundary, restart, and release-summary steps were skipped. Artifact `docker-e2e-evidence` contains only the pre-start diagnostics (`compose-ps.txt` has no services and the probes report endpoint not ready), consistent with failure before stack creation. Do not infer whether the image is private, the tag is unavailable, or GHCR authentication is required without a separate live pull check; the hosted log proves only the denial.

## Defect classification

### 1. Workflow/environment defects

These explain observed CI failures but do not by themselves prove the application correct:

1. **CI dependency provisioning gap:** the tested PostgreSQL job does not install `ffmpeg`, `ffprobe`, or PostgreSQL 17 client tools, while the selected tests require them (`.github/workflows/validation.yml` target job; failures listed in the hosted JUnit artifact).
2. **Multipart packaging mismatch:** the tested dependency set does not install the import that Starlette requires for `Request.form()`; `src/umd/api/routers/sources.py:259` calls `await request.form()`.
3. **Compose-test environment mismatch:** required Hatchet secrets are not exported in the unit/PostgreSQL jobs, while `deploy/compose.yaml:106-107` rejects missing values.
4. **Candidate image pull/environment gate:** `ghcr.io/hatchet-dev/hatchet:v0.105.2` is denied by GHCR in the hosted Docker job. The candidate pin is explicitly pending live validation in `deploy/pins/runtime.txt:47-63` and `HATCHET_LIVE_VALIDATION_HANDOFF.md:18-38`.
5. **Container runtime tool gap to verify during repair planning:** `deploy/Dockerfile:26-32` installs Python dependencies only and does not install FFmpeg or PostgreSQL client tools. Even after host CI provisioning is repaired, the actual API/worker image must be checked against the Task.md Docker/modality requirements; host tools cannot be assumed to exist inside the container.

### 2. Genuine deployment gaps

These are release-relevant gaps, not acceptable reasons to skip tests:

1. **The required live stack never starts in run 33164294061.** Consequently there is no evidence for migrations, API readiness, worker callback registration, real Hatchet stage execution, persistence across restart, or the public API E2E. The Docker evidence is a failed startup, not a gated pass.
2. **Hatchet candidate pair is unvalidated.** The repository records SDK `1.38.1` and server `v0.105.2` as candidates, but the image pull was denied and the hosted real execution path did not run. Candidate values must not be promoted to validated release pins until a real pull/connectivity/execution test succeeds.
3. **Worker image/package composition must be proven.** `pyproject.toml:75-81` places `hatchet-sdk==1.38.1` in the optional `worker` extra, while `deploy/Dockerfile:32` runs `pip install .` without the worker extra. The worker role in `deploy/compose.yaml:81-99` therefore requires an explicit packaging decision/plan; it cannot be assumed that the worker image contains the SDK.
4. **The release gate is currently structurally bypassable.** The workflow comments and conditional startup/readiness path (`.github/workflows/validation.yml:208-268`) make live worker validation opt-in and default Docker startup limited to `db api`. This conflicts with R4 and the handoff's hard release gate (`HATCHET_LIVE_VALIDATION_HANDOFF.md:232-241`). Changing the gate to skip more is not a repair.

### 3. Product integration gaps

These are the reasons a CI-only fixer would be insufficient:

1. **Production API uses the wrong runner.** `src/umd/api/app.py:94-101` documents the interim wiring and imports `DurableDAGRunner` at `:52-54`; `build_context` instantiates it at `:167` and passes it to `JobService` at `:168`. `src/umd/jobs/runner.py:263-296` defines `ProductionDAGRunner`, whose contract is to submit each stage to the sole Hatchet scheduler, but `app.py` does not construct or inject it. The current API path therefore executes the in-process synchronous runner rather than proving the required production Hatchet path. This is a genuine implementation/integration gap under R4, not a missing CI package.
2. **The existing dedicated live-Hatchet tests are not release evidence as currently described by the handoff.** `HATCHET_LIVE_VALIDATION_HANDOFF.md:184-202` records that the three shape tests use `_RecordingClient` with `executor=None`; the recording submit method records submissions but does not invoke callbacks, so no durable `stage_run` rows can demonstrate execution. `tests/test_hatchet_live.py:920-1006` contains the shape-test assertions, but a test that only records submission or uses an in-process double cannot satisfy R4's real callback/execution gate. The tests must be repaired as part of a plan, not made green by changing assertions or adding skips.
3. **The public-boundary E2E is currently self-gating on active scheduler/worker capability.** `tests/test_api_boundary_e2e.py:108-137` skips unless `/v1/capabilities` reports an active scheduler/worker. `src/umd/jobs/capability.py:46-84` correctly refuses to claim `active` without verified live connectivity, but the combination means the E2E is not release evidence until the API is wired to the real production runner and the worker is live. A capability-based skip is appropriate for an unconfigured local developer environment, not for the hosted mandatory release job.
4. **The API's asynchronous contract is not yet connected end-to-end.** `ProductionDAGRunner.run_graph` submits queued Hatchet work (`src/umd/jobs/runner.py:276-296`), while the current `JobService.submit` path invokes the runner and immediately refreshes status (`src/umd/application/jobs.py:90-116`). The design must reconcile queued/running/complete status observation with callback-owned `DurableStageExecutor` completion; it must not substitute synchronous execution or fabricate completion.

## Cross-check against `Task.md` and immutable requirements

The failed run does not satisfy the following mandatory Definition-of-Done items:

* **Task.md §23 / §40 items 21 and 31:** durable asynchronous jobs must survive restart, and Docker deployment must work. The Docker job failed before startup.
* **Task.md §26 / §40 items 5-8 and 29:** real representative text, image, audio, and video decomposition plus heterogeneous fixtures. Six FFmpeg failures and six multipart failures prevented the PostgreSQL evidence suite from exercising these paths.
* **Task.md §§1-2, 7, 16 / §40 items 10-11, 16, 19-20:** source/evidence/semantic separation, immutable provenance, user correction, descendant-only invalidation, and stage rerun. These cannot be release-proven through the current synchronous API wiring or a recording Hatchet client.
* **Task.md §23 and R4:** Hatchet must be the sole v1 scheduler, with real callback registration and real stage execution as a release gate. `DurableDAGRunner` in `app.py` and the defective recording-client shape tests do not meet this requirement.
* **Task.md §40 items 32-35:** static checks passing is insufficient; automated integration tests, final adversarial review, and repair/rerun of the complete validation suite remain required. Plan J phases 3 and 4 are explicitly not started.

The following constraints remain binding for any downstream design/implementation:

* Never repair this by stubbing stages, unconditionally skipping failures, weakening assertions, or claiming readiness without real callback bindings (R2).
* Preserve all source/evidence/semantic/provenance, immutable-byte, representative-modality, correction/invalidation, restart, and selective-rerun obligations from `Task.md` (R3).
* Do not add a second scheduler; use Hatchet as the sole v1 scheduler (R4).
* Flow this diagnosis into R&D design, then an implementation plan, then Exec-Manager (R5).
* The prior local `392 passed / 189 skipped` result and static checks are context only; they are not hosted release evidence (R6).

## Root cause

```yaml
rootCause:
  type: MULTIPLE_INDEPENDENT_CI_AND_PRODUCT_INTEGRATION_DEFECTS
  location:
    workflow: .github/workflows/validation.yml
    application: src/umd/api/app.py:52-54,167-168
    scheduler_seam: src/umd/jobs/runner.py:263-296
  explanation: >-
    The hosted run executes a dependency-incomplete and environment-incomplete
    validation matrix (missing python-multipart, ffmpeg, pg_dump, and Compose
    interpolation variables), and its Docker job cannot pull the candidate Hatchet
    image. Independently, the production API still injects DurableDAGRunner rather
    than ProductionDAGRunner, while the available recording-client Hatchet tests do
    not prove callback execution. Therefore the mandatory real Hatchet production
    path and the hosted Docker release evidence do not exist for this run.
  affectedFiles:
    - .github/workflows/validation.yml
    - deploy/compose.yaml
    - deploy/Dockerfile
    - pyproject.toml
    - tests/conftest.py
    - tests/test_deployment_phaseE.py
    - tests/test_hatchet_live.py
    - tests/test_api_boundary_e2e.py
    - src/umd/api/app.py
    - src/umd/application/jobs.py
    - src/umd/jobs/runner.py
    - src/umd/jobs/hatchet.py
    - src/umd/jobs/capability.py
    - src/umd/deploy/cli.py
```

## fixComplexity

```yaml
fixComplexity: NEEDS_PLAN
```

The repair crosses workflow provisioning, Python/native/container dependencies, Compose/GHCR deployment, API application wiring, Hatchet worker packaging and connectivity, live callback test design, asynchronous job status semantics, and the Task.md release matrix. It is not a single function or section and is not eligible for `SIMPLE`/Exec-Fixer routing.

## Suggested routing (not an implementation)

No `suggestedFix` field is supplied because the complexity is not `SIMPLE`. R&D should turn the confirmed findings into a coordinated repair design and implementation plan, explicitly preserving the Task.md ledger and the Hatchet-only release gate. Exec-Manager should execute that plan only after the design/plan gate. Completion requires pushing the implementation to GitHub and retrieving a new run's logs/artifacts; local checks alone cannot close this diagnosis.

## Evidence index

* Hosted run: <https://github.com/xiaden/Universeity/actions/runs/33164294061>
* Docker job: <https://github.com/xiaden/Universeity/actions/runs/33164294061/job/98825909849>
* PostgreSQL job: <https://github.com/xiaden/Universeity/actions/runs/33164294061/job/98825910085>
* Unit job: <https://github.com/xiaden/Universeity/actions/runs/33164294061/job/98825910133>
* PostgreSQL artifact `postgres-test-results`, ID `9682972550`
* Unit artifact `unit-test-results`, ID `9682936266`
* Docker artifact `docker-e2e-evidence`, ID `9682930252`
* `artifacts/designs/parts/universal-media-decomposer/HATCHET_LIVE_VALIDATION_HANDOFF.md:184-202,232-241`
* `artifacts/designs/parts/universal-media-decomposer/CONTRACTS.md:58-63`
* `artifacts/plans/pending/TASK-universal-media-decomposer-J-api-boundary-ci-release.md:38-49`
* `artifacts/logs/exec-manager.log.jsonl:L57-L67` (Plan J dependency block and Hatchet/live-validation history)
