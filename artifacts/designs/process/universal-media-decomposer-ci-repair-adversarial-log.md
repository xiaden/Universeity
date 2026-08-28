# Adversarial Design Log: UMD Evidence-Backed GitHub CI Repair and Release-Gate Restoration

*This file records the full adversarial refinement process for repairing the
Universal Media Decomposer's GitHub CI and restoring the Hatchet release gate.
The design document (DD-universal-media-decomposer-ci-repair.md) contains
distilled decisions, not this raw debate.*

*Process: 8 sequential turns — T1 Ideator (approaches) → T2 Counter-Ideator
(critique) → T3 Ideator (refine) → T4 Counter-Ideator (surviving concerns) →
T5 Improver (implementation patterns) → T6 Counter-Improver (pattern risks) →
T7 Improver (final patterns) → T8 Counter-Improver (open risks & human
questions). Every technology/version choice is validated against current
official/maintainer sources with source + check date recorded, or explicitly
labeled PROVISIONAL.*

*Immutable requirement ledger (binding for every turn):*

- **R1** — CI is managed by pushing to GitHub and retrieving CI reports once run there (mandatory).
- **R2** — CI failures must be diagnosed for REAL missing implementation/dependencies; no stubs, unconditional skips, fake readiness, or weakened assertions (mandatory).
- **R3** — Every repair must be cross-checked against Task.md's full Universal Media Decomposer Definition of Done: source/evidence/semantic separation, immutable provenance, real representative text/image/audio/video decomposition, durable asynchronous restartable DAG, selective invalidation/rerun, public HTTP-only correction E2E, honest capability reporting, final adversarial review (mandatory).
- **R4** — Hatchet is the sole v1 scheduler; live worker callback registration and real stage execution are a release gate. No second scheduler; no in-process doubles as release evidence (mandatory).
- **R5** — Support findings → design → implementation plan → Exec-Manager (mandatory process).
- **R6** — Local checks (Ruff, mypy, local pytest) are context only, not release evidence.

*Alternatives the debate must cover:* (A) coordinated hosted-CI provisioning +
genuine Hatchet deployment/live execution + production-runner wiring +
public-boundary E2E; (B) CI-only provisioning while deferring product wiring
(must be rejected if it violates R4/R3); (C) opt-in/skip/recording-doubles
(must be rejected under R2/R4).

---
*Sections below are appended by design agents during adversarial refinement.*
---

## Proposed Approaches

*Turn 1 (T1) — rnd-ideator, 2026-08-28. Evidence basis: support-debugger durable report `universal-media-decomposer-ci-repair-debugger.md` (CI run 33164294061, commit a6b1a62), support-researcher delegation `given-harlequin-prawn`, librarian brief `controversial-teal-smelt`, the carried-forward T1 from the prior adversarial record (`ADVERSARIAL-universal-media-decomposer-ci-repair.md`), and first-hand reads of the current tree (git HEAD = a6b1a62; working-tree fixes for python-multipart/ffmpeg/PGDG-client/conftest/compose-secrets remain UNCOMMITTED).*

### Current-state verification (read at 2026-08-28, before proposing)

1. **The three live shape tests are NOT the `_RecordingClient`/`executor=None` version the handoff §6 describes.** `tests/test_hatchet_live.py` now calls `HatchetWorkerFactory.start(... executor=executor, client=_real_client())` and polls Postgres with `_poll_until` (lines ~920–1006). The handoff §6 defect describes the Plan I P4-S1 state; the repair it demanded ("bind a real executor and a real SDK client") is already present in the tree. What remains unproven is **live execution itself** — no run has ever executed against a live cluster, so SDK-surface mismatches (task-name namespacing, `run_workflow` payload shape, gRPC routing) are untested. The honest gate is "run live and fix what surfaces", not "rewrite the tests".
2. **`CapabilityReporter` has no connectivity probe.** `src/umd/jobs/capability.py` returns `configured-but-unavailable` whenever `UMD_HATCHET_SERVER_URL`/`UMD_HATCHET_TOKEN` are set; its docstring claims a reachable client flips it to `active`, but no reachability check exists in code. Consequently `_require_production_path` (`tests/test_api_boundary_e2e.py` ~line 108) would skip **even against a fully live stack**. Every approach below must close this gap or the public-boundary E2E can never run as release evidence.
3. **The worker image cannot import the SDK as composed.** `deploy/Dockerfile:32` runs `pip install .` without the `worker` extra, while `pyproject.toml:75-81` places `hatchet-sdk==1.38.1` in the optional `worker` extra. The compose `worker` service therefore starts with no `hatchet_sdk` → `cli.worker()` exits 2 with `worker unavailable: hatchet_sdk not installed`. Any approach that starts the worker container must first fix packaging.
4. **The four defect classes confirmed by support** (debugger report): (a) workflow/environment — missing `python-multipart`, `ffmpeg`, `pg_dump` client, and Compose-secret provisioning in the wrong jobs; (b) deployment — `ghcr.io/hatchet-dev/hatchet:v0.105.2` is 403-denied (wrong path; real images are sub-path `hatchet-engine`/`hatchet-lite`/`hatchet-admin`/`hatchet-migrate`, verified 200 OK at v0.105.2); (c) product integration — `src/umd/api/app.py:167` wires `DurableDAGRunner` (in-process) instead of `ProductionDAGRunner` (Hatchet submission); (d) gate posture — `UMD_VALIDATE_LIVE_WORKER` defaults to `false`, docker-e2e starts `db api` only, and the worker-readiness step is opt-in (`if: env.UMD_VALIDATE_LIVE_WORKER == 'true'`).

### Approach 1 — "Coordinated Full Repair" (alternative A in full)

**What it changes.** One coherent change set: (1) commit the five working-tree fixes CI never saw — `python-multipart==0.0.32` in `pyproject.toml` + `deploy/pins/runtime.txt`, ffmpeg + PGDG `postgresql-client-17` install step in `test-postgres`, `_resolve_pg_bin()`/`UMD_PG_BIN` in `tests/conftest.py`, compose-secret `env.setdefault` in `test_deployment_phaseE.py`; (2) repair `deploy/compose.yaml:104` to the verified sub-path image `ghcr.io/hatchet-dev/hatchet/hatchet-engine:${HATCHET_VERSION:-v0.105.2}` (multi-service production topology) and update the pin-agreement surfaces (`src/umd/jobs/hatchet.py` `HATCHET_SERVER_IMAGE`, handoff table); (3) fix worker packaging so the container actually contains the SDK (`pip install .[worker]` or promote `hatchet-sdk` to core deps) and the worker role can reach exit-0 readiness; (4) wire `app.py` to `ProductionDAGRunner` whenever a Hatchet client is configurable, keeping `DurableDAGRunner` only behind an explicit non-release env (e.g. `UMD_EXECUTION_BACKEND=durable` for hermetic unit seams) with `/v1/capabilities` reflecting the active backend; (5) add a real connectivity probe to `CapabilityReporter` (at minimum an engine version/health fetch through the SDK client; strongest form a no-op workflow submit + completion poll) so `active` is only ever true against a reachable cluster that actually executes — the precondition that makes `_require_production_path` pass honestly; (6) flip the gate polarity: the live path is mandatory on push-to-main (fail-closed), the docker-e2e job's live run is the release evidence, and the historical suite runs unmodified.

**Real production systems using the same pattern.** Greptile (LLM code-search indexing; Hatchet durable DAG over thousands of AST leaf nodes, resume-on-failure, group round-robin) — https://hatchet.run/customers/greptile (checked 2026-08-28 in prior T1; carried forward). Aevy (50k-document AI pipeline as Hatchet DAG) — https://hatchet.run/customers/aevy (checked 2026-08-28). Both demonstrate the UMD shape: a long document/media pipeline whose steps are known up front (DAG), dispatched from a service to Hatchet workers with idempotent durable execution, dashboard-observed. For the CI shape, sdr-enthusiasts/docker-acarshub's `fullstack-e2e.yml` runs a full-stack E2E against a real Docker-built backend in GitHub Actions with no DinD (compose up + host pytest + `if: always()` teardown) — https://github.com/sdr-enthusiasts/docker-acarshub/blob/5bd6c238c01d49e6b118407cad56d541fed65d5b/.github/workflows/fullstack-e2e.yml (checked 2026-08-28).

**Requirement mapping.** R1 ✓ (push + retrieve CI reports is the only close-out; local green is not evidence). R2 ✓ (no stubs/skips; the gate is real execution; the `_require_production_path` skip is removed only by making the scheduler genuinely active, never by deleting the skip). R3 ✓ (all uncommitted fixes verified non-weakening; E2E path untouched; representative media runs for real via ffmpeg). R4 ✓ (Hatchet remains sole v1 scheduler; the durable backend is explicit-env only and never counts as release evidence; live registration + real stage execution is the gate). R5 ✓ (this design is the R&D step; implementation goes to Exec-Manager). R6 ✓ (local validation remains context).

### Approach 2 — "Prove-Then-Run Pre-Flight" (moonshot: fail-fast attribution + unconditional live path)

**What it changes.** Add a mandatory pre-flight step inside the docker-e2e job before any compose-up: `docker manifest inspect` the exact pinned image paths/tags (sub-path `hatchet-engine`, and `hatchet-lite` for the CI option) asserting exit 0, plus an SDK/server pair probe (e.g. `pip index versions hatchet-sdk` cross-checked against the pinned engine tag) that fails if the pair is not the agreed one. This converts the current failure mode — a 36-second build-then-`403 DENIED` pull at the end of the job — into a seconds-scale attributable failure at the start. Second, invert the gate posture: remove `UMD_VALIDATE_LIVE_WORKER` as a user-controllable default entirely; the live path is unconditional on push-to-main, and `workflow_dispatch` may add `allow-failure: true` only as an explicit opt-out that still **runs** the live path (never skips it). Third, gate the boundary E2E on the `CapabilityReporter` connectivity probe (same probe as Approach 1) rather than env-only checks.

**Real production systems using the same pattern.** Hatchet's own self-hosting docs now pin released GHCR tags with the sub-path images (`hatchet-engine`, `hatchet-admin`, `hatchet-migrate`, `hatchet-dashboard`) and its upgrading/downgrading page instructs pinning e.g. `hatchet-engine:v0.78.26` — https://docs.hatchet.run/self-hosting/docker-compose and https://docs.hatchet.run/self-hosting/upgrading-downgrading (checked 2026-08-28). Pre-flight registry verification before compose-up is documented CI hygiene for exactly this failure class: the registry returns the same `denied` for "private and unauthorized" and "repo does not exist", so a wrong path is only catchable by probing the exact reference (devopsaitoolkit.com/blog/docker-error-pull-access-denied, latchkey.dev/learn/docker/docker-compose-pull-access-denied-image-in-ci; both checked 2026-08-28).

**Requirement mapping.** R1 ✓ R2 ✓ (fail-closed, no fake readiness, no skip expansion) R3 ✓ R4 ✓ (unconditional live path is the strongest R4 stance) R5 ✓ R6 ✓. **Honest limitation:** C's pre-flight proof depends on the pinned pair being *pullable* and *compatible* — the 403 on the top-level path proved pull is not guaranteed; `manifest inspect` proves existence, not functionality, so it must be paired with Approach 1's live execution.

### Approach 3 — "Split-Job CI" (complement; standalone = rejectable alternative B)

**What it changes.** Re-architect `.github/workflows/validation.yml` into two docker jobs instead of one job with an opt-in branch: (1) `docker-baseline` — `db` + `api` only, runs on every push/PR, fast feedback on the proven stack; (2) `docker-live` — full stack `db api hatchet worker sandbox-runner` with the live gate always on, hard-gated on push to main and on PRs touching worker/hatchet/api/jobs paths via path filters. The live job owns the boundary E2E + three shape tests + restart/durability segments; the baseline job owns compose-config, migration ordering, and API external flows that do not require the scheduler. Both jobs upload diagnostics with `if: always()` and teardown with `down -v --remove-orphans`.

**Real production systems using the same pattern.** Same sdr-enthusiasts `fullstack-e2e.yml` reference as Approach 1 for the compose-up mechanics; the "fast hermetic baseline + slow live gate" split is the standard CI topology for systems with an integration-only dependency (the baseline/live split is exactly how the UMD's own Plan J intended to separate static from live evidence — `TASK-universal-media-decomposer-J-api-boundary-ci-release.md`).

**Requirement mapping.** R1 ✓ R2 ✓ (split is not a weakening; the live job's gate remains fail-closed) R3 ✓ R4 ✓ R5 ✓ R6 ✓. **Honest limitation:** B is a CI-structure improvement, not a repair of the product wiring; it must be combined with Approach 1's code changes. **The rejectable variant (alternative B as defined in the task — "CI-only provisioning while deferring product wiring") must be rejected:** committing only the environment fixes while leaving `app.py` on `DurableDAGRunner`, the image path wrong, and the live gate opt-in would make the workflow green while the required Hatchet execution path remains absent or unproven — a direct R4 and R3 violation. The working-tree fixer diff is exactly this variant, which is why the debugger classified `NEEDS_PLAN` rather than `SIMPLE`.

### Approach 4 — "Single-Container Scheduler" (Lite in CI; rejected as release-evidence surface)

**What it changes.** Replace the multi-service Hatchet topology in the *CI* compose override with the official single-container `ghcr.io/hatchet-dev/hatchet/hatchet-lite:v0.105.2` image (bundles engine + dashboard + its own Postgres), reducing startup surface; production `deploy/compose.yaml` stays on the full sub-path topology. The pin tests and live shape tests must still assert the same `v0.105.2` server version across both surfaces.

**Real production systems using the same pattern.** Hatchet's own docs offer exactly this split: full multi-service compose for production self-hosting (https://docs.hatchet.run/self-hosting/docker-compose) and `hatchet-lite` for development/low-volume/CI-style use ("designed for development and low-volume use-cases", single container with bundled Postgres — https://docs.hatchet.run/self-hosting/hatchet-lite; both checked 2026-08-28). A third-party VPS guide also distinguishes the full control-plane compose from the Lite path (ramnode.com/guides/hatchet, checked 2026-08-28).

**Requirement mapping.** R1 ✓ R2 ✓ R3 ✓ R4 ✓-with-skew (Lite is an official Hatchet artifact, not a second scheduler). **Honest limitation — this is the only approach that changes what stack produces the release evidence.** The handoff release gate (§8) demands shape tests pass against "the same Compose/CI stack" that users deploy; if CI proves the Lite topology but production runs the full topology, the evidence is weaker. The topology-skew risk conflicts with R4's "same stack" spirit. **Verdict: rejected as the release-evidence surface; acceptable only as a documented, team-approved CI simplification layered on Approach 1.**

### Explicit rejection of the prohibited alternatives

| Alternative (as defined in the task) | Rejection basis |
|---|---|
| (B) CI-only provisioning while deferring product wiring | Violates R4 (production path stays `DurableDAGRunner`; no real Hatchet execution proven) and R3 (DoD #21/#30/#31 remain unproven). Exactly the fixer-diff shape the debugger flagged. |
| (C) opt-in/skip/recording-doubles as release evidence | Violates R2 (making CI green by exclusion — `UMD_VALIDATE_LIVE_WORKER=false` default, `db api`-only start, capability-based skips as the norm) and R4 (recording clients / in-process doubles are not scheduler release evidence per CONTRACTS.md:61-62). |

### Ranking and recommendation

| # | Approach | Fit | Effort | Risk | Testability | Maint. | Composite |
|---|----------|-----|--------|------|-------------|--------|-----------|
| 1 | Approach 1 — Coordinated Full Repair | 5 | 3 | 2 | 5 | 4 | 3.8 |
| 2 | Approach 2 — Prove-Then-Run Pre-Flight | 4 | 2 | 2 | 4 | 4 | 3.2 |
| 3 | Approach 3 — Split-Job CI | 4 | 2 | 3 | 4 | 5 | 3.6 |
| 4 | Approach 4 — Single-Container Scheduler | 2 | 3 | 3 | 3 | 3 | 2.8 |

**Top pick: Approach 1**, with Approach 2's pre-flight probes folded in (cheap, high-value failure attribution) and Approach 3's job split as an optional follow-up after green. Approach 4 stays out of release evidence. Approaches (B) and (C) as defined are rejected outright (R4/R3 and R2/R4 respectively).

### Technology validation summary (checked 2026-08-28 unless noted)

| Technology | Claim | Source | Evidence status |
|------------|-------|--------|-----------------|
| Hatchet server image paths | Top-level `ghcr.io/hatchet-dev/hatchet:vX` does not exist publicly; real images are sub-paths `hatchet-engine`, `hatchet-admin`, `hatchet-migrate`, `hatchet-dashboard`, `hatchet-lite` | https://docs.hatchet.run/self-hosting/docker-compose ; https://docs.hatchet.run/self-hosting/hatchet-lite | EVIDENCE-BACKED (docs + researcher's 403/200 probes) |
| Hatchet server v0.105.2 | Real GitHub release 2026-08-25; sub-path images carry the tag | https://github.com/hatchet-dev/hatchet/releases/tag/v0.105.2 ; newreleases.io (prior T1) | EVIDENCE-BACKED (release exists; tag verified on sub-paths) |
| hatchet-sdk 1.38.1 | Real PyPI release 2026-08-25; `requires-python <4,>=3.10`; Worker.start() blocks forever (matches cli.py loop) | https://pypi.org/project/hatchet-sdk/ ; prior T1 | EVIDENCE-BACKED (release exists) |
| SDK↔server pair | Both released 2026-08-25 — contemporaneous, numerically aligned | PyPI + GitHub releases | **PROVISIONAL/CANDIDATE** until live shape validation (handoff §1 unchanged) |
| python-multipart 0.0.32 | Starlette 1.6.0 imports `python_multipart`; 0.0.14 changed the namespace and 0.0.16 fixed it; 0.0.32 pin is post-fix | fastapi discussions #12532 (prior T1), #5144, issues #1599, #1551 | EVIDENCE-BACKED |
| ffmpeg on ubuntu-latest | Not preinstalled on Ubuntu 24.04 runner; apt install is the standard fix; install can fail on runner-image drift | actions/runner-images Ubuntu2404-Readme (prior T1); commitizen-tools/commitizen#1870 | EVIDENCE-BACKED |
| postgres:17 service + PG client | ubuntu-latest ships PG 16 client; pg_dump 16 aborts against PG 17 server ("server version mismatch"); PGDG `postgresql-client-17` + explicit `/usr/lib/postgresql/17/bin` path is the documented fix | shallowbrooksoftware.com ; stackoverflow.com/questions/79105375 ; actions/runner-images#11531 ; Adventurers-Guild commit ea56a04 | EVIDENCE-BACKED (multiple real incidents) |
| Compose required interpolation | `HATCHET_COOKIE_SECRET`/`HATCHET_MASTER_KEY` use `${VAR:?}`; the unit/postgres jobs never export them — a real env mismatch, not a test-logic bug | deploy/compose.yaml:106-107 ; debugger report | EVIDENCE-BACKED (hosted JUnit text) |
| Docker Compose E2E in GH Actions | Native hosted-runner compose (no DinD), `up -d` + host pytest, teardown in `if: always()` | sdr-enthusiasts/docker-acarshub fullstack-e2e.yml | EVIDENCE-BACKED |

---

## Critique

*Turn 2 (T2) — rnd-counter-ideator, 2026-08-28. Searches run for documented failures, postmortems, migration regrets, and acknowledged limitations per approach; citations ranked by evidence tier (T1 = primary/official maintainer source; T2 = real-world incident with reproducible detail; T3 = strong community/guide with reproduced error). Every claim below was checked against THIS project's context (UMD files, CI failure classes) before being applied.*

### Critique of Approach 1 — Coordinated Full Repair

1. **The wiring change (DurableDAGRunner → ProductionDAGRunner) is the highest-risk edit in the entire plan, and the ideator's own evidence shows why.** The submission path depends on `Hatchet.runs.admin_client().run_workflow(workflow_name, json.dumps(input))` — a *shimmed* surface (`_SDKSubmissionShim` in `src/umd/jobs/hatchet.py`) because "real SDK has no client.submit_workflow_run". The official Python SDK changelog (T1) shows the SDK is actively changing: "Stops retrying gRPC requests on 4XX", "Adds a warning on client init if the SDK version is not compatible with the tenant (engine) version", `grpc_enable_fork_support` added — the Admin/Runs surface is a moving target. A shim over a moving public API is precisely the shape that breaks in production after CI passed: the test double (`dict_client`) satisfies the shim's duck-type, but the *real* client may differ. **Real incident:** hatchet-dev/hatchet#3283 (Go SDK) documents that worker construction performs startup RPCs (GetVersion, PutWorkflowV1) that can block indefinitely and cannot be cancelled when the server is unavailable or TLS-mismatched — a direct analog to UMD's worker startup path and a concrete failure mode for the live gate (wait-for-worker could hang, not fail). T1-tier source. Applied: the worker readiness gate must have a hard timeout and the capability probe must distinguish "connectable" from "registered and executing".
2. **The CapabilityReporter connectivity probe is new code that must itself be validated, and there is a real risk it becomes another "fake readiness".** The honest pattern (CONTRACTS.md:60-63: "readiness requires live client + real callback registration"; CapabilityReporter "never represents unavailable as active") is only as good as the probe. If the probe is a version-ping, it proves reachability, not execution — a miswired worker (wrong token, wrong tenant, gRPC broadcast misconfig) still passes "reachable" while never executing stages. **Real failure mode:** hatchet-python-quickstart#16 shows a *successful-looking* worker that fails to register with `UNAVAILABLE: ... Socket closed` at `put_workflow` — if a probe only checks version, this class of misconfig sails through. T2-tier source. Applied: probe must include at least one real workflow submission + completion poll, or the E2E must be the probe.
3. **The worker packaging fix is mandatory for the gate to run at all — the ideator lists it but the failure evidence is stronger than presented.** `deploy/Dockerfile:32` `pip install .` without `[worker]` means the worker container lacks `hatchet_sdk`; `cli.worker()` exits 2 ("worker unavailable: hatchet_sdk not installed"). This is not hypothetical: the whole reason `hatchet-sdk` is in the optional `worker` extra is image-size control (pyproject.toml:75-81). If the fix is `pip install .[worker]`, the image grows; if the fix is "promote to core deps", the honest-gate distinction in `cli.py` (exit 2 when SDK absent) becomes dead code. Both are fine, but the choice must be deliberate and tested — a container smoke test (`umd worker --help` or `python -c "import hatchet_sdk"`) inside the docker-e2e job is the cheapest verification. Not a documented-failure citation, but directly grounded in the debugger's NEEDS_PLAN diagnosis.
4. **Flipping the gate polarity has a documented reversion hazard.** The exact pattern UMD currently exhibits — a `UMD_VALIDATE_LIVE_WORKER` defaulting to `false` plus a `db api`-only default compose — is the classic "CI green by exclusion" anti-pattern. The librarian brief records that the *in-flight fixer diff turned the live-worker gate OFF*, contradicting the release gate. There is no external postmortem to cite for "gate flip gets reverted" because every org has it; the closest documented analog is the Adventurers-Guild pg_dump incident (T2-tier): a silent `|| continue` swallowed a failed backup and applied a migration with zero backup — the fix was (a) call the versioned binary explicitly and (b) *remove the silent continue so failure hard-stops the job*. Applied: the gate must be fail-closed structurally (missing live evidence = red job + job-summary digest), not policy-only.
5. **The five working-tree fixes, while correct in direction, must not be assumed sufficient — the multipart failure is a namespace trap, not just a missing pin.** The debugger reported 6× `AssertionError: The 'python-multipart' library must be installed` (Starlette form parsing). The community evidence shows this error has *three* distinct root causes: package absent (fastapi#1599, T1), the `multipart` vs `python-multipart` namespace conflict when both are installed (fastapi#5144, T1-tier discussion), and — the subtle one — pre-0.0.16 versions importing as `multipart` while Starlette 1.x imports `python_multipart` (fastapi#5144 detailed reproduction). A pin alone (0.0.32) resolves 2 and 3; a *stale resolved lockfile or a transitive `multipart` dep* recreates 1. The CI must fail loudly on any residual multipart failure, not re-pin in a hurry. T1/T2-tier sources.

**Verdict: Approach 1 survives, with mandatory additions** — (i) probe = submit+poll or E2E-as-probe, not version-ping; (ii) worker-readiness wait must have a hard timeout so the gate fails, not hangs; (iii) worker-image smoke test inside the job; (iv) gate is structurally fail-closed; (v) multipart pin verified against a clean resolve in the hosted run.

### Critique of Approach 2 — Prove-Then-Run Pre-Flight

1. **`docker manifest inspect` proves existence, not functionality — the ideator admits this, but the failure is worse than admitted.** The GHCR `denied` error is *deliberately conflated* by registries: "private and unauthorized" and "repo does not exist" return the same 403 so the registry never confirms private-image existence to anonymous callers (devopsaitoolkit.com, T3-tier but authoritative on OCI semantics). A public sub-path can pass `manifest inspect` and still be unusable: bad tag, broken layer, image with a different `cmd` than the compose expects (the engine image's entrypoint is `/hatchet/hatchet-engine --config /hatchet/config`, not a bare command — compose must mount/seed config; Hatchet's own compose uses a `setup-config` + `migration` sidecar pattern). **Applied:** pre-flight must also verify the compose-level contract (entrypoint, required config volume) — a manifest 200 does not mean the stack will start.
2. **The SDK/server pair probe is weaker than claimed.** "Cross-check `pip index versions hatchet-sdk` against the pinned engine tag" proves both exist, not that they interoperate. The official troubleshooting doc (T1) explicitly warns: "Check SDK version — ensure your SDK version is compatible with your engine version. Mismatches can cause subtle failures." The TS SDK false-positive V0/V1 warning (hatchet#4038, T1) proves version-gating logic itself is buggy — a warning layer can misreport compatibility. The ONLY reliable pair proof is a live workflow executed end-to-end. Applied: pair probe is a fast-fail tripwire, never a substitute for live execution; Approach 2 cannot stand alone for R4.
3. **Removing `UMD_VALIDATE_LIVE_WORKER` entirely increases main-branch CI cost and could push teams to weaken elsewhere (workflow_dispatch allow-failure becomes the new escape hatch).** The ideator's own design carves out "explicit opt-out that still runs the live path" — good — but the split-job alternative (Approach 3) already exists to contain cost. Keeping BOTH an unconditional live path and a separate live job would double the expensive scheduler runs. Applied: choose one topology (Approach 1's single-job unconditional live path, OR Approach 3's split with the live job unconditional on main); do not stack both.
4. **Pre-flight probes add a new failure surface to the job.** If `docker manifest inspect` itself fails (rate limit, network), the job fails before the actual test even if the stack is fine — acceptable if the probe is idempotent and retried, but a `429` on manifest inspect must not be confused with a wrong image path (devopsaitoolkit.com documents rate-limit `429` vs `denied` distinction). Applied: classify probe failures (429 vs 403 vs 404) and fail with a specific, attributable message.

**Verdict: Approach 2 survives only as a fast-fail pre-flight complement to Approach 1** — manifest inspect + pair tripwire at the top of the docker-e2e job; never as the release-evidence mechanism; must not be stacked redundantly with Approach 3.

### Critique of Approach 3 — Split-Job CI

1. **Path filters are a documented CI anti-pattern for exactly this kind of gate.** If `docker-live` only triggers on pushes touching worker/hatchet/api/jobs paths, then a change to `deploy/compose.yaml`, `deploy/pins/runtime.txt`, or `pyproject.toml`'s worker extra that *does not match the filter* silently skips the live gate — recreating "CI green by exclusion" (R2). The filter list must include compose, Dockerfile, pins, pyproject, migrations, and any scheduler-adjacent file; a filter that drifts from the code it gates is a maintenance trap. No clean external postmortem, but the Adventurers-Guild `|| continue` incident (T2) is the same class: a silent path that lets a release proceed without its required evidence.
2. **The split requires two Postgres/OCFL stack runs per push unless cached; the ideator under-specifies the duplication cost.** `docker-baseline` and `docker-live` each build the API image and boot a stack. The build cache helps only if the same runner/cache keys are shared. This is operational, not design-fatal, but the composite-fit score (3.6) assumed it.
3. **Approach 3 does not repair the product wiring — the ideator states this — but the ordering hazard deserves emphasis.** If the split is implemented before Approach 1's wiring, `docker-live` fails immediately (image path + worker packaging), turning the "nice structure" into another red job. The split must land AFTER the coordinated repair is green.
4. **The baseline/live split is legitimately evidenced** (sdr-enthusiasts fullstack-e2e; oneuptime/atomicobject-style compose E2E patterns from prior T1), so the structural pattern itself is sound — the critique is about filter drift, duplication, and ordering, all mitigable.

**Verdict: Approach 3 survives as a post-green follow-up** (after Approach 1), with (i) exhaustive path filters including compose/Dockerfile/pins/pyproject/migrations; (ii) shared build cache; (iii) explicit ordering after Approach 1; (iv) live job unconditional on main.

### Critique of Approach 4 — Single-Container Scheduler (Lite)

1. **The topology-skew risk is real and is a release-gate weakening under R4.** Handoff §8 says the gate fails if shape tests do not pass "on the same Compose/CI stack". Lite bundles its own Postgres, dashboard, and engine in one image; the production topology splits engine/admin/migrate across separate services with distinct config mounts. Evidence produced against Lite is evidence that *a* Hatchet works, not that *the deployed topology* works. The RamNode guide (T2) and Hatchet docs both treat Lite as a dev/low-volume surface; the docs' own "hatchet server start --disable-auth" wording (T1) says "Auth-disabled mode is for local development only."
2. **Lite's bundled Postgres breaks the UMD persistence evidence.** The restart/durability shape tests (P1-S4 semantics) must prove stage_run rows survive restart and OCFL volumes persist. Against Lite, the app's Postgres is still UMD's own `db` service, so stage-run persistence holds — but the *worker/scheduler* connection semantics differ (Lite engine on its own gRPC port, fixed worker token), meaning a passing Lite shape test does not validate the full-topology worker gRPC routing (engine on 7077, dashboard on 8080, broadcast address config). The engine-gRPC routing is exactly the class of bug that hatchet-python-quickstart#16 and docs troubleshooting call out.
3. **Operator-noise risk:** hatchet#4038 (T1) documents false-positive version warnings on `hatchet-lite` self-hosted setups — in CI, a noisy-but-passing Lite could mask a genuine version mismatch that the full topology would surface.

**Verdict: Approach 4 rejected as release-evidence surface.** Acceptable only as a documented developer convenience (local shape debugging), never in the release pipeline.

### Summary of surviving / dead approaches

| Approach | Survives? | Condition |
|----------|-----------|-----------|
| Approach 1 — Coordinated Full Repair | ✅ SURVIVES (with additions) | Add submit+poll probe or E2E-as-probe; hard-timeout worker wait; worker-image smoke test; structurally fail-closed gate; clean-resolve multipart verification |
| Approach 2 — Prove-Then-Run | ✅ SURVIVES as complement only | Pre-flight tripwire; classify probe errors; never sole release evidence; do not stack with Approach 3 |
| Approach 3 — Split-Job CI | ✅ SURVIVES as follow-up | After Approach 1 green; exhaustive filters; shared cache; live job unconditional on main |
| Approach 4 — Single-Container (Lite) | ❌ DEAD as release surface | Topology-skew + persistence/routing evidence gap (R4); dev-only at most |
| Alternative (B) — CI-only, defer wiring | ❌ DEAD | R4/R3 violation; fixer-diff shape |
| Alternative (C) — opt-in/skip/recording-doubles | ❌ DEAD | R2/R4 violation; gate-by-exclusion |

---

## Refined Approaches

*Turn 3 (T3) — rnd-ideator (resumed session), 2026-08-28. Responds to every T2 finding. Dead approaches are dropped with reasons. Changed/remaining technology choices revalidated against official sources with check dates.*

### Refined Approach A — "Coordinated Full Repair with Structural Gate Enforcement" (Approach 1 + T2 additions)

The T2 critique is accepted in full. The refined approach incorporates all five mandatory additions; nothing was restated without changing the design.

1. **Probe = real execution, not version-ping (T2 #1/#2).** `CapabilityReporter`'s connectivity probe becomes a **submit+poll probe**: on `/v1/capabilities` (with a short TTL cache, e.g. 30s), the reporter submits a no-op workflow through the configured client, polls Postgres/Hatchet for a single completed run, and only then reports `active`. If submission or completion fails, status stays `configured-but-unavailable` with the specific failure in `reason`. This makes `_require_production_path` pass only when a real worker executed a real run — the honest precondition CONTRACTS.md:60-63 requires, and it structurally prevents the hatchet-python-quickstart#16 failure class (registered-looking but never-executing workers) from faking readiness. The probe is gated to release environments (or any environment with scheduler env configured) and never faked in tests; tests use a probe seam that is itself tested.
   - *Revalidation:* hatchet-python-quickstart#16 (2025-02-08, still open with confirmations 2025-03-25) documents `UNAVAILABLE: Socket closed` at `put_workflow` during registration — a worker that looks connected but cannot register. Official troubleshooting (https://docs.hatchet.run/v1/troubleshooting, checked 2026-08-28) lists "ensure your SDK version is compatible with your engine version. Mismatches can cause subtle failures" — compatibility cannot be proven by a version ping. **Best fit:** submit+poll is the only probe that satisfies the honest-readiness contract. PROVISIONAL: exact SDK method for a no-op submit (via the existing `_SDKSubmissionShim`/`runs.admin_client().run_workflow`) must be confirmed against the installed 1.38.1 client in the first hosted run — the shim already exists and is exercised by unit tests, but live surface confirmation is outstanding.
2. **Worker-readiness wait has a hard timeout and a fail-fast exit (T2 #1).** `wait-for-worker.sh` gains a bounded retry window (e.g. 90s) and, on timeout, dumps worker/engine logs and exits non-zero (job red), never hanging. Rationale: hatchet-dev/hatchet#3283 (checked 2026-08-28) shows worker construction can block indefinitely on startup RPCs when the engine is unavailable — a hang is worse than a failure for CI.
3. **Worker-image smoke test inside the job (T2 #3).** The docker-e2e job runs `docker compose run --rm worker umd worker --help` (or `python -c "import hatchet_sdk"` in the built image) *before* the gate, verifying the SDK packaged into the image. Packaging decision: `pip install .[worker]` in `deploy/Dockerfile` (keeps SDK optional for the API role, preserves the honest exit-2 gate in `cli.py`). 
   - *Revalidation:* `hatchet-sdk==1.38.1` remains a real PyPI release (2026-08-25; https://pypi.org/project/hatchet-sdk/, checked 2026-08-28); the `[worker]` extra remains the declared home of the SDK (pyproject.toml:75-81). EVIDENCE-BACKED that the packaging gap exists; the fix is standard Python packaging practice.
4. **Structurally fail-closed gate (T2 #4).** `UMD_VALIDATE_LIVE_WORKER` is removed from the default posture: the docker-e2e job always starts `db api hatchet worker sandbox-runner` and always runs the gate on push to main. The gate step reads a single env the job itself sets from a constant (not a workflow input default). `workflow_dispatch` may pass `allow-live-failure: true` — but the live run still executes and its evidence is still uploaded; only the job's green/red verdict is softened for manual debugging runs. Job summary + JUnit must include a machine-readable "live-worker-gate: PASS|FAIL" line so the release gate cannot be "green by exclusion".
   - *Revalidation:* this follows the Adventurers-Guild incident fix (commit ea56a04, checked 2026-08-28): remove silent continue; hard-fail on missing required evidence. EVIDENCE-BACKED pattern.
5. **Clean-resolve multipart verification (T2 #5).** `python-multipart==0.0.32` pinned in `pyproject.toml` and `deploy/pins/runtime.txt`; the hosted `test-postgres` run is the verification (it already exercises `sources.py` multipart ingestion). A unit test asserts `import python_multipart` succeeds in the test env so a namespace-conflict regression (`multipart` shadowing) fails early, not in production.
   - *Revalidation:* fastapi discussion #5144 (checked 2026-08-28) documents the 0.0.14 namespace break and the fix path (>=0.0.16 imports `python_multipart`); 0.0.32 is post-fix and is the pin already present in the working tree. EVIDENCE-BACKED.
6. **Worker/hatchet services must be startable in the release topology (T2 #1 applied to compose).** The refined approach keeps the full sub-path topology in `deploy/compose.yaml` — `hatchet-engine` (not top-level) — and adds the config-mount/entrypoint detail the official compose shows: the engine needs `--config /hatchet/config` from the seeded config dir (https://docs.hatchet.run/self-hosting/docker-compose, checked 2026-08-28). The refined compose adds the engine's gRPC broadcast/insure vars required for in-stack worker connectivity (SERVER_GRPC_BROADCAST_ADDRESS, SERVER_GRPC_INSECURE for the CI network) — these are exactly the "subtle" misconfig class the troubleshooting doc warns about.
   - *Revalidation:* official compose at https://docs.hatchet.run/self-hosting/docker-compose (checked 2026-08-28) shows engine envs (DATABASE_URL, SERVER_GRPC_BIND_ADDRESS, SERVER_GRPC_INSECURE, SERVER_GRPC_BROADCAST_ADDRESS, SERVER_INTERNAL_CLIENT_INTERNAL_GRPC_BROADCAST_ADDRESS). EVIDENCE-BACKED as the official shape; the exact UMD values are PROVISIONAL until the hosted stack boots.

### Refined Approach B — "Split-Job CI" (Approach 3, now explicitly ordered after A)

T2's four mitigations are folded in: (i) **exhaustive path filters** — the `docker-live` job triggers on any change to `src/umd/jobs/**`, `src/umd/api/app.py`, `deploy/**`, `pyproject.toml`, `tests/test_hatchet_live.py`, `tests/test_api_boundary_e2e.py`, `.github/workflows/validation.yml`, `migrations/**` — plus always on push to main; (ii) **shared build cache** — the live job reuses the baseline job's Docker layer cache via `actions/cache` or a single build step producing the image once (a "build-once, run-twice" job artifact); (iii) **ordering** — the split is implemented only after Refined Approach A is green on a hosted run; (iv) **live job unconditional on main** regardless of filters. The baseline job keeps compose-config, migration ordering, and API external flows that need no scheduler.

*Revalidation:* the split pattern is evidenced by sdr-enthusiasts/docker-acarshub fullstack-e2e.yml (checked 2026-08-28); no new technology introduced; the change is workflow topology only.

### Dropped approaches (with reasons)

- **Approach 4 — Single-Container Scheduler (Lite): DROPPED.** T2's topology-skew finding stands (R4: release evidence must be produced against the same deployed stack; Lite bundles its own Postgres and differs in gRPC/dashboard routing). Dev-only convenience at most; not part of the repair.
- **Alternative (B) — CI-only provisioning while deferring product wiring: DROPPED.** R4/R3 violation; exactly the fixer-diff shape that caused this repair to be needed.
- **Alternative (C) — opt-in/skip/recording-doubles: DROPPED.** R2/R4 violation; gate-by-exclusion.

### Revalidated technology/version claims (T3)

| Choice | Claim | Source (checked 2026-08-28) | Status |
|--------|-------|------------------------------|--------|
| Hatchet server v0.105.2 sub-path images | `ghcr.io/hatchet-dev/hatchet/hatchet-engine:v0.105.2` + admin/migrate/dashboard/lite | https://docs.hatchet.run/self-hosting/docker-compose ; https://docs.hatchet.run/self-hosting/upgrading-downgrading (pin pattern `hatchet-engine:v0.78.26`) | EVIDENCE-BACKED (paths/tags); stack boot PROVISIONAL |
| hatchet-sdk 1.38.1 | PyPI 2026-08-25; installed via `[worker]` extra | https://pypi.org/project/hatchet-sdk/ | EVIDENCE-BACKED |
| SDK↔server pair | Contemporaneous 2026-08-25 releases; MUST be confirmed by live submit+poll | PyPI + GitHub release tags | **PROVISIONAL/CANDIDATE — the single biggest open item** |
| python-multipart 0.0.32 | Post-fix namespace (`python_multipart`); pin already in tree | fastapi discussion #5144 (0.0.14 break, fix >=0.0.16) | EVIDENCE-BACKED |
| ffmpeg + PGDG postgresql-client-17 | ubuntu-latest lacks ffmpeg; PG 16 client vs postgres:17 service | commitizen#1870 ; shallowbrooksoftware.com ; stackoverflow 79105375 ; actions/runner-images#11531 | EVIDENCE-BACKED |
| Engine entrypoint/config-mount | Engine image entrypoint `/hatchet/hatchet-engine --config /hatchet/config`; needs seeded config | https://docs.hatchet.run/self-hosting/docker-compose (setup-config/migration pattern) | EVIDENCE-BACKED |
| actions/checkout@v4, setup-python@v5, upload-artifact@v4 | Current majors; upload-artifact@v4 required (v3 deprecated 2024-11-30) | prior T1 validation | EVIDENCE-BACKED (no change) |

**Honest limitations carried forward:** (1) the SDK↔server pair and the full-stack boot are unproven until the first hosted live run; the plan budgets 2–3 hosted iterations; (2) the submit+poll probe method must be confirmed against the installed SDK in the first run; (3) engine gRPC env values for the CI network are provisional until the stack boots.

---

## Surviving Concerns

*Turn 4 (T4) — rnd-counter-ideator (resumed session), 2026-08-28. Assesses whether T3's refinements actually resolve T2's critique. Verdict: the refinements are substantive, not cosmetic — probe-as-execution, hard-timeout readiness, image smoke test, structural fail-closed gate, and clean-resolve multipart verification all change the design rather than restate it. What follows is what STILL does not work or remains genuinely open.*

### Still open after T3

1. **The SDK↔server pair remains CANDIDATE until a live run — and T3's own probe design depends on the very surface that is unproven.** The submit+poll probe goes through `_SDKSubmissionShim` → `runs.admin_client().run_workflow(workflow_name, json.dumps(input))`. T3 marks this "PROVISIONAL: exact SDK method confirmed in the first hosted run". That is circular in an important way: the probe cannot produce `active` until the shim's real-surface assumptions hold, and the shim cannot be validated until the probe runs. This is acceptable as an explicit first-step (run the live job, observe, fix the shim), but it means **the very first hosted live run is expected to surface SDK-surface defects, not pass**. The plan must treat run #1 as a discovery run with an explicit "expected to fail, capture diagnostics" posture rather than a green-check.
2. **The worker-readiness hard timeout (90s) may be too short for a cold first boot** — image pull of the Hatchet engine (~hundreds of MB) plus engine migrations (setup-config + migrate sidecar ordering) plus worker registration can exceed 90s on a cold hosted runner. T2 demanded a timeout to avoid hangs; T3 set 90s. **This is now a concrete tuning risk, not a design flaw:** the timeout must be configurable and set from the observed cold-boot duration of the first hosted runs (capture timestamps in diagnostics), otherwise the gate becomes flaky-red on cold starts and someone "fixes" it by raising the timeout to a meaningless value or — worse — by reverting to opt-in. The mitigation is to measure, not to guess.
3. **The gate's "allow-live-failure for workflow_dispatch only" escape hatch is still an escape hatch.** T3 correctly keeps the live run executing and its evidence uploaded even under `allow-live-failure: true`, so the machine-readable "live-worker-gate: PASS|FAIL" line always reflects truth. That closes the evidence gap. What remains open is the *policy* question: who is allowed to press workflow_dispatch with allow-live-failure, and does the release gate (handoff §8 / Plan J) read the FAIL line independently of the job's green/red verdict? If the release gate is a human reading a green checkmark, the escape hatch silently re-opens. **This requires a human decision (T8), not a design one.**
4. **`_require_production_path` skip removal still hinges on probe truthfulness at the exact moment of the E2E run.** T3's submit+poll probe has a 30s TTL cache; the E2E's `_require_production_path` reads `/v1/capabilities` at setup. If the probe cache expires mid-E2E or the worker dies between probe and E2E (crash, OOM in the worker container), the skip re-engages or the E2E fails confusingly. Two sub-risks: (a) the E2E must fail loudly (not skip) in the release job if the scheduler is not active at E2E start — a skip in the release job is a silent evidence gap; (b) the probe TTL must be longer than the E2E run or the E2E must re-probe on its own. **Not resolved by T3; needs a concrete rule: "in release jobs, `_require_production_path` must not skip — it must FAIL".**
5. **The engine gRPC env values are PROVISIONAL and are exactly the "subtle failure" class the official docs warn about.** T3 added SERVER_GRPC_BROADCAST_ADDRESS / SERVER_GRPC_INSECURE to the compose — good — but wrong values produce workers that register-and-never-execute (or never register) with confusing `UNAVAILABLE` gRPC errors (hatchet-python-quickstart#16 class). The first hosted run must assert **worker registration count > 0 via the engine, not just the container running**, before the shape tests are trusted. The existing `worker ready: registered N Hatchet workflows` line is a start; the debugger notes it says "(candidate, pending Plan J live validation)" — that parenthetical must be removed only when a live run proves registration.
6. **Multipart: the pin is right, but the hosted verification is the `test-postgres` job — which is exactly the job that was failing.** T3 correctly notes the hosted run is the verification, and the fix is in the uncommitted tree. Concern: the uncommitted fixes have never been pushed (R1). Until a hosted run passes with them, all five fixes are *believed-correct but unproven*; the debugger's NEEDS_PLAN classification stands on this. This is process risk, not design risk: the plan must commit-and-push first, observe, then iterate.
7. **The E2E restart/durability segments depend on volume persistence (`ocfl-db`, `ocfl-data`) surviving `stop/start` — a real CI hazard if the job's teardown uses `down -v` between segments.** T3 keeps handoff §4's "stop/start not down/up" for the restart segment. What is not specified: the *final* teardown `down -v --remove-orphans` runs in `if: always()`. If any step between restart segments reuses `down -v` (e.g. a retry wrapper), the persistence evidence is destroyed silently and the "restart" test passes vacuously. **Add a guard: assert OCFL namaste (`0=ocfl_1.1`) and stage_run row counts immediately before AND after the restart segment; a vanished volume fails the job.**

### What T3 resolved well (for the record)

- Probe = execution (submit+poll) rather than version-ping — directly answers T2 #1/#2.
- Hard-timeout readiness with log dump + non-zero exit — answers T2 #1 hang risk.
- Worker-image smoke test + `[worker]` extra decision — answers T2 #3.
- Structural fail-closed gate with machine-readable gate line — answers T2 #4.
- Clean-resolve multipart with import-assert unit test — answers T2 #5.
- Split-job filters, cache, ordering, unconditional-on-main — answers T2 critique of Approach 3.
- Approach 4 dropped as release surface; alternatives (B)/(C) dropped — consistent with R4/R3/R2.

### Persisting risks (ranked)

| # | Risk | Severity | Status |
|---|------|----------|--------|
| 1 | SDK↔server pair + shim surface unproven; first live run expected to surface SDK defects | HIGH | Open (by design; discovery-run posture) |
| 2 | Cold-boot readiness timeout tuning (90s guess vs measured) → flaky gate | MEDIUM | Open (measure in runs #1-#3) |
| 3 | Release job allows E2E skip if scheduler not active at E2E start | HIGH | Open (must FAIL, not skip, in release jobs) |
| 4 | gRPC broadcast/route misconfig → workers never execute, confusing UNAVAILABLE | MEDIUM | Open (assert registration via engine; remove "candidate" parenthetical only after live proof) |
| 5 | Volume-wipe between restart segments silently vacuously-passes persistence tests | MEDIUM | Open (add pre/post namaste + stage_run assertions) |
| 6 | allow-live-failure policy reopens gate if release reads checkmark not gate line | MEDIUM | Open (human decision, T8) |
| 7 | Uncommitted fixes unproven until pushed and hosted-run (R1) | LOW (process) | Open (commit+push first step) |

---

## Implementation Patterns

*Turn 5 (T5) — rnd-improver (first spawn), 2026-08-28. Grounded in the surviving Refined Approach A. Each pattern cites real-world practice/production implementations; each key library validated against current official documentation with check date.*

### Pattern 1 — Data flow: "submit-workflow-per-stage, callbacks own completion"

**Pattern.** Public API → `JobService.submit` → `ProductionDAGRunner.run_graph` → `submit_workflow_runs` (one Hatchet workflow run per stage `umd-{stage.lower()}` with `depends_on` from `STAGE_DEPENDENCIES`) → durable queue → worker callback `_make_handler` → `DurableStageExecutor.run` (claim-before-side-effect) → `StageCompleted`/`StageFailed` recorded in Postgres → projections refresh. Events are `queued` on submission; completion is only ever recorded by the callback. This is the CONTRACTS.md:60-63 shape and the UMD codebase already implements it; the repair restores it as the wired path and proves it live.

**Real-world basis.** This is the canonical durable-DAG pattern: a service submits jobs to a scheduler and workers own execution with idempotent claims. Hatchet's own Python quickstart exercises exactly "worker registers workflows, engine dispatches, worker executes" (https://github.com/hatchet-dev/hatchet-python-quickstart, checked 2026-08-28); Greptile's Hatchet DAG (https://hatchet.run/customers/greptile, carried forward) is the production-scale instance of per-node submit + durable execution. FastAPI-based services that submit to a durable scheduler (rather than running the DAG in-process) follow the same "API returns 202-style queued status; completion observed via DB" contract.

### Pattern 2 — State management: "Postgres is the authority; Postgres is the scheduler's authority"

**Pattern.** Job/stage state lives in Postgres (JobRunAudit, StageRunRepository with UNIQUE(idempotency_key) claims, PostgresQuarantine). Scheduler state (Hatchet workflow runs) is *derived* — `/v1/jobs/{id}` reads Postgres, never the scheduler API. Restart = new app/worker processes over the same engine/store (handoff §4: stop/start, never down/up; volumes `ocfl-db`, `ocfl-data` persist). The capability probe caches in-process with a TTL, but the probe's *verdict* is derived from an actual execution, not from env state.

**Real-world basis.** Event-sourced/append-only authority with rebuildable projections is the UMD's settled architecture (research report, 2026-08-25). For the scheduler, Hatchet's own persistence model keeps workflow state in Postgres and the official docs' troubleshooting (https://docs.hatchet.run/v1/troubleshooting, checked 2026-08-28) confirms workers authenticate to the engine's Postgres-backed state. The "status read from Postgres, not from the scheduler API" rule avoids the dual-source-of-truth hazard the handoff flags in JobService.submit (immediate status refresh racing callback-owned completion).

### Pattern 3 — Error handling: "bounded retry for transient, quarantine for deterministic, fail-closed for gates"

**Pattern.** Per-stage: transient failures retry with bounded backoff (RealBackoff/RetryPolicy); deterministic failures quarantine (PostgresQuarantine) with the failure recorded in the audit trail. Worker boot: honest gates — exit 2 on missing SDK/env/executors (`cli.worker()`), with the ready line printed only after bound callbacks. CI gate: fail-closed — missing live evidence fails the job; `capture-diagnostics` and teardown always run (`if: always()`, `continue-on-error`), never `|| true` on the evidence-producing steps.

**Real-world basis.** The `|| continue` swallowing of a failed backup, and its fix (remove silent continue; hard-fail on required evidence), is documented in a real migration incident — Adventurers-Guild commit ea56a04 "fix: pin pg_dump ... hard-fail migrate-deploy on backup failure" (checked 2026-08-28). The same principle — required evidence steps must hard-fail — is applied to the live gate. Hatchet's Python SDK changelog (https://docs.hatchet.run/reference/changelog/python, checked 2026-08-28) documents SDK-side error-handling fixes ("Stops retrying gRPC requests on 4XX failures", typed transport exceptions), reinforcing the pattern that retry policy belongs to the executor, not the SDK.

### Pattern 4 — Testing: "four tiers, hosted evidence for release"

**Pattern.** (1) **Unit** (hermetic, no scheduler): pin-agreement tests (`HATCHET_SDK_VERSION`/`HATCHET_SERVER_IMAGE` vs pins), capability-state tests, runner shape (dict-client submission), the import-assert for `python_multipart`; (2) **Postgres integration**: real media decomposition with the multipart API + `_poll_to_terminal`; (3) **Live shape** (`@pytest.mark.cluster`, real binding): the three `test_live_hatchet_*` tests polling Postgres up to 120s for distinct idempotency keys / StageCompleted counts / distinct dag_universe; (4) **Public-boundary E2E** (HTTP-only, enforced by `test_api_boundary_guardrails.py`): ingest → decompose → retrieve → correction → invalidation → restart → consistency classes, gated on `_require_production_path` — which, per T4, must FAIL (not skip) in release jobs when the scheduler is not active.

**Real-world basis.** The four-tier split with a hard-gated live tier is standard for systems with a scheduler dependency; the boundary-E2E's HTTP-only enforcement mirrors how FastAPI E2E suites isolate the public contract from internals. sdr-enthusiasts/docker-acarshub's `fullstack-e2e.yml` (checked 2026-08-28) demonstrates the compose-up + host pytest + `if: always()` teardown shape in GitHub Actions, which is the delivery vehicle for tiers 3–4 here.

### Pattern 5 — CI orchestration: "pre-flight probe → build → boot → gate → E2E → restart → evidence"

**Pattern.** In the docker-e2e job, in order: (1) **pre-flight** — `docker manifest inspect` on the exact pinned sub-path image refs + SDK/server pair tripwire (fast, attributable failures); (2) **build** — `docker compose build api worker` with the `[worker]` extra; (3) **worker-image smoke** — import `hatchet_sdk` in the built image; (4) **boot** — compose up `db api hatchet worker sandbox-runner` with required secrets; wait-for-http `/v1/ready` (240s); wait-for-worker with hard timeout (T3/T4: 90s configurable, measured); (5) **live gate** — assert worker registration via engine + capability probe `active`; (6) **public-boundary E2E** (FAIL-not-skip on inactive scheduler); (7) **persistence segments** — restart with stop/start, pre/post OCFL namaste + stage_run assertions (T4 #5); (8) **evidence** — `record-release-summary.sh` emits machine-readable `live-worker-gate: PASS|FAIL` + JUnit upload (`actions/upload-artifact@v4`, required since v3 deprecated 2024-11-30 — prior T1); teardown `down -v --remove-orphans` in `if: always()`.

**Real-world basis.** Registry pre-flight against GHCR `denied` semantics: devopsaitoolkit.com/blog/docker-error-pull-access-denied (checked 2026-08-28) and latchkey.dev/learn/docker/docker-compose-pull-access-denied-image-in-ci (checked 2026-08-28) both document probing the exact reference before compose-up. Compose secrets provisioning in CI: the UMD failure (`HATCHET_COOKIE_SECRET` missing at interpolation) is the canonical "CI never exported required compose vars" class; the fix is a single step that sets them for the compose job.

### Pattern 6 — Library/version choices (validated 2026-08-28)

| Library | Version | Why | Source | Status |
|---------|---------|-----|--------|--------|
| hatchet-sdk | 1.38.1 (worker extra) | Sole scheduler client; contemporaneous with server v0.105.2 | https://pypi.org/project/hatchet-sdk/ | EVIDENCE-BACKED release; pair CANDIDATE until live |
| Hatchet server | v0.105.2 sub-path images | Sole scheduler; full topology in CI | https://docs.hatchet.run/self-hosting/docker-compose | EVIDENCE-BACKED paths; boot PROVISIONAL |
| python-multipart | 0.0.32 | Post-namespace-fix pin for form/file parsing | fastapi #5144/#12532 | EVIDENCE-BACKED |
| ffmpeg | apt (ubuntu-latest) | Required for video/audio fixtures in hosted run | commitizen#1870 (runner drift risk) | EVIDENCE-BACKED |
| postgresql-client-17 | PGDG apt | pg_dump/psql vs postgres:17 service | shallowbrooksoftware.com; stackoverflow 79105375 | EVIDENCE-BACKED |
| actions/checkout, setup-python, upload-artifact | v4/v5/v4 | Current majors; artifact v4 required | prior T1 | EVIDENCE-BACKED |

---

## Pattern Risks

*Turn 6 (T6) — rnd-counter-improver (first spawn), 2026-08-28. For each T5 pattern: edge cases, integration risks, library-specific gotchas, and cross-pattern interaction failures, with trigger conditions and whether they match the UMD use case. Each risk cites a real source; where a reported issue applies to a different SDK version, that is stated.*

### Risk 1 — Pattern 1 (submit-workflow-per-stage): the shimmed submission surface is the single most fragile point

**Risk.** `_SDKSubmissionShim` duck-types `submit_workflow_run` onto `Hatchet.runs.admin_client().run_workflow(workflow_name, json.dumps(input))`. The Python SDK changelog (https://docs.hatchet.run/reference/changelog/python, checked 2026-08-28) shows active surface churn — gRPC retry behavior changed ("Stops retrying gRPC requests on 4XX failures"), typed transport exceptions added, `aio_sleep_for`/`SleepCondition` bugs fixed. **Trigger:** any of (a) `run_workflow` signature change, (b) admin-client auth shape change, (c) worker namespacing (`client.task(name=...)`) drift between registered name and submitted name, (d) payload size limits on `json.dumps(input)` — the UMD run_input carries `dag_universe`, `manifest.to_dict()`, `causation_id`; large manifests (audio/video metadata) could exceed gRPC message limits. **Matches UMD:** YES — exactly the unproven live surface (T4 #1). **Mitigation:** the live shape tests ARE the surface check; add an explicit payload-size boundary test (large manifest → submission succeeds); the pin lock (test asserting installed `hatchet_sdk.__version__ == "1.38.1"`) prevents silent SDK drift; upgrade rule (handoff §1: bump SDK+server lockstep, new DAG universe, drain) governs any future bump.

### Risk 2 — Pattern 2 (Postgres authority): dual-writer race between JobService.submit refresh and callback-owned completion

**Risk.** `src/umd/application/jobs.py:90-116` — `JobService.submit` immediately refreshes status after submission; callbacks later record `StageCompleted`. If submit's refresh writes a terminal-looking state (or if the callback and the refresh race on the same stage row), the public API can report stale or contradictory status. **Trigger:** any submission where the callback completes faster than the refresh read (fast stages, in-process debug backend). **Matches UMD:** YES — handoff §6 and CONTRACTS.md flag this exact contract ("status read from Postgres; callback-owned completion"). **Mitigation:** submit must record only `queued` (it already emits `queued` events — CONTRACTS-compliant); the refresh must be read-only and must not overwrite terminal states; add a status-transition invariant test (queued→running→complete is append-only; never complete→queued).

### Risk 3 — Pattern 3 (bounded retry/quarantine): retry-policy interaction with the SDK's changed gRPC retry behavior

**Risk.** The SDK now stops retrying gRPC requests on 4XX and raises typed transport exceptions; the executor's `RealBackoff/RetryPolicy` decides retry vs quarantine. If the executor treats an SDK-level 4XX (e.g. 401 token, 404 workflow-not-found) as transient, it will retry a deterministic failure to exhaustion, then quarantine — correct but slow. If it treats a *transient* SDK transport error as deterministic, work is quarantined that a retry would have completed — losing the durable-restart guarantee R3 demands. **Trigger:** token rotation mid-run, engine restart during a run, workflow-name mismatch. **Matches UMD:** YES — the retry/quarantine boundary is exactly what the three live shape tests must prove. **Mitigation:** classify SDK exceptions: 4XX → deterministic (quarantine), transport/timeout → transient (retry); assert this classification in a unit test that mocks SDK exceptions; the live shape test `test_live_hatchet_retry_and_quarantine_single_authoritative_completion` verifies end-to-end.

### Risk 4 — Pattern 4 (four-tier testing): the "FAIL not skip" rule for `_require_production_path` is a behavioral change that can break local dev

**Risk.** T4 demanded the release job FAIL (not skip) when the scheduler is inactive; but the same `_require_production_path` is used by local dev where skipping is correct (no scheduler). If the rule is implemented as "always fail", local dev can no longer run the boundary E2E subset that needs no scheduler (the correctness/metadata tests that don't touch live paths). **Trigger:** a single shared skip helper with no release-vs-dev distinction. **Matches UMD:** YES — `_require_production_path` is shared. **Mitigation:** the helper takes a `release` flag: in release jobs, inactive scheduler → FAIL with the capability report in the failure message; locally, inactive scheduler → skip (context only, R6). The release flag is set by the CI job, never defaulted on locally.

### Risk 5 — Pattern 5 (CI orchestration): cold-boot timing, image-tag drift, and teardown ordering

**Risk (a) cold-boot timing.** The 90s worker-readiness timeout is a guess (T4 #2); a cold engine boot (migrations + config seeding) on a shared hosted runner can exceed it → flaky red → someone disables the gate. **Risk (b) `latest` drift.** Hatchet's own compose examples use `:latest` (docs, checked 2026-08-28); UMD pins `${HATCHET_VERSION:-v0.105.2}` in compose and constants in code — but the *compose default can be overridden by env* (`HATCHET_VERSION`), and nothing currently fails if a caller sets a drifting value. **Risk (c) teardown order.** `down -v --remove-orphans` in `if: always()` destroys volumes; if any step between restart segments re-triggers down, persistence evidence is silently destroyed (T4 #5). **Matches UMD:** all three YES. **Mitigation:** (a) measure and set the timeout from runs #1–#3 timestamps (configurable, logged); (b) pin-agreement test asserts compose default == code constant == pins file; the compose var becomes a fixed default with no override in the release path (or an override that itself fails the pin test); (c) guard restart segments with pre/post OCFL namaste + stage_run assertions.

### Risk 6 — Pattern 6 (libraries): version-specific gotchas that DO apply to our pins

**Risk (a) python-multipart namespace shadowing.** fastapi discussion #5144 (checked 2026-08-28) documents that installing BOTH `multipart` and `python-multipart` (or resolving an old lockfile) recreates "Form data requires python-multipart" even when the package is present — this is a *resolve-time* trap, not just an install-time one. Our pin 0.0.32 is post-fix (imports `python_multipart`), but the CI must verify a clean resolve (no transitive `multipart`); the import-assert unit test covers this. **Risk (b) hatchet-sdk worker loop blocks forever** — `Worker.start()` runs forever (T1), so the ready line printed before `start()` is the ONLY signal the gate sees; a worker that prints ready then fails to register (hatchet-python-quickstart#16 class) would pass a naive grep. **Matches UMD:** YES — `wait-for-worker.sh` greps `worker ready: registered` (handoff §3). **Mitigation:** the gate must ALSO verify engine-side registration (probe or engine check), not just the log line; the "candidate" parenthetical in the ready line stays until a live run proves registration. **Risk (c) ffmpeg install drift on ubuntu-latest** — commitizen-tools/commitizen#1870 (2026-02-14, checked 2026-08-28) documents ffmpeg install failure on the Ubuntu 24.04 runner image via a third-party action; UMD's direct `apt-get install ffmpeg` is less fragile, but the runner image can still change under us. **Mitigation:** keep the apt install in the same job that needs it (test-postgres), fail loudly if it fails, and record the ffmpeg version in diagnostics.

### Cross-pattern interaction failures

1. **Probe (Pattern 5) × E2E skip rule (Pattern 4):** if the submit+poll probe's TTL (30s) expires mid-E2E, `/v1/capabilities` can flip to `configured-but-unavailable` between the E2E's setup check and its long-running segments → the release job either skips (violating T4's FAIL rule) or fails spuriously. **Mitigation:** release-job E2E re-probes at segment boundaries; the FAIL-not-skip rule applies per segment; probe TTL > longest E2E segment.
2. **Restart persistence (Pattern 2) × teardown (Pattern 5):** described in Risk 5(c). The restart segment's "new app over same engine/store" only proves durability if the volumes survive; the pre/post namaste assertions are the tripwire.
3. **Worker-image smoke (Pattern 5) × packaging (Pattern 6):** if `pip install .[worker]` is applied but `cli.py`'s exit-2 path is removed as "dead code", the honest-gate distinction collapses; the smoke test must assert the exit-2 path still exists for a stripped image (negative test: build without extra → expect exit 2).

### Risk summary

| # | Risk | Severity | Applies to our pins? | Mitigation |
|---|------|----------|----------------------|------------|
| 1 | Shimmed submission surface drift + payload limits | HIGH | YES (unproven live surface) | Live shape tests + payload-boundary test + pin lock |
| 2 | Submit-refresh vs callback completion race | MEDIUM | YES | queued-only writes; append-only transition test |
| 3 | SDK 4XX vs transport classification on retry boundary | MEDIUM | YES | exception classification unit test; live retry shape test |
| 4 | FAIL-not-skip rule breaks local dev | MEDIUM | YES | release flag in helper; local skip stays (R6) |
| 5 | Cold-boot timeout; `latest`/env drift; teardown volume wipe | MEDIUM | YES | measure; pin-agreement test; namaste guards |
| 6 | multipart shadowing; ready-line-only gate; ffmpeg drift | MEDIUM/HIGH | YES | clean-resolve assert; engine-side registration check; apt in-job |

---

## Final Patterns

*Turn 7 (T7) — rnd-improver (resumed session), 2026-08-28. Every T6 risk is addressed: mitigated with cited evidence, or acknowledged as fundamental. Refined patterns supersede the T5 versions where changed.*

### Addressing T6 risks

| T6 risk | Disposition | Resolution |
|---------|-------------|------------|
| 1 — Shimmed submission surface drift + payload limits | **Mitigated** | The live shape tests remain the surface check; ADD payload-boundary test (large manifest with audio/video metadata → submission succeeds and appears as queued) and pin-lock test (`hatchet_sdk.__version__ == "1.38.1"`); upgrade rule (handoff §1 lockstep bump + new DAG universe + drain) is the governance. The shim itself stays behind the existing seam so the live surface is isolated to one module. |
| 2 — Submit-refresh vs callback completion race | **Mitigated** | Submit records only `queued` (already CONTRACTS-compliant); refresh is read-only and never overwrites terminal states; ADD append-only status-transition invariant test (queued→running→complete; complete never reverts). This is a test + contract assertion, not new machinery. |
| 3 — SDK 4XX vs transport classification on retry boundary | **Mitigated** | ADD exception-classification unit test: SDK 4XX (401/404) → deterministic → quarantine; transport/timeout → transient → retry. The live shape test `test_live_hatchet_retry_and_quarantine_single_authoritative_completion` verifies end-to-end. Cited: Python SDK changelog documents the 4XX retry stop and typed transport exceptions (https://docs.hatchet.run/reference/changelog/python, checked 2026-08-28). |
| 4 — FAIL-not-skip rule breaks local dev | **Mitigated** | `_require_production_path` takes a `release` flag: release job → inactive scheduler FAILS with the capability report in the message; local dev → skip (R6, context only). The flag is set by the CI job, never defaulted locally. |
| 5a — Cold-boot timeout guess | **Mitigated** | Timeout is configurable and set from runs #1–#3 measured timestamps (logged in diagnostics); initial 90s stands as a floor, measured value becomes the default. |
| 5b — `latest`/env drift | **Mitigated** | Pin-agreement test asserts compose default == code constant (`src/umd/jobs/hatchet.py`) == pins file (`deploy/pins/runtime.txt`); the compose `HATCHET_VERSION` var is fixed in the release path (no override), or an override fails the pin test. |
| 5c — Teardown volume wipe | **Mitigated** | Restart segments guarded by pre/post OCFL namaste (`0=ocfl_1.1`) + stage_run row-count assertions; any vanished volume fails the job. `down -v` only at final teardown. |
| 6a — multipart namespace shadowing | **Mitigated** | Clean-resolve verification in the hosted run; import-assert unit test (`import python_multipart`); pin 0.0.32 (post-fix, fastapi #5144). |
| 6b — ready-line-only gate | **Mitigated** | Gate verifies engine-side registration (capability probe's submit+poll or an engine registration check), NOT the log line alone; the "candidate" parenthetical in `worker ready: registered N Hatchet workflows` is removed only after a live run proves registration. |
| 6c — ffmpeg install drift | **Mitigated** | Apt install stays in the job that needs it (test-postgres), fails loudly, and the installed ffmpeg version is recorded in diagnostics; pinned `ffmpeg` package via `apt-get install -y ffmpeg` is the direct, least-fragile path (commitizen#1870 was a third-party action, not apt — acknowledged). |

**No fundamental limitations required acknowledgment** — every T6 finding is mitigable in code/test/workflow with no residual behavior the design must live with. The one *unavoidable* residual is the pair-compatibility uncertainty itself (T4 #1), which is not a pattern defect but a fact to be discovered on the first live run; the design accounts for it with the discovery-run posture.

### Refined Pattern Deltas (supersede T5 where noted)

- **Pattern 1 (data flow)** — unchanged, plus payload-boundary test and pin-lock test (T6-1 mitigation).
- **Pattern 2 (state)** — unchanged, plus append-only status-transition invariant test (T6-2).
- **Pattern 3 (errors)** — ADD SDK exception-classification unit test (T6-3); gate reads machine-readable `live-worker-gate: PASS|FAIL` (T3) and registration verification (T6-6b).
- **Pattern 4 (testing)** — `_require_production_path(release: bool)`; release jobs FAIL-not-skip, local dev skips (T6-4). E2E re-probes at segment boundaries; probe TTL > longest segment (cross-pattern fix).
- **Pattern 5 (CI)** — pre-flight probes (T3/Approach 2) + measured timeout (T6-5a) + fixed pin default (T6-5b) + namaste guards around restart segments (T6-5c) + engine-side registration gate (T6-6b) + ffmpeg version in diagnostics (T6-6c).
- **Pattern 6 (libraries)** — unchanged pins; all revalidated 2026-08-28 (hatchet-sdk 1.38.1 PyPI; python-multipart 0.0.32; ffmpeg/PGDG apt; actions v4/v5/v4).

### Final verification order (what runs, in what order, and what proves it)

1. **Commit + push the five working-tree fixes** → hosted run #1: unit + postgres jobs must pass (R1, R2). Local green is NOT evidence (R6).
2. **Repair image path + packaging + gate polarity** → hosted run #2: docker-e2e pre-flight passes, stack boots, worker registers (candidate→real), boundary E2E runs with scheduler ACTIVE (R4).
3. **Wire ProductionDAGRunner + probe** → hosted run #3: live shape tests pass on the same stack (R4); restart/durability segments pass with namaste guards (R3); E2E segments pass with FAIL-not-skip (R3).
4. **Release gate reads `live-worker-gate: PASS|FAIL`** independent of job verdict; JUnit + job summary uploaded (R1); optional split-job follow-up after green (T3 Approach B).

**Stop/rollback conditions:** any hosted run that reveals a pin/pair incompatibility stops the release — do NOT bump the pair unilaterally; apply handoff §1 upgrade rule (lockstep bump + new DAG universe + drain) as a design change. Any step that weakens a gate (reverts polarity, expands skips, removes namaste guards, drops the FAIL-not-skip rule) is a release-gate regression and blocks completion (R4/R3). If hosted evidence contradicts the image-path or pair claims, the pin documentation (`deploy/pins/runtime.txt`, handoff table) is corrected with the observed evidence — never by guessing.

---

## Open Risks & Human Questions

*Turn 8 (T8) — rnd-counter-improver (resumed session), 2026-08-28. Assesses T7 against T6. Verdict: every T6 finding received a concrete mitigation — none were dismissed or restated. What remains below is (1) genuinely unresolved risks and (2) questions that require human judgment because evidence alone cannot decide them.*

### Assessment of T7 vs T6

All six T6 risks are addressed with test/workflow changes that preserve or strengthen the release gate. No weakening: the FAIL-not-skip rule, the pin lock, the namaste guards, and the engine-side registration check are all *stronger* than the pre-T6 design. The claim "no fundamental limitations required acknowledgment" is fair **with one exception the Improver itself named**: pair compatibility is a fact to be discovered, not a pattern to mitigate — this belongs in the open risks below, not in the pattern table.

### Unresolved risks (not resolvable without live evidence)

1. **SDK 1.38.1 ↔ server v0.105.2 pair compatibility (CANDIDATE, PROVISIONAL).** Every mitigation (pin lock, payload test, live shapes) detects failure after the fact; none *predicts* compatibility. The pair is contemporaneous (both released 2026-08-25 — PyPI https://pypi.org/project/hatchet-sdk/, GitHub release v0.105.2) but unproven end-to-end. First live run may surface shim-surface defects (T4 #1). **This is the release's critical path.**
2. **Engine gRPC routing in the CI network is PROVISIONAL** (SERVER_GRPC_BROADCAST_ADDRESS / SERVER_GRPC_INSECURE values). Wrong values produce the "registers-but-never-executes" class (hatchet-python-quickstart#16). Detection: engine-side registration count + shape-test execution. Resolution: observed in run #2.
3. **The `_require_production_path` release-flag change is designed but not yet written.** It is a one-parameter behavior split (FAIL in release, skip locally); until implemented, the boundary E2E's honest gating depends on the probe's truthfulness alone.
4. **Worker-ready timing is measured, not predicted** (T6-5a): the first cold boot may exceed 90s; the plan's discovery-run posture absorbs this, but a flaky first gate could tempt a revert — a human process risk, not a code risk.
5. **The docker-e2e step-6 raw error text was never retrieved** (artifact download requires auth; prior researcher caveat). The image-path diagnosis rests on the 36s duration + 403 probes + official docs, which is high-confidence but not the raw log line. If run #2's pre-flight contradicts it (e.g., top-level image suddenly exists), the pin documentation must be corrected from observed evidence.

### Human-judgment questions (evidence cannot decide these alone)

1. **Release-evidence stack: full multi-service topology vs `hatchet-lite` in CI.** Evidence: handoff §8 demands shape tests pass on "the same Compose/CI stack" users deploy → full topology; but full topology costs more CI time and has more boot surface (engine + admin + migrate sidecars). **Recommendation (evidence-backed):** full topology in the release path; Lite only as documented dev convenience. The team must confirm the cost is acceptable — this is the one place where CI-budget preference can override the recommendation without violating R4 (Lite is official Hatchet, not a second scheduler).
2. **`allow-live-failure` policy for `workflow_dispatch`.** Who may run it, and does the release gate read the machine-readable `live-worker-gate: PASS|FAIL` line or the job checkmark? Evidence says the FAIL line must be authoritative (Adventurers-Guild incident: silent evidence swallowing caused a production backup-less migration). **Recommendation:** the release gate reads the FAIL line only; allow-live-failure is restricted to maintainers and never merges evidence into a release path.
3. **Make `hatchet-sdk` a core dependency vs keep the `worker` extra?** Keeping the extra preserves the honest exit-2 gate and smaller API image; promoting simplifies packaging but removes the "SDK absent" honesty signal. Evidence: the exit-2 path is a deliberate honesty gate (cli.py). **Recommendation:** keep the extra; `pip install .[worker]` in the Dockerfile; negative smoke test asserts the exit-2 path survives. Team confirms image-size/rebuild tradeoff.
4. **How many hosted iterations are budgeted before escalation?** Evidence: the plan expects run #1 to surface SDK-surface defects (discovery posture). **Recommendation:** budget 3 hosted runs for the three verification steps (env fixes → stack/gate → wiring/live), then escalate to RnD-Manager with the captured diagnostics if not green — escalation is the R5 process, not failure.
5. **Does the release gate block PRs or only push-to-main?** Evidence: path-filter drift can silently skip the live job on PRs (T2 critique of Approach 3); unconditional-on-main is the safe default. **Recommendation:** live evidence required on push-to-main; PRs run the live job only when scheduler-adjacent files change (exhaustive filter list, T3). Team decides whether PR green also requires the live gate — the stricter choice costs more runner-minutes.

### Provisional / unvalidated technology claims (final register)

| Claim | Status | What closes it |
|-------|--------|----------------|
| hatchet-sdk 1.38.1 ↔ server v0.105.2 pair compatible | **PROVISIONAL** | Hosted live shape tests pass on the same stack (run #3) |
| Engine gRPC env values for CI network | **PROVISIONAL** | Hosted stack boot + registration (run #2) |
| Full sub-path image topology boots in CI | **PROVISIONAL** | Hosted pre-flight + compose up (run #2) |
| Top-level image 403 = path error (no raw log line) | EVIDENCE-BACKED (high-confidence inference) | Raw docker-e2e step-6 log if retrievable |
| python-multipart 0.0.32, ffmpeg/PGDG apt, actions v4/v5/v4 | EVIDENCE-BACKED | Hosted env-fix pass (run #1) |

### Final adversarial verdict

The design that survives eight turns: **Refined Approach A — Coordinated Full Repair with Structural Gate Enforcement** (commit fixes → repair image path → package SDK → wire ProductionDAGRunner → execution-based probe → structurally fail-closed gate → FAIL-not-skip boundary E2E → measured timing → persistence guards → hosted evidence), with Approach 2's pre-flight probes folded in and Approach 3's split-job CI as a post-green follow-up. Approach 4 (Lite) is dev-only. Alternatives (B) CI-only-deferred and (C) opt-in/skip/recording-doubles are rejected under R4/R3 and R2/R4 respectively. The design satisfies R1 (hosted push + report retrieval), R2 (real diagnosis; no stubs/skips/weakened assertions), R3 (Task.md DoD cross-check via E2E, durable restartable DAG, selective invalidation/rerun, honest capabilities, final adversarial review), R4 (Hatchet sole v1 scheduler; live registration + real stage execution as release gate), R5 (support → design → plan → Exec-Manager), R6 (local checks context only).

---
*End of adversarial log. Final status: COMPLETE — all 8 turns (T1–T8) present, substantive, evidence-backed, with requirement mapping per turn. The design document (DD-universal-media-decomposer-ci-repair.md) remains a skeleton; DDAuthor distills these decisions.*
---
