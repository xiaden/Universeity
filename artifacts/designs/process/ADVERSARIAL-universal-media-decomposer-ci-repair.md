# Adversarial Design Log: UMD Evidence-Backed GitHub CI Repair and Release-Gate Restoration

*This file records the full adversarial refinement process for repairing the
Universal Media Decomposer's GitHub CI (run 33164294061 on commit a6b1a62) and
restoring the mandatory live Hatchet worker / real-stage release gate. The
design document (DD-universal-media-decomposer-ci-repair.md) contains distilled
decisions, not this raw debate.*

*Process: 8 sequential turns — T1 Ideator (approaches) → T2 Counter-Ideator
(critique) → T3 Ideator (refine) → T4 Counter-Ideator (surviving concerns) →
T5 Improver (implementation patterns) → T6 Counter-Improver (pattern risks) →
T7 Improver (final patterns) → T8 Counter-Improver (open risks & human
questions). Every technology/version choice MUST be validated against current
official/maintainer sources with source + check date recorded, or explicitly
labeled PROVISIONAL. Newest is not automatically best; unvalidated claims must
be labeled provisional.*

*Regeneration note (rnd-refiner, 2026-08-28): a prior partial run of this log
contained a T1 section claiming the debugger report
`universal-media-decomposer-ci-repair-debugger.md` was MISSING from disk. That
claim is stale — the debugger report exists and is the authoritative diagnosis.
This log was therefore regenerated from the immutable requirement ledger below
so every turn (T1–T8) is present, current, and trustworthy. The prior partial
content is superseded.*

---

## Immutable Requirement Ledger (binding for every turn)

Original user request (verbatim, preserved):

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

Immutable ledger:

- **R1** — Complete Task.md Universal Media Decomposer Definition of Done.
- **R2** — Do not trust contracts/docs/fixtures/stubs/green tests.
- **R3** — Repair real production decomposition, durable async
  scheduling/restart/retry/cancel/selective rerun/invalidation, real
  modality/semantic work, public API heterogeneous correction E2E, and GitHub
  Actions Docker/Compose/container validation.
- **R4** — No stubs, weakened gates, silent skips, or test doubles as release
  evidence.
- **R5** — Preserve immutable OCFL source, provenance, evidence/semantic
  separation, append-only authority, stable locators, multilingual/adaptation
  individuality, selective descendant invalidation.
- **R6** — Capability statuses distinguish
  active/reference-only/configured-unavailable/gated/disabled.
- **R7** — Docs only after behavior exists; final DoD classify PASS/FAIL/GATED
  with no unresolved FAIL.
- **R8** — Full formal workflow exact stages, no skips.
- **R9** — Cross-check each repair against Task.md and DD/contracts/plans.
- **R10** — Produce/update formal DD and validated implementation plans,
  explicitly separate product implementation from CI environment remediation,
  and identify exact live Hatchet topology/compatibility evidence needed.
- **R11** — Do not edit production code beyond design artifacts.
- **R12** — Return paths, risks, and gates for Exec-Manager.

Additional binding constraints from the design layer (CONTRACTS.md,
DD-universal-media-decomposer-ci-repair.md, HATCHET_LIVE_VALIDATION_HANDOFF.md):

- **C1** — Hatchet is the SOLE v1 scheduler; live worker callback registration
  and real stage execution are a release gate. No second scheduler; no
  in-process doubles as release evidence.
- **C2** — CI is managed by pushing to GitHub and retrieving CI reports once run
  there; local validation is context only, never release evidence.
- **C3** — `CapabilityReporter.report()` never reports `active` without verified
  live connectivity; statuses are active/reference-only/
  configured-unavailable/gated/disabled.
- **C4** — Candidate pin SDK `1.38.1` ↔ server `v0.105.2` is CANDIDATE/PENDING
  live validation; must not be promoted until a real pull/connect/execute test
  succeeds. Upgrade = bump both surfaces in lockstep + new DAG universe + drain.
- **C5** — The three `test_live_hatchet_*` shape tests must be repaired (real
  executor + real SDK client), never made green by weakening assertions or
  adding skips. Primary live release evidence =
  `test_boundary_restart_duplicate_retry_and_consistency` (public HTTP-only E2E).
- **C6** — Worker readiness = real SDK worker loop start with callbacks bound;
  `worker ready: registered N Hatchet workflows (candidate, pending Plan J live
  validation)` line emitted BEFORE the blocking `start()`; never remove the
  "(candidate...)" suffix while unproven.
- **C7** — `HATCHET_COOKIE_SECRET`/`HATCHET_MASTER_KEY` stay required
  (`${VAR:?}`); never weaken the interpolation or the Compose-config test.
- **C8** — Separate the product-repair stream from the CI-environment-remediation
  stream in the final design/plans.

## Support Findings (run 33164294061, commit a6b1a62, workflow `validation`)

Verified by support-debugger (`universal-media-decomposer-ci-repair-debugger.md`,
status DIAGNOSED/NEEDS_PLAN) and support-librarian briefing
(`universal-media-decomposer-ci-repair-librarian.md`):

- **Run result:** Ruff lint PASS; strict mypy PASS (173 files); Unit FAIL 1;
  PostgreSQL FAIL 14 (14 failed / 550 passed / 17 skipped); Docker E2E FAIL
  before startup (step 6, 36s, `ghcr.io/v2/hatchet-dev/hatchet/manifests/
  v0.105.2: denied`).
- **Environment/package defects (uncommitted working-tree fixes exist):**
  1. Missing committed `python-multipart` → 7 multipart failures (starlette
     `AssertionError: The python-multipart library must be installed...`);
     pin 0.0.32 is real (PyPI 2026-06-04) — CI failure was the missing package,
     NOT an import-name mismatch.
  2. Hosted runner lacks ffmpeg → 5 media failures (`FileNotFoundError: 'ffmpeg'`).
  3. Missing PG-17 client (`/usr/lib/postgresql/17/bin/pg_dump`); ubuntu-latest
     ships PG-16 client which aborts against PG-17 server → 1 backup failure.
     Fix = PGDG `noble-pgdg` + `postgresql-client-17` + `_resolve_pg_bin()`/`UMD_PG_BIN`.
  4. Compose interpolation failure (`required variable HATCHET_COOKIE_SECRET is
     missing a value`) in unit+postgres jobs → secrets must be exported there;
     NEVER remove `${VAR:?}`.
- **Genuine deployment defect:** `deploy/compose.yaml:104` pins
  `ghcr.io/hatchet-dev/hatchet:${HATCHET_VERSION:-v0.105.2}` — top-level path is
  403 DENIED/nonexistent. Real public sub-paths at v0.105.2 (all 200 OK verified):
  `ghcr.io/hatchet-dev/hatchet/hatchet-engine`, `hatchet-admin`, `hatchet-migrate`,
  `hatchet-lite`, `hatchet-lite-dev`. `src/umd/jobs/hatchet.py:56`
  (`HATCHET_SERVER_IMAGE`) still has the WRONG top-level path and is surfaced by
  /v1/capabilities — must change together with compose.yaml.
- **Product wiring defects:**
  1. `src/umd/api/app.py:52-54,167-168` wires `DurableDAGRunner` (in-process
     synchronous) instead of `ProductionDAGRunner` (sole-Hatchet dispatch) —
     CONTRACTS.md:61 violated; boundary E2E can never run.
  2. `CapabilityReporter` (`src/umd/jobs/capability.py:46-84`) has NO connectivity
     probe — always `configured-but-unavailable` when env present; never `active`
     even against a live stack. `tests/test_api_boundary_e2e.py:108-137`
     `_require_production_path` skips unless /v1/capabilities reports active
     scheduler/worker → the public-boundary E2E is not release evidence today.
  3. Current committed `tests/test_hatchet_live.py` (lines ~920-1006) already
     binds a real executor + real client (the handoff §6 `_RecordingClient`/
     `executor=None` state is the Plan-I P4-S1 snapshot, superseded in tree) —
     but NO live cluster run has ever executed, so SDK-surface mismatches
     (task-name namespacing, `run_workflow` payload shape, gRPC `host_port`
     routing) are untested.
- **Known SDK 1.38.1 facts (verified 2026-08-28):** `Worker.start()` blocks
  forever; token MUST be a valid JWT (`ey`-prefix) — `umd-ci-token` placeholder
  can never register; `ClientConfig` env prefix `HATCHET_CLIENT_` with
  `HATCHET_CLIENT_HOST_PORT` override; cli.py:104-106 hardcodes
  `host_port=<url-hostname>:7070` which breaks hatchet-lite (grpc 7077) and split
  topology when URL host is the dashboard; `runs.admin_client().run_workflow(
  name, str(input))` is the public submit route; `client.submit_workflow_run`
  does NOT exist on real SDK.
- **Topology facts (docs.hatchet.run, verified 2026-08-28):** split production
  topology = hatchet-migrate → hatchet-admin (config gen) → hatchet-engine
  (grpc 7070) + hatchet-dashboard (8080); hatchet-lite = single container,
  DATABASE_URL as DB+msgqueue, grpc 7077, dashboard 8888, does NOT use
  SERVER_AUTH_COOKIE_SECRET/SERVER_ENCRYPTION_MASTER_KEY (UMD compose's required
  vars come from the split-admin flow). Current compose `hatchet` service env
  matches NEITHER topology — service is non-functional even after image-path fix.
- **Working-tree fix safety verdict (already verified):** python-multipart 0.0.32
  safe; validation.yml ffmpeg + PGDG install sound; `_resolve_pg_bin()` sound;
  `env.setdefault` sound; docker-e2e db+api default + opt-in live gate is an
  HONEST deferral, NOT weakening of a passing gate — BUT the opt-in gate is
  guaranteed-fail if enabled today (image path + non-JWT token).

## Alternatives the debate must cover

- (A) Coordinated hosted-CI provisioning + genuine Hatchet deployment/live
  execution + production-runner wiring + public-boundary E2E.
- (B) CI-only provisioning while deferring product wiring (must be rejected if
  it violates C1/R3).
- (C) Opt-in/skip/recording-doubles (must be rejected under R4/C1).

Every proposed approach, refinement, and pattern MUST be cross-checked against
Task.md (Definition of Done §40 items 1-35, esp. 21/23-24/26/29-35), the parent
DD (`artifacts/designs/pending/DD-universal-media-decomposer.md`), CONTRACTS.md
§58-63, and the release gate (HATCHET_LIVE_VALIDATION_HANDOFF.md §8).

## Key file paths (context for every turn)

- Task.md (root); parent DD `artifacts/designs/pending/DD-universal-media-decomposer.md`
- CONTRACTS.md `artifacts/designs/parts/universal-media-decomposer/CONTRACTS.md`
- HATCHET_LIVE_VALIDATION_HANDOFF.md `artifacts/designs/parts/universal-media-decomposer/HATCHET_LIVE_VALIDATION_HANDOFF.md`
- Debugger report `artifacts/designs/process/universal-media-decomposer-ci-repair-debugger.md`
- Librarian briefing `artifacts/designs/process/universal-media-decomposer-ci-repair-librarian.md`
- Handoff `artifacts/plans/handoff-G-to-I-J.md`
- Plans G/H/I/J `artifacts/plans/pending/TASK-universal-media-decomposer-{G,H,I,J}-*.md`
- Workflow `.github/workflows/validation.yml`; scripts `.github/scripts/*.sh`
- Compose `deploy/compose.yaml`; Dockerfile `deploy/Dockerfile`; pins `deploy/pins/runtime.txt`
- Source: `src/umd/api/app.py`, `src/umd/jobs/{runner,hatchet,capability,production,stage_execution}.py`,
  `src/umd/application/jobs.py`, `src/umd/deploy/cli.py`, `src/umd/api/routers/{sources,system}.py`
- Tests: `tests/test_api_boundary_e2e.py`, `tests/test_hatchet_live.py`,
  `tests/test_deployment_phaseE.py`, `tests/conftest.py`, `tests/fixtures.py`
- Workspace skills: `.opencode/skills/umd-ci-hatchet-deployment/SKILL.md`,
  `.opencode/skills/umd-env-config-deploy/SKILL.md`

---
*Sections below are appended by design agents during adversarial refinement.*
---

## Proposed Approaches

*(T1 — rnd-ideator, first spawn. This regenerated log records the T1 proposals in
the Immutable Requirement Ledger (R1–R12), the Support Findings, and
"Alternatives the debate must cover" above; this marker labels that record and
adds no new claim. Four approaches were proposed:*

1. **A — "Commit-and-Wire" (conventional, primary).** One commit lands the
   uncommitted environment/package fixes together with the product wiring
   (`ProductionDAGRunner` in `app.py`, capability probe, compose topology) and
   makes the live Hatchet path the mandatory, unskippable release gate.
2. **B — "Split-Job CI" (complement).** CI-structure-only: split jobs so the
   live gate is a separate, always-on job with its own evidence — deferred
   until A is green.
3. **C — "Prove-Then-Run" (moonshot).** A `docker manifest inspect` pre-flight
   tripwire on the pinned images plus a conditional live path — folded into A
   as a fast 403-class tripwire.
4. **D — "Single-Container Scheduler" (Hatchet Lite in CI).** Rejected by the
   Ideator's own ranking (3.0) as a release-evidence surface; formally killed
   in T2/T3.

*Every technology/version claim made in T1 is validated in T2 §0's verification
table and T3 §5's revalidation table (all checks 2026-08-28).*

## Critique

*(rnd-counter-ideator, Round 1 critique of the Ideator's Proposed Approaches — appended 2026-08-28.
Evidence tiers per agent rules: T1 = postmortem/incident, T2 = official docs/maintainer statement,
T3 = issue/community report, T4 = practitioner opinion. All web checks dated today.)*

### 0. Verification of the Ideator's technology claims (my own checks, 2026-08-28)

| Ideator claim | My check | Result |
|---|---|---|
| Top-level `ghcr.io/hatchet-dev/hatchet` image path is wrong (403) | GHCR API: token request for that repo fails, `tags/list` → HTTP 403 | **CONFIRMED** (T2 — live registry response) |
| Sub-paths (`hatchet-lite` etc.) exist | GHCR API: `hatchet-dev/hatchet/hatchet-lite` returns 200 with tags (v0.30.x–v0.33.x visible on first page) | **CONFIRMED — with one gap:** v0.105.2 did NOT appear in the n=50 alphabetical page I pulled (alphabetical ordering places v0.10x after v0.09x/before v0.11x, outside the window). The Ideator's table asserted sub-path v0.105.2 as verified 200 OK; I could only confirm the repo exists, not that the specific tag is present for `hatchet-lite`. Must be re-checked with pagination before D is used even for dev. |
| ffmpeg not preinstalled on ubuntu-24.04 runner | actions/runner-images `Ubuntu2404-Readme.md` installed-apt list contains no ffmpeg; migration guides document the package trim (tenki.cloud, dev.to) | **CONFIRMED** (T2) — the uncommitted `apt-get install ffmpeg` step is the correct fix |
| PGDG postgresql-client-17 needed (runner ships PG16 client vs postgres:17 server) | runner migration table: PostgreSQL client on 24.04 = 16.*; pg_dump from older major aborts against newer server | **CONFIRMED** (T2) |
| python-multipart 0.0.32 pin correct (starlette imports `python_multipart`) | 0.0.14 broke the `multipart` namespace (issues #170/#173), yanked; starlette formparsers imports `python_multipart` with fallback | **CONFIRMED** (T3, strong) |
| actions/checkout@v4 / setup-python@v5 "valid, not a defect" | current majors have advanced (checkout v6+ seen in dorny/paths-filter README examples) but versions are compatible | **AGREED — non-load-bearing**, optional bump |

**Correction to the Ideator's evidence base (process fact):** the T1 summary recorded the debugger
report `artifacts/designs/process/universal-media-decomposer-ci-repair-debugger.md` as MISSING from
disk. It now EXISTS (186 lines, untracked, mtime 2026-08-28 21:10). Either it was created after the
T1 check or the check missed it. It must be read before planning; do not plan around a "missing"
artifact that is present.

### 1. Approach A — "Commit-and-Wire" (conventional) — **SURVIVES-WITH-CONDITIONS**

**Finding A-1 (HIGH) — The gate weakening the Ideator says it will flip is the working tree, uncommitted.**
I verified `git diff .github/workflows/validation.yml` against HEAD (a6b1a62 — the commit CI
actually ran). HEAD was FAIL-CLOSED: full stack `--profile sandbox up -d --build` and a hard
`Wait for worker/scheduler readiness (gate)` step that fails the job. The working tree (uncommitted)
adds `UMD_VALIDATE_LIVE_WORKER: "${UMD_VALIDATE_LIVE_WORKER:-false}"`, boots only `db api` by
default, and gates the worker readiness check on the flag.
- **The failure:** a release gate that is off by default (or settable by a PR/repo env var) does not
gate. CodePulse's adversarial CI audit (T3, 2026-04-27): "A test gate that runs is not the same as a
test gate that gates" — the four bypasses all produced green runs without gating.
- **Relevance:** this is exactly OUR gate. The Ideator's fix #5 (flip the default to true) is correct and
necessary — but it must land in the SAME commit as the uncommitted fixes, and the flag must not remain
user-settable. If the weakened diff is committed first, the R4 release gate is off by omission.
- **Severity:** HIGH (fully fixable; ordering is the risk).

**Finding A-2 (HIGH) — `UMD_EXECUTION_BACKEND=durable` is a release-evidence bypass if the default or
the capability report is wrong.**
The Ideator keeps `DurableDAGRunner` behind an explicit non-release env. The problem: the public-
boundary E2E's `_require_production_path` keys off `/v1/capabilities` scheduler/worker status — NOT
off which runner is wired. If the durable backend is active and capabilities report scheduler status
anything but the strict "live cluster reachable AND ProductionDAGRunner wired" truth, the gate passes
against an in-process double.
- **The failure (same shape):** LaunchDarkly 5.0 flag misconfiguration postmortem (johal.in, T3): a
hardcoded fallback-to-true left over from testing silently activated the broken discount engine in
production when the client was slow — the fallback default was wrong and nobody audited it.
- **The failure (same shape):** "Your Fallback Path Is the Only Untested Code in Production"
(tianpan.co, T3): fallback paths "manufacture confidence" and rot because they are never exercised.
AWS's documented position on fallbacks (via HLD handbook quoting the 2001 shipping-cache incident,
T2): fallback almost never helps; prefer exercising the primary path continuously.
- **Relevance:** the durable runner is continuously exercised by the hermetic Postgres seam tests, so it
won't rot. But its mere existence + an env gate creates a plausible release-evidence path. Requirements:
(1) default = `ProductionDAGRunner` or fail-closed startup error when the backend env is absent;
(2) capabilities must report scheduler `active` ONLY when ProductionDAGRunner is wired AND a live
reachability probe passes — never from the durable backend; (3) the boundary E2E must hard-assert the
live backend, not just read a capability string.
- **Severity:** HIGH. This is the answer to open question (b): yes, the leak risk is real; it is
contained only by fail-closed defaults + capability honesty.

**Finding A-3 (HIGH) — The live shape tests cannot reach the stack from where the workflow runs them.**
Handoff §6 invokes pytest from the HOST with `UMD_HATCHET_SERVER_URL=http://hatchet:8080`;
`_real_client()` defaults to `host_port :7070`. Compose publishes NO ports on the hatchet service, so
from the host `hatchet` does not resolve and neither 8080 nor 7070 is reachable.
- **The failure:** hatchet-python-quickstart#13 (T3) documents this exact class: the SDK's admin client
fails with "DNS resolution failed for hatchet-engine:7070" when the client is not on the right network
or port. gRPC `host_port` routing is one of the three SDK-surface mismatches the handoff already flags
as untested.
- **Relevance:** even with `UMD_VALIDATE_LIVE_WORKER=true`, the three `test_live_hatchet_*` tests fail at
connection — the "will fail on first enable" item every approach inherits. Fix: publish the engine's
HTTP+gRPC ports and remap env to 127.0.0.1, OR run the shape tests inside a test container on the
compose network (preferred — matches §8 "same stack").
- **Severity:** HIGH.

**Finding A-4 (MEDIUM) — the CapabilityReporter probe must not be a naive per-request network check.**
Adding a real connectivity probe is the right direction, but a synchronous per-request probe flaps and
turns the engine into a hard dependency of the request path.
- **The failure:** Kubernetes probe literature (KubeHA "Your Readiness Probe Is Probably Lying" T3; New
Relic probe tuning guide T2; Code With Karani on shared /health endpoints T3): tight thresholds flip
readiness on a single slow response; the fix is a cached background probe with hysteresis
(`failureThreshold ≥ 2`, cached result). A probe that checks the wrong surface (HTTP 8080 reachable ≠
gRPC admin reachable ≠ engine can execute) produces false confidence.
- **Relevance:** `_require_production_path` reads capability status once at scenario start. A flapping
probe yields a false-negative skip (hides a real pass) or, worse, an env-only "probe" yields a false
positive. This is the answer to open question (f): yes add the probe; it must be background/cached with
hysteresis, must probe the gRPC admin surface the SDK actually uses, and must never block the request
path.
- **Severity:** MEDIUM.

**Approach A verdict: SURVIVES-WITH-CONDITIONS.** Conditions: gate-polarity flip in the same commit as
the uncommitted fixes; durable backend fail-closed with capability honesty; live-test invocation
repaired to reach the stack; probe with hysteresis on the gRPC surface.

### 2. Approach B — "Split-Job CI" (complement) — **SURVIVES as complement ONLY**

**Finding B-1 (HIGH) — trigger-level path filters on a required release gate are a documented anti-pattern.**
- **The failure:** a trigger-level `paths` filter silently produces no run (or a skipped run) for changes
outside the listed paths (Latchkey Learn, T3, 2026-06; StackOverflow 67717380, T3). Worse,
`branches` and `paths` are ANDed, so a docs-only push to main skips the live job entirely (dev.to
analysis, T4). The systematic fix: "For anything gating a merge, filter inside the workflow instead, so
the workflow always runs and always reports", with a gate job using `if: always()` that fails if the
live job was skipped (DevOpsNess, T3).
- **Relevance:** B gates `docker-live` on push-to-main AND path filters over worker/hatchet/api/jobs. A
change to `deploy/compose.yaml`, `deploy/Dockerfile`, `deploy/pins/*`, `pyproject.toml`, or
`tests/conftest.py` that breaks the live stack but touches no listed path silently skips the live gate
— the "CI green by exclusion" shape that R2/R4 prohibit. The 300-file / 1000-commit ceiling on path
filtering (dev.to, T4) adds a second hole: a giant merge runs the filter as if it passed.
- **Severity:** HIGH — mitigated by (i) no trigger-level path filter on the live job for main pushes;
(ii) an always-running gate job that fails if `docker-live` did not run; (iii) filter inside with
dorny/paths-filter only if cost is a real problem.

**Finding B-2 (MEDIUM) — ordering hazard.** The Ideator is honest that B is CI-structure only and must
combine with A. Endorsed, with the ordering made explicit: if B lands before A's code fixes, `docker-live`
is red from day one (403 image path + worker packaging), and the first response will be to disable or
path-filter the live job — which is the corrosion B was meant to prevent.

**Finding B-3 (LOW-MEDIUM) — duplication cost under-specified.** Two stack boots per push unless build
cache is shared across jobs; ubuntu-24.04 runners also cache NO docker base images (runner migration
notes, T3), so first-pull time is a real cost. Operational, not design-fatal.

**Approach B verdict: SURVIVES as complement ONLY, after A is green, with no trigger-level path filter
on the live job, a gate job that fails on skip, and shared build cache.**

### 3. Approach C — "Prove-Then-Run" (moonshot) — **SURVIVES folded into A; allow-failure posture is the risk**

**Finding C-1 (MEDIUM-HIGH) — the `allow-failure: true` opt-out is a documented corrosion pattern.**
- **The failure:** "From allow_failure to blocking" (phpboyscout.uk, T3): "a warning nobody is forced to
act on is a warning nobody acts on… it becomes scenery"; BackEndTea "Stop (ab)using allow failure"
(T3): the flag stays long after the trigger issue is fixed, hiding the next real failure; GitLab docs
(T2): an allow_failure job's commit is "marked as passed with no warnings".
- **Relevance:** the Ideator's mitigation (workflow_dispatch opt-out that STILL runs the live path, never
skips it) is structurally better than the alternatives — but any mechanism that lets the live job fail
while the overall run is green recreates the corrosion. Requirement: the opt-out must still fail the
overall run on push-to-main (no green-with-warning posture), and any tolerated-failure mechanism must
expire / require re-authorization.
- **Severity:** MEDIUM-HIGH.

**Finding C-2 (MEDIUM) — `docker manifest inspect` proves tag existence, not pullability or runnability.**
A manifest can exist while layers fail to pull (rate limit, storage backend error) or the image fails at
entrypoint. For THIS defect class (403 on the top-level path), manifest inspect fails fast and
attributably — a genuine improvement — and the Ideator correctly labels it a tripwire, not release
evidence. Evidence here is registry-behavior knowledge (T4); I could not find a strong postmortem and
say so honestly. The compose-up + live run remains the evidence.

**Finding C-3 (LOW) — `pip index versions` probe adds near-zero value.** The pin-agreement test
(`test_hatchet_release_pin_is_single_validated_and_agreed`) already covers the SDK pin statically;
`pip index` is experimental and environment-dependent. Harmless; skip or keep as a 3-line tripwire.

**Approach C verdict: SURVIVES folded into A (pre-flight probe catches the 403 class fast); the
allow-failure posture must be constrained as in C-1.**

### 4. Approach D — "Single-Container Scheduler" (Lite in CI) — **DEAD as release-evidence surface**

**Finding D-1 (HIGH) — topology skew violates handoff §8's "same Compose/CI stack" release gate.**
- **The failure:** Hatchet's own docs describe lite as "designed for development and low-volume
use-cases" (T2). The split production topology differs from lite in load-bearing ways: gRPC port (the
official lite compose maps 7077; UMD hardcodes 7070 in cli.py and `_real_client`), dashboard port
(8888 vs 8080), DB+msgqueue (lite = DATABASE_URL postgres-backed queue; full topology = separate
engine/admin/migrate services and RabbitMQ per the official compose docs), and auth vars (lite does NOT
consume SERVER_AUTH_COOKIE_SECRET / SERVER_ENCRYPTION_MASTER_KEY — the vars UMD's compose hatchet
service requires). The log's own topology facts (lines 150-156 above) state the current compose `hatchet`
service matches NEITHER topology — so the same-stack gate has already failed once; Lite would compound
rather than repair the skew.
- **Relevance:** handoff §8's gate fails if shape tests pass only on a different scheduler surface.
Evidence produced against Lite is evidence that *a* Hatchet works, not that the deployed topology works
— the exact gap R4 forbids. This is the answer to open question (c): yes, D violates the same-stack
release gate; the Ideator's own ranking (3.0, rejected standalone) already concedes this.
- **Severity:** HIGH.

**Finding D-2 (MEDIUM) — the lite gRPC port divergence is a concrete, documented difference in the
untested-routing class.** The official lite compose maps gRPC on 7077 (T2); UMD's `_real_client()`
defaults to 7070 and cli.py derives `{hostname}:7070`. Without `UMD_HATCHET_CLIENT_HOST_PORT` set in
CI, worker registration/submission points at the wrong port. hatchet-python-quickstart#13 (T3)
documents the resulting failure verbatim (gRPC DNS/routing error). Even a dev-only Lite adoption needs
the env override.

**Approach D verdict: DEAD as release-evidence surface. Acceptable only as documented local developer
convenience, never in the release pipeline — matching the Ideator's own rejection.**

### 5. Cross-cutting: the shared SDK-surface risk that gates EVERY approach

The single highest-risk unvalidated item is the SDK registration/submission surface. Every approach's
live gate depends on `worker.start()` registering tasks and the SDK submitting workflow runs — and
three surfaces are contradicted or unverified by documented SDK v1 semantics:

1. **Task handler signature (HIGH).** The V1 migration guide (T2) states tasks now take two arguments:
`input` and `context`. The UMD handler built by `_make_handler` takes ONE argument (`payload`) and
indexes `payload["input"]["manifest"]`. With the default input validator (EmptyModel), the first live
dispatch fails (TypeError or a Pydantic-model attribute error). This follows directly from documented
SDK v1 semantics versus the code in tree — the tests will surface it on first live run as a poll
timeout (the compose worker crashes the handler, no stage_run rows are written).
2. **Submission surface (HIGH).** The migration guide (T2) states "The AdminClient has been removed, and
refactored into individual clients… you can use `hatchet.runs.create`", with input typed as
`JSONSerializableMapping`. `_real_submit_workflow_run` calls
`runs.admin_client().run_workflow(name, json.dumps(input))` — method name (run_workflow vs create) and
input type (JSON string vs mapping) both differ from the documented surface. Either the code is right
about an internal accessor (unverifiable without SDK source) or the first live submit fails.
3. **Worker/task name namespacing (MEDIUM).** Hatchet #2832 (T3) documents name-normalization
inconsistencies; worker names get a configured namespace auto-prepended (T2). UMD's `umd-{stage.lower()}`
is probably fine but unverified against 1.38.1.

**Relevance:** this is exactly why the CANDIDATE pin status and the live shape gate are load-bearing, and
why NO approach can claim the live path is release evidence until one genuine live run has executed and
these three surfaces are observed. This argues FOR C's prove-first posture and AGAINST any path that
deploys the wiring before a live run (A already orders this correctly by making the live path the gate).
The plan must budget for a first-live-run cycle where these surfaces are fixed as they surface, not
assumed.

### 6. Answers to the Refiner's open questions (a)-(f)

- **(a) Does any approach secretly rely on in-process doubles / weakened gates?** Verified: the
uncommitted working-tree `validation.yml` IS a weakened gate (opt-in live off), but no approach proposes
committing it as-is — A flips it, B makes live always-on, C makes it unconditional. The only in-process
double risk is A's `UMD_EXECUTION_BACKEND=durable` escape (Finding A-2). The recording-client cluster
tests remain as hermetic unit coverage, correctly cluster-marked, and are NOT release evidence — fine.
- **(b) Does A's durable-backend env risk leak into release evidence?** Real. Contained only by
fail-closed default + capability honesty + a hard assert in the boundary E2E (Finding A-2).
- **(c) Does D's topology skew violate §8?** Yes (Finding D-1); DEAD.
- **(d) Is `_require_production_path` skip removal honest in every approach?** Yes — every approach
removes it only by real scheduler activity via the capability probe, never by deleting the skip. The
probe itself must be a real reachability check with hysteresis (Finding A-4).
- **(e) Ideator correction #1 (tests bind real executor + client) — consistent with handoff §6?**
Confirmed in the current tree; the handoff defect describes the Plan-I P4-S1 snapshot, superseded. The
tests are structurally correct but STILL need the live-run repair cycle: the SDK-surface mismatches in
§5 (handler signature, submission surface, host_port) will fail on first live execution. "Repair"
means one real live run with the compose worker, not editing the tests.
- **(f) Is adding a CapabilityReporter connectivity probe right?** Yes; failure modes are flapping and
wrong-surface (Finding A-4). Probe the gRPC admin surface with a cached background probe and
hysteresis; never per-request synchronous.

### 7. Summary

- **Surviving approaches:**
  - **A (Commit-and-Wire)** — SURVIVES-WITH-CONDITIONS: flip gate polarity in the same commit as the
  uncommitted fixes; durable backend fail-closed + capability honesty; repair live-test invocation to
  reach the stack; probe with hysteresis on the gRPC surface.
  - **C (Prove-Then-Run)** — SURVIVES folded into A: pre-flight manifest inspect as a tripwire; constrain
  the allow-failure posture (no green-with-warning on main).
  - **B (Split-Job CI)** — SURVIVES as post-green follow-up: no trigger-level path filter on the live job;
  always-running gate job that fails if the live job was skipped; shared build cache.
- **Dead approaches:** D (Single-Container Lite) — topology skew violates §8; lite gRPC port diverges
from the hardcoded 7070.
- **Most critical unresolved concern:** the SDK v1 surface mismatches (§5) are untested and load-bearing
for every approach's release gate. The first genuine live run is the arbiter; the plan must budget for
it and for the host-to-stack invocation defect (Finding A-3) that will otherwise make the first live
run fail at connection, not at the application.

## Refined Approaches

*(rnd-ideator, Turn 3 — refinement of the T1 Proposed Approaches after the T2 Critique. All
T2 findings are addressed; the debugger report (present on disk, read fully) is integrated. All
web checks dated 2026-08-28 unless noted. Every surviving approach is the REFINED version, not a
restatement.)*

### 0. Verdict on the T1 approaches after T2

| Approach | T2 verdict | Status after refinement |
|---|---|---|
| A — Commit-and-Wire | SURVIVES-WITH-CONDITIONS (A-1..A-4) | **REFINED — primary approach** (§1) |
| C — Prove-Then-Run | SURVIVES folded into A (C-1..C-3) | **FOLDED INTO A** (§1, C-items mapped) |
| B — Split-Job CI | SURVIVES as post-green complement (B-1..B-3) | **REFINED — post-green complement** (§2) |
| D — Single-Container Lite | DEAD (D-1 HIGH, D-2 MEDIUM) | **REJECTED — documented** (§3) |

### 1. Refined Approach A — "Commit-and-Wire, fail-closed, prove-first" (primary)

One commit that lands the uncommitted environment/package fixes together with the gate-polarity
flip and the product wiring; the live Hatchet path is the mandatory, unskippable release gate.
The T2 critique confirmed the working tree (uncommitted `validation.yml`) weakens the gate; HEAD
(a6b1a62) was fail-closed. A-refined fixes the ordering risk by making the flip part of the same
commit as the fixes, and removes every user-settable escape.

**Finding → refinement mapping (every HIGH/MEDIUM finding):**

- **A-1 (HIGH, gate weakening is the uncommitted working tree).** Refinement: the uncommitted
  `validation.yml` diff (ffmpeg + PGDG install in the postgres job — CORRECT and retained; the
  `UMD_VALIDATE_LIVE_WORKER: "${UMD_VALIDATE_LIVE_WORKER:-false}"` env + `db api` default boot +
  `if: env.UMD_VALIDATE_LIVE_WORKER == 'true'` on the worker readiness step — REMOVED) must land
  **in the same commit** as the product fixes (app.py runner wiring, capability probe, compose
  topology, SDK-surface fixes). The flag must not remain user-settable: the docker-e2e job boots
  the full stack unconditionally (`--profile sandbox up -d --build` as at HEAD) and the
  worker/scheduler readiness step is unconditional. A repo/PR env var that can switch the gate off
  is exactly the "test gate that runs is not a gate that gates" corrosion (CodePulse adversarial
  CI audit, T3 2026-04-27 — recorded in T2 §1).
- **A-2 (HIGH, `UMD_EXECUTION_BACKEND=durable` is a release-evidence bypass).** Refinement:
  (1) `build_context` (src/umd/api/app.py:167) defaults to **`ProductionDAGRunner`** — no env
  required; the `durable` backend is selectable only via an explicit non-release env that the
  release CI never sets, and even then the API refuses to report scheduler `active`.
  (2) `CapabilityReporter.report()` reports scheduler `active` **only when** the wired runner is
  `ProductionDAGRunner` **AND** the cached live probe (A-4) passes; the durable backend can never
  produce `active` — it reports `configured-but-unavailable`/`reference-only` with a gate reason.
  This closes the LaunchDarkly-flag / tianpan.co fallback-path hole identified in T2 §1: the
  fallback is not merely less-tested, it is structurally incapable of producing release evidence.
  (3) The boundary E2E does not merely read a capability string: it hard-asserts the live backend
  — capabilities `scheduler.status == active`, the reported `server_image` equals the pinned
  sub-path image, AND the job transitions asynchronously (observes `queued` stage states /
  `RUNNING`, then terminal `COMPLETE` from worker-callback-committed `stage_run` rows). A job that
  reaches COMPLETE synchronously inside the submit call is a durable-backend signature and fails
  the assertion. `_require_production_path` (tests/test_api_boundary_e2e.py:108-137) keeps its
  honest gate semantics, and the CI step additionally fails if the scenario was vacuously skipped
  (no green-without-run).
- **A-3 (HIGH, live shape tests cannot reach the stack from the host).** Refinement — preferred
  per T2: **run the shape tests inside a container on the compose network** ("same stack", handoff
  §8), not from the host. Mechanism: a one-shot test-runner container (same API image, worker
  extra installed) joined to the compose network, invoked with `docker compose run`/`exec`, with
  `UMD_HATCHET_SERVER_URL=http://hatchet-dashboard:8080`,
  `UMD_HATCHET_CLIENT_HOST_PORT=hatchet-engine:7070` (gRPC — in-network, no host port publishing
  required), `UMD_TEST_POSTGRES=true`, and the db service reachable as `db:5432`. This directly
  matches the handoff §6 "in-stack service name" contract and removes the DNS/port class of
  failure (hatchet-python-quickstart#13, T3, recorded in T2 §1). Real-world precedent:
  Genealogy-MCP/gramps-mcp `fix(ci): run tests inside Docker Compose network` (commit 071e3f6,
  2026-04-08 — https://github.com/Genealogy-MCP/gramps-mcp/commit/071e3f645cda7254acb13b6d8032eaba960e6f0e);
  Compose Tip #52 "Setting up a CI test environment" (G. Lours, 2026-04-13 —
  https://lours.me/posts/compose-tip-052-ci-test-environment/); pytest-docker /
  pytest-dockerc fixtures (https://github.com/avast/pytest-docker). The host-publish + 127.0.0.1
  remap remains the documented fallback.
- **A-4 (MEDIUM, probe must be cached/background with hysteresis on the gRPC surface).**
  Refinement: the CapabilityReporter connectivity probe is a **background cached probe** with
  hysteresis — minimum `failureThreshold ≥ 2` consecutive failures to flip to not-active and
  `successThreshold ≥ 2` to flip back (flap damping), probing the **gRPC admin surface the SDK
  actually uses** (`host_port` = engine gRPC 7070 in the split topology; not the HTTP dashboard
  port — HTTP reachable ≠ gRPC admin reachable ≠ engine executes). The request path reads the
  cached boolean; the probe never runs per-request and never blocks `/v1/capabilities`. This is
  the documented production pattern: Kubernetes probe semantics
  (https://kubernetes.io/docs/concepts/workloads/pods/probes/ — failureThreshold/successThreshold
  hysteresis), "readiness probe flapping → add hysteresis successThreshold 2 / failureThreshold 3"
  (oneuptime k8s health-check guide, 2026-01-08 — https://oneuptime.com/blog/post/2026-01-08-kubernetes-network-health-checks/view),
  and cached-background-probe ("cache dependency state in memory, refresh on a background tick,
  the probe handler reads the cached value" — decodeops, 2026-05-06 — https://decodeops.substack.com/p/your-readiness-probe-hammers-your).
  The probe requires `hatchet_sdk` in the API image (see §4 worker-image packaging) — an
  additional reason the shared image installs the worker extra.
- **C-1 (MEDIUM-HIGH, allow-failure is corrosion).** Refinement: **no `allow-failure: true` /
  `continue-on-error` anywhere on the live path on push-to-main.** Any tolerated-failure
  mechanism (none survives in A-refined) would have to fail the overall run on main and expire /
  require re-authorization. Rationale per BackEndTea "Stop (ab)using allow failure" and GitLab
  docs (T2 §3, recorded).
- **C-2 (MEDIUM, manifest inspect ≠ pullability).** Refinement: keep `docker manifest inspect` on
  the **sub-path** images (it fails fast and attributably on the 403 class — T2 §3 agrees) as a
  **tripwire only**; compose-up + live run remains the release evidence. C-3: the `pip index
  versions` probe is dropped as near-zero value (T2 §3 agrees; the static pin-agreement test
  covers the SDK line).
- **§5 cross-cutting (HIGH, SDK v1 surface).** Refinement: no assumption that the tree's SDK
  surfaces are correct — the first-live-run cycle is the arbiter, and the plan must budget for
  it (T2 §5). The two documented mismatches are now confirmed against official sources
  (validation table §5): (a) task handler must take **two positional arguments**
  (`input, ctx`), not one `payload` (the tree's `_make_handler(payload)` indexing
  `payload["input"]["manifest"]` breaks against the default `EmptyModel` input — first dispatch
  fails as a poll timeout, not a clean error); (b) the submission surface is
  **`Workflow.run(input)` / `Standalone.run(input)` or `hatchet.runs.create` with a
  JSONSerializableMapping** — `runs.admin_client().run_workflow(name, json.dumps(input))`
  (src/umd/jobs/hatchet.py:118-137) targets the removed `AdminClient` (removed in v1, PR #1413
  "don't export admin client anymore"). Worker/task name namespacing (Hatchet #2832, T3) remains
  a first-live-run observation, not a fix target.

### 2. Refined Approach B — "Split-Job CI" (post-green complement ONLY)

B is CI structure only and is deferred until A-refined is green on a hosted run (T2 B-2 ordering:
if B lands first, `docker-live` is red from day one and the first response would be to disable it —
the corrosion B exists to prevent).

**Finding → refinement mapping:**

- **B-1 (HIGH, trigger-level path filters on a required gate are an anti-pattern).** Refinement:
  **no trigger-level `paths` filter on the live job for main pushes** (a change to
  compose/Dockerfile/pins/pyproject/conftest outside the listed paths must never silently skip
  the live gate — T2 B-1, Latchkey/StackOverflow/dev.to evidence recorded there). The workflow
  always runs on main pushes. **An always-running gate job** (`if: always()`, `needs: [live-job]`)
  **fails the run if the live job did not run (skipped) or failed**. This is the documented
  topology: GitHub's own troubleshooting docs — "You should not use path or branch filtering to
  skip workflow runs if the workflow is required", "A job is skipped by a conditional → reports
  Success", "Use `always()` with `needs` for required checks that depend on other jobs"
  (https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories-with-code-quality-features/troubleshooting-required-status-checks);
  the always-run fallback/gate job pattern (Latchkey Learn, 2026-06-26 — https://latchkey.dev/learn/github-actions/github-actions-conditional-job-skipped-marked-failed-branch-protection);
  and the always-run-job-that-fails-on-upstream-skip pattern used by LinkedIn Venice in
  production (actions/runner#2566 — https://github.com/actions/runner/issues/2566). Only if
  runner cost becomes a measured problem is dorny/paths-filter used **inside** the job with the
  gate job still failing on skip.
- **B-3 (LOW-MEDIUM, duplicate stack boots).** Refinement: shared docker build cache across jobs
  (docker/build-push-action cache or equivalent) so the second boot reuses layers; ubuntu-24.04
  runners cache no base images, so first-pull cost is real (T2 B-3).

### 3. Approach D — REJECTED (documented rejection)

**D (Single-Container Hatchet Lite in CI) is DEAD as a release-evidence surface.** Rejection
reasons (T2 D-1/D-2, confirmed by my own checks today):

1. **Topology skew violates handoff §8's "same Compose/CI stack" release gate (HIGH).** Hatchet's
   own docs describe lite as "designed for development and low-volume use-cases"
   (https://docs.hatchet.run/self-hosting/hatchet-lite, checked 2026-08-28). Evidence produced
   against lite is evidence that *a* Hatchet works, not that the deployed topology works — the
   exact gap R4 forbids.
2. **gRPC port divergence (MEDIUM):** lite maps gRPC on **7077** (official lite compose,
   `SERVER_GRPC_PORT: "7077"`, dashboard 8888) while UMD hardcodes `:7070` in
   `src/umd/deploy/cli.py:106` and defaults `host_port :7070` in `tests/test_hatchet_live.py`
   `_real_client()` (line 308). The split engine also defaults `SERVER_GRPC_PORT 7070`; the
   hardcoded 7070 is only correct for split, never lite, without an env override.
3. **Auth-var mismatch (MEDIUM):** lite does not consume `SERVER_AUTH_COOKIE_SECRET` /
   `SERVER_ENCRYPTION_MASTER_KEY` (the vars UMD compose requires under `${VAR:?}`); those come
   from the split-admin flow. C7 forbids weakening the interpolation, so lite and C7 are
   incompatible in the current compose.
4. **Current compose `hatchet` service matches NEITHER topology** (support findings, log lines
   150-156): single service, no command, no DATABASE_URL, no config mount, no port mapping,
   split-admin vars but no admin/engine/dashboard split — it is non-functional even after the
   image-path fix. D would compound rather than repair this skew. Rejected as release-evidence
   surface; not even acceptable as a local-dev convenience until the env override exists.

### 4. Debugger-report findings integrated into A-refined

The debugger report (`universal-media-decomposer-ci-repair-debugger.md`, read fully) adds four
items that A-refined now carries explicitly:

1. **Worker-image packaging decision (NEW gap).** `deploy/Dockerfile:32` runs `pip install .`
   (base deps only); `pyproject.toml:79-81` puts `hatchet-sdk==1.38.1` in the optional `worker`
   extra. The compose `worker` service builds the SAME Dockerfile — so the image the worker role
   actually runs lacks the SDK, and `cli.worker()` exits 2 ("hatchet_sdk not installed"). **Decision:
   the single shared image installs the worker extra (`pip install .[worker]`), OR a
   multi-target Dockerfile with a `worker-image` target that compose's worker service selects.
   The single-image variant is recommended** (matches the "one image, two roles" design comment
   at the top of the Dockerfile; the API process never imports `hatchet_sdk` at module level so
   there is no API startup cost; AND the A-4 capability probe needs the SDK inside the API
   container). Installing the SDK does NOT promote the CANDIDATE pin (C4) — it only makes the
   image runnable; the pin stays pending live validation.
2. **JobService async status reconciliation (product gap).** `ProductionDAGRunner.run_graph`
   (src/umd/jobs/runner.py:276-296) submits queued work; `JobService.submit`
   (src/umd/application/jobs.py:90-116) invokes the runner then immediately `_refresh_status`.
   **Decision:** the async contract is preserved and reconciled by (a) submit leaving the job
   RUNNING with queued stage states — never fabricated COMPLETE (the existing `_derive_status`
   already folds stage states and returns RUNNING until all are complete); (b) terminal COMPLETE
   arriving only from worker-callback-committed `stage_run` rows via `DurableStageExecutor`
   (claim-before-side-effect, UNIQUE idempotency_key, atomic StageCompleted — CONTRACTS.md:60-63);
   (c) the boundary E2E and shape tests polling `/v1/jobs/{id}` / Postgres until terminal state,
   which is exactly the evidence the failed run lacks. No synchronous substitution, no fabricated
   completion.
3. **Exact image-path repair target.** `deploy/compose.yaml:104`
   (`ghcr.io/hatchet-dev/hatchet:${HATCHET_VERSION:-v0.105.2}`) and
   `src/umd/jobs/hatchet.py:56` (`HATCHET_SERVER_IMAGE`) both carry the WRONG top-level path
   (403). The repair target is the split sub-paths (`hatchet-engine`, `hatchet-admin`,
   `hatchet-migrate`, `hatchet-dashboard`) — **I verified all four sub-path repos return HTTP 200
   for the `v0.105.2` manifest and the top-level path returns 403** (GHCR manifest HEAD checks,
   2026-08-28 — same check Docker performs; this closes T2's pagination gap). The compose hatchet
   service must be rebuilt to the official split topology (migrate → admin/config-gen →
   engine+dashboard on the compose network), with the worker reaching engine gRPC at
   `hatchet-engine:7070` in-network and the dashboard HTTP at `hatchet-dashboard:8080`; the
   required `HATCHET_COOKIE_SECRET`/`HATCHET_MASTER_KEY` (`${VAR:?}`, C7) are exported in the
   unit/postgres jobs too (debugger H3) and passed to the config-gen service in whatever form
   v0.105.2 consumes (PROVISIONAL — see §6).
4. **Environment fixes (retained from the working tree, unweakened):** python-multipart 0.0.32
   (already committed in pyproject at HEAD? — NO: it is part of the uncommitted fixes; it lands in
   the same commit per A-1), ffmpeg + PGDG `postgresql-client-17` + `UMD_PG_BIN` in the postgres
   job, and secrets export in unit/postgres jobs. All are real dependency defects, none is a stub
   or skip (R2).

### 5. Refined technology validation summary (revalidated 2026-08-28)

| Choice | Source / check date | Result | Why best fit (not merely newest) |
|---|---|---|---|
| `hatchet-sdk==1.38.1` | PyPI project page https://pypi.org/project/hatchet-sdk/ and GitHub release `py/1.38.1` (2026-08-25) — checked 2026-08-28 | Current release line; MIT; Python >=3.10,<4 | Already the recorded candidate (deploy/pins/runtime.txt, pyproject worker extra, hatchet.py); released 3 days ago — kept as candidate, NOT promoted; lockstep-upgrade rule (C4) applies if the live pair fails |
| Server image sub-paths at `v0.105.2` | Direct GHCR manifest HEAD: `ghcr.io/v2/hatchet-dev/hatchet/{hatchet-engine,hatchet-lite,hatchet-admin,hatchet-migrate}/manifests/v0.105.2` — checked 2026-08-28 | **All four sub-path repos: HTTP 200; top-level `hatchet-dev/hatchet`: HTTP 403** | Closes T2's open tag-existence gap; confirms the exact repair target (split sub-paths) and the exact failure class (top-level 403 = the CI daemon error) |
| Task handler signature (v1) | Official V1 migration guide — https://docs.hatchet.run/v1/migrating/migration-guide-python — checked 2026-08-28 | "Tasks have a new signature. They now take two arguments: `input` and `context`"; input is a Pydantic model (default `EmptyModel`) | Confirms §5(a): tree `_make_handler(payload)` is a live-run blocker; the first-live-run cycle fixes it |
| Submission surface (v1) | Official "SDK Improvements in V1" — https://docs.hatchet.run/v1/migrating/v1-sdk-improvements — checked 2026-08-28 | "The `AdminClient` has been removed… you can use `hatchet.runs.create`. This replaces the old `hatchet.admin.run_workflow`"; all client functions are verbs (`runs.list`, `runs.create`); `Workflow.run`/`Standalone.run` preferred | Confirms §5(b): `runs.admin_client().run_workflow(...)` targets the removed surface; align to `Workflow.run`/`runs.create` with a JSON-serializable mapping |
| Hatchet split topology (engine gRPC 7070 / dashboard 8080) | Official Docker Compose deployment — https://docs.hatchet.run/self-hosting/docker-compose — checked 2026-08-28 | split = migrate → admin (config gen) → engine (gRPC 7070) + dashboard; lite = single container, gRPC 7077, dashboard 8888, no split auth vars | Confirms D rejection (topology skew) and the target topology for A-refined |
| `python-multipart==0.0.32` | T2 registry evidence (yanked 0.0.14 class, starlette formparsers import) — recorded in Critique §0 | Pin real; CI failure was the missing package | Keep as-is in the same commit as A-1 |
| ffmpeg on ubuntu-24.04 | actions/runner-images Ubuntu2404 apt list (T2 §0) | Not preinstalled; `apt-get install ffmpeg` is the correct fix | Retained from working tree |
| PGDG `postgresql-client-17` | runner migration table: 24.04 ships PG16 client vs postgres:17 service (T2 §0) | PGDG `noble-pgdg` + client-17 + `_resolve_pg_bin()`/`UMD_PG_BIN` sound | Retained from working tree |
| Action versions (checkout@v4, setup-python@v5, upload-artifact@v4) | T2 §0 — "valid, not a defect; optional bump" | Non-load-bearing | Keep; optional bump only, never in the same commit as A-1 |
| Background probe with hysteresis | Kubernetes probe docs (checked 2026-08-28); oneuptime k8s guide (2026-01-08); decodeops (2026-05-06) | failureThreshold ≥ 2 / successThreshold ≥ 2; cached background state read by the handler | A-4 design basis |
| Gate-job-fails-on-skip CI topology | GitHub troubleshooting docs (checked 2026-08-28); Latchkey Learn (2026-06-26); LinkedIn Venice actions/runner#2566 | always-running gate job + `always()` + needs.result check | B-1 design basis |
| In-network test execution | gramps-mcp commit 071e3f6 (2026-04-08); Compose Tip #52 (2026-04-13); pytest-docker | one-shot test container on the compose network | A-3 design basis |

### 6. PROVISIONAL items and the first-live-run cycle

The following remain PROVISIONAL (not live-validated) and are exactly what the first genuine
hosted run must observe:

1. **SDK ↔ server live pair (C4).** hatchet-sdk 1.38.1 ↔ server v0.105.2 remains CANDIDATE until
   a real pull/connect/execute test succeeds. Nothing in this refinement promotes it.
2. **The exact v1 handler/submission shapes on the live pair.** The two-arg handler and the
   `Workflow.run`/`runs.create` submission surface are documented, but the tree's
   `_make_handler`/`_real_submit_workflow_run` must be aligned and observed end-to-end; worker/task
   name namespacing (Hatchet #2832) is observed, not pre-fixed. Expected first-run cycle:
   (a) handler TypeError / poll timeout from the one-arg handler; (b) `HatchetNotConfiguredError`
   or 4xx from the removed `admin_client` surface; (c) gRPC routing issues until
   `HATCHET_CLIENT_HOST_PORT`/host_port matches the split engine — each fixed as it surfaces,
   never by weakening the gate.
3. **The compose split-topology env contract for v0.105.2.** The exact variable names the
   v0.105.2 engine/config-gen consumes (`SERVER_AUTH_COOKIE_SECRET` singular vs newer
   `SERVER_AUTH_COOKIE_SECRETS`/`SERVER_ENCRYPTION_MASTER_KEYSET` plural forms seen in the k8s
   docs, `SERVER_GRPC_*`, `DATABASE_URL`, msgqueue choice) are PROVISIONAL until the image runs;
   the `${VAR:?}` required-interpolation contract (C7) is preserved regardless.
4. **Capability probe behavior in production.** The probe's threshold/timing and the exact gRPC
   admin call are design intent until measured against the live engine.
5. **Worker readiness line under the real stack.** The `worker ready: registered N Hatchet
   workflows (candidate, pending Plan J live validation)` line (C6) is emitted before
   `worker.start()`; its "(candidate...)" suffix stays until the live pair is proven.

**Ordering guarantee (A-1):** the gate-polarity flip, the uncommitted fixes, the runner wiring,
the compose topology/image-path repair, the packaging decision, and the capability probe land in
ONE commit; CI is managed by pushing to GitHub and retrieving reports (R1/C2); local validation
is context only (R6); the design/plan/Exec-Manager process (R5/R9) is unchanged.

---

## Surviving Concerns

*(rnd-counter-ideator, Turn 4 — final critique of the T3 Refined Approaches. All claims below were
re-verified against the current tree and official/maintainer sources on 2026-08-28. Evidence tiers
per agent rules; every concern states what persists, why it applies HERE, and the trigger.)*

### 0. Re-verification of T3's load-bearing claims (my own checks, 2026-08-28)

| T3 claim | My check | Result |
|---|---|---|
| Four sub-path repos serve the `v0.105.2` manifest (200); top-level path is 403 | GHCR token dance + manifest HEAD: `hatchet-engine`, `hatchet-admin`, `hatchet-migrate`, `hatchet-dashboard` → **200, 200, 200, 200**; top-level token request returns empty (`token_response_len=0`) → manifest **403** | **CONFIRMED exactly** (note: an unauthenticated `curl -I` returns 401 for ALL paths, so the check must be the token-dance form the T3 used; Docker performs the same) |
| V1 task handler takes two args (`input`, `context`) | Official V1 migration guide + SDK Improvements page: "inputs are injected directly into the task as the first positional argument, so the signature of a task now will be `Callable[[YourWorkflowInputType, Context]]`"; tree `_make_handler` is still `def handler(payload)` (hatchet.py:224) | **CONFIRMED** (both the doc surface and the tree mismatch) |
| `AdminClient` removed; use `runs.create` / `Workflow.run` / `Standalone.run` | Official V1 SDK Improvements page: "The `AdminClient` has been removed… you can use `hatchet.runs.create`. This replaces the old `hatchet.admin.run_workflow`"; tree `_real_submit_workflow_run` still calls `runs.admin_client().run_workflow(name, json.dumps(input))` (hatchet.py:118-137) | **CONFIRMED** |
| Split topology service names `hatchet-engine` / `hatchet-dashboard` | Official Docker Compose deployment page (fetched today): services are exactly `hatchet-engine` (gRPC) and `hatchet-dashboard`; migrate/admin images run as `migration` / `setup-config` services | **CONFIRMED for engine+dashboard names** — with a port nuance, see §2.2 |
| API process never imports `hatchet_sdk` at module level | `cli.py:40` lazy-imports via `importlib.import_module`; `capability.py:53` uses `find_spec`; `hatchet.py` has no top-level SDK import; `app.py` imports neither | **CONFIRMED** — "no API startup cost" holds |
| Debugger integration accurate (4 items) | Items 1 (Dockerfile `pip install .` at :32 vs pyproject `worker` extra :79-81), 3 (image-path repair target compose.yaml:104 + hatchet.py:56), 4 (env fixes in the working tree) | **ACCURATE** |
| Debugger item 2: "`_derive_status` already folds stage states and returns RUNNING until all complete" | `_derive_status` (jobs.py:313-323) does fold stage states — **but returns PENDING, not RUNNING, when `states` is empty** (line 316-317) | **NOT ACCURATE as claimed — see §2.1** |

### 1. Assessment of the T2 findings against the T3 refinement

- **A-1 (HIGH — gate weakening is the uncommitted working tree): PARTIALLY RESOLVED.** T3 A-1
  correctly names the mechanism (remove `UMD_VALIDATE_LIVE_WORKER`, unconditional full-stack boot +
  unconditional readiness in the same commit). I verified the working-tree diff matches the T3
  description exactly (the opt-in flag, the `db api` default boot, the `if:` on the readiness gate,
  and the ffmpeg/PGDG installs — the installs are real fixes and must stay). What is NOT resolved:
  the "one commit" guarantee is an execution promise, not a design property, and the working tree
  contains unrelated uncommitted changes (`deploy/pins/asr-runtime.md`, `src/umd/audio/pipeline.py`,
  `tests/test_asr_faster_whisper.py`, `tests/test_capability_transitions.py`, `docs/limitations.md`,
  `src/umd/jobs/production.py`, plus 10+ churning `artifacts/logs/*.jsonl`) — a naive `git add -A`
  violates C8's separation of streams and makes the commit un-reviewable. The flip also immediately
  hits an unaddressed blocker: the docker-e2e job's `UMD_HATCHET_TOKEN=${UMD_HATCHET_TOKEN:-umd-ci-token}`
  is not a JWT and can never register (§3, risk 1).
- **A-2 (HIGH — durable-backend release-evidence bypass): PARTIALLY RESOLVED in design.** T3's
  fail-closed default (`ProductionDAGRunner`, durable backend can never report `active`, E2E
  hard-asserts the live path) is the right shape and closes the LaunchDarkly/tianpan fallback hole.
  The residual gap is that the E2E's own async assertion ("observes `queued` stage states / RUNNING")
  is unachievable against the current code with `ProductionDAGRunner` — see §2.1. Nothing in T3
  specifies the code change that makes "submit leaves the job RUNNING" true.
- **A-3 (HIGH — shape tests cannot reach the stack): PARTIALLY RESOLVED.** The in-network
  test-runner direction is correct and matches the official split compose network + handoff §8
  "same stack". But the T3's exact env contract breaks against the current test code (two concrete
  bugs, §2.2), and the test-runner recipe is underspecified (no pytest/dev extra, no tests dir, no
  media tooling — §2.3).
- **A-4 (MEDIUM — probe with hysteresis): RESOLVED in design.** Cached background probe,
  failure/success thresholds, gRPC-surface probing, non-blocking request path — matches the
  Kubernetes probe hysteresis literature. Deployment surface is PROVISIONAL: the API container needs
  `UMD_HATCHET_*` env and the SDK (covered by the shared-image decision), but the compose api service
  env does not yet carry those vars and the exact gRPC admin call is unmeasured until the live engine.
- **B-1 (HIGH — trigger-level path filters on a required gate): RESOLVED.** T3 B-1 mandates no
  trigger-level path filter, an always-running gate job that fails on skip, and inside-job filtering
  only as a cost response — consistent with GitHub's troubleshooting docs and the Venice
  `actions/runner#2566` pattern I re-checked. B is correctly deferred until A is green.
- **B-3 (LOW-MEDIUM — duplicate stack boots): RESOLVED** (shared build cache; operational).
- **C-1 (MEDIUM-HIGH — allow-failure corrosion): RESOLVED, stronger than required.** No
  `allow-failure`/`continue-on-error` anywhere on the live path on main; no green-with-warning
  posture survives.
- **C-2 (MEDIUM — manifest inspect ≠ pullability): RESOLVED** (tripwire only; compose-up + live run
  is the evidence — T3 honors this).
- **C-3 (LOW — `pip index` probe): RESOLVED** (dropped; static pin-agreement test covers the line).
- **§5 SDK-surface (HIGH): RESOLVED as a budgeted first-live-run item.** The two-arg handler and the
  removed AdminClient / `runs.create` / `Workflow.run` surface are now confirmed against official
  docs (table §0). T3 correctly does not claim the tree is right and budgets the fix cycle.
- **D rejection: RESOLVED.** T3's documented rejection matches my D-1/D-2 and the official lite/split
  docs; D stays dead as a release-evidence surface.

### 2. What still doesn't work

**2.1 The async-status reconciliation claim is false against the current code (HIGH).**
`JobService.submit` (jobs.py:90-116) sets RUNNING, calls `run_graph`, then `_refresh_status`
(jobs.py:309-310) → `status()` → `_derive_status`. With `ProductionDAGRunner`, `run_graph`
(→ `submit_workflow_runs`, runner.py:202-260) submits the runs and returns `queued` events but
**never records any stage state in the store** (no `store.record_stage` call — contrast
`DurableDAGRunner.run_graph`, runner.py:147-150, which observes every stage). So immediately after
submit the store has zero stage states, `_derive_status` hits `if not states: return PENDING`
(jobs.py:316-317), and `_refresh_status` **overwrites RUNNING back to PENDING**. The T3 §4.2(a)
assertion — "submit leaving the job RUNNING with queued stage states… `_derive_status` already folds
stage states and returns RUNNING until all are complete" — is only true given states exist; the
asynchronous path produces none until the first worker callback commits a `stage_run` row. The
boundary E2E's "observes queued/RUNNING" assertion therefore fails against the refined design as
specified. Fix (unspecified in T3): record `queued` StageState rows at submission (in
`submit_workflow_runs` or `JobService`), or skip `_refresh_status` for async runners and let the
E2E accept PENDING→RUNNING→COMPLETE. The same flip breaks `retry` (jobs.py:188) and `rerun_stage`
(jobs.py:213-220) status after scheduling.

**2.2 The A-3 in-network env contract has two concrete connection bugs (HIGH).**
(a) `_real_client()` (tests/test_hatchet_live.py:291-310) treats `UMD_HATCHET_CLIENT_HOST_PORT` as a
bare PORT appended to the server-URL hostname: `port = os.environ.get("UMD_HATCHET_CLIENT_HOST_PORT",
"7070"); host_port=f"{host}:{port}"`. T3 A-3 sets `UMD_HATCHET_SERVER_URL=http://hatchet-dashboard:8080`
AND `UMD_HATCHET_CLIENT_HOST_PORT=hatchet-engine:7070` → host_port becomes
`hatchet-dashboard:hatchet-engine:7070` — malformed. The correct values under the current test code
are server URL host = `hatchet-engine` with port override `7070`; or the test's host_port derivation
must itself be fixed (not specified). Note the SDK-native `HATCHET_CLIENT_HOST_PORT=hatchet-engine:7070`
works for the WORKER container (cli.py:104-106 leaves it to the SDK env), so the split exists only in
the test path.
(b) The dashboard's in-network port is 80, not 8080. The official split compose maps `8080:80`
(host 8080 → container 80); the engine maps `7077:7070` (container 7070 gRPC — T3's
`hatchet-engine:7070` is correct). `http://hatchet-dashboard:8080` from inside the network only
works if UMD's rebuilt compose redefines the dashboard's container port (e.g. `SERVER_HTTP_PORT`),
which T3 does not specify. PROVISIONAL, but the default (official) compose contradicts the T3 URL.

**2.3 The test-runner container recipe is incomplete (MEDIUM-HIGH).** "Same API image, worker extra
installed" is insufficient to run pytest: the Dockerfile installs `pip install .` (base deps only;
pytest lives in the `dev` extra, pyproject:83-90) and copies only `pyproject.toml`, `alembic.ini`,
`migrations`, `src` — **no `tests/` directory**. The one-shot test container needs `.[dev,worker]`
(or an explicit test stage), a way to see `tests/` (bind-mount or image copy), the `umd_db`/conftest
fixtures against `db:5432` with migrations applied, an OCFL writable volume, and — because the
compose worker executes the REAL production registry for these jobs — enough media tooling for every
stage in `STAGE_ORDER` to reach COMPLETE. `test_live_hatchet_retry_and_quarantine_single_authoritative_completion`
polls for `StageCompleted count == len(STAGE_ORDER)`; a container without ffmpeg/sandbox tooling
will quarantine media stages and fail that assertion. The debugger's "container runtime tool gap"
(item 5) is only half-addressed: the SDK packaging is decided, the ffmpeg question is not.

**2.4 The single-image `pip install .[worker]` decision has real downsides (MEDIUM).** It bakes the
CANDIDATE-pin SDK (and grpcio + transitive deps) into EVERY image build — API image bloat,
widened supply-chain surface, and a subtle pin-promotion hazard: a reader may see the SDK in the base
image and conclude the pin is validated. The C4 note must stay explicit that installing ≠ promoting.
The alternative (multi-target Dockerfile `worker-image` stage) keeps the candidate out of the API
image but then the A-4 probe loses its SDK; the single-image choice is defensible, just not free.

**2.5 The "one commit" ordering is achievable only with explicit path scoping (MEDIUM).** Verified
via `git status`/`git diff`: the working tree mixes the CI-repair stream (validation.yml,
pyproject.toml, conftest.py) with unrelated changes (ASR pins, audio pipeline, capability-transition
tests, docs/limitations.md) and 10+ agent log files that churn on every turn. The single commit must
be assembled with `git add <paths>` — and the commit must also not omit any of the interdependent
pieces (runner wiring, compose split rebuild, Dockerfile change, probe, SDK-surface fixes, gate
flip), or the pushed run fails for a missing-part reason. This is an execution risk, not a design
flaw; it just means the T3's guarantee is not yet realized.

### 3. Risks that persist (ranked)

- **RISK 1 (HIGH — currently unaddressed, guaranteed first-run failure): real API-token creation is
  missing.** The docker-e2e job still sets `UMD_HATCHET_TOKEN=${UMD_HATCHET_TOKEN:-umd-ci-token}`;
  the log's own known-SDK facts state the token must be a valid JWT (`ey`-prefix) and the placeholder
  "can never register" (log lines 143-144). The refined A never specifies how a real token is created
  against the live stack (`hatchet-admin token create --config … --tenant-id …` per the official
  compose docs, or dashboard-issued). The official docs also warn that changing the gRPC broadcast
  address/server URL requires re-issuing the token. Trigger: first hosted run with the flip on — the
  worker readiness gate fails at registration, the shape tests fail at `_real_client()` connection,
  and the E2E skips (no active capability). Why here: this is precisely the "first live run fails at
  connection, not at the application" class from T2 §7, and it is the SAME class the T3 claims to
  have fixed via A-3. Mitigation needed (absent): a token-creation step sequenced after
  setup-config/config-gen completes, with the tenant ID discovered from the live config.
- **RISK 2 (HIGH): the A-3 mechanism as written cannot connect** (§2.2a/b). Trigger: enabling the
  in-network shape tests with the T3's exact env values — malformed gRPC host_port and a dashboard
  port that does not listen inside the network. Why here: the shape tests are the R4 release
  evidence; connection failure at the SDK boundary is the exact untested class the CANDIDATE pin
  status exists to observe. Mitigation: fix `_real_client` host_port parsing or set
  `UMD_HATCHET_SERVER_URL=http://hatchet-engine:…` + port `7070`; confirm the dashboard container
  port in the rebuilt compose; re-issue tokens after the broadcast address is set.
- **RISK 3 (HIGH): the boundary E2E's async assertion is unsatisfiable as specified** (§2.1).
  Trigger: first hosted run with the production wiring — the API returns PENDING (not RUNNING) right
  after submit, and the E2E's "queued stage states / RUNNING" observation fails or must be loosened
  (loosening is exactly what R4 forbids). Why here: the E2E is the primary live release evidence
  (C5). Mitigation: specify the queued-state recording (or the PENDING-tolerant polling contract)
  before implementation.
- **RISK 4 (MEDIUM): test-runner/compose-worker media capability is unproven** (§2.3). Trigger: any
  shape-test job that reaches a media stage inside a container without ffmpeg/sandbox tooling →
  quarantine → `StageCompleted count == len(STAGE_ORDER)` fails. Why here: Task.md §26/§40 items
  5-8 require real representative modality decomposition, and the docker-e2e job is where that must
  be proven in the container. Mitigation: verify the worker image can complete every stage in
  `STAGE_ORDER` (add ffmpeg + sandbox profile or route media stages through the sandbox-runner
  service) before treating shape-test green as release evidence.
- **RISK 5 (MEDIUM): the split-topology env contract is still PROVISIONAL and conflicts in one
  detail with C7.** The official split compose does not pass `SERVER_AUTH_COOKIE_SECRET` /
  `SERVER_ENCRYPTION_MASTER_KEY` to config-gen at all (secrets are generated into the config); UMD's
  compose requires both under `${VAR:?}` (C7). If v0.105.2's config-gen does not consume those vars
  in that form, C7's interpolation is preserved mechanically but the vars no longer gate the server's
  auth — a semantic weakening no one intends. T3 flags this PROVISIONAL; the plan must verify the
  exact config-gen env contract and keep the Compose-config test meaningful, not just present.
- **RISK 6 (LOW): single-commit hygiene** (§2.5) — unrelated working-tree changes and log churn leak
  into the release commit, violating C8. Mitigation: explicit `git add <paths>` and a pre-commit diff
  review.

### 4. Newly questionable items introduced by T3

1. **`hatchet-dashboard:8080` in the in-network URLs** — official compose container port is 80
   (§2.2b). PROVISIONAL and likely wrong as written.
2. **`UMD_HATCHET_CLIENT_HOST_PORT=hatchet-engine:7070`** — mis-parsed by the test's `_real_client()`
   (§2.2a). The same env value is correct for the worker container (SDK-native prefix) but not for
   the test, which uses the `UMD_`-prefixed name as a bare port.
3. **`pip install .[worker]` in the shared image** — CANDIDATE-pin blast radius grows to every image
   build; pin-promotion confusion risk (§2.4). Not a C4 violation, but the C4 note must be restated at
   the Dockerfile, not only in runtime.txt.
4. **The boundary E2E assertion "the reported `server_image` equals the pinned sub-path image"** —
   requires `hatchet.py:56` to change in the same commit; correct, but it makes the E2E depend on the
   repair commit's compose/env values, so the E2E and the compose change must be validated together or
   the assertion misleads.

### 5. What still needs human judgment

- **The token-creation workflow** (RISK 1) — whether to issue via `hatchet-admin token create` after
  config-gen or via the dashboard, and how to discover the tenant ID in CI, is an operational decision
  the evidence cannot fully settle.
- **Queued-state recording** (RISK 3) — whether to persist `queued` StageState rows (new store
  writes on every submission) or to make the E2E PENDING-tolerant and skip `_refresh_status` for
  async runners. The first option is more honest but touches the stage-state model; the second is
  cheaper but must not become a weakened assertion. Human judgment needed on which contract the job
  lifecycle should publish.
- **Whether the compose-worker media capability must be proven in the same first run** (RISK 4) or
  whether media-stage quarantine for shape-test jobs is acceptable as long as the boundary E2E uses
  text kinds only. This is a scope call against Task.md §40 items 5-8.

### Bottom line

**A-refined (with C folded in, B deferred) is the right structure and every T2 finding received a
good-faith, mostly verified response — but as written it is NOT sufficient to restore the R4 release
gate.** Three gaps guarantee a failed first hosted run or an unsatisfiable gate: (1) no real
API-token creation step (placeholder JWT cannot register); (2) the A-3 in-network env contract
mis-parses the gRPC host_port and points at the wrong dashboard port; (3) the async-status
reconciliation claim is false against the current code — `ProductionDAGRunner` submission leaves the
job PENDING, not RUNNING-with-queued-stages, so the boundary E2E's core assertion cannot pass as
specified. The **single highest-risk item before a first hosted run** is the end-to-end live wiring
chain: real token creation → correct gRPC `host_port` from the test/worker → engine reachable on the
compose network. If that chain is not specified before the one commit lands, the first hosted run
will fail at the connection layer again — the same failure class the refinement set out to eliminate.

### 6. Addendum — second T4 critique pass (obligation-level concerns and topology-proof list)

*Sections 0-5 above are the first T4 pass (tree-level verification: the
`_derive_status` PENDING bug, `_real_client` host_port parsing, dashboard
container-port nuance, test-runner recipe, single-commit hygiene). This
addendum is the second T4 pass by the same role; it frames the same material as
implementation obligations (SC-1..SC-7) and names the exact live-topology proofs
R10 requires. Both passes are T4 (rnd-counter-ideator). No content from either
draft was deleted.*

*(rnd-counter-ideator, Turn 4 — second critique pass over the T3 Refined
Approaches. I verified each refinement against the actual tree (hatchet.py,
capability.py, runner.py, app.py, cli.py, validation.yml, compose/Dockerfile)
and the web checks dated 2026-08-28. Product-repair vs CI-remediation
distinction is explicit per R10/C8. No section of T3 was deleted or regressed.)*

### 6.1 What T3 genuinely resolved (second T4 pass)

| T2 finding | T3 resolution | Verdict |
|---|---|---|
| A-1 gate weakening is the uncommitted working tree | Same-commit flip + no user-settable flag | **RESOLVED** (ordering constraint is now explicit) |
| A-2 durable-backend release-evidence bypass | Default `ProductionDAGRunner`, durable can never report `active`, E2E hard-asserts live backend | **RESOLVED** at design level; the E2E hard-assert is only as strong as the fail-on-skip mechanism (SC-5 below) |
| A-3 live shape tests cannot reach the stack from host | In-stack test-runner container on the compose network | **RESOLVED** with two precedents (gramps-mcp 071e3f6, Compose Tip #52) + pytest-docker |
| A-4 probe flapping / wrong surface | Cached background probe, hysteresis, gRPC admin surface | **RESOLVED** at design level; exact probe call still unspecified (SC-6) |
| C-1 allow-failure corrosion | No `allow-failure`/`continue-on-error` on the live path on main | **RESOLVED** |
| C-2 manifest inspect ≠ pullability | Tripwire only; compose-up + live run is the evidence | **RESOLVED** |
| D-1/D-2 topology skew | D formally REJECTED with four documented reasons | **RESOLVED** |
| §5 SDK v1 surface | Confirmed against official docs (two-arg handler; `Workflow.run`/`runs.create`) | **PARTIALLY RESOLVED** — documented, but NOT yet aligned in the tree (SC-1) |
| Debugger additions (worker packaging, async reconciliation, image path) | Integrated: `[worker]` extra decision, no-fabricated-COMPLETE contract, 4 sub-paths verified 200 | **RESOLVED** |

T3 also closed T2's open pagination gap: all four split sub-path repos return
HTTP 200 for the v0.105.2 manifest (direct GHCR manifest HEAD, 2026-08-28) while
the top-level path returns 403 — the exact failure class of run 33164294061 is
now attributed to the wrong image path, not to a private/tag/auth cause.

### 6.2 Surviving obligations (unresolved after T3: SC-1..SC-7)

**SC-1 (HIGH, product stream) — the two documented SDK v1 surfaces are still
un-aligned in the tree.** T3 validated the v1 contract but did not commit to
changing the code before the first live run:
- `src/umd/jobs/hatchet.py:224` `_make_handler` builds a **one-argument**
  `handler(payload)` that indexes `payload["input"]["manifest"]`; the v1
  migration guide (docs.hatchet.run/v1/migrating/migration-guide-python,
  checked 2026-08-28) documents a **two-argument** `(input, ctx)` signature
  with Pydantic-typed input. First live dispatch will fail as a poll timeout
  (handler crash), not a clean error — exactly T2 §5(a).
- `src/umd/jobs/hatchet.py:118-137` `_real_submit_workflow_run` still submits
  via `runs.admin_client().run_workflow(name, json.dumps(input))`. T3 validated
  that v1 removed the exported AdminClient and offers `Workflow.run(input)` /
  `Standalone.run(input)` / `hatchet.runs.create` with a JSON-serializable
  mapping. Whether `RunsClient.admin_client()` still exists as an internal
  accessor on 1.38.1 is **unverified** (SDK source not inspected); the tree
  code asserts it. This is a load-bearing uncertainty for every approach's
  submission path.
- **My position:** both surfaces should be **pre-aligned now** — the docs are
  authoritative and the change is small; the first-live-run cycle should be
  reserved for observation of *namespacing* (Hatchet #2832) and *host_port
  routing*, not for rediscovering documented API shapes. T3's "fix as it
  surfaces" posture costs at least one extra hosted-run cycle and is the
  weaker plan when the docs are clear. This becomes an explicit implementation
  obligation with a surface-contract unit test (see T7 R-P1).

**SC-2 (HIGH, CI stream) — live-worker token provisioning is unspecified.** The
skill/grounding facts are binding: `umd-ci-token` (validation.yml default) is
NOT a JWT and can never register (`ClientConfig` raises on non-JWT,
docs.hatchet.run checked 2026-08-28); `_real_client()` (test_hatchet_live.py:305-309)
requires `UMD_HATCHET_TOKEN`; the compose worker service env has no
`UMD_HATCHET_*` entries. T3's A-3 specifies the *test-runner* env but never
says how the **compose worker service** obtains a valid JWT in CI. For the
split topology the documented route is
`hatchet-admin token create --config /hatchet/config --tenant-id <uuid>`
(docs.hatchet.run/self-hosting/docker-compose) — that is a boot-time step in
compose, not a pre-existing secret. Without this, the worker cannot register,
the gate fails at connection, and the first live run proves nothing about the
application.

**SC-3 (HIGH, CI stream) — no concrete compose split-topology spec exists.** The
current `hatchet` service (deploy/compose.yaml:101-111) matches NEITHER the
split NOR lite topology (no DATABASE_URL, no msgqueue, no config volume, no
ports, no migrate→admin→engine+dashboard ordering). T3 §4.3 says the service
"must be rebuilt to the official split topology" but does not enumerate the
service definitions, env vars, config volume, healthchecks, and boot order.
This is the highest-leverage concrete deliverable of the plan; leaving it as an
intent means the first hosted run boots a broken stack again.

**SC-4 (MEDIUM-HIGH, process) — R10's two-stream separation vs A-1's "ONE
commit" is unarticulated.** R10/C8 require the design/plans to explicitly
separate the product-implementation stream from the CI-environment-remediation
stream. A-refined's ordering guarantee says the gate flip, uncommitted fixes,
runner wiring, compose topology, packaging, and probe land in ONE commit
(log lines 694-697). These are reconcilable — separation at the plan/document
level, atomic landing at the commit level so a weakened gate is never the
committed state — but T3 never says so, and a downstream planner could read
"one commit" as "one undifferentiated stream" and violate R10. T5/T7 must
carry the split explicitly.

**SC-5 (MEDIUM, CI stream) — the "fail if the E2E was vacuously skipped"
mechanism is unmechanized.** `_require_production_path`
(tests/test_api_boundary_e2e.py:108-138) correctly keeps its honest skip, and
T3 requires the CI step to fail if the scenario was skipped — but pytest
returns exit 0 on skips (pytest-dev/pytest#1364, long-standing; no built-in
fail-on-skip). Options exist (pytest-error-for-skips; conftest hook that fails
`pytest.skip` on CI; post-run assertion on the JUnit/log; the Test Ratchet
action which fails when the skipped count rises, github.com/marketplace/actions/
test-ratchet) — but T3 names none. Without a chosen mechanism, the boundary
gate is a skip-away from being vacuous. **Product vs CI:** this is a CI-gate
mechanism (CI stream) enforcing a product-truth obligation (product stream).

**SC-6 (MEDIUM, product stream) — the capability probe's exact call and
integration point are unpinned.** A-4 specifies the gRPC admin surface with
hysteresis but not *which* call (e.g., a `runs.list(limit=1)` admin roundtrip
vs a workers/health RPC) nor where it lives (inside `CapabilityReporter` vs a
separate probe module with an injected client for testability). The probe must
prove gRPC **reachability only**, never execution (CONTRACTS.md:63). Also
unaddressed: the probe runs in the API process, so it needs `hatchet_sdk` in
the API image — the T3 §4.1 packaging decision covers this, but the probe
module design does not yet.

**SC-7 (MEDIUM, product stream) — retry ownership between Hatchet task retries
and `DurableStageExecutor` is undefined.** The tree already has a
`RetryPolicy`/`RealBackoff` inside `DurableStageExecutor` (quarantine for
deterministic failures, bounded backoff for transient — CONTRACTS.md:60-63).
Hatchet additionally offers task-level retries with exponential backoff and a
`NonRetryable` escape (docs.hatchet.run/v1/error-handling/retry-policies,
checked 2026-08-28). If both layers retry, attempts amplify and quarantine rows
can duplicate. Who owns retry must be decided (T7 R-P2).

### 6.3 Topology/compatibility proof still required (exact items)

The following are the exact live Hatchet topology/compatibility proofs the plan
must name (R10). Each is a **first-live-run observation**, not a static claim:

1. **SDK 1.38.1 ↔ server v0.105.2 live pair (C4)** — real pull, registration,
   execution on the hosted stack; until then the pin stays CANDIDATE.
2. **Submission surface on the live pair** — whichever shape survives SC-1 must
   be observed succeeding (`Workflow.run`/`runs.create` on 1.38.1 against
   v0.105.2 engine gRPC).
3. **Worker/task name namespacing** on 1.38.1 — whether `umd-{stage}` registers
   and is matched by submitted runs (Hatchet #2832 class).
4. **gRPC `host_port` routing** — `hatchet-engine:7070` in-network reachability
   from the worker, test-runner, and probe with the JWT-derived broadcast
   address vs explicit override (cli.py:104-106).
5. **v0.105.2 env contract** — exact config-gen/engine variable names and forms
   (`SERVER_AUTH_COOKIE_SECRET` vs `SERVER_AUTH_COOKIE_SECRETS` plural,
   `SERVER_ENCRYPTION_MASTER_KEY` vs `..._MASTER_KEYSET`, `SERVER_MSGQUEUE_KIND
   =postgres` validity, dashboard port mapping) — PROVISIONAL until the image
   boots (T3 §6.3 already flags this; SC-3 makes it a named obligation).
6. **Token minting path** — `hatchet-admin token create` against the v0.105.2
   config output (SC-2).

### 6.4 Summary (second T4 pass)

- **Surviving approaches:** A-refined remains the primary (SC-1..SC-7 are
  obligations on it, not fatal flaws); B remains the post-green complement.
  No approach is newly dead.
- **The single most important unresolved item:** the SDK submission surface
  (SC-1) — every live path depends on it, and the code currently asserts an
  unverified accessor shape. Fix it ahead of the run with a surface-contract
  test; do not discover it in the run.
- **The second most important:** compose topology + token (SC-2/SC-3) — the
  CI stack cannot boot or register without them, and they are the entire
  CI-remediation stream.
- **Honest limitation:** T4 cannot verify that T3's four GHCR 200 checks are
  the same paths Docker will pull in the hosted runner; the preflight tripwire
  (C-2) exists precisely to catch any residual discrepancy at run time.

## Implementation Patterns

*(rnd-improver, Turn 5 — concrete implementation patterns for the surviving
approach (A-refined) plus the B complement. Each pattern names where it lands in
the tree, its evidence, and its validated key choices. Product-repair patterns
P1-P4/P6-P8 and CI-remediation patterns P5/P9-P11 are explicitly separated per
R10/C8. Web checks dated 2026-08-28; every library/version revalidated in §12.)*

### P1 (product) — Submission data flow: HTTP → `JobService.submit` → `ProductionDAGRunner` → Hatchet gRPC → worker callback

The end-to-end path the boundary E2E must observe asynchronously:

```
POST /v1/sources (multipart) / /v1/jobs (correct/invalidate)
  → JobService.submit (src/umd/application/jobs.py:90-116)
  → create job (PENDING→RUNNING) + runner.run_graph(...)
  → ProductionDAGRunner.run_graph (src/umd/jobs/runner.py:263-296)
  → submit_workflow_runs (runner.py:~205-260): one run per stage, payload =
    {job_id, source_id, dag_universe, manifest, causation_id?}, events = queued
  → _SDKSubmissionShim (src/umd/jobs/hatchet.py:140-158) → gRPC engine queue
  → worker callback (_make_handler, hatchet.py:224-282) → DurableStageExecutor.run
  → atomic stage_run row + StageCompleted (CONTRACTS.md:60-63)
  → JobService.status / _derive_status folds stage states → terminal COMPLETE
    only from committed rows (never fabricated; debugger §3.4)
```

- **Evidence:** the queue of `queued` StageRunEvents returned by submit; the
  stage_run/StageCompleted rows committed by callbacks; `/v1/jobs/{id}` polling.
- **Key choice (validated):** one workflow run per stage (not one workflow per
  job) matches the tree's existing `build_hatchet_workflows`
  (hatchet.py:179-201) and Hatchet's DAG semantics where `parents`/`depends_on`
  express lineage (docs.hatchet.run/v1/directed-acyclic-graphs, checked
  2026-08-28). Hatchet is at-least-once: "a task can run more than once, so
  your task code should be idempotent" (docs.hatchet.run/v1/architecture-and-guarantees)
  — which is exactly why the idempotency-key authority (P2) is load-bearing.
- **SC-1 obligation:** align the submission surface to the v1 shape
  (`Workflow.run(input)` / `runs.create` with JSON-serializable mapping) and
  assert it with a surface-contract unit test (T7 R-P1).

### P2 (product) — Worker callback + idempotency authority (claim-before-side-effect)

`_make_handler` (hatchet.py:224-282) is the callback Hatchet invokes. Pattern:

1. Construct `StageManifest` from the payload; **align to the v1 two-argument
   `(input, ctx)` signature** (SC-1).
2. Read the persisted job status (cancel propagation — a cancelled job returns a
   replayed `cancelled` record, no row, no work).
3. Resolve **committed** upstream evidence refs deterministically
   (`store.committed_evidence_refs`) so the idempotency key is stable across
   retries (dedupe on replay).
4. `executor.run(manifest, work)` — claim via UNIQUE `idempotency_key`
   (`StageRunClaim`), bounded backoff for transient, quarantine for
   deterministic (CONTRACTS.md:60-63); NEVER mark complete outside the executor.
5. **Retry ownership (SC-7):** the executor owns retry/quarantine; Hatchet
   task-level retries stay at 0 (or 1 with `NonRetryable` raised for
   deterministic failures) so attempts are not amplified. Hatchet's own docs
   demand idempotent task bodies before enabling retries
   (docs.hatchet.run/v1/error-handling/retry-policies) — the executor already
   provides that idempotency, so a second retry layer adds amplification
   without benefit.
6. Timeouts: use Hatchet execution/scheduling timeouts as backstops only
   (`execution_timeout` default 60s, `schedule_timeout` default 5m —
   docs.hatchet.run/v1/error-handling/timeouts); stage work that legitimately
   runs longer must use `ctx.refreshTimeout` or a task-level timeout matching
   the longest stage, not a silent default cut.

### P3 (product) — Status reconciliation (state management)

- `submit` leaves the job RUNNING with queued stage states; `_derive_status`
  (jobs.py:118-123) folds stage states and returns RUNNING until all complete.
- Terminal COMPLETE arrives only from callback-committed `stage_run` rows.
- Polling consumers (`_poll_until`, test_hatchet_live.py:313-331) wait on
  Postgres for terminal state and dump evidence on timeout — the same contract
  the boundary E2E uses.
- **Evidence:** Hatchet persists execution state in Postgres and performs state
  transitions transactionally (architecture-and-guarantees) — the engine is the
  durable queue; UMD's Postgres rows are the authoritative completion record.

### P4 (product) — Capability probe (background, cached, hysteresis, gRPC surface)

- New probe module (or method on `CapabilityReporter`) with an **injected
  client** for testability; background task refreshes a cached boolean.
- Hysteresis: `failureThreshold ≥ 2` consecutive failures to drop from active,
  `successThreshold ≥ 2` to recover (Kubernetes probe semantics —
  kubernetes.io/docs/concepts/workloads/pods/probes/; oneuptime k8s guide
  2026-01-08; decodeops 2026-05-06 — all cited in T3 §5).
- Probes the **gRPC admin surface the SDK uses** (`host_port`
  = `hatchet-engine:7070` in-network), a reachability-only call (SC-6); never
  claims execution.
- Status mapping (CONTRACTS.md:63): no SDK → `gated`; SDK + no env →
  `configured-but-unavailable`; SDK + env + probe pass + `ProductionDAGRunner`
  wired → `active`; durable backend → never `active` (A-2).
- **Integration ordering (T7 R-P3):** the E2E runs only after the worker is
  registered AND the probe is warm.

### P5 (CI-remediation) — In-stack test execution (A-3 pattern)

- One-shot test-runner container on the compose network: `docker compose run
  --rm --no-deps` with the shared API image (`pip install .[worker]` — the
  packaging decision from T3 §4.1), env `UMD_HATCHET_SERVER_URL=
  http://hatchet-dashboard:8080`, `UMD_HATCHET_CLIENT_HOST_PORT=hatchet-engine:
  7070`, `UMD_TEST_POSTGRES=true`, `db:5432`.
- Precedents (cited in T3 §1 A-3): gramps-mcp commit 071e3f6 (tests inside the
  compose network), Compose Tip #52 (CI test environment), pytest-docker
  fixtures.
- The three `test_live_hatchet_*` shape tests and the boundary E2E run here —
  they submit via a real SDK client and poll Postgres; they never start their
  own worker loop (the compose worker owns execution).

### P6 (CI-remediation) — Gate topology (fail-closed, no skip-without-fail)

- **Gate polarity:** docker-e2e boots the full stack unconditionally
  (`--profile sandbox up -d --build` as at HEAD); no `UMD_VALIDATE_LIVE_WORKER`
  flag remains user-settable (A-1).
- **Fail-on-skip (SC-5):** choose ONE mechanism — recommended: a conftest hook
  in the E2E file that raises on `pytest.skip` when `GITHUB_ACTIONS=true`
  (pattern from pytest-dev/pytest#1364 — fail-on-CI-skip; the skip stays honest
  locally), with an explicit allowlist of named permitted skips (e.g., optional
  providers gated). Hardening later: Test Ratchet (github.com/marketplace/
  actions/test-ratchet) ratchets the whole-suite skip count.
- **Always-run gate job (B-1):** a `gate` job with `if: always()`,
  `needs: [docker-e2e]` that fails if the live job was skipped or failed
  (GitHub troubleshooting docs + Latchkey + actions/runner#2566, cited in T3
  §2).
- **Preflight tripwire (C-2):** `docker manifest inspect` on the pinned
  sub-path images before compose-up; tripwire only, never release evidence.
- Teardown stays `if: always()` + `continue-on-error` (never masks a real
  failure).

### P7 (CI-remediation) — Environment/package provisioning (the 14 postgres-job failures)

All retained from the verified working tree, landed in the same commit (A-1):
python-multipart 0.0.32 (pyproject, committed); ffmpeg + ffprobe install;
PGDG `noble-pgdg` + `postgresql-client-17` + `UMD_PG_BIN` (GITHUB_ENV);
`HATCHET_COOKIE_SECRET`/`HATCHET_MASTER_KEY` exported in unit/postgres jobs
(never weaken `${VAR:?}`, C7). These are environment defects (debugger H2/H3) —
**CI stream**, verified in T2 §0.

### P8 (CI-remediation) — Compose split-topology spec (SC-3)

Concrete service set for `deploy/compose.yaml` (all PROVISIONAL against the
v0.105.2 env contract until the image boots, T3 §6.3):

- `hatchet-migrate` (DATABASE_URL; runs first; must complete before admin).
- `hatchet-admin` config-gen (DATABASE_URL, msgqueue, auth secret forms;
  generates `/hatchet/config` + certs on a shared volume).
- `hatchet-engine` (gRPC `7070` in-network; `--config /hatchet/config`) +
  `hatchet-dashboard` (HTTP `8080`).
- `hatchet-worker` (UMD worker service): image with `[worker]` extra; env
  `UMD_HATCHET_SERVER_URL=http://hatchet-dashboard:8080`,
  `UMD_HATCHET_TOKEN=<minted JWT>`,
  `HATCHET_CLIENT_HOST_PORT=hatchet-engine:7070`; readiness line printed before
  blocking `worker.start()` (C6, cli.py pattern already in tree).
- Token minting (SC-2): `hatchet-admin token create --config /hatchet/config
  --tenant-id <uuid>` during compose boot or a CI step; export to the worker.
- **Postgres-only msgqueue:** `SERVER_MSGQUEUE_KIND=postgres` — Hatchet
  documents starting self-hosted with Postgres-only and adding RabbitMQ for
  throughput (architecture-and-guarantees) — avoids a RabbitMQ service in CI;
  marked PROVISIONAL until v0.105.2 boots.
- Port publishing for the host fallback path (A-3 fallback): engine 7070,
  dashboard 8080; the primary path is in-network so publishing is optional.

### P9 (product) — Worker packaging (decision from T3 §4.1)

Shared image installs the worker extra (`pip install .[worker]`); the API
process never imports `hatchet_sdk` at module level so there is no API startup
cost, and the P4 probe needs the SDK inside the API container. Does NOT promote
the CANDIDATE pin (C4).

### P10 (product) — Surface-contract tests (SC-1 enforcement)

Unit tests that mock the SDK client and assert:
1. Submission uses the v1 surface (`Workflow.run`/`runs.create` with a
   JSON-serializable mapping), not the removed `admin_client().run_workflow`.
2. The handler accepts `(input, ctx)` and builds the manifest from
   `input.manifest` (Pydantic model).
These run hermetic (no cluster) but lock the SDK contract so the first live run
observes namespacing/routing, not documented API shapes.

### P11 (CI-remediation) — Evidence capture and release summary

Keep the existing scripts: `wait-for-http.sh`, `wait-for-worker.sh` (greps
`worker ready: registered`), `capture-diagnostics.sh`, `record-release-summary.sh`;
add a machine-readable `live-worker-gate: PASS|FAIL` line to the summary
(DD pattern-enforcer approval requires it; a green checkmark must never
override a failed/missing machine-readable gate).

### 12. Technology validation summary (revalidated 2026-08-28)

| Choice | Source / check date | Result | Why best fit (not merely newest) |
|---|---|---|---|
| `hatchet-sdk==1.38.1` | PyPI + py/1.38.1 release (2026-08-25); SDK client docs — docs.hatchet.run/reference/python/client | Current line; `ClientConfig` env prefix `HATCHET_CLIENT_`; token MUST be valid JWT (ValueError otherwise) | Already the recorded candidate (C4); kept CANDIDATE until live pair proves |
| Server `v0.105.2` split sub-paths | GHCR manifest HEAD, all four sub-paths 200 (T3 §5) | Exact repair target | Split topology = deployed shape; lite rejected (D) |
| Task retries/timeouts at Hatchet layer | docs.hatchet.run/v1/error-handling/retry-policies + /timeouts (2026-08-28) | Task retries + exponential backoff + `NonRetryable`; execution timeout default 60s, schedule 5m; `refreshTimeout` | P2 retry-ownership decision basis |
| DAG parents/depends_on | docs.hatchet.run/v1/directed-acyclic-graphs (2026-08-28) | Parents list = lineage; `ctx.task_output` | P1 one-run-per-stage matches `STAGE_DEPENDENCIES` |
| At-least-once guarantee | docs.hatchet.run/v1/architecture-and-guarantees (2026-08-22) | Tasks can run more than once; idempotency required; Postgres durable store; Postgres-only start OK | P2 idempotency authority + P8 Postgres msgqueue basis |
| Fail-on-skip mechanism | pytest-dev/pytest#1364; pytest skip docs; Test Ratchet action (2026-08-28) | No built-in fail-on-skip; conftest CI-hook / plugin / ratchet patterns exist | P6 SC-5 mechanism basis; chosen: conftest hook scoped to E2E |
| `python-multipart==0.0.32` | T2 §0 registry evidence | Pin real; CI failure was missing package | P7, retained |
| ffmpeg / PGDG `postgresql-client-17` | T2 §0; runner-images migration | Correct fixes for the hosted runner | P7, retained |
| Action versions (checkout@v4, setup-python@v5, upload-artifact@v4) | T2 §0 | Valid, not defects | Keep; optional bump only, never in the A-1 commit |

## Pattern Risks

*(rnd-counter-improver, Turn 6 — adversarial review of the T5 implementation
patterns. Each risk names trigger conditions and whether they match our use
case, with cited evidence. Product vs CI stream is explicit. Web checks dated
2026-08-28.)*

### R-P1 (HIGH, product) — Submission-surface mismatch survives into the live run

The tree's `_real_submit_workflow_run` asserts `runs.admin_client().run_workflow`
(hatchet.py:130-137) and raises `HatchetNotConfiguredError` if the accessor
chain is absent. T5 P1 says "align to v1" but P10's surface-contract test only
locks the shape if someone writes it; until then the first live submit either
works (accessor still exists internally on 1.38.1) or fails with a 4xx /
`HatchetNotConfiguredError`. **Trigger:** any code path that submits before the
alignment. **Matches us:** yes — the boundary E2E is the first submit.
**Evidence tier:** T2 (official docs) — v1 removed the exported AdminClient
(v1-sdk-improvements); the internal accessor is unverified, so this is a real
fork in the road, not theatre.

### R-P2 (MEDIUM-HIGH, product) — Double-retry amplification between Hatchet task retries and the executor

P2 sets Hatchet retries to 0 (or 1 + `NonRetryable`), but nothing enforces it:
`build_hatchet_workflows`/`HatchetWorkerFactory.start` (hatchet.py:391-426)
currently registers tasks without retry configuration, and the v1 `task()`
decorator accepts `retries`. If a later change sets task retries > 0, a
deterministic failure is retried by Hatchet while the executor also retries →
amplified attempts and duplicate quarantine paths. **Trigger:** future config,
or an operator "helpfully" enabling retries. **Matches us:** latent, not
present. **Evidence tier:** T2 (Hatchet retry docs demand idempotency before
retries; the executor provides it, so amplification is the only effect).

### R-P3 (MEDIUM-HIGH, CI) — Poll-timeout flakiness on cold start

P3/P5 depend on `_poll_until` (default 120s) for first-boot observations:
engine boot → migrations → config-gen → engine up → worker registers →
callbacks execute → rows commit. On a hosted runner the first pull of four
sub-path images plus first compile can exceed 120s. **Trigger:** cold cache;
runner variation. **Matches us:** yes — this is the first-ever live run.
**Evidence tier:** T4 (runner-images cache note from T2 B-3: ubuntu-24.04
caches no docker base images). **Mitigation:** readiness ordering (worker
registered AND probe warm) before tests start; raise poll timeouts to 180s;
evidence dump on timeout already present.

### R-P4 (MEDIUM, product) — Probe surface drift: gRPC reachable ≠ engine executes

P4 probes gRPC reachability only. Risk: the probe flips `active` while the
engine is up but cannot execute (misconfigured msgqueue, worker-less queue,
DAG universe mismatch). **Trigger:** topology changes that leave gRPC up but
execution broken. **Matches us:** partially — the E2E hard-assert (A-2) is the
execution check, so the probe is correctly NOT the execution authority; the
risk is only that operators read `active` as "proven". **Evidence tier:** T3
(kube probe literature — readiness probes lie when they probe the wrong
surface). **Mitigation:** the /v1/capabilities schema must include the
observed reason/version and the E2E must still require real stage transitions.

### R-P5 (MEDIUM, CI) — In-stack test-runner container races/conflicts

P5 runs pytest via `docker compose run --rm --no-deps`. Risks: (a) exit-code
propagation through compose run; (b) the runner container and the worker share
the engine queue — the shape tests submit runs that the compose worker executes
(by design), but if a test also tried to start a worker loop, duplicate
registration/name collisions occur (they do not, per test_hatchet_live.py —
they only submit + poll); (c) `--no-deps` assumes the stack is already up —
ordering must be explicit; (d) service-name/network alias changes (P8) break
the env (`hatchet-engine`/`hatchet-dashboard` must be stable names).
**Trigger:** any of these mis-ordering or renaming events. **Matches us:** the
ordering is the real risk — the current workflow runs pytest from the HOST
(A-3 defect), so the containerized path is new.

### R-P6 (MEDIUM, CI) — Fail-on-skip mechanism false-positives on legitimate skips

P6's conftest hook raising on `pytest.skip` when `GITHUB_ACTIONS=true` will
also fire for **legitimate** named skips (optional providers configured-
unavailable, provider-gated capabilities — R6's honest status vocabulary).
**Trigger:** any test in the E2E file that skips for a non-production-path
reason. **Matches us:** yes — `test_api_boundary_guardrails.py` and the E2E
file contain capability-gated paths. **Evidence tier:** T3 (Test Ratchet docs —
ratchet the *count*, don't ban all skips; pytest #1364 — skip is legitimate
for expected constraints). **Mitigation:** allowlist of named permitted skips
scoped to the E2E run; the production-path skip is NOT on the allowlist.

### R-P7 (LOW-MEDIUM, CI) — Apt/runner drift in the provisioning step

P7 installs ffmpeg + PGDG client-17 via apt on ubuntu-latest. **Trigger:**
runner image major bumps (24.04 → 26.04) change package availability or
versions; PGDG key rotation. **Matches us:** the 24.04→22.04 migration already
bit the suite once (T2 §0). **Mitigation:** version-assert the tools in CI
(`ffmpeg -version`, `pg_dump --version` must report 17.x), pin the PGDG key;
accept apt-drift risk as LOW.

### R-P8 (HIGH, CI) — v0.105.2 env contract uncertainty compounds P8

P8's whole split-topology spec is PROVISIONAL: the exact config-gen/engine
variable names (`SERVER_AUTH_COOKIE_SECRET` vs plural `_SECRETS`,
`SERVER_ENCRYPTION_MASTER_KEY` vs `_MASTER_KEYSET`, `SERVER_MSGQUEUE_KIND=
postgres` validity, dashboard container port) are unverified until the image
boots. **Trigger:** the first compose-up with the spec. **Matches us:** this is
exactly the class of failure that produced the "matches NEITHER topology"
state. **Evidence tier:** T2/T3 (docs read; skill's explicit "must be read from
the v0.105.2 tag docs/compose, not current docs"). **Mitigation:** read the
v0.105.2 tag's compose/docs at plan time (not current docs); the preflight
tripwire catches image pull, not env contract — so budget a boot-fix cycle.

### R-P9 (MEDIUM, product) — Idempotency-key stability under evidence-ref resolution

P2 resolves committed upstream refs before `executor.run` to keep keys stable.
**Trigger:** if `committed_evidence_refs` ever reads non-committed rows
(in-progress upstream), the key changes across retries → duplicate execution.
**Matches us:** the code deliberately resolves committed-only rows
(hatchet.py:242-252); the duplicate-submission live test
(`test_live_hatchet_duplicate_and_restart_preserve_single_completion`)
guards this — but it has never run live. **Evidence tier:** T3 (design intent);
the live shape test is the arbiter.

### R-P10 (MEDIUM, product) — Worker readiness line vs real registration skew

P8 keeps the C6 readiness line printed BEFORE blocking `start()`. **Trigger:**
the line can print while registration later fails (bad token, namespacing,
engine unreachable) — `wait-for-worker.sh` greps the line, so the gate could
pass on a line, not on registration. **Matches us:** yes — this is the
documented P2-S3 compromise (start() blocks; print-before is the only signal
available pre-start). **Mitigation:** after `start()` begins, the shape tests
+ boundary E2E are the real registration/execution proof; the line alone never
closes the release gate (handoff §8). Keep the "(candidate...)" suffix (C6).

### Cross-pattern interactions

1. **P4 (probe) × P6 (fail-on-skip):** a warm-up race — probe not yet warm when
   the E2E starts — turns a legitimate cold-start into a hard E2E failure.
   Interaction rule: gate order = wait-for-worker (line) → probe warm
   (`/v1/capabilities` scheduler active, bounded retry) → E2E.
2. **P2 (executor retries) × P1 (at-least-once):** unstable keys (R-P9) would
   turn at-least-once into duplicate execution; P2's committed-only resolution
   is the guard.
3. **P5 (in-stack runner) × P8 (topology):** stable service names/aliases are a
   contract between the test env and the compose spec; renaming breaks the
   E2E silently.
4. **P8 (token) × P4 (probe) × P2 (registration):** token minting is a
   prerequisite for the probe AND worker registration AND submission; a
   non-JWT token fails all three at once (umd-ci-token class). Token
   provisioning is the least-redundant dependency in the whole design.
5. **P6 (gate job) × R4:** the always-run gate job only helps if branch
   protection requires it; CI-side gating without branch-protection wiring is
   advisory (documented limitation).

### Verdict on T5 patterns

P1, P2, P3, P5, P6, P7, P9, P10, P11 survive with the mitigations above.
**P4 and P8 are the two patterns that cannot be fully de-risked statically** —
the probe call and the v0.105.2 env contract are first-boot observations. The
plan must budget a boot-fix cycle and must not present a green run that skips
the live gate as evidence (R4).

## Final Patterns

*(rnd-improver, Turn 7 — refinement of the T5 patterns against the T6 Pattern
Risks. Every risk is addressed with a mitigation or an explicit acknowledged
limitation; affected technologies revalidated in §F. Product vs CI stream stays
explicit.)*

### F1 — Pre-aligned submission surface with surface-contract tests (addresses R-P1, SC-1)

**Mitigation:** adopt the v1 surface NOW, before the first live run:
- `_real_submit_workflow_run` (hatchet.py:118-137) switches to
  `Workflow.run(input)` / `hatchet.runs.create` with a JSON-serializable
  mapping; the `_SDKSubmissionShim` (hatchet.py:140-158) keeps intercepting
  `submit_workflow_run` so the shared `submit_workflow_runs` path stays
  unchanged.
- `_make_handler` (hatchet.py:224-282) becomes `handler(input, ctx)` building
  the manifest from the Pydantic-typed input (two-arg v1 signature).
- **P10 becomes mandatory, not optional:** a hermetic unit test mocking the SDK
  client asserts (a) submission reaches `Workflow.run`/`runs.create` with a
  mapping input, (b) the handler accepts two args. This locks the documented
  contract so the first live run observes only namespacing/routing (Hatchet
  #2832 class) — the residual unknowns.
- **Acknowledged limitation:** if 1.38.1's internal accessor chain still
  exists and `Workflow.run` differs in an unverifiable detail, the surface test
  fails fast in hermetic CI (before any live run) — cheaper than a hosted
  discovery. Evidence: v1-sdk-improvements + migration guide (T2/T3 validated).

### F2 — Retry ownership: single authority (addresses R-P2, SC-7)

**Mitigation:** the executor (`RetryPolicy`/`RealBackoff`) is the ONLY retry
authority. Hatchet task `retries=0` is set explicitly in
`HatchetWorkerFactory.start` registration (hatchet.py:391-426) so future
configuration cannot silently add a second layer; deterministic failures raise
`NonRetryable` at the Hatchet boundary so even an operator-enabled task retry
bypasses. Evidence: Hatchet retry docs (idempotency + NonRetryable, checked
2026-08-28); CONTRACTS.md:60-63.

### F3 — Readiness ordering and poll budgets (addresses R-P3)

**Mitigation:** explicit gate order in docker-e2e:
1. `wait-for-http.sh` on `/v1/ready` (API up).
2. `wait-for-worker.sh` (worker line — registration signal only, R-P10 caveat).
3. Probe-warm wait: bounded retry (≤60s) on `/v1/capabilities` until
   `scheduler.status == active` (P4 hysteresis already damps flapping).
4. Run the boundary E2E + shape tests.
Poll timeouts raised from 120s to 180s in `_poll_until` for cold-start
tolerance; evidence dump on timeout retained.

### F4 — Probe contract pinned (addresses R-P4, SC-6)

**Mitigation:** probe = a single reachability-only gRPC admin call (e.g.,
`runs.list(limit=1)`) via an injected client in a new `CapabilityProbe` module;
`CapabilityReporter` consumes the cached result. The /v1/capabilities schema
carries status + reason + observed sdk/server versions; the E2E still requires
real stage transitions (A-2 hard-assert) — the probe never claims execution.
**Acknowledged limitation:** a reachable-but-broken engine can still report
active; the E2E is the execution authority, and that separation is intentional
and documented in the capabilities schema.

### F5 — In-stack runner made ordering-safe (addresses R-P5)

**Mitigation:** a single `docker compose run --rm --no-deps` step AFTER the
stack is up and the worker is ready; service names/aliases
(`hatchet-engine`, `hatchet-dashboard`, `db`) are declared stable contract in
the compose spec (P8/F8) and asserted by the preflight; the runner container
uses the same shared image (`[worker]` extra) so the SDK and probes match the
worker exactly; tests submit + poll only (never start their own worker loop —
already true in test_hatchet_live.py). Exit-code propagation is native to
`docker compose run`; the step fails on any non-zero test exit.

### F6 — Fail-on-skip with a named allowlist (addresses R-P6, SC-5)

**Mitigation:** conftest hook scoped to the E2E run: when `GITHUB_ACTIONS=true`,
`pytest.skip` raises unless the reason matches an explicit allowlist of named
permitted skips (optional-provider configured-unavailable/gated). The
production-path skip (`_require_production_path`) is NOT on the allowlist →
vacuous green is impossible in CI while remaining honest locally.
**Hardening (later, optional):** Test Ratchet to ratchet the whole-suite skip
count (baseline today = 17 in the postgres job — set the baseline, only
ratchet down). Evidence: pytest-dev#1364; Test Ratchet docs (checked
2026-08-28).

### F7 — Provisioning hardening (addresses R-P7)

**Mitigation:** keep ffmpeg/ffprobe + PGDG `postgresql-client-17` installs;
add version assertions in CI (`ffmpeg -version`; `pg_dump --version` == 17.x)
so runner drift fails loudly; pin the PGDG key with a sha256 check;
`--no-install-recommends` retained. **Acknowledged limitation:** apt-drift
across future runner majors remains a LOW accepted risk, mitigated by the
version assertions.

### F8 — Compose split topology with env-contract boot cycle (addresses R-P8, SC-2, SC-3)

**Mitigation:**
- At plan time, read the **v0.105.2 tag's** compose/docs (not current docs) to
  pin the exact env surface; record the actual variable names as a plan
  artifact before implementation (this converts the PROVISIONAL item into a
  checked fact or an explicit PROVISIONAL note with the exact unknown named).
- Compose spec: `hatchet-migrate` → `hatchet-admin` (config-gen) →
  `hatchet-engine` + `hatchet-dashboard`, shared `/hatchet/config` volume,
  `depends_on` ordering + healthchecks; Postgres-only msgqueue
  (`SERVER_MSGQUEUE_KIND=postgres`) unless the v0.105.2 tag docs say otherwise.
- Token (SC-2): mint via `hatchet-admin token create --config /hatchet/config
  --tenant-id <uuid>` in a boot step; export to the worker env; the token is
  per-run (never committed, never a GitHub secret dependency).
- Worker service env gains `UMD_HATCHET_SERVER_URL`,
  `UMD_HATCHET_TOKEN`, `HATCHET_CLIENT_HOST_PORT=hatchet-engine:7070`.
- **Acknowledged limitation:** the first compose-up may still need a boot-fix
  cycle for env-contract surprises; the plan budgets exactly one, and the gate
  stays fail-closed through it (no opt-in, no skip).

### F9 — Worker readiness honesty preserved (addresses R-P10, C6)

**Mitigation:** the `(candidate, pending Plan J live validation)` suffix stays
until the live pair is proven; `wait-for-worker.sh` remains a registration
signal only; the release gate closes on real stage transitions (shape tests +
boundary E2E), never on the line. No change to the print-before-start
compromise (start() blocks on 1.38.1 — verified).

### F10 — F1..F9 retained, with cross-pattern rules encoded

The five interaction rules from T6 become explicit CI steps/assertions:
(1) gate order in F3; (2) key stability guarded by the duplicate-submission
live test; (3) stable service names asserted by preflight; (4) token minting
is step 0 of the boot sequence (least-redundant dependency); (5) gate job +
branch-protection wiring noted as a required follow-up.

### F. Technology revalidation (checked 2026-08-28)

| Choice | Revalidation | Status |
|---|---|---|
| `hatchet-sdk==1.38.1` | SDK client/worker docs (2026-08-28): `ClientConfig` JWT enforcement, `HATCHET_CLIENT_` prefix, `worker.start()` blocks, `WorkerStatus` lifecycle | Unchanged; CANDIDATE until live pair |
| Server `v0.105.2` split sub-paths | GHCR manifest HEAD 200 (T3 §5) | Unchanged; pullable |
| v0.105.2 env contract | NOT yet re-readable from the tag's own docs — flagged PROVISIONAL with exact unknowns named (F8) | **PROVISIONAL** (first-boot arbiter) |
| Fail-on-skip (conftest hook) | pytest #1364 + skip docs (2026-08-28) | Adopted; allowlist design |
| Postgres-only msgqueue | architecture-and-guarantees (2026-08-22) | Adopted, PROVISIONAL against v0.105.2 |
| All other pins | Unchanged from T3 §5 (python-multipart, ffmpeg, PGDG, actions) | Unchanged |

**Verdict:** P4/P8's static de-risking limit is acknowledged, not hidden; the
design converts every PROVISIONAL item into a named, budgeted first-boot
observation with a fail-closed gate throughout.

## Open Risks & Human Questions

*(rnd-counter-improver, Turn 8 — final risk assessment and the questions that
genuinely require human judgment. Product vs CI stream explicit. Web checks
dated 2026-08-28.)*

### 0. What the adversarial process resolved

The 8-turn debate produced one primary approach (A-refined: commit-and-wire,
fail-closed, prove-first) with B as a post-green complement, D dead
(documentedly), C folded into A as a preflight tripwire, and all 14 CI
environment failures plus the product wiring/capability/probe/packaging gaps
mapped to named implementation obligations. The SDK v1 surface, the compose
topology, token provisioning, retry ownership, fail-on-skip, and probe
semantics are now explicit pattern decisions — not first-run discoveries.

### 1. Unresolved risks (no static mitigation exists)

| Risk | Severity | Why it persists | Arbiter |
|---|---|---|---|
| SDK 1.38.1 ↔ server v0.105.2 pair fails on the live stack (C4) | HIGH | No live cluster run has ever executed; surface alignment (F1) is documented-based, not live-observed | First hosted run |
| v0.105.2 env contract (secret forms, msgqueue, dashboard port) | HIGH | Docs read are current-line, not the tag's own; compose spec is PROVISIONAL | First compose boot |
| Name namespacing / gRPC `host_port` routing on 1.38.1 | MEDIUM-HIGH | Hatchet #2832 class; only observable live | First live registration |
| Cold-start timing exceeds poll budgets | MEDIUM | Runner cache behavior + first-pull of 4 images | First hosted run |
| Probe reports reachability, not execution | MEDIUM | Intentional (E2E is the execution authority); misread risk remains | Capabilities schema + E2E hard-assert |
| Apt/runner drift | LOW | Accepted; version assertions mitigate | Ongoing |

### 2. Human-judgment questions (evidence cannot decide alone)

**HQ-1 — How faithful must the CI scheduler topology be to the deployed shape?**
The full split (migrate→admin→engine+dashboard, Postgres msgqueue,
`hatchet-admin` token) is the deployed shape but adds a boot-fix cycle risk and
env-contract unknowns; the `hatchet-lite-dev` image (auth compiled out, fixed
worker token — the CI-friendliest) was rejected as release evidence (D-1/D-2
topology skew). *At stake:* release fidelity vs CI cost/stability. *Evidence:*
T3 D-rejection (same-stack gate, §8); architecture-and-guarantees
(Postgres-only start supported). *Recommendation:* full split with Postgres-only
msgqueue; treat lite-dev strictly as a local developer convenience. Human
decision needed only if the boot-fix cycle exceeds budget.

**HQ-2 — How many hosted-run cycles to budget for the first-live-run loop, and
what to pre-fix vs observe?** Pre-alignment (F1) is cheap and doc-backed; the
residual unknowns are namespacing, routing, and env contract. *At stake:*
main-branch red runs during the loop; branch-protection posture. *Recommendation:*
prove the live gate on a feature branch / `workflow_dispatch` first (2-3
cycles), then flip the main gate fail-closed. Human decision: whether main is
allowed to be red during the proof window.

**HQ-3 — Token minting: per-run via `hatchet-admin` vs GitHub secret?**
Per-run minting avoids secret storage but couples token creation to the admin
boot step; a GitHub secret requires a tenant id and a longer-lived token
(expiry/rotation). *At stake:* security posture vs CI determinism.
*Recommendation:* per-run minting in the compose boot; revisit only if the
v0.105.2 admin CLI differs.

**HQ-4 — Fail-on-skip strictness in the E2E file.** Blanket fail-on-skip makes
optional-provider-gated runs red by design (R6's honest status vocabulary);
allowlist-based (F6) keeps those honest skips green while banning the
production-path skip. *At stake:* what "no green-without-run" means for
provider-gated capabilities. *Recommendation:* allowlist-based F6; record every
skip in the release summary with its reason.

**HQ-5 — Postgres-only vs RabbitMQ msgqueue in CI.** Evidence supports
Postgres-only for self-hosted start; if the production deployment runs
RabbitMQ, CI introduces the same class of skew D was rejected for. *At stake:*
same-stack fidelity vs CI simplicity. *Recommendation:* Postgres-only in CI,
with the deployment truth (does UMD production run RabbitMQ?) confirmed before
promoting the pair; if production uses RabbitMQ, add it to the CI stack before
release.

### 3. Final classification

- **Approaches:** A-refined (primary, survives) + B (post-green complement);
  C folded into A; D rejected with reasons (T2/T3).
- **Provisional facts that must be observed, not assumed:** SDK/server live
  pair; v0.105.2 env contract; namespacing; host_port routing; cold-start
  timing; probe behavior under load.
- **No unvalidated technology claim is presented as validated:** every choice
  carries source + check date (T3 §5, T5 §12, T7 §F) or is explicitly
  PROVISIONAL.
- **The design is ready to flow downstream** (DDAuthor distillation → plan →
  Exec-Manager → pushed GitHub implementation → retrieved hosted evidence) with
  the obligations below.

## Downstream Input Skeleton

*(rnd-refiner, final validation — distilled input for DDAuthor / the downstream
plan. This is a decision record for the next stage, not a design document.)*

**Chosen approach:** A-refined — "Commit-and-Wire, fail-closed, prove-first"
with C's `docker manifest inspect` preflight folded in as a tripwire. B
(Split-Job CI) is a post-green complement only.

**Implementation obligations (product stream):**
1. Rewire `build_context` (src/umd/api/app.py:167-168) to
   `ProductionDAGRunner` (default; durable backend never reports `active`).
2. Pre-align the SDK v1 surface: two-arg handler `(input, ctx)` +
   `Workflow.run`/`runs.create` submission (hatchet.py:118-137, 224-282) +
   mandatory surface-contract unit tests (P10/F1).
3. `CapabilityProbe` (gRPC reachability-only, cached, hysteresis) consumed by
   `CapabilityReporter`; capabilities schema: status + reason + versions
   (P4/F4).
4. Retry ownership: executor-only; Hatchet task `retries=0` + `NonRetryable`
   (P2/F2).
5. Worker packaging: shared image installs `.[worker]` (P9).
6. No fabricated completion: terminal COMPLETE only from callback-committed
   rows (P3).

**Implementation obligations (CI-remediation stream):**
7. Same-commit landing of: python-multipart 0.0.32, ffmpeg/ffprobe + PGDG
   client-17 + `UMD_PG_BIN`, secrets export in unit/postgres jobs, gate-polarity
   flip (no `UMD_VALIDATE_LIVE_WORKER` opt-in), fail-on-skip allowlist hook,
   always-run gate job, preflight tripwire (P5/P6/P7/F3/F6).
8. Compose split-topology spec: migrate→admin→engine+dashboard, shared config
   volume, Postgres msgqueue, per-run token minting, worker env
   `UMD_HATCHET_*`/`HATCHET_CLIENT_HOST_PORT` (P8/F8).
9. In-stack test-runner step after readiness ordering (P5/F3/F5).

**Evidence gates (all must be observed on a hosted run):**
- `live-worker-gate: PASS` machine-readable line (P11).
- `/v1/capabilities` scheduler `active` with observed versions + correct
  `server_image` sub-path.
- Boundary E2E passes with ZERO production-path skips (fail-on-skip enforced);
  job reaches terminal COMPLETE via committed stage_run rows.
- Three `test_live_hatchet_*` shape tests pass against the live stack
  (duplicate/restart single completion; retry/quarantine single authority;
  universe-change drain/rekey).
- Restart persistence: named volumes survive stop/start; boundary E2E passes
  after restart.
- Postgres suite green (14 failures resolved) with no skips added.

**Rejected alternatives:**
- D (Single-Container Lite) — topology skew violates handoff §8; gRPC port
  divergence (7077 vs hardcoded 7070); auth-var mismatch with C7; current
  compose matches neither topology (T2 D-1/D-2, T3 §3).
- B before A — ordering hazard: live job red from day one → corrosion (T2 B-2).
- C standalone — allow-failure posture is corrosion; accepted only as
  tripwire-in-A (T2 C-1/C-2).
- Opt-in/skip/recording-doubles as release evidence — prohibited by R4/C1.

**Unresolved provisional facts (first-boot arbiters, never assumed):**
- SDK 1.38.1 ↔ server v0.105.2 live pair (C4).
- v0.105.2 env contract (secret forms, `SERVER_MSGQUEUE_KIND=postgres`,
  dashboard port mapping).
- Task/workflow name namespacing on 1.38.1 (Hatchet #2832 class).
- gRPC `host_port` routing / JWT broadcast address.
- Cold-start timing vs 180s poll budgets.
- Probe behavior under a reachable-but-broken engine (E2E is the authority).

**References (research/librarian artifacts):**
- Diagnosis: `artifacts/designs/process/universal-media-decomposer-ci-repair-debugger.md`
- Librarian briefing: `artifacts/designs/process/universal-media-decomposer-ci-repair-librarian.md`
- Pattern-enforcer approval (DD validation): `artifacts/designs/process/universal-media-decomposer-ci-repair-pattern-enforcer-approval.md`
- Parent DD: `artifacts/designs/pending/DD-universal-media-decomposer.md`;
  CI-repair DD: `artifacts/designs/pending/DD-universal-media-decomposer-ci-repair.md`
- Contracts: CONTRACTS.md §58-63; release gate: HATCHET_LIVE_VALIDATION_HANDOFF.md §8
- Plans: `artifacts/plans/pending/TASK-universal-media-decomposer-J-api-boundary-ci-release.md` (+ G/H/I, handoff-G-to-I-J)
- Workspace skills: `.opencode/skills/umd-ci-hatchet-deployment/SKILL.md`,
  `.opencode/skills/umd-env-config-deploy/SKILL.md`
- Web sources (checked 2026-08-28): docs.hatchet.run v1 (retry-policies,
  timeouts, architecture-and-guarantees, directed-acyclic-graphs,
  migration-guide-python, v1-sdk-improvements, reference/python/client,
  self-hosting/docker-compose); GHCR manifest HEAD probes; pytest-dev#1364;
  Test Ratchet; GitHub troubleshooting docs; kubernetes.io probe semantics.

## Implementation Patterns

*(rnd-improver, Turn 5 — concrete implementation patterns for the surviving
approach (A-refined + C folded in; B deferred). This section is appended on a
fresh T5 pass over the full adversarial log; where it refines the earlier T5
patterns (P1–P11) it is written to be self-consistent with the log's T1–T8
record and explicitly supersedes conflicting earlier pattern text. Product-
repair patterns (IP-4, IP-5, IP-6, IP-7) and CI-remediation patterns (IP-1,
IP-2, IP-3, IP-8) are separated per R10/C8. Web checks dated 2026-08-28;
every library/version revalidated in the table at the end.)*

### IP-1 (CI-remediation) — Compose split-topology deployment pattern

**Data flow:** `db` healthy → `hatchet-migrate` runs once → `hatchet-setup-config`
(config-gen) writes `/hatchet/config` → `hatchet-engine` (gRPC 7070 in-network) +
`hatchet-dashboard` (HTTP 80 in-network) boot against the generated config → UMD
`worker` registers over engine gRPC. This is the official split topology verbatim:
migration → setup-config → engine+dashboard with a shared config volume and
`depends_on: condition: service_completed_successfully` ordering
(https://docs.hatchet.run/self-hosting/docker-compose, checked 2026-08-28).

**Concrete service set for `deploy/compose.yaml`** (replacing the current
non-functional single `hatchet` service at lines 101-111, which matches NEITHER
topology — log lines 150-156):

- `hatchet-migrate` — image `ghcr.io/hatchet-dev/hatchet/hatchet-migrate:v0.105.2`
  (sub-path verified 200, T3 §5), `command: /hatchet/hatchet-migrate`, env
  `DATABASE_URL` (Hatchet's own DB), `depends_on: db: service_healthy`.
- `hatchet-setup-config` — image `hatchet-admin:v0.105.2`,
  `command: /hatchet/hatchet-admin quickstart --skip certs --generated-config-dir /hatchet/config --overwrite=false`
  (the official config-gen command), env `DATABASE_URL` + `SERVER_MSGQUEUE_KIND=postgres`
  (Postgres-only msgqueue — official docs: set this and delete RabbitMQ references),
  `SERVER_GRPC_BROADCAST_ADDRESS: hatchet-engine:7070` + `SERVER_INTERNAL_CLIENT_INTERNAL_GRPC_BROADCAST_ADDRESS: hatchet-engine:7070`
  (in-network worker routing), shared `hatchet-config` volume.
- `hatchet-engine` — image `hatchet-engine:v0.105.2`,
  `command: /hatchet/hatchet-engine --config /hatchet/config`, env `DATABASE_URL`,
  `depends_on: hatchet-setup-config: service_completed_successfully`.
- `hatchet-dashboard` — image `hatchet-dashboard:v0.105.2`,
  `command: sh ./entrypoint.sh --config /hatchet/config`, env `DATABASE_URL`.
- UMD `worker` service gains `depends_on: hatchet-engine: service_started` (official
  in-network worker dependency) and the env contract of IP-2/IP-3.
- Hatchet needs its OWN database. The official compose uses `postgres:15.6`; UMD's
  `db` is `pgvector/pgvector:pg18` (compose.yaml:36). Whether v0.105.2 runs against
  Postgres 18 is **PROVISIONAL** — the plan must read the v0.105.2 tag docs; the
  safe default is a dedicated `hatchet-db` service pinned to the tag's documented
  Postgres major, so Hatchet migration/engine compatibility never depends on UMD's
  pgvector-18 choice.

**Health dependencies:** `db` healthy → migrate completed → setup-config
completed → engine+dashboard up. UMD's existing `wait-for-http.sh`/`wait-for-worker.sh`
(scripts already in tree) become the readiness gates; the API's healthcheck pattern
(compose.yaml:72-78) is the model for engine/dashboard healthchecks.

**The `${VAR:?}` secret contract (C7) — mechanical AND semantic.** The official
config-gen does NOT consume `SERVER_AUTH_COOKIE_SECRET`/`SERVER_ENCRYPTION_MASTER_KEY`
as interpolation inputs (secrets are generated into the config; the current-line
compose passes no auth-secret env to setup-config — checked 2026-08-28). Pattern:
(1) keep `HATCHET_COOKIE_SECRET`/`HATCHET_MASTER_KEY` required (`${VAR:?}`) in the
compose file so the Compose-config test remains mechanically gated (C7); (2) pass
them to `hatchet-setup-config` **in the exact form the v0.105.2 tag consumes**
(PROVISIONAL — plan-time read of the tag's compose/docs, per F8); (3) make the
Compose-config test *semantically* meaningful by asserting the generated config
enables auth — e.g. the dashboard/engine rejects unauthenticated requests and the
minted worker token is a real JWT — so the required vars gate the server's auth,
not just the interpolation. This converts RISK 5's "mechanical but hollow" hazard
into an enforced property.

### IP-2 (CI-remediation) — Token-creation/registration pattern (RISK 1)

**Sequence (step 0 of the boot chain — the least-redundant dependency, T6
cross-pattern rule 4):** after `hatchet-setup-config` completes, mint a real JWT
via the documented CLI:

```sh
docker compose run --no-deps setup-config \
  /hatchet/hatchet-admin token create --config /hatchet/config --tenant-id <uuid>
```

The official split-compose docs give this exact command and the dashboard
alternative (Settings → API Tokens) — checked 2026-08-28
(https://docs.hatchet.run/self-hosting/docker-compose). The `umd-ci-token`
placeholder (validation.yml:234) is deleted — it can never register
(known-SDK facts, log lines 143-144).

**Tenant-ID discovery:** the config-gen writes the tenant into `/hatchet/config`;
the tenant-id is read from the generated config (or the quickstart output) in the
mint step — exact location PROVISIONAL until the v0.105.2 image boots, so the mint
step must be written defensively: dump the config dir on failure and fail the job
(never fabricate a token).

**Token-to-env handoff:** the minted JWT is written to the worker's env
(`UMD_HATCHET_TOKEN`) and the test-runner's env in the same CI step; it is a
per-run secret — never committed, never a GitHub-secret dependency (HQ-3's
recommendation).

**Re-issue semantics (official, verbatim-adjacent):** "modifying the GRPC broadcast
address or server URL will require re-issuing an API token." Pattern: the mint
step re-runs whenever the stack is re-created with a different broadcast
address/server URL — in CI this is every run, so mint-per-run is the correct and
only safe posture. A stale token (broadcast change without re-mint) fails the
worker registration gate, which is the honest failure.

### IP-3 (CI-remediation) — In-network live-test execution pattern (RISK 2, RISK 4)

**Mechanism:** one-shot test-runner container on the compose network:
`docker compose run --rm --no-deps <image> pytest <shape-tests + boundary E2E>`
(`--no-deps` = don't start linked services; `--rm` = remove after; exit code is the
container's — https://docs.docker.com/reference/cli/docker/compose/run/, checked
2026-08-28). Precedents: gramps-mcp 071e3f6, Compose Tip #52 (log-cited T3).

**The two concrete env-contract fixes (T4 §2.2, RISK 2):**
- (a) **Fix `_real_client` host_port parsing** (tests/test_hatchet_live.py:308):
  it currently treats `UMD_HATCHET_CLIENT_HOST_PORT` as a bare PORT and builds
  `host_port=f"{host}:{port}"` → `hatchet-dashboard:hatchet-engine:7070` (malformed).
  Pattern: accept the full `host:port` value when it contains a colon
  (`host_port = os.environ.get("UMD_HATCHET_CLIENT_HOST_PORT") or f"{host}:7070"`),
  matching the SDK-native `HATCHET_CLIENT_HOST_PORT=hatchet-engine:7070` semantics
  the worker already relies on (cli.py:104-106). This is a test-code fix, not an
  assertion change.
- (b) **Dashboard in-network port is 80** (official compose maps host 8080→container
  80). Pattern: `UMD_HATCHET_SERVER_URL=http://hatchet-dashboard:80` (or
  `http://hatchet-dashboard` — default HTTP port) for the test-runner, NOT
  `:8080`, unless the rebuilt compose explicitly sets the dashboard container port
  to 8080 via a supported env (`SERVER_HTTP_PORT`, PROVISIONAL against v0.105.2).

**Full test-runner env contract:** `UMD_HATCHET_SERVER_URL=http://hatchet-dashboard:80`,
`UMD_HATCHET_CLIENT_HOST_PORT=hatchet-engine:7070` (gRPC, in-network — no host port
publishing required), `UMD_HATCHET_TOKEN=<minted JWT from IP-2>`,
`UMD_TEST_POSTGRES=true`, `UMD_PG_HOST=db`, `UMD_PG_PORT=5432`, `UMD_PG_BIN`
pointing at the image's pg client dir (see IP-7), OCFL writable volume mounted at
`/data/ocfl`, and media tooling (ffmpeg/ffprobe) so every `STAGE_ORDER` stage can
reach COMPLETE inside the container (RISK 4 / T4 §2.3 — the retry shape test
asserts `StageCompleted count == len(STAGE_ORDER)`). Host-publish fallback (engine
7070 + dashboard 8080 on 127.0.0.1) remains documented but is NOT the primary path.

### IP-4 (product) — Job lifecycle / async status pattern (RISK 3)

**Chosen contract: persist queued stage states at submission.** The T4 §5
human-judgment item (queued-row recording vs PENDING-tolerant polling) is decided
toward the MORE honest option: `submit_workflow_runs` (runner.py:202-260) gains a
store write per stage — a `queued` StageState/`stage_run` row keyed by the
submission's idempotency material — so `_derive_status` (jobs.py:313-323) sees
non-empty states and returns RUNNING immediately after submit instead of flipping
RUNNING→PENDING (T4 §2.1). Terminal COMPLETE still arrives ONLY from
callback-committed rows (never fabricated, debugger §3.4). This makes the
lifecycle **PENDING → RUNNING (queued stages observable) → COMPLETE** explicit and
satisfies the boundary E2E's "observes queued/RUNNING" hard assertion without
weakening it (A-2). Retry (jobs.py:188) and `rerun_stage` (jobs.py:193-221) reuse
the same submission path, so their status after scheduling stays RUNNING.

**Interaction with the idempotency authority (IP-6/P2):** the queued row must be
claimable by the worker callback's `UNIQUE idempotency_key` claim
(CONTRACTS.md:60-63). The callback resolves committed upstream refs before
`executor.run` (hatchet.py:242-252), which can change the manifest-derived key
(R-P9). Pattern: the queued row uses the same key basis the claim will use —
verify `StageManifest.idempotency_key()` derivation at plan time and, if the key
includes `evidence_refs`, key the queued row on `(job_id, stage, dag_universe)`
instead so the claim transitions the row rather than colliding. The live
duplicate/restart shape test remains the arbiter.

**Observation:** `/v1/jobs/{id}` returns job.status + stage states; the boundary
E2E polls until terminal COMPLETE and asserts it observed an intermediate
queued/RUNNING state (a job reaching COMPLETE synchronously inside the submit call
is a durable-backend signature and FAILS — A-2 hard-assert). State-machine
reference: Celery's documented task states PENDING→STARTED→SUCCESS/FAILURE/RETRY
with observable intermediate states and DB-backed storage
(https://docs.celeryq.dev/en/stable/userguide/tasks.html#states, checked
2026-08-28).

### IP-5 (product) — Fail-closed backend selection + honest capability pattern

**Wiring (A-2):** `build_context` (app.py:167) defaults to `ProductionDAGRunner`.
The durable backend is selectable ONLY via an explicit non-release env
(`UMD_EXECUTION_BACKEND=durable`), which release CI never sets, and even then it
can never produce scheduler `active`.

**Capability reporting (R6/C3):** `CapabilityReporter.report()` reports scheduler
`active` only when (a) SDK importable, (b) env present, (c) the wired runner is
`ProductionDAGRunner`, AND (d) the cached live probe passes. The durable backend
reports `configured-but-unavailable`/`reference-only` with a gate reason, never
`active` (capability.py currently can never flip active — the missing probe is the
entire gap).

**Probe (A-4/SC-6):** a `CapabilityProbe` module with an INJECTED client (for
hermetic testability), background-cached, with hysteresis — `failureThreshold ≥ 2`
consecutive failures to drop, `successThreshold ≥ 2` to recover (Kubernetes probe
semantics — https://kubernetes.io/docs/concepts/workloads/pods/probes/, checked
2026-08-28; oneuptime 2026-01-08; decodeops 2026-05-06, log-cited). It probes the
gRPC admin surface the SDK uses (a reachability-only call such as
`runs.list(limit=1)` — SC-6), never execution (CONTRACTS.md:63), and never blocks
`/v1/capabilities` (request path reads the cached boolean). The /v1/capabilities
schema carries status + reason + sdk_version + server_image (and probe timestamp),
so `active` is never read as "proven" (R-P4 mitigation).

**Boundary E2E hard-asserts:** capabilities scheduler `active`; reported
`server_image` equals the pinned sub-path image (`hatchet-engine` sub-path — this
forces `hatchet.py:56` to change in the same commit as compose.yaml, T4 §4.4); and
the async lifecycle assertion from IP-4. The E2E's `_require_production_path`
(tests/test_api_boundary_e2e.py:108-138) keeps its honest skip semantics; the CI
gate additionally fails on a vacuous skip (IP-8).

### IP-6 (product) — SDK-surface alignment pattern

**Handler (SC-1, §5(a)):** `_make_handler` (hatchet.py:224) becomes a v1
two-argument handler `handler(input, ctx)` where `input` is the Pydantic input
model (default `EmptyModel` per the SDK; the workflow declares an
`input_validator`). The manifest is built from the typed input
(`input.manifest`), not `payload["input"]["manifest"]`. The v1 contract is
verbatim: "the signature of a task now will be
`Callable[[YourWorkflowInputType, Context]]`"
(https://docs.hatchet.run/v1/migrating/v1-sdk-improvements and
https://docs.hatchet.run/reference/python/client — checked 2026-08-28).

**Submission (§5(b)):** `_real_submit_workflow_run` (hatchet.py:118-137) switches
from `runs.admin_client().run_workflow(name, json.dumps(input))` to the v1
surface: `Workflow.run(input)` / `Standalone.run(input)` (preferred) or
`hatchet.runs.create` with a JSON-serializable mapping — "The `AdminClient` has
been removed… you can use `hatchet.runs.create`. This replaces the old
`hatchet.admin.run_workflow`" (v1-sdk-improvements, checked 2026-08-28). The
`_SDKSubmissionShim` (hatchet.py:140-158) keeps the shared `submit_workflow_runs`
path unchanged. Return values stay JSONSerializableMapping/Pydantic (SDK
restriction, checked 2026-08-28).

**Registration/naming:** `HatchetWorkerFactory.start` registers via the SDK
decorator surface (`client.task(name="umd-{stage}")`, keyword-only `name` — already
handled at hatchet.py:412-426). Task `retries=0` is set EXPLICITLY (SDK default is
0; making it explicit locks retry ownership to the executor — IP-4/P2, R-P2).
Worker/task name namespacing (Hatchet #2832 class) is observed live, not pre-fixed.
`cli.py:131` owns the blocking `client.worker("umd-worker", workflows=...).start()`
and prints the readiness line BEFORE start (C6 — already correct in tree).

**Surface-contract tests (SC-1 enforcement):** hermetic unit tests (mock the SDK
client) assert (a) submission reaches `Workflow.run`/`runs.create` with a mapping,
(b) the handler accepts two args and builds the manifest from the typed input.
This locks the documented contract so the first live run observes only
namespacing/routing — the residual unknowns (T7 F1).

### IP-7 (product) — Worker-image packaging pattern (RISK 4, T4 §2.4)

**Decision: single shared image installs the worker extra** (`pip install .[worker]`
in deploy/Dockerfile:32, replacing `pip install .`). Rationale: the IP-5 probe
runs in the API process and needs `hatchet_sdk`; the API never imports it at
module level (verified T4 §0), so there is no startup cost; one image, two roles
matches the Dockerfile's stated design. The multi-target alternative (a
`worker-image` stage via `FROM base` + `--target`, the official Docker multi-stage
pattern — https://docs.docker.com/build/building/multi-stage/, checked 2026-08-28)
keeps the candidate SDK out of the API image but loses the probe's SDK — rejected
for this reason.

**C4 hazard mitigation (T4 §2.4):** a comment AT THE DOCKERFILE line states
"installing the SDK ≠ promoting the pin; hatchet-sdk 1.38.1 ↔ server v0.105.2
stays CANDIDATE until the live pair proves (deploy/pins/runtime.txt, C4)". The
existing static pin-agreement test covers the pin line itself.

**Media capability (RISK 4):** the image also installs ffmpeg/ffprobe (and the
Postgres client matching `UMD_PG_BIN` for conftest resolution) so every
`STAGE_ORDER` stage reaches COMPLETE in the compose worker and the test-runner
container; sandbox-runner keeps its non-privileged profile (compose.yaml:114-140)
for isolated media execution. This closes the debugger's "container runtime tool
gap" (item 5) for the image, complementing the host-side ffmpeg/PGDG installs in
the unit/postgres jobs (IP-8/P7).

### IP-8 (CI-remediation) — CI gate topology pattern

**Gate polarity (A-1):** docker-e2e boots the full stack unconditionally
(`--profile sandbox up -d --build` as at HEAD); the `UMD_VALIDATE_LIVE_WORKER`
opt-in env + conditional boot/readiness (working-tree diff, validation.yml:208-268)
are removed in the SAME commit as the fixes. No user-settable escape remains; no
`allow-failure`/`continue-on-error` on the live path on main (C-1).

**Always-running gate job (B-1):** add a `gate` job with `if: always()` and
`needs: [docker-e2e]` that fails the run when docker-e2e was skipped or failed.
GitHub's own docs are explicit: "A job is skipped by a conditional → The job
reports 'Success'" and "Use `always()` with `needs` for required checks that
depend on other jobs"
(https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories-with-code-quality-features/troubleshooting-required-status-checks,
checked 2026-08-28). No trigger-level path filter on the live job for main pushes
(T2 B-1). Branch protection must require the gate job (T6 interaction rule 5).

**Fail-on-skip (SC-5):** a conftest hook scoped to the E2E run raises on
`pytest.skip` when `GITHUB_ACTIONS=true`, with an explicit allowlist of named
permitted skips (optional providers configured-unavailable/gated); the
production-path skip (`_require_production_path`) is NOT on the allowlist.
pytest has no built-in fail-on-skip — this is the documented long-standing request
(https://github.com/pytest-dev/pytest/issues/1364, checked 2026-08-28). Hardening
later: Test Ratchet ratchets the whole-suite skip count
(https://github.com/marketplace/actions/test-ratchet, log-cited).

**Preflight tripwire (C-2):** `docker manifest inspect` on the pinned sub-path
images before compose-up — fails fast and attributably on the 403 class; tripwire
only, never release evidence.

**Secrets + provisioning (H3/P7):** `HATCHET_COOKIE_SECRET`/`HATCHET_MASTER_KEY`
exported in the unit/postgres jobs (so the Compose-config test passes — never by
weakening `${VAR:?}`, C7); python-multipart 0.0.32, ffmpeg/ffprobe + PGDG
`postgresql-client-17` + `UMD_PG_BIN` retained from the verified working tree, with
version assertions (`pg_dump --version` == 17.x) against runner drift (R-P7).

**Readiness ordering (F3):** API `/v1/ready` → worker line (registration signal
only, R-P10) → probe warm (bounded retry on /v1/capabilities scheduler active) →
run boundary E2E + shape tests. Poll budgets raised to 180s; evidence dump on
timeout retained.

**Evidence capture (P11):** keep wait-for-http/wait-for-worker/capture-diagnostics/
record-release-summary; add machine-readable `live-worker-gate: PASS|FAIL` to the
summary; artifacts (logs, junit, diag) uploaded on failure and success.
Teardown stays `if: always()` + `continue-on-error` (never masks a real failure).

**Single-commit hygiene (RISK 6 / T4 §2.5):** assemble the A-1 commit with explicit
`git add <paths>` (CI stream: validation.yml, pyproject.toml, conftest.py,
compose.yaml, Dockerfile, runtime.txt, scripts, hatchet.py, app.py, jobs.py,
runner.py, capability.py, cli.py, tests) and a pre-commit `git diff --cached`
review — the unrelated ASR/audio/docs/log churn stays out of the commit (C8).

### Technology validation (revalidated 2026-08-28)

| Choice | Source / check date | Result | Why best fit (not merely newest) |
|---|---|---|---|
| `hatchet-sdk==1.38.1` | PyPI + py/1.38.1 release 2026-08-25 (log T3 §5) | Current line; MIT; py>=3.10,<4 | Recorded candidate; stays CANDIDATE until the live pair proves (C4) |
| Server v0.105.2 split sub-paths | GHCR manifest HEAD, four sub-paths 200 (T3 §5, T4 §0) | Exact repair target; top-level path 403 | Split = deployed shape; lite rejected (D) |
| Split topology service names/commands/token CLI | docs.hatchet.run/self-hosting/docker-compose (fetched 2026-08-28) | migrate → setup-config → engine+dashboard; `hatchet-admin token create --config … --tenant-id …`; Postgres-only via `SERVER_MSGQUEUE_KIND=postgres`; token re-issue on broadcast change | IP-1/IP-2 basis; env forms still PROVISIONAL vs the v0.105.2 tag |
| v1 handler `(input, ctx)` + `Workflow.run`/`runs.create` | v1-sdk-improvements + reference/python/client (fetched 2026-08-28) | Two-arg signature; AdminClient removed; inputs Pydantic/EmptyModel; retries default 0; worker.start() blocking | IP-6 alignment targets, doc-authoritative |
| Gate job fails-on-skip | GitHub troubleshooting docs (fetched 2026-08-28); pytest-dev#1364 (fetched 2026-08-28) | Skipped-conditional job reports Success; always()+needs for dependents; no built-in fail-on-skip | IP-8 topology + conftest hook |
| One-shot compose run | docs.docker.com/reference/cli/docker/compose/run (fetched 2026-08-28) | `--no-deps`, `--rm`, exit-code propagation | IP-3 test-runner mechanism |
| Multi-stage Dockerfile | docs.docker.com/build/building/multi-stage (fetched 2026-08-28) | Named stages + `--target` | Evaluated and rejected for IP-7 (probe needs SDK in API image) |
| Async state machine | docs.celeryq.dev/en/stable/userguide/tasks.html#states (fetched 2026-08-28) | PENDING→STARTED→SUCCESS/FAILURE with observable intermediates, DB backend | IP-4 lifecycle contract reference |
| Probe hysteresis | kubernetes.io/docs/concepts/workloads/pods/probes (log-verified); oneuptime 2026-01-08; decodeops 2026-05-06 | failureThreshold/successThreshold ≥ 2; cached background | IP-5 probe design |
| python-multipart 0.0.32, ffmpeg, PGDG client-17, actions | Log T2 §0 / T3 §5 | Verified fixes | IP-8, retained unchanged |

### Remaining PROVISIONAL items (first-boot arbiters, never assumed)

1. **v0.105.2 env contract** — exact config-gen/engine variable names
   (`SERVER_AUTH_COOKIE_SECRET` vs plural `_SECRETS`,
   `SERVER_ENCRYPTION_MASTER_KEY` vs `_MASTER_KEYSET`, `SERVER_MSGQUEUE_KIND=postgres`
   validity, dashboard container port, tenant-id location in the generated config)
   — the plan MUST read the v0.105.2 tag's compose/docs before implementation
   (F8); the boot-fix cycle is budgeted and the gate stays fail-closed through it.
2. **SDK 1.38.1 ↔ server v0.105.2 live pair (C4)** — real pull/register/execute on
   the hosted stack; the preflight tripwire catches pull, not env contract.
3. **Name namespacing / gRPC `host_port` routing on 1.38.1** — observed live;
   surface alignment (IP-6) is doc-based.
4. **Queued-row key basis** — whether `StageManifest.idempotency_key()` includes
   `evidence_refs` decides the queued-row keying (IP-4); verified at plan time.
5. **Dashboard in-network port** — 80 per the official compose; a
   `SERVER_HTTP_PORT`-style override is tag-dependent (IP-3).
6. **Cold-start timing vs 180s poll budgets** — first-pull of four sub-path images
   on a cache-less ubuntu-24.04 runner (T2 B-3).

## Pattern Risks

*Critique of IP-1..IP-8 (rnd-improver, Turn 5). All web sources fetched 2026-08-28. Code-seam facts verified in-tree (conftest.py, test_hatchet_live.py, stage_repository.py, manifest.py, job_repository.py, cli.py, compose.yaml, Dockerfile, pyproject.toml).*

### Verdict up front

IP-1..IP-8 cannot restore the R4 release gate as written. The first hosted run fails on three independent blockers: **(1) the live shape tests poll a different Postgres database than the compose worker commits to; (2) the compose worker cannot register with the specified env contract because `cli.py:104-106` derives the gRPC host from the REST `server_url` host, and the single `compose up` in IP-8 starts the worker before the IP-2 token mint exists; (3) the IP-4 queued-row design is unsatisfiable with the current `StageRunRepository.claim` (INSERT-ON-CONFLICT-DO-NOTHING, never transitions a row).** The architecture survives with the mitigations below; the pattern text must be amended at plan time.

---

### Per-pattern risk analysis

#### IP-1 — Compose split-topology deployment
- **Source:** [Tier 3] Official Hatchet split compose, docs.hatchet.run/self-hosting/docker-compose (fetched); [Tier 1] postgres:15.6 pin in that compose.
  **Mechanism:** Official compose pins `postgres:15.6`; UMD's `db` is `pgvector/pgvector:pg18`. Hatchet engine v0.105.2 on Postgres 18 is unverified (msgqueue kind=postgres uses LISTEN/NOTIFY + polling; pg18 retains both, but the engine's SQL/SQLAlchemy dialect expectations on pg18 are not documented).
  **Trigger:** Adopting the dedicated `hatchet-db` — the pattern already handles this (PROVISIONAL item 1).
  **Blast radius:** Engine/msgqueue breakage on first boot if pg18 were used; contained by the dedicated pinned major.
  **Mitigation:** Keep `hatchet-db` at the documented major (15.x) for v0.105.2; do NOT reuse the pg18 `db` service. Plan must read the v0.105.2 tag's compose to pin the exact tag-level image + env contract (PROVISIONAL item 1 already says this — confirm it is executed, not deferred).
  **Severity:** LOW (pattern already mitigates; execution risk only).

#### IP-2 — Token creation/registration
- **Source:** [Tier 1] GitHub raw — cmd/hatchet-admin/cli/token.go @ v0.105.2 (hatchet-dev/hatchet).
  **Mechanism:** Ground truth for the flags: `--tenant-id` (string), `--name` (default `"default"`), `-e/--expiresIn` (Duration, **default 90 days**). `--config` is NOT a token-subcommand flag — it is the cobra root persistent `configDirectory` flag, which is why the docs put it in the same invocation. `tenantIDForTokenCreate` returns `--tenant-id` if provided, **else falls back to `srv.Seed.DefaultTenantID` from the generated config**.
  **Trigger:** The pattern's plan to "read the tenant-id from generated config" is unnecessary work — `--tenant-id` is OPTIONAL; omitting it uses the config's seed tenant.
  **TTL:** The 90-day default defuses the "shape suite + restart segments exceed TTL" concern (the suite is minutes). Mint-per-run remains correct for the *broadcast-address re-issue* semantics (the JWT embeds the broadcast address), not for TTL. No mid-suite re-mint needed.
  **Mechanism 2:** The generated token JWT embeds `grpc_broadcast_address`/`server_url` claims; SDK `ClientConfig.validate_addresses` (see IP-5 evidence) uses those when host_port/server_url are not explicitly set. This makes the host_port env dance partially redundant — and dangerous when explicit values are wrong (IP-3 findings below).
  **Blast radius:** If the plan insists on tenant-id discovery, it adds a fragile config-parse step with no benefit. Low.
  **Mitigation:** Mint with `--tenant-id` omitted (seed default). Keep defensive config dump on failure. **Do not fabricate a token** — the pattern already says this; the SDK enforces JWT shape ("must start with `ey`"), so `umd-ci-token` can never register — the deletion is correct.
  **Severity:** LOW (process simplification; no breakage).

#### IP-3 — In-network live-test execution
- **Source:** [Tier 3] docs.docker.com compose run (pattern's citation); [Tier 1] in-tree conftest.py + test_hatchet_live.py (verified).
  **Mechanism (BLOCKING):** `umd_db` yields `migrated_db` — a **throwaway database `umd_p1test_{uuid}`** created on `db:5432` (conftest.py:87-123, 181-186). The **compose worker commits `stage_run`/`semantic_event` rows to the `umd` database** (`UMD_POSTGRES__DSN=...@db:5432/umd`, compose.yaml). The live shape tests poll `umd_db` (test_hatchet_live.py:921-978) → they poll a database the worker never writes → `_poll_until` 120s timeout → `pytest.fail`. The pattern's env contract (UMD_PG_HOST=db etc.) is necessary but **not sufficient**: it never specifies that the test engine and the worker DSN must converge on the SAME database.
  **Trigger:** Every docker-e2e run of the live shape suite, as specified.
  **Blast radius:** R4 release evidence (live retry/quarantine/duplicate shape tests) can never pass → the gate cannot be restored. Also the `_truncate` in the `umd_db` fixture would wipe the worker's in-flight rows if the tests were pointed at the worker's DB per-test — per-test truncation against the live DB is itself a data-destruction hazard.
  **Mitigation (required):** (a) Harness creates a dedicated shared DB (e.g. `umd_ci`) and applies migrations ONCE before the suite; worker DSN + test engine both point at it; (b) a **non-truncating** `live_db` fixture for the live tests (the `umd_db` truncation must not run against the live DB); or (c) tests poll an engine built from `UMD_POSTGRES__DSN` directly. The pattern must pick one and encode it.
  **Severity:** BLOCKING.
  **Mechanism (HIGH):** The `_real_client` fix is incomplete. `host_port = os.environ.get("UMD_HATCHET_CLIENT_HOST_PORT") or f"{host}:7070"` — when the env is absent, `host` comes from `urlparse(UMD_HATCHET_SERVER_URL).hostname` = `hatchet-dashboard` → `host_port="hatchet-dashboard:7070"` → gRPC to a container that serves HTTP on 80, not gRPC on 7070 → connection refused. The fallback is actively harmful.
  **Mitigation:** When the env is absent, **omit host_port entirely** and let the SDK derive it from the JWT broadcast claim (which config-gen wrote as `hatchet-engine:7070`) — this is the documented SDK default (config.py `validate_addresses`). Explicit `hatchet-engine:7070` also works.
  **Severity:** HIGH.
  **Mechanism (MEDIUM):** `docker compose run` attaches the one-off container to the project network (reachable: `hatchet-engine:7070`, `hatchet-dashboard:80`, `db:5432`), and `--no-deps` only skips starting linked services. Correct. BUT if the one-off reuses the `api` service definition (published port 8080:8080), the bind collides with the running api container.
  **Mitigation:** Dedicated `test-runner` service, no published ports.
  **Severity:** MEDIUM-LOW.
  **Mechanism (MEDIUM):** Media-capability is only half of RISK 4. The compose worker runs the REAL registry, and `_ensure_source(umd_db)` inserts source **rows** — the real INGEST pipeline needs source **bytes** in the worker's OCFL volume and a resolvable locator. ffmpeg/ffprobe alone does not make every STAGE_ORDER stage reach COMPLETE. The pattern must specify the fixture layout (OCFL volume shared with the worker, seeded source objects) — the pattern does not.
  **Severity:** MEDIUM-HIGH.

#### IP-4 — Job lifecycle / async status
- **Source:** [Tier 1] in-tree stage_repository.py (claim: INSERT ON CONFLICT DO NOTHING, cannot UPDATE/transition), manifest.py (idempotency_material INCLUDES `evidence_refs`), job_repository.py (`_STATUS_RANK` has no "queued" → rank 0), hatchet.py:250-252 (callback resolves + OVERWRITES evidence_refs before executor.run).
  **Mechanism (BLOCKING — internal contradiction):** For the root stage (INGEST, no upstream evidence), the submission-time idempotency key (evidence_refs=[]) EQUALS the callback claim key → the queued row occupies the UNIQUE(idempotency_key) slot → the worker's claim returns `already_exists, won=False` → **INGEST never executes → the whole job stalls**. For downstream stages, the callback-resolved evidence_refs change the key → no collision, but then the queued row is orphaned and the shape tests' raw-DB assertions (`_stage_run_count_for_stage`, `_distinct_idempotency_keys`) see 2 rows per stage.
  **Trigger:** Any live submission of a multi-stage job; every live shape test.
  **Blast radius:** Either the DAG never starts or the evidence assertions fail; `_derive_status` is saved only because complete(5) outranks queued(0) in the fold — but the raw-DB tests are not folded.
  **Mitigation (required):** The queued row must NOT occupy the claim key slot. Options: (a) queued rows in a separate table/view; (b) submission-time evidence resolution so the key is stable across submit→claim (contradicts "never at submission time" — must change); (c) `claim` gains an UPDATE-transition path (schema change to UNIQUE(job_id, stage, dag_universe) or a status transition). Pattern's "key queued row on (job_id, stage, dag_universe)" avoids the collision but then claim never transitions it — the queued row persists forever and raw counts still break. The plan must rework either the claim machinery or the tests. "Live duplicate/restart shape test is arbiter" is circular — the arbiter cannot pass under the current contract.
  **Severity:** BLOCKING.
  **Mechanism (MEDIUM):** Write amplification: every submission writes N queued rows; `retry`/`rerun_stage` reuse the submission path → repeat submissions; dedup by claim saves correctness but the queued-table grows.
  **Mitigation:** Batch insert + dedupe on (job_id, stage, dag_universe) at the repository layer.
  **Severity:** MEDIUM.

#### IP-5 — Fail-closed backend selection + honest capability
- **Source:** [Tier 1] SDK py/1.38.1 features/runs.py + clients/admin.py (raw GitHub); config.py.
  **Mechanism (HIGH — surface mismatch):** `runs.list(limit=1)` is a **REST** call (`WorkflowRunsApi.v1_workflow_run_list` over `server_url`), NOT a gRPC call, and it REQUIRES `client_config.tenant_id` + valid auth. The pattern's claim "probes the gRPC admin surface the SDK uses (a reachability-only call such as runs.list(limit=1))" is wrong on both counts: (a) it does not exercise the gRPC socket the worker uses (host_port/7070); (b) `RunsClient` construction spins up workflow-run listeners + admin_client (threads) — heavy for a probe.
  **Trigger:** Probe mis-reports "active" while the worker's gRPC path is dead (registration failing), or mis-reports "inactive" when gRPC is fine but REST is blocked.
  **Blast radius:** The capabilities gate's honesty is the R4 centerpiece — a wrong surface means the gate validates the wrong thing.
  **Mitigation:** Probe the actual worker surface: an AdminClient v1 gRPC call (e.g. `get_details` on a sentinel or a workers-list RPC over the gRPC conn built from host_port) or the SDK healthcheck client; or explicitly rename the probe semantics to "REST/auth reachable" and pair it with the worker registration check (R-P10 line) as the gRPC evidence. Set `server_url` + `host_port` EXPLICITLY in the probe's ClientConfig (do not rely on JWT defaults — see IP-2; the config-gen `SERVER_AUTH_COOKIE_DOMAIN=localhost:8080` hints the JWT server_url claim may be wrong for in-network REST).
  **Severity:** HIGH.
  **Mechanism (HIGH — token handoff gap):** IP-2 hands the token to the worker + test-runner env, but the **API container has no token env**; the probe runs in the API process and needs SDK + token to construct any client ("Token must be set" → ValueError). Without a client, capabilities can never report active → boundary E2E `_require_production_path` skips → the IP-8 gate fails on vacuous skip. The IP-5×IP-8 ordering ("probe warm" after worker line) presupposes the API has a token that the patterns never deliver.
  **Trigger:** Every run, as specified.
  **Mitigation:** Add the minted token (+ UMD_HATCHET_SERVER_URL / host_port) to the `api` service env before it starts (ties into the two-phase up below).
  **Severity:** HIGH.

#### IP-6 — SDK-surface alignment
- **Source:** [Tier 1] SDK py/1.38.1 clients/admin.py (raw); [Tier 3] v1 SDK migration docs (pattern's citation).
  **Mechanism (MEDIUM — fact correction):** The premise "AdminClient has been removed" is FALSE for 1.38.1. `AdminClient.run_workflow(workflow_name, input: str, options)` EXISTS — deprecated (the `RunsClient.admin_client` property warns "will be removed in v2.0.0") but functional, calling the v0 gRPC `TriggerWorkflow` surface. Consequence: the tree's `runs.admin_client().run_workflow(name, json.dumps(input))` does NOT crash on 1.38.1 — it works through the legacy v0 path (gRPC to host_port). The first-live-run failure mode is NOT a guaranteed submission crash (contradicts SC-1/R-P1's "removed" framing); the real risk is v0-trigger → v1-registered-task matching semantics and the deprecated-surface drift. IP-6's alignment to `Workflow.run`/`runs.create` is still correct (documented v1 surface), but the hermetic surface-contract test must NOT assert AdminClient absence — it must assert the v1 surface is USED.
  **Severity:** MEDIUM.
  **Mechanism (MEDIUM — worker-side validation):** The SDK validates the input against the workflow's `input_validator` at the WORKER (dispatch), not at submit. A mis-declared input model → worker-side Pydantic error → stage fails (retries=0 → immediate) → the gate sees a poll timeout, not a clean submit error. Slower to debug; the 180s budgets + evidence dump cover detection, but the hermetic tests must exercise exact model coercion (missing fields, wrong types) to avoid first-run discovery.
  **Severity:** MEDIUM.
  **Mechanism (LOW):** `runs.create` applies the SDK namespace (`apply_namespace`) — with empty namespace, no-op; harmless.
  **Severity:** LOW.

#### IP-7 — Worker-image packaging
- **Source:** [Tier 3] grpcio wheel availability (cp313 linux x86_64 wheels exist since grpcio 1.66); in-tree Dockerfile (pip install . only), pyproject.toml (dev extra holds pytest).
  **Mechanism (MEDIUM-HIGH — the image can't run the suite):** IP-7 changes the Dockerfile to `pip install .[worker]`; IP-3 runs pytest in the same image. **pytest lives in the `dev` extra** — `.[worker]` does not install pytest, and the Dockerfile does not COPY `tests/`. The test-runner container cannot run the shape/E2E suite as specified. Either the image installs `.[dev,worker]` + `COPY tests/`, or a separate test stage is needed (the pattern rejected a multi-target worker-image but that rejection was about splitting the WORKER image; a test image is a different question).
  **Severity:** MEDIUM-HIGH.
  **Mechanism (LOW):** grpcio on python:3.13-slim amd64 (ubuntu-24.04) has cp313 wheels — no source build expected; the cost is build time + CVE surface on every image (acknowledged by the C4 note). No multi-arch trigger in this CI (amd64 only).
  **Severity:** LOW.
  **Mechanism (LOW — pg client version):** `migrated_db`/`umd_db`/`_postgres_available` use SQLAlchemy+Alembic and psycopg — NO pg_dump in the gate-path suite (verified conftest.py:87-123). The pg_dump 17-vs-pg18 server-major refusal is NOT triggered by the docker-e2e gate scope; it only bites if backup/restore tests enter the in-container scope or UMD_PG_BIN mispoints. Keep the version assertion for the unit/postgres jobs (client-17 against postgres:17 is consistent).
  **Severity:** LOW (conditional).

#### IP-8 — CI gate topology
- **Source:** [Tier 1] pytest-dev/pytest#1364 (fetched — closed, no built-in fail-on-skip: pattern's mechanism is correct); [Tier 3] GitHub required-status-checks troubleshooting (pattern's citation).
  **Mechanism (MEDIUM — sequencing gap):** IP-8 boots the full stack with ONE `--profile sandbox up -d --build`. The worker (and API) start BEFORE the IP-2 mint. With no token env at start, `ClientConfig` raises ("Token must be set" / non-JWT) → worker exits → compose restart-loop → registration never happens → the wait-for-worker line can never be observed. The official flow mints AFTER server up and runs the worker as a later step. The pattern must specify a two-phase up: (a) db + migrate + setup-config + engine + dashboard; (b) mint; (c) api + worker + test-runner with token env. This also fixes the IP-5 API-token gap.
  **Severity:** HIGH (blocks the entire gate).
  **Mechanism (MEDIUM — hook scope):** The fail-on-skip hook must live in the E2E run's conftest ONLY. Placed in the root conftest, it fires in unit/postgres jobs (GITHUB_ACTIONS=true everywhere) and turns legitimate provider-gated skips into failures. Marker deselection (`-m "not postgres"`) does NOT call pytest.skip — it is collection-level deselection, invisible to the hook (correct behavior: deselected is intentional, not vacuous). Actual skip sites in the gate scope: `_require_live_hatchet`, `_require_production_path`, `migrated_db` (postgres-unavailable) — with the full-stack boot these should all be satisfied; the allowlist should be EMPTY in the gate context. `_require_production_path` NOT on the allowlist is correct.
  **Severity:** MEDIUM.
  **Mechanism (LOW — cancelled runs):** `if: always()` also returns true for cancelled workflows; a cancelled run's gate job runs and reports failure (needs.result='cancelled') → the run shows failed instead of cancelled. Add `&& !cancelled()`. The core semantics are correct: a skipped docker-e2e → needs.result='skipped' → gate fails → branch protection (requiring the gate) blocks merge. Verify at plan time that the gate job is listed as a required check and docker-e2e itself is NOT the required check.
  **Severity:** LOW.

---

### Cross-pattern interaction failures

1. **IP-2 × IP-8 (HIGH):** Single `compose up` starts worker/api before the minted token exists → crash-loop (ClientConfig JWT validation). Fix: two-phase up (infra → mint → app). Same fix delivers the token to the API container that IP-5 needs.
2. **IP-2 × IP-3 (HIGH):** The JWT embeds the broadcast address; SDK defaults host_port/server_url from it. Both `cli.py:104-106` (worker) and `_real_client` (test, fallback branch) OVERRIDE host_port from the REST server_url host → wrong gRPC address when server_url host ≠ engine. Fix: remove both overrides (let JWT win) or set explicit `hatchet-engine:7070`.
3. **IP-3 × conftest × compose worker (BLOCKING):** Test engine (throwaway `umd_p1test_*`) vs worker DSN (`umd` DB) diverge; live shape tests can never observe worker commits. Fix: shared `umd_ci` DB + non-truncating live fixture.
4. **IP-4 × IP-6 (HIGH):** retries=0 (SDK) + executor retry ownership is consistent (good), but the queued-row design's key instability (evidence_refs resolved at callback) directly collides with the claim key for INGEST and duplicates rows downstream (IP-4 BLOCKING). retries=0 makes the worker-side validation failures (IP-6) fail fast — correct for the gate.
5. **IP-5 × IP-8 (HIGH):** Probe needs API-container token; gate ordering "probe warm" is unreachable without the two-phase up. Also the probe's REST surface (runs.list) cannot validate the gRPC worker path — pair with the wait-for-worker registration line as gRPC evidence.
6. **IP-7 × IP-3 (MEDIUM-HIGH):** `pip install .[worker]` omits pytest; tests/ not in the image; the test-runner cannot run the suite. Also media-fixture bytes (source objects) unspecified for the real-registry worker (IP-3 MEDIUM-HIGH).
7. **IP-7 × IP-1 (LOW):** pg client major in the image vs pgvector:pg18 `db` — defused for the gate scope (no pg_dump in migrated_db path); conditional if backup tests enter scope.

---

### Severity-ranked risk table

| # | Risk | Severity | Trigger | Matches our use case? | Mitigation in pattern? |
|---|------|----------|---------|------------------------|------------------------|
| 1 | Live shape tests poll a different DB than the compose worker commits to | **BLOCKING** | Every docker-e2e live run | YES — R4 evidence cannot pass | NO — env contract omits DB convergence |
| 2 | Worker/API start before minted token exists; cli.py host_port override points gRPC at the dashboard | **BLOCKING** | First boot as specified | YES — registration never happens | NO — IP-8 single up; IP-3 fixes only the test |
| 3 | IP-4 queued-row key collides with claim key (INGEST stalls) / orphans rows downstream; claim cannot transition | **BLOCKING** | Any live multi-stage submission | YES — DAG never starts / counts break | NO — "key on (job_id, stage, dag_universe)" avoids collision but never transitions |
| 4 | Probe surface mismatch (REST vs gRPC) + API container has no token | HIGH | Every run | YES — capability gate validates wrong surface / never active | Partial — pattern pins runs.list but the claim "gRPC admin surface" is wrong; token handoff missing |
| 5 | `_real_client` fallback `or f"{host}:7070"` derives gRPC host from server_url host | HIGH | UMD_HATCHET_CLIENT_HOST_PORT absent | YES — wrong address whenever env missing | Partial — the fallback itself is the bug |
| 6 | Test image lacks pytest/tests (.[worker] ≠ dev extra) | MEDIUM-HIGH | docker-e2e pytest step | YES — container cannot run the suite | NO |
| 7 | Real-registry media stages need source bytes + OCFL fixtures, not just ffmpeg | MEDIUM-HIGH | Every live shape run | YES — StageCompleted==len(STAGE_ORDER) unreachable | Partial (tooling only) |
| 8 | Fail-on-skip hook scope / cancelled-run gate semantics | MEDIUM / LOW | Root-conftest placement; workflow cancel | Conditional | Partial (pattern says E2E-scoped; add !cancelled()) |
| 9 | AdminClient not actually removed in 1.38.1 (deprecated-but-present) | MEDIUM | Hermetic test asserting absence | YES — mis-specified test would false-fail | NO (pattern premise wrong) |
| 10 | Token TTL mid-suite | LOW (defused) | — | NO — 90-day default | N/A |
| 11 | hatchet-db on pg18 | LOW | PROVISIONAL item | Conditional | YES |
| 12 | grpcio source build / pg client-17-vs-pg18 | LOW | amd64 wheels exist; no pg_dump in gate scope | NO / conditional | N/A |

---

### Verdict

**IP-1..IP-8 (with mitigations) CAN restore the R4 release gate — but NOT as written.** Three BLOCKING items (DB-target divergence, worker-token/host_port sequencing, queued-row claim contradiction) guarantee first-run failure, and they are exactly the class of integration failures the adversary exists to catch: each pattern is internally coherent, and the breakage lives in the seams (fixture DB vs worker DSN; mint timing vs container start; submission key vs claim key). The core architecture — split-topology deploy, mint-per-run JWT, in-network test-runner, fail-closed probe, SDK v1 alignment, gate-on-skip — is sound and evidence-backed. Required amendments before plan time:
1. Encode the shared-DB contract (harness-created `umd_ci` + non-truncating live fixture).
2. Two-phase compose up (infra → mint → app) + remove the cli.py host_port override; deliver the token to the API container.
3. Rework the queued-row persistence so it never occupies the claim key slot and is transitionable or out-of-table.
4. Replace the probe's REST runs.list with a gRPC-path check (or rename semantics + pair with registration evidence).
5. Install `.[dev,worker]` + COPY tests/ for the test-runner; specify OCFL/source-byte fixtures for the real registry.
