# Universal Media Decomposer — Plan K Netns Workflow Amendment — Design Document

**Status:** Proposed  
**Author:** rnd-dd-author  
**Created:** 2026-08-29  

**Related Documents:**
- [Validated eight-turn adversarial log and Validation Manifest](artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-plan-k-netns-workflow-validated.md) — Immutable request/L1-L9, canonical T5/T6/T7/T8, F1-F10, F-R18, U1-U8, Q1-Q8, AT-1-AT-19, hosted evidence, and verdict.
- [Architecture options](artifacts/designs/process/universal-media-decomposer-plan-k-netns-architecture-options.md) — DONE; Option D bounded hybrid workflow-only recommendation and forbidden alternatives.
- [Complexity review](artifacts/designs/process/universal-media-decomposer-plan-k-netns-complexity-review.md) — DONE; canonical S1-S9 simplifications and justified complexity.
- [Final estimate](artifacts/designs/process/universal-media-decomposer-plan-k-netns-final-estimate.md) — LARGE/MEDIUM, DD_REQUIRED; workflow-only scope and hosted-proof gates.
- [Approved DD anchor](artifacts/designs/pending/DD-universal-media-decomposer-ci-repair.md) — Approved A + minimal C anchor: full split Hatchet, sole scheduler, real callbacks, mandatory hosted validation.
- [Plan K](artifacts/plans/pending/TASK-universal-media-decomposer-K-ci-repair-release-gate.md) — P2/P3 and Phase 6 workflow/release-gate steps amended by this DD; Phases 1-4 complete, 5-6 pending.
- [Authoritative requirements](Task.md) — Task.md §§1-41, especially §40 DoD 1-35.

---

## Scope

Workflow-only Plan K amendment for hosted Docker/Compose startup, reconciliation, diagnostics, and release gating. No product, deployment topology, full split Hatchet topology, or scheduler change.

---

## Problem Statement

Recurring GitHub Actions Docker network-namespace failures require deeper investigation without bypassing Task.md. R10/R11 show the exact daemon bind-mount netns marker during concurrent startup; R15 shows Compose exit 0 while required services remain Created; R16/R17 show independent sandbox security EPERMs and a ps -q false-absence defect. The evidence supports a bounded workflow-design amendment, not an architectural/topology change. The design must preserve the approved full split Hatchet stack, real callbacks, mandatory hosted validation, no skips/stubs/fake readiness, and Hatchet as the sole scheduler.

---

## Architecture

The architecture remains the approved product architecture: PostgreSQL/OCFL
authority, the real production runner, callback-owned durable completion, and
Hatchet as the only scheduler. This amendment changes only the GitHub Actions
workflow's Compose ownership, startup ordering, state classification, evidence
retention, and release-gate semantics. It introduces no service, network,
scheduler, API, or data-topology replacement.

## Decision and invariants
Adopt the validated adversarial T1-T8 recommendation and Architect Option D, simplified by complexity findings S1-S9: amend only Plan K workflow/release-gate steps. Preserve the exact eight-service full split topology (`db`, `hatchet-migrate`, `hatchet-admin`, `hatchet-engine`, `hatchet-dashboard`, `api`, `worker`, `sandbox-runner`), native hosted Docker, ordinary service-name networking, real SDK/client callbacks, callback-owned durable completion, mandatory hosted proof, and one Hatchet scheduler. No Hatchet Lite, host networking, DinD, host Docker socket, second scheduler, blanket privilege/security bypass, optional mandatory gate, fake readiness, or blanket retry.

This is explicitly a **Plan K amendment**, not a replacement plan. The approved DD remains the product and deployment architecture authority; this document only adds workflow sequencing, classification, evidence, and gate contracts. It introduces no new service, scheduler, network, API, data store, semantic authority, or execution authority.

## Control flow
`docker version`/`docker info`/Compose-version/image-digest/network capability snapshot (not readiness) -> Phase 1 `db` then migrate/admin and config completion -> existing JWT mint step boundary -> Phase 2 engine/dashboard/api/worker/sandbox with `--profile sandbox`, `--no-deps`, `COMPOSE_PARALLEL_LIMIT=1` -> per-phase reconciliation -> final full-set reconciliation -> real registration/callback/live HTTP/restart proof -> diagnostics/upload -> escalation verdict and aggregate gate.

Phase 1 retains the existing config-generation and real tenant JWT step boundary. Token output is masked and exported through `$GITHUB_ENV` for the subsequent container-creation step. Empty/non-JWT/query/mint/admin failure is a named hard failure and never a netns retry. Phase 2 must not re-list one-shot migrate/admin dependencies. Every Compose `up` has an explicit timeout. A `config --services` assertion must equal the full eight-service set. Tenant selection must be scheduler-eligible: the selected tenant must have non-null scheduler and worker partition identifiers, and the workflow must fail closed if discovery is ambiguous or selects an internal/unpartitioned tenant. The token tenant, worker tenant, workflow tenant, and submitted-task tenant must agree in the hosted evidence.

## Mandatory hosted Hatchet execution contracts (before Phase 6)

The workflow/release gate must prove the real pinned `hatchet-sdk==1.38.1`
execution contract; registration, worker readiness, health text, and a successful
submission are not substitutes for execution. The callback registered for every
`umd-<stage>` task has the v1 signature `handler(input, ctx)`, with the input
object passed directly (there is no v0 `{"input": ...}` wrapper). It reads the
direct v1 manifest shape, invokes `DurableStageExecutor`, and lets the callback
path persist its completion and audit records (`stage_run`, `StageCompleted`, and
the operational job audit) durably. It must not mark completion from registration
or from the callback without executor/store persistence.

The hermetic callback fixture must invoke `(input, ctx)` with the direct v1 shape,
and a real-SDK-shaped test must fail on a one-argument handler or v0 wrapped
payload. The hosted live gate requires an observed callback plus the resulting
durable UMD rows; engine-visible registration/readiness alone is a hard failure.
This contract is evidenced by `artifacts/logs/support-researcher.log.jsonl:L9`,
`src/umd/jobs/hatchet.py:209-230`, and hosted run `33229130339`, job
`99038602321`.

Tenant selection is deterministic and scheduler-eligible. Discovery must yield
exactly one setup-created tenant identity, or exactly one tenant with both
non-null `schedulerPartitionId` and `workerPartitionId`; zero matches,
multiple matches, or a null partition is fail-closed. The workflow records the
selected tenant and both partition IDs. Before live execution it asserts that
the JWT tenant, worker tenant, workflow tenant, and submitted-task tenant are
identical and that the recorded partition IDs are non-null. A worker-ready line
or registration record without these assertions is insufficient. This contract
is evidenced by `artifacts/logs/support-debugger.log.jsonl:L8-L12` and the same
run/job above; the queued, unassigned tasks are not a readiness success.

Every release task must use the pinned SDK's durable registration surface:
`hatchet_sdk==1.38.1` `client.durable_task(name=wf_name)(handler)` for each
`umd-<stage>` action (not `client.task(...)`). The hosted DB/engine evidence must
assert `v1_task.is_durable=true` for every registered release task and submitted
task. Postgres durability of callback-owned UMD rows is additional evidence, not
proof of Hatchet durable scheduling. This contract is evidenced by
`artifacts/logs/support-debugger.log.jsonl:L9` and `src/umd/jobs/hatchet.py:417-428`.
These three contracts are mandatory pre-Phase-6 gates and do not introduce a
second scheduler, service, topology, or execution authority.

## Bash/status/retry contract
Scope Bash only to Compose-owning scripts (`#!/usr/bin/env bash`, explicitly invoked as `bash script.sh`) with `set -euo pipefail`; do not flip the job-wide shell default. Every logged Compose pipeline uses the errexit-safe form `rc=0; docker compose ... 2>&1 | tee "$log" || rc=${PIPESTATUS[0]}`. Branch on captured Compose status and visible output, never the tee status. Retry only the exact anchored marker `bind-mount /proc/[0-9]+/ns/net -> /var/run/docker/netns/[0-9a-f]+: no such file or directory`, including a marker with Compose rc 0. Exclude `lstat`, other `/proc` errors, timeout, EPERM, OOM, invalid config/image, one-shot nonzero, and generic text. Use one shared three-attempt startup budget, fixed five-second backoff, and `--no-build` after attempt one. Exhaustion writes `hosted-netns-escalation: TRUE`, preserves evidence, fails, and escalates as a hosted daemon/runner issue; never silently enlarges the budget or changes topology.

Each attempt is classified from the visible labeled output **and** captured
Compose status: marker evidence is considered even when status is zero, while
a nonzero status without the exact marker is a diagnosed hard failure, not a
blanket transient retry. Thus “marker-or-nonzero” is a classification contract,
not permission to retry every nonzero result. A reconciliation re-up consumes
the same bounded budget only when its own visible output contains the exact
marker; otherwise it fails closed.

## Reconciliation and security
Reconcile after each phase and perform a final full-set authoritative reconcile. Use `docker compose ps -a` plus `docker inspect`; never one-shot `ps -q`. Long-lived services must be running, healthy where defined, non-restarting, non-OOM-killed, and have empty `State.Error`; migrate/admin must be clean exited(0). The first observed nonzero one-shot `ExitCode` is a hard failure regardless of restart policy; inspect exit/restart/restarting/health/error/OOM rather than waiting for final exit. Re-up is recoverable only when its visible output contains the exact marker; otherwise fail closed. Preserve and strengthen `2d84d07`/`e6b5c3f` intent; no hidden `|| true` in gate decisions. The proposed settle window is 60s polling every 5s (Q3).

Sandbox `statx`, `fsmount`, `getcwd`, `vfork`, `clone`, `unshare`, or related EPERM is an independent sandbox security failure and never consumes netns budget. Document the actual `deploy/security/sandbox-seccomp.json` honestly as the observed `SCMP_ACT_ERRNO` ungated approximately 415-syscall allowlist, not as a capability-gated Moby default. Require independent human AppArmor/userns/security sign-off and capture effective user, bwrap argv, host AppArmor state, and profile digest. The mandatory hosted sandbox-runner gate receives full worker Hatchet environment parity and has a distinct boot/security proof; Q1 is the required human sign-off on that role and security contract, not permission for a silent omission. Any explicitly approved gated/configured-unavailable outcome must remain visible and release-blocking for this mandatory validation, never become a skip or fake readiness signal.

## Evidence and release gate
Use one `umd-evidence/` directory: `docker-capability.txt`, `image-digests.txt`, phase/attempt Compose logs, reconciliation logs, `svc-inspect/<service>.json`, `compose-ps.txt`, `network-inspect.txt`, `sandbox-security.txt`, `escalation-verdict.txt`, service logs, JUnit/coverage, DB dump, OCFL/fixity, and release summary. `capture-diagnostics.sh` runs under `if: always()` before teardown and is collection-only. Upload uses `if-no-files-found: error`; trap/death paths write a verdict. The aggregate gate reads existing live/boundary/restart gate files plus escalation verdict: TRUE or absent is FAIL. Preserve named volumes through stop/start/restart proof; `down -v` only after evidence upload. Capability snapshots and health/readiness text never prove execution: real engine-visible registrations, callbacks, durable rows, hosted HTTP, and restart evidence remain mandatory.

## Blockers and gate semantics

Phase 6 release proof cannot begin until the pre-Phase-6 gate has PASS evidence
for AT-16 through AT-19 and the existing mandatory gates. Any one-argument/v0
callback observation, absent callback, absent `stage_run`/`StageCompleted`/audit
row, zero or multiple tenant matches, null partition ID, tenant-consistency
mismatch, readiness-only proof, or `v1_task.is_durable=false` is a hard FAIL and
blocks the hosted release gate. A skipped or unavailable mandatory check remains
visible and release-blocking; it is never converted into a pass. Only a hosted
run with the callback observed, durable Hatchet task rows, scheduler-eligible
tenant consistency, callback-owned durable rows, and the existing topology,
sandbox, HTTP, restart, and evidence proofs may advance to Phase 6. The exact
netns marker retains its separate bounded retry/escalation semantics and must not
mask any of these execution failures.

---

## Design Goals

- Preserve immutable L1-L9 and every Task.md §40 obligation.
- Narrow and diagnose the observed daemon race without changing product or topology.
- Correct Bash errexit/PIPESTATUS handling and Compose exit-0 false-success classification.
- Prevent one-shot dependency re-trigger/hang via two phases, `--no-deps`, and explicit `up` timeouts.
- Preserve JWT ordering, mandatory sandbox/security validation, real callbacks, diagnostics, hosted proof, and fail-closed gates.
- Keep the amendment bounded and directly mappable to Plan K.

---

## Constraints

This is a design artifact only; do not implement code/workflows or amend Plan K here. The original request and L1-L9 are immutable authority. Full split Hatchet topology, real callbacks, mandatory hosted validation, no skips/stubs/fake readiness, and Hatchet sole scheduler are mandatory. Forbidden: Hatchet Lite, host networking, DinD/socket mounts, privileged or blanket seccomp/AppArmor bypass, skipping sandbox, optional/trigger-level mandatory gate, fake readiness, second scheduler, blanket retry, and Compose `--wait` as sole gate. Local Docker absence is only a named local gate. R18 tier-1 retrieval remains required before finalization.

---

## Open Questions

### Canonical S1-S9 complexity findings
- **S1 BLOCKING:** correct unreachable bare PIPESTATUS capture with `rc=0; ... | tee ... || rc=${PIPESTATUS[0]}`.
- **S2:** two phases, not four; retain serialization, topology tripwire, and `--no-deps`.
- **S3:** scope Bash to Compose-owning scripts; no job-wide default flip without the mandatory AT-11 audit.
- **S4:** one shared three-attempt startup budget, not per-batch multiplication.
- **S5:** drop speculative 120s/5s daemon-reachability wait; retain capability snapshot and immediate capability hard fails.
- **S6:** drop duplicate `docker wait` machinery; inspect classifies one-shots; retain explicit timeout on every `up`.
- **S7:** retain JWT mint step boundary and masking; drop own-process export, while adding the scheduler-eligible tenant/partition assertion surfaced by hosted run `33229130339`.
- **S8:** start/security-classify sandbox-runner with full worker Hatchet env parity; Q1 signs off the required-running/security semantics.
- **S9:** phase/attempt evidence names, not four-batch names.

### T8 unresolved risks U1-U8
U1 PIPESTATUS; U2 one-shot re-trigger/hang; U3 shell blast radius; U4 seccomp honesty and AppArmor/userns sign-off; U5 upload error/verdict death paths; U6 Docker major-version marker drift; U7 R18 tier-1 retrieval obligation; U8 validated-artifact order/process note (read T6 before T7, canonical T5 IP-1-IP-10). All remain visible and are not silently waived.

### T8 human questions Q1-Q8
- **Q1 (blocks the next hosted run):** sign off the mandatory sandbox-runner gate with full worker Hatchet environment parity and a distinct security/stay-running contract. If the platform cannot satisfy it, record `configured-unavailable`/`gated` as a visible blocking outcome; it is not a permitted skip or release pass.
- **Q2 (blocks finalization):** retrieve R18 (`33228898244`, job `99037936832`) from GitHub tier 1 and update the ledger before treating its coordination-tier summary as authoritative.
- **Q3:** approve/record the bounded 60-second settle window with 5-second polling, or a justified bounded alternative.
- **Q4:** approve/record the daemon preflight policy. The recommended design records a capability snapshot and treats preflight as non-readiness; any reachability wait must be bounded and use the same escalation route, never replace readiness or reconciliation.
- **Q5:** approve/record `COMPOSE_PARALLEL_LIMIT=1` via environment for initial hosted runs and measure the resulting wall time.
- **Q6:** obtain separate human security sign-off for the actual seccomp/AppArmor/userns posture; no broad privileged or unconfined bypass is acceptable.
- **Q7:** approve/record `--no-deps` on later/recovery starts and an explicit timeout on every Compose `up`.
- **Q8:** approve the scoped Bash contract and complete the per-step Bash/pipefail audit for every docker-e2e step (AT-11); any future job-wide shell default also requires that audit before the change.

### Acceptance tests AT-1-AT-19
AT-1 through AT-15 remain unchanged and mandatory; AT-16 through AT-19 extend
the set without weakening, replacing, or making conditional any earlier check.
AT-1 shielding/PIPESTATUS reachability; AT-2 capability snapshot and hard-fail assertions; AT-3 profile/full eight-service config tripwire; AT-4 masked JWT step-boundary, scheduler-eligible partition assertion, and mandatory sandbox-runner env parity; AT-5 exact marker negative matrix and exact budget; AT-6 first nonzero one-shot/restart classifier; AT-7 final full-set and classified re-up; AT-8 evidence upload and verdict gate; AT-9 independent sandbox EPERM classification; AT-10 R18 tier-1 retrieval/ledger update; AT-11 mandatory per-step Bash/pipefail audit for every docker-e2e step; AT-12 explicit timeout/`--no-deps`/tripwire; AT-13 Docker/Compose version drift revalidation; AT-14 error-on-missing evidence and trap verdict; AT-15 sandbox-security fields and sign-off.

AT-16 pinned `hatchet-sdk==1.38.1` v1 callback contract: hermetic fixture and
real-SDK-shaped test invoke `(input, ctx)` with direct input, reject one-argument
or v0-wrapped payloads, and prove `DurableStageExecutor` callback-owned
completion plus durable `stage_run`/`StageCompleted`/audit rows; hosted gate
observes the callback and rows.

AT-17 deterministic tenant eligibility: exactly one setup-created or
scheduler-eligible tenant has non-null scheduler and worker partition IDs;
zero/multiple/null cases fail closed; selected IDs are recorded; JWT, worker,
workflow, and submitted-task tenant identities match; readiness alone fails.

AT-18 pinned SDK durable registration: every release `umd-<stage>` task uses
`client.durable_task(name=wf_name)(handler)`, and hosted DB/engine evidence
asserts every resulting `v1_task.is_durable=true` (callback Postgres rows alone
do not satisfy this check).

AT-19 pre-Phase-6 gate composition: AT-16, AT-17, and AT-18 are mandatory,
non-skippable hosted checks joined with AT-1 through AT-15; any failure, skip,
missing evidence, readiness-only result, or configured-unavailable outcome is
release-blocking and cannot be hidden by netns retry or a later gate.

### R18 boundary
R18 (`33228898244`) is retained as a coordination-tier report only until tier-1 GitHub retrieval. It must not be presented as finalized evidence or used to close the release gate.

---

## Authoritative original request and immutable L1-L9 ledger

Original user request (verbatim):

> Continue the approved R&D repair workflow for Plan K, incorporating the user's new concern: recurring GitHub Actions netns/network-namespace roadblocks are abnormal and require deeper investigation. Do not bypass or weaken Task.md. Review the approved DD, Plan K, current support findings, and the eventual netns support reports when available. Determine whether netns requires an architectural/topology change or workflow design change. If a new design decision is needed, run the formal R&D path required by dispatching-agents (including adversarial review) and amend/create a validated plan. Do not implement code/workflows. Return exact design/plan artifacts, requirement-ledger impact, and handoff instructions to Exec-Manager. Preserve full split Hatchet topology, real callbacks, mandatory hosted validation, no skips/stubs/fake readiness, and no second scheduler.

Immutable ledger:
- **L1:** Continue the approved R&D repair workflow for Plan K.
- **L2:** Recurring GitHub Actions netns/network-namespace roadblocks are abnormal and require deeper investigation.
- **L3:** Do not bypass or weaken Task.md.
- **L4:** Review the approved DD, Plan K, current support findings, and eventual netns support reports when available.
- **L5:** Determine whether netns requires an architectural/topology change or workflow design change.
- **L6:** If a new design decision is needed, run the formal R&D path required by dispatching-agents, including adversarial review, and amend/create a validated plan.
- **L7:** Do not implement code or workflows.
- **L8:** Return exact artifacts/ledger impact/Exec-Manager handoff instructions.
- **L9:** Preserve full split Hatchet topology, real callbacks, mandatory hosted validation, no skips/stubs/fake readiness, and no second scheduler.

---

## Plan K phase mapping and implementation handoff

| DD contract | Plan K location | Proof/gate |
|---|---|---|
| Scoped Bash, shielding idiom, marker-or-nonzero classification, bounded retry | P3-S3 | AT-1, AT-5, AT-6 |
| Capability snapshot, Docker/Compose/image/network facts, no readiness claim | P3-S4 and P3-S5 | AT-2, AT-13 |
| Two-phase startup, profile pin, `COMPOSE_PARALLEL_LIMIT=1`, full-set tripwire, `--no-deps`, timeout | P3-S3; preserve P2-S2/P2-S3 | AT-3, AT-12 |
| JWT step boundary, scheduler-eligible tenant/partition assertion, and mandatory sandbox-runner env parity | P2-S4 and P3-S3 | AT-4, Q1 |
| v1 `(input, ctx)` direct-input callback, executor invocation, and callback-owned durable completion/audit | P2-S4/P2-S5 and P3-S3; must pass before Phase 6 | AT-16 |
| Deterministic schedulable tenant selection, partition recording, and tenant consistency | P2-S4/P2-S5 and P3-S3; must pass before Phase 6 | AT-4, AT-17 |
| Pinned durable Hatchet task registration and hosted `v1_task.is_durable=true` assertion | P2-S5 and P3-S3; must pass before Phase 6 | AT-18 |
| First-exit inspection and final full-set reconcile | P3-S3; preserve `2d84d07`/`e6b5c3f` | AT-6, AT-7 |
| Evidence directory, diagnostics, upload, verdict, aggregate gate | P3-S5 | AT-8, AT-14 |
| Sandbox independent classification and security sign-off | P3-S3; Phase 6 | AT-9, AT-15, Q6 |
| R18 tier-1 retrieval and final hosted proof | Phase 6 | AT-10, Q2 |

Exec-Manager must amend only Plan K workflow/release-gate steps, implement AT-1-AT-19 (AT-11 conditional), and complete the AT-16/AT-17/AT-18 contracts before entering Phase 6. Push path-scoped changes, retrieve exact SHA/run URL/jobs/attempt/logs/JUnit/diagnostics/artifacts, and use the first green hosted run under corrected status capture as the F4/F7 arbiter. Stop on any missing/skipped mandatory gate, absent verdict, non-marker failure, sandbox security denial, failed one-shot, topology mismatch, missing real callback, one-argument/v0 callback, absent durable callback rows, ineligible or inconsistent tenant, `v1_task.is_durable=false`, or mandatory Task.md FAIL. If the exact marker exhausts the shared budget, escalate with evidence; do not add retries or redesign topology.

---

## Hosted evidence and references

Hosted evidence: baseline run `33164294061` (SHA `a6b1a62f8413655b9908b40e4fc7a484828364e0`); R10 `33226227591`; R11 `33226431905`; R15 `33227518543`; R16 `33228084721` (job `99035605497`); R17 `33228376245` (job `99036443345`); R18 `33228898244` (job `99037936832`, tier-1 retrieval pending).

Exact local references: `.github/workflows/validation.yml:248-307,313-385,497-509,526-539`; `.github/scripts/preflight-hatchet-images.sh`; `.github/scripts/capture-diagnostics.sh`; `.github/scripts/record-release-summary.sh`; `deploy/compose.yaml:148,173,176,195-218,235-251`; `deploy/security/sandbox-seccomp.json`; `artifacts/designs/parts/universal-media-decomposer/CONTRACTS.md:58-67`; `Task.md:1375-1394,1641-1692`.

Technology evidence checked 2026-08-29 in upstream reports: Docker Compose networking/daemon diagnostics/seccomp/AppArmor/userns/host-network docs; GitHub Actions shell/service-container docs; GNU Bash `set -e`/`PIPESTATUS`; Compose `COMPOSE_PARALLEL_LIMIT`; Moby/containerd netns issues `moby/moby#50750`, `#46490`, `containerd/containerd#12141`; Compose one-shot issues `#10985`, `#11808`, `#12134`; runner drift `actions/runner-images#13474`, `#13682`, `#13708`, `#14105`. These support workflow hypotheses/contracts; hosted runs are release authority.

Additional hosted evidence requiring Plan K reconciliation: run `33229130339`, job `99038602321`, exposed a real JWT minted for the first/internal tenant whose scheduler and worker partition IDs were null. Submissions were accepted and worker registration was real, but tasks remained queued and callback-owned UMD rows stayed empty. This is not netns evidence and does not change topology; it adds a fail-closed tenant-partition eligibility assertion to P2-S4/P3-S3 and the AT-4/AT-17 proof. The same run's SDK handler-contract finding is a mandatory real-SDK execution contract captured by AT-16, not a network failure. The durable-registration finding is captured by AT-18 and must be independently proven with `v1_task.is_durable=true`.

---
