# Universal Media Decomposer — Plan K Netns/Network-Namespace Workflow Amendment — FINAL Sizing (workflow-only)

**Status:** DONE — read-only final sizing for the **workflow-only Plan K amendment** (netns/network-namespace recovery). Evidence-backed from the validated adversarial artifact (`ADVERSARIAL-universal-media-decomposer-plan-k-netns-workflow-validated.md`, T1–T8 + Validation Manifest), the architect report (`universal-media-decomposer-plan-k-netns-architecture-options.md`, Option D recommended), the approved anchor DD (`DD-universal-media-decomposer-ci-repair.md`, A + minimal C), Plan K (`TASK-universal-media-decomposer-K-ci-repair-release-gate.md`), Task.md §40, the current `validation.yml`, and direct reads of the affected scripts (`preflight-hatchet-images.sh`, `capture-diagnostics.sh`, `record-release-summary.sh`, `wait-for-worker.sh`) and `deploy/compose.yaml`. No code, workflow, DD, plan, or adversarial-log edit made (L7). Only the estimate artifact is written.
**Date:** 2026-08-29
**Agent:** `rnd-estimator`

## Scope caveat (important)

This estimate sizes the **Plan K workflow-only amendment** defined by the validated adversarial verdict (T8 "Final decision" + Validation Manifest): **no architecture/topology change**; the amendment carries T7's canonical **F1–F10 + F-R18** with the **U1–U8** resolutions and the **Q1–Q8** human decisions. It is bounded to the hosted CI surface (`.github/workflows/validation.yml`, the four `.github/scripts/*`, `deploy/compose.yaml` **without topology change**, one new single-owner startup wrapper, and the AT-1..AT-15 acceptance-test fixtures) plus the Plan K / anchor-DD doc amendments. **No `src/umd/**` product code, no schema, no topology, no scheduler change is in scope** — that is what distinguishes this LARGE from the prior EPIC/LARGE product estimates.

The immutable constraints from the ledger (L1–L9) and the anchor DD (C1–C8) are preserved; the forbidden set (Hatchet Lite, DinD/socket mounts, privileged/unconfined broad bypass, skipping sandbox, optional/trigger-level gate, fake readiness, second scheduler, host networking, blanket retry, `--wait` sole gate) is never re-introduced. **DD_REQUIRED is locked and immutable:** the anchor `DD-universal-media-decomposer-ci-repair.md` already exists and the amendment to it is the planning deliverable this amendment feeds; this estimate does not author or amend it, and the DD amendment gate is not downgradable.

## Pending-input note

**No netns/Plan-K complexity review exists yet** in `artifacts/designs/process/` (only the prior `ci-repair` complexity reviews: `universal-media-decomposer-ci-repair-complexity-review.md` and `-t8.md`). The complexity review for this Plan K amendment is **pending input** and not part of this sizing; it should be reconciled before DDAuthor/Exec-Planner finalizes the amendment. R18 (`33228898244`) tier-1 retrieval (U7/Q2) is likewise pending and blocks amendment finalization.

---

## Executive result

| | |
|---|---|
| **Size tier** | **LARGE** |
| **Confidence** | **MEDIUM** (the enumerated workflow scope is firmly bounded — F1–F10 + AT-1..AT-15 are fully specified by the validated adversarial artifact — but R18 tier-1 is unretrieved, Q1/Q2 remain undecided, and the first green hosted run under the corrected F1 status contract is the unenumerable arbiter of F4/F7; the wrapper's file-vs-inline shape and the U1/U2 pattern-text corrections also land before DDAuthor) |
| **plan_needed** | **true** (weighted_chars ≈ 99K ≫ 32K) |
| **dd_needed** | **true** (weighted_chars ≈ 99K ≥ 80K) — **DD_REQUIRED locked/immutable**; the anchor `DD-universal-media-decomposer-ci-repair.md` exists and the amendment is a workflow-only distillation of F1–F10 + F-R18 |
| **fixComplexity** | **NEEDS_PLAN** (cross-cutting across workflow + 4 scripts + new wrapper + tests + two design docs; not `SIMPLE`/Exec-Fixer eligible) |

The dominant cost driver is **not** the enumerated edits (bounded ≈52K chars) but the **hosted proof loop**: whether the exact anchored netns marker recurs on a clean runner under the corrected `pipefail`/`PIPESTATUS` status contract (F1), with the 3-attempt budget exhausted, is the first-boot arbiter of the F4 escalation verdict; each discovery is gated on a full pushed hosted CI iteration. That unknown — plus the unretrieved R18 (U7/Q2) and the undecided Q1 sandbox-runner role/env — is why confidence is MEDIUM rather than HIGH despite a fully enumerated known shape. It is not LOW because, unlike the prior product estimates, the scope is **workflow-only, fully enumerated, and topology/architecture is off the table** unless new hosted evidence re-opens it.

---

## 1. Formula inputs (measured from the real tree)

Edit-scope chars = the sections being edited plus adjacent context needed to understand them (conservative, rounded up). Tests and the wrapper are included. The two design/plan doc amendments are counted because they are the amendment's own deliverables and are non-trivial contract text (F1–F10 verbatim + AT-1..AT-15).

| Input | Value | Basis |
|---|---|---|
| **Files — modify** | 7 | `validation.yml`, `preflight-hatchet-images.sh`, `capture-diagnostics.sh`, `record-release-summary.sh`, `deploy/compose.yaml` (profile/env only), Plan K doc, anchor DD doc |
| **Files — create** | 2 | single-owner startup wrapper `.github/scripts/startup-compose.sh` (F3/F4/F5/F6/F7); new AT test/fixture file (`tests/test_workflow_startup_contract.py`) |
| **Files — delete** | 0 | None confirmed |
| **Files — total** | 9 | |
| **Sections** (distinct edit locations) | 27 | workflow (8) + scripts (6) + wrapper (5) + compose (1) + tests (3) + docs (4) — §3 |
| **char_count** (edit-scope chars) | 52,000 | Sum of edited sections + required adjacent context; conservative round-up |
| **cognitive_weight** | 1.90 | 1 + 0.03×(27−1) + 0.015×(9−1) = 1 + 0.78 + 0.12 |
| **weighted_chars** | **98,800** | 52,000 × 1.90 |

**Threshold crossings:**

| Threshold | Value | Criteria |
|---|---|---|
| TRIVIAL | < 8K | — |
| SMALL | 8K–32K | — |
| MEDIUM | 32K–80K | — |
| **LARGE** | **80K–320K** | **≈99K → LARGE (low-mid band)** |
| EPIC | ≥320K | Not reached |

The tier is **not fragile to the unenumerable hosted leg**: even doubling char_count to 104K (absorbing first-green-run rework and extra marker-matrix fixtures) yields ≈198K weighted — still LARGE, below the EPIC floor. **EPIC is not warranted**: this is a workflow-only amendment to existing CI/scripts with no product, schema, topology, or scheduler surface, not greenfield creation.

---

## 2. Current tree state verified (evidence for the edits)

Direct reads this pass confirm the amendment's target surface in the working tree:

| Surface | Tree state (verified) | Amendment change |
|---|---|---|
| `validation.yml:313-384` "Start complete split topology" | Single simultaneous `up -d --build` of all 8 services; 3-attempt retry on `grep -q "bind-mount /proc/"`; reconcile loop `ps -a -q` + inspect Status, re-up with output hidden (`>/tmp/compose-reconcile.log 2>&1 \|\| true`) | **F3** four serialized batches + `--profile sandbox` pinning + `COMPOSE_PARALLEL_LIMIT=1`; **F4** exact anchored regex + 3-attempt budget + escalation verdict; **F5/F7** classified reconcile with settle window + visible output |
| `validation.yml:328-330` compose pipeline | `if docker compose ... \| tee /tmp/compose-up.log; then` — **no `set -o pipefail`**; retry observes `tee`'s exit (axonops/audit#622 masking class) | **F1** explicit `PIPESTATUS[0]` shielding idiom (`rc=0; ... \|\| rc=${PIPESTATUS[0]}`) — the single most important change (U1) |
| `validation.yml:248-307` config-gen/JWT | Two-phase tenant discovery + real JWT mint, exported to GITHUB_ENV **before** api/worker creation | **F6** move mint **inside** the wrapper with own-process export + sandbox-runner env parity (T4 Q2 / T8 Q1) |
| `validation.yml:238-240` preflight | `preflight-hatchet-images.sh` runs exact-image manifest tripwire only | **F2** add docker version/info/compose version/network capability snapshot + `docker-capability.txt` (U6/AT-13) |
| `validation.yml:497-509` aggregate gate + `record-release-summary.sh` | Gate reads 3 PASS markers; summary emits live-worker-gate | **F10** gate reads `escalation-verdict.txt` (absent = FAIL); summary adds verdict |
| `validation.yml:516-539` diagnostics/upload | `capture-diagnostics.sh` per-service logs/probes/dump/fixity; upload `if-no-files-found: warn` | **F8** `umd-evidence/` schema wired into capture/upload; **U5** upload → `error` + verdict on all death paths; **U4/AT-15** `sandbox-security.txt` |
| `deploy/compose.yaml` | No custom network / no `network_mode`; sandbox-runner env present | **F3** profile pinning + `COMPOSE_PARALLEL_LIMIT` env + **F6** sandbox-runner env parity; **no topology change** |
| `deploy/security/sandbox-seccomp.json` | Amended P3-S3: full moby-default (414) + pivot_root (415) already in tree | **F9/U4** honest re-documentation + AppArmor/userns diagnostics (AT-15) — doc/security-sign-off, no profile rewrite |

The four `wait-for-*.sh`/`capture-diagnostics.sh`/`preflight-hatchet-images.sh`/`record-release-summary.sh` helpers were read directly; `wait-for-worker.sh` needs at most a minor env-parity touch (F6), counted under compose/validation, not as a separate section.

---

## 3. Workstream breakdown — three streams distinguished

### S — Workflow startup contract (validation.yml docker-e2e + single-owner wrapper)

| Item | File(s) | Sections | ~Chars | Notes |
|---|---|---|---|---|
| Job shell default / pipefail contract | `validation.yml` | 1 | 1,800 | **F1/U3**: job-level `defaults: run: shell: bash -eo pipefail` flip + per-step audit (AT-11) |
| Capability preflight step | `validation.yml` | 1 | 1,600 | **F2** docker/version/network snapshot; named hard failure |
| Serialized-batch startup | `validation.yml` | 1 | 2,600 | **F3** db → migrate+admin → engine+dashboard → api+worker+sandbox; `--no-deps` + `timeout` on every `up` (U2/Q7, AT-12) |
| Exact-marker retry + escalation | `validation.yml` | 1 | 1,400 | **F4** anchored regex + 3-attempt budget + `hosted-netns-escalation` verdict (AT-5) |
| Classified reconcile + settle | `validation.yml` | 1 | 2,200 | **F5/F7** `ps -a` + exit/restart/OOM/error classifier; settle window (Q3, AT-6/AT-7) |
| JWT mint + env parity | `validation.yml` | 1 | 1,200 | **F6** mint inside wrapper; token reaches every worker (AT-4) |
| Aggregate gate + verdict | `validation.yml` | 1 | 900 | **F10** reads escalation verdict, absent = FAIL (AT-8) |
| Diagnostics schema + upload | `validation.yml` | 1 | 1,300 | **F8/U5** `umd-evidence/` + upload `if-no-files-found: error` (AT-8/AT-14) |
| Single-owner startup wrapper (NEW) | `startup-compose.sh` | 5 | 12,500 | **F3/F4/F5/F6/F7** consolidated; sole compose owner; `set -euo pipefail` + shielding idiom; bounded waits; escalation verdict on all death paths |

### H — Helper scripts

| Item | File(s) | Sections | ~Chars | Notes |
|---|---|---|---|---|
| Capability preflight | `preflight-hatchet-images.sh` | 2 | 2,800 | **F2** + `docker-capability.txt` (U6/AT-13) |
| Diagnostics schema | `capture-diagnostics.sh` | 3 | 3,200 | **F8** daemon/network/inspect/restart/error; **U4/AT-15** `sandbox-security.txt` |
| Release summary | `record-release-summary.sh` | 1 | 1,200 | **F10** escalation-verdict table |
| Compose env/profile | `deploy/compose.yaml` | 1 | 700 | **F3/F6** profile pinning + env parity; no topology |

### T — Acceptance tests and design/plan docs

| Item | File(s) | Sections | ~Chars | Notes |
|---|---|---|---|---|
| AT-1..AT-15 fixtures (NEW) | `tests/test_workflow_startup_contract.py` | 3 | 9,500 | shielding-idiom fixture (AT-1/U1); marker/budget matrix (AT-5); classifier/reconcile (AT-6/AT-7); config tripwire (AT-3); token-complete (AT-4); artifact-listing (AT-8); EPERM-class (AT-9); R18 checklist (AT-10) |
| Plan K amendment | `TASK-...-K-ci-repair-release-gate.md` | 2 | 7,000 | P3-S3 startup contract, P3-S4/S5, Phase 6 R18 ledger obligation |
| Anchor DD amendment | `DD-universal-media-decomposer-ci-repair.md` | 2 | 3,500 | F1–F10 + F-R18 contract text, acceptance criteria |

---

## 4. Confidence and risk register (U1–U8, Q1–Q8 carried verbatim-in-spirit)

The validated adversarial artifact's **Unresolved Risks (U1–U8)** and **Human Questions (Q1–Q8)** are binding inputs to execution. They are recorded here as the estimate's risk register (they materially affect scope, not the LARGE tier):

**Risks affecting scope/completion:**
- **U1 (BLOCKING):** `PIPESTATUS` capture unreachable under `set -e` as written in T7 F1 — must be rewritten with the shielding idiom `rc=0; docker compose … 2>&1 | tee "$log" || rc=${PIPESTATUS[0]}` (or `if`/`!`) before DDAuthor writes the amendment (AT-1). Pattern-text correction, not design change.
- **U2 (HIGH):** `up`-level hang / one-shot re-trigger (`service_completed_successfully`) — encode `--no-deps` on batches 3/4 + explicit `timeout` on every `up` into F3/F5 (Q7, AT-12).
- **U3 (MEDIUM):** job-level `defaults: run: shell: bash` blast radius — per-step pipefail audit required (Q8, AT-11).
- **U4 (MEDIUM/HIGH):** seccomp profile honesty — actual `sandbox-seccomp.json` is an ungated ~415-syscall allowlist, not "moby default + pivot_root"; human security sign-off + AppArmor/userns diagnostics required (Q6, AT-15). **Security-posture decision, not a netns one.**
- **U5 (MEDIUM):** upload `if-no-files-found: warn` → `error`; verdict file on all death paths (AT-14).
- **U6 (MEDIUM):** Docker version marker drift (runner 28.0.4 today, v29 pending) — re-validate F4 regex on major-version change (AT-13).
- **U7 (OBLIGATION):** R18 tier-1 re-retrieval blocks amendment finalization (Q2, AT-10). **Hosted-proof uncertainty — the single biggest confidence drag.**
- **U8 (PROCESS):** source artifact order anomaly — resolved in the validated artifact; consumers must read T6 before T7.

**Human decisions (Q1–Q8) blocking or bounding execution:**
- **Q1 (blocks next hosted run):** sandbox-runner role/env — option a (mandatory gate, full Hatchet env parity, recommended) vs option b (named gated capability). Security-posture/product call.
- **Q2 (blocks finalization):** R18 tier-1 re-retrieval + ledger-row update.
- **Q3:** reconcile settle-window (proposed 60s/5s). **Q4:** daemon-reachability budget (proposed 120s/5s). **Q5:** `COMPOSE_PARALLEL_LIMIT=1` via env. **Q6:** seccomp profile sign-off. **Q7:** `--no-deps` + `timeout` on every `up`. **Q8:** job-level shell default audit.

**Dependencies:** the amendment is gated on (1) the U1 shielding-idiotn pattern-text landing in F1 before DDAuthor writes the amendment; (2) Q1 (sandbox-runner role) decided before the next hosted run; (3) R18 tier-1 retrieval (U7/Q2) before finalization; (4) a **first green hosted run** as the validation arbiter of F4/F7 (the escalation branch has never executed in production). The **hosted proof loop** is the unenumerable cost driver; each discovery iteration is gated on a full pushed hosted CI run.

**DD_REQUIRED:** **locked/immutable** — the anchor `DD-universal-media-decomposer-ci-repair.md` exists (A + minimal C; workflow-only amendment) and the DD amendment is the planning deliverable this sizing feeds. Not downgradable.

---

## 5. Threshold and pipeline

```yaml
size: LARGE
confidence: MEDIUM

scope:
  files:
    modify: 7
    create: 2
    delete: 0
    total: 9
  sections: 27
  char_count: 52000
  weighted_chars: 98800

breakdown:
  - layer: workflow-startup
    files: 2          # validation.yml + new startup-compose.sh wrapper
    reason: "F1-F7 + F10: serialized batches, exact-marker retry/escalation, classified reconcile, JWT-mint-in-wrapper, verdict gate"
  - layer: helper-scripts
    files: 4          # preflight-hatchet-images.sh, capture-diagnostics.sh, record-release-summary.sh, compose.yaml (env/profile)
    reason: "F2 capability preflight, F8 umd-evidence schema, U5 verdict-on-all-paths, sandbox security diagnostics (AT-15)"
  - layer: acceptance-tests
    files: 1          # new tests/test_workflow_startup_contract.py
    reason: "AT-1..AT-15: shielding idiom, marker/budget matrix, classifier/reconcile, tripwire, escalation gate, EPERM, R18 checklist"
  - layer: design-plan-docs
    files: 2          # Plan K + anchor DD amendments
    reason: "F1-F10 + F-R18 contract text verbatim + acceptance criteria"

pipeline:
  plan_needed: true    # weighted_chars 98800 >= 32K
  dd_needed: true      # weighted_chars 98800 >= 80K (DD_REQUIRED locked; anchor DD exists, amendment is the deliverable)

risks:
  - "U1 BLOCKING: PIPESTATUS shielding idiom must land in F1 before DDAuthor writes the amendment (AT-1)"
  - "U2 HIGH: --no-deps + timeout on every compose up (Q7, AT-12)"
  - "U4 MEDIUM/HIGH: seccomp profile honesty + human security sign-off + AppArmor/userns diagnostics (Q6, AT-15)"
  - "U7/Q2 OBLIGATION: R18 tier-1 re-retrieval blocks finalization - hosted proof uncertainty"
  - "Q1: sandbox-runner role/env undecided - blocks the next hosted run"
  - "First green hosted run under the corrected F1 status contract is the unenumerable arbiter of F4/F7"
  - "Complexity review for this Plan K amendment is pending input (not yet in artifacts/designs/process/)"

notes: >
  Workflow-only Plan K amendment; NO architecture/topology change (validated adversarial verdict, T1-T8
  consensus). Preserves L1-L9 and the forbidden set (Lite, DinD/socket, privileged/unconfined bypass,
  skipping sandbox, optional gate, fake readiness, second scheduler, host networking, blanket retry,
  --wait sole gate). Topology re-opens ONLY on new hosted evidence (tier-1 R18 contradiction, or the exact
  anchored marker recurring on a clean runner under the corrected F1 contract with the 3-attempt budget
  exhausted). No product code (src/umd/**), schema, or scheduler change in scope.
```

---

## 6. Artifact lineage and handoff

- **Inputs:** `artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-plan-k-netns-workflow-validated.md` (T1–T8 + Validation Manifest, canonical F1–F10 + F-R18, U1–U8, Q1–Q8); `universal-media-decomposer-plan-k-netns-architecture-options.md` (Option D, bounded hybrid, recommended); `artifacts/designs/pending/DD-universal-media-decomposer-ci-repair.md` (anchor, A + minimal C); `artifacts/plans/pending/TASK-universal-media-decomposer-K-ci-repair-release-gate.md`; `Task.md` §40; `.github/workflows/validation.yml`; `.github/scripts/{preflight-hatchet-images.sh,capture-diagnostics.sh,record-release-summary.sh,wait-for-worker.sh}`; `deploy/compose.yaml`; `deploy/security/sandbox-seccomp.json`.
- **Deliverable:** this estimate (`universal-media-decomposer-plan-k-netns-final-estimate.md`).
- **Handoff to DDAuthor/Exec-Planner (L8):** distill F1–F10 + F-R18 with the U1–U8 resolutions and Q1–Q8 decisions into the Plan K amendment and the anchor DD amendment; U1 pattern-text correction must land first; Q1 and Q2 block execution/finalization respectively; acceptance = AT-1..AT-15 pass in a `test` job before the first amended hosted run.
- **Pending inputs:** netns complexity review (absent, to be reconciled); R18 tier-1 retrieval (U7/Q2).

**Read-only scope honored:** no code, workflow, DD, plan, or adversarial-log edit; only this estimate artifact was created.
