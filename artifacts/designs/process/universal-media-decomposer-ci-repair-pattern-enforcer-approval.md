# Universal Media Decomposer CI Repair — PatternEnforcer Approval

**Status:** PASS  
**Gate:** Final DDAuthor design-document validation  
**Date:** 2026-08-28  
**Supersedes:** the raced pre-publication report at this same path, which was
`BLOCKED` solely because it inspected the pending skeleton before DDAuthor's
final DD was written.

## Decision

The final DD is approved without amendment. It is internally consistent,
conforms to the immutable R1–R6 ledger and the verbatim user request, and
provides a downstream implementation/release contract. No production code,
workflow, test, plan, or ADR was edited or created by this gate.

```yaml
status: PASS
coverage: PASS
internal_consistency: PASS
requirement_conformance: PASS
amendment_applied: false
implementation_plan_created: false
production_code_changed: false
unavailable_raw_unit_or_docker_evidence_invented: false
```

## DD validated

- `artifacts/designs/pending/DD-universal-media-decomposer-ci-repair.md`
  (Proposed, 274 lines; final DD)

The DD is a repair/release design, not a claim that the release gate is
currently closed. Its explicit closing statement at lines 262–274 preserves
that boundary.

## Required coverage checks

### User request and immutable ledger

- The authoritative user request is preserved verbatim at DD lines 15–17.
- The immutable R1–R6 ledger is preserved at DD lines 25–36, including:
  hosted GitHub evidence (R1), real diagnosis/no stubs or weakened gates (R2),
  full `Task.md` cross-check (R3), Hatchet-only live execution (R4),
  Support → design → plan → Exec-Manager routing (R5), and local results as
  context only (R6).
- The DD does not silently substitute the longer historical request from the
  regenerated adversarial artifact; it also records that artifact's process
  evidence separately.

### Adversarial and Support flow

- All eight substantive turns T1–T8 are explicitly verified and distilled at
  DD lines 239–249, with completion recorded in
  `artifacts/designs/process/universal-media-decomposer-ci-repair-adversarial-log.md`
  lines 420–425.
- The Support-Librarian briefing, Support-Researcher technology report, and
  Support-Debugger diagnosis are named at DD lines 241–247 and are represented
  in the design's evidence, failure inventory, and handoff.
- The required flow is explicit at DD lines 23, 111–135, and 262–271:
  Support findings → DD → downstream implementation plan → Exec-Manager →
  pushed GitHub implementation → retrieved hosted evidence → final QA/rerun.
- The debugger's `NEEDS_PLAN` classification is retained at DD line 69; the
  design does not route this cross-cutting repair to Exec-Fixer.

### Hosted run 33164294061 and evidence boundaries

The DD's exact run inventory at lines 38–69 covers every failure class:

| Class | DD handling | Evidence boundary |
|---|---|---|
| Missing `python-multipart` | Declare/clean-resolve `python-multipart==0.0.32`; verify import and real multipart ingestion; retain assertions | Hosted unit/Postgres reports and source contract; no invented local proof |
| Missing FFmpeg | Install and version-check FFmpeg; run the real video path; never skip video | Hosted Postgres failures and fixture path |
| Missing PostgreSQL 17 client | Install PGDG `postgresql-client-17`, set `UMD_PG_BIN`, fail backup errors | Hosted Postgres failure and `pg_dump` contract |
| Missing Compose secrets | Export test-only values in every relevant job; retain `${VAR:?}` | Exact hosted interpolation failure and Compose lines |
| Hatchet image denial | Exact-reference preflight and corrected pinned topology; underlying original registry cause remains provisional | Hosted Docker failure proves denial only |
| Worker packaging/config/runtime | Build with `[worker]`, provide complete config, shared runtime assembly, real callbacks | Must be proven by a new hosted run |
| API runner wiring | Use `ProductionDAGRunner`; callback-owned completion | Must be proven by real live execution |
| Capability/gate bypass | Bounded truthful disclosure, full-stack mandatory gate, release inactive = failure | Must be proven by hosted gate and live tests |

The DD explicitly states at lines 9, 52, 61, 93, 152, 184, and 260 that
the raw Docker step-6 log was not retrievable and that no conclusion pretends
otherwise. It records the hosted job/artifact IDs and URLs without promoting
local results or pre-start diagnostics to release evidence.

### Selected architecture and anti-pattern rejection

- Architecture A (coordinated commit-and-wire) plus minimal C (diagnostic
  prove-then-run preflight) is selected at DD lines 71–100.
- The preflight is correctly bounded as a diagnostic tripwire, not functional
  proof and not a scheduler (lines 91–93).
- Lite/release-topology skew, CI-only deferred wiring, opt-in/skip/recording
  doubles, and split-job critical-path substitution are rejected at lines
  102–109.
- The DD repeatedly forbids stubs, unconditional release skips, fake readiness,
  fabricated completion, recording doubles as release evidence, weakened
  assertions, and a second scheduler (lines 11, 30–36, 87–100, 106–109,
  180–184).

### Hatchet, execution, wiring, capability, and packaging

- Hatchet remains the sole v1 scheduler; live registration, callback execution,
  durable `stage_run` evidence, and callback-owned completion are required at
  lines 81–89, 121–129, 141–150, and 186–195.
- `ProductionDAGRunner` wiring is an explicit affected boundary and acceptance
  obligation at lines 63–67, 123–126, and 158–171.
- Capability honesty is preserved: active requires verified live connectivity,
  observed reason/version, and release inactivity is red; local unavailable
  behavior is not release evidence (lines 66, 89, 98, 125, 146, 182–184).
- Worker packaging is explicit: the `[worker]` extra must be installed in the
  shared image and checked in-image; missing-SDK exit-2 behavior remains honest
  (lines 61–64, 119–125, 143–146).
- The SDK/server pair and full topology remain `CANDIDATE`/`PROVISIONAL` until
  real hosted pull, registration, execution, retry, restart, and persistence
  evidence succeeds (lines 13, 61, 89, 135, 152, 180–184).

### GitHub push/retrieval and release gate

The hosted sequencing/evidence contract at DD lines 137–152 requires:

1. Exec-Manager's implementation to be pushed to GitHub with SHA/run identity.
2. Hosted lint, type, unit, and PostgreSQL reports.
3. Exact image preflight, digest capture, full native Compose topology, and
   worker-image smoke evidence.
4. Bounded API/worker readiness plus engine-visible registration.
5. Real `/v1` health/readiness/version/capability checks and live shape tests.
6. HTTP-only heterogeneous correction/invalidation/selective-rerun E2E.
7. Duplicate/retry/late-failure/restart and durable Postgres/OCFL evidence.
8. `if: always()` diagnostics, JUnit/log/image-digest/release-summary uploads,
   machine-readable `live-worker-gate: PASS|FAIL`, final teardown, and then
   GitHub artifact retrieval/inspection.

The DD expressly says a green checkmark cannot override a failed or missing
machine-readable live gate.

### Full `Task.md` DoD matrix

DD lines 197–237 contain a complete numbered matrix for DoD items **1–35**.
Each row has an obligation and required evidence; it covers the adversarial
process, implementation/hosted identity, OCFL persistence, representative
text/image/audio/video, stable locators/provenance, semantics and confidence,
multilingual/adaptation/alignment/resolution, edits, descendant invalidation,
stage rerun, durable restart, queries, provider honesty, heterogeneous
contradictions, HTTP-only correction E2E, Docker, static checks, tests, final
adversarial review, and repair/rerun.

This is an obligation/evidence matrix, not a false declaration that DoD is
already complete; that distinction is explicit at DD lines 197–200.

### Rollback, stop conditions, security, docs, and final QA

- Stop and rollback conditions are explicit at DD lines 180–184, including
  missing/skipped evidence, fallback to `DurableDAGRunner` in hosted release,
  log-only registration, absent callback rows, volume wipes, in-process E2E,
  weakened secrets/assertions, and unilateral pin changes.
- Security obligations for untrusted media, subprocess argument arrays,
  resource bounds, archive/path/symlink safety, parser containment, and
  sandboxing are retained at lines 173–178.
- Documentation is correctly deferred until behavior and workflow evidence
  pass, and must use measured hosted results (lines 176–178).
- Final adversarial QA is mandatory and covers the specified provenance,
  semantic, invalidation, locator, language/adaptation, scheduler/restart,
  storage, media-safety, and capability risks (lines 177–178 and 233–237).

## Internal consistency and provisional-claim review

**PASS.** The DD consistently distinguishes:

- evidence already available (the exact failed hosted run and retrieved JUnit/
  artifact metadata);
- evidence not available (raw Docker step-6 log);
- evidence required later (new pushed hosted run and complete live gate);
- provisional/candidate claims (Hatchet image topology, SDK/server compatibility,
  gRPC values, cold-start timing, exact submission surface); and
- local context only (R6).

The DD's minimal C preflight is not presented as scheduler proof; live callback
registration, real stage execution, public HTTP E2E, retry, and restart remain
separate mandatory gates. No contradiction or material omission was found that
requires amending the final DD.

## Exact artifacts and paths inspected

### Final DD and process artifacts

- `artifacts/designs/pending/DD-universal-media-decomposer-ci-repair.md`
- `artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-ci-repair.md`
- `artifacts/designs/process/universal-media-decomposer-ci-repair-adversarial-log.md`
- `artifacts/designs/process/universal-media-decomposer-ci-repair-librarian.md`
- `artifacts/designs/process/universal-media-decomposer-technology-research.md`
- `artifacts/designs/process/universal-media-decomposer-ci-repair-debugger.md`
- `artifacts/designs/process/universal-media-decomposer-ci-repair-architecture-options.md`
- `artifacts/designs/process/universal-media-decomposer-ci-repair-complexity-review.md`
- `artifacts/designs/process/universal-media-decomposer-ci-repair-estimate.md`

### Governing specification, contracts, and plans

- `Task.md` (full file; DoD lines 1641–1692)
- `artifacts/designs/pending/DD-universal-media-decomposer.md`
- `artifacts/designs/parts/universal-media-decomposer/CONTRACTS.md`
- `artifacts/designs/parts/universal-media-decomposer/HATCHET_LIVE_VALIDATION_HANDOFF.md`
- `artifacts/plans/pending/TASK-universal-media-decomposer-J-api-boundary-ci-release.md`
- `artifacts/plans/pending/TASK-universal-media-decomposer-I-hatchet-worker-integration.md`
- `artifacts/plans/pending/TASK-universal-media-decomposer-G-production-runner-api.md`
- `artifacts/plans/handoff-G-to-I-J.md`

### Referenced implementation/workflow/test surfaces

- `.github/workflows/validation.yml`
- `.github/scripts/wait-for-http.sh`
- `.github/scripts/wait-for-worker.sh`
- `.github/scripts/capture-diagnostics.sh`
- `.github/scripts/record-release-summary.sh`
- `deploy/compose.yaml`
- `deploy/Dockerfile`
- `deploy/pins/runtime.txt`
- `pyproject.toml`
- `src/umd/api/app.py`
- `src/umd/application/jobs.py`
- `src/umd/jobs/runner.py`
- `src/umd/jobs/hatchet.py`
- `src/umd/jobs/production.py`
- `src/umd/jobs/capability.py`
- `src/umd/deploy/cli.py`
- `src/umd/api/routers/sources.py`
- `tests/test_hatchet_live.py`
- `tests/test_api_boundary_e2e.py`
- `tests/test_api_boundary_guardrails.py`
- `tests/test_capability_transitions.py`
- `tests/conftest.py`
- `tests/fixtures.py`
- `tests/test_deployment_phaseE.py`

### Hosted evidence references

- Run: <https://github.com/xiaden/Universeity/actions/runs/33164294061>
- Docker job `98825909849`; artifact `docker-e2e-evidence` `9682930252`
- PostgreSQL job `98825910085`; artifact `postgres-test-results` `9682972550`
- Unit job `98825910133`; artifact `unit-test-results` `9682936266`
- Ruff job `98825909969`
- Tested SHA: `a6b1a62f8413655b9908b40e4fc7a484828364e0`

## Downstream handoff

**Approved recommendation:** derive a bounded implementation plan from the
final DD, preserve its Phase 0 → Phase 4 dependency order, and route execution
to Exec-Manager. Do not treat this approval as plan approval, implementation
approval, or release approval. The next gate is the downstream plan/design
validation, followed by Exec-Manager's pushed implementation and retrieved
hosted evidence.

No material gaps were found; therefore no DD amendment and no validation rerun
were necessary in this pass.
