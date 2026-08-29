# Final Effort Estimate — Plan K Live Hatchet Blocker (SDK 1.38.1 v1 Callback Contract Repair)

- **Agent:** rnd-estimator
- **Date:** 2026-08-29
- **Scope sized:** The selected bounded package from `universal-media-decomposer-plan-k-hatchet-live-blocker-architecture-options.md` (A2′ typed v1 boundary + A1′ mechanical fallback + A3′ additive declaration check), reconciling the binding netns DD AT-16/17/18/19 authority, as it amends the existing Plan K (`TASK-universal-media-decomposer-K-ci-repair-release-gate.md`).
- **Status:** DONE — sizing only. No design changes, no source/test/workflow/DD/plan edits made. This report changes nothing; it measures and sequences the work the Exec path will perform.

---

## Verdict

```yaml
size: MEDIUM
confidence: MEDIUM

scope:
  files:
    modify: 7            # hatchet.py, cli.py, test_hatchet_live.py, validation.yml,
                         # capture-diagnostics.sh, record-release-summary.sh, Plan K
    create: 0            # UmdStageInput lives inside hatchet.py; no new source file
    delete: 0
    total: 7
  sections: 14           # distinct edit locations (see breakdown)
  char_count: 28000      # estimated chars in edit scope, rounded up
  cognitive_weight: 1.48 # 1 + 0.03*(14-1) + 0.015*(7-1)
  weighted_chars: 41440  # 28000 × 1.48

breakdown:
  - layer: adapter/worker   # src/umd/jobs/hatchet.py
    files: 1
    sections: 4
    reason: "UmdStageInput model; handler (input, ctx) signature + direct manifest read; durable_task-only hard-fail registration (suppress removal); _ready tightening; JSON-safe return"
  - layer: cli               # src/umd/deploy/cli.py
    files: 1
    sections: 1
    reason: "Delete len(work_registry) readiness fallback; exact-count-only truthful count"
  - layer: tests             # tests/test_hatchet_live.py
    files: 1
    sections: 5
    reason: "_RecordingClient.durable_task alias; _invoke_callback two-arg; line 1393 two-arg; registration-test honest re-scope; new spec-first contract/negative tests; optional A3' engine-declaration test"
  - layer: hosted evidence   # .github/workflows/validation.yml + scripts
    files: 3
    sections: 3
    reason: "Hosted gate: tenant eligibility/agreement + assignment/runtime, latest-version is_durable=true, callback-owned rows, A3' one-probe; evidence capture + release-summary additions"
  - layer: plan              # artifacts/plans/pending/TASK-...-K-...md
    files: 1
    sections: 1
    reason: "Plan K amendment mapping F-1..F-7 into P2-S4/S5/P3-S3 + Phase 6 gate (exec-planner work; counted lightly, non-implementation)"

pipeline:
  plan_needed: true       # weighted_chars 41.4K >= 32K (MEDIUM) — a plan is required
  dd_needed: false        # weighted_chars < 80K AND architecture already selected
                          # (A2'/A1'/A3' package) AND requirements complete — no new DD
```

---

## Scope (measured, not guessed)

The code is bounded to the diagnosed defect set. Existing sections that will be read and edited
(`wc -c` measured at HEAD `6614b32`):

| File | Section | Chars | Edit |
|---|---|---|---|
| `src/umd/jobs/hatchet.py` | 209–287 `_make_handler` + `handler` | 3,823 | signature → `(input, ctx)`; `payload["input"]["manifest"]` → `input.manifest` |
| `src/umd/jobs/hatchet.py` | 381–448 `HatchetWorkerFactory.start` | 3,805 | durable_task hard-fail (no fallback chain); delete `contextlib.suppress(Exception)`; `_ready = callbacks_bound and bool(registered_workflows)` |
| `src/umd/deploy/cli.py` | 28–133 `worker` | 5,537 | delete `or (len(work_registry)...)` at line 123; exact-count readiness only |
| `tests/test_hatchet_live.py` | 175–202 `_RecordingClient` | 1,000 | add `durable_task` alias recording into `callbacks`/`workflows` |
| `tests/test_hatchet_live.py` | 439–480 `_register_worker`/`_invoke_callback` | 2,021 | `_invoke_callback` → `cb(_direct_input(manifest), _FakeCtx())` |
| `tests/test_hatchet_live.py` | 1035–1080 engine-visible test | 2,220 | honest re-scope (rename + docstring to local-binding shape) |
| `tests/test_hatchet_live.py` | 1348–1395 hermetic connectivity | 2,159 | line 1393 → `cb(sub["input"], _FakeCtx())` |

**New code written** (conservative, rounded up): `UmdStageInput(BaseModel)` (~500c);
spec-first contract + negative tests — one-arg handler raises, v0-wrapped payload raises, missing
`durable_task` fails closed, `mock_run`-shaped input reaches executor (~1,800c); `_RecordingClient.durable_task`
alias (~150c); optional A3′ engine-declaration test (~900c); hosted-gate additions to `validation.yml`
+ `capture-diagnostics.sh` + `record-release-summary.sh` (tenant agreement, assignment/runtime,
latest-version `is_durable=true`, callback-row polling, A3′ one-probe) (~3,000c); Plan K amendment (~2,000c).

**Total ≈ 28,000c**, 14 sections, 7 files. This is a single-layer, cross-cutting-but-bounded repair;
the plan (`plan_needed: true`) is warranted because ≥32K weighted chars means the full edit set no
longer fits comfortably in one reasoning pass. It stays below LARGE and well below EPIC.

**Explicitly NOT in scope** (per the architecture report's out-of-bounds list): no netns/Compose/
seccomp/image/API/DB/token/endpoint/`run_workflow` redesign; no v0→v1 adapter; no `task`↔`durable_task`
dual-path; no readiness subsystem; no async conversion (A4 deferred); no executor/OCFL/ledger/provenance
changes; no second scheduler/worker.

---

## Weighted context / effort

- **Raw char count:** 28,000 (rounded up per conservative-measurement principle)
- **Cognitive weight:** 1.48 (`1 + 0.03×(14−1) + 0.015×(7−1)`)
- **Weighted chars:** **41,440** (≈ 10.4K weighted tokens at ~4 chars/token)
- **Size band:** **MEDIUM** (32K–80K weighted) — multiple files, one layer, one defect family.

The weighted-context result is consistent with the complexity review's verdict (APPROPRIATE,
defect-sized, S1–S6 simplifications applied): the number is not inflated by speculative abstraction
because RA1–RA4 guards (exactly ONE of A2′/A1′, all-durable, no serializer layer, A3′ non-authority)
are already enforced in the design inputs.

---

## Dependencies

1. **Netns DD (binding authority):** AT-16/17/18/19 in `DD-universal-media-decomposer-plan-k-netns-workflow-amendment.md` must be referenced, not duplicated. The estimate implements its contracts; it does not add a parallel gate set.
2. **Prior defects (L7.1/L7.2/L7.3):** suppress removal, readiness truthfulness, and the honest local-test re-scope are prerequisites bundled in this same scope — they cannot be skipped to reduce size.
3. **Tenant requirement (L8/AT-17):** the workflow-side tenant eligibility + identity + assignment/runtime assertion block is preserved verbatim; it is existing DD authority, not new work invented here.
4. **Q2 typed-vs-dict spike:** a minimal strict-mypy spike against the installed pinned `hatchet-sdk==1.38.1` must run FIRST. It selects A2′ (typed) or records the mechanical A1′ (dict) fallback. This is a decision prerequisite, not a size driver (both paths are ~the same scope; A1′ is slightly smaller).
5. **Downstream gate sequence:** DD (rnd-dd-author) → this estimate → PatternEnforcer → Exec-Planner plan amendment → Exec-Manager implementation + hosted rerun → QA. Plan K Phases 1–4 are complete; the amendment targets P2-S4/P2-S5/P3-S3 + Phase 5/6 gates.

---

## Risk / uncertainty

**Confidence: MEDIUM** — the code scope is well-bounded and SDK-verified, but two genuine
uncertainties preclude HIGH:

| # | Risk | Nature | Resolution |
|---|---|---|---|
| B2 | Strict-mypy overload acceptance of the typed `UmdStageInput` path | MEDIUM, pre-implementation (PROVISIONAL per adversarial table row 6) | A1′ recorded fallback if the spike fails; does NOT change size, only which one of A2′/A1′ ships |
| B1 | Durable-slot assignment on v0.105.2 may reproduce queued-but-unassigned | BLOCKING until hosted-proven | First hosted rerun must show ASSIGNED/RUNNING + `v1_task_runtime`/`WorkerAssignEvent` + callback-owned rows; `is_durable=true` alone is not proof |
| B3 | REST `workflows.list()` response/filter shape | MEDIUM, A3′-only | One-probe on first hosted run; A3′ is non-authority so cannot block AT-16/17/18 |
| B4 | Latest-version scoping of `is_durable=true` | MEDIUM | Hosted SQL keys latest `WorkflowVersion` per `umd-<stage>` |
| B5 | Gate polling accepts SDK ack before durable rows exist | MEDIUM | `_poll_until` for rows; never ack-only |
| N2/N3 | Sync-durable deprecation warning; `StageRunRecord` return serialization | LOW, tracked | Keep sync; return JSON-safe ack, durable rows are authority |

The largest uncertainty is **hosted-outcome**, not implementation-size: whether the successor run
to `33229130339`/`99038602321` passes the release gate. If B1 (durable-slot assignment) fails on the
hosted axis, remediation may expand beyond this bounded set (e.g., engine slot configuration) — that
would be a NEW scope decision, not part of this MEDIUM estimate, and must go through the Support →
R&D → plan → Exec route rather than being bolted on.

---

## Recommended sequencing

1. **Pre-implementation spike (B2):** minimal strict-mypy registration spike against pinned
   `hatchet-sdk==1.38.1` → decide A2′ vs A1′. Record the choice; never ship both (RA1).
2. **Production edits (smallest surface first):** `hatchet.py` (UmdStageInput/handler → registration
   durable_task hard-fail → `_ready` tightening) then `cli.py` (readiness fallback deletion).
3. **Test edits:** `_RecordingClient.durable_task` alias → `_invoke_callback`/line-1393 two-arg →
   registration-test honest re-scope → new spec-first contract/negative tests → A3′ declaration test
   (keep-or-drop per Q3; non-authority either way).
4. **Hosted-gate evidence steps:** `validation.yml` + `capture-diagnostics.sh` +
   `record-release-summary.sh` additions (tenant agreement, assignment/runtime, latest-version
   `is_durable=true`, callback-row polling, A3′ one-probe).
5. **Plan K amendment** (exec-planner) mapping F-1..F-7 into the existing phases, then **Exec-Manager**
   pushes the repair SHA and runs the successor hosted run.
6. **Release gate (blocking):** the hosted evidence per AT-16/17/18/19 composed with AT-1–15 must pass
   before any docs/DoD closure (Plan K Phases 5–6). Stop on any assignment, callback-row, tenant,
   durable, skip, or evidence failure.

---

## Gate authority (non-negotiable)

This estimate **cannot downgrade DD_REQUIRED and cannot weaken the hosted gates.** Explicitly:

- The repair is **not** DD_REQUIRED for a new design document — the architecture is already selected
  by the completed options report, and AT-16/17/18/19 authority already exists in the netns DD. This
  MEDIUM size does not add, remove, or alter that authority. DD_REQUIRED standing is determined by the
  design process and netns DD, not by effort size.
- **No gate weakening:** the hosted release gate (AT-19 composition of AT-16/17/18 with AT-1–15,
  non-skippable, release-blocking on any failure/skip/readiness-only/configured-unavailable/stale-
  version/missing-evidence) remains fully binding. The candidate readiness line, the optional A3′
  declaration check, and the release proof are three distinct tiers and must not be conflated.
- L13/L14 ("no skips/stubs/fake readiness/recording doubles as release evidence", "no weakening
  gates") are preserved. The local test re-scope is honest narrowing of a claim, not a gate downgrade;
  the hosted DB+callback evidence remains the sole release proof.
- Plan K Phases 5–6 (docs after evidence; QA/adversarial/DoD closure) cannot be reached until the
  retrieved hosted evidence passes.

---

## Blocker(s)

1. **B1 — Durable-slot assignment on v0.105.2** is the primary blocker: the successor hosted run must
   prove submitted tasks transition QUEUED → ASSIGNED/RUNNING with `v1_task_runtime`/`WorkerAssignEvent`
   and callback-owned `stage_run`/`StageCompleted`/audit rows. QUEUED-with-no-assignment after the
   bounded polling window is a hard failure. This is a hosted-outcome blocker, not a size blocker.
2. **B2 — Strict-mypy overload acceptance** must be resolved by the spike before fixture/test edits
   are expanded; A1′ is the recorded fallback, never a silent substitution.
3. **B5 — Gate polling** must poll for durable rows, never accept an SDK acknowledgement alone.
4. **Q1/Q2 (from the adversarial T8 register)** remain human-judgment gates: Q1 (all-durable posture,
   single path) and Q2 (typed vs dict) must be resolved before implementation commits to fixtures.
   Q3 (A3′ keep/drop) and Q4 (`eviction_policy=None`) are lower-stakes and resolvable at implementation.

---

## Deliverable

**Exact report path:** `artifacts/designs/process/universal-media-decomposer-plan-k-hatchet-live-blocker-final-estimate.md`
**Size / confidence:** MEDIUM / MEDIUM (weighted context 41,440 chars; plan required, no new DD)
**Blockers:** B1 durable-slot assignment (hosted, blocking), B2 strict-mypy spike (pre-implementation),
B5 gate row-polling; plus human gates Q1/Q2.
