# Universal Media Decomposer CI Repair — Semantic Complexity Review (post-T8, post-G/H/I)

**Agent:** rnd-complexity-advisor
**Date:** 2026-08-28
**Scope:** Read-only semantic complexity review of the completed 8-turn adversarial log (`ADVERSARIAL-universal-media-decomposer-ci-repair.md`), the CI-repair DD (`DD-universal-media-decomposer-ci-repair.md`), CONTRACTS.md §58-63, plans G/H/I/J, the handoff, and the current tree at the state after Plans G/H/I completed. Validates product-vs-CI split, release-gate closure, no-skip posture, and exact live-topology evidence.
**Verdict preview:** The post-T8 design is **APPROPRIATE with residual EXCESS** — and the residual excess is no longer in the *design* (the adversarial process correctly dropped Lite, deferred the split job, shrank the probe to one reachability call, and banned skips). It is in **implementation-vs-design drift on five items**: two runtime-assembly paths, an opt-in gate still in the working tree, no capability probe, no E2E transport switch, and the dual-runner window. Each is cheap to close and every one of them blocks honest release evidence.

---

## 1. Inputs and verification method

| Input | Used for |
|---|---|
| `ADVERSARIAL-universal-media-decomposer-ci-repair.md` (T1–T8, complete) | Approach verdicts, SC-1..SC-7 obligations, F1..F10 final patterns, downstream obligations |
| `DD-universal-media-decomposer-ci-repair.md` | R1–R12 ledger, A+minimal-C architecture, phases 0–4, deliberate simplifications |
| `CONTRACTS.md` §58-63, HATCHET_LIVE_VALIDATION_HANDOFF.md | Contract surface, release gate |
| `Task.md` (full), parent `DD-universal-media-decomposer.md` | Requirement-mandated vs accidental |
| Plans G/H/I/J + `handoff-G-to-I-J.md` | What each plan mandates, overlap between plans |
| `universal-media-decomposer-ci-repair-librarian.md`, support-researcher L1–L5 | Prior decisions, stale-note identification |
| Current tree: `src/umd/api/app.py`, `src/umd/deploy/cli.py`, `src/umd/jobs/capability.py`, `tests/test_api_boundary_e2e.py`, `.github/workflows/validation.yml`, `tests/conftest.py` | Verifying what is designed vs what is implemented |

**Technology validation:** no new technology is introduced or recommended by this review. The SDK 1.38.1 ↔ server v0.105.2 pair remains CANDIDATE/PROVISIONAL per C4 and is not promoted here; all six topology proofs remain first-live-run observations (adversarial §6.3). No web re-checks were needed beyond the adversarial log's dated 2026-08-28 validations.

## 2. State of the tree vs the design (verified)

| Item | Design says | Tree has | Gap |
|---|---|---|---|
| Runtime assembly | "one shared runtime assembly function" (DD simplifications; adversarial F2) | `app.build_context` calls `build_runtime(...)` with 16 deps; `cli.worker` builds `runtime={"engine": engine}` (cli.py:96) | **DUPLICATE PATH** — worker runs degraded stage work |
| Runner selection | default `ProductionDAGRunner`; durable never `active` (A-2) | `app.py:167` still wires `DurableDAGRunner` | **WINDOW** — release path could remain the seam |
| Gate polarity | flip `UMD_VALIDATE_LIVE_WORKER` to unconditional (A-1) | `validation.yml:214` still `"${UMD_VALIDATE_LIVE_WORKER:-false}"`, conditional wait at :245/:266 | **OPEN BYPASS** in the working tree |
| Capability probe | one reachability-only gRPC call, cached, hysteresis (F4) | `CapabilityReporter` emits static text; no probe module exists | **NOT BUILT** — `/v1/capabilities` can never be `active` |
| E2E transport | live transport reaches the running API; never in-process in live mode (DD §147, F1-prior) | `_require_production_path` (e2e:108-138) self-skips; scenario builds in-process `create_app`; no `UMD_LIVE_API_URL`/httpx switch | **NOT BUILT** — E2E is vacuous in CI |
| Fail-on-skip | conftest hook raising on skip when `GITHUB_ACTIONS=true`, named allowlist (F6) | no hook in `tests/conftest.py` | **NOT BUILT** |
| Shape tests | real client + real executor (researcher L5) | committed `test_hatchet_live.py` uses `_real_client()` + `_poll_until` | **OK** — but Plan I QA R3 note (4) still calls them RecordingClient-defective (stale) |

The design is correct; the tree is behind it. All gaps are execution items owned by Plan J's pending phases, not design errors — but until they land *together*, the release gate cannot close and CI can still be green-by-skip.

## 3. Requirements-mandated complexity (validated — keep)

These are the repair's real content, each traceable to Task.md/CONTRACTS/R4. None is accidental.

1. **Hatchet sole v1 scheduler + `ProductionDAGRunner` wiring** — Task.md §23, CONTRACTS.md:61, R4. Not a second scheduler; `DurableDAGRunner` is the documented hermetic seam.
2. **Compose split topology** (migrate → admin → engine+dashboard, shared config volume, Postgres-only msgqueue, per-run token minting) — R4 same-stack gate (§8). Lite was correctly rejected (D-1/D-2); the cost is genuine production wiring, explicitly budgeted as a boot-fix cycle (F8).
3. **SDK v1 surface pre-alignment** (two-arg handler, `Workflow.run`/`runs.create`, mandatory surface-contract tests) — F1. Cheap, doc-backed, converts a first-run discovery into a hermetic failure.
4. **Retry ownership single authority** (executor-only, Hatchet `retries=0` + `NonRetryable`) — F2. Prevents attempt amplification; the executor already provides the idempotency Hatchet's own docs demand.
5. **CapabilityProbe** — one reachability-only gRPC call via injected client, cached with hysteresis, disclosure not gate (F4). Correctly sized: the E2E remains the execution authority.
6. **Fail-on-skip allowlist + always-run gate job** — F6/B-1. No green-without-run; named-allowlist keeps honest provider gates green (R6).
7. **Preflight manifest tripwire** — C-2 folded into A, ~10 lines, catches the 403 class fast, never release evidence.
8. **Restart segments with named volumes** (`stop`/`start`, never `down -v` mid-restart), pre/post namaste + stage_run assertions — DD Phase 4.
9. **The five mechanical env/package fixes** (python-multipart, ffmpeg, PGDG client-17 + `UMD_PG_BIN`, secrets export, `_resolve_pg_bin`) — real dependency defects, commit-only, no design.
10. **Pin agreement surfaces (4)** enforced by `test_hatchet_release_pin_is_single_validated_and_agreed` — the pair-agreement rewrite (SDK 1.x vs server 0.x lines) was the correct simplification of an unsatisfiable single-string assertion.
11. **Runner set** — `DurableDAGRunner` (seam/test driver), `ProductionDAGRunner` + `HatchetRunner` (both delegating to the shared `submit_workflow_runs` helper — no duplicated submission path), `SynchronousRunner` (test-only, statically guarded). Justified seam structure; the shared helper is the key that keeps it non-redundant.

## 4. Accidental complexity (findings)

### F1 (HIGH, product) — Two runtime-assembly paths; the worker would run degraded stage work

`app.build_context` (app.py:134-153) assembles a 16-dependency runtime; `cli.worker` (cli.py:96) builds `{"engine": engine}` only. `StageWorkRegistryFactory` degrades every real modality binding to deterministic refs with warnings when deps are absent — so a live worker would execute *degraded* stage work while the API path executes real work. This is the exact duplication my prior review named the "single highest-leverage simplification" and the DD's own simplifications list mandates — written but not executed. Plan I P2-S3's step text demands the full assembly ("OCFL store, provider registry, sandbox policy…") but the implementation note contradicts it.

**Simplification:** extract one shared assembly (e.g. `build_worker_runtime(settings, engine, source_store)`) called by both `app.build_context` and `cli.worker` with identical deps. One definition of "real stage work"; no second wiring path to drift.

### F2 (HIGH, CI) — The opt-in gate is still in the working tree

`validation.yml:214` retains `UMD_VALIDATE_LIVE_WORKER: "${...:-false}"` with the `db api`-only default and `if:`-gated readiness. This is precisely the "test gate that runs is not a gate that gates" anti-pattern the DD's own ledger forbids (A-1). The design mandates removal in the same commit as the wiring; it has not been removed.

**Simplification:** delete the flag, boot `--profile sandbox up -d --build` unconditionally, make readiness unconditional — exactly as at HEAD (fail-closed).

### F3 (HIGH, CI) — No capability probe ⇒ the boundary E2E remains vacuous

`CapabilityReporter` (capability.py:87-99) reports static strings; no probe exists anywhere. `_require_production_path` (e2e:108-138) therefore skips against any stack, live or not. The gate flip (F2) landing *without* the probe would produce a green-by-skip run unless fail-on-skip (F6 design) lands in the same commit. The design's ordering (F3: worker line → probe warm → E2E) is correct; the pieces must simply be built together.

**Simplification:** implement F4 as specified — one reachability call via injected client, cached boolean, no TTL cache in the request path, no poll loop. ~60-100 lines, not a subsystem.

### F4 (HIGH, CI) — No E2E transport switch

The DD (§147, Phase 3) mandates the live E2E reach the running API and never construct `create_app` in live mode. The file builds in-process `TestClient` (and the restart test builds a *second* `create_app`). No `UMD_LIVE_API_URL`/httpx switch exists.

**Simplification:** one file, two transports — `TestClient` when no live URL is set, `httpx.Client(base_url=os.environ["UMD_LIVE_API_URL"])` when it is. No second E2E file, no internal-service imports (guardrails already enforce).

### F5 (MEDIUM, product) — Dual-runner window

`app.py:167` still wires `DurableDAGRunner`. The A-2 design (default `ProductionDAGRunner`, durable can never report `active`) is right; the tree is behind. The risk is time-bounded only if the rewire lands with the gate flip — which the design orders, but which is an execution promise, not a property.

**Simplification:** rewire as the design says (env-derived: live env → `ProductionDAGRunner`; absent → hermetic seam, never `active`). No new env axis (`UMD_EXECUTION_BACKEND` is correctly not in the final design).

### F6 (LOW-MEDIUM, process) — Stale artifact notes cause rework

Plan I QA R3 deviation (4) and handoff §6 still describe the three `test_live_hatchet_*` tests as RecordingClient/executor=None defects, while the committed file (and researcher L5) show real client + real executor. The "repair the shape tests" work item is chasing an already-repaired target. Also `worker started:`/`worker ready:` terminology drifted across artifacts before settling on `worker_ready_line` — resolved, but three documents carry the old text.

**Simplification:** a one-line correction pass on Plan I + handoff §6; not a code change.

## 5. Focus-area validation

### Product-vs-CI split (R10/C8)
**CLEAN at the design level.** The adversarial downstream obligations separate product (1–6: runner rewire, SDK surface, probe, retry ownership, packaging, no-fabricated-completion) from CI remediation (7–9: same-commit env fixes, compose topology, in-stack runner). The DD phases map 0–1 → CI-remediation, 2–3 → product + evidence, 4 → release. SC-4's "one commit" is reconciled with the two-stream requirement correctly: separation at the plan level, atomic landing at the commit level. **Residual risk is execution hygiene:** the working tree mixes unrelated changes (ASR pins, audio pipeline, docs, logs); the commit must use explicit `git add <paths>` and a pre-commit diff review.

### Release gate closure
**NOT closed — and correctly so.** No hosted run is green (R1); the candidate pair is not promoted. The gate *topology* is minimal and fail-closed: no second scheduler, no `allow-failure`/`continue-on-error` on the live path on main, no split-job bypass (B deferred), no Lite substitution. Closure requires the five F1–F5 execution items plus a green hosted run with the six topology proofs. Nothing about the gate design needs simplification; everything about the gate *implementation* is pending Plan J.

### No skips
**Design is sound; mechanism absent.** The F6 allowlist hook (ban the production-path skip, permit named provider gates) is the right shape and directly answers R6's honest-status vocabulary. The fail-on-skip mechanism is not in the tree. The boundary E2E still self-skips via `_require_production_path` — the single most important "skip" to close, and it closes only when the probe (F3) and the transport switch (F4) land with the gate flip (F2). The design's gate order (F3 adversarial) already prevents the warm-up race; the execution must honor it.

### Exact live topology compatibility evidence
**Satisfied as named observations, no machinery.** Adversarial §6.3 lists six exact proofs: SDK↔server live pair, submission surface, worker/task namespacing, gRPC `host_port` routing, v0.105.2 env contract, token minting path. Each is a first-live-run observation with a budgeted boot-fix cycle (F8) and a fail-closed gate throughout. The one static gap (v0.105.2 env contract is read from current-line docs, not the tag's own) is explicitly PROVISIONAL and converted to a plan-time read obligation (F8). This is the correct treatment: observations, not new subsystems.

## 6. Verdict

```yaml
status: DONE
target: "UMD CI-repair: adversarial T1-T8 + DD + plans G/H/I/J + current tree"
structure:
  schedulers: 1 (Hatchet; Durable = hermetic seam, never release evidence)
  runtime_assembly_paths: 2 (app.build_context full, cli.worker {"engine": engine}) — must be 1
  runner_classes: 4 (Durable seam, Production, Hatchet→shared submit_workflow_runs, Synchronous test-only)
  workflow_jobs: 3 + gate job (split-job B deferred, correctly)
  hatchet_topology: 1 (full split; Lite rejected)
  probes: 1 designed (reachability-only), 0 built
  e2e_transports: 1 designed (hermetic|live), 0 built
verdict:
  complexity_level: APPROPRIATE-with-residual-EXCESS
  justified: true (design) / false (five execution gaps: F1-F5)
  summary: >
    The 8-turn adversarial process converged on the minimal correct design:
    one scheduler, one split topology, one reachability probe, one E2E
    transport, no split job, no Lite, no skips, no second runtime.
    The excess that remains is drift between that design and the tree:
    the worker still assembles a degraded runtime, the gate is still
    opt-in, the probe and transport switch are unbuilt, and app.py still
    wires the durable seam. Every one of these is a Plan J execution
    item that blocks honest release evidence — none requires new
    machinery or a design change.
```

## 7. Simplification recommendations (ordered)

1. **Collapse `cli.worker` onto the shared runtime assembly** (F1). Highest value: one definition of "real stage work", removes silent-degradation in the release path.
2. **Land gate flip + probe + fail-on-skip + E2E transport switch in ONE commit** (F2/F3/F4), with `git add <paths>` to keep the product/CI streams reviewable (SC-4). Do not land the gate flip without the fail-on-skip hook — that recreates green-by-skip.
3. **Build the `CapabilityProbe` as specified** (F4): one reachability call via injected client, cached boolean, hysteresis; no TTL cache, no poll loop, never blocks the request path.
4. **Add the E2E transport switch** — `UMD_LIVE_API_URL` env selects httpx against the running stack; keep `TestClient` for hermetic runs; the restart test must use `stop`/`start` on real containers in live mode, not a second `create_app`.
5. **Rewire `build_context` to `ProductionDAGRunner`** per A-2 (env-derived, durable never `active`); delete the interim note when done.
6. **Correct stale artifact notes** (F6): Plan I QA R3 deviation (4) and handoff §6 shape-test status.
7. **Keep everything else.** The justified core — split topology + token minting, SDK surface pre-alignment, retry single authority, allowlist fail-on-skip, preflight tripwire, restart segments, pin surfaces — is already minimal and must not be "simplified" further. In particular: do not reintroduce Lite, do not add the split job before green, do not weaken the probe to an env-string.

---

*Evidence citations: file:line references verified against the current tree on 2026-08-28. Adversarial log T1–T8, CI-repair DD, CONTRACTS.md, handoff, librarian brief, and support-researcher L1–L5 cited by artifact + section.*
