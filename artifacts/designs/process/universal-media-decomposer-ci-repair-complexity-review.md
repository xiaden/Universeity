# Universal Media Decomposer CI Repair — Semantic Complexity Review

**Agent:** rnd-complexity-advisor
**Date:** 2026-08-28
**Scope:** Read-only structural review of the proposed UMD evidence-backed GitHub CI repair (DD skeleton `artifacts/designs/pending/DD-universal-media-decomposer-ci-repair.md`) against the verified tree at HEAD `a6b1a62`, the debugger report (`universal-media-decomposer-ci-repair-debugger.md`), support research (support-researcher log L3/L4), and the in-flight adversarial log (`universal-media-decomposer-ci-repair-adversarial-log.md`).
**Verdict preview:** The repair's core is **requirement-mandated, justified complexity** — but four proposed additions (split job, preflight probe subsystem, probe-as-gate, and the durable-backend env axis) are **accidental complexity** that can be simplified without weakening R1–R5. The single most important finding is that the current release gate's *only* E2E evidence surface is vacuous in CI (skips twice over), and the design must repair that surface rather than add new ones.

---

## 1. Inputs consumed and verification method

All claims below were verified by direct reads of the committed tree at HEAD `a6b1a62` (plus the uncommitted working tree, which CI never saw) and the artifact corpus:

| Input | Used for |
|---|---|
| DD skeleton `pending/DD-universal-media-decomposer-ci-repair.md` | R1–R6 ledger, anti-pattern list, scope |
| Debugger report `universal-media-decomposer-ci-repair-debugger.md` | Failure classification, defect list, NEEDS_PLAN routing |
| Support research (support-researcher log L3/L4) | Image topology (sub-path images exist, top-level 403), SDK 1.38.1 config surface, working-tree fix safety |
| Librarian brief `universal-media-decomposer-ci-repair-librarian.md` | Corpus map, prior decisions, handoff §6/§8 |
| Adversarial log `universal-media-decomposer-ci-repair-adversarial-log.md` + `ADVERSARIAL-universal-media-decomposer-ci-repair.md` | T1–T4 content, approach A/B/C/D, surviving risks |
| Original complexity review `universal-media-decomposer-complexity-review.md` | Baseline posture (Hatchet sole scheduler, one API+worker image, DAGRunner seam) |
| Source: `src/umd/api/app.py`, `src/umd/jobs/runner.py`, `hatchet.py`, `capability.py`, `production.py`, `src/umd/application/jobs.py`, `src/umd/deploy/cli.py`, `deploy/compose.yaml`, `deploy/Dockerfile`, `deploy/pins/runtime.txt`, `.github/workflows/validation.yml`, `tests/test_hatchet_live.py`, `tests/test_api_boundary_e2e.py`, `tests/conftest.py`, `tests/test_deployment_phaseE.py`, `tests/test_capability_transitions.py`, `.env.example`, `docker-entrypoint.sh`, `wait-for-worker.sh`, `pyproject.toml` | Every claim below |

**Technology validation:** no new technology is introduced by the repair (Hatchet, GitHub Actions, python-multipart, ffmpeg/PGDG are all already in the tree or in the working-tree fixes). The one consequential version claim — the SDK↔server pair (hatchet-sdk 1.38.1 ↔ server v0.105.2) — remains a CANDIDATE per `deploy/pins/runtime.txt:47-63`, and T4 risk #1 correctly budgets the first hosted run as a discovery run. This review makes no new version recommendations; it defers to the adversarial log's EVIDENCE-BACKED/PROVISIONAL labels (checked 2026-08-28).

## 2. Verification of the adversarial log (T1–T8) — REQUIRED by scope

**State: T1–T4 complete; T5–T8 NOT YET PRESENT.**

- `universal-media-decomposer-ci-repair-adversarial-log.md` currently contains: T1 Proposed Approaches (4 approaches + ranking), T2 Critique, T3 Refined Approaches, T4 Surviving Concerns (7 ranked persisting risks). The file ends at line 249 after T4's table; no Improver/Counter-Improver turns exist.
- The rnd-refiner log confirms the process is mid-flight: "T1 verified; dispatching T2 Counter-Ideator" (2026-08-28T11:12Z).
- **Implication for DDAuthor:** the DD skeleton's footer says "DDAuthor distills the adversarial log into final decisions after all 8 turns." That condition is **not yet met**. The DD must NOT be finalized from a 4-turn debate; T5 (implementation patterns) and T6/T8 (pattern risks, open human questions) are the turns that normally surface the over-engineering concerns this review independently found (probe-as-gate machinery, split-job stacking, env-axis creep).

Content already on the record is high quality: T2's five mandatory additions to Approach 1 (probe = execution not version-ping; hard-timeout worker wait; worker-image smoke test; structural fail-closed gate; clean-resolve multipart) are all **justified complexity**. T3 correctly DROPPED approach D (Lite) and alternatives B/C. T4's persisting risks 1, 3, 4, 5 are real and must survive into the DD.

## 3. Verified current-state evidence (the tree, not the brief)

| Claim | Verified evidence |
|---|---|
| API wires the in-process durable runner, not Hatchet | `src/umd/api/app.py:167` `runner = DurableDAGRunner(...)`; `ProductionDAGRunner` (`runner.py:263-296`) is constructed **nowhere in `src/`** — only in `tests/test_hatchet_live.py:881` with a recording client |
| Wrong Hatchet image path surfaces twice | `deploy/compose.yaml:104` `ghcr.io/hatchet-dev/hatchet:${HATCHET_VERSION:-v0.105.2}` (top-level; 403-denied per hosted log) AND `src/umd/jobs/hatchet.py:56` `HATCHET_SERVER_IMAGE` same wrong path (surfaced via `/v1/capabilities`). Research L3/L4: all 5 sub-path images return 200 at v0.105.2 |
| Worker container cannot import the SDK | `deploy/Dockerfile:32` `pip install .` (no `[worker]` extra); `pyproject.toml:79-81` `worker = ["hatchet-sdk==1.38.1"]` → `cli.worker()` exits 2 at `hatchet_sdk` ImportError |
| Worker service cannot reach Hatchet even if packaged | `deploy/compose.yaml:81-99` `worker` env sets only `UMD_ROLE: worker` + the api env anchor — **no `UMD_HATCHET_SERVER_URL`/`UMD_HATCHET_TOKEN`** → `cli.py:49-57` exits 2. The workflow's defaults (`validation.yml:233-234`) are `http://hatchet:8080` + non-JWT `umd-ci-token`, which the SDK's `ClientConfig` rejects (research L4: token must be a JWT). `cli.py:106` additionally hardcodes gRPC `:7070` |
| Capability reporter has NO connectivity probe | `src/umd/jobs/capability.py:46-84`: returns `configured-but-unavailable` whenever env vars are set; docstring claims "a reachable client flips it to active" but no reachability check exists. `_require_production_path` (`test_api_boundary_e2e.py:108-138`) therefore skips even against a live stack |
| The release gate is structurally bypassable | `validation.yml:208-214` `UMD_VALIDATE_LIVE_WORKER` defaults `false`; `:245-249` default compose-up is `db api` only; `:265-268` worker readiness is `if: env.UMD_VALIDATE_LIVE_WORKER == 'true'` |
| The "boundary E2E against the live stack" step is vacuous twice over | (1) `tests/test_api_boundary_e2e.py` builds its **own in-process app** via `TestClient(create_app(...))` over the `umd_db`/`source_store` fixtures — it never touches the live container; (2) `migrated_db` (conftest:86-124) skips unless `UMD_TEST_POSTGRES=true`, which the docker-e2e job never sets, and the compose `db` service publishes **no port** (`compose.yaml:35-52`), so host pytest cannot reach compose Postgres anyway; (3) `_require_production_path` then skips all four scenario tests on capabilities. Result: **zero assertions** from the file in CI |
| The three live shape tests are real bindings but are executed by NO CI job | `test_hatchet_live.py:920-1006` use `_real_client()` + real `DurableStageExecutor` + `_poll_until` (contradicting handoff §6's RecordingClient description — that defect describes the Plan I P4-S1 state). They are `cluster`-marked and require `umd_db` + a reachable Hatchet; no workflow step runs them. Note they run `work_registry={s: _ok ...}` — a stub stage work that always succeeds (line 939/969/996) |
| Worker runtime is thin even after reachability | `cli.py:96-97` `runtime: dict[str, Any] = {"engine": engine}` — no `source_store`, `sandbox`, `artifacts`, `builders`, `replay`, `providers`. `production.py` degrades every real binding to deterministic refs with warnings when deps are absent, so the production worker would execute *degraded* stage work, unlike `app.build_context` which wires the full runtime (`app.py:134-153`) |
| The four dependency/env fixes are mechanical, verified, and uncommitted | `pyproject.toml:42-45` python-multipart pin; `validation.yml:163-178` ffmpeg + PGDG postgresql-client-17 step; `tests/conftest.py:34-46` `_resolve_pg_bin`; `tests/test_deployment_phaseE.py:249-251` `env.setdefault` for the compose-config test. None changes product semantics; all must simply be committed and re-run hosted (R1/R6) |

## 4. Justified complexity (keep — required by R1–R5 / Task.md)

These are the repair's real content. They are **production wiring**, not decoration:

1. **Commit the five uncommitted dependency/env fixes** (python-multipart, ffmpeg, PGDG client, `_resolve_pg_bin`, compose-secret provisioning). Zero design decisions; mandatory under R2 (they fix real defects) and R1 (they only count hosted).
2. **Repair the Hatchet topology in compose + adapter pin surface** (`compose.yaml:104`, `hatchet.py:56`, runtime.txt, pin-agreement test must agree on one sub-path image). The official engine requires config mount + `SERVER_GRPC_*` envs (T3/T4) — genuine deployment wiring the current compose does not model.
3. **Wire `ProductionDAGRunner` into `app.py`** when a Hatchet client is configured (the R4 seam already exists; `submit_workflow_runs` at `runner.py:202-260` and the `_SDKSubmissionShim` at `hatchet.py:140-158` are the documented bridges). This is the one-line-ish product fix the debugger §3.1 requires.
4. **Install `[worker]` extra in the one image** (`Dockerfile:32` → `pip install .[worker]`), preserving `cli.py`'s honest exit-2 gate and the pinned `test_worker_missing_sdk_exits_2` behavior.
5. **Provision real worker connectivity** (valid JWT token, correct server URL/ports for the chosen topology, `HATCHET_CLIENT_HOST_PORT` where needed). Fixing `cli.py:106`'s `:7070` hardcode is part of this.
6. **A single honest connectivity signal** so `/v1/capabilities` can truthfully report the scheduler/worker state (see F6 for how small this should be).
7. **Flip the gate: the live path is mandatory in the hosted docker-e2e job**, and the boundary E2E / shape tests actually execute there (F1/F2).
8. **CI hygiene additions T2 already justified:** worker-readiness hard timeout (already bounded at 240s in `wait-for-worker.sh`; tuning against measured cold boot per T4 risk #2), worker-image smoke test, machine-readable gate line, pre/post namaste + stage_run assertions around the restart segment (T4 risk #5).

Keep the existing `test_hatchet_release_pin_is_single_validated_and_agreed` (`test_hatchet_live.py:1044-1097`) as the static cross-surface authority — it already does the right thing and needs no expansion.

## 5. Accidental complexity (simplify or drop)

### F1 (HIGH confidence) — The release E2E surface is vacuous; repair the one scenario, do not add another

`tests/test_api_boundary_e2e.py` is the acceptance spec for the production path, but in CI it contributes **zero assertions**: it is in-process (TestClient over a throwaway DB), it cannot reach compose Postgres (no published port, no `UMD_TEST_POSTGRES` in the docker-e2e job), and it self-skips on capabilities. The workflow's step name "Run the public-boundary E2E scenario against the live stack" describes something the file does not do.

**Recommendation:** give the scenario a **transport switch** — one file, two modes:
- Hermetic: `TestClient` (as today) for local/PR postgres runs.
- Live: an `httpx.Client(base_url=os.environ["UMD_LIVE_API_URL"])` transport when that env is set, selected in the `api_ctx` fixture.
The docker-e2e job sets `UMD_LIVE_API_URL=http://127.0.0.1:8080` (+ publishes the db port only if the shape tests need host-side Postgres — see F2). In the release job, `_require_production_path` must **FAIL** rather than skip when capabilities are not active (T4 risk #3) — a one-var rule (`UMD_RELEASE_GATE=1` turns the skip into a failure), not a new framework.

This removes the duplication (three surfaces today: in-process scenario + curl smoke + shape tests) by consolidating the scenario to two transports instead of adding a second E2E file.

### F2 (HIGH confidence) — The live shape tests are the R4 gate and are executed by no job; the worker must run the same real stage work as the API path

Two gaps, one fix each:

1. **Execution:** the three `test_live_hatchet_*` tests must run in the docker-e2e job (or a step that owns them) against the live stack — either in-network (`docker compose run --rm`) or host-side with the engine gRPC port published. This is what R4's "live worker callback registration and real stage execution are a release gate" means; a readiness-line grep is not stage execution.
2. **Real stage work:** the shape tests use `_ok` stub work (they prove scheduler/worker/executor wiring — correct), but `cli.py`'s worker assembles only `{"engine": engine}`, so even a live worker would run degraded stage work (warnings, deterministic refs) instead of the real media branches `app.build_context` wires. **The single highest-leverage simplification in the repair:** extract the full runtime assembly (`app.py:134-153`) into one shared function used by BOTH `app.build_context` and `cli.worker`. One definition of "real stage work"; no second wiring path to drift.

This also resolves the debugger's §3.4 async-status concern for free: status is already derived from durable `stage_run` rows (`application/jobs.py:313-323`), so once callbacks write rows, the public status model works — no new status machinery.

### F3 (HIGH confidence) — Flip the gate in the existing job; do not add a second docker job (B)

`UMD_VALIDATE_LIVE_WORKER` default-false + `db api`-only start + opt-in wait-for-worker is exactly the "CI green by exclusion" anti-pattern the DD's own list forbids. The fix is to make the existing docker-e2e job always start `db api hatchet worker` and always run the gate.

The T1/T3 "Split-Job CI" (B) is **not needed**: the `test-postgres` job already provides the fast non-container feedback loop; the split adds a second job definition, duplicated provisioning, image-build reuse machinery, and — the real trap — path filters that drift from the code they gate (T2's own critique). If the team still wants B after A is green, it must come with the exhaustive filter list T3 already drafted and shared build cache — but it should be treated as optional CI ergonomics, never as part of the repair's critical path.

### F4 (MEDIUM confidence) — Preflight manifest probes: keep as one fast-fail step, not a subsystem

`docker manifest inspect` + SDK/server pair tripwire at the top of the docker-e2e job is cheap and converts the 36s build-then-403 failure into a seconds-scale attributable failure. That is **justified** as a diagnostic step. What is **not** justified: error-classification taxonomies (403 vs 404 vs 429), retry machinery, or treating the probe as release evidence. T2's verdict is exactly right — it can never prove functionality (registries conflate "private" and "does not exist" as 403), so it must remain a complement to live execution and must not be stacked with B. Keep it to ~10 lines in the workflow.

### F5 (MEDIUM confidence) — D (Lite) is correctly dropped; accept the compose cost that follows

The adversarial process already dropped Lite for topology skew (R4 "same stack" evidence). Agree. But flag the flip side for DDAuthor: the current compose has a **single** `hatchet` service with a required-secret surface; the full sub-path topology (migrate → admin → engine + dashboard, config volume, `SERVER_GRPC_*` envs) is a **much larger compose surface**. That cost is genuine production wiring (unavoidable under R4), not accidental — but it must be budgeted as real work, and the design should not try to dodge it with a CI-only override that reintroduces skew.

### F6 (MEDIUM-HIGH confidence) — The connectivity probe must be disclosure, not a gate; do not build submit+poll machinery with a TTL cache

T3's "submit+poll probe with 30s TTL cache" is the most over-engineered element of the debate so far. The capabilities endpoint is **honest disclosure**; the release gate is **the shape tests + boundary E2E executing**. Building a cached submit+poll probe into `/v1/capabilities` adds a moving part (TTL expiry mid-E2E → T4 risk #3's skip-re-engagement) that the gate should not depend on.

**Simpler shape:**
- `CapabilityReporter` receives the *actually injected* runner/client (constructor injection from `build_context`), not env assumptions. It reports `active` when the injected backend is the Hatchet runner AND a single lightweight reachability check succeeds (SDK health/version fetch or a bounded no-op submit — whichever the first live run confirms against 1.38.1); otherwise the honest status with the failure in `reason`.
- The gate does not read the probe's TTL cache; the E2E's `_require_production_path` reads live capability state and **fails** (not skips) in release jobs.
- No caching, no poll loops in the API path. If a cached probe is truly desired later, it is a measured addition — not part of this repair.

### F7 (MEDIUM confidence) — Worker image extras: one-line change; resist multi-stage/dual-image complexity

`pip install .[worker]` in the single `Dockerfile` matches the declared "one image, two roles" posture (Dockerfile header, compose comment). Do **not** build a separate worker stage or worker Dockerfile — the roles share 95% of the dependency set and a second build target is pure maintenance surface. The `[worker]` extra stays declared in `pyproject.toml` so `cli.py`'s exit-2 gate and its pinned tests remain meaningful. Add the T3 worker-image smoke test (`import hatchet_sdk` in the built image) as the verification. Note also the `sandbox-runner` service (`compose.yaml:114-140`, `command: ["worker"]`) inherits the same image — the one-line fix covers it too.

### F8 (MEDIUM confidence) — Runner selection: prefer env-derived, not a new env axis

T1's `UMD_EXECUTION_BACKEND=durable|hatchet` env flag is an extra configuration axis the repair does not need. The existing env already decides: `UMD_HATCHET_SERVER_URL` + `UMD_HATCHET_TOKEN` present and constructible → `ProductionDAGRunner`; absent → `DurableDAGRunner` (hermetic/development). Deterministic, fail-fast (`HatchetNotConfiguredError` if a live client is required but unconstructable), and `/v1/capabilities` reports which backend is active — so there is no silent switch. If the team prefers an explicit flag for operational explicitness, that is acceptable but optional; do not build both.

### F9 (LOW-MEDIUM confidence) — Connectivity constants must have one home

`cli.py:106` (`:7070`), `validation.yml:233-234` (`http://hatchet:8080`, `umd-ci-token`), and `test_hatchet_live.py:308` (default `7070`) each encode a topology assumption. Pick the topology first (F5), then drive the server URL/ports/token from one place (compose env or `deploy/pins`) consumed by the worker service, the workflow, and the shape tests. Three files holding the same assumption is exactly the class of drift that produced the `hatchet.py`/`compose.yaml` image-path mismatch.

### F10 (LOW, note only) — Pre-existing seams to acknowledge, not expand

- `_SDKSubmissionShim` (`hatchet.py:140-158`) exists because the shared submission path calls `client.submit_workflow_run` (recording-double shape) while the real SDK exposes `runs.admin_client().run_workflow`. Justified seam; the repair must NOT add a second submission path (e.g., a "live E2E helper" calling the SDK directly) — that would duplicate the shim's job. T4 risk #1 (shim surface unproven) is correct; budget run #1 as a discovery run.
- `WorkerHandle.registered_workflows = []` class-attribute override (`hatchet.py:351`) is a dataclass-introspection workaround — a smell, but out of repair scope.
- `ProductionRuntime`'s 16-optional-field degrade machinery (`production.py:170-225`) is the documented honest-degradation design; the repair's only obligation is that `cli.worker` assembles the same full runtime (F2), so degradation is never silent in the release path.

## 6. Focus points, answered

| Focus point | Verdict |
|---|---|
| Commit-only dependency fixes vs genuine production wiring | Clean split: the 4-5 mechanical fixes are commit-only (verified, uncommitted). Genuine wiring = runner switch (F8/F2), compose topology + image path (F5), worker packaging + env (F7/F9), capability truth (F6), gate polarity (F3), and the E2E/shape-test execution surface (F1/F2). The design must not blur these: commit+push the mechanical fixes FIRST (R1), then land wiring against a real hosted run |
| Mandatory hosted live job | Required under R1+R4 and the DD's own anti-pattern list. It is the **existing** docker-e2e job with the gate always-on — not a new job, not a local Docker proof (R6). Treat hosted run #1 as a discovery run (T4 risk #1) |
| Preflight manifest probes | Justified as a ~10-line fast-fail diagnostic step (F4); not a subsystem, not release evidence |
| Capability connectivity | One lightweight probe, injected backend, disclosure-only (F6); the tests are the gate |
| Worker image extras | `pip install .[worker]` in the single image (F7); no second build target |
| Test duplication | Consolidate: one boundary scenario with a transport switch + the existing shape tests executed in CI + curl smoke (F1/F2). No new E2E files |
| B split-job risk | Not needed now; test-postgres is already the fast loop; path filters drift (F3). Optional post-green ergonomics only |
| D Lite topology risk | Correctly dropped (F5); accept the full-topology compose cost; do not reintroduce skew via CI-only overrides |
| No second scheduler | Verified: no second scheduler exists in the tree or is proposed; `DurableDAGRunner` is the interim hermetic seam, explicitly non-release evidence everywhere |
| No fake readiness/skips | Verified honest: `capability.py` never lies; `cli.py` exits 2 honestly; `wait-for-worker.sh` fails loudly. The violations are all in the **workflow posture** (opt-in gate, vacuous E2E step) and the **non-JWT default token** — all covered by F1/F3/F9 |

## 7. Verdict

```yaml
status: DONE
target: "artifacts/designs/pending/DD-universal-media-decomposer-ci-repair.md (proposed repair)"
structure:
  workflow_jobs: 3 (+1 optional split proposed)
  production_wiring_surfaces: 2 (app.build_context, cli.worker) — must collapse to 1 shared assembly
  hatchet_surfaces_that_must_agree: 4 (runtime.txt, pyproject worker extra, compose image, hatchet.py adapter)
  indirection_hops_entry_to_work: Entry → DAGRunner seam → ProductionDAGRunner/HatchetRunner → submit_workflow_runs → worker callback → DurableStageExecutor → StageWork (5, all documented seams — justified)
verdict:
  complexity_level: APPROPRIATE-with-reducible-EXCESS
  justified: true (core) / false (4 proposed additions: B split, probe subsystem, probe-as-gate, env axis)
  summary: >
    The repair's core is the minimal correct set for R1–R5: commit the mechanical
    dependency/env fixes, repair the Hatchet image/topology, wire the existing
    ProductionDAGRunner seam, install the worker extra, make capabilities honest,
    and flip the gate to mandatory in the existing hosted job. The excess is
    structural — a second docker job, a cached submit+poll probe, error-taxonomy
    preflight machinery, and a new env axis — all replaceable by simpler forms
    without weakening any requirement.
```

## 8. Recommendations for DDAuthor (concrete, ordered)

1. **Do not finalize the DD yet** — T5–T8 are pending (adversarial log ends after T4). Distill only after turn 8.
2. **Commit + push the five mechanical fixes first** and observe a hosted run (R1). They are not design; they are evidence. Do not interleave them with the wiring work in one giant push — the debugger's NEEDS_PLAN classification is about the wiring, not the fixes.
3. **Collapse the two production wiring surfaces into one shared runtime-assembly function** used by `app.build_context` and `cli.worker` (F2). This is the single most valuable simplification: it makes "real stage work" one definition and removes the silent-degradation risk in the worker.
4. **Wire `ProductionDAGRunner` from existing env** (F8); no `UMD_EXECUTION_BACKEND` axis unless the team insists; capabilities report the active backend.
5. **Pick one Hatchet topology** (full sub-path) and drive all ports/URLs/token from one home (F5/F9). Budget the compose expansion as real work.
6. **Fix the vacuous E2E step** with a transport switch in `test_api_boundary_e2e.py` + a FAIL-not-skip rule in release jobs (F1). Execute the three shape tests in CI (F2). These two changes make the gate mean something; everything else is secondary.
7. **Keep the probe minimal and disclosure-only** (F6); the tests are the gate.
8. **Drop the split job** (F3) unless green-first makes it attractive as ergonomics — never as critical path. **Keep the preflight as a 10-line step** (F4).
9. **Carry T4 risks 1–7 into the DD** as explicit acceptance criteria: discovery-run posture for run #1, measured (not guessed) cold-boot timeout, release-job FAIL-not-skip, engine-side registration assertion, pre/post restart persistence assertions, allow-live-failure policy as a named human decision, and commit+push as step zero.

---

*Evidence citations: all file:line references verified against the committed tree at HEAD a6b1a62 on 2026-08-28. Debugger report, support-researcher L3/L4, and the adversarial log are cited by artifact name + section.*
