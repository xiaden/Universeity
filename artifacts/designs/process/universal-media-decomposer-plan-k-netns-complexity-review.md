# Universal Media Decomposer — Plan K Netns/Network-Namespace Workflow Amendment — Semantic Complexity Review

**Agent:** rnd-complexity-advisor
**Date:** 2026-08-29
**Scope:** Read-only structural review of the recommended bounded workflow amendment carried by the validated adversarial artifact `artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-plan-k-netns-workflow-validated.md` (T7 canonical F1–F10 + F-R18; T8 U1–U8, Q1–Q8, AT-1..AT-15) against the current tree (HEAD `6614b32`), the approved DD (`DD-universal-media-decomposer-ci-repair.md`), Plan K (`TASK-universal-media-decomposer-K-ci-repair-release-gate.md`), the architect report (`universal-media-decomposer-plan-k-netns-architecture-options.md`), and the support corpus (librarian/researcher/architect logs, prior complexity findings L8/L9).
**Verdict preview:** The amendment's **core is justified, evidence-backed complexity** (exact-marker bounded retry, fail-closed state reconciliation, status-capture correctness, one-shot exit classification, sandbox security classification, evidence schema, escalation verdict). It is **not** a topology change and preserves every L9 invariant. However, roughly one-third of the amendment's machinery is **reducible excess**: per-batch retry budgets, a fourth startup batch, a 120s daemon-reachability preflight budget for an unobserved failure class, `docker wait` + `timeout` machinery that duplicates the existing bounded polling, a job-wide shell-default flip that creates a blast-radius audit, and wrapper-consolidation forcing an own-process JWT export that the current step structure already achieves. **One defect is BLOCKING and must be corrected before DDAuthor writes the amendment: T7 F1's PIPESTATUS idiom is self-defeating under `set -e` (T8 U1).** No code, workflow, DD, or plan edits were made by this review (L7).

---

## 1. Inputs consumed and verification method

All claims below were verified by direct reads of the validated artifact, the current tree, and the artifact corpus on 2026-08-29:

| Input | Used for |
|---|---|
| `ADVERSARIAL-universal-media-decomposer-plan-k-netns-workflow-validated.md` (full: ledger, T1–T8, Validation Manifest) | The amendment under review: F1–F10, F-R18, U1–U8, Q1–Q8, AT-1..AT-15 |
| `universal-media-decomposer-plan-k-netns-architecture-options.md` (architect, `DONE`) | Option D = the recommended hybrid workflow amendment; rejection table; evidence boundary |
| `TASK-universal-media-decomposer-K-ci-repair-release-gate.md` (Plan K, Phases 1–6) | P3-S3 startup/reconcile contract, P3-S4 preflight, P3-S5 diagnostics, P2-S4 JWT, Phase 6 QA/DoD |
| `DD-universal-media-decomposer-ci-repair.md` (approved anchor) | A + minimal C, full split Hatchet, sole scheduler, mandatory hosted validation, no skips/stubs/fake readiness, no second scheduler |
| `Task.md` §40 (DoD 1–35, esp. 31 Docker deployment, 33 tests, 34 adversarial review, 35 rerun) | Immutable release matrix (L3) |
| `.github/workflows/validation.yml` (current) | Config-gen + JWT mint step :248-307; start-topology retry :322-345; reconcile :346-384; aggregate gate :497-509; upload list :526-539 |
| `deploy/compose.yaml` (current) | Split topology; one-shot `restart: on-failure` :148,:176; `service_completed_successfully` :173,:195-197,:215-218; sandbox `profiles: ["sandbox"]` :235 and missing Hatchet env :236-241; worker env :120-122; sandbox `restart: unless-stopped` :251 |
| `.github/scripts/{preflight-hatchet-images.sh, capture-diagnostics.sh, record-release-summary.sh}` | Existing preflight/diagnostics/summary surfaces the amendment touches |
| `deploy/security/sandbox-seccomp.json` | `defaultAction: SCMP_ACT_ERRNO`, flat ungated ~415-syscall allowlist (T8 U4 claim verified structurally) |
| Logs: `rnd-architect` L8-L10, `support-librarian` L19-L20, `support-researcher` L6-L8, `rnd-complexity-advisor` L8-L9 (prior session) | Support findings and prior complexity dispositions for the same amendment |
| Prior review precedent `universal-media-decomposer-ci-repair-complexity-review.md` | Output format/verdict conventions |

**Technology validation:** the amendment introduces no new technology (bash, Docker/Compose, GitHub Actions, hatchet-admin token, bubblewrap are all already in the tree or already validated by T6/T7/T8 against current official sources with 2026-08-29 check dates). The two technology claims I rely on are (a) GitHub Actions' documented shell semantics (`bash -e {0}` default vs `bash --noprofile --norc -eo pipefail {0}` — per T7 F1 citations, checked 2026-08-29) and (b) Docker Compose env/flag precedence for `COMPOSE_PARALLEL_LIMIT` (env ignored when the flag is given — per T6 §4/T7 F3, checked 2026-08-29). Both are already in the validated artifact; I do not introduce new version claims. Check date for all citations below: **2026-08-29**.

## 2. What is under review

The validated artifact's recommendation is a **workflow-only Plan K amendment** carrying, verbatim, **F1** bash/pipefail status contract, **F2** two-phase preflight (Class A daemon-reachability 120s/5s; Class B capability hard-fail), **F3** four serialized batches + `--profile sandbox` pinning + `COMPOSE_PARALLEL_LIMIT=1` (env) + `config --services` topology tripwire, **F4** exact-marker anchored regex + 3-attempt budget + escalation verdict, **F5** one-shot first-exit rule + `timeout 300` engine waits, **F6** JWT mint inside the wrapper with own-process export + sandbox-runner env parity, **F7** per-batch + final full-set reconcile with classified re-up and 60s/5s settle window, **F8** `umd-evidence/` schema wired into capture/upload, **F9** independent sandbox seccomp classification, **F10** aggregate gate reads `escalation-verdict.txt` (absent = FAIL), plus **F-R18** the R18 ledger-row re-retrieval obligation. T8 adds unresolved risks U1–U8, human questions Q1–Q8, and acceptance tests AT-1..AT-15.

Indirection count (entry → work): workflow step → `compose-start.sh` wrapper → preflight + phase-2 `up` → `docker inspect`/`ps -a` reconcile → aggregate gate. That is 3–4 hops, consistent with a CI startup state machine and comparable to the existing workflow's hop count. The count is not itself the problem; the problem is machinery inside individual hops.

## 3. Mandatory-item disposition (the ten review items)

| # | Item under review | Disposition | Rationale |
|---|---|---|---|
| 1 | **Duplicate T5 / physical order reconciliation** (T7 R1, T8 U8) | **RESOLVED — keep the validated artifact's canon; no further machinery** | The two T5 sets are an artifact-integrity defect, not engineering complexity. The Validation Manifest already designates the canonical T5 (IP-1–IP-10), merges the three unique first-T5 details (evidence-dir layout, 60s/5s settle, 120s/5s reachability) into F2/F7/F8, and flags the stale T7 "no T6 exists" statement. Consumers must read T6 before T7 and quote F1–F10, never either T5 alone. No code/plan change follows from this item. |
| 2 | **pipefail/PIPESTATUS idiom** (F1, U1) | **BLOCKING — must be corrected (pattern-text), then KEEP** | F1 as written ("capture `rc=${PIPESTATUS[0]}` on the line immediately after every compose pipeline") is self-defeating under `set -e` (T8 U1): a bare failing pipeline exits the script before the capture line runs, making the retry/reconcile branches dead code in exactly the failure state F1 exists for. Fix is one line: `rc=0; docker compose … 2>&1 \| tee "$log" \|\| rc=${PIPESTATUS[0]}` (the `\|\|` RHS is exempt from `set -e`). The correction *is* the simplification — no extra machinery. |
| 3 | **Preflight / daemon reachability** (F2, R3, Q4) | **SIMPLIFY — drop the 120s/5s Class A wait; keep Class B capability assertions as hard fails** | R10–R18 contain **zero** instances of an unreachable-not-yet-up daemon at step start; every observed failure was mid-start (netns race, seccomp EPERM, compose-exit-0-with-Created). A budgeted wait (120s/5s) with its own escalation routing is speculative machinery for an unobserved class. The valuable parts of F2 are (a) recording `docker version`/`compose version` into `docker-capability.txt` (keeps U6 version-drift detection alive) and (b) Class B immediate hard-fail on denied image / `compose config` failure. The existing `preflight-hatchet-images.sh` already covers the image half of Class B. |
| 4 | **Serialization / profile / topology tripwire** (F3, R4, U2, Q5) | **SIMPLIFY — collapse four batches to the two-phase structure the workflow already has; keep `--no-deps`, `COMPOSE_PARALLEL_LIMIT=1`, and the tripwire** | The current workflow already runs phase 1 (`db`+`hatchet-migrate`+`hatchet-admin` + config poll + JWT mint, :248-307) then phase 2 (everything else, :313-385). The amendment's marginal fourth batch (engine+dashboard separate from api+worker+sandbox) adds a batch state machine whose ordering benefit is already delivered by compose `depends_on` (worker→engine `service_started`; api→db `service_healthy`) **plus** `COMPOSE_PARALLEL_LIMIT=1`. The genuinely mandatory fixes are: (a) phase 2 must **not re-list migrate/admin** and must use `--no-deps` — the current all-8 re-up re-triggers the one-shot `service_completed_successfully` chain on *every* reconcile attempt (U2's #10985/#11808 class, already latent at :328-330/:375-377); (b) `COMPOSE_PARALLEL_LIMIT=1` via env (valid per current docs; env survives flag-precedence bugs); (c) the `config --services` full-8-set tripwire (cheap, prevents silent topology reduction). |
| 5 | **JWT / env parity** (F6, R5, Q1) | **SIMPLIFY — keep the mint step boundary; do NOT build own-process export or sandbox env-parity before Q1** | The token-at-container-create invariant is already satisfied by the current two-step structure (mint step writes `$GITHUB_ENV`; containers created in a later step read it). The own-process export machinery in F6 is only *needed* because F3 consolidates mint+phase-2 into one wrapper step — a coupling F3 forces and F6 pays for. Keep the step boundary; the wrapper reads env like today. **sandbox-runner env parity (option a) must not be built before Q1**: giving sandbox-runner the token + `command: ["worker"]` registers a *second* `umd-worker` with a materially different execution environment (read-only root, cap_drop ALL, tmpfs) — stage work would be non-deterministically assigned across two differently-isolated workers. That is a product/security decision, not workflow plumbing. |
| 6 | **Retries** (F4, R6) | **SIMPLIFY — one shared 3-attempt budget for the startup phase, not 3-per-batch; KEEP the anchored regex, escalation verdict, negative-test matrix** | The anchored regex (excluding the `lstat` class, moby/moby#46490), the budget, `--no-build` after attempt 1, and the `hosted-netns-escalation: TRUE` verdict are all evidence-backed and mandatory. The per-batch budget multiplication (3×4 = 12 potential attempts) multiplies the retry state machine for no added safety — the marker is a startup-phase phenomenon, and the reconciliation gate (F7) already bounds per-batch failure. One budget, one escalation verdict file. |
| 7 | **One-shot handling** (F5, R7, L9) | **SIMPLIFY — keep first-nonzero-exit classification via `docker inspect`; drop `docker wait` + `timeout 300` machinery** | The first-nonzero-`ExitCode` rule and the `RestartCount`/`Restarting` classifier are mandatory (R17 false-absence, restart-loop class). But the workflow already has bounded completion signals that fail closed: the `/hatchet/config` poll, the 30×2s tenant-discovery poll, and the JWT mint (which requires the tenant row, hence completed migrate). `docker wait` + `timeout 300` is a second wait primitive duplicating those polls; keeping both is redundant surface. Classify via inspect; wait via the existing polls. |
| 8 | **Diagnostics / upload / gate** (F8/F10, R9, U5) | **KEEP — justified; two one-word changes (U5)** | One `umd-evidence/` dir per run with fixed filenames + whole-dir artifact glob + labeled compose logs is the *minimum* that makes a failed marker-retry post-hoc classifiable (the whole point of F8). Gate reading `escalation-verdict.txt` (absent = FAIL) closes the green-gate-files-on-escalated-run hole. Apply U5: `if-no-files-found: error` for the evidence dir; write the verdict on trap paths. Minor: `record-release-summary.sh:73` still calls sandbox-runner "Required" — must be reconciled with the Q1 decision (honest `OPTIONAL`/profile-gated unless Q1 selects option a). |
| 9 | **Sandbox security distinction** (F9, R10, Q6) | **KEEP — mandatory, and already minimal** | R16/R17 prove the seccomp/AppArmor/userns class is distinct from netns. The rule (any `statx`/`fsmount`/`getcwd`/`vfork`/`clone`/`unshare` EPERM in sandbox logs → security-class hard failure, never consumes netns budget) is a classifier, not machinery. Carry U4/Q6: the actual `sandbox-seccomp.json` is an ungated ~415-syscall allowlist (`defaultAction: SCMP_ACT_ERRNO`), not "moby default + pivot_root" — re-document honestly and obtain human security sign-off; specify the `sandbox-security.txt` fields (AT-15). |
| 10 | **R18 tier caveat** (F-R18, U7, Q2) | **KEEP — honest labeling, no machinery** | R18 corroborated at coordination tier only; tier-1 GitHub re-retrieval is a binding Phase 6 obligation before the ledger row is finalized. Zero engineering cost; prevents over-reading the strongest support for the whole A′ shape. |

## 4. Justified complexity (keep — do not reduce)

The following are **requirement- and evidence-mandated**. Any attempt to simplify them would weaken a proven failure class or an L9 invariant:

1. **The fail-closed state reconciliation gate (F7 core + commit `2d84d07`).** R15 proved `compose up` can exit 0 with services still `Created`; R18 proved the reconcile loop recovered a swallowed marker fail-closed. This is the deterministic gate; L3 forbids weakening it. The amendment only strengthens the *evidence* it reads (inspect ExitCode/RestartCount/State.Error, `ps -a`, labeled non-suppressed re-up logs). KEEP.
2. **Exact-marker bounded retry with anchored regex (F4 core).** R10/R11/R18 show the marker recurs; the anchored regex (variable pid/id only, `lstat` class excluded) is the *narrowing* that prevents retrying other `/proc` bind-mount failures and the EPERM/OOM/one-shot classes. The committed negative-test matrix (AT-5) is a small shell test that converts the taxonomy into a hermetic regression. KEEP.
3. **Bash-only status contract, scoped (F1 core).** R18 empirically showed pipefail was off and the marker was swallowed by `| tee`. The *correct* status contract (shielding idiom, U1) is the single most important line of the amendment. KEEP — with the U1 correction and the scope reduction in S3 below.
4. **Independent sandbox security classification (F9).** Distinct root cause, distinct fail route, no budget mixing. KEEP unchanged.
5. **Evidence schema + escalation verdict (F8/F10).** The whole design depends on "the first green run is F4's first real test"; without the evidence dir and the verdict file, a budget-exhausted run is indistinguishable from a green-gate run. KEEP.
6. **`--no-deps` + explicit `timeout` on every compose `up` (U2 mitigation).** Not extra machinery — it is the *removal* of a hang class (compose re-runs `service_completed_successfully` deps on every `up`). KEEP as part of the simplified F3/F5.
7. **Topology tripwire (`config --services` full-set assertion).** A one-command guard against silent topology reduction by profile/selection error. KEEP.
8. **R18 ledger-row obligation (F-R18) and the honest preflight/capability snapshot naming** (F2's "capability snapshot, never a readiness proof"). Both are zero-machinery honesty contracts. KEEP.

## 5. Concrete simplifications (findings)

### S1 (BLOCKING — correction, not reduction): F1's PIPESTATUS capture is unreachable under `set -e` (T8 U1)

- **Location:** T7 F1; maps to Plan K P3-S3 job-level shell contract.
- **Concern:** "`rc=${PIPESTATUS[0]}` captured on the line immediately after every compose pipeline" — under `set -e` the failing pipeline aborts the script first (bash `set` builtin exception list). The retry branch stays dead code in the exact ON state F1 creates.
- **Alternative (simpler and correct):** shield with `\|\|`: `rc=0; docker compose … 2>&1 \| tee "$log" \|\| rc=${PIPESTATUS[0]}`. The `\|\|` RHS is exempt from `set -e`; `PIPESTATUS[0]` still refers to the compose pipeline. Branch retry/reconcile on `rc` **and** the marker classification, never on the bare pipeline.
- **Confidence:** HIGH (bash semantics verified; T8 U1 already names it; T8's amended AT-1 is the direct regression test).
- **Disposition:** must land in F1's pattern text before DDAuthor writes the amendment. Do not attempt to "simplify" by dropping the status contract — that is the R18 regression.

### S2 (HIGH): Four startup batches → the two-phase structure already in the workflow

- **Location:** T7 F3; maps to Plan K P3-S3 startup contract.
- **Concern:** The amendment's batch split (db → migrate+admin → JWT → engine+dashboard → api+worker+sandbox) adds a per-batch state machine whose marginal value over the existing two-phase shape (config-gen step :248-307, full-stack step :313-385) is ordering that compose `depends_on` + `COMPOSE_PARALLEL_LIMIT=1` already deliver.
- **Alternative:** Phase 1 = `db`+`hatchet-migrate`+`hatchet-admin` + config poll + JWT mint (unchanged shape); Phase 2 = one `up --build --no-deps` for `hatchet-engine hatchet-dashboard api worker sandbox-runner` with `COMPOSE_PARALLEL_LIMIT=1` set via env, then the final full-set reconcile + tripwire. `--no-deps` is safe because the config-gen phase already proves migrate/admin completion (the JWT mint requires the tenant row). The race-window narrowing R10 calls for comes from `=1` serialization, not from batch count.
- **Confidence:** HIGH that ordering/topology invariants are preserved; MEDIUM on the marginal race-window equivalence (only the first green hosted run can measure it — which F8's evidence schema is designed to do).
- **Disposition:** amend F3's batch table to two phases; keep the tripwire, `--no-deps`, and the parallel-limit env var. This also removes the "per-batch retry" multiplication from S4.

### S3 (HIGH): Drop the job-wide `defaults: run: shell: bash` flip; scope bash to the compose-owning scripts

- **Location:** T7 F1; U3 (per-step audit AT-11).
- **Concern:** Flipping the docker-e2e job default to `bash -eo pipefail` changes the semantics of **every** inline step (including the `pytest | tee` steps), requiring the U3 per-step audit (AT-11) before the flip — a new workstream to manage a change only ~3 scripts need.
- **Alternative:** The compose-owning scripts carry `#!/usr/bin/env bash` + `set -euo pipefail` internally and are invoked explicitly as `bash script.sh` in the workflow (double-pin: shebang + invocation). Inline `run:` steps that own a compose pipeline use `bash -eo pipefail -c '...'` or are extracted to the script. Non-compose steps (pytest/tee) keep today's semantics — the pipefail behavior they need is already handled by their existing `set -o pipefail` + `\|\|`-guarded patterns or `|| true` JUnit-skip handling.
- **Confidence:** HIGH (confines the change; removes the AT-11 audit workstream; U3's blast-radius risk vanishes).
- **Disposition:** amend F1 to scope the interpreter contract to scripts that own compose pipelines; delete AT-11 as a prerequisite.

### S4 (HIGH): One shared retry budget, not 3-per-batch

- **Location:** T7 F4; maps to Plan K P3-S3 retry contract (:322-345 replacement).
- **Concern:** "3 attempts per batch" × 4 batches = 12 potential `up` invocations; the per-batch bookkeeping (which batch, which budget) is a state-machine multiplication for a startup-phase phenomenon.
- **Alternative:** One 3-attempt budget for the entire startup phase (phase-2 `up`), attempts counted from visible compose output under the corrected F1 status contract, `--no-build` after attempt 1, 5s backoff, escalation verdict written once on exhaustion. Reconcile failures that are *not* the exact marker are hard fails without budget consumption (per F7's classified re-up).
- **Confidence:** HIGH (single phenomenon, single budget; F7's reconcile already bounds per-batch failure).
- **Disposition:** amend F4 text; the escalation verdict file and F10 gate read stay identical.

### S5 (MEDIUM-HIGH): Drop F2 Class A daemon-reachability wait (120s/5s)

- **Location:** T7 F2; T8 Q4.
- **Concern:** No hosted run (R10–R18) shows an unreachable daemon at step start; every observed failure is mid-start. A 120s/5s budgeted wait with escalation routing is speculative machinery for an unobserved class, and it introduces a new flake surface (a wait that burns 120s on a genuinely-broken daemon).
- **Alternative:** A single `docker version --format '{{.Server.Version}}'` + `docker compose version` recorded into `docker-capability.txt` (U6 version-drift tripwire preserved). Capability assertions (denied image — already in `preflight-hatchet-images.sh`; `compose config` failure) are immediate hard fails with diagnostics. If the daemon is genuinely down, phase-2 `up` fails fast with a clear non-marker error that is a hard fail — the same outcome Class A escalates to, without the wait.
- **Confidence:** MEDIUM-HIGH (the failure class is unobserved; the cost of being wrong is a fast hard-fail rather than a wait-and-escalate, and Q4 was a human-approval parameter anyway).
- **Disposition:** amend F2 to "capability snapshot + Class B hard fails"; drop the Class A budget and its escalation branch; keep only the single escalation route owned by F4.

### S6 (MEDIUM-HIGH): Drop `docker wait` + `timeout 300` machinery from F5

- **Location:** T7 F5.
- **Concern:** The workflow already owns bounded, fail-closed completion signals: the `/hatchet/config` poll (config-gen step), the 30×2s tenant-discovery poll, and the JWT mint (tenant-row dependency). `docker wait` + `timeout 300` on every engine-level wait is a second wait primitive that duplicates those polls.
- **Alternative:** One-shot completion = the existing polls; one-shot classification = `docker inspect --format '{{.State.ExitCode}}'`/`{{.RestartCount}}`/`{{.Restarting}}` (first non-zero `ExitCode` = hard failure, per F5). The first-exit rule and the classifier stay; only the blocking-wait primitive is dropped. The `timeout` requirement survives in exactly one place: an explicit `timeout` on every compose `up` (S2/U2), which bounds the U2 hang class.
- **Confidence:** MEDIUM-HIGH (the polls demonstrably fail closed today; no hosted evidence shows a need for `docker wait`).
- **Disposition:** amend F5 to remove the `docker wait` fixture from AT-6; keep the first-exit classifier fixtures.

### S7 (MEDIUM): Keep the JWT mint step boundary; drop F6 own-process export machinery

- **Location:** T7 F6.
- **Concern:** F6's "wrapper exports the minted JWT into its own process environment before Batch 4" exists only because F3 consolidated the mint into the wrapper step. The current two-step structure (mint step → `$GITHUB_ENV` → later container-creation step) already satisfies the token-at-create invariant and is already in production shape (:302-303).
- **Alternative:** Keep the mint in its own step writing `$GITHUB_ENV` (add `::add-mask::` per T8 note); the wrapper reads the env like today. The mandatory F6 residuals — mint failure = named hard failure, never a netns retry — stay. This is the same pattern already proven in the tree.
- **Confidence:** MEDIUM-HIGH (removes machinery whose only reason to exist is F3's consolidation; S2 removes that reason).
- **Disposition:** amend F6 to "keep mint step boundary + add-mask"; delete the own-process export contract and its AT-4 fixture (replace with an env-reaches-containers assertion at the step boundary, which the current tree already satisfies).

### S8 (MEDIUM): sandbox-runner env-parity wiring must wait for Q1; do not build option-a machinery speculatively

- **Location:** T7 F6/R5, T7 F7, T8 Q1.
- **Concern:** F7's final full-set reconcile lists `sandbox-runner` as a required running service, and F6's option a gives it full worker env parity. Both presuppose Q1's answer. If Q1 selects option a, sandbox-runner becomes a second registered `umd-worker` with a different isolation environment — a product decision (deterministic execution environment) that must not be baked in by workflow plumbing. If Q1 selects option b, the F7 required_running list and F3's tripwire semantics both change.
- **Alternative:** Wire the amendment so sandbox-runner is **started** (`--profile sandbox` pinned — L9's mandatory-sandbox posture) and **security-classified** (F9: any EPERM class = hard fail), and report its role honestly; leave the required_running membership and env-parity as a named Q1-dependent decision. The tripwire lists sandbox-runner either way (absence visible), but the *gate* semantics follow Q1. Also reconcile `record-release-summary.sh:73` ("Required") with the Q1 outcome.
- **Confidence:** MEDIUM (this is a scope discipline call; Q1 is explicitly a human decision the amendment already carries).
- **Disposition:** amend F6/F7 to carry both branches as one decision point; do not build either branch's machinery before Q1.

### S9 (LOW): evidence-dir naming follows the batch count

- **Location:** T7 F8 (first-T5 detail merged).
- **Concern:** `compose-up-batch-{1..4}-{attempt}.log` is tied to the four-batch structure (S2). Cosmetic.
- **Alternative:** `compose-up-{phase}-{attempt}.log` (two phases) or `compose-up-{attempt}.log` if S4's single-budget makes phase labels moot.
- **Confidence:** HIGH (pure naming).
- **Disposition:** rename with the S2/S4 amendments; the evidence-dir layout, artifact glob, and verdict-file contract otherwise stand.

## 6. Preserved unresolved risks and human questions

The simplifications above **do not** eliminate any of T8's U1–U8 or Q1–Q8. Each is preserved:

- **U1 (BLOCKING)** — carried into S1 as the mandatory correction; T8's amended AT-1 (shielding-idiom fixture) becomes the regression test.
- **U2 (HIGH)** — carried; the S2 two-phase + `--no-deps` + explicit `up` timeout *is* the mitigation (T8 Q7).
- **U3 (MEDIUM)** — carried; S3's scoped interpreter contract removes the blast radius, so the audit (AT-11) is no longer a prerequisite. If the team still flips the job default, the audit must return.
- **U4 (MEDIUM/HIGH)** — carried unchanged: honest re-documentation of `sandbox-seccomp.json` (ungated ~415-syscall allowlist) + human security sign-off (Q6) + `sandbox-security.txt` fields (AT-15).
- **U5 (MEDIUM)** — carried: `if-no-files-found: error` for the evidence dir + verdict written on trap paths (AT-14).
- **U6 (MEDIUM)** — carried: `docker-capability.txt` records Docker/Compose versions; re-validate the F4 regex on major-version change (AT-13). Preserved by S5 (versions still recorded).
- **U7 (OBLIGATION)** — carried: R18 tier-1 re-retrieval + ledger-row update blocks amendment finalization (AT-10, Q2).
- **U8 (PROCESS)** — carried as a read-before-write note for consumers (T6 before T7; canonical T5 = IP-1–IP-10).
- **Q1–Q8** — all carried. Q1 (sandbox-runner role; S8) and Q2 (R18 retrieval) block execution/finalization respectively; Q3/Q4/Q5/Q7/Q8 remain parameter approvals (S2/S4/S5 adjust the *values under approval*, not the need for approval).

**Verification gaps the amendment itself does not close (carry to Exec-Manager):**
- **R16's five failed reconcile re-ups (run `33228084721`)** — whether a marker-affected half-created container needs `docker compose rm -sf <svc>` (or `docker rm -f` on the victim) *before* the classified re-up is not answered by F4/F7. Prior complexity finding L8 raised this (MEDIUM). R18 suggests a plain re-up can recover, but R18 ran *after* the ps-a/seccomp fixes, so the classes are confounded. The first green run under the corrected F1 contract is the arbiter; F8's evidence schema makes it auditable. **Do not add rm machinery speculatively — observe first.**
- **Host-SDK and test-isolation blockers from R18** (`ModuleNotFoundError hatchet_sdk`, `source_pkey` UniqueViolation) are toolchain/test repairs already addressed in working-tree commits (`6614b32`); they are not netns and must not be relabeled.

## 7. Immutable-requirement check (L1–L9) and forbidden set

The amendment as simplified by S1–S9 preserves every binding invariant, verified against the ledger:

- **L1/L2/L4/L5** — approved R&D workflow continued; netns investigated against R10–R18 hosted evidence; verdict remains **workflow-design change, no architecture/topology change** (S2 changes batch count, never topology — the tripwire proves the 8-service set either way).
- **L3** — Task.md not bypassed/weakened: `2d84d07`/`e6b5c3f` reconciles preserved and strengthened by the corrected status contract (S1) and classify-by-inspect (S6).
- **L6** — adversarial review complete; this review is a read-only structural check on top of it.
- **L7** — no code, workflow, DD, or plan edits by this review; the artifact is the only write.
- **L8** — handoff below.
- **L9** — full split Hatchet topology (tripwire + `--profile sandbox` pinning), real callbacks (JWT mint fail-closed; token reaches api/worker at create via the kept step boundary), mandatory hosted validation (F7 reconcile + F10 gate), no skips/stubs/fake readiness (F2 snapshot labeling + F5/F7 evidence), no second scheduler (single-owner wrapper; Hatchet sole scheduler). S8's deferral of sandbox-runner env parity keeps sandbox **started and validated** (never skipped), per L9's mandatory-sandbox wording.

**Forbidden set never re-introduced:** Hatchet Lite, DinD/socket mounts, privileged/unconfined broad bypass, skipping sandbox, optional/trigger-level gate, fake readiness, second scheduler, host networking, blanket retry, `--wait` sole gate. None of S1–S9 touches this set; S5's removal of the Class A wait routes daemon-down through a fast hard fail, which is fail-closed, not bypass.

## 8. Verdict and recommendation

```yaml
status: DONE
target: "artifacts/designs/process/universal-media-decomposer-plan-k-netns-complexity-review.md"

structure:
  amendment_surface: "F1-F10 + F-R18 (T7 canonical) + U1-U8 + Q1-Q8 + AT-1..AT-15"
  scripts_touched_by_amendment: 3-4        # compose-start.sh (new), preflight, capture-diagnostics, validation.yml
  indirection_hops: 3-4                    # step -> wrapper -> compose/inspect -> gate
  comparable_to_codebase_norm: true        # existing wait-for-*.sh / preflight / capture-diagnostics helpers

comparison:
  similar_surface: ".github/scripts/* + validation.yml docker-e2e job (pre-amendment)"
  delta: "Amendment adds a wrapper script, a bash-status contract, a classifier (marker/one-shot/EPERM), an evidence schema, and an escalation verdict"
  norm: "Existing scripts are ~40-80 line sh helpers; the amendment's canonical design is consistent with that norm once S1-S9 are applied"

findings:
  - location: "T7 F1 pipefail/PIPESTATUS idiom (T8 U1)"
    concern: "BLOCKING defect — capture line is unreachable under set -e; retry branches stay dead"
    evidence: "bash set builtin exception list; R18 marker swallowed by | tee"
    alternative: "shielding idiom rc=0; docker compose ... | tee log || rc=${PIPESTATUS[0]}"
    confidence: HIGH
  - location: "T7 F3 four serialized batches"
    concern: "Fourth batch and per-batch state machine exceed the two-phase structure the workflow already has"
    evidence: "validation.yml:248-307 (phase 1 + JWT), :313-385 (phase 2); depends_on ordering; COMPOSE_PARALLEL_LIMIT=1"
    alternative: "two phases + --no-deps + COMPOSE_PARALLEL_LIMIT=1 (env) + topology tripwire"
    confidence: HIGH
  - location: "T7 F2 Class A daemon-reachability wait (120s/5s)"
    concern: "Speculative wait for an unobserved failure class; new flake surface and second escalation route"
    evidence: "R10-R18 contain no daemon-unreachable-at-start observation"
    alternative: "record docker/compose versions in docker-capability.txt; Class B hard fails; compose up as the reachability probe"
    confidence: MEDIUM-HIGH
  - location: "T7 F5 docker wait + timeout 300 machinery"
    concern: "Duplicates the existing bounded fail-closed polls (config poll, tenant-discovery 30x2s, JWT mint)"
    evidence: "validation.yml:252-307; tenant-row dependency of token create"
    alternative: "first-nonzero-ExitCode classifier via docker inspect; keep one explicit timeout on compose up only"
    confidence: MEDIUM-HIGH
  - location: "T7 F1 job-wide defaults: run: shell: bash flip"
    concern: "U3 blast radius over every inline step forces AT-11 audit workstream"
    evidence: "U3; docs.github.com shell semantics (checked 2026-08-29)"
    alternative: "scope bash to compose-owning scripts (shebang + bash script.sh double-pin)"
    confidence: HIGH
  - location: "T7 F6 own-process JWT export + sandbox-runner env parity"
    concern: "Machinery forced by F3 step consolidation; env parity presumes unresolved Q1 (second umd-worker)"
    evidence: "current mint step :302-303 satisfies token-at-create; Q1; second umd-worker isolation concern"
    alternative: "keep mint step boundary + add-mask; gate sandbox-runner env parity on Q1"
    confidence: MEDIUM-HIGH
  - location: "T7 F4 per-batch retry budget (3x4)"
    concern: "Budget multiplication for a startup-phase phenomenon"
    evidence: "marker is a startup-phase class; F7 reconcile bounds per-batch failure"
    alternative: "one shared 3-attempt budget + one escalation verdict"
    confidence: HIGH
  - location: "F2/F4/F5/F7/F8/F9/F10 core + F-R18"
    concern: "Justified — keep unchanged"
    evidence: "R10/R11/R15/R16/R17/R18 hosted evidence; L3"
    alternative: "none"
    confidence: HIGH

verdict:
  complexity_level: ELEVATED        # core justified; ~1/3 of the amendment surface reducible
  justified: true                   # the core is justified; the reducible excess is bounded and safe to trim
  summary: "Workflow-only amendment is the right decision (no topology change). Core machinery is evidence-backed and must ship. Trim: two-phase startup (S2), one retry budget (S4), no Class A wait (S5), no docker-wait machinery (S6), scoped bash contract (S3), kept mint step boundary (S7), Q1-gated sandbox env parity (S8). One BLOCKING correction: F1's PIPESTATUS idiom (S1/U1)."

recommendation: |
  For DDAuthor / Exec-Planner (workflow-only Plan K amendment):
  1. CORRECT F1 first (S1/U1): the shielding idiom is a prerequisite for any retry/reconcile branch.
  2. Adopt S2-S9 as amendment text: two-phase startup with --no-deps + COMPOSE_PARALLEL_LIMIT=1
     (env) + tripwire; one 3-attempt budget; capability-snapshot preflight (no Class A wait);
     first-exit inspect classifier (no docker wait); bash scoped to compose-owning scripts;
     mint step boundary retained; sandbox-runner gate semantics gated on Q1.
  3. Keep AT-1 (amended, shielding fixture), AT-3, AT-5, AT-6 (without docker-wait fixture),
     AT-7, AT-8, AT-9, AT-10, AT-12, AT-13, AT-14, AT-15. Drop AT-11 (S3). Defer AT-4 to Q1 (S8).
  4. Carry U1-U8 and Q1-Q8 unchanged; Q1 and Q2 remain blocking.
  5. Observe the first green run before adding any container-removal (rm) logic for the
     marker-affected victim (R16 5-failed-re-ups question) — do not build it speculatively.
```

**Bottom line:** the validated artifact's recommendation — **workflow-only Plan K amendment, no architecture/topology change** — is the correct decision and its core machinery (exact-marker bounded retry, fail-closed reconcile, status-capture correctness, one-shot/EPERM classification, evidence schema, escalation verdict, R18 honesty caveat) is **justified complexity** that must ship. What remains is a bounded set of trims (S2–S9) and one mandatory correction (S1/U1) that together make the amendment **smaller and more testable without weakening a single L1–L9 invariant or dropping a single U1–U8 risk**.

## 9. Citations and check dates

All checked **2026-08-29** (same date as the validated artifact; no re-check was needed for claims that are already tier-1/3-cited there, and this review introduces no new technology claims):

- [Tier 1/2] Hosted runs R10/`33226227591`, R11/`33226431905`, R15/`33227518543`, R16/`33228084721`, R17/`33228376245`, R18/`33228898244` — restated exactly as in the validated artifact ledger; R18 remains corroborated-at-coordination-tier with tier-1 re-retrieval pending (U7/Q2).
- [Tier 1-local] `.github/workflows/validation.yml` (:248-307 config-gen/JWT, :322-345 retry, :346-384 reconcile, :497-509 aggregate gate, :526-539 upload), `deploy/compose.yaml` (:148,:176 restart on-failure; :173,:195-197,:215-218 service_completed_successfully; :235 sandbox profile; :236-241 sandbox env; :251 unless-stopped), `.github/scripts/preflight-hatchet-images.sh`, `capture-diagnostics.sh`, `record-release-summary.sh:73`, `deploy/security/sandbox-seccomp.json` (SCMP_ACT_ERRNO, flat ungated allowlist) — read 2026-08-29.
- [Tier 3] GitHub Actions shell semantics (`bash -e {0}` vs `bash --noprofile --norc -eo pipefail {0}`), Docker Compose `COMPOSE_PARALLEL_LIMIT` env/flag precedence, compose `service_completed_successfully` re-trigger/hang family (docker/compose#10985/#11808/#12134), moby netns marker classes (moby/moby#50750/#46490), GNU Bash `set -e` exception list — all as cited in T6/T7/T8 of the validated artifact with 2026-08-29 check dates.
- [Process] Validation Manifest of the validated artifact (canonical T5 = IP-1–IP-10; T6-before-T7; U8 read-order note).

**Handoff:** this review is read-only. It does not amend Plan K, the DD, or any workflow/code (L7). The next consuming step is DDAuthor/Exec-Planner distilling F1–F10 + F-R18 with the S1–S9 adjustments and the U1–U8/Q1–Q8 carries into the Plan K amendment.
