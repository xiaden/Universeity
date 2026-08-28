# Universal Media Decomposer — CI Repair / Release-Gate Restoration — FINAL Sizing (post-G/H/I, post-T8)

**Status:** DONE — read-only final sizing; supersedes and refines `universal-media-decomposer-ci-repair-estimate.md`. Evidence-backed from the completed 8-turn adversarial artifact (T1–T8), the architect-stage report, the post-T8 complexity review, the Support-Librarian/Researcher reports, `Task.md`, the parent DD, the CI-repair DD skeleton, CONTRACTS.md, and plans G/H/I/J plus first-hand reads of the actual affected files. No code written, no plan created, no DD authored/amended, no production file edited.
**Date:** 2026-08-28
**Agent:** `rnd-estimator`

## Scope caveat (important)

This estimate sizes the **remaining** work on an existing codebase after Plans **G** (production runner/API), **H** (local providers/modality composition), and **I** (Hatchet worker) have all reached `QA R3 PASS / COMPLETE`, and after Plan J Phases 1–2 (spec-first boundary E2E + hosted workflow, static) are done. It is **not** a re-derivation of the greenfield EPIC estimate (`universal-media-decomposer-final-estimate.md`, ≈59.3M weighted chars) and not a re-count of the already-delivered G/H/I implementation. It deliberately **distinguishes** product implementation from CI environment remediation from hosted Hatchet compatibility/proof from docs-after-behavior from final adversarial/revalidation, because those five streams have different owners, different release gates, and wildly different uncertainty profiles.

The immutable ledger (R1–R12) and **DD_REQUIRED** are preserved and carried forward verbatim-in-spirit; DD_REQUIRED **cannot be downgraded** (§7).

---

## Executive result

| | |
|---|---|
| **Size tier** | **LARGE** |
| **Confidence** | **LOW** (known remaining scope is firmly LARGE; the live-Hatchet execution fix count and the final-adversarial finding count are unenumerable from static analysis and are bounded only by hosted iteration under R1) |
| **plan_needed** | **true** (weighted_chars ≈ 157K ≫ 32K) |
| **dd_needed** | **true** (weighted_chars ≈ 157K ≥ 80K, AND the runner-wiring/gate-posture decisions are architecturally consequential) — **DD_REQUIRED immutable; the scoped DD skeleton `DD-universal-media-decomposer-ci-repair.md` already exists and satisfies the gate**; this estimate does not author or amend it |
| **fixComplexity** | **NEEDS_PLAN** (crosses workflow provisioning, deployment topology, app wiring, live-gate, live tests, docs, and final adversarial review — not `SIMPLE`/Exec-Fixer eligible) |

The remaining work is **cross-cutting and multi-layer**, and it now has a much tighter known shape than the interim estimate (whose adversarial log was incomplete at T1). The design is **locked**: Architecture **A** (commit-and-wire) + minimal **C** (prove-then-run preflight), full split Hatchet topology, Lite rejected, B deferred until after green. Plans G/H/I delivered the product foundation (real stage registry, real modality composition, real worker/callback/SDK binding). What remains is the **execution-to-green-and-release** stream: five confirmed execution gaps in the tree (F1–F5, verified below against actual files), the CI/deployment remediation, the **dominant unenumerable live-Hatchet proof loop**, docs-after-behavior, and final adversarial/revalidation.

The dominant cost driver is **not** the enumerated edits (bounded ≈58K chars) but the **hosted live-Hatchet execution loop**: v0.105.2 env-contract forms, SDK 1.38.1 ↔ server v0.105.2 live pair, task-name namespacing, `run_workflow`/`runs.create` payload shape, gRPC `host_port` routing, four sub-path image cold-boot, and cold-start timing are all **first-boot arbiters** that can only be discovered against a real running cluster; each discovery is gated on a full pushed hosted CI iteration under R1. That unknown — plus the final-adversarial finding-repair loop — is why confidence is LOW despite a firmly bounded known scope.

---

## 1. Formula inputs (measured from the real tree, not greenfield)

Inputs are the affected files named by the debugger/architect/complexity reports and **confirmed by direct reads** during this pass. Edit-scope chars = the sections being edited plus adjacent context needed to understand them (conservative, rounded up). Tests are included.

| Input | Value | Basis |
|---|---|---|
| **Files — modify** | 23 | Streams R/C/H/D/V file lists (§3) |
| **Files — create** | 2 | `CapabilityProbe` module (or injected probe into capability.py) + conftest fail-on-skip allowlist hook; `compose.ci.yaml` override NOT counted (design repairs the existing docker-e2e job, no split) |
| **Files — delete** | 0 | None confirmed |
| **Files — total** | 25 | |
| **Sections** (distinct edit locations) | 46 | Product (15) + CI (10) + hosted (6) + docs (10) + adversarial repairs (5) — §3 |
| **char_count** (edit-scope chars) | 58,000 | Sum of edited sections + required adjacent context; conservative round-up |
| **cognitive_weight** | 2.71 | 1 + 0.03×(46−1) + 0.015×(25−1) = 1 + 1.35 + 0.36 |
| **weighted_chars** | **157,200** | 58,000 × 2.71 |

**Threshold crossings:**

| Threshold | Value | Criteria |
|---|---|---|
| TRIVIAL | < 8K | — |
| SMALL | 8K–32K | — |
| MEDIUM | 32K–80K | — |
| **LARGE** | **80K–320K** | **≈157K → LARGE (mid-band)** |
| EPIC | ≥320K | Not reached |

The tier is **not fragile to the unenumerable legs**: even doubling the known char_count to 116K (to absorb adversarial-finding repair variance) yields ≈314K weighted — still LARGE, just under the EPIC floor. The **EPIC tier is not warranted** because this is repair/completion of existing code, not greenfield creation: the dominant EPIC drivers of the original estimate (310 new files, 950 sections, ≈1.74M chars) are already built, and G/H/I have already delivered the heaviest product layers (real stage registry, modality composition, worker/SDK binding).

---

## 2. Verified current tree state (evidence for the gaps)

Direct reads this pass confirmed the post-T8 complexity review's five execution gaps (F1–F5) remain open in the working tree:

| Gap | Design (DD/adversarial) | Tree has (verified) | Status |
|---|---|---|---|
| **F5** — runner selection | default `ProductionDAGRunner`; `DurableDAGRunner` never reports `active` | `app.py:167` still `runner = DurableDAGRunner(executor=executor, store=job_store)` | **OPEN** |
| **F1** — one shared runtime assembly | single assembly consumed by API and worker | `cli.py:96` builds degraded `runtime={"engine": engine}`; `app.build_context` (app.py:134–153) builds the full 16-dep runtime | **DUPLICATE PATH** — worker would execute degraded stage work in release |
| **F3** — capability probe | one reachability-only gRPC call via injected client, cached, hysteresis | `capability.py:46–99` returns `configured-but-unavailable` even when SDK+env are present; no probe exists; `active` unreachable | **NOT BUILT** |
| **F2** — gate polarity | unconditional full-stack boot; remove the opt-in flag | `validation.yml:214` `UMD_VALIDATE_LIVE_WORKER: "${UMD_VALIDATE_LIVE_WORKER:-false}"`, `db api`-only default boot (:248), `if:`-gated readiness (:266) | **OPEN BYPASS** in working tree |
| **F4** — E2E transport switch | live mode reaches the running API (httpx), never in-process | `test_api_boundary_e2e.py:108–138` `_require_production_path` self-skips; scenario builds in-process `TestClient`/`create_app`; no `UMD_LIVE_API_URL` | **NOT BUILT** |

Additionally verified: **G5** (queued-state reconciliation) — `JobService.submit` (jobs.py:90–116) invokes the runner then immediately refreshes status; `ProductionDAGRunner` submits queued events but does not yet create persisted queued `stage_run` rows, so `RUNNING→PENDING` regression is possible before the first callback. The shape tests (`tests/test_hatchet_live.py`) already use a real client + real executor (the handoff §6 `_RecordingClient`/`executor=None` defect was repaired in Plan I) — what remains unproven is **live execution itself**.

---

## 3. Workstream breakdown — five streams distinguished

### R — Product implementation (remaining wiring; G/H/I already delivered the foundation)

| Item | File(s) | Sections | ~Chars | Notes |
|---|---|---|---|---|
| Rewire `app.py` to `ProductionDAGRunner` over the sole Hatchet client; `DurableDAGRunner` remains hermetic/dev-only, never `active` | `app.py` | 3 | 4K | env-derived selection (A-2); no new `UMD_EXECUTION_BACKEND` axis |
| Collapse `cli.worker` onto the shared runtime assembly (full OCFL/ledger/provider/sandbox/replay/registry), replacing `runtime={"engine": engine}` | `cli.py`, `production.py` | 4 | 4K | F1 — highest-leverage simplification; one definition of "real stage work" |
| Queued-state reconciliation (persisted queued `stage_run` rows or durable job-state contract) | `jobs.py`, `runner.py` | 2 | 3K | G5 — prevents `RUNNING→PENDING` before first callback; no fabricated completion |
| Capability probe: reachability-only gRPC call via injected client, cached, hysteresis | `capability.py` (+ new probe) | 2 | 2K | F3/F4 — only thing that honestly flips `active` |
| Tests for the above | `test_capability_transitions.py`, `test_production_*.py` | 4 | 6K | capability probe behavior; worker-runtime parity; queued-state; no-weakening |
| **Subtotal R** | **5 files** | **15** | **19K** | |

### C — CI environment remediation (mostly mechanical, in-tree, needs commit + proof)

| Item | File(s) | Sections | ~Chars | Notes |
|---|---|---|---|---|
| Commit W1 env fixes: ffmpeg/ffprobe + PGDG `postgresql-client-17` + `UMD_PG_BIN`; `python-multipart==0.0.32`; secrets export in unit/postgres jobs; `_resolve_pg_bin` | `validation.yml`, `pyproject.toml`, `conftest.py`, `test_deployment_phaseE.py` | 5 | 6K | Already in working tree (+59 lines etc.); mechanical but must be committed + proven (R1). Fixes 14 PG + 1 unit + Compose failures |
| Split Hatchet topology (migrate → admin → engine+dashboard) + correct sub-path image; drop the 403-ing top-level `ghcr.io/hatchet-dev/hatchet:v0.105.2` | `compose.yaml` | 3 | 4K | Full split, not Lite (same-stack gate); per-run JWT; Postgres-only msgqueue |
| `pip install .[worker]` in the shared image (+ SDK-pin comment); verify negative missing-SDK exit-2 retained | `Dockerfile` | 1 | 0.5K | IP-7; worker image must contain the SDK |
| `HATCHET_SERVER_IMAGE` constant → corrected sub-path pin; update the pair-agreement pin test | `hatchet.py`, `test_hatchet_live.py` | 2 | 2K | P1-S3 pair agreement |
| **Subtotal C** | **5 files** | **11** | **12.5K** | |

### H — Hosted Hatchet compatibility / proof (the dominant unknown; fixed edits + unenumerable loop)

| Item | File(s) | Sections | ~Chars | Notes |
|---|---|---|---|---|
| Gate flip: full-stack unconditional boot (`--profile sandbox`), readiness unconditional, remove opt-in flag, add always-run gate job | `validation.yml` | 3 | 4K | F2/A-1 — fail-closed; gate job `if: always()` + `needs: [docker-e2e]` |
| Fail-on-skip allowlist hook (raise on `pytest.skip` under `GITHUB_ACTIONS=true`, production-path skip NOT allowed) | `conftest.py` (new hook) | 1 | 1K | F6/SC-5 |
| E2E transport switch: `UMD_LIVE_API_URL` → httpx against running stack; `TestClient` only for hermetic; restart via real `stop`/`start` | `test_api_boundary_e2e.py` | 2 | 2K | F4 |
| Preflight manifest tripwire (`docker manifest inspect` on the sub-paths) | `validation.yml` | 1 | 0.5K | C-2, ~10 lines |
| **Fixed-edit subtotal H** | **3 files** | **7** | **7.5K** | |
| **Live iteration loop** | **— (variable)** | — | — | **Unenumerable** — see §4. The genuine cost driver |

### D — Docs-after-behavior (Plan J Phase 3; hard-gates on a green hosted run)

| Item | File(s) | Sections | ~Chars | Notes |
|---|---|---|---|---|
| Update README, docs/testing, docs/deployment, docs/providers, docs/limitations, docs/runbooks, client examples with measured defaults, exact statuses, scheduler pin, CI behavior, measured counts | ~8 files | 10 | 12K | Only after behavior+workflow pass (R7) |
| **Subtotal D** | **8 files** | **10** | **12K** | |

### V — Final adversarial / revalidation (Plan J Phase 4)

| Item | File(s) | Sections | ~Chars | Notes |
|---|---|---|---|---|
| Fresh QA/adversarial review (12 risk areas), repair findings through plan/Exec, complete rerun, release commit + final DoD matrix with no unresolved mandatory FAIL | ~3 files | 5 | 6K | Finding-repair count is variable/unenumerable; rerun loop bounded only by R1 |
| **Subtotal V** | **3 files** | **5** | **6K** | |

**Totals** — Files 25 · Sections 46 · Chars ≈58K → weighted ≈157K → **LARGE**.

---

## 4. Dependencies, critical path, and the risk-reserve variables

**Dependency graph (bounded):**
1. **C (W1 env fixes)** must land first and be proven by a hosted run — independent of the wiring decision; unblocks the multipart/FFmpeg/pg_dump/Compose-interpolation failures.
2. **H/C (deployment topology + Dockerfile worker extra)** precede **R (runner wiring)** — the worker must exist and contain the SDK before `ProductionDAGRunner`/`HatchetWorkerFactory` can register against it.
3. **R probe (F3)** is a precondition for the boundary E2E to unskip; the **F2 gate flip + F3 probe + F6 fail-on-skip + F4 transport switch must land in ONE commit** (SC-4) — landing the gate flip without fail-on-skip recreates green-by-skip.
4. **D (docs-after-behavior)** hard-gates on a green hosted run (R7/Plan J P3).
5. **V (final adversarial)** gates on everything; its findings route back through plan/Exec and require a full rerun.

**Network critical path:** C(W1 proof) → C/H(deploy topology + image) → R(product wiring + probe) → H(live proof) → D(docs) → V(final adversarial + rerun). The **live-proof leg (H)** is the network's dominant and **unenumerable** leg.

**Risk-reserve variables (carried explicitly, not hidden in a number):**

- **Hosted-iteration variable (dominant):** minimum **1** hosted run after committing W1 fixes (should turn the 14 PG + 1 unit + Compose failures green). Then the live path: **2–5 additional** hosted iterations to discover and fix v0.105.2 env-contract forms, the SDK↔server live pair, task-name namespacing, `run_workflow`/`runs.create` payload shape, gRPC `host_port` routing, four sub-path cold-boot, and cold-start timing. **Estimate ≈3–7 total hosted iterations**, each a full run, bounded only by the requirement that every fix be proven on a hosted run (R1/R6). This is the dominant schedule driver and the primary reason confidence is LOW.
- **Adversarial-finding-repair variable:** final QA/adversarial may surface 1–N findings (provenance, invalidation overreach, scheduler races, capability honesty, etc.); each is a bounded follow-up plan/Exec cycle + full rerun. Not enumerable from static analysis.

**Unbounded/risked, NOT a fixed char count:** the live-iteration fixes and the adversarial-finding repairs. The bounded ≈58K-char scope above sizes the known edits; these two loops are the risk reserve.

---

## 5. Effort/schedule (transparent planning aid only — NOT a commitment)

These are rough heuristics, not a commitment. The correctness/evidence weight (hosted-only proof, fail-closed gate, adversarial review) and the unbounded hosted iteration justify a wide range.

- **Known-edit implementation:** ≈2–3 engineer-weeks (≈1 engineer) for streams R+C+D fixed edits + the H fixed edits, spread over the dependency path.
- **Hosted-iteration loop:** ≈1–3 engineer-weeks additional, dominated by the 3–7 hosted runs and their live-discovery fix cycles (not parallelizable — each fix is gated on a full pushed hosted run under R1).
- **Adversarial/revalidation:** ≈1 engineer-week + the rerun loop.
- **Illustrative calendar:** ≈4–7 engineer-weeks single-track from current state to a green hosted release with docs and final adversarial PASS. The unbounded legs (hosted iterations, adversarial findings) are the variance; the bounded legs are not the constraint.

---

## 6. Risks and gates

| # | Risk / Gate | Severity | Stream | Notes |
|---|---|---|---|---|
| G1 | **Live SDK↔server surface mismatches unproven** (v0.105.2 env contract, task namespacing, `run_workflow`/`runs.create`, gRPC `host_port`, cold-boot) | HIGH | H | Not enumerable from static analysis; surfaces only on a real cluster. Dominant uncertainty; drives the hosted-iteration variable and LOW confidence. |
| G2 | **Hatchet candidate pair (SDK 1.38.1 ↔ server v0.105.2) unvalidated** | HIGH | H | Release pin is a build gate; must not be promoted until a real pull/register/execute test succeeds (lockstep bump + new DAG universe + drain on failure). |
| G3 | **Image path/topology repair depends on a live pull** | MED-HIGH | C/H | 403 proved the top-level path wrong; sub-paths confirmed reachable, but the split-topology rework + env/token forms must be validated on a hosted run. |
| G4 | **Gate-posture drift** — `UMD_VALIDATE_LIVE_WORKER=false` + `db api`-only default still in tree | HIGH | H | Restoring the fail-closed default is the R4 release gate; must not stay opt-in, and must land with fail-on-skip (SC-4). |
| G5 | **Dual-runner / degraded-worker window** — `cli.py` builds `{"engine": engine}`; `app.py` still wires `DurableDAGRunner` | HIGH | R | F1/F5; rewire both and collapse to one shared runtime; durable never `active`. |
| G6 | **Queued-state reconciliation** — `RUNNING` can regress to `PENDING` before first callback | MED | R | Add persisted queued state / durable job-state contract; no fabricated completion. |
| G7 | **Docs-after-behavior ordering** — docs must not precede a green hosted run | MED | D | R7/Plan J P3 hard-gate; stale counts are release-blocking. |
| G8 | **Final-adversarial finding loop** — 1–N findings, each a plan/Exec cycle + full rerun | MED | V | Bounded but variable; must complete with no unresolved mandatory FAIL. |
| G9 | **Stream-mixing commit hygiene** — unrelated ASR/audio/docs/log churn in the tree | LOW-MED | all | Explicit `git add <paths>` + pre-commit diff review (SC-4/C8); no `git add -A`. |

**Why Exec-Fixer is inappropriate:** this is not a list of line-level issues. It requires (a) a runner-wiring decision with R4/R2 implications, (b) a deployment-topology decision (compose image path + split services + token minting), (c) a gate-polarity decision (default flip, always-run gate job, fail-on-skip allowlist) that must land atomically with the probe + transport switch, (d) a live-execution loop bounded only by hosted iterations, (e) docs-after-behavior, and (f) final adversarial review. Exec-Fixer has no mandate for structural wiring/topology/gate/docs/review decisions. Routing is correctly R5: design → implementation plan → Exec-Manager.

---

## 7. Immutable requirements and DD_REQUIRED (preserved verbatim-in-spirit)

**DD_REQUIRED = TRUE and is declared immutable — cannot be downgraded.** This follows from all three DD-trigger axes simultaneously:
1. **Weighted chars ≈157K ≫ 80K** (LARGE threshold) — decisively exceeded.
2. **Architecturally consequential** — the `ProductionDAGRunner` wiring, queued-state contract, capability-probe posture, and fail-closed gate are structural choices with R4/R2 implications.
3. **Incomplete/ambiguous at implementation time** — the six first-boot arbiters (v0.105.2 env contract, live pair, namespacing, routing, cold-boot, cold-start timing) cannot be resolved statically.

The scoped DD skeleton **`artifacts/designs/pending/DD-universal-media-decomposer-ci-repair.md`** already exists and is the DDAuthor deliverable that satisfies this gate. This estimate does **not** create, author, or amend it.

Immutable ledger preserved (R1–R12, carried verbatim-in-spirit from the DD):
- **R1** CI managed by pushing to GitHub and retrieving reports; **R2** diagnose real missing implementation/deps, no stubs/skips/fake-readiness/weakened assertions; **R3** cross-check against Task.md full DoD; **R4** Hatchet sole v1 scheduler, live worker = release gate; **R5** Support → design → plan → Exec-Manager (Exec-Fixer not the executor); **R6** local checks context only, not release evidence; **R7** docs after behavior, final PASS/FAIL/GATED with no unresolved FAIL; **R8** complete workflow; **R9** cross-check; **R10** DD/plans separate product vs CI and exact live proof; **R11** R&D no production edits; **R12** return paths/risks/gates. No local result, fixture, stub, or green test closes the gate.

---

## 8. Confirmation

- **plan_needed = true** (weighted ≈157K ≫ 32K).
- **dd_needed = true / DD_REQUIRED = immutable** (weighted ≥80K AND structural). The scoped DD skeleton satisfies the gate; not amended here.
- **Tier = LARGE, confidence = LOW.** Known remaining scope is firmly LARGE (mid-band, robust to ± on the unenumerable legs); the live-Hatchet execution fix count and the final-adversarial finding count are the unenumerable unknowns, reflected in LOW confidence + the explicit hosted-iteration risk reserve (§4) rather than an inflated tier.
- **Streams distinguished:** R (product, ≈19K) / C (CI remediation, ≈12.5K) / H (hosted proof, ≈7.5K fixed + unbounded loop) / D (docs-after-behavior, ≈12K) / V (final adversarial/revalidation, ≈6K + unbounded loop).
- **Read-only.** No code written, no plan created, no production file edited, no DD amended.

---

*End of final estimate. Read-only; no code, no plan, no DD amendment.*
