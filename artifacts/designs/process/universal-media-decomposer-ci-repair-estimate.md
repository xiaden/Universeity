# Universal Media Decomposer — Scoped CI Repair / Release-Gate Restoration — Final Effort Estimate

**Status:** DONE — read-only estimation; evidence-backed from the debugger report, support-researcher findings, the scoped adversarial log, the scoped DD skeleton, Plan J, and first-hand reads of the actual affected files. No code written, no plan created, no DD authored/amended, no production file edited.
**Date:** 2026-08-28
**Agent:** `rnd-estimator`
**Work item:** Repair the hosted GitHub CI (run 33164294061) and restore the mandatory Hatchet live release gate — **scoped to the existing repository**, NOT the original greenfield UMD build. Estimate implementation complexity from the real affected files and the confirmed defect classes.

**Scope caveat (important):** this estimate sizes the *repair* of an existing codebase. It is deliberately not a re-derivation of the original EPIC estimate (`universal-media-decomposer-final-estimate.md`, ≈59.3M weighted chars). The immutable requirement ledger (R1–R6) is preserved and carried forward verbatim (§6).

---

## Executive result

| | |
|---|---|
| **Size tier** | **LARGE** |
| **Confidence** | **LOW** (known scope is LARGE; the genuine live-Hatchet execution path is unproven and its fix count is not enumerable from static analysis) |
| **plan_needed** | **true** (weighted_chars ≈ 87K ≫ 32K) |
| **dd_needed** | **true** (weighted_chars ≈ 87K ≥ 80K, AND the production-runner wiring + gate-posture decision is a structural choice) — the scoped DD skeleton `DD-universal-media-decomposer-ci-repair.md` already exists and satisfies this gate |
| **fixComplexity** | **NEEDS_PLAN** (crosses workflow provisioning, deployment topology, app wiring, live-gate, and live tests — not `SIMPLE`/Exec-Fixer eligible) |

The repair is **cross-cutting and multi-layer**: it spans CI workflow provisioning, the Compose/GHCR deployment topology, Docker packaging, the production API runner wiring, the capability-reporting seam, the live-gate posture, and three live shape tests plus the public-boundary E2E. It is not a single function or section. The dominant cost driver is **not** the enumerated edits (which are bounded) but the **hosted live-Hatchet execution loop**: SDK↔server surface mismatches (task-name namespacing, `run_workflow` payload shape, gRPC `host_port` routing) can only be discovered and fixed against a real running cluster, and each discovery is gated on a full pushed hosted CI iteration under R1. That unknown is why confidence is LOW despite a firmly bounded known scope.

---

## 1. Formula inputs (measured, not greenfield)

Inputs are the affected files named by the debugger report and confirmed by direct reads. Edit-scope chars = the sections being edited plus adjacent context needed to understand them (conservative, rounded up). Tests are included.

| Input | Value | Basis |
|---|---|---|
| **Files — modify** | 17 | See §2 workstream file lists |
| **Files — create** | 2 | Likely `deploy/compose.ci.yaml` override (if CI topology split chosen) + a sub-path image pin-agreement test |
| **Files — delete** | 0 | None confirmed |
| **Files — total** | 19 | |
| **Sections** (distinct edit locations) | 30 | Workflow (6), compose (3), Dockerfile (1), pyproject (2), app.py (3), runner.py (2), hatchet.py (3), capability.py (2), jobs.py (2), cli.py (2), tests (8), new (1) |
| **char_count** (edit-scope chars) | 41,000 | Sum of the edited sections + required adjacent context (see §2); conservative round-up |
| **cognitive_weight** | 2.13 | 1 + 0.03×(30−1) + 0.015×(19−1) = 1 + 0.87 + 0.27 |
| **weighted_chars** | **87,300** | 41,000 × 2.13 |

**Threshold crossings:**

| Threshold | Value | Criteria |
|---|---|---|
| TRIVIAL | < 8K | — |
| SMALL | 8K–32K | — |
| MEDIUM | 32K–80K | — |
| **LARGE** | **80K–320K** | **≈87K → LARGE (just above the 80K floor)** |
| EPIC | ≥320K | Not reached |

The tier is not fragile: the edit scope is already counted conservatively, and the known edits alone (provisioning + topology + wiring + live gate + test repairs) land at the LARGE floor. The EPIC tier is **not** warranted because this is repair of existing code, not greenfield creation — the dominant EPIC drivers of the original estimate (310 new files, 950 sections, ≈1.74M chars) are already built.

---

## 2. Workstream breakdown (scoped to actual affected files + evidence)

### W1 — Commit the hosted-runner environment provisioning fixes (CI never saw them)

The debugger confirmed these are already in the working tree but were **not** present in the GitHub checkout at commit `a6b1a62`, so they cannot explain or repair the failed run until committed + pushed (R1):

- `.github/workflows/validation.yml` — add `ffmpeg` + PGDG `postgresql-client-17` install step to the `test-postgres` job (fixes 6 FFmpeg `FileNotFoundError` + the `pg_dump` missing-binary failure). *Working-tree diff present (+59 lines).*
- `pyproject.toml` — pin `python-multipart==0.0.32` (fixes the 6 `AssertionError: python-multipart must be installed` failures at `test_api_contract.py:967,997` + `test_phase4_heterogeneous_ingestion.py`). *Present in tree.*
- `tests/conftest.py` — `_resolve_pg_bin()` helper (robust `pg_dump` path resolution, `UMD_PG_BIN` authoritative). *Present in tree.*
- `tests/test_deployment_phaseE.py` — `HATCHET_COOKIE_SECRET`/`HATCHET_MASTER_KEY` `env.setdefault` for the `docker compose config` test (keeps `${VAR:?}` required — does NOT weaken R2; test correctly exposes the env mismatch). *Present in tree.*

**This workstream alone fixes the 6 multipart + 6 FFmpeg + 1 pg_dump + 1 Compose-interpolation failures.** It is mechanical but must be committed and proven by a new hosted run; local green is not evidence (R6).

### W2 — Wire the production runner + repair the genuine deployment gap

These are confirmed genuine gaps, not CI packages:

- `src/umd/api/app.py:167` — `build_context` injects `DurableDAGRunner` (in-process synchronous), not `ProductionDAGRunner`. Fix: construct `ProductionDAGRunner` over the sole Hatchet scheduler (per Approach A: behind an explicit non-release env only, e.g. `UMD_EXECUTION_BACKEND=durable` for hermetic seams; `/v1/capabilities` must reflect which backend is active). This is the R4 wiring decision.
- `deploy/compose.yaml:104` — top-level `ghcr.io/hatchet-dev/hatchet:v0.105.2` image does not exist (confirmed `403 DENIED` by GHCR in the hosted run; support-researcher live probes confirmed the real images are sub-path `hatchet-engine` / `hatchet-admin` / `hatchet-migrate` / `hatchet-lite`). Fix the image path + topology; the `hatchet` service is currently a single service, so the multi-service topology (engine+admin+migrate+dashboard, or `hatchet-lite` for CI via a `compose.ci.yaml` override) must be reworked.
- `deploy/Dockerfile:32` — `pip install .` without the `worker` extra while `hatchet-sdk==1.38.1` lives in the optional `worker` extra. The worker image may not contain the SDK. Fix: `pip install .[worker]` (or make the worker extra a base dependency for the image). Must be validated against the Task.md Docker/modality requirements.
- `src/umd/jobs/hatchet.py:56` — `HATCHET_SERVER_IMAGE` constant must track the corrected sub-path pin + the P1-S3 pin-agreement test surface updated.
- `src/umd/deploy/cli.py` — verify the worker loop wiring against the real SDK (`cli.py` runs the blocking `hatchet.worker(...).start()`).

### W3 — Add a real capability connectivity probe

- `src/umd/jobs/capability.py` — confirmed defect (T1 correction): `CapabilityReporter` has **no connectivity probe**; it returns `configured-but-unavailable` whenever `UMD_HATCHET_SERVER_URL`/`UMD_HATCHET_TOKEN` are set, even against a reachable cluster. The docstring claims a reachable client flips it to `active`, but no reachability check exists. Fix: add a real probe (e.g. engine health fetch through the SDK client) so `active` is only ever true against a reachable cluster. **This is what honestly unblocks `_require_production_path`** in the boundary E2E — without it, wiring `ProductionDAGRunner` alone still leaves the E2E skipping.
- `tests/test_capability_transitions.py` — update expectations for the probe behavior (honest statuses preserved; no weakening).

### W4 — Restore the fail-closed live gate posture (not opt-in)

- `.github/workflows/validation.yml` — the docker-e2e job currently defaults `UMD_VALIDATE_LIVE_WORKER: false` and brings up only `db api` (`docker compose up --build -d db api`), making live worker validation opt-in. Per R4 + the handoff's hard gate (`HATCHET_LIVE_VALIDATION_HANDOFF.md:232-241`), the live path must be the release evidence: flip the default to `true`, start the full stack (`db api hatchet worker sandbox-runner`), and make worker-registration readiness a fail-closed gate. Optionally split into `docker-baseline` (proven stack, fast) + `docker-live` (mandatory gate) jobs (Approach B), or add a pre-flight `docker manifest inspect` + SDK/server-pair probe (Approach C, cheap + high-value failure attribution).
- Restart/durability/persistence + image-digest + release-summary steps already exist in the workflow; they must now pass against the live stack for real.

### W5 — Run and repair the live tests (unproven surface)

- `tests/test_hatchet_live.py` (1370 lines) — the three `@pytest.mark.cluster` shape tests (`test_live_hatchet_duplicate_and_restart_preserve_single_completion`, `...retry_and_quarantine_single_authoritative_completion`, `...universe_change_drains_and_rekeys`) already use a real `hatchet_sdk` client + real `DurableStageExecutor` + Postgres polling (T1 verified this — the `_RecordingClient`/`executor=None` defect described by the handoff §6 was already repaired in the tree). What remains unproven is **live execution itself**: no run has ever executed against a live cluster, so SDK-surface mismatches (task-name namespacing, `run_workflow` payload shape, gRPC `host_port` routing) are untested. These are findings after a live run — **not enumerable from static analysis** (the dominant unknown).
- `tests/test_api_boundary_e2e.py` (641 lines) — `_require_production_path` will stop skipping once the capability probe (W3) + live worker (W2/W4) are real; the full heterogeneous boundary scenario then runs against the live stack for real.
- `tests/test_api_contract.py` / `tests/test_phase4_heterogeneous_ingestion.py` — expected to pass once W1 fixes multipart; minimal or no edits.

### W6 — Hosted CI evidence iterations (the actual dominant cost)

- R1 mandates push + retrieve hosted runs. Each iteration is a full hosted run (lint/typecheck/unit/Postgres/Docker-E2E). The number of iterations required to get the live-Hatchet path genuinely green is a **variable, not a fixed count** — see §4. Local checks (Ruff/mypy/local pytest, prior `392 passed / 189 skipped`) remain context only (R6).

---

## 3. Per-layer allocation

| Workstream | Files | Sections | ~Chars | Reason |
|---|---|---|---|---|
| W1 provisioning (commit env fixes) | 4 | 5 | 9K | workflow install step + pyproject pin + conftest pg_bin + compose-config test |
| W2 runner wiring + deployment gap | 6 | 14 | 16K | app.py backend wiring, compose hatchet topology + image path, Dockerfile worker extra, hatchet constant, cli worker loop |
| W3 capability probe | 2 | 3 | 3K | capability.py probe + capability_transitions test |
| W4 live-gate posture | 1 | 3 | 4K | validation.yml gate default + full-stack startup (+ optional job split/pre-flight) |
| W5 live test repair | 3 | 4 | 8K | three shape tests + boundary E2E unskip + pin-agreement surface |
| W6 hosted iterations + new files | 3 | 1 | 1K | `compose.ci.yaml` override (maybe) + image pin test |
| **Totals** | **19** | **30** | **41K** | weighted ≈ **87.3K → LARGE** |

---

## 4. Dependencies and the hosted-evidence iteration variable

**Dependency graph (bounded):**
1. W1 must land first and be proven by a hosted run — it unblocks the multipart/FFmpeg/pg_dump/Compose-interpolation failures and is independent of the wiring decision.
2. W2's `ProductionDAGRunner` wiring depends on the compose/Dockerfile image-path + worker-extra fixes (the worker must exist and contain the SDK before it can register).
3. W3 (capability probe) is a precondition for the boundary E2E to unskip; W2 wiring alone is insufficient (the T1-verified gap).
4. W4 (gate posture) must be decided jointly with W2 — the live path only becomes release evidence if both the wiring AND the fail-closed gate land together.
5. W5 (live tests) is the terminal step and consumes every earlier workstream; its fix count is unknown until the first live run.

**Hosted-evidence iterations (the genuine unknown):**
- Minimum: **1** hosted run after committing W1 fixes (should turn the 14 PostgreSQL + 1 unit + Compose failures green, assuming no new regressions).
- Then the live path: **1+ iterations** to pull the corrected image, start the stack, get the worker registered, and pass the three shape tests + boundary E2E. Realistic expectation based on the T1-identified untested SDK surfaces (task namespacing, `run_workflow` payload, gRPC routing): **2–5 additional hosted iterations** to discover and fix surface mismatches.
- **Estimate: ≈3–7 total hosted iterations**, each a full run. This is the dominant schedule driver and the reason confidence is LOW. The count is not enumerable from code; it is bounded only by the requirement that every fix be proven on a hosted run (R1/R6).

---

## 5. Risks and gates

| # | Risk / Gate | Severity | Workstream | Notes |
|---|---|---|---|---|
| G1 | **Live SDK↔server surface mismatches are unproven** (task-name namespacing, `run_workflow` payload shape, gRPC `host_port` routing) | HIGH | W5/W6 | Not enumerable from static analysis; surfaces only on a real cluster. Dominant uncertainty — drives the hosted-iteration variable and LOW confidence. |
| G2 | **Hatchet candidate pair (SDK 1.38.1 ↔ server v0.105.2) unvalidated** | HIGH | W2/W6 | Release pin is a build gate (`HATCHET_LIVE_VALIDATION_HANDOFF.md:18-38`); candidates must not be promoted until a real pull/connectivity/execution test succeeds. |
| G3 | **Image path/topology repair depends on a live pull** | MED-HIGH | W2 | The 403 denial proved the top-level path is wrong; sub-path images confirmed reachable via live probes, but the topology rework + `compose.ci.yaml` override must be validated on a hosted run. |
| G4 | **Gate-posture drift** — `UMD_VALIDATE_LIVE_WORKER=false` default + `db api`-only startup currently make live validation opt-in and the release gate structurally bypassable | HIGH | W4 | Restoring the fail-closed default is the R4 release gate; must not be left opt-in. |
| G5 | **Async status reconciliation** — `JobService.submit` invokes the runner then immediately refreshes status (`jobs.py:90-116`); the design must reconcile queued/running/complete observation with callback-owned `DurableStageExecutor` completion — no synchronous substitution, no fabricated completion | MED | W2 | R4/R2 constraint; must not regress the "never fabricate complete" invariant. |
| G6 | **Adversarial log incomplete at estimation time** — only T1 (Ideator) is appended (`ADVERSARIAL-universal-media-decomposer-ci-repair.md`); T2 was dispatched but T2–T8 are not yet verified | MED | process | The scoped DD is still being distilled; final decisions (e.g. whether CI uses `hatchet-lite` vs full sub-path topology, Approach A/B/C/D blend) are not yet locked. This estimate sizes the superset of confirmed workstreams; the approved approach may shrink or shift some items. |
| G7 | **Multiple new tests needed** — sub-path image pin-agreement test, capability-probe behavior test | LOW | W3/W5 | Small, additive. |
| — | **Local results are context only** (R6): the prior `392 passed / 189 skipped` and green Ruff/mypy cannot close the diagnosis | — | W6 | No local green is release evidence. |

**Why Exec-Fixer is inappropriate:** the debugger's `fixComplexity: NEEDS_PLAN` and the multi-defect evidence are decisive. Exec-Fixer is scoped to *targeted repairs for MINOR severity review issues* and is explicitly not designed for cross-cutting release-gate restoration. This repair is not a list of line-level issues with given paths/line numbers to fix mechanically: it requires (a) a wiring decision with R4/R2 implications (which runner is injected, how status is reconciled without faking completion), (b) a deployment-topology decision (compose image path + multi-service/lite topology) that is not a syntax fix, (c) a gate-posture decision (default polarity, job split, pre-flight probes), and (d) a live-execution loop that is bounded only by hosted iterations, not by an issue list. Exec-Fixer has no mandate to make structural wiring/topology/gate decisions, and a fixer-only pass could make jobs green while leaving the required Hatchet production path absent or unproven — exactly the failure the debugger warns against. Routing is correctly R5: design → implementation plan → Exec-Manager.

---

## 6. Immutable requirements preserved (R1–R6, carried verbatim-in-spirit)

- **R1** — CI is managed by pushing to GitHub and retrieving CI reports once run there (mandatory).
- **R2** — CI failures must be diagnosed for REAL missing implementation/dependencies; do not make CI green with stubs, unconditional skips, fake readiness, or weakened assertions (mandatory).
- **R3** — Every repair must be cross-checked against Task.md's full Definition of Done (source/evidence/semantic separation, immutable provenance, representative text/image/audio/video decomposition, durable restartable DAG, selective invalidation/rerun, public HTTP-only correction E2E, honest capability reporting, final adversarial review) (mandatory).
- **R4** — Hatchet is the sole v1 scheduler; live worker callback registration and real stage execution are a release gate. No second scheduler; no in-process doubles as release evidence (mandatory).
- **R5** — Support findings → design → implementation plan → Exec-Manager (mandatory process). **Exec-Fixer is NOT the executor** (§5).
- **R6** — Local checks (Ruff, mypy, local pytest) are context only, not release evidence.

All estimated workstreams (W1–W6) preserve these. W1's compose-config test fix and W3's capability probe specifically avoid weakening R2/R4 (required secrets stay `${VAR:?}`; `active` is never claimed without verified connectivity).

---

## 7. Confirmation

- **plan_needed = true** (weighted ≈87K ≫ 32K).
- **dd_needed = true** (weighted ≥80K AND the runner-wiring/gate-posture decisions are architecturally consequential). The scoped DD skeleton (`artifacts/designs/pending/DD-universal-media-decomposer-ci-repair.md`) already exists and is the DDAuthor deliverable that satisfies this gate; this estimate does **not** author or amend it.
- **Tier = LARGE, confidence = LOW.** Known scope is firmly LARGE; the live-Hatchet execution fix count is the unenumerable unknown, reflected in LOW confidence + the hosted-iteration variable (§4) rather than an inflated tier.
- **Read-only.** No code written, no plan created, no production file edited, no DD amended.

---

*End of estimate. Read-only; no code, no plan, no DD amendment.*
