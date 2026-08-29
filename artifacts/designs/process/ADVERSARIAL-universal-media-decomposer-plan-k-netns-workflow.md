# Adversarial Design Log: Plan K Netns/Network-Namespace Workflow Decision

*This file records the full adversarial refinement process for a NEW bounded
workflow-design decision/amendment to Plan K
(`TASK-universal-media-decomposer-K-ci-repair-release-gate.md`): whether the
recurring GitHub Actions Docker netns/network-namespace roadblocks
(R10/R11/R15/R16/R17 hosted runs) require an architectural/topology change or
a workflow-design change, and what the amended workflow contract must be.*

*The approved design document
(`DD-universal-media-decomposer-ci-repair.md`, Proposed, A+C, full split
Hatchet topology, sole scheduler, real callbacks, mandatory hosted validation,
no skips/stubs/fake readiness, no second scheduler) remains the design anchor.
This log is the raw debate that DDAuthor/Exec-Planner will distill into a DD /
Plan K amendment. It is a NEW standalone artifact and does NOT overwrite the
prior adversarial artifact
(`ADVERSARIAL-universal-media-decomposer-ci-repair.md`).*

*Process: 8 sequential turns — T1 Ideator (approaches) → T2 Counter-Ideator
(critique) → T3 Ideator (refine) → T4 Counter-Ideator (surviving concerns) →
T5 Improver (implementation patterns) → T6 Counter-Improver (pattern risks) →
T7 Improver (final patterns) → T8 Counter-Improver (open risks & human
questions). Every technology/version choice MUST be validated against current
official/maintainer sources with source + check date recorded, or explicitly
labeled PROVISIONAL. Newest is not automatically best; unvalidated claims must
be labeled provisional.*

---

## Immutable Requirement Ledger (binding for every turn)

Original user request (verbatim, preserved):

> Continue the approved R&D repair workflow for Plan K, incorporating the
> user's new concern: recurring GitHub Actions netns/network-namespace
> roadblocks are abnormal and require deeper investigation. Do not bypass or
> weaken Task.md. Review the approved DD, Plan K, current support findings,
> and the eventual netns support reports when available. Determine whether
> netns requires an architectural/topology change or workflow design change.
> If a new design decision is needed, run the formal R&D path required by
> dispatching-agents (including adversarial review) and amend/create a
> validated plan. Do not implement code/workflows. Return exact design/plan
> artifacts, requirement-ledger impact, and handoff instructions to
> Exec-Manager. Preserve full split Hatchet topology, real callbacks,
> mandatory hosted validation, no skips/stubs/fake readiness, and no second
> scheduler.

Immutable ledger L1–L9 (verbatim, binding for every turn and for the final
artifact; downstream consumers must compare their output against it):

- **L1:** Continue the approved R&D repair workflow for Plan K.
- **L2:** Recurring GitHub Actions netns/network-namespace roadblocks are
  abnormal and require deeper investigation.
- **L3:** Do not bypass or weaken Task.md.
- **L4:** Review the approved DD, Plan K, current support findings, and
  eventual netns support reports when available.
- **L5:** Determine whether netns requires an architectural/topology change or
  workflow design change.
- **L6:** If a new design decision is needed, run the formal R&D path required
  by dispatching-agents, including adversarial review, and amend/create a
  validated plan.
- **L7:** Do not implement code or workflows.
- **L8:** Return exact artifacts/ledger impact/Exec-Manager handoff
  instructions.
- **L9:** Preserve full split Hatchet topology, real callbacks, mandatory
  hosted validation, no skips/stubs/fake readiness, and no second scheduler.

## Decision to be made

This is a **bounded workflow-design decision/amendment**, not a product
feature design. The question the adversarial pairs must answer:

1. Does the recurring GitHub Actions Docker **netns/network-namespace**
   roadblock (hosted runs R10/R11/R15/R16/R17) require an
   **architectural/topology change** (e.g., different Hatchet topology, host
   networking, DinD, socket mounts, Lite, a second scheduler) or a
   **workflow-design change** (startup serialization, capability preflight,
   exact-marker bounded retry, post-up state reconciliation, diagnostics
   contract)?
2. What is the exact amended workflow contract that preserves every L9
   invariant (full split Hatchet topology, real callbacks, mandatory hosted
   validation, no skips/stubs/fake readiness, no second scheduler) while
   making the race window deterministic and diagnosable?
3. What must be rejected and why (Lite, DinD/socket mounts,
   privileged/unconfined broad bypass, skipping sandbox, optional/trigger-
   level gate, fake readiness, second scheduler, treating all errors as
   transient)?

The expected outcome is an explicit decision recommendation:
**workflow-only DD/Plan-K amendment** vs **architecture change**, with the
exact contracts the amendment must carry and the open risks/questions that
require human judgment.

## Inputs used (cited, not rediscovered)

| Input | Path | Why it matters |
|---|---|---|
| Approved DD | `artifacts/designs/pending/DD-universal-media-decomposer-ci-repair.md` | Approved design anchor: A + minimal C, full split Hatchet, sole scheduler, mandatory hosted validation, no skips/stubs/fake readiness, no second scheduler. |
| Plan K | `artifacts/plans/pending/TASK-universal-media-decomposer-K-ci-repair-release-gate.md` | Phases 1–4 complete, Phases 5–6 pending. P3-S3 amended to full moby default seccomp + bwrap syscalls after R17. Current workflow has exact-netns bounded retry and post-up state reconciliation in commit `2d84d07`; it must not be weakened. |
| Task.md | `Task.md` | Authoritative spec; §40 items 1–35 and all 35 DoD rows are binding (L3). |
| Debugger RCA | `artifacts/logs/support-debugger.log.jsonl` L4–L5 | Two root causes: daemon netns lifecycle race + sandbox seccomp EPERM; recurrence mechanism INCONCLUSIVE until per-run daemon/runtime/timing evidence is captured. |
| Researcher RCA | `artifacts/logs/support-researcher.log.jsonl` L6 | Verdict: no architectural/topology change required; workflow-design refinement only (plan amendment), no formal R&D; moby/containerd namespace lifecycle race; serialization + preflight + reconciliation recommended. |
| Librarian briefing | `artifacts/logs/support-librarian.log.jsonl` L19–L20 | No netns DD/plan exists yet; R17 shows workflow-induced false absence (`ps -q` without `-a`); R18 result (33228898244) NOT established in corpus — do not invent it; researcher verdict conflicts with rnd-manager L28 DD_REQUIRED lock. |
| Debugger report | `artifacts/designs/process/universal-media-decomposer-ci-repair-debugger.md` | Authoritative prior diagnosis of run 33164294061 (NEEDS_PLAN). |
| Prior adversarial artifact | `artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-ci-repair.md` | Prior 8-turn fight; the surviving A+C design is the anchor for this amendment. |
| Other process artifacts | `...-librarian.md`, `...-architect-stage.md`, `...-complexity-review-t8.md`, `...-final-estimate.md` | Prior R&D support reports. |

## Hosted evidence (authoritative tier — do not invent or extrapolate)

| Run | Evidence | Reading |
|---|---|---|
| R10 / `33226227591` | Exact daemon error: `Error response from daemon: bind-mount /proc/4009/ns/net -> /var/run/docker/netns/06d21594cf1f: no such file or directory` during ~10 simultaneous default-bridge starts | Daemon netns bind-mount failure before app code; candidate Docker/Moby namespace lifecycle race. |
| R11 / `33226431905` | Netns retry then independent alembic.ini failure | Netns marker recurs; independent app failure must not be masked by netns handling. |
| R15 / `33227518543` | `compose up` exited 0 while required services stayed Created | Orchestration defect: daemon-side start-abort not propagated as pipeline failure; post-up reconciliation (`2d84d07`) is the deterministic fail-closed gate. |
| R16 / `33228084721` | Sandbox bwrap `statx`/`fsmount` EPERM | Seccomp profile defect (distinct root cause from netns). |
| R17 / `33228376245` | Sandbox `getcwd`/`vfork` EPERM, `sandbox-runner=restarting`, `hatchet-migrate/admin=absent` in `ps -q` view | Distinct from daemon race; workflow-induced false absence (one-shot `ps -q` without `-a`); provisional 15-syscall seccomp insufficient → P3-S3 amended to full moby default + bwrap. |
| R18 / `33228898244` | **Result NOT yet established in corpus — do not invent it.** | Any claim about R18 outcome is PROVISIONAL until retrieved from GitHub. |

## Research findings to test adversarially (hypotheses, not conclusions)

1. The daemon netns error occurs **before app code** and matches a
   Moby/containerd namespace lifecycle race (moby/moby#50750,
   containerd/containerd#12141, moby/moby#46490; unrelated projects reproduce
   the identical error on ordinary compose-up).
2. **Full simultaneous Compose startup** (~10 containers) amplifies the race
   window; serialized startup batches narrow it.
3. Recommended workflow-only refinement: docker health/version capability
   preflight; serialized startup batches (db → migrate+admin →
   engine+dashboard → api+worker+sandbox-runner); exact-marker bounded retry;
   post-up reconciliation; per-service retry only on diagnosed recurrence;
   diagnostics with Docker state/exit/restart/netns facts; **do not use
   `docker compose --wait` as the sole gate**; distinguish sandbox
   seccomp/AppArmor/userns failures and fail closed.
4. Likely verdict: **new workflow design decision** (serialization/preflight/
   diagnostic contracts change Plan K) but **no topology redesign**.
5. Explicit rejections to compare and justify: Hatchet Lite; DinD / Docker
   socket mounts; privileged/unconfined broad bypass; skipping sandbox;
   optional/trigger-level gate; fake readiness; second scheduler; treating all
   errors as transient.

## Evidence tiers (binding for citation quality)

1. **Hosted release evidence (authoritative):** pushed SHA, GitHub logs/JUnit/
   diagnostics, compose/service/DB/OCFL observations, image digests, capability
   snapshots, machine-readable release summary retrieved from GitHub.
2. **Local repository evidence (context):** source, tests, contracts, static
   checks, local runs used to diagnose and develop only.
3. **Technology/reference evidence (non-execution):** dated official docs,
   package metadata, registry probes, maintainer-issue citations used to
   justify candidate choices only.

Counter turns must cite tier-1 hosted evidence where it exists, tier-3
maintainer/primary sources for technology claims, and must not present tier-2
local results as release evidence.

## Alternatives the debate must cover

The debate must explicitly compare and, where warranted, reject:

- **A. Workflow-only refinement (serialization + preflight + reconciliation
  + diagnostics)** — candidate recommended path; changes Plan K contracts.
- **B. Topology/architecture change** — e.g., host networking, network_mode,
  different container orchestration shape, DinD, socket mounts.
- **C. Hatchet Lite in CI** — rejected in the approved DD as release
  evidence (different service topology/ports/config/auth/operational behavior).
- **D. Privileged/unconfined broad bypass** (privileged:true, seccomp
  unconfined, AppArmor unconfined as a blanket) — security-posture tradeoff.
- **E. Skipping sandbox / optional or trigger-level gate / fake readiness /
  second scheduler** — forbidden by L9 and the approved DD.
- **F. Treating all errors as transient** (blind retry everything) — rejected
  by R15/R16/R17 evidence (distinct root causes must be classified).

## Key file paths (context for every turn)

- `artifacts/designs/pending/DD-universal-media-decomposer-ci-repair.md`
- `artifacts/plans/pending/TASK-universal-media-decomposer-K-ci-repair-release-gate.md`
- `Task.md` §40 (items 1–35)
- `.github/workflows/validation.yml`
- `.github/scripts/{preflight-hatchet-images.sh,wait-for-http.sh,wait-for-worker.sh,capture-diagnostics.sh,record-release-summary.sh,rollback-hatchet-pair.sh}`
- `deploy/compose.yaml`, `deploy/security/sandbox-seccomp.json`
- `artifacts/logs/support-debugger.log.jsonl` (L4–L5),
  `artifacts/logs/support-researcher.log.jsonl` (L6),
  `artifacts/logs/support-librarian.log.jsonl` (L19–L20),
  `artifacts/logs/exec-manager.log.jsonl` (R10–R17 coordination entries)
- Prior adversarial log `ADVERSARIAL-universal-media-decomposer-ci-repair.md`
  (format precedent; do not overwrite)

## Technology-validation invariant

Whenever a turn introduces, compares, upgrades, or relies on a technology,
library, framework, SDK, platform, runtime, protocol, or version (Docker/
Moby, containerd, bubblewrap, GitHub Actions runner images, Compose, Hatchet
SDK/server, seccomp profiles, AppArmor, userns), the responsible agent MUST
validate it against current official or maintainer sources. The validation
must check support status, compatibility, deprecations, security caveats, and
relevant limitations, and explain best fit for this project's constraints.
Record source and check date. Newest is not automatically best; unvalidated
claims MUST be labeled PROVISIONAL.

---
*Sections below are appended by design agents during adversarial refinement.*
---

## T1 Ideator — Proposed Approaches

**Turn 1 scope.** This section proposes 4 genuinely distinct, bounded options for
the netns decision (L5), compares them against the approved DD anchor (A +
minimal C; full split Hatchet; sole scheduler; mandatory hosted validation; no
skips/stubs/fake readiness; no second scheduler), and ranks them. It does not
implement code or workflows (L7); it is design debate only. Hosted evidence
(R10–R17) is restated exactly from the ledger above; R18 is explicitly not
established. Every technology claim carries a source and check date
(2026-08-29) per the technology-validation invariant.

### Evidence restated exactly (hosted tier, authoritative — do not extrapolate)

| Run | ID | Evidence (verbatim reading) | Implication |
|---|---|---|---|
| R10 | 33226227591 | `Error response from daemon: bind-mount /proc/4009/ns/net -> /var/run/docker/netns/06d21594cf1f: no such file or directory` during ~10 simultaneous default-bridge starts | Daemon netns bind-mount failure before app code; candidate Moby/containerd namespace lifecycle race. |
| R11 | 33226431905 | Netns retry then independent alembic.ini failure | Netns marker recurs; independent app failure must not be masked by netns handling. |
| R15 | 33227518543 | `compose up` exited 0 while required services stayed Created | Orchestration defect: daemon-side start-abort not propagated as pipeline failure; post-up reconciliation (`2d84d07`) is the deterministic fail-closed gate. |
| R16 | 33228084721 | Sandbox bwrap `statx`/`fsmount` EPERM | Seccomp profile defect (distinct root cause from netns). |
| R17 | 33228376245 | Sandbox `getcwd`/`vfork` EPERM, `sandbox-runner=restarting`, `hatchet-migrate/admin=absent` in `ps -q` view | Workflow-induced false absence (one-shot `ps -q` without `-a`); P3-S3 amended to full moby default + bwrap seccomp. |
| R18 | 33228898244 | **Result NOT established in this corpus — do not invent it.** | Any claim about R18 outcome is PROVISIONAL until retrieved from GitHub. |

### Technology-validation notes (all checked 2026-08-29)

- The exact error string `bind-mount /proc/<pid>/ns/net -> /var/run/docker/netns/<id>: no such file or directory` is reproduced in the wild in checkpoint/restore and CI contexts: moby/moby#50750 and containerd/containerd#12141 (the criu project's own CI hit it). Since Docker 28.0.0, Moby no longer uses the OCI prestart hook; the daemon asks containerd to create the task, then discovers the container netns via `/proc/<pid>/ns/net` (moby/moby#50750 comments; moby/moby#52488 "Eliminating SetKey" documents the same runtime-creates-netns → daemon-bind-mounts pattern and its race window). This matches the candidate hypothesis — a daemon-side lifecycle race *before app code* — but does **not** prove the recurrence mechanism in our runs; that stays INCONCLUSIVE until per-run daemon/runtime/timing evidence is captured (debugger RCA). Label: candidate mechanism, not root cause.
- GitHub-hosted runners have a documented history of compose/network flakiness tied to runner-image and daemon state: compose v2.19.0→v2.19.1 patch for "container not connected to network" (actions/runner-images#7862); hosted-agent-dependent DNS/network failures inside compose containers (actions/runner-images#6526). This supports classifying hosted netns failures as infrastructure-variance-adjacent, not product defects — but the classification must be proven per-run, not assumed.
- `docker compose up --wait` is not a reliable sole gate: it exits non-zero when any service exits (even exit 0), has healthcheck-transition bugs, and its restart-policy semantics are contested (docker/compose#10596, #11638, #13069, #12424). This confirms the research finding "do not use `--wait` as the sole gate".
- Serializing docker service startup and making exactly one process own compose are proven production CI patterns: oven-sh/bun commit 2ad4199 ("ci: serialize docker service startup through a per-shard coordinator"); SpecHive commit abc6dea (replacing `compose up --wait` with healthcheck polling + engine-level `docker wait` on container IDs); ma.ttias.be (rootless-docker race writeup: `flock`-serialized network creates; removing host-port publication removed the port race in a 16-way harness).

### Option A — Workflow amendment: deterministic serialized startup + capability preflight + exact-marker bounded retry + post-up reconciliation (RECOMMENDED primary candidate)

- **Summary:** keep the exact split-Hatchet topology and change only the startup contract — order compose calls into dependency batches, preflight docker/network capability, retry only the exact netns marker a bounded number of times, and keep post-up reconciliation (`2d84d07`) as the deterministic fail-closed gate.
- **Mechanism:** (1) capability preflight (docker version/health, network create, and the minimal-C image-manifest tripwire) before any compose up; (2) serialized startup batches — db → migrate+admin → engine+dashboard → api+worker+sandbox-runner — each batch a separate compose invocation with dependency wait between batches; (3) exact-marker bounded retry: only the exact `bind-mount ... no such file or directory` marker is retried, with a small cap and backoff; all other failures fail closed; (4) post-up state reconciliation as the gate (R15: compose exit 0 with services in Created must fail the pipeline); (5) per-service diagnostics contract (docker state/exit/restart/netns facts) on failure. `--wait` may be a convenience but never the sole gate.
- **Codebase fit:** `.github/scripts/{preflight-hatchet-images.sh,wait-for-http.sh,wait-for-worker.sh,capture-diagnostics.sh,rollback-hatchet-pair.sh}` already exist; post-up reconciliation is already in commit `2d84d07` and must not be weakened (L3, DD "Hosted sequencing"); P3-S3 seccomp amendment is already in place for the sandbox-class failures.
- **Preserves every L9 invariant:** full split Hatchet topology, real callbacks, hosted mandatory validation, no skip/stub/fake readiness, no second scheduler. Purely a workflow contract, matching the researcher verdict and the DD's workflow-only orientation (L5 answer: workflow change).
- **Tradeoffs:** adds startup wall-time; introduces a per-service startup-ordering contract future services must respect; the retry policy must be provably bounded to avoid the "treat all errors as transient" trap (F).
- **Feasibility:** architecture fit 5 (workflow-only), effort 4 (scripts exist; amend ordering + preflight + diagnostics), risk 2 (changes timing, not topology), testability 4 (deterministic batches locally reproducible), maintainability 4 (contract documented in Plan K amendment).
- **Evidence:** serialization pattern (oven-sh/bun 2ad4199); hosted-runner network flakiness context (actions/runner-images#7862, #6526); `--wait` not a sole gate (docker/compose#10596, #13069).

### Option B — Workflow amendment: single-owner compose coordinator + engine-level per-container gates (alternative workflow-only candidate)

- **Summary:** exactly one process per run owns all compose operations and gates readiness at the engine level (`docker inspect`/`docker wait` per container ID), never at the compose-CLI level.
- **Mechanism:** the workflow delegates ALL compose operations to a single coordinator; concurrent/parallel compose invocations become structurally impossible; per-service readiness is polled via `docker inspect` state/health, and one-shot services via engine-level `docker wait` (returns the recorded exit code and works on already-exited containers); failure diagnostics are captured by the same owner. This operationalizes "do not use `docker compose --wait` as the sole gate" at the mechanism level.
- **Codebase fit:** the existing `wait-for-*.sh` scripts can be consolidated under one owner; the bounded-retry + reconciliation contract in `2d84d07` remains intact.
- **Preserves every L9 invariant:** same topology; workflow-only.
- **Tradeoffs:** more machinery than A (a coordinator process is a new failure surface that must itself be diagnosable); overlaps A on serialization; may be harder to review than A's explicit batch ordering.
- **Feasibility:** architecture fit 5, effort 3 (more code than A), risk 3 (new single-owner process), testability 4, maintainability 3.
- **Evidence:** single-owner compose coordinator (oven-sh/bun 2ad4199); healthchecks + `docker wait` replacing `--wait` (SpecHive abc6dea).

### Option C — Topology change: host networking / in-network job execution (compared; fallback only)

- **Summary:** eliminate the daemon netns bind-mount surface by running the job inside a container on the compose network (no published host ports), or by host networking for the stack.
- **Mechanism:** job-container on the compose network reaching services by name (the GitHub-Actions service-container pattern), or `network_mode: host` for services.
- **Tradeoffs:** proven effective at removing port/network race classes (ma.ttias.be 16-way harness: 14/16 with host ports → 16/16 without), BUT it changes the release-evidence surface: the approved DD's release target is the exact split topology with default-bridge routing (engine gRPC 7070 route, dashboard separate, JWT/config/auth checks). Host networking or in-network execution would prove a different network topology than production. That makes this an architecture/topology change (L5), which the DD anchor and the researcher verdict do not support at this stage. Keep as a bounded contingency if A+B fail to stabilize hosted runs — and only via a new DD amendment.
- **Feasibility:** architecture fit 2 (violates the DD's exact-topology evidence contract), effort 3, risk 4 (new topology = new unknown behaviors; changes the proof surface), testability 2 (cannot prove production netns behavior), maintainability 3.
- **Evidence:** job-in-container + no host ports (ma.ttias.be); hosted-agent network variance (actions/runner-images#6526).

### Option D — Topology bypass: DinD / socket mounts / privileged-unconfined (REJECTED)

- **Summary:** run Docker inside Docker, mount the host docker socket into containers, or grant privileged/unconfined seccomp/AppArmor as a blanket.
- **Mechanism:** nested daemon (DinD) or `privileged: true` + `seccomp=unconfined`/AppArmor unconfined.
- **Why rejected:** (1) DinD has its own netns/daemon lifecycle races and is not the approved topology; (2) socket mounts and privileged/unconfined bypass are a security-posture tradeoff and invalidate the sandbox isolation the project exists to prove — R16/R17 were sandbox seccomp defects, and the fix is the P3-S3 seccomp amendment, not unconfining everything; (3) the DD already rejects privileged/unconfined broad bypass; (4) it would prove a different scheduler/security surface than production (same objection as Lite).
- **Feasibility:** architecture fit 1, effort 4 (nested-daemon complexity), risk 5 (security + evidence invalidation), testability 1, maintainability 1.

### Forbidden per L9 (restated as non-options, not alternatives)

Skipping sandbox; optional/trigger-level gate; fake readiness (a readiness line or version ping alone); second scheduler; treating all errors as transient. R15/R16/R17 prove distinct root-cause classes (orchestration defect vs seccomp defects vs workflow-induced false absence); blind retry (F) would mask all three. The DD rejects a second scheduler (C1: repository DAG = lineage authority; Hatchet = scheduler authority). These remain non-options for every turn.

### Ranked recommendation (T1)

1. **Option A** — workflow-only amendment; matches the researcher verdict and the DD anchor; smallest bounded change; preserves every L9 invariant.
2. **Option B** — workflow-only; strongest on the "sole gate" objection; more machinery; best treated as a complement folded into A (single-owner + engine-level gates) rather than a rival.
3. **Option C** — topology fallback only; bounded contingency if A+B fail to stabilize hosted runs, via a new DD amendment.
4. **Option D** — rejected; document the security/evidence tradeoff, do not adopt.

**Verdict direction:** workflow-design change (DD/Plan-K amendment), not architecture/topology change — consistent with L5, the researcher verdict, and the approved DD anchor. The amendment must carry: capability preflight; serialized startup batches; exact-marker bounded retry; post-up reconciliation (never weakened); per-service diagnostic contract; no `--wait` sole gate; sandbox-class failures fail closed; full split Hatchet / real callbacks / hosted mandatory validation / no skip-stub-fake-readiness / no second scheduler (L9) intact.

**Open risks / human questions:** (1) R18 (33228898244) outcome is unknown — every decision here must be revisited once retrieved from GitHub; (2) whether serialization alone removes the race on hosted runners is unproven until a green hosted run; (3) the per-batch ordering contract adds review burden to future compose changes; (4) hosted runner image / docker-compose version drift can change the exact-marker set — tier-3 sources checked 2026-08-29 are snapshots, not guarantees; re-validate the marker list when runner images change.

## T2 Counter-Ideator — Critique

**Turn 2 scope.** I read the T1 approaches (A–D + forbidden list) against the immutable
ledger, the DD anchor, and the current workflow (`validation.yml:309-384`). Every critique
below cites a real source (tier noted) checked 2026-08-29; hosted tier-1 evidence is cited
where it exists. Explicit tests performed: serialization, daemon preflight, exact-marker
retry, pipefail/status preservation, reconciliation, diagnostics, topology changes, and the
R18-unknown handling. No code, workflow, DD, or plan edits are proposed (L7).

### Approach A — serialized startup + preflight + exact-marker retry + reconciliation

- **Source:** [Tier 2] axonops/audit#622 — real CI postmortem: `make ... 2>&1 | tee
  /tmp/bdd-output.txt` without pipefail masked every BDD failure for months; CI was
  green-but-broken. **Link:** https://github.com/axonops/audit/issues/622
  **Finding:** the pipeline exit status is `tee`'s (always 0), not the left-side command's.
  **Relevance:** the current workflow's retry gate is `if docker compose ... 2>&1 | tee
  /tmp/compose-up.log; then` (`validation.yml:328-330`) with no `set -o pipefail`.
  **Severity:** HIGH — fatal to A's exact-marker mechanism as written.
- **Source:** [Tier 3] actions/runner-images#4459 — GitHub's default `bash` shell is
  invoked as `/usr/bin/bash -e {0}` WITHOUT pipefail (contested against the docs; the
  opposite reading appears in mlflow/mlflow#23155, 2026-05). **Link:**
  https://github.com/actions/runner-images/issues/4459
  **Finding:** whether pipefail is on by default is contested and version-dependent.
  **Relevance:** A's bounded-retry contract silently depends on it. If pipefail is off and
  compose fails while `tee` succeeds: (a) the exact-marker retry never fires — every netns
  failure is instead pushed into the reconciliation re-up loop, which re-runs `up` on ANY
  state mismatch (`validation.yml:375-377`, output hidden with `>/tmp/compose-reconcile.log
  2>&1 || true`); (b) non-transient failures (denied image, config error) are swallowed the
  same way — the "treat all errors as transient" trap in inverted form. **Severity:** HIGH.
- **Source:** [Tier 3] moby/moby#50750 + containerd/containerd#12141 + langgenius/dify#7739.
  **Links:** https://github.com/moby/moby/issues/50750,
  https://github.com/containerd/containerd/issues/12141,
  https://github.com/langgenius/dify/issues/7739
  **Finding:** the exact marker `bind-mount /proc/<pid>/ns/net -> /var/run/docker/netns/<id>:
  no such file or directory` has MULTIPLE root causes. moby#50750: since Docker 28.0.0 the
  daemon asks containerd to create the task, then bind-mounts the task's netns — on
  checkpoint-restore the pid is 0 and the source never exists. dify#7739: the identical
  string fired on a plain `docker compose up -d db` for one service; the maintainer
  classified it as environment-specific, not app code. **Relevance:** the marker confirms "a
  netns bind-mount source disappeared," NOT "transient daemon race." Our R10 marker used a
  live pid (`/proc/4009/ns/net`) — consistent with the transient race, but not proof. Retry
  on the marker is sound ONLY if bounded AND paired with an escalation clause: budget
  exhausted on a clean runner → preserve evidence, escalate as a hosted-runner/daemon issue,
  never silently enlarge the budget. A says "small cap and backoff" but must name the
  escalation outcome. **Severity:** HIGH for classification integrity.
- **Source:** [Tier 1] hosted R10 + R15 (restated exactly from the ledger).
  **Finding:** R10 fired under ~10 simultaneous starts; R15 proved `compose up` can exit 0
  with services in Created. **Relevance:** serialization narrows the simultaneous window but
  cannot make it zero (dify#7739 fired with a single service), and a preflight cannot predict
  the race window (it lives in task-create→netns-discover→bind-mount, after any daemon ping).
  A must keep bounded retry + reconciliation as the actual gate and label preflight a
  capability snapshot, never a readiness proof (a "fake readiness" variant). **Severity:**
  MEDIUM (contract clarity).
- **Source:** [Tier 1] validation.yml:280-307 + Plan K P2-S4 (JWT minting after migrate+admin
  config generation, exported to GITHUB_ENV before api/worker container creation).
  **Finding:** compose resolves api/worker env at container create; `UMD_HATCHET_TOKEN` must
  exist before batch 4. **Relevance:** A's batch list `db → migrate+admin → engine+dashboard
  → api+worker+sandbox-runner` omits the tenant-discovery + JWT-mint step as a named
  dependency. Without it, api/worker start without a token and the worker-registration gate
  fails for a configuration reason that is misattributable to the netns race. **Severity:**
  MEDIUM — the amendment must interleave JWT mint before the api/worker batch.
- **Source:** [Tier 1] R17 + validation.yml:346-382.
  **Finding:** R17 showed one-shot false absence under `ps -q` without `-a`; the current
  reconcile already uses `ps -a -q` + inspect `State.Status`, but the re-up recovery hides
  its output with `>/tmp/compose-reconcile.log 2>&1 || true` and classifies only
  running/exited. **Relevance:** the amended reconciliation must additionally require:
  one-shots exited with `State.ExitCode == 0`, long-lived services not `restarting`, no
  non-empty `State.Error`, no `State.OOMKilled`; and the recovery re-up must emit its output
  so a post-hoc marker-vs-non-marker classification is possible. **Severity:** MEDIUM.

### Approach B — single-owner coordinator + engine-level gates

- **Source:** [Tier 3] Docker CLI reference — `docker wait` has no timeout flag.
  **Link:** https://docs.docker.com/reference/cli/docker/container/wait/
  **Finding:** `docker wait` blocks until the container stops; for a hung or never-exiting
  container the caller must enforce its own deadline. **Relevance:** B's engine-level gates
  must specify a bounded wait (shell `timeout` or polling with deadline) or a wedged one-shot
  hangs the pipeline indefinitely. Correct usage for one-shots (including `restart:
  on-failure` — `docker wait` returns on first stop, surfacing the non-zero exit) is sound.
  **Severity:** MEDIUM.
- **Source:** [Tier 2] axonops/audit#622 (same masking class as A).
  **Finding:** a coordinator process does not fix status masking if its own invocation is
  piped to `tee` without pipefail. **Relevance:** B inherits A's pipefail gap; the
  coordinator script must itself run under `set -euo pipefail` and preserve `PIPESTATUS`
  across every compose invocation, or B centralizes the same bug into one point. **Severity:**
  MEDIUM.
- **Source:** [Tier 3] (self-evident design risk, acknowledged by T1 as risk 3).
  **Finding:** a single-owner process is a new failure surface. **Relevance:** the
  coordinator's own logs must flow through the same `if: always()` diagnostics path, and its
  death must fail the run with evidence — never fall back to a second compose owner
  (re-introduces the concurrency B exists to remove). **Severity:** LOW.

### Approach C — topology fallback (host networking / in-network execution)

- **Source:** [Tier 3] ma.ttias.be rootless-docker writeup + Docker host-network docs.
  **Link:** https://docs.docker.com/engine/network/drivers/host/
  **Finding:** the 16-way harness evidence concerns host-PORT publication races — a different
  failure class from the daemon netns bind-mount (moby/moby#50750). Host mode shares the host
  network namespace and removes per-container IP allocation. **Relevance:** the cited
  mechanism evidence does not transfer to the netns race; host networking sidesteps the
  bridge-netns path but invalidates the same-stack proof surface (published engine gRPC 7070
  / dashboard 8081 routes are part of the DD evidence per `validation.yml:304-307`). C is
  correctly fallback-only in T1; the amendment must keep it gated behind a new DD decision
  and not over-read the port-race evidence. **Severity:** MEDIUM (evidence hygiene; C already
  correctly rejected for now).
- **Source:** [Tier 1] R11 (full split topology booted) + R10 (failure during concurrent
  creation). **Finding:** no hosted evidence establishes topology causality. **Relevance:**
  supports C's fallback-only status — restated as agreement, not a new concern.
  **Severity:** LOW (agreement).

### Approach D — DinD / socket mounts / privileged-unconfined (rejected — agreement + evidence)

- **Source:** [Tier 3] actions/runner#4117 (docker-socket "broken pipe" failures in dind
  under runner v2.329.0) + actions/actions-runner-controller#3794 (iptables chain conflicts
  when two dind runners share a node). **Links:**
  https://github.com/actions/runner/issues/4117,
  https://github.com/actions/actions-runner-controller/issues/3794
  **Finding:** DinD has its own daemon/network race family and expands the Docker trust
  boundary. **Relevance:** moving to DinD trades the hosted netns race for dind races while
  still not reproducing the production topology — strengthens T1's rejection with tier-3
  evidence. **Severity:** supporting.
- **Source:** [Tier 3] Docker seccomp docs + moby `profiles/seccomp/default_linux.go`
  (v28). **Link:** https://docs.docker.com/engine/security/seccomp/
  **Finding:** the default profile is an allowlist with `SCMP_ACT_ERRNO` default; `unshare`,
  `setns`, `mount`, `clone3`, `fsmount`, `mount_setattr`, etc. are allowed ONLY when gated by
  `CAP_SYS_ADMIN`. `pivot_root` is not in the default allowlist at all. **Relevance:** the
  P3-S3 seccomp JSON being "moby default + pivot_root" is necessary but NOT sufficient proof
  the sandbox boots under `cap_drop ALL`/no-new-privileges — the syscall allows are
  capability-gated. Any claim that the current profile "proves" bwrap works is PROVISIONAL
  until a hosted run passes the sandbox boot gate. This also reframes R16/R17: the correct
  response is profile repair (already amended), never blanket unconfining. **Severity:**
  MEDIUM — flags a PROVISIONAL claim, not a defect in D's rejection.

### Cross-cutting tests (per instruction)

- **R18 unknown (explicit test):** T1 correctly marks R18 (33228898244) NOT established. I
  additionally flag that the rnd-architect options doc read as an input asserts an R18
  reading (job 99037936832: topology reached readiness, one marker recovered, worker
  registered 9 workflows, live suite failed on host-SDK/uniqueness). That assertion is NOT in
  the DD's hosted-evidence table and is PROVISIONAL until the GitHub run is retrieved. T3
  must not lean on either T1's caution or the architect's assertion as fact. If retrieved and
  green-boot, R18 supports A's direction but still does NOT close the release gate (live
  suite failed on unrelated defects); if it shows budget exhaustion, it argues for escalation,
  not more retries.
- **Diagnostics contract (explicit test):** the `if: always()` capture-diagnostics path must
  run before teardown even when the startup gate fails, must never decide the gate outcome
  (collection-only `|| true` is fine), and must include the compose-up + reconcile logs so a
  failed marker-retry can be post-hoc classified transient-vs-persistent from evidence. A/B
  must state this explicitly; the current script's non-masking contract must survive.
- **Immutable requirements (explicit test):** A and B preserve every L9 invariant — verified
  against the ledger. C is correctly gated behind a new DD amendment. D is rejected. The
  forbidden list (Lite, skips/stubs/fake readiness, second scheduler, blanket retry) matches
  the ledger — restatement verified, no weakening found.

### Summary

- **Surviving approaches:** A, amended — must add (1) explicit `set -o pipefail` /
  `PIPESTATUS` status preservation as a named contract item (HIGH), (2) escalation-on-budget-
  exhaustion for the exact marker (HIGH), (3) JWT-mint interleaving before the api/worker
  batch (MEDIUM), (4) reconciliation requirements: `ps -a`, one-shot exit code 0, no
  restarting/OOM/daemon-error, visible recovery output (MEDIUM). B, as a complement folded
  into A (single owner + engine-level gates + explicit timeouts), not a rival.
- **Dead approaches:** D (rejected, evidence added); C is fallback-only and requires a new DD
  amendment and evidence hygiene (port-race evidence ≠ netns-race evidence).
- **Most critical unresolved concern for T3:** the exact-marker retry and the reconcile
  re-up classification both depend on exit-status preservation that neither A nor B states
  explicitly. Make `set -o pipefail`/`PIPESTATUS` capture mandatory, and specify that a
  reconcile re-up is classified as a bounded marker retry only when the exact marker is
  present in the visible compose evidence — otherwise it is a hard failure with diagnostics.

## T3 Ideator — Refined Approaches

**Turn 3 scope.** This turn refines the surviving workflow design in direct response to T2.
It does not re-propose T1 wholesale: it disposes of every T2 critique (severity noted),
folds B into A as a single-owner wrapper mechanism, reassesses the topology options,
and produces the exact amended workflow contract the DD/Plan-K amendment must carry.
R10/R11/R15/R16/R17 are restated exactly from the ledger below (not paraphrased from any
downstream report). R18 (`33228898244`) remains **NOT established** — see the dedicated
subsection; the `rnd-architect` report's R18 assertion is tier-2 local analysis and is
explicitly not relied upon as fact. All technology claims below were re-checked against
current official/maintainer sources on **2026-08-29**; anything unvalidated is labeled
PROVISIONAL. No code, workflow, DD, or plan edits are made (L7).

### T2 critique disposition (what T3 changes and why)

| T2 critique | Severity | Disposition in T3 |
|---|---|---|
| Exact-marker retry and reconcile classification depend on exit-status preservation that neither T1 approach stated explicitly | HIGH (most critical) | Contract items 1 + 4b: mandatory `set -euo pipefail` + `PIPESTATUS[0]` capture around every compose pipeline; a reconcile re-up is a bounded marker retry only when the exact marker is present in its visible output — otherwise hard failure. |
| Budget exhaustion needs a named escalation outcome, not "small cap and backoff" | HIGH | Contract item 4a: on clean-runner budget exhaustion → preserve evidence, fail with `hosted-netns-escalation: TRUE`, never silently enlarge the budget. |
| Marker has multiple root causes; marker confirms "netns source disappeared", not "transient" | HIGH (classification integrity) | Contract item 4 preamble: marker classified per-attempt from visible output; recurrence mechanism stays INCONCLUSIVE until per-run daemon/timing evidence (debugger L5). |
| Preflight is a capability snapshot, never a readiness proof | MEDIUM | Contract item 2: explicit labeling; preflight failure is a named hard failure, not a readiness signal. |
| JWT mint must be a named dependency interleaved before the api/worker batch | MEDIUM | Contract item 3: corrected batch list (Batch 2 → JWT mint → Batch 3 → Batch 4). |
| Reconciliation must require one-shot exit 0, no restarting/OOM/daemon-error, visible recovery output | MEDIUM | Contract items 5–7. |
| `docker wait` has no timeout flag; bounded wait required | MEDIUM | Contract item 5: explicit `timeout` wrapper around engine-level waits. |
| Single-owner coordinator inherits pipefail gap and is itself a failure surface | MEDIUM/LOW | B′ wrapper runs under `set -euo pipefail`; its death fails the run with evidence, never falls back to a second compose owner. |
| C's port-race evidence does not transfer to the netns bind-mount class | MEDIUM (evidence hygiene) | C stays fallback-only behind a new DD; evidence table below adds the daemon-side sources. |
| R18 unknown must not be leaned on either way | Explicit test | R18 subsection: kept UNKNOWN/PROVISIONAL; no reliance on the architect doc's assertion. |
| Diagnostics must run before teardown and never decide the gate | Explicit test | Contract item 8: `if: always()` collection-only; non-masking contract preserved. |

### Hosted evidence restated exactly (authoritative tier — binding for the amendment)

| Run | Evidence (verbatim reading from the ledger) | Implication for the refined contract |
|---|---|---|
| R10 / `33226227591` | `Error response from daemon: bind-mount /proc/4009/ns/net -> /var/run/docker/netns/06d21594cf1f: no such file or directory` during ~10 simultaneous default-bridge starts | Live-pid marker (not checkpoint pid 0); daemon netns bind-mount failure before app code; serialization (item 3) narrows the simultaneous window; marker retry (item 4) with exact classification. |
| R11 / `33226431905` | Netns retry then independent alembic.ini failure | Netns handling must never mask independent app failures (items 4/9 classify, never blanket-retry). |
| R15 / `33227518543` | `compose up` exited 0 while required services stayed Created | Aggregate compose exit code is never the gate (item 7); post-up reconciliation (`2d84d07`) is the deterministic fail-closed gate and must not be weakened (L3). |
| R16 / `33228084721` | Sandbox bwrap `statx`/`fsmount` EPERM | Seccomp profile defect, distinct root cause from netns (item 9); never consumes netns budget. |
| R17 / `33228376245` | Sandbox `getcwd`/`vfork` EPERM, `sandbox-runner=restarting`, `hatchet-migrate/admin=absent` in `ps -q` view | Workflow-induced false absence (one-shot `ps -q` without `-a`) → item 5 mandates `ps -a` + inspect exit-code evidence; seccomp class fixed by P3-S3 moby-default+pivot_root amendment. |
| R18 / `33228898244` | **Result NOT established in this corpus — do not invent it.** | Any claim about R18 outcome is PROVISIONAL until retrieved from GitHub (see R18 subsection). |

### Refined Approach A′ — serialized startup + capability preflight + exact-marker bounded retry with escalation + classified reconciliation (RECOMMENDED; B′ folded in as the single-owner wrapper)

**Summary.** Keep the exact split-Hatchet topology and change only the startup contract:
one workflow wrapper owns all compose operations; compose calls are ordered into four
dependency batches with the JWT mint interleaved; every pipeline preserves its true exit
status; only the exact netns marker is retried, with a named budget and a named escalation
outcome; post-up reconciliation remains the deterministic fail-closed gate, now with
per-service exit-code/restart/OOM/error evidence and visible recovery output.

**Mechanism — the exact amended workflow contract (the DD/Plan-K amendment must carry these ten items verbatim):**

1. **Exit-status preservation contract (PIPESTATUS/pipefail).** Every compose-owning step
   and script begins with `set -euo pipefail`; every `docker compose ... 2>&1 | tee <log>`
   invocation captures `rc=${PIPESTATUS[0]}` immediately and branches on the captured rc —
   never on the pipeline tail. This is **version-independent by design**: GitHub's ADR 0277
   documents the default `bash` shell as `bash --noprofile --norc -eo pipefail {0}`
   (actions/runner ADR "run-action-shell-options"), while actions/runner-images#4459
   contests that the actual hosted default is `/usr/bin/bash -e {0}` without pipefail. T3
   removes the ambiguity: the workflow does not rely on the default. Rationale: the
   axonops/audit#622 postmortem (CI green-but-broken for months because `make | tee` masked
   every failure) proves the failure class this contract closes. This is the single most
   important change; items 4 and 7 depend on it.
2. **Daemon/version capability preflight.** Before any container creation: `docker version`
   (client + server), `docker info` (storage driver, containerd/runc versions, cgroup
   version), `docker compose version`, `docker network ls` capability snapshot, and the
   existing P3-S4 exact-image manifest tripwire (`preflight-hatchet-images.sh` already
   fails on any denied/nonexistent split image). Preflight failure = named hard failure.
   Explicitly a **capability snapshot**, never a readiness proof (T2 MEDIUM; avoids a
   "fake readiness" variant). Matches researcher L6 amendment (a).
3. **Serialized startup batches with JWT dependency ordering.** One wrapper runs compose in
   four dependency-ordered invocations, never one simultaneous ~10-service `up`:
   - **Batch 1 — `db`:** wait for Postgres health (inspect `State.Health` or `pg_isready`).
   - **Batch 2 — `hatchet-migrate` + `hatchet-admin`:** one-shots must reach `exited` with
     `State.ExitCode == 0` and the shared `/hatchet/config` volume populated; then **mint
     the real tenant JWT** (existing bounded 30x2s case-insensitive tenant discovery +
     `hatchet-admin token create`, exporting `HATCHET_TENANT_TOKEN`/`UMD_HATCHET_TOKEN` to
     `GITHUB_ENV`) **before Batch 3/4 create any container that consumes it**. This corrects
     T1's batch list, which omitted the JWT-mint as a named dependency (T2 MEDIUM: compose
     resolves api/worker env at container create; `UMD_HATCHET_TOKEN` must exist first;
     the current workflow already does this two-phase, `validation.yml:248-307`).
   - **Batch 3 — `hatchet-engine` + `hatchet-dashboard`:** engine gRPC 7070 route and
     dashboard health verified.
   - **Batch 4 — `api` + `worker` + `sandbox-runner`:** api `/v1/ready`, worker real
     registration (`wait-for-worker.sh` grep of the exact C6 readiness line), sandbox no
     restart loop and no security EPERM.
   Serialization precedent: oven-sh/bun commit 2ad4199 ("ci: serialize docker service
   startup through a per-shard coordinator") — production proof that concurrent `compose
   up` for one project is itself a race source and that serialization + single ownership
   removes the create-race class.
4. **Exact-marker bounded retry with escalation.**
   - **Marker set (exact):** retry ONLY the full daemon marker
     `bind-mount /proc/<pid>/ns/net -> /var/run/docker/netns/<id>: no such file or
     directory` (variable pid/id). Do not retry on "not running", timeout, EPERM, OOM,
     invalid config, missing image, nonzero one-shot exit, or generic text.
   - **Budget:** 3 attempts per batch, no rebuild after attempt 1 (`--no-build`), fixed
     backoff (e.g., 5s). Attempts are counted from the *visible* compose output under item
     1's pipefail contract.
   - **4a. Escalation (T2 HIGH):** budget exhausted on the SAME clean runner → preserve the
     full evidence set, fail the run with `hosted-netns-escalation: TRUE` recorded in the
     release summary, and route as a hosted-runner/daemon issue. Never silently enlarge the
     budget, never convert to blanket retry (forbidden F).
   - **4b. Reconcile-re-up classification (T2's most critical concern):** a reconciliation
     re-up is classified as a bounded marker retry ONLY when the exact marker is present in
     that re-up's visible output. Any other mismatch after a re-up is a hard failure with
     diagnostics — never re-run-forever (the current `validation.yml:375-377` `|| true`
     loop is the anti-pattern this replaces).
   - **Marker honesty:** moby/moby#50750 (maintainer-described: since Docker 28.0.0 the
     prestart hook is gone; the daemon asks containerd to create the task and bind-mounts
     the task's netns from `/proc/<pid>/ns/net`; the code persists in v28.5.2
     `libnetwork/osl/namespace_linux.go`) and containerd/containerd#12141 (criu CI + gvisor
     triggers) prove the marker has MULTIPLE trigger contexts — checkpoint-restore pid 0,
     CRIU CI, and ordinary task-create. Our R10 marker used a **live pid** (`/proc/4009`),
     consistent with the transient class during concurrent creation, but that is evidence,
     not proof: recurrence mechanism stays INCONCLUSIVE until per-run daemon/runtime/timing
     evidence is captured (debugger L5). The classification contract above is the honest
     posture; the marker alone never authorizes blanket retry.
5. **One-shot exit-code-0 semantics and engine-level gates.** Reconciliation inspects EVERY
   required service with `docker compose ps -a` (never `ps -q` — R17 false-absence) plus
   `docker inspect` per container: long-lived services `State.Status == running`, empty
   `State.Error`, not `restarting`, `State.OOMKilled == false`; one-shots
   (`hatchet-migrate`, `hatchet-admin`) `State.Status == exited` **and**
   `State.ExitCode == 0`. Engine-level `docker wait <cid>` may gate one-shot completion
   (SpecHive commit abc6dea replaced `compose up --wait` with exactly this: `docker wait`
   works on already-exited containers and returns the recorded exit code) **but must be
   wrapped in an explicit `timeout`** — `docker wait` has no timeout flag (Docker CLI
   reference), so a wedged one-shot would otherwise hang the pipeline (T2 MEDIUM).
6. **Visible recovery output.** No `>/tmp/... 2>&1 || true` on any retry or reconcile
   re-up. Every recovery compose invocation writes to a labeled log that is (a) streamed to
   the step output, (b) retained as an artifact, and (c) included in diagnostics — so a
   post-hoc marker-vs-non-marker classification is always possible from evidence (items 4b
   and 8 depend on this). The current `validation.yml:375-377` suppression is removed.
7. **Post-up state reconciliation as the deterministic fail-closed gate.** After every batch
   and after every retry, reconcile the required state set under item 1's exit-status
   contract. On mismatch: re-run ONLY the affected batch under item 4b's classification;
   budget exhausted → hard failure. The aggregate `compose up` exit code is never trusted
   as the gate — this is the direct answer to R15 (`up` exited 0 with services in
   `Created`). The `2d84d07` reconciliation remains the fail-closed gate and must not be
   weakened (L3).
8. **Diagnostics contract.** `capture-diagnostics.sh` runs under `if: always()` BEFORE any
   teardown and is collection-only: its `|| true` guards must never decide the gate outcome
   (the DD P3-S5 non-masking contract survives). Required additions: daemon/version/network
   facts from item 2, per-service inspect JSON (status/exit/restart/error/OOM/health),
   the compose-up and reconcile logs from item 6, `docker network inspect`, sandbox
   seccomp/AppArmor/userns observations, DB dump, OCFL listing/fixity, JUnit/coverage, and
   the `live-worker-gate` verdict. A failed marker-retry must be post-hoc classifiable
   transient-vs-persistent from this evidence (T2 explicit test).
9. **Distinct sandbox security classification.** `statx`, `fsmount`, `getcwd`, `vfork`,
   `clone`, `unshare`, or related `EPERM` in sandbox logs is a sandbox profile/AppArmor/
   userns failure: it FAILS the run closed and routes to security/profile diagnosis (the
   P3-S3 moby-default + `pivot_root` profile is the amended fix), and it NEVER consumes
   netns retry budget. R16/R17 are the hosted proof the two classes are distinct (R16:
   `statx`/`fsmount` EPERM; R17: `getcwd`/`vfork` EPERM + `sandbox-runner=restarting`).
   PROVISIONAL claim (T2 MEDIUM): Docker's default seccomp profile is an allowlist whose
   namespace syscalls (`unshare`, `setns`, `mount`, `clone3`, `fsmount`, `mount_setattr`)
   are allowed only when gated by `CAP_SYS_ADMIN` (Docker seccomp docs); "the P3-S3 profile
   proves bwrap boots under cap_drop ALL/no-new-privileges" is therefore PROVISIONAL until a
   hosted run passes the sandbox boot gate. Blanket privileged/unconfined remains rejected.
10. **No `--wait` sole gate.** `docker compose up --wait` may be a convenience at most,
    never the gate. It is by-design incompatible with one-shot services that exit 0 —
    docker/compose#10596 (still reproduced as of compose 2.24.7, confirmed in a 2025-04
    forum report) and docker/compose#11774 (closed without a real fix; workarounds are
    `--wait-services`, done-file healthchecks, or dummy downstream services) — and its
    restart-policy semantics are contested (docker/compose#11638, #13069, #12424). The
    engine-level inspect/wait evidence in items 5/7 is the gate; SpecHive commit abc6dea
    (2026-04-27) is a current production replacement precedent.

**Codebase fit.** `.github/scripts/preflight-hatchet-images.sh` already provides item 2's
image tripwire; `wait-for-http.sh`/`wait-for-worker.sh` already gate api/worker; the
two-phase config-generation + JWT-mint block (`validation.yml:248-307`) already exists and
is extended into the four-batch shape; `capture-diagnostics.sh` already runs under
`if: always()` and is extended per item 8; the `2d84d07` reconciliation is preserved and
strengthened per items 5–7.

**Preserves every L9 invariant.** Full split Hatchet topology (migrate → admin → engine +
dashboard + UMD db/api/worker/sandbox-runner); real callbacks with engine-visible
registration and callback-owned rows; mandatory hosted validation (no opt-in, fail on
skip); no skips/stubs/fake readiness (item 2's preflight is explicitly not readiness);
no second scheduler; sandbox mandatory with the seccomp profile (never skipped, never
unconfined). Purely a workflow contract — matching the researcher verdict (L6), the
debugger NEEDS_PLAN classification (L5), and the DD anchor's workflow-only orientation.
**L5 answer: workflow-design change, not architecture/topology change.**

**Tradeoffs.** Adds cold-start wall time (4 batches + interleaved JWT mint); introduces a
per-batch ordering contract future compose changes must respect; the wrapper script is a
new reviewable surface. Risk: the retry/escalation policy must stay provably bounded so the
"treat all errors as transient" trap (forbidden F) cannot re-enter through the reconcile
path.

**Feasibility:** architecture fit 5 (workflow-only), effort 3 (scripts exist; amend
ordering + pipefail + classification), risk 2 (changes timing and status handling, not
topology), testability 4 (deterministic batches locally reproducible; shell classification
unit-testable), maintainability 4 (contract documented in the Plan K amendment).

**Evidence:** moby/moby#50750 + containerd/containerd#12141 (marker mechanism, checked
2026-08-29); actions/runner ADR 0277 vs actions/runner-images#4459 (pipefail default
contested → contract item 1 makes it explicit); axonops/audit#622 (tee masking postmortem);
oven-sh/bun 2ad4199 (serialization + single owner); SpecHive abc6dea (engine-level
`docker wait` + timeout, 2026-04-27); docker/compose#10596/#11774/#11638/#13069/#12424
(`--wait` not a sole gate); Docker CLI reference (`docker wait` no timeout).

### Refined Approach B′ — single-owner wrapper (folded into A′, not a rival)

**Summary.** Exactly one process per run owns ALL compose operations; concurrent or
competing compose invocations become structurally impossible. B′ is now the *mechanism*
A′ runs under (a workflow-level script such as `compose-start.sh`), not a separate option:
A′'s batches, classification, and reconciliation execute inside the single owner.

**Mechanism.** The wrapper: (1) runs under `set -euo pipefail` (it must not centralize
item 1's bug into one point — T2 MEDIUM); (2) holds the batch state machine and the
per-service inspect evidence; (3) decides retry-vs-fail under item 4's exact-marker rule;
(4) on its own death (script error, unreadable log, missing container), fails the run with
its log flowing through the same `if: always()` diagnostics path — it never falls back to
a second compose owner, which would reintroduce the concurrency it exists to remove
(T2 LOW). The oven-sh/bun 2ad4199 coordinator is the production precedent: a single
coordinator with an in-flight map collapses concurrent requests onto one `compose up`, and
an `ok=false` reply is a real service failure that is thrown, not retried.

**Tradeoffs.** A new script is a new failure surface and must be reviewed like product
code; it adds review burden beyond A′'s explicit batch ordering alone. This is why B′ is
folded into A′ (the wrapper owns the batches) rather than ranked as a separate option.

### Approach C — topology change (reassessed; fallback only, gated behind a new DD)

**Reassessment.** No hosted evidence establishes topology causality: R11 booted the full
split topology; R10 failed during concurrent creation; the daemon-side lifecycle is the
race surface (moby/moby#50750, #46490 — the 2023 `lstat /proc/<pid>/ns/net` class under
concurrent compose; #50326 — daemon-restart netns ordering, fixed daemon-side by
moby/moby#50327). Host networking shares the host netns and in-network job execution
changes the published-port evidence surface the DD requires; the ma.ttias.be port-race
evidence does not transfer to the netns bind-mount class (T2 MEDIUM evidence hygiene).
**C remains rejected for now, fallback only** if A′+B′ fail to stabilize hosted runs AND
per-run daemon evidence proves a persistent hosted-runner limitation — and only through a
new DD amendment.

### Approach D — DinD / socket mounts / privileged-unconfined (dead; evidence strengthened)

**Why still dead.** DinD trades the hosted netns race for dind's own race family:
actions/runner#4117 (dind "broken pipe" failures) and actions-runner-controller#3828
(dind connection failures scale with runner count; required a wait-for-docker sidecar).
Socket mounts and privileged/unconfined bypasses expand the Docker trust boundary and
invalidate the sandbox isolation R16/R17 were about — the correct response is the P3-S3
profile repair, never blanket unconfining. A second scheduler remains forbidden by L9/C1.
**Feasibility:** architecture fit 1, effort 4, risk 5, testability 1, maintainability 1.

### R18 (`33228898244`) handling — UNKNOWN unless corroborated

T3 does **not** rely on either T1's caution-only framing or the `rnd-architect` report's
assertion (job `99037936832`: topology reached readiness, one marker recovered, worker
registered 9 workflows, live suite failed on host-SDK/uniqueness). The librarian L20
confirms R18's outcome is **not present in the log corpus** (grep for `33228898244` only
matches exec-manager's push note); the architect report is tier-2 local analysis and its
asserted R18 reading is **PROVISIONAL until the GitHub run is retrieved** (tier-1
evidence). Every decision in this section is therefore conditional: if R18 is retrieved
and shows a green boot, it supports A′'s direction (and still does not close the release
gate — live-suite failures are separate repairs, never netns relabels); if it shows budget
exhaustion, it argues for item 4a escalation, never more retries and never a topology
change.

### Ranked recommendation (T3)

1. **A′ (with B′ folded in as the single-owner wrapper)** — workflow-only amendment; the
   exact 10-item contract above is what the DD/Plan-K amendment must carry; every L9
   invariant preserved.
2. **C** — fallback only; requires a new DD amendment and runner/daemon-level evidence
   before any topology change.
3. **D** — rejected; document the security/evidence tradeoff, do not adopt.

**Verdict direction (unchanged from T1, now evidence-hardened):** workflow-design change
(DD/Plan-K amendment), not architecture/topology change — consistent with L5, the
researcher verdict (L6), the debugger classification (L5), and the approved DD anchor. The
amendment must carry the ten contract items verbatim: (1) pipefail/PIPESTATUS, (2) daemon/
version preflight as capability snapshot, (3) serialized batches with JWT interleave,
(4) exact-marker bounded retry + escalation + reconcile classification, (5) one-shot
exit-code-0 semantics with bounded engine waits, (6) visible recovery output, (7) post-up
reconciliation as the fail-closed gate, (8) diagnostics before teardown, (9) distinct
sandbox seccomp classification, (10) no `--wait` sole gate.

### Technology citations (all checked 2026-08-29)

| Source | Tier | Check date | What it supports |
|---|---|---|---|
| moby/moby#50750 (maintainer mechanism; code persists in v28.5.2 `libnetwork/osl/namespace_linux.go`) | 3 | 2026-08-29 | Marker = daemon task-create → netns-discover → bind-mount lifecycle; multiple trigger contexts; our live-pid marker is consistent with transient class, not proof |
| containerd/containerd#12141 (criu CI + gvisor triggers) | 3 | 2026-08-29 | Same marker in unrelated projects; supports hosted-variance classification, requires per-run proof |
| moby/moby#46490 (2023 `lstat /proc/<pid>/ns/net` under concurrent compose) | 3 | 2026-08-29 | Concurrent-start amplification is a recognized daemon-side class, not UMD topology |
| moby/moby#50326 + PR #50327 (daemon-restart netns ordering) | 3 | 2026-08-29 | Daemon-level fixes exist; confirms daemon owns the race surface |
| actions/runner ADR 0277 (`bash -eo pipefail` documented default) vs actions/runner-images#4459 (contested default) | 3 | 2026-08-29 | Item 1 must be explicit; do not rely on the contested default |
| axonops/audit#622 (tee masking postmortem) | 2 | 2026-08-29 | Item 1 failure class |
| oven-sh/bun 2ad4199 (per-shard single compose owner) | 2 | 2026-08-29 | Items 3 + B′ |
| SpecHive abc6dea (2026-04-27; `--wait` → healthchecks + `docker wait` with timeout) | 2 | 2026-08-29 | Items 5/10 engine-level gate pattern |
| docker/compose#10596, #11774, #11638, #13069, #12424 | 3 | 2026-08-29 | Item 10: `--wait` incompatible with one-shot exit-0; contested restart semantics |
| Docker CLI reference — `docker wait` (no timeout flag) | 3 | 2026-08-29 | Item 5: mandatory `timeout` wrapper |
| Docker seccomp docs (capability-gated allowlist) | 3 | 2026-08-29 | Item 9: PROVISIONAL bwrap-under-cap_drop proof; reject blanket unconfined |
| actions/runner#4117; actions-runner-controller#3828 | 3 | 2026-08-29 | Approach D: dind's own race family |
| langgenius/dify#7739 (marker on single-service compose up) | 3 | 2026-08-29 | Serialization narrows but cannot zero the window |

### Open risks / human questions (carried to T4+)

1. **R18 unknown:** the entire recommendation is conditional on the retrieved outcome of
   `33228898244`; re-open this section once the GitHub run is fetched (tier-1).
2. Whether serialized batches + explicit pipefail remove the hosted race is unproven until
   a green hosted run on the amended workflow.
3. The per-batch ordering contract adds review burden to every future compose change; the
   wrapper script itself must be reviewed like product code.
4. Hosted runner image / docker-compose version drift can change the exact-marker set —
   the tier-3 sources above are snapshots, not guarantees; re-validate the marker list
   when runner images change.
5. The P3-S3 seccomp profile's ability to boot bwrap under `cap_drop ALL`/no-new-privileges
   is PROVISIONAL until a hosted run passes the sandbox boot gate; a residual AppArmor/
   userns failure would be a security-posture design question (bounded options: named
   unconfined for sandbox-runner only, or documented honest gated OS-isolation) — never a
   netns retry, never a topology change.
6. If the exact marker recurs after serialization + pipefail on a clean runner, the
   escalation path (item 4a) is the only permitted response: preserve evidence, fail with
   `hosted-netns-escalation: TRUE`, route as a hosted-runner/daemon issue. Do not enlarge
   the budget; do not change topology speculatively.

## T4 Counter-Ideator — Surviving Concerns

**Turn 4 scope.** I read the full shared file (T1–T3), the approved DD anchor, Plan K
(current tree, including the `2d84d07`/`e6b5c3f` reconcile and P3-S3 seccomp amendment),
the current workflow (`validation.yml:248-548`), `deploy/compose.yaml`, the four
`.github/scripts`, and the support logs (debugger L4–L5, researcher L6–L8,
librarian L19–L20, exec-manager L96–L105). Every claim below cites a real source with
tier noted; technology claims were re-checked 2026-08-29. No code, workflow, DD, or
plan edits are made (L7). **Corpus update first:** T3's R18 subsection relies on
librarian L20 (02:27:57Z) asserting R18 is absent from the corpus; that assertion is
now **stale** — exec-manager L105 (02:29:29Z) and researcher L8 (02:30:38Z) both
record an R18 reading (see "R18 status update" below). This changes what T4 can rely
on and is the single most important new fact in this turn.

### A′/B′ 10-item contract — item-by-item disposition

1. **Exit-status preservation (PIPESTATUS/pipefail).** `RESOLVED in intent, NOT
   RESOLVED as written — shebang trap.`
   - **Original concern (T2 HIGH):** the current retry gate `if docker compose ... 2>&1
     | tee /tmp/compose-up.log; then` (`validation.yml:328-330`) has no `set -o
     pipefail`, so `tee`'s 0 masks compose's failure and the marker retry branch is
     dead code (axonops/audit#622 masking class).
   - **Empirical confirmation (NEW, R18):** researcher L8 (02:30:38Z) and exec-manager
     L105 (02:29:29Z) both record that in run `33228898244` the netns bind-mount race
     **appeared once and was swallowed by `| tee`** — "topology step lacks `set -o
     pipefail`; retry branch is dead code" — and the reconcile loop recovered it
     fail-closed. This settles the ADR-0277-vs-actions/runner-images#4459 contest for
     the hosted runner actually used: **pipefail was OFF** (if it were on, the `if`
     would have seen compose's failure and the retry branch would have fired). Item 1
     is now the empirically-justified top change, not just a precaution.
   - **Remaining risk (NOT RESOLVED):** `PIPESTATUS` and `set -o pipefail` are
     **bash-only**. The current scripts are `#!/usr/bin/env sh`
     (`wait-for-worker.sh`, `capture-diagnostics.sh`, `preflight-hatchet-images.sh`)
     and dash does not implement `pipefail`; `PIPESTATUS[0]` under dash is unbound or
     empty. T3 item 1 says "every compose-owning step and script begins with `set -euo
     pipefail`" but does not pin the interpreter. If the new `compose-start.sh` (B′)
     or any rewritten script keeps a `sh` shebang and is executed as `./script.sh`,
     pipefail silently no-ops and the exact-marker classification collapses — the same
     silent-failure class item 1 exists to kill. **The contract must require
     `#!/usr/bin/env bash` or explicit `bash script.sh` invocation for every
     pipefail/PIPESTATUS-bearing script**, and `rc=${PIPESTATUS[0]}` must be captured
     on the line immediately after the pipeline.

2. **Daemon/version capability preflight.** `RESOLVED (labeling), PARTIALLY RESOLVED
   (failure classification).`
   - **Original concern (T2 MEDIUM):** preflight must be a capability snapshot, never
     a readiness proof. T3 item 2 labels it correctly and makes preflight failure a
     named hard failure.
   - **Remaining risk:** item 2 does not distinguish **"daemon not reachable yet"**
     (cold-start runner flake class; the daemon is still booting) from **"capability
     assertion failed"** (wrong storage driver, missing containerd, denied image). A
     one-shot `docker version`/`docker info` timeout on a fresh hosted runner would
     hard-fail with no retry budget and no escalation path, introducing a new flake
     surface unrelated to the netns race. The preflight must separate a bounded
     daemon-reachability wait (with the same escalation route as item 4a) from
     capability assertion failures (hard fail with diagnostics). Also note preflight
     PASS gives **zero** coverage of the race window (the race lives in
     task-create→netns-discover→bind-mount, after any daemon ping) — T3's labeling
     already concedes this; the gate remains reconcile, not preflight.

3. **Serialized startup batches with JWT ordering.** `RESOLVED (ordering), PARTIALLY
   RESOLVED (topology/profile and intra-step env traps).`
   - **Original concern (T2 MEDIUM):** JWT mint must be a named dependency before the
     api/worker batch. T3 item 3 corrects the batch list (Batch 2 → JWT mint → Batch 3
     → Batch 4), matching the current two-phase shape (`validation.yml:248-307`).
   - **Explicit topology question (user-requested):** does `COMPOSE_PARALLEL_LIMIT` /
     staged serialization itself alter the required full topology? **No.** Per current
     official Docker docs (checked 2026-08-29):
     [COMPOSE_PARALLEL_LIMIT](https://docs.docker.com/compose/how-tos/environment-variables/envvars/)
     "specifies the maximum level of parallelism for concurrent engine calls" and is
     equivalent to `--parallel` (default 64; older docs "may not be set lower than 2";
     newer reference `--parallel=-1` = unlimited). It is a **concurrency knob within a
     single compose invocation** — it does not add/remove services, networks, ports, or
     profiles; it cannot change the compose model. Therefore neither
     `COMPOSE_PARALLEL_LIMIT` nor splitting `up` into four batches can alter the
     topology **as long as every batch uses the same compose file and the same
     `--profile sandbox` flag** where sandbox-runner is selected.
   - **Remaining risk 1 (topology via profile, not parallelism):** T3 item 3's Batch 4
     lists `api + worker + sandbox-runner` but does **not** state that the command must
     carry `--profile sandbox`. `sandbox-runner` is profile-gated
     (`compose.yaml:235 profiles: ["sandbox"]`); a batch written as `docker compose up
     -d api worker sandbox-runner` **without** the flag silently creates no
     sandbox-runner at all — the effective topology loses a required service while the
     batch "succeeds", and item 5's required-set reconcile either fails on
     sandbox-runner=absent (correct but confusing) or gets weakened to drop it
     (forbidden). The contract must pin `--profile sandbox` explicitly on the batch
     that starts sandbox-runner and on every full-set reconcile.
   - **Remaining risk 2 (JWT export scope):** the current mint runs in its own workflow
     step, so `>> $GITHUB_ENV` reaches the next step's containers. In A′, the wrapper
     owns batches AND the mint in **one** step; `GITHUB_ENV` is read by subsequent
     steps, not by containers created later in the same step. The wrapper must export
     the minted token in its **own** process environment (or write it to a file the
     batch reads) before Batch 4 — otherwise api/worker start without
     `UMD_HATCHET_TOKEN` and the registration gate fails for a mechanism reason.
   - **Remaining risk 3 (mint failure class):** item 3 does not assign a failure class
     to a failed tenant discovery / `hatchet-admin token create` (empty, non-`ey`, or
     error). It must be a named HARD failure with diagnostics, never retried as a netns
     marker, never blanket-retried.

4. **Exact-marker bounded retry with escalation.** `PARTIALLY RESOLVED — pattern and
   budget need pinning; zero hosted-run evidence for the retry branch itself.`
   - **Original concern (T2 HIGH):** budget needs a named escalation (item 4a — present)
     and the marker has multiple root causes (item 4 preamble — present).
   - **Remaining risk 1 (exact pattern):** item 4 says "the full daemon marker ... with
     variable pid/id" but does not pin the regex. The current grep `bind-mount /proc/`
     (`validation.yml:334`) is a prefix match that would also catch other
     `/proc` bind-mount errors; the amendment must name the exact anchored pattern
     (e.g. `bind-mount /proc/[0-9]+/ns/net -> /var/run/docker/netns/[0-9a-f]+: no such
     file or directory`) and **explicitly exclude the `lstat /proc/<pid>/ns/net` class**
     (moby/moby#46490, the 2023 concurrent-compose failure with a different message) —
     otherwise an operator can widen the grep and begin retrying the wrong class.
   - **Remaining risk 2 (retry branch has never run):** R18 proved the retry branch is
     currently dead code; until item 1 lands, the exact-marker retry logic has **zero
     production executions**. The only hosted-proven recovery mechanism is the reconcile
     loop. The contract is correct to keep item 7 (reconcile) as the gate and item 4 as
     a bounded optimization — but DDAuthor/Exec-Planner must treat the first green run
     as the first real test of the retry branch and keep diagnostics that make
     marker-vs-non-marker classifiable post-hoc (items 6/8).

5. **One-shot exit-code-0 semantics and engine-level gates.** `PARTIALLY RESOLVED —
   restart-policy interplay unnamed; timeout value unbounded.`
   - **Original concern (T2 MEDIUM):** `docker wait` has no timeout flag → explicit
     timeout wrapper (T3 item 5 present).
   - **Remaining risk 1:** `hatchet-migrate` and `hatchet-admin` use `restart:
     on-failure` (`compose.yaml:148,176`). A one-shot that exits non-zero is
     **restarted by Docker**, so `State.Status == exited` may never be true (it cycles
     exited→restarting→running→exited), and the current reconcile
     (`validation.yml:361-369` checks only `State.Status == exited`) would keep
     "waiting" forever. Item 5's `ExitCode == 0` requirement fixes this **only if** the
     contract states the rule explicitly: the **first** non-zero exit of a one-shot is a
     hard failure regardless of restart policy — do not wait for a "final" exited state
     that never comes. R17's `migrate/admin=absent` false-absence (ps -q without -a)
     is fixed (`ps -a` in `validation.yml:353,362`), but the restart-loop case is a
     different, unaddressed trap.
   - **Remaining risk 2:** item 5 says "explicit `timeout`" but names no bound. A
     wedged one-shot needs a named limit (e.g. 300s) and a named escalation (evidence →
     hard fail), mirroring item 4a.

6. **Visible recovery output.** `RESOLVED — mechanical, low residual risk.`
   - T3 item 6 removes the `>/tmp/compose-reconcile.log 2>&1 || true` suppression
     (`validation.yml:375-377`). No new concern beyond item 8's requirement that these
     labeled logs actually reach the artifact upload (see item 8).

7. **Post-up reconciliation as the fail-closed gate.** `RESOLVED in principle —
   PARTIALLY RESOLVED on final-set scope.`
   - **Original concern (T2 MEDIUM + R15):** `up` exits 0 with services in `Created`;
     reconcile is the deterministic gate. R18 (exec-manager L105/researcher L8) is the
     first hosted evidence that reconcile **recovers** a swallowed marker fail-closed —
     this is the strongest support for the whole A′ shape.
   - **Remaining risk:** item 7 says "after every batch ... reconcile the required state
     set" — ambiguous between per-batch and full-set. A per-batch reconcile can pass
     while an earlier batch's service has silently regressed (e.g. engine crashed after
     Batch 3 "passed", or a batch-2 one-shot is in a restart loop). The **final** gate
     must reconcile the **full** required set (db, api, worker, sandbox-runner,
     hatchet-engine, hatchet-dashboard running; migrate/admin exited 0) after the last
     batch, matching the DD's full split topology. Item 5's "EVERY required service"
     language should be restated as the final-set contract in item 7.

8. **Diagnostics contract.** `PARTIALLY RESOLVED — wrapper logs and escalation flag
   are not wired into capture/upload/gate.`
   - **Original concern (T2 explicit test):** capture before teardown, collection-only.
     The current `capture-diagnostics.sh` already runs under `if: always()` and is
     collection-only — good.
   - **Remaining risk 1:** item 8 requires "the compose-up and reconcile logs from item
     6", but the current script captures per-service logs only; it does **not** copy
     `/tmp/compose-up.log` / `/tmp/compose-reconcile.log`, and the artifact upload list
     (`validation.yml:526-539`) does not include them. The wrapper must write its
     labeled logs into the diagnostics dir / artifact glob, or a failed marker-retry
     cannot be post-hoc classified from evidence.
   - **Remaining risk 2:** item 4a's escalation verdict (`hosted-netns-escalation:
     TRUE`) is "recorded in the release summary" but the aggregate gate
     (`validation.yml:497-509`) only reads the three gate files. The aggregate gate
     must also fail on an unclassified escalation marker (absent = FAIL), or an
     escalated run could produce green gate files.

9. **Distinct sandbox security classification.** `RESOLVED (classification) — HIGH
   unresolved configuration question on sandbox-runner viability.`
   - **Original concern (T2 MEDIUM, PROVISIONAL):** the seccomp allowlist is
     capability-gated; P3-S3's moby-default+pivot_root is necessary, not sufficient,
     proof bwrap boots under cap_drop ALL. R18 (exec-manager L105) shows the sandbox
     booted after the seccomp fix — the PROVISIONAL claim moved one step closer, but a
     single green run is not proof of the general posture.
   - **Remaining risk (NOT RESOLVED — configuration, not seccomp):** `sandbox-runner`
     is profile-gated "optional" (`compose.yaml:235`) yet the workflow forces
     `--profile sandbox` AND requires it running (`validation.yml:328,347`); researcher
     L7 flagged this conflation and — critically — that `sandbox-runner`'s env block
     (`compose.yaml:236-241`) carries `UMD_ROLE: worker` + `UMD_SANDBOX_PROFILE` +
     `umd-api-env` but **not** `UMD_HATCHET_SERVER_URL`, `UMD_HATCHET_TOKEN`, or
     `HATCHET_CLIENT_HOST_PORT`, which the `worker` service gets
     (`compose.yaml:120-122`). Plan K P2-S3 makes cli.worker fail-closed (exit non-zero)
     on missing token/URL. If `sandbox-runner` runs the same `worker` command with that
     env, it exits non-zero and crash-loops under `restart: unless-stopped`
     (`compose.yaml:251`) regardless of seccomp correctness. Whether R18's reconcile
     actually counted sandbox-runner as running is not established in the corpus; this
     must be resolved (env parity with worker, or a distinct sandbox gate contract)
     before the next hosted run. **Severity: HIGH.**

10. **No `--wait` sole gate.** `RESOLVED — current sources re-checked 2026-08-29.`
    - Docker `compose up --wait` still exits 1 when a one-shot exits 0 — reproduced in
      docker/compose#10596 (open, with the same failure in the 2025-04 forum report),
      #11638, #13069, and the `--wait-allow-exit` PR #11649 still not merged into a
      release at check time. Engine-level `docker wait` (bounded) + inspect remains the
      correct gate. No new concern.

### B′, C, D disposition

- **B′ (single-owner wrapper):** folded into A′ correctly. The wrapper is a new failure
  surface; T3 already requires its log to flow through diagnostics and forbids a second
  compose owner. Add the shebang/bash requirement (item 1) to the wrapper spec and the
  item-6/8 log routing.
- **C (topology fallback):** correctly remains fallback-only behind a new DD. R18 adds
  supporting evidence: the topology booted and the worker registered 9 workflows under
  the **current non-serialized** workflow, so the "topology must change" premise has no
  hosted support. The port-race evidence (ma.ttias.be) still does not transfer to the
  netns bind-mount class (T2 MEDIUM evidence hygiene) — unchanged.
- **D (DinD/socket/privileged):** dead — agreement with T3; evidence strengthened by
  actions/runner#4117 and actions-runner-controller#3828/#3794 (dind's own race family).
  No new concern.

### R18 status update (corrects T3's "not in corpus")

T3 lines 697-710 state R18 is "not present in the log corpus" citing librarian L20
(02:27:57Z). **That grep predates two later corpus entries:**
- exec-manager L105 (02:29:29Z): R18 (`33228898244`) — full split topology boots,
  `/v1/ready` PASS, worker registration gate PASS, external HTTP flows PASS; live
  Hatchet suite first execution: 6 pass / 4 FAIL (4 source_pkey UniqueViolation + 1
  ModuleNotFoundError `hatchet_sdk`). Root causes in-repo verified (test seed collision
  + host env missing the `[worker]` extra) — toolchain/test-isolation, **not** netns.
- researcher L8 (02:30:38Z): identical reading, plus the key fact that the netns
  bind-mount race **appeared once in R18 and was swallowed by `| tee`** (retry branch
  dead code; reconcile recovered it fail-closed).

**What this means:** (1) T3's "UNKNOWN" posture is now only "not independently
re-retrieved from GitHub by this design artifact" — the outcome is partially
corroborated in-corpus and it **strengthens** the workflow-only verdict: topology boots,
registration green, and the live-suite blockers are toolchain/test-isolation, not
topology. (2) R18 **empirically confirms T2's HIGH pipefail finding** and is the first
hosted evidence that reconcile-as-gate works. (3) The `rnd-architect` assertion T3
refused to rely on is now corroborated by two independent corpus entries — it can be
upgraded from "do not invent" to "corroborated at coordination/analysis tier; re-retrieve
the GitHub run before finalizing the ledger."

### What Still Needs Human Judgment

1. **R18 ledger row:** DDAuthor/Exec-Planner must re-retrieve `33228898244` from GitHub
   and update the shared ledger (tier-1) before the amendment is finalized — the
   "not established" row is stale as of 02:30Z.
2. **Sandbox-runner's role and env:** is it a mandatory release gate (then it needs
   full Hatchet env parity with `worker` and a distinct boot contract) or a named
   profile-gated capability (then it must be reported `configured-unavailable`/`gated`,
   never silently dropped from the required set)? This is a security-posture/product
   call, not a netns call — but it will block the next hosted run if left as-is.
3. **Reconcile re-up trigger:** created-without-marker after a re-up — hard failure
   (T3 4b, fail-closed) vs bounded settle-then-reclassify (avoids spurious hard fails
   from normal start latency). T3 chose fail-closed; the settle-window parameter needs a
   human-approved bound so legitimate start latency does not become a false escalation.
4. **Preflight daemon-reachability budget:** how long may the wrapper wait for a
   cold-starting daemon before escalation, distinct from capability-assertion failures?
5. **Whether to also set `COMPOSE_PARALLEL_LIMIT=1` inside each batch:** orthogonal to
   staging (documented concurrency knob, not topology); it would further narrow the
   intra-batch race window at the cost of wall-time. Decide explicitly; it cannot be
   inferred from the current contract.

### Evidence needed before a green amendment

1. One hosted run of the amended 4-batch workflow with item 1's bash/pipefail contract,
   the pinned exact-marker regex, final full-set reconcile, and sandbox env resolved —
   this is the first real execution of the retry branch (it has never run in
   production).
2. A negative-test matrix for the marker regex (lstat class, other `/proc` bind-mounts,
   "not running", EPERM, one-shot non-zero) committed as a shell unit test.
3. `compose config` assertion that every batch resolves the **full** service set
   including `sandbox-runner` (profile pinning) and that `sandbox-runner` env is
   token-complete if it is a gate.
4. Artifact listing proving `compose-up.log`/`compose-reconcile.log` and the escalation
   verdict survive to the uploaded diagnostics.
5. Re-retrieved R18 artifacts (tier-1) to close the ledger row.

**L9/conservation verification:** A′+B′ as amended above preserves every immutable
requirement — full split Hatchet topology (with the profile-pinning caveat), real
callbacks, mandatory hosted validation, no skips/stubs/fake readiness (preflight
explicitly non-readiness; C6 line still candidate until live proof), no second
scheduler, no Lite, no DinD, no socket mounts, no privileged/unconfined broad bypass,
no blanket retry (F), no weakening of `2d84d07` reconcile, no `--wait` sole gate.
None of the concerns above permit a topology bypass, a skipped gate, or a fake
readiness line as release evidence.

## T5 Improver — Implementation Patterns

**Turn 5 scope.** I read the full shared file (T1–T4), the approved DD anchor
(`DD-universal-media-decomposer-ci-repair.md`), Plan K (current tree, `2d84d07`/`e6b5c3f`
reconcile and P3-S3 seccomp amendment), Task.md §40 (items 1–35), the support logs
(debugger L4–L5, researcher L6–L8, librarian L19–L20, exec-manager L96–L105), and the
architect report (`universal-media-decomposer-plan-k-netns-architecture-options.md`).
This turn proposes **implementation patterns** for the amended workflow contract that
survived T1–T4 — concrete shapes for the ten contract items (job/step decomposition,
daemon preflight snapshot, serialized batches, exact-marker retry + PIPESTATUS, one-shot
state model, JWT dependency order, post-up reconciliation, diagnostics artifact schema,
independent sandbox classification, hosted gate + escalation) — mapped to Plan K phases
and preserved requirements. **No code, workflow, DD, or plan edits are made (L7); these
are patterns for DDAuthor/Exec-Planner to encode, not edits.** Every technology claim
was re-validated against current official/maintainer sources on **2026-08-29** (citations
table below); claims that cannot be validated are labeled PROVISIONAL. R18 status follows
T4's correction (corroborated at coordination tier; tier-1 GitHub re-retrieval pending).

### Pattern 1 — Job/step decomposition (single-owner wrapper inside a step sequence)

**Shape.** The docker-e2e job (`validation.yml:203+`) currently runs the entire startup
state machine inline in one step (`validation.yml:313-382`). The amendment extracts the
state machine into ONE bash script — `.github/scripts/compose-start.sh` — owned by
exactly one workflow step ("Start split topology (serialized batches, fail-closed)"),
per B′ folded into A′ (T3 lines 653-672). The wrapper is the **sole compose owner**:
concurrent or competing compose invocations become structurally impossible. Everything
else stays as separate steps so no step can mask another:

1. *Set Compose runtime env* (`validation.yml:225-232`, exists; unchanged).
2. *Preflight* — daemon/version/network snapshot + exact-image tripwire (Pattern 2).
3. *compose-start.sh* — Batch 1→4 + JWT mint + exact-marker retry + per-batch and
   final full-set reconcile (Patterns 3–7).
4. *Readiness gates* — `wait-for-http.sh` (/v1/ready), `wait-for-worker.sh` (C6 line),
   unchanged in meaning (candidate signal only; live proof remains the suite).
5. *Live suite + boundary E2E + restart persistence* (P4-S7, unchanged).
6. *capture-diagnostics.sh* — `if: always()` before teardown (Pattern 8).
7. *Aggregate gate* — reads gate files + escalation verdict (Pattern 10).

**Why this shape.** (a) A single owner removes the concurrency that amplifies the race
window (oven-sh/bun 2ad4199 coordinator precedent; T1/T3 evidence). (b) Keeping preflight
and diagnostics in separate steps means a wrapper crash still yields a diagnostics step
that runs under `if: always()` and fails the run with evidence — the wrapper's own death
never falls back to a second compose owner (T2 LOW, T3 B′ item 4). (c) The wrapper is a
reviewable, unit-testable surface: its state classifier (Pattern 5) and marker matcher
(Pattern 4) can be shell-unit-tested offline, which the inline YAML block cannot (T4
evidence-need 2). **Interpreter contract (T4 item 1, HIGH):** the wrapper and every
pipefail/PIPESTATUS-bearing script MUST be `#!/usr/bin/env bash` (or invoked explicitly
as `bash script.sh`). The current `sh` shebangs (`wait-for-worker.sh`,
`capture-diagnostics.sh`, `preflight-hatchet-images.sh`) run dash on Ubuntu hosts, and
dash has neither `pipefail` nor `PIPESTATUS` — a silent no-op that recreates the exact
masking class item 1 exists to kill. The GitHub-hosted default shell is contested
(actions/runner ADR 0277 `-eo pipefail` vs actions/runner-images#4459); the pattern must
not depend on it.

**Testing approach.** (1) Shell unit tests for the classifier and regex against fixture
log/inspect text (T4 evidence-need 2: negative-test matrix for the marker regex — the
`lstat` class, other `/proc` bind-mounts, "not running", EPERM, one-shot non-zero).
(2) `compose config --profile sandbox --services` assertion that every batch resolves the
FULL required service set including sandbox-runner (T4 evidence-need 3). (3) The first
green hosted run is the first real execution of the retry branch — it has never run in
production (R18: swallowed by `tee`; T4 item 4 risk 2) — so the run must preserve all
evidence (Pattern 8) for post-hoc marker-vs-non-marker classification.

### Pattern 2 — Daemon preflight snapshot (two failure phases, capability not readiness)

**Shape.** Extend the existing preflight (`preflight-hatchet-images.sh`, wired at
`validation.yml:238`) with a daemon/version/network snapshot written to a labeled file
(`docker-capability.txt`): `docker version` (client + server), `docker info` (storage
driver, containerd/runc versions, cgroup version), `docker compose version`, `docker
network ls`, runner kernel/security facts available without privileged inspection, and
the existing exact-image manifest/digest tripwire (P3-S4). Snapshot on every run, before
any container creation.

**Two failure phases (T4 item 2, PARTIALLY RESOLVED → pattern closes it).**
- *Daemon-reachability wait:* a bounded poll for `docker version --format
  '{{.Server.Version}}'` (e.g., up to 120s in 5s steps) — a fresh hosted runner's daemon
  can still be booting. Exhaustion routes through the SAME escalation path as the marker
  budget (Pattern 10): preserve evidence, `hosted-netns-escalation: TRUE`, never a bare
  hard fail with no route. Recommended bound is a human-approved parameter (T4 question 4).
- *Capability assertion failure:* wrong storage driver, missing containerd, denied image,
  unusable network — immediate named HARD failure with diagnostics, no retry.

**Labeling.** Explicitly a **capability snapshot, never a readiness proof** (T2 MEDIUM).
Preflight PASS gives zero coverage of the race window — the race lives in
task-create→netns-discover→bind-mount, after any daemon ping (moby/moby#50750). The gate
remains reconcile (Pattern 7), never preflight. A preflight failure is a named hard
failure, and its PASS must never be displayed as "stack ready" (a fake-readiness variant,
forbidden by L9).

**Evidence.** Docker daemon troubleshooting guidance (disappearing/broken networks as an
infrastructure concern); Docker Compose envvars reference for `docker compose version`
reporting; hosted-runner variance context (actions/runner-images#7862, #6526).

### Pattern 3 — Serialized Compose batches preserving full split topology

**Shape.** The wrapper runs four dependency-ordered `docker compose -f deploy/compose.yaml
--profile sandbox up -d <services>` invocations — never one simultaneous ~10-service
`up` — with dependency waits between batches:

- **Batch 1 — `db`:** wait for Postgres (inspect `State.Health` or `pg_isready`).
- **Batch 2 — `hatchet-migrate` + `hatchet-admin`:** one-shots must reach `exited` with
  `State.ExitCode == 0` and the shared `/hatchet/config` volume populated; then the JWT
  mint (Pattern 6) BEFORE Batch 3/4 create any consumer container.
- **Batch 3 — `hatchet-engine` + `hatchet-dashboard`:** engine gRPC 7070 route and
  dashboard health verified.
- **Batch 4 — `api` + `worker` + `sandbox-runner`:** api `/v1/ready`, worker real C6
  registration, sandbox no restart loop and no security EPERM.

**Topology preservation (T4 item 3 risk 1, explicit).** Every batch uses the SAME compose
file, the SAME project, and — critically — the `--profile sandbox` flag on the batch that
creates `sandbox-runner` AND on every full-set reconcile. `sandbox-runner` is
profile-gated (`compose.yaml:235 profiles: ["sandbox"]`); a batch written without the
flag silently creates no sandbox-runner while "succeeding". The contract pins
`--profile sandbox` so the effective topology always equals the DD's full split set
(db, api, worker, sandbox-runner, hatchet-migrate/admin/engine/dashboard).

**Intra-batch parallelism decision (T4 question 5 — the pattern decides, human
confirms).** Set `COMPOSE_PARALLEL_LIMIT=1` in the wrapper's environment. Verified
against current Docker docs (2026-08-29): `COMPOSE_PARALLEL_LIMIT` "specifies the
maximum level of parallelism for concurrent engine calls" and is equivalent to
`--parallel`; it is a concurrency knob within a single compose invocation and cannot
change the compose model (services/networks/ports/profiles) — so it cannot alter
topology. It further narrows the intra-batch race window at the cost of wall-time.
Caveats to encode: (a) the env var takes precedence over the `--parallel` flag in current
compose (docker/compose#10547, fixed by PR #10566 so flags win in newer releases) — set
it via env, not flag, and verify with the `docker compose version` snapshot; (b) older
compose docs record a floor of 2 ("may not be set lower than 2") while the current
reference defaults to `-1` (unlimited) — if the installed compose rejects 1, use 2 and
record it in `docker-capability.txt`. PROVISIONAL: exact floor behavior is
version-dependent and must be confirmed against the pinned runner image at preflight.

**Evidence.** Docker Compose envvars reference; docker/compose#10547/#10566; oven-sh/bun
2ad4199 (serialization + single owner, production CI); T4's topology analysis (a
concurrency knob cannot alter the compose model).

### Pattern 4 — Exact-marker retry and PIPESTATUS (status preservation as a hard contract)

**Shape.** Every compose pipeline in the wrapper is:
`docker compose ... 2>&1 | tee "$log"` followed **on the next line** by
`rc=${PIPESTATUS[0]}` and a branch on `rc` — never on the pipeline tail. Verified against
the GNU bash manual (2026-08-29): `PIPESTATUS` is an array of the exit statuses of the
components of the most-recently-executed foreground pipeline and is bash-only; it is
updated by the next command, so capture must be immediate. Under `set -o pipefail` the
pipeline itself returns the rightmost non-zero status, but the explicit `PIPESTATUS[0]`
capture is the robust form: R18 proved the hosted runner had pipefail OFF (the marker was
swallowed by `| tee`; exec-manager L105, researcher L8), so the contract must not depend
on the shell default. The current `if docker compose ... | tee /tmp/compose-up.log; then`
(`validation.yml:328-330`) is the anti-pattern replaced — the axonops/audit#622 postmortem
(CI green-but-broken for months) is the failure class.

**Marker set (exact, anchored — T4 item 4 risk 1).** Retry ONLY the full daemon marker
with the pinned anchored pattern, allowing variable pid/id:

```text
bind-mount /proc/[0-9]+/ns/net -> /var/run/docker/netns/[0-9a-f]+: no such file or directory
```

The current prefix grep `bind-mount /proc/` (`validation.yml:334`) is deliberately
replaced: it would catch other `/proc` bind-mount errors. Explicitly EXCLUDE the
`lstat /proc/<pid>/ns/net` class (moby/moby#46490, the 2023 concurrent-compose failure
with a different message) — an operator widening the grep to that class starts retrying
the wrong failure. Do not retry on: "not running", timeout, EPERM, OOM, invalid config,
missing image, nonzero one-shot exit, generic text.

**Budget.** 3 attempts per batch; `--no-build` after attempt 1; fixed backoff (5s);
attempts counted from the VISIBLE compose output under the status-capture contract. On
budget exhaustion → Pattern 10 escalation. Never silently enlarge the budget, never
convert to blanket retry (forbidden F). Marker honesty stands: the marker has multiple
trigger contexts (moby/moby#50750, containerd/containerd#12141 — checkpoint pid 0, CRIU
CI, ordinary task-create); our R10 marker used a live pid, consistent with the transient
class but not proof — the classification contract is the honest posture.

**Testing approach.** A committed negative-test matrix for the regex (T4 evidence-need 2):
lstat class, other `/proc` bind-mounts, "not running", EPERM, one-shot non-zero, generic
compose failure — each must classify as NOT-marker. The first green hosted run is the
first real execution of this branch (T4 item 4 risk 2); the run's diagnostics must make
marker-vs-non-marker classifiable post-hoc (Pattern 8).

**Evidence.** GNU bash manual (`PIPESTATUS`, `pipefail`); axonops/audit#622; R18 corpus
(exec-manager L105, researcher L8); moby/moby#50750/#46490; actions/runner ADR 0277 vs
actions/runner-images#4459.

### Pattern 5 — One-shot state model (per-service-class classifier, first-exit rule)

**Shape.** The wrapper contains a pure classifier — given
(service, `State.Status`, `State.ExitCode`, `State.Error`, `RestartCount`,
`State.OOMKilled`) → OK / failure-class — unit-testable offline and applied by every
reconcile (Pattern 7). Required states (docker inspect `State` fields, verified against
the Docker CLI reference 2026-08-29):

- **Long-lived** (`db`, `api`, `worker`, `sandbox-runner`, `hatchet-engine`,
  `hatchet-dashboard`): `State.Status == running`, `State.Error` empty, not restarting,
  `State.OOMKilled == false`, `RestartCount` within a named bound (0 at gate; a bounded
  settle window may tolerate a small early count, then it is a hard failure).
- **One-shots** (`hatchet-migrate`, `hatchet-admin`): `State.Status == exited` AND
  `State.ExitCode == 0`, AND the shared config volume populated.

**First-exit rule (T4 item 5 risk 1, HIGH if missed).** Both one-shots use `restart:
on-failure` (`compose.yaml:148,176`). A non-zero exit is therefore **restarted by
Docker**: `State.Status == exited` may never be observed (it cycles
exited→restarting→running→exited), and a reconcile that waits for a "final" exited state
waits forever. The pattern: the **first** non-zero `ExitCode` observed on a one-shot is a
HARD failure regardless of restart policy — record the exit, classify, fail closed. R17's
`ps -q` false-absence is already fixed (`ps -a` in `validation.yml:353,362`), but the
restart-loop case is the distinct, unaddressed trap this rule closes.

**Bounded engine-level wait (T4 item 5 risk 2).** `docker wait` has no timeout flag
(Docker CLI reference) — every engine-level wait is wrapped in an explicit `timeout`
(e.g., 300s) with a named escalation (evidence → hard fail), mirroring Pattern 10.
`docker wait <cid>` works on already-exited containers and returns the recorded exit code
(SpecHive abc6dea precedent for replacing `compose up --wait` with healthchecks +
`docker wait`), but a wedged one-shot must not hang the pipeline.

**Evidence.** Docker CLI reference (`docker wait` no timeout; `docker inspect` State
fields); compose `restart: on-failure` semantics (`compose.yaml:148,176`); SpecHive
abc6dea (2026-04-27).

### Pattern 6 — JWT dependency order (mint inside the wrapper, same-process export)

**Order.** Batch 1 (`db`) → Batch 2 (`hatchet-migrate` + `hatchet-admin`, exited(0) +
config volume) → **tenant discovery + token mint** → Batch 3 (`engine` + `dashboard`) →
Batch 4 (`api` + `worker` + `sandbox-runner`). The mint uses the amended P3-S3 discovery
contract exactly as written in Plan K: bounded 30x2s case-insensitive poll
(`SELECT table_schema, table_name FROM information_schema.tables WHERE lower(table_name)
= 'tenant' ORDER BY 1 LIMIT 1`), then the schema-qualified exact-case quoted query
(`SELECT id::text FROM "<schema>"."<table>" ORDER BY "createdAt" LIMIT 1`) — the R6
`SET search_path` variant is dead (SET command-tag pollution, invalid UUID length 39);
psql stderr visible; no hardcoded tenant UUID; fail closed.

**Same-process env-scope rule (T4 item 3 risk 2, the mechanism trap).** In the current
workflow the mint runs in its own step, so `>> "$GITHUB_ENV"` reaches the next step's
containers. In the single-owner wrapper the mint and Batch 4 are in ONE step: `GITHUB_ENV`
is read by subsequent STEPS, not by containers created later in the same step. The wrapper
must export the minted token into its OWN process environment (or write it to a file that
Batch 4's compose invocation sources) BEFORE Batch 4 — compose resolves api/worker env at
container create; without this, api/worker start with empty `UMD_HATCHET_TOKEN` and the
registration gate fails for a mechanism reason that is misattributable to the netns race
(T2 MEDIUM, carried).

**Mint failure class (T4 item 3 risk 3).** Empty / non-`ey` / error from discovery or
`hatchet-admin token create` = named HARD failure with diagnostics — never retried as a
netns marker, never blanket-retried. The SDK requires a real 3-part JWT (`ey` prefix;
researcher L4: token REQUIRED, tenant id derived from JWT).

**Evidence.** Plan K P3-S3 amended text (discovery facts: `public` / `"Tenant"` /
`"createdAt"`; R6 SET-tag pollution); researcher L4 (SDK token contract); the existing
two-phase shape `validation.yml:248-307` as the baseline being moved into the wrapper.

### Pattern 7 — Post-up reconciliation (per-batch + final full-set, classified re-up)

**Shape.** Reconcile after EVERY batch (the batch's services must reach Pattern 5
required states) AND a FINAL full-set reconcile after Batch 4 (T4 item 7 risk — a
per-batch pass can hide an earlier batch regressing, e.g. engine crashed after Batch 3
"passed"). The final gate reconciles the FULL required set: `db`, `api`, `worker`,
`sandbox-runner`, `hatchet-engine`, `hatchet-dashboard` running; `hatchet-migrate`,
`hatchet-admin` exited(0). Every reconcile uses `docker compose ps -a` (never `ps -q` —
R17 false-absence) + per-container `docker inspect` (Pattern 5 classifier). The aggregate
`compose up` exit code is NEVER the gate (R15: exited 0 with services in `Created`);
reconcile is the deterministic fail-closed gate, and the `2d84d07` reconciliation must
not be weakened (L3).

**Re-up classification (T3 4b, T2's most critical concern).** A reconcile re-up is a
bounded marker retry ONLY when the exact anchored marker (Pattern 4) is present in that
re-up's VISIBLE output; any other mismatch after a re-up is a HARD failure with
diagnostics. The current `validation.yml:375-377` `>/tmp/compose-reconcile.log 2>&1 ||
true` suppression is removed: every recovery compose invocation writes to a labeled log
that is (a) streamed to the step output, (b) retained as an artifact (Pattern 8), (c)
included in diagnostics — so a post-hoc marker-vs-non-marker classification is always
possible (T3 items 6/8 depend on this).

**Settle-window parameter (T4 question 3 — the pattern proposes, human approves).**
"Created without marker" after a re-up: T3 chose fail-closed (T3 4b). To keep legitimate
start latency from becoming a false escalation, the pattern adds a named bounded settle
window (e.g., poll the full set up to 60s in 5s steps before classifying a
created-without-marker as hard failure). The exact bound is a human-approved parameter;
the default recommendation is 60s/5s, recorded in the amendment.

**Evidence.** R15 (hosted: `up` exited 0, services Created) + R18 (hosted: reconcile
recovered a swallowed marker fail-closed — the strongest support for the A′ shape,
exec-manager L105/researcher L8); Docker inspect State fields; T3 item 7 contract.

### Pattern 8 — Diagnostics/evidence artifact schema (fixed layout, survives upload)

**Shape.** One evidence directory per run (e.g., `$RUNNER_TEMP/umd-evidence/`) with a
fixed schema, written by the wrapper and `capture-diagnostics.sh`, and uploaded as one
artifact glob (T4 item 8 risk 1 — the upload list `validation.yml:526-539` must include
the directory; today it does not carry `/tmp/compose-up.log` or
`/tmp/compose-reconcile.log`, so a failed marker-retry cannot be classified post-hoc):

```text
umd-evidence/
  docker-capability.txt              # Pattern 2 snapshot (version/info/compose/network)
  image-digests.txt                  # existing P3-S4 tripwire output
  compose-up-batch-{1..4}-{attempt}.log   # visible, streamed, retained (Pattern 4/6/7)
  compose-reconcile-{n}.log          # visible, never suppressed (Pattern 7)
  svc-inspect/{service}.json         # full inspect JSON at failure and at final gate
  compose-ps.txt  network-inspect.txt  docker-info.txt  docker-version.txt
  sandbox-security.txt               # seccomp/AppArmor/userns observations + EPERM strings
  escalation-verdict.txt             # hosted-netns-escalation: TRUE|FALSE (Pattern 10)
  live-worker-gate.txt  public-boundary-gate.txt  public-boundary-after-restart-gate.txt
  # existing: junit/coverage, db dump, OCFL listing/fixity, per-service logs, capability snapshots
```

**Contract.** `capture-diagnostics.sh` runs under `if: always()` BEFORE teardown and is
collection-only — its `|| true` guards never decide the gate outcome (DD P3-S5
non-masking contract survives). Named volumes are preserved through restart/duplicate/
retry/E2E (`stop`/`start`, never `down -v`); final `down -v` only after evidence upload
(DD P3-S5, T3 item 8). An escalated run (Pattern 10) must ship the complete evidence dir
so a marker-recurrence → escalation decision is data-driven.

**Evidence.** GitHub Actions artifact-upload pattern (existing `validation.yml:526-539`);
T4 item 8 disposition; the existing `capture-diagnostics.sh` collection-only contract.

### Pattern 9 — Independent sandbox classification (distinct failure class, env parity)

**Classification rule (T3 item 9).** `statx`, `fsmount`, `getcwd`, `vfork`, `clone`,
`unshare`, or related `EPERM` in sandbox logs = sandbox profile/AppArmor/userns failure:
FAIL the run closed, route to security/profile diagnosis (the P3-S3 moby-default +
`pivot_root` profile is the amended fix), and NEVER consume netns retry budget. R16/R17
are the hosted proof the classes are distinct (R16 `statx`/`fsmount`; R17
`getcwd`/`vfork` + `sandbox-runner=restarting`). PROVISIONAL (T2 MEDIUM): Docker's default
seccomp profile is an allowlist whose namespace syscalls (`unshare`, `setns`, `mount`,
`clone3`, `fsmount`, `mount_setattr`) are allowed only when gated by `CAP_SYS_ADMIN`
(Docker seccomp docs); "the P3-S3 profile proves bwrap boots under cap_drop
ALL/no-new-privileges" stays PROVISIONAL until a hosted run passes the sandbox boot gate.
Blanket privileged/unconfined remains rejected.

**Env parity (T4 item 9, HIGH — the pattern must resolve it before the next run).**
`sandbox-runner` is profile-gated "optional" (`compose.yaml:235`) yet the workflow forces
`--profile sandbox` AND requires it running (`validation.yml:328,347`); its env block
(`compose.yaml:236-241`) carries `UMD_ROLE: worker` + `UMD_SANDBOX_PROFILE` +
`umd-api-env` but NOT `UMD_HATCHET_SERVER_URL`, `UMD_HATCHET_TOKEN`, or
`HATCHET_CLIENT_HOST_PORT` — which `worker` gets (`compose.yaml:120-122`). Plan K P2-S3
makes `cli.worker` fail-closed on missing token/URL; if `sandbox-runner` runs the same
worker command, it exits non-zero and crash-loops under `restart: unless-stopped`
(`compose.yaml:251`) REGARDLESS of seccomp correctness. **Pattern:** because the workflow
already forces `--profile sandbox` and requires sandbox-runner running, keep it a
MANDATORY release gate and give it FULL Hatchet env parity with `worker` (the three
variables), verified by a `compose config` assertion that sandbox-runner env is
token-complete (T4 evidence-need 3). The alternative — declaring sandbox-runner a named
profile-gated capability reported `configured-unavailable`/`gated` and dropping it from
the required set — is a product/security call (T4 human question 2) that L9's
mandatory-sandbox wording does not obviously permit; it must not be chosen silently.

**Evidence.** Docker seccomp docs (capability-gated allowlist); `compose.yaml` env blocks
(:120-122 vs :236-241, :235, :251); Plan K P2-S3 `cli.worker` fail-closed contract;
R16/R17 hosted table; researcher L7.

### Pattern 10 — Hosted gate and escalation (fail-closed aggregate, bounded route)

**Aggregate gate (T4 item 8 risk 2).** The always-running aggregate gate
(`validation.yml:497-509`) currently reads the three gate files. It MUST additionally
read `escalation-verdict.txt`: `hosted-netns-escalation: TRUE` present = FAIL; marker
absent = FAIL (fail-closed). A run that escalated must not be able to produce green gate
files.

**Escalation path (T3 4a).** Budget exhausted on the SAME clean runner, OR the exact
marker recurs after serialized startup + corrected pipefail → preserve the full evidence
dir (Pattern 8), fail with `hosted-netns-escalation: TRUE` recorded in the release
summary, route as a hosted-runner/daemon issue. Never silently enlarge the budget; never
convert to blanket retry (forbidden F); never change topology speculatively (C is gated
behind a new DD; R18's green boot supports the workflow-only direction and does not close
the release gate — live-suite blockers were toolchain/test-isolation, not netns).

**First-green-run semantics.** The exact-marker retry branch has NEVER executed in
production (R18: swallowed by `tee`; recovered by reconcile). The amended run is its
first real test — the evidence schema (Pattern 8) and the escalation route are what make
that first execution data-driven instead of judgment-driven.

**Evidence.** R18 corpus (exec-manager L105, researcher L8); R15 (reconcile-as-gate);
T3 item 4a; the aggregate-gate shape `validation.yml:497-509`.

### Mapping to Plan K phases and preserved requirements

| Pattern | Plan K phase it amends | Preserved requirement (binding) |
|---|---|---|
| 1 job/step decomposition | P3-S3 workflow contract (startup block) | L9 no second scheduler; DD P3-S5 non-masking; Task.md §40-33 (no hidden skips) |
| 2 daemon preflight snapshot | P3-S4 exact-image preflight (extends `preflight-hatchet-images.sh`) | L9 no fake readiness (snapshot, not readiness); Task.md §40-3 (implemented service identified by pushed SHA/hosted reports) |
| 3 serialized batches + topology pinning | P3-S3 startup contract; `--profile sandbox` pinned | L9 full split Hatchet topology; DD C1 sole scheduler; Task.md §40-31 (native Docker/Compose + full topology) |
| 4 exact-marker retry + PIPESTATUS | P3-S3 startup contract (replaces `validation.yml:313-345`) | L9 no blanket retry (F); DD fail-closed gates; Task.md §40-33 |
| 5 one-shot state model | P3-S3 reconcile contract (`ps -a` + inspect) | R15 fail-closed; L9 no weakening of `2d84d07` reconcile; Task.md §40-31 |
| 6 JWT dependency order | P3-S3 two-phase config+JWT (moves mint into wrapper) | Plan K P3-S3 discovery contract; C7 secret interpolation; Task.md §40-3 |
| 7 post-up reconciliation | P3-S3 reconcile (final full-set; classified re-up) | L9 mandatory hosted validation; R15/R18 evidence; Task.md §40-21 (durable restart) |
| 8 diagnostics artifact schema | P3-S5 diagnostics + artifact upload (`validation.yml:526-539`) | DD P3-S5 `if: always()` collection-only; Task.md §40-4 (OCFL fixity), §40-33 |
| 9 independent sandbox classification | P3-S3 seccomp amendment + sandbox-runner env | L9 mandatory sandbox (never skipped/unconfined); Task.md §40-31; DD no privileged bypass |
| 10 hosted gate + escalation | P3-S5 aggregate gate + release summary | L9 no skip/stub/fake readiness; Task.md §40-35 (repair + rerun); escalation route for hosted-runner issues |

**L9 conservation (verified).** Every pattern preserves: full split Hatchet topology
(Pattern 3 topology pinning), real callbacks with engine-visible registration and
callback-owned rows (Patterns 6/7 — unchanged gates), mandatory hosted validation
(Patterns 1/10 — no opt-in), no skips/stubs/fake readiness (Patterns 2/5 — preflight
explicitly non-readiness; C6 line remains candidate until live proof), no second
scheduler (Pattern 1 — sole compose owner, Hatchet sole scheduler), and the forbidden set
(Lite, DinD, socket mounts, privileged/unconfined, `--wait` sole gate, blanket retry) is
never re-introduced by any pattern.

### R18 status for these patterns

T3's "not in corpus" posture is **stale** (T4 correction, lines 988-1009): exec-manager
L105 (02:29:29Z) and researcher L8 (02:30:38Z) both record an R18 reading — full split
topology boots, `/v1/ready` PASS, worker registration PASS, external HTTP flows PASS,
live Hatchet suite 6 pass / 4 FAIL (4 `source_pkey` UniqueViolation + 1
`ModuleNotFoundError hatchet_sdk`; toolchain/test-isolation, NOT netns), and the key
fact that the netns marker appeared once and was **swallowed by `| tee`** (pipefail off;
retry branch dead; reconcile recovered it fail-closed). The `rnd-architect` assertion is
now corroborated at the coordination/analysis tier. **The patterns above are written to
be valid under either residual reading:** if the GitHub run is re-retrieved (tier-1) and
shows a green boot, it supports A′'s direction; if it shows budget exhaustion, it argues
for Pattern 10 escalation — never more retries, never a topology change. The shared
ledger's "not established" R18 row must be updated from tier-1 retrieval before the
amendment is finalized (T4 human question 1).

### Technology citations (re-checked 2026-08-29)

| Source | Tier | Check date | Supports |
|---|---|---|---|
| Docker Compose envvars reference (`COMPOSE_PARALLEL_LIMIT` = max parallelism for concurrent engine calls; equivalent to `--parallel`) | 3 | 2026-08-29 | Pattern 3 intra-batch parallelism decision |
| docker/compose#10547 (+ fix PR #10566) | 3 | 2026-08-29 | Pattern 3: env var precedence over `--parallel` is version-dependent — set via env, verify at preflight |
| Docker CLI reference — `docker container wait` (blocks indefinitely; no timeout flag) | 3 | 2026-08-29 | Pattern 5: mandatory `timeout` wrapper (300s) |
| Docker CLI reference — `docker container inspect` (`State.Status/ExitCode/Error`, `OOMKilled`, `RestartCount`) | 3 | 2026-08-29 | Patterns 5/7: classifier fields |
| GNU bash manual (`PIPESTATUS` array, bash-only; `pipefail`; captured by next command) | 3 | 2026-08-29 | Pattern 4: `rc=${PIPESTATUS[0]}` immediately after pipeline; `#!/usr/bin/env bash` |
| axonops/audit#622 (tee masking postmortem) | 2 | 2026-08-29 | Patterns 1/4: status-masking failure class |
| moby/moby#50750; containerd/containerd#12141; moby/moby#46490 (`lstat` class) | 3 | 2026-08-29 | Patterns 4/7: marker mechanism; exact regex excludes `lstat` class |
| oven-sh/bun 2ad4199 (single compose owner, serialization) | 2 | 2026-08-29 | Patterns 1/3 |
| SpecHive abc6dea (2026-04-27; `--wait` → healthchecks + `docker wait` with timeout) | 2 | 2026-08-29 | Patterns 5/7: engine-level gate pattern |
| docker/compose#10596, #11774, #11638, #13069, #12424 | 3 | 2026-08-29 | No `--wait` sole gate (carried, unchanged) |
| Docker seccomp docs (capability-gated allowlist; `unconfined` not recommended) | 3 | 2026-08-29 | Pattern 9: PROVISIONAL bwrap-under-cap_drop proof; reject blanket unconfined |
| actions/runner ADR 0277 vs actions/runner-images#4459 (hosted bash default contested) | 3 | 2026-08-29 | Pattern 1: do not rely on shell default |
| R18 corpus: exec-manager L105, researcher L8 | 1 (coordination tier; GitHub re-retrieval pending) | 2026-08-29 | R18 status; pipefail OFF empirically; reconcile recovers fail-closed |

### Open risks / human questions (carried to T6+)

1. **R18 tier-1 retrieval:** re-fetch `33228898244` from GitHub and update the shared
   ledger row before the amendment is finalized (T4 question 1).
2. **Sandbox-runner role/env parity (HIGH, blocks next hosted run):** mandatory gate with
   full Hatchet env parity (Pattern 9) vs named `configured-unavailable` capability —
   product/security call, not a netns call (T4 question 2).
3. **Reconcile re-up settle window:** proposed 60s/5s poll before created-without-marker
   is classified a hard failure (Pattern 7); exact bound is human-approved (T4 question 3).
4. **Preflight daemon-reachability budget:** proposed 120s/5s (Pattern 2); exact bound is
   human-approved (T4 question 4).
5. **`COMPOSE_PARALLEL_LIMIT=1` wall-time tradeoff:** pattern recommends =1 with a 2
   floor-fallback; explicit decision required (T4 question 5).
6. **Retry branch first production execution:** the amended run is the first real test of
   Pattern 4's branch — treat its evidence as the validation, not the design.
7. **P3-S3 seccomp sufficiency remains PROVISIONAL** until a hosted run passes the
   sandbox boot gate; a residual AppArmor/userns failure is a security-posture design
   question (named unconfined for sandbox-runner only, or documented gated
   OS-isolation) — never a netns retry, never a topology change.

## T5 Improver — Implementation Patterns

**Turn 5 scope.** I read the full shared file (T1–T4), the approved DD anchor, Plan K
(current tree, including the `e6b5c3f` seccomp + `ps -a` fixes and the P3-S3 amendment),
the current workflow (`validation.yml:47-548`), `deploy/compose.yaml`, the six
`.github/scripts` (all `#!/usr/bin/env sh`), and the support logs (exec-manager L94–L105,
researcher L6–L8, librarian L19–L20). T4 is the input: every T4 finding below is
addressed by a concrete implementation pattern for the A′+B′ workflow amendment (T3's
10-item contract). No code, workflow, DD, or plan edits are made (L7). Technology claims
were validated 2026-08-29 against current official/maintainer sources; anything
unvalidated is labeled PROVISIONAL.

### R18 corroborated status — what T5 builds on (tier-1 corpus update)

T4's corpus update is accepted and extended by the raw log entries:

- **exec-manager L105 (02:29:29Z):** R18 (`33228898244`) MILESTONE — full split topology
  boots (seccomp + `ps -a` fixes landed), `/v1/ready` PASS, worker registration gate
  PASS, external HTTP flows PASS. Live Hatchet suite executed for the first time:
  **6 pass / 4 FAIL** (5 listed incl. engine_visible_registration — 4× `source_pkey`
  UniqueViolation + 1× ModuleNotFoundError `hatchet_sdk`). Root causes verified in-repo:
  (1) `_ensure_source` plain INSERT with a fixed `_SOURCE_ID` collides across the
  session-scoped shared `live_db`; (2) host pytest env installs only `.[dev]`,
  `hatchet_sdk` lives in the `[worker]` extra. Toolchain/test-isolation — **not** netns.
- **researcher L8 (02:30:38Z):** identical reading, plus the decisive fact — the netns
  bind-mount race **appeared once in R18 and was swallowed by `| tee`** (topology step
  lacks `set -o pipefail`; retry branch is dead code); the reconcile loop recovered it
  fail-closed. Also confirms the live-suite errors (1× SDK import + source_pkey
  collisions; the exact test-level split of 4 vs 5 listed entries is a tier-1 retrieval
  detail for Phase 6, not a design blocker).

**Consequences for the patterns:** (1) the ADR-0277-vs-runner-images#4459 pipefail
contest is **empirically settled for the hosted runner actually used: pipefail was OFF**
— if it had been on, the `if docker compose ... | tee ...` guard (`validation.yml:328-330`)
would have seen compose's failure and the retry branch would have fired. Patterns IP-1/
IP-2 make this version-independent instead of relying on the observed default. (2) R18
is the **first hosted execution of reconcile-as-gate** — the strongest hosted support for
the whole A′ shape; the exact-marker retry branch itself has **zero production
executions**, and the first green run of the amended workflow is its first real test
(T4 item 4 risk 2). (3) The ledger row "R18 NOT established" is stale; T4's upgraded
reading ("corroborated at coordination/analysis tier; re-retrieve the GitHub run before
finalizing the ledger") is the standing posture, and Phase 6 must re-retrieve
`33228898244` (tier-1).

### Implementation patterns (each maps to Plan K phases in the table below)

**Pattern IP-1 — Interpreter consistency: every compose-owning script is bash, invoked as
bash (T4 item 1 shebang trap).**
- `PIPESTATUS` and `set -o pipefail` are **bash-only**. All six current scripts are
  `#!/usr/bin/env sh`; on Ubuntu hosted runners `/bin/sh` is dash, which has **no
  pipefail** (`sh -o pipefail` → "Illegal option"; dash ignores it) and no `PIPESTATUS`
  array (github/docs#23853 empirical dash test; GNU Bash Reference Manual § 3.2.3).
- Concrete pattern: every script that captures `PIPESTATUS` or sets `pipefail` — the new
  `compose-start.sh` (B′ wrapper) and any rewritten script that grows a pipeline — gets
  `#!/usr/bin/env bash` **and** is invoked as `bash script.sh` in the workflow. The
  double pin matters: `bash script.sh` forces bash regardless of shebang, but direct
  `./script.sh` execution (and `sh script.sh`) honors the shebang and silently loses
  pipefail — the same silent-failure class item 1 exists to kill.
- Also set the docker-e2e job-level `defaults: run: shell: bash` so every inline `run:`
  block gets `bash --noprofile --norc -eo pipefail {0}` explicitly (ADR 0277) instead of
  the observed `bash -e {0}` default (actions/runner#353; github/docs#23853).

**Pattern IP-2 — Exit-status preservation: capture `rc=${PIPESTATUS[0]}` on the line
immediately after every compose pipeline (T3 item 1; T4 item 1).**
- Replace the `if docker compose ... 2>&1 | tee log; then` guard
  (`validation.yml:328-330` — the `if` makes the pipeline's *tail* status the branch
  condition, and tee returns 0 without pipefail, so the failure branch is unreachable)
  with:
  ```bash
  docker compose -f deploy/compose.yaml --profile sandbox up -d ... 2>&1 | tee "$COMPOSE_UP_LOG"
  rc=${PIPESTATUS[0]}
  ```
  then branch on `rc`. `PIPESTATUS` is volatile — it must be captured before any
  intervening command (GNU Bash Reference Manual § 5.2). `PIPESTATUS[0]` is the invariant
  form that reports compose's true exit code whether or not pipefail is on; use it
  everywhere, never `$?` of a pipeline tail.
- Every retry, reconcile re-up, and one-shot gate uses the same idiom; no compose-owning
  step may evaluate a pipeline's exit status through a tail command.

**Pattern IP-3 — Preflight = two classes: bounded daemon-reachability wait vs capability
assertion, never readiness (T3 item 2; T4 item 2).**
- **Class A — daemon reachability:** `docker version` (client+server) with a bounded poll
  (e.g., the project's own established `seq 1 30` / `sleep 2` idiom from tenant
  discovery, `validation.yml:278-291`). Only "daemon not reachable yet" is
  bounded-retried; budget exhaustion routes through the same escalation channel as IP-4.
  A cold-starting hosted runner must not become a new flake surface.
- **Class B — capability assertion:** wrong storage driver, missing containerd/runc,
  denied/nonexistent image (the existing `preflight-hatchet-images.sh` tripwire, P3-S4),
  `compose config` failure → immediate hard failure with diagnostics, no retry.
- Preflight PASS is recorded as a **capability snapshot** (version/info facts, image
  digests) and never as a readiness signal — the race window lives in
  task-create→netns-discover→bind-mount, after any daemon ping (moby/moby#50750), so the
  gate remains IP-8's reconcile. This preserves the "no fake readiness" invariant (L9).

**Pattern IP-4 — Exact marker class + bounded escalation (T3 item 4/4a/4b; T4 item 4).**
- **Anchored regex, not prefix:** the retry predicate is the full daemon marker
  `bind-mount /proc/[0-9]+/ns/net -> /var/run/docker/netns/[0-9a-f]+: no such file or
  directory` (variable pid/id only). The current `grep -q "bind-mount /proc/"`
  (`validation.yml:334`) is a prefix match that would retry other `/proc` bind-mount
  failures, and the `lstat /proc/<pid>/ns/net` class (moby/moby#46490 — different message
  and mechanism) is **explicitly excluded**. Grep against the labeled compose log
  captured under IP-2; classify per attempt from visible evidence.
- **Budget and escalation:** 3 attempts per batch; `--no-build` after attempt 1; fixed 5s
  backoff. Budget exhausted on the same clean runner → preserve full evidence, write
  `hosted-netns-escalation: TRUE` to a dedicated verdict file (see IP-9), fail the run,
  route as hosted-runner/daemon issue; never enlarge the budget, never convert to blanket
  retry (forbidden F).
- **Negative-test matrix (committed shell unit test, T4 evidence-needed #2):** lstat
  class, other `/proc` bind-mounts, "not running", EPERM, one-shot non-zero, denied image
  → must NOT retry; the exact marker with variable pid/id → retry. This guards against an
  operator widening the grep and retrying the wrong class.

**Pattern IP-5 — COMPOSE_PARALLEL_LIMIT / staged batches without topology reduction
(T3 item 3; T4 item 3).**
- `COMPOSE_PARALLEL_LIMIT` "specifies the maximum level of parallelism for concurrent
  engine calls" and is equivalent to `--parallel` — a concurrency knob **within a single
  compose invocation**. It does not add/remove services, networks, ports, or profiles; it
  cannot change the compose model (Docker docs envvars; docker compose CLI reference;
  checked 2026-08-29). Neither `COMPOSE_PARALLEL_LIMIT` nor splitting `up` into four
  batches alters topology **as long as every batch uses the same `-f deploy/compose.yaml`
  and the same `--profile sandbox` on the batch that starts sandbox-runner and on every
  full-set reconcile** (`compose.yaml:235` gates sandbox-runner behind
  `profiles: ["sandbox"]`; a batch without the flag silently creates no sandbox-runner
  while "succeeding").
- Pin the knob explicitly: the wrapper sets `COMPOSE_PARALLEL_LIMIT=${COMPOSE_PARALLEL_LIMIT:-1}`
  (or passes `--parallel`); do not rely on the default (64). The flag-vs-env precedence
  has a historical bug (docker/compose#10547; fixed by PR #10566) — pinning one mechanism
  makes behavior deterministic. **Whether `=1` (intra-batch serialization) is worth the
  wall-time is T4 human question 5; the pattern provides the mechanism, the value is a
  human call** — default recommendation PROVISIONAL: `1` for the first hosted runs to
  minimize the intra-batch window, re-measured after a green run.
- **Topology tripwire (T4 evidence-needed #3):** after the batches, run `docker compose
  -f deploy/compose.yaml --profile sandbox config --services` and assert the resolved set
  equals the full required set (db api worker sandbox-runner hatchet-migrate
  hatchet-admin hatchet-engine hatchet-dashboard). Silent topology reduction (missing
  profile, dropped service, wrong file) becomes a hard failure with evidence.

**Pattern IP-6 — JWT ordering + env propagation to EVERY worker, including sandbox-runner
(T3 item 3; T4 items 3 risk 2-3 and 9 HIGH).**
- **Ordering:** Batch 1 db → Batch 2 migrate+admin (exited 0 + `/hatchet/config`
  populated) → tenant discovery (bounded 30×2s case-insensitive;
  `validation.yml:278-291` is the precedent) → JWT mint → **export before any Batch 3/4
  container creation**.
- **Wrapper-scope env propagation (T4 item 3 risk 2):** compose resolves
  api/worker/sandbox-runner env at container create. When the wrapper owns batches AND
  the mint in one step, `$GITHUB_ENV` is read by *subsequent steps*, not by containers
  created later in the same step. The wrapper must therefore export
  `UMD_HATCHET_TOKEN`/`HATCHET_TENANT_TOKEN` into its **own process environment** (and
  mirror to `$GITHUB_ENV` for later steps) before Batch 4 — or write the token to a file
  Batch 4's invocation reads via `--env-file`.
- **Mint failure class (T4 item 3 risk 3):** empty token, non-`ey` prefix, or
  `hatchet-admin token create` error → named HARD failure with diagnostics; never
  retried as netns, never blanket-retried.
- **sandbox-runner env parity (T4 item 9 — the HIGH open question):** sandbox-runner's
  env block (`compose.yaml:236-241`) carries `UMD_ROLE: worker` + `UMD_SANDBOX_PROFILE` +
  `umd-api-env` but **not** `UMD_HATCHET_SERVER_URL`, `UMD_HATCHET_TOKEN`, or
  `HATCHET_CLIENT_HOST_PORT`, which `worker` gets (`compose.yaml:120-122`). `cli.worker`
  fails closed (exit non-zero) on missing token/URL, so sandbox-runner running the worker
  command crash-loops under `restart: unless-stopped` (`compose.yaml:251`) regardless of
  seccomp. Both resolution branches are presented (the choice is T4 human question 2):
  - **Option a — sandbox-runner IS a mandatory release gate:** full Hatchet env parity
    with `worker` (the three vars above) plus a distinct boot contract (register and stay
    running; never counted via a readiness line alone).
  - **Option b — sandbox-runner is a named profile-gated capability:** exclude it from
    `required_running` and report it `configured-unavailable`/`gated` honestly (exact
    vocabulary per Plan K Phase 5); never silently drop it from the topology tripwire
    (IP-5) or from the required set.
  - Until the human decision lands, the reconcile required-set must match the chosen
    branch and the topology tripwire must keep sandbox-runner listed in the resolved set
    (profile-pinned), so absence is visible either way.

**Pattern IP-7 — One-shot exit semantics: first non-zero exit is the failure (T3 item 5;
T4 item 5).**
- `hatchet-migrate`/`hatchet-admin` use `restart: on-failure` (`compose.yaml:148,176`). A
  one-shot that exits non-zero is **restarted by Docker**, so `State.Status == exited`
  may never become true (it cycles exited→restarting→running→exited), and a reconcile
  that only checks `exited` (`validation.yml:361-369`) waits forever. Rule: the **first
  non-zero exit of a one-shot is a hard failure regardless of restart policy** — do not
  wait for a "final" exited state that never comes.
- Implementation: gate one-shots on `docker inspect --format '{{.State.ExitCode}}'` plus
  `{{.RestartCount}}`/`{{.Restarting}}`, not on `State.Status` alone; `ExitCode == 0` and
  no restart cycle is the only pass.
- **Bounded engine waits:** `docker wait` has no timeout flag (Docker CLI reference —
  "Block until one or more containers stop, then print their exit codes") — wrap it in
  `timeout 300` with a named escalation (capture evidence → hard fail), mirroring IP-4's
  escalation. A wedged one-shot must not hang the pipeline.

**Pattern IP-8 — Post-up reconciliation: full-set, classified, visible (T3 items 4b/6/7;
T4 item 7).**
- **Final-set gate:** after the last batch (and after every retry), reconcile the FULL
  required set — db, api, worker, hatchet-engine, hatchet-dashboard `running` with empty
  `State.Error`, not `restarting`, `State.OOMKilled == false`; migrate/admin `exited`
  with `ExitCode == 0` — via `docker compose ps -a` + per-container `docker inspect`
  (never `ps -q`; R17 false-absence fixed in `e6b5c3f`). Per-batch reconciles are a
  fast-fail aid; only the final full-set reconcile is the gate (an earlier batch's
  service can silently regress while later batches "pass").
- **Classified re-up:** a reconcile re-up is a bounded marker retry **only when the exact
  marker (IP-4 regex) is present in that re-up's visible output**; any other mismatch
  after a re-up is a hard failure with diagnostics — never re-run-forever (replaces the
  `validation.yml:375-377` `|| true` suppression). The settle-window parameter (how long
  to allow normal start latency before classifying) is T4 human question 3 — the
  pattern's fail-closed default stands until a human-approved bound is set.
- **Visible recovery output:** every retry/re-up writes a labeled log that is (a)
  streamed to step output, (b) added to the artifact upload (IP-9), (c) included in
  diagnostics — so a post-hoc marker-vs-non-marker classification is always possible.

**Pattern IP-9 — Diagnostics schema: labeled logs + escalation verdict reach
capture/upload/gate (T3 item 8; T4 item 8).**
- **Wire the wrapper logs in:** capture-diagnostics.sh currently captures per-service
  logs only; it does not copy `/tmp/compose-up.log` / `/tmp/compose-reconcile.log`, and
  the artifact upload list (`validation.yml:526-539`) does not include them. The wrapper
  must write its labeled logs into the diagnostics dir (or the artifact glob must add
  them), so a failed marker-retry is post-hoc classifiable from evidence (T4 item 8
  risk 1).
- **Machine-readable schema:** per-service records `{service, status, exit_code,
  restart_count, oom_killed, error, health}` derived from `docker inspect` JSON;
  daemon/version/network facts from IP-3's preflight plus `docker network inspect`;
  sandbox seccomp/AppArmor/userns observations; the JUnit/coverage/DB dump/OCFL listing
  already collected under P3-S5.
- **Escalation verdict reaches the gate (T4 item 8 risk 2):** the aggregate gate
  (`validation.yml:497-509`) reads only three gate files; a run with
  `hosted-netns-escalation: TRUE` but green gate files must FAIL. Add the escalation
  verdict file to the gate's read set — absent = FAIL. capture-diagnostics.sh stays
  collection-only (`|| true` guards never decide gate outcome — DD P3-S5 non-masking
  contract).

**Pattern IP-10 — Independent seccomp classification (T3 item 9; T4 item 9).**
- Any `statx`, `fsmount`, `getcwd`, `vfork`, `clone`, `unshare`, or related `EPERM` in
  sandbox logs is a sandbox profile/AppArmor/userns failure: **FAIL closed, route to
  security/profile diagnosis, NEVER consume netns retry budget**. R16 (`statx`/`fsmount`)
  and R17 (`getcwd`/`vfork` + `sandbox-runner=restarting`) are the hosted proof the
  classes are distinct; R18 (tier-1) shows the sandbox booted after the P3-S3
  moby-default + `pivot_root` fix (415 syscalls, `e6b5c3f`).
- **Honest PROVISIONAL label:** Docker's default seccomp profile is an allowlist whose
  namespace syscalls are allowed only when gated by `CAP_SYS_ADMIN` (Docker seccomp
  docs, checked 2026-08-29); "the P3-S3 profile proves bwrap boots under cap_drop
  ALL/no-new-privileges" is PROVISIONAL — R18 is one green run, not proof of the general
  posture; a residual AppArmor/userns failure is a security-posture design question
  (bounded options: named unconfined for sandbox-runner only, or documented honest gated
  OS-isolation), never a netns retry, never a topology change.

### Testing approach (T4 "Evidence needed before a green amendment")

1. **Shell unit tests for the marker classifier (IP-4):** the negative-test matrix
   committed as a test script run in a `test` job (no Docker daemon needed — pure grep on
   fixture strings). This is the first real test of logic that has never executed in
   production (T4 item 4 risk 2).
2. **`compose config` topology assertion (IP-5):** assert every batch resolves the FULL
   service set including sandbox-runner (profile-pinned) and that sandbox-runner env is
   token-complete if it is a gate (IP-6 option a).
3. **Artifact-listing assertion (IP-9):** assert compose-up.log / compose-reconcile.log
   and the escalation verdict survive to the uploaded diagnostics.
4. **First hosted green run** of the amended 4-batch workflow is the first real execution
   of the retry branch; the run must record per-attempt classification evidence
   (IP-2/IP-8) so the marker-vs-non-marker split is auditable.

### Mapping to Plan K phases and requirements

| Pattern | Plan K phases/steps | Requirement/ledger |
|---|---|---|
| IP-1 bash interpreter | P3-S3 (docker-e2e startup contract); Phase 6 review | T3 item 1; T4 item 1; L9 (no weakened gates) |
| IP-2 PIPESTATUS/pipefail | P3-S3; P3-S5 (gate reads real status) | T3 item 1; T4 item 1; L9; axonops failure class |
| IP-3 preflight two-class | P3-S4 (preflight extension); P3-S5 (facts) | T3 item 2; T4 item 2; L9 (no fake readiness) |
| IP-4 marker class + escalation | P3-S3 (retry contract); Phase 6 (negative matrix) | T3 item 4/4a/4b; T4 item 4; L9 (bounded, not blanket) |
| IP-5 COMPOSE_PARALLEL_LIMIT + profile pin | P3-S3 (batch contract); P2-S2/P2-S3 (topology evidence) | L5/L9 (no topology reduction); DD C1/C2 |
| IP-6 JWT ordering + env parity | P2-S4 (JWT mint); P3-S3 (Batch 4 env); Phase 5 (vocabulary) | T3 item 3; T4 item 9; L9 (real registration) |
| IP-7 one-shot exit semantics | P3-S3 (reconcile contract) | T3 item 5; T4 item 5; L9 |
| IP-8 full-set reconcile | P3-S3 (gate); commit `2d84d07` preserved | T3 items 4b/6/7; R15/R18; L3 (never weaken) |
| IP-9 diagnostics schema | P3-S5 (capture/upload/aggregate gate) | T3 item 8; T4 item 8; DD P3-S5 |
| IP-10 seccomp classification | P3-S3 (P3-S3 seccomp amendment preserved); Phase 6 (re-verify) | T3 item 9; R16/R17/R18; L9 (no unconfined) |

**L9 conservation:** every pattern is workflow-level; none touches topology (IP-5 pins
it), callbacks (IP-6 keeps real token/registration), hosted validation (IP-3/IP-8 keep
the gates), fake readiness (IP-3's labeling + IP-8's full-set reconcile), second
scheduler (no scheduler anywhere), or the `2d84d07`/`e6b5c3f` reconciles (IP-8 preserves
and strengthens). **L5 answer unchanged: workflow-design change, not
architecture/topology change.**

### Technology citations (all checked 2026-08-29)

| Source | Tier | Supports |
|---|---|---|
| GNU Bash Reference Manual § 3.2.3 (Pipelines) + § 5.2 (PIPESTATUS) | 3 | IP-1/IP-2: pipefail semantics; PIPESTATUS volatile — capture immediately |
| github/docs#23853 (default shell table + dash empirical test) | 3 | IP-1: unspecified = `bash -e {0}` (no pipefail); `shell: bash` = `-eo pipefail`; dash rejects `-o pipefail` |
| actions/runner ADR 0277 + ScriptHandler.cs (default `sh`) | 3 | IP-1: pin `defaults: run: shell: bash`; do not rely on the contested default |
| actions/runner#353 (observed `/bin/bash -e {0}`) | 3 | IP-1: empirical hosted default lacks pipefail |
| R18 / exec-manager L105 + researcher L8 (tier-1 corpus) | 1 | pipefail was OFF; marker swallowed by tee; reconcile recovered fail-closed; topology/readiness/registration green; live suite 6 pass / 4 FAIL (toolchain/test-isolation) |
| Docker docs envvars — COMPOSE_PARALLEL_LIMIT; compose CLI reference `--parallel` | 3 | IP-5: concurrency knob within one invocation; cannot change topology |
| docker/compose#10547 + PR #10566 | 3 | IP-5: pin one precedence mechanism (env-vs-flag historical bug) |
| Docker CLI reference `docker wait` / `docker inspect` | 3 | IP-7: no timeout flag; State fields (ExitCode/Restarting/OOMKilled/Error) |
| moby/moby#50750, containerd/containerd#12141, dify#7739, moby/moby#46490 | 3 | IP-4: exact marker class + excluded lstat class; multiple trigger contexts |
| Docker seccomp docs (capability-gated allowlist) | 3 | IP-10: PROVISIONAL bwrap-under-cap_drop proof |
| axonops/audit#622 (tee masking postmortem) | 2 | IP-2 failure class |
| oven-sh/bun 2ad4199 (serialized single-owner compose) | 2 | IP-5 / B′ single-owner precedent |
| SpecHive abc6dea (engine-level `docker wait` + timeout) | 2 | IP-8 engine-level gate precedent |

### Open risks / human questions carried to T6+

1. **R18 tier-1 re-retrieval** — the ledger row is corroborated at coordination tier, but
   the GitHub run (`33228898244`) must be re-fetched before the amendment is finalized
   (T4 human question 1).
2. **sandbox-runner role/env decision** — IP-6 option a vs b is a security-posture/product
   call (T4 human question 2); it blocks the next hosted run if unresolved.
3. **Reconcile settle-window bound** — IP-8's fail-closed default needs a human-approved
   settle parameter so normal start latency is not a false escalation (T4 human question 3).
4. **Daemon-reachability budget** — IP-3 Class A's bounded wait length and escalation
   route (T4 human question 4).
5. **COMPOSE_PARALLEL_LIMIT value** — mechanism provided (IP-5); `=1` vs default 64 is a
   wall-time tradeoff the first green runs should measure (T4 human question 5).
6. **Retry branch first execution** — the exact-marker retry has never run in production;
   the first green hosted run is its first real test, and diagnostics (IP-9) must make
   that execution auditable.

## T7 Improver — Final Patterns and Mitigations

**Turn 7 scope.** This is the Improver's final turn in the Plan K netns adversarial
flow. I read the full shared file (T1–T4 plus both duplicate T5 sections at lines
1056–1505 and 1506–1817), the approved DD anchor
(`DD-universal-media-decomposer-ci-repair.md`), Plan K
(`TASK-universal-media-decomposer-K-ci-repair-release-gate.md`), and the support
logs. Per L7 I make **no code, workflow, DD, or plan edits** — this section is the
single canonical workflow-amendment design that DDAuthor/Exec-Planner distills.
**Section-state transparency:** at write time the shared file contains **no
`## T6 Counter-Improver` section** — the counter-improver's T6 dispatch was blocked
pre-T5 and no T6 content exists in this corpus (its log records the blocker). The
eleven T6 risks resolved below are the risk list given verbatim in the Refiner's T7
dispatch instruction: duplicate T5/order; bash-only contract; daemon wait vs
capability preflight; profile/full topology; JWT/env parity; exact marker and
bounded escalation; one-shot restart handling; final full-set reconcile;
diagnostics/upload/gate; sandbox independent classification; R18 tier-1/corpus
status. If a T6 section is later appended, verify it against this list; the
resolutions below stand on the file's hosted evidence and re-checked sources
(2026-08-29).

### R1 — Duplicate T5/order: one canonical pattern set, explicit consumer contract

**Problem.** Two `## T5 Improver — Implementation Patterns` sections coexist: lines
1056–1505 (Patterns 1–10, references the architect options doc) and lines 1506–1817
(IP-1–IP-10, the later append). Both derive from the same T3 10-item contract and
converge on the same mechanisms, but they are not textually identical, and a
downstream consumer cannot merge them by guessing.

**Resolution.** The **canonical pattern set is IP-1–IP-10 (lines 1506–1817)** — the
later, self-contained append that satisfies the task's explicit finding list
(improver L2) and carries the R18-corpus correction as its foundation. The first T5
(lines 1056–1505) is a **supplementary detail source**, not a rival; three details
it carries are merged into the canonical set below: (a) the concrete `umd-evidence/`
directory layout with fixed filenames (first-T5 Pattern 8), (b) the proposed
settle-window bound 60s/5s (Pattern 7), (c) the proposed daemon-reachability bound
120s/5s (Pattern 2). **Consumer contract:** the DD/Plan-K amendment quotes **F1–F10
below**, never either T5 alone; where F1–F10 are silent, the second T5 (IP-1–IP-10)
is the fallback authority, then the first T5. Prior sections are not edited (L7);
the Refiner's final validation should record the duplicate and confirm the canonical
designation.

### R2 — Bash-only contract: pipefail/PIPESTATUS must not silently no-op

**Problem.** `set -o pipefail` and `PIPESTATUS` are bash-only; every current script
is `#!/usr/bin/env sh` (dash on Ubuntu hosted runners), and dash rejects `-o
pipefail` silently ("Illegal option") and has no `PIPESTATUS` (github/docs#23853
empirical dash test). R18 empirically settled the ADR-0277-vs-runner-images#4459
contest: the marker was swallowed by `| tee` — **pipefail was OFF** on the hosted
runner actually used (exec-manager L105, researcher L8).

**Resolution (F1).** Every compose-owning script — the new
`.github/scripts/compose-start.sh` and every rewritten script that grows a pipeline
— must (1) carry `#!/usr/bin/env bash`, (2) be invoked explicitly as `bash
script.sh` in the workflow (the double pin forces bash regardless of shebang), and
(3) the docker-e2e job sets `defaults: run: shell: bash` so every inline `run:`
block executes `bash --noprofile --norc -eo pipefail {0}`. `rc=${PIPESTATUS[0]}`
is captured **on the line immediately after** every compose pipeline and is the only
status that branches retry/reconcile decisions — never `$?` of a pipeline tail.
Re-checked 2026-08-29: docs.github.com workflow-syntax documents the unspecified
default as `bash -e {0}` (no pipefail) and explicit `shell: bash` as `bash
--noprofile --norc -eo pipefail {0}`; actions/runner#353 confirms the empirical
default; axonops/audit#622 is the failure class this closes.

**Acceptance test (AT-1).** Shell unit test asserts each compose-owning script
starts with the bash shebang and that a fixture pipeline `false | tee log` yields
`PIPESTATUS[0] == 1` under the script's own interpreter (invoked as `bash
script.sh`); a dry-run YAML parse asserts `defaults: run: shell: bash` is present on
the docker-e2e job.

### R3 — Daemon wait vs capability preflight: two failure classes, one escalation route

**Problem.** A single one-shot preflight would hard-fail a cold-starting runner's
daemon (a new flake surface) while masking capability defects; preflight PASS gives
zero coverage of the race window (task-create→netns-discover→bind-mount, after any
daemon ping — moby/moby#50750).

**Resolution (F2).** Preflight splits into two named failure classes, both before
any container creation, both writing to `umd-evidence/docker-capability.txt`:
- **Class A — daemon reachability (bounded wait):** poll `docker version --format
  '{{.Server.Version}}'` up to a proposed 120s in 5s steps (human-approved
  parameter, T4 Q4); exhaustion routes through the SAME escalation channel as F4
  (preserve evidence → `hosted-netns-escalation: TRUE` → fail) — never a bare hard
  fail with no route.
- **Class B — capability assertion (immediate hard fail):** wrong storage driver,
  missing containerd/runc, denied/nonexistent image (existing
  `preflight-hatchet-images.sh` P3-S4 tripwire), `compose config` failure → hard
  fail with diagnostics, no retry.
Preflight PASS is a **capability snapshot, never a readiness proof** (L9
no-fake-readiness); the gate remains F7's reconcile.

**Acceptance test (AT-2).** Unit test feeds a fake `docker version` that (a) fails
transiently then succeeds → Class A path, (b) never succeeds → escalation verdict
written; capability-assertion fixtures (denied image, compose config error) → Class
B hard fail without touching the retry budget.

### R4 — Profile/full topology: `--profile sandbox` pinning and a resolved-set tripwire

**Problem.** `sandbox-runner` is profile-gated (`compose.yaml:235 profiles:
["sandbox"]`); a batch without the flag silently creates no sandbox-runner while
"succeeding", and neither `COMPOSE_PARALLEL_LIMIT` nor batch splitting may ever
reduce the effective topology (T4 item 3 risk 1).

**Resolution (F3).** The wrapper runs four `docker compose -f deploy/compose.yaml
--profile sandbox up -d <services>` invocations (Batch 1 `db` → Batch 2
`hatchet-migrate`+`hatchet-admin` → JWT mint (F6) → Batch 3
`hatchet-engine`+`hatchet-dashboard` → Batch 4 `api`+`worker`+`sandbox-runner`),
the SAME compose file, SAME project, and `--profile sandbox` **on Batch 4 and on
every full-set reconcile**. `COMPOSE_PARALLEL_LIMIT=1` (proposed; human-approved
value, T4 Q5) is set **via environment**, because current compose docs state that
explicit CLI flags override the env var — env keeps the knob stable against flag
precedence bugs (docker/compose#10547/#10566), and the documented default is
`--parallel=-1` (unlimited), so `=1` is a deliberate narrowing. Re-checked
2026-08-29: Docker compose envvars reference and CLI reference
(`COMPOSE_PARALLEL_LIMIT` = "maximum level of parallelism for concurrent engine
calls", equivalent to `--parallel`; default `-1`; flags ignore the env var when both
are given). **Topology tripwire:** after the batches, `docker compose -f
deploy/compose.yaml --profile sandbox config --services` must equal the full
required set `db api worker sandbox-runner hatchet-migrate hatchet-admin
hatchet-engine hatchet-dashboard` — silent topology reduction is a hard failure with
evidence.

**Acceptance test (AT-3).** `compose config --profile sandbox --services` assertion
in a test job (no daemon needed) asserting the full 8-service set for every batch
command line, plus a negative fixture (batch without `--profile sandbox`) that the
tripwire flags.

### R5 — JWT/env parity: mint inside the wrapper, token reaches every worker

**Problem.** Two traps. (a) In the single-owner wrapper the mint and Batch 4 are in
ONE step, so `>> $GITHUB_ENV` reaches subsequent steps, not containers created later
in the same step — api/worker would start with empty `UMD_HATCHET_TOKEN` (T4 item 3
risk 2). (b) `sandbox-runner`'s env block lacks `UMD_HATCHET_SERVER_URL`,
`UMD_HATCHET_TOKEN`, `HATCHET_CLIENT_HOST_PORT` that `worker` gets
(`compose.yaml:120-122` vs `:236-241`), so under Plan K P2-S3's fail-closed
`cli.worker` it crash-loops under `restart: unless-stopped` (`compose.yaml:251`)
regardless of seccomp (T4 item 9, HIGH).

**Resolution (F6).** (1) Batch order is Batch 1 → Batch 2 (exited(0) +
`/hatchet/config` populated) → **tenant discovery (bounded 30×2s
case-insensitive) + JWT mint** → Batch 3 → Batch 4. (2) The wrapper exports
`UMD_HATCHET_TOKEN`/`HATCHET_TENANT_TOKEN` into its **own process environment**
before Batch 4 (and mirrors to `$GITHUB_ENV` for later steps); compose resolves
api/worker env at container create, so own-process export is the mechanism. (3)
Mint failure (empty, non-`ey`, `hatchet-admin token create` error) = named HARD
failure with diagnostics, never a netns retry. (4) **sandbox-runner env parity** —
because the workflow already forces `--profile sandbox` and requires sandbox-runner
running, the canonical default is **option a: sandbox-runner is a mandatory release
gate with FULL Hatchet env parity with `worker`** (the three variables) plus a
distinct boot contract (register and stay running; never counted via a readiness
line alone); **option b** (named profile-gated capability reported
`configured-unavailable`/`gated`, excluded from `required_running`) remains the
documented alternative and is a security-posture/product call (T4 Q2) that must be
made before the next hosted run; the topology tripwire (F3) lists sandbox-runner
either way so absence is visible.

**Acceptance test (AT-4).** `compose config` assertion that sandbox-runner env is
token-complete (the three vars resolve, not empty) under option a; a shell fixture
asserting a wrapper-owned mint writes the token to the process env before Batch 4's
invocation; mint-failure fixtures (empty/non-`ey`/error) classify as hard failure.

### R6 — Exact marker and bounded escalation: anchored regex, named budget, named route

**Problem.** The marker has multiple root causes (moby/moby#50750,
containerd/containerd#12141: checkpoint pid 0, CRIU CI, ordinary task-create); the
current prefix grep `bind-mount /proc/` would retry other `/proc` bind-mount
failures; and the retry branch has zero production executions (R18: swallowed by
tee) (T4 item 4).

**Resolution (F4).** Retry predicate is the anchored regex `bind-mount
/proc/[0-9]+/ns/net -> /var/run/docker/netns/[0-9a-f]+: no such file or directory`
(variable pid/id only); the `lstat /proc/<pid>/ns/net` class (moby/moby#46490,
different message/mechanism) is **explicitly excluded**; no retry on "not running",
timeout, EPERM, OOM, invalid config, missing image, nonzero one-shot exit, generic
text. Budget: 3 attempts per batch, `--no-build` after attempt 1, fixed 5s backoff,
attempts counted from visible compose output under F1's status contract.
**Escalation:** budget exhausted on the same clean runner → preserve the full
evidence dir, write `hosted-netns-escalation: TRUE` to
`umd-evidence/escalation-verdict.txt`, fail the run, route as a hosted-runner/daemon
issue; never enlarge the budget, never convert to blanket retry (forbidden F).
**Negative-test matrix committed** (T4 evidence-needed #2): lstat class, other
`/proc` bind-mounts, "not running", EPERM, one-shot non-zero, denied image →
NOT-marker; exact marker with variable pid/id → retry.

**Acceptance test (AT-5).** Committed shell unit test running the matrix against the
anchored regex (pure grep, no daemon); an integration fixture proving a marker hit
consumes exactly one budget slot and a non-marker failure fails closed without
budget consumption.

### R7 — One-shot restart handling: first non-zero exit is the failure

**Problem.** `hatchet-migrate`/`hatchet-admin` use `restart: on-failure`
(`compose.yaml:148,176`); a non-zero exit is restarted by Docker, so
`State.Status == exited` may never be observed (cycles
exited→restarting→running→exited) and a reconcile waiting for a "final" exited
state waits forever (T4 item 5 risk 1).

**Resolution (F5).** The **first non-zero `State.ExitCode` observed on a one-shot is
a HARD failure regardless of restart policy** — record the exit, classify, fail
closed; do not wait for a final exited state. Gate one-shots on `docker inspect
--format '{{.State.ExitCode}}'` + `{{.RestartCount}}`/`{{.Restarting}}`, not
`State.Status` alone; `ExitCode == 0` with no restart cycle is the only pass. Every
engine-level wait is wrapped in `timeout 300` (`docker wait` has no timeout flag —
Docker CLI reference), with a named escalation (evidence → hard fail) mirroring F4.
`docker wait` works on already-exited containers and returns the recorded exit code
(SpecHive abc6dea precedent).

**Acceptance test (AT-6).** Classifier unit test: fixture inspect JSON with
`ExitCode != 0` → failure even with `State.Status` cycling; `ExitCode == 0` +
`RestartCount > 0` → failure; clean exited(0) → pass; a `docker wait` fixture that
never returns is killed by `timeout 300` and escalates.

### R8 — Final full-set reconcile: the deterministic fail-closed gate

**Problem.** Per-batch reconcile can pass while an earlier batch's service silently
regressed (T4 item 7 risk); R15 proved `compose up` can exit 0 with services in
`Created`; R18 proved reconcile recovers a swallowed marker fail-closed (the
strongest support for the whole A′ shape).

**Resolution (F7).** Reconcile after EVERY batch (fast-fail aid) AND a **final
full-set reconcile after Batch 4 that is THE gate**: `db`, `api`, `worker`,
`sandbox-runner` (per R5's decision), `hatchet-engine`, `hatchet-dashboard` running
with empty `State.Error`, not restarting, `State.OOMKilled == false`;
`hatchet-migrate`, `hatchet-admin` exited(0). Every reconcile uses `docker compose
ps -a` + per-container `docker inspect` (never `ps -q`; R17 false-absence fixed in
`e6b5c3f`). **Classified re-up:** a re-up is a bounded marker retry ONLY when the
exact anchored regex is present in that re-up's VISIBLE output; any other mismatch
after a re-up is a hard failure with diagnostics. The current
`validation.yml:375-377` `>/tmp/compose-reconcile.log 2>&1 || true` suppression is
removed: every recovery invocation writes a labeled log that is (a) streamed, (b)
retained as an artifact, (c) included in diagnostics. **Settle window:** proposed
60s/5s poll (human-approved, T4 Q3) before a created-without-marker is classified a
hard failure, so normal start latency is not a false escalation. The `2d84d07`
reconciliation is preserved and strengthened, never weakened (L3).

**Acceptance test (AT-7).** Negative-test matrix for the classifier (each service
class × required state); a fixture where Batch 3 passes then engine regresses →
final full-set reconcile fails; a fixture where the re-up output contains the exact
marker → classified retry (budget consumed), where it does not → hard failure.

### R9 — Diagnostics/upload/gate: evidence survives, verdict reaches the gate

**Problem.** `capture-diagnostics.sh` captures per-service logs only;
`/tmp/compose-up.log`/`/tmp/compose-reconcile.log` are not copied and the artifact
upload list (`validation.yml:526-539`) does not include them — a failed marker-retry
cannot be post-hoc classified from evidence; and the aggregate gate reads only three
gate files, so an escalated run could produce green gate files (T4 item 8 risks 1–2).

**Resolution (F8).** One evidence directory per run (`$RUNNER_TEMP/umd-evidence/`)
with the fixed layout (first-T5 Pattern 8 merged): `docker-capability.txt`,
`image-digests.txt`, `compose-up-batch-{1..4}-{attempt}.log`,
`compose-reconcile-{n}.log`, `svc-inspect/{service}.json`, `compose-ps.txt`,
`network-inspect.txt`, `sandbox-security.txt`, `escalation-verdict.txt`, plus the
existing junit/coverage/db-dump/OCFL per-service logs. The wrapper writes its
labeled logs into this dir; the artifact glob (`validation.yml:526-539`) must
include the whole dir. `capture-diagnostics.sh` runs under `if: always()` BEFORE
teardown and stays **collection-only** (`|| true` guards never decide the gate — DD
P3-S5 non-masking contract). **F10 (gate):** the aggregate gate
(`validation.yml:497-509`) reads `escalation-verdict.txt` in addition to the three
gate files: `hosted-netns-escalation: TRUE` present = FAIL; verdict file absent =
FAIL (fail-closed). Named volumes preserved through restart/duplicate/retry/E2E
(`stop`/`start`, never `down -v`); final `down -v` only after evidence upload.

**Acceptance test (AT-8).** Artifact-listing assertion (T4 evidence-needed #4): a
fixture run uploads the evidence dir and the listing contains
`compose-up-batch-*.log`, `compose-reconcile-*.log`, `escalation-verdict.txt`; a
gate fixture with green gate files but `escalation-verdict.txt` = TRUE → FAIL;
missing verdict file → FAIL.

### R10 — Sandbox independent classification: seccomp class fails closed, never consumes netns budget

**Problem.** R16 (`statx`/`fsmount` EPERM) and R17 (`getcwd`/`vfork` EPERM +
`sandbox-runner=restarting`) prove the sandbox seccomp class is distinct from the
netns class; mixing them would let seccomp failures consume netns retry budget and
mask profile defects.

**Resolution (F9).** Any `statx`, `fsmount`, `getcwd`, `vfork`, `clone`, `unshare`,
or related `EPERM` in sandbox logs = sandbox profile/AppArmor/userns failure: FAIL
the run closed, route to security/profile diagnosis (the P3-S3 moby-default +
`pivot_root` amendment is the fix, already in the tree), and NEVER consume netns
retry budget. PROVISIONAL (unchanged, T2 MEDIUM): Docker's default seccomp profile
is a capability-gated allowlist (Docker seccomp docs), so "the P3-S3 profile proves
bwrap boots under cap_drop ALL/no-new-privileges" is PROVISIONAL — R18 is one green
sandbox boot, not proof of the general posture; a residual AppArmor/userns failure
is a security-posture design question (bounded options: named unconfined for
sandbox-runner only, or documented honest gated OS-isolation), never a netns retry,
never a topology change. Blanket privileged/unconfined remains rejected (L9, DD).

**Acceptance test (AT-9).** Classifier unit test: sandbox-log fixtures with each
EPERM string → security-class failure, netns budget untouched; a fixture mixing a
netns marker and a sandbox EPERM in one run → both classes reported distinctly,
budget consumed only by the marker.

### R11 — R18 tier-1/corpus status: corroborated at coordination tier, tier-1 retrieval is a Phase 6 obligation

**Resolution (F-R18).** R18 (`33228898244`) is **corroborated at the
coordination/analysis tier** by two independent corpus entries — exec-manager L105
(02:29:29Z) and researcher L8 (02:30:38Z): full split topology boots, `/v1/ready`
PASS, worker registration gate PASS, external HTTP flows PASS; live Hatchet suite
first execution **6 pass / 4 FAIL** (4× `source_pkey` UniqueViolation + 1×
`ModuleNotFoundError hatchet_sdk` — toolchain/test-isolation, NOT netns); the netns
marker **appeared once and was swallowed by `| tee`** (pipefail OFF → the F1 bash
contract is empirically justified) and the reconcile loop recovered it fail-closed.
**Standing posture:** the ledger's "R18 NOT established" row is stale; T4's upgraded
reading stands — corroborated at coordination tier, **tier-1 GitHub re-retrieval
pending** and is a binding Phase 6 / Exec-Manager handoff obligation before the
ledger is finalized. R18 supports the workflow-only direction (topology boots under
the current non-serialized workflow; the live-suite blockers are not topology) and
does NOT close the release gate; if re-retrieval shows budget exhaustion, it argues
for F4 escalation, never more retries, never a topology change.

**Acceptance test (AT-10).** Phase 6 checklist item: re-fetch `33228898244` from
GitHub, update the ledger row, and diff the tier-1 reading against L105/L8; the
amendment is not final until this row is updated.

### Single canonical amendment design (what the DD/Plan-K amendment must carry)

F1–F10 above are the consolidated canonical design, each derived from both T5 sets
(second T5 canonical + first-T5 details merged). The amendment carries, verbatim:
**F1** bash/pipefail interpreter + status contract; **F2** two-phase preflight;
**F3** four serialized batches + `--profile sandbox` pinning + topology tripwire +
`COMPOSE_PARALLEL_LIMIT=1` (env); **F4** exact-marker anchored regex + 3-attempt
budget + escalation verdict; **F5** one-shot first-exit rule + bounded `timeout 300`
waits; **F6** JWT mint inside wrapper with own-process export + sandbox-runner env
parity; **F7** per-batch + final full-set reconcile with classified re-up and settle
window; **F8** `umd-evidence/` schema wired into capture/upload; **F9** independent
sandbox seccomp classification; **F10** aggregate gate reads the escalation verdict
(absent = FAIL); plus the R18 ledger-row obligation (F-R18).

### Mapping to Plan K amendment and acceptance tests

| Final pattern | Plan K phase/step it amends | Acceptance test |
|---|---|---|
| F1 bash contract | P3-S3 (docker-e2e startup contract; job `defaults: run: shell: bash`); Phase 6 review | AT-1 interpreter + PIPESTATUS fixture |
| F2 two-phase preflight | P3-S4 (extends `preflight-hatchet-images.sh`); P3-S5 facts | AT-2 Class A/B fixtures |
| F3 batches + topology pinning | P3-S3 startup contract; `--profile sandbox` pinned; P2-S2/P2-S3 topology evidence | AT-3 `compose config --services` full-set assertion |
| F4 exact marker + escalation | P3-S3 retry contract (replaces `validation.yml:313-345`); Phase 6 negative matrix | AT-5 marker matrix + budget accounting |
| F5 one-shot state model | P3-S3 reconcile contract (`ps -a` + inspect); commit `2d84d07` preserved | AT-6 first-exit classifier fixtures |
| F6 JWT ordering + env parity | P2-S4 (JWT mint); P3-S3 Batch 4 env; Phase 5 vocabulary (option a/b) | AT-4 token-complete `compose config` + mint fixtures |
| F7 full-set reconcile | P3-S3 gate; `2d84d07`/`e6b5c3f` preserved | AT-7 classifier matrix + regression fixture |
| F8 diagnostics schema | P3-S5 capture/upload (`validation.yml:526-539`) | AT-8 artifact-listing + gate-verdict fixtures |
| F9 sandbox classification | P3-S3 seccomp amendment preserved; Phase 6 re-verify | AT-9 EPERM-class fixtures |
| F10 gate + escalation | P3-S5 aggregate gate (`validation.yml:497-509`) + release summary | AT-8 escalation-verdict gate fixture |
| F-R18 ledger row | Phase 6 final QA | AT-10 tier-1 re-retrieval checklist |

### Preserved immutable requirements (L1–L9) and forbidden set

F1–F10 + F-R18 preserve every binding invariant, verified against the ledger: **L1**
(approved R&D workflow continued — this log is the formal adversarial path for L6);
**L2** (netns roadblocks investigated — R10–R18 hosted evidence table); **L3**
(Task.md not bypassed/weakened — `2d84d07`/`e6b5c3f` reconciles and the P3-S3
seccomp amendment preserved); **L4** (DD anchor, Plan K, support findings reviewed);
**L5** (verdict: **workflow-design change, not architecture/topology change** — no
topology pattern anywhere; C/D remain rejected/gated); **L6** (adversarial review
run; this log is the record); **L7** (no code/workflow/DD/plan edits — this section
is design only); **L8** (exact artifacts/handoff below); **L9** (full split Hatchet
topology via F3 pinning; real callbacks via F6 real-token registration; mandatory
hosted validation via F7/F10 gates; no skips/stubs/fake readiness via F2 labeling +
F5/F7 evidence; no second scheduler — the wrapper is the sole compose owner, Hatchet
remains the sole scheduler). Forbidden set never re-introduced: Hatchet Lite,
DinD/socket mounts, privileged/unconfined broad bypass, skipping sandbox,
optional/trigger-level gate, fake readiness, second scheduler, blanket retry (F),
`--wait` sole gate (carried: docker/compose#10596/#11774/#11638/#13069/#12424).

### Hosted runs cited (exact) and sources/check dates

Hosted tier-1 evidence restated exactly from the ledger: R10/`33226227591` (daemon
bind-mount netns marker, live pid), R11/`33226431905` (netns retry then independent
alembic.ini failure), R15/`33227518543` (`compose up` exited 0, services Created —
reconcile-as-gate), R16/`33228084721` (sandbox `statx`/`fsmount` EPERM),
R17/`33228376245` (sandbox `getcwd`/`vfork` EPERM, `sandbox-runner=restarting`,
`ps -q` false absence), R18/`33228898244` (corroborated at coordination tier:
topology boots, registration PASS, 6 pass/4 FAIL toolchain blockers, marker
swallowed by `tee`, reconcile recovered fail-closed; tier-1 GitHub re-retrieval
pending).

Sources re-checked **2026-08-29**: docs.github.com workflow-syntax
(`defaults.run.shell`: unspecified = `bash -e {0}`, `bash` = `bash --noprofile
--norc -eo pipefail {0}`); github/docs#23853 (dash empirical test); actions/runner#353
+ ADR 0277 (contested default → F1 explicit); Docker compose envvars reference +
CLI reference (`COMPOSE_PARALLEL_LIMIT` = max parallelism for concurrent engine
calls; `--parallel=-1` default; flags override env); docker/compose#10547/#10566
(flag-vs-env precedence); Docker CLI reference (`docker wait` no timeout; `docker
inspect` State fields); moby/moby#50750/#46490, containerd/containerd#12141,
dify#7739 (marker classes; lstat exclusion); Docker seccomp docs (capability-gated
allowlist); axonops/audit#622 (tee masking postmortem); oven-sh/bun 2ad4199
(single-owner serialization); SpecHive abc6dea (2026-04-27, engine-level `docker
wait` + timeout). Prior-turn citations (GNU Bash manual §3.2.3/§5.2, compose
`--wait` issues #10596/#11774/#11638/#13069/#12424, dind race family
actions/runner#4117 + actions-runner-controller#3828/#3794) stand with their
2026-08-29 check dates.

### Open risks / human questions (carried to T8 and Exec-Manager)

1. **sandbox-runner role/env (blocks next hosted run):** option a (mandatory gate,
   full env parity — canonical default) vs option b (named gated capability) —
   security-posture/product call (T4 Q2).
2. **R18 tier-1 re-retrieval** — binding Phase 6 obligation; the ledger row must be
   updated from GitHub before the amendment is finalized.
3. **Reconcile settle-window bound** — F7 proposes 60s/5s (T4 Q3).
4. **Daemon-reachability budget** — F2 proposes 120s/5s (T4 Q4).
5. **`COMPOSE_PARALLEL_LIMIT` value** — F3 proposes `=1` via env; measure wall-time
   on the first green runs (T4 Q5).
6. **Retry branch first production execution** — F4's branch has never run; the
   first green hosted run is its first real test, and F8's evidence schema makes it
   auditable.

### Handoff to DDAuthor/Exec-Planner (L8)

Distill **F1–F10 + F-R18** (above) into the Plan K amendment and the DD
`DD-universal-media-decomposer-ci-repair.md` amendment (A + minimal C remains the
anchor; the amendment is workflow-only). Acceptance criteria: AT-1..AT-10 pass in a
`test` job before the first amended hosted run; the first amended hosted run is the
validation run for F4/F7. No topology, scheduler, or evidence-surface changes; no
code/workflow edits were made by this turn (L7). Artifacts: this section is the
canonical pattern record; the duplicate T5 sections (lines 1056–1505 and 1506–1817)
are flagged for Refiner reconciliation (canonical = lines 1506–1817).
## T6 Counter-Improver — Pattern Risk Assessment

**Turn 6 scope.** I read the entire shared file (T1–T5, both T5 pattern sets), the
approved DD anchor, Plan K, the current workflow (`validation.yml`), `deploy/compose.yaml`,
`deploy/security/sandbox-seccomp.json` + `SANDBOX_HOST_PROFILE.md`, all six `.github/scripts`
(verified `#!/usr/bin/env sh`), and the support logs referenced in the corpus. This turn
critiques the implementation patterns from **both** T5 sets at the pattern level, flags the
duplicate-T5/process-order defect for later reconciliation, and checks every immutable
requirement (L1–L9). No code, workflow, DD, or plan edits are made (L7). All technology
claims re-checked against current official/maintainer sources **2026-08-29**; anything not
independently verifiable is labeled PROVISIONAL.

### 0. Process-order defect (must be reconciled before DDAuthor/Exec-Planner consumes T5)

- **The Improver (T5) output was appended TWICE.** The canonical first T5 set
  (`Pattern 1–10`, lines 1056–1505) and a second, divergent T5 set (`Pattern IP-1…IP-10`,
  lines 1506–1817, EOF at 1817) both exist. They are **not duplicates**: different pattern
  numbering, different scope text (first reads `validation.yml:203+`; second reads
  `validation.yml:47-548`), different parameter values for the SAME contract item, and
  different granularity. This file has NO T6 until now; do not append a second T6.
- **Why this is a pattern-level risk, not cosmetic:** DDAuthor/Exec-Planner cannot consume
  "the T5 patterns" as a single contract. Concrete conflicts:
  1. **Daemon-reachability budget differs:** first T5 Pattern 2 proposes `120s in 5s steps`;
     second T5 IP-3 proposes the `seq 1 30 / sleep 2` tenant-discovery idiom (≈60s). Same
     parameter, two values — a human must pick one.
  2. **Settle-window parameter:** first T5 Pattern 7 proposes `60s/5s` poll before
     created-without-marker is a hard failure; second T5 IP-8 leaves it at "fail-closed
     default" with no number.
  3. **Job-level shell default:** second T5 IP-1 adds `defaults: run: shell: bash` at the
     docker-e2e job level (affects EVERY step in the job, including the pre-existing
     pytest/tee steps that currently run under `bash -e {0}`); first T5 Pattern 1 only pins
     the wrapper script's shebang. Flipping the job default is a much wider blast radius
     than the first set implies and must be audited per-step.
  4. **Profile/topology pinning:** both sets agree `--profile sandbox` must be pinned, but
     only the second set (IP-5) adds the `config --services` topology tripwire; the first
     set (Pattern 3) does not. The first set alone would miss silent topology reduction.
- **Recommendation:** T7 (Improver final) must emit ONE reconciled pattern set with a
  disposition table for each conflict above, or the amendment inherits two competing
  contracts. **Severity: BLOCKING for the amendment process** (not for the design
  direction, which both sets agree on).

### 1. Pattern 4 / IP-2 — PIPESTATUS capture is unreachable under `set -euo pipefail` (BLOCKING)

- **Source:** [Tier 3] GNU Bash Reference Manual — `set -e` ("Exit immediately if a
  pipeline … returns a non-zero status") and its exceptions (`&&`/`||` lists), and
  `PIPESTATUS` ("an array variable … contains a list of the exit status values from the
  processes in the most-recently-executed foreground pipeline"; updated by the next
  command). Checked 2026-08-29.
- **Mechanism:** Both T5 sets mandate `set -euo pipefail` on the wrapper AND
  `rc=${PIPESTATUS[0]}` "on the line immediately after" every compose pipeline (first T5
  Pattern 4, lines 1193-1200; second T5 IP-2, lines 1568-1581). These two mandates
  **conflict**: under `set -e`, a failing pipeline (compose exits non-zero) aborts the
  script *before* the capture line executes — the retry branch never runs and the wrapper
  dies as a bare hard failure. The capture idiom only works in the pipefail-OFF world
  (where `PIPESTATUS[0]` still reports compose's true rc) or when the pipeline is shielded
  from `set -e` by an `||`/`if` construct.
- **Trigger:** exactly the condition the pattern exists for — compose fails with the netns
  marker and pipefail is on (which the pattern mandates). Under the pattern as written,
  the bounded retry is dead code in the ON state and works only in the OFF state it is
  meant to eliminate.
- **Blast radius:** the exact-marker retry, the reconcile re-up classification, and the
  escalation path all key off `rc`. If the wrapper exits on first failure, the 3-attempt
  budget never runs; classification never happens; evidence capture still runs but the
  escalation verdict is never written.
- **Mitigation (pattern must be rewritten):** `rc=0; docker compose … 2>&1 | tee "$log" ||
  rc=${PIPESTATUS[0]}` — the `||` shields the pipeline from `set -e`, and the
  `PIPESTATUS[0]` expansion still refers to the compose pipeline. Alternatively drop
  `set -e` around compose-owning statements and branch on `rc` explicitly. **Severity:
  BLOCKING** — the single most important status-preservation contract is self-defeating as
  written.

### 2. Pattern 4 / IP-4 — retry trigger assumes compose exits non-zero on the marker; R15 proves it can exit 0 (HIGH)

- **Source:** [Tier 1] hosted R15 (`33227518543`): `compose up` exited 0 while required
  services stayed Created. [Tier 1-coordination] R18 corpus (exec-manager L105, researcher
  L8): netns marker "appeared once and was swallowed by `| tee`"; reconcile recovered it
  fail-closed.
- **Mechanism:** both pattern sets branch the bounded retry on `rc` (the captured compose
  exit status) alone. If the marker fires while compose exits 0 — the R15-proven
  daemon-side start-abort class — `rc=0`, the retry branch never fires, and the marker is
  only recovered by the reconcile re-up (a *different* budget: 5 attempts, no backoff, no
  escalation verdict). The bounded 3-attempt budget + `hosted-netns-escalation` path would
  then be unreachable for exactly the failure they were designed for.
- **Trigger:** the R15-class mechanism; indistinguishable from the R18 "pipefail OFF"
  reading on observable evidence alone (both paths look identical: retry branch silent,
  reconcile recovers). The second T5 set's claim (lines 1537-1540) that R18 "empirically
  settles … pipefail was OFF" is an **inference, not a direct observation** — the same
  observable outcome is produced by compose-exit-0.
- **Blast radius:** retry/escalation contract silently dead; false confidence that a
  "bounded retry" exists.
- **Mitigation:** classify on "exact marker present in visible output **OR** `rc != 0`",
  never `rc` alone. Reconcile remains the gate (both sets agree — correct). **Severity:
  HIGH.**

### 3. Cross-pattern — one-shot `restart: on-failure` × `depends_on: service_completed_successfully` × reconcile re-up = indefinite hang (HIGH)

- **Source:** [Tier 3] `compose.yaml:148,176` (`hatchet-migrate`/`hatchet-admin` use
  `restart: on-failure` with no max-retries → unlimited), `compose.yaml:172-173,194-198`
  (engine/dashboard depend on `service_completed_successfully`). [Tier 2/3] docker/compose#12134
  (open, 2024-09): `--wait-timeout` and `--timeout` do **not** work with
  `service_completed_successfully` — `up` hangs indefinitely. docker/compose#10985
  (2023-09): every `up` invocation **re-runs** the one-shot dependency even after a
  successful completion. docker/compose#10728 (chain hang; fixed in v2.19.0).
- **Mechanism:** a one-shot that exits non-zero is restarted by Docker (never reaches
  `exited`); any `up` for a dependent service waits on `service_completed_successfully`
  forever — and `--wait-timeout` cannot save it (#12134). The current reconcile re-up
  (`validation.yml:375-377`, `|| true`, no timeout) would block for hours. Additionally,
  because depends_on re-triggers dependencies on every `up`, **batches 3/4 re-run
  migrate+admin** even though batch 2 "already ran them" — the pattern sets' implicit
  "one-shots run once in batch 2" assumption is false.
- **Trigger:** any non-zero one-shot exit (e.g., a transient DB/connection error during
  migrate) — not a netns event at all.
- **Blast radius:** the wrapper hangs; the step exceeds GitHub's default 360-min timeout;
  evidence is captured but the run dies without classification. The first-exit rule
  (Pattern 5/IP-7) fixes classification but runs AFTER the hang, so it is not a
  mitigation for the re-up.
- **Mitigation:** (a) classify one-shot state from `docker inspect` **before** any re-up,
  and fail closed on first non-zero exit; (b) wrap every compose `up` in an explicit
  `timeout`; (c) run batches 3/4 with `--no-deps` (batch 2 already satisfied
  dependencies) to avoid re-entering the depends_on wait and re-running the one-shots.
  **Severity: HIGH.**

### 4. Pattern 3 / IP-5 — `COMPOSE_PARALLEL_LIMIT=1` is valid on current Compose; the "floor of 2" fallback is stale (LOW)

- **Source:** [Tier 3] docker/compose `cmd/compose/compose.go` (main, checked 2026-08-29):
  `if v, ok := os.LookupEnv(ComposeParallelLimit); ok && !composeCmd.Flags().Changed("parallel")`
  — the flag-wins precedence fixed by PR #10566 is present in current source; `--parallel`
  default is `-1` (unlimited); any positive value including 1 is accepted (`if parallel >
  0`). Docker docs envvars reference confirms the knob semantics. Hosted runner images
  announced Docker Compose 2.40.3 / Docker 29.1.* (actions/runner-images#13474, 2026-02).
- **Mechanism:** the first T5 Pattern 3's "may not be set lower than 2 … use 2" fallback
  is stale relative to current Compose; `=1` works. The second T5 IP-5 is correct.
- **Blast radius:** none at runtime (compose accepts 1); only the stale fallback would
  silently relax the intra-batch serialization decision.
- **Mitigation:** pin `=1`; record the actual `docker compose version` in
  `docker-capability.txt` (both sets already require the snapshot). **Severity: LOW.**

### 5. Pattern 9 / IP-10 — the seccomp premise is factually wrong about the actual profile; AppArmor/userns is the live risk (HIGH)

- **Source:** [Tier 1-local] `deploy/security/sandbox-seccomp.json` (read 2026-08-29):
  `defaultAction: SCMP_ACT_ERRNO` with a **single ungated allowlist** of ~415 syscalls that
  includes `unshare`, `clone`, `clone3`, `mount`, `mount_setattr`, `move_mount`, `fsmount`,
  `fsopen`, `fspick`, `pivot_root`, `setns`, `ptrace`, `process_vm_readv/writev`,
  `open_by_handle_at`, `bpf`, `perf_event_open`, `init_module`/`delete_module`, `iopl`,
  `ioperm`, `reboot`. [Tier 3] Docker seccomp docs (checked 2026-08-29): the **default**
  moby profile gates `clone`/`unshare`/`mount`/`setns` on `CAP_SYS_ADMIN` (with the
  `CLONE_NEWUSER` exception); moby/moby#42441 (open, updated 2025-10-08) and moby/profiles#4/#5
  (open, 2025-10) confirm the default still gates `unshare` at check time. [Tier 2/3]
  containers/bubblewrap#505 (maintainer: Docker's default seccomp blocks the clone/unshare
  bwrap needs) and the Codex/Claude-Code reports show Ubuntu 24.04's AppArmor
  `apparmor_restrict_unprivileged_userns` applies **inside** containers on the host kernel.
- **Mechanism:** the actual profile is NOT "moby default + pivot_root" — it is an **ungated
  allowlist** that permits namespace/mount syscalls without any capability gate. That is
  why R18's sandbox boot is plausible despite `cap_drop ALL`/no-new-privileges. But it
  also means the documented "validated non-privileged posture" is materially closer to
  `seccomp=unconfined` for namespace/mount/ptrace/bpf operations than either T5 set
  states, and the PROVISIONAL framing ("necessary but not sufficient") understates the
  exposure. The residual, genuinely unproven layer is **AppArmor/userns on the host
  kernel**, not seccomp: hosted `ubuntu-latest` is Ubuntu 24.04 (GitHub changelog
  2024-09-25; runner-images Ubuntu2404 readme, image 20260823.283.1, kernel
  6.17.0-1022-azure), and if `sandbox-runner` invokes bwrap as a non-root user, unprivileged
  userns creation may be blocked by host AppArmor regardless of the seccomp JSON. If it
  runs as root, bwrap skips userns (claude-code#48304 mechanism) and the ungated profile
  allows the needed mounts — which is consistent with R18's green boot but is a
  single coordination-tier datum.
- **Trigger:** any hosted-runner image move to a kernel/AppArmor config that restricts
  unprivileged userns (24.04 already does); or a bwrap invocation that needs userns as a
  non-root user.
- **Blast radius:** sandbox boot gate fails; Pattern 9/IP-10 would correctly fail-closed,
  but the classification cites the wrong mechanism (seccomp instead of AppArmor), so the
  diagnostics contract (Pattern 8) must actually capture AppArmor/userns facts — which the
  sandbox-security.txt item only gestures at.
- **Mitigation:** (a) re-document the profile honestly as an ungated allowlist and have a
  human security review sign off (this is a security-posture decision, not a netns one);
  (b) capture `sandbox-runner`'s effective user, bwrap argv, and host AppArmor state in
  diagnostics; (c) keep the classification rule (never consume netns budget) — it is
  correct regardless of the profile misdescription. **Severity: HIGH** for evidence
  integrity and security-posture honesty.

### 6. Pattern 6 / IP-6 — GITHUB_ENV same-step trap confirmed; sandbox-runner env parity is the blocking open question (MEDIUM/HIGH)

- **Source:** [Tier 3] GitHub docs — Workflow commands (checked 2026-08-29): "The step
  that creates or updates the environment variable does not have access to the new value,
  but all subsequent steps in a job will have access." Confirms the same-process export
  requirement. [Tier 1-local] `compose.yaml:120-122` vs `:236-241`: `worker` receives
  `UMD_HATCHET_SERVER_URL`/`UMD_HATCHET_TOKEN`/`HATCHET_CLIENT_HOST_PORT`;
  `sandbox-runner` does not (only `UMD_ROLE`, `UMD_SANDBOX_PROFILE`, `umd-api-env`), and
  uses `restart: unless-stopped` (`:251`).
- **Mechanism:** the env-scope fix is correct. Residual risks: (a) `echo
  "UMD_HATCHET_TOKEN=$TOKEN" >> "$GITHUB_ENV"` (existing `validation.yml:302-303`)
  exposes the per-run JWT to every subsequent step's environment; bounded blast radius
  (per-run token) but should use `::add-mask::` on the value in the same step; (b) whether
  `sandbox-runner` actually runs the worker command that fails closed on missing token/URL
  is still **unresolved in the corpus** — R18's reconcile counted *a* required set, but
  whether `sandbox-runner` specifically was `running` (vs crash-looping) is NOT
  established. Both T5 sets correctly carry this as human question 2, but neither provides
  the decision; it blocks the next hosted run.
- **Blast radius:** if sandbox-runner is a mandatory gate without env parity, it
  crash-loops under `unless-stopped`; the final full-set reconcile then hard-fails for a
  configuration reason misattributable to the netns class.
- **Mitigation:** resolve the product/security call (full parity + mandatory gate, or
  honest `configured-unavailable`) before the next hosted run; add-mask the minted token.
  **Severity: HIGH** (carried from T4; unchanged).

### 7. Pattern 8 / IP-9 — diagnostics/upload/aggregate gate: verified gaps, one residual (MEDIUM)

- **Source:** [Tier 1-local] `validation.yml:497-509` (aggregate gate reads only
  live-worker/boundary/after-restart gate files), `:526-539` (upload list lacks
  compose-up/reconcile logs), `:539` (`if-no-files-found: warn`).
- **Mechanism:** both pattern sets close the upload-list and gate-read-set gaps correctly
  (evidence dir + escalation-verdict.txt; absent = FAIL). Residual: `if-no-files-found:
  warn` means a wrapper that dies before writing the evidence dir can still upload with
  nothing and the run "succeeds" at the upload step; the aggregate gate still fails on the
  missing verdict (fail-closed is preserved), but the post-hoc classification evidence is
  silently lost. Also note the aggregate gate (step at `:497`) currently runs BEFORE
  capture-diagnostics (`:516`) and upload (`:521`); under `if: always()` the later steps
  still run, so the verdict file is on the runner filesystem for the gate regardless —
  no ordering defect, but the wrapper must write `escalation-verdict.txt` even on its own
  death path.
- **Mitigation:** change upload to `if-no-files-found: error` for the escalation case;
  require the wrapper to write the verdict file before any exit (including trap paths).
  **Severity: MEDIUM.**

### 8. Preflight vs readiness (Pattern 2 / IP-3) — sound; one naming trap (LOW)

- Both sets correctly label preflight a capability snapshot, never readiness, and split
  daemon-reachability from capability-assertion failures. No new pattern risk beyond T4's
  disposition. Note: preflight PASS gives zero coverage of the race window (already
  conceded) — the gate remains reconcile. The only trap: a step named "preflight" whose
  PASS line reads like readiness would violate L9's no-fake-readiness; both sets already
  avoid it. **Severity: LOW.**

### 9. R18 evidence status (must not be over-read)

- The R18 (`33228898244`) readings (exec-manager L105, researcher L8) are
  **coordination-tier**; tier-1 GitHub re-retrieval is still pending, and the shared
  ledger's hosted-evidence row (line 117) still says "NOT established — do not invent it."
  Both T5 sets correctly carry this. The amendment must not be finalized on the
  coordination reading. Additionally, the hosted runner now ships Docker 29.1.* / Compose
  2.40.3 (actions/runner-images#13474, 2026-02) — the exact-marker set was validated
  against Docker 28.x behavior (moby/moby#50750); the marker regex must be re-validated
  and the negative-test matrix re-run against the pinned runner image. **Severity: MEDIUM**
  (marker drift) + carried human question.

### 10. Immutable-requirement check (L1–L9) — no violation in either pattern set, but one process risk

- L1/L2/L4/L5: both sets answer "workflow-design change, not topology change," consistent
  with the ledger. L3/L9: no pattern weakens Task.md, the `2d84d07` reconcile, full split
  topology, real callbacks, mandatory hosted validation, or sole-scheduler; the forbidden
  set (Lite, DinD, socket mounts, privileged/unconfined, `--wait` sole gate, blanket
  retry) is not re-introduced. L7: no code/workflow edits made by any turn. **The only
  ledger-adjacent risk is process-integrity:** the duplicate T5 append (§0) means the
  amendment cannot cite "the T5 contract" without an explicit reconciliation, and the R18
  ledger row must be tier-1-updated before finalization.

### Summary

- **Blocking issues:** (1) PIPESTATUS capture unreachable under `set -euo pipefail` as
  written (Pattern 4/IP-2); (2) the duplicate-T5/process-order defect — one reconciled
  pattern set required before DDAuthor/Exec-Planner consumes T5.
- **High issues:** (3) retry trigger on `rc` alone is defeated by the R15 compose-exit-0
  class; (4) one-shot `on-failure` × `service_completed_successfully` × re-up indefinite
  hang (compose#12134/#10985); (5) seccomp profile described inaccurately as "moby
  default + pivot_root" when it is an ungated ~415-syscall allowlist, with AppArmor/userns
  on Ubuntu 24.04 as the real unproven layer; (6) sandbox-runner env parity still
  unresolved (blocks next hosted run).
- **Mitigable:** marker drift against Docker 29.1 runner image (re-run negative matrix);
  upload `if-no-files-found: warn`; stale `COMPOSE_PARALLEL_LIMIT` floor-2 fallback;
  JWT add-mask; `--no-deps` on batches 3/4.
- **What the Improver must address in T7:** one reconciled pattern set with a
  conflict-resolution table (§0 items 1–4); rewrite the PIPESTATUS idiom as
  `rc=0; … | tee log || rc=${PIPESTATUS[0]}`; classify on "marker in visible output OR
  rc≠0"; bound every compose `up` with `timeout` and classify one-shot state before any
  re-up; state whether batches 3/4 use `--no-deps`; correct the seccomp-profile
  description to the actual JSON and add AppArmor/userns capture; pick the daemon-wait and
  settle-window parameters; decide sandbox-runner gate-or-gated (human call).

## T8 Counter-Improver — Open Risks and Human Questions

**Turn 8 scope (final turn).** I read the full shared file — including, in physical order,
both T5 sets (lines 1056–1505, 1506–1818), **T7 Improver — Final Patterns and Mitigations**
(lines 1819–2235), and **T6 Counter-Improver — Pattern Risk Assessment** (lines 2236–2511),
which I appended after T7 existed. The physical order anomaly is real and is item U8 below.
This turn assesses whether T7's F1–F10 + F-R18 resolve the T6 risk list, produces the final
adversarial risk register, and states the human decisions the amendment still needs. Per
L7: **no code, workflow, DD, or plan edits** — this section is design-decision record only.
All technology claims re-checked against current official/maintainer sources **2026-08-29**
(citations below); anything not independently verifiable is labeled PROVISIONAL.

### Final decision (adversarial verdict)

**Verdict: workflow-only Plan K amendment; NO architecture/topology change.** The
amendment carries F1–F10 + F-R18 (T7's canonical set) subject to the resolutions in this
section. Nothing in the hosted evidence (R10–R18) or in current technology sources
implicates topology: R15 proves an orchestration defect (compose exit 0 with services
Created — fixable in workflow), R16/R17 prove a sandbox seccomp-profile defect (already
amended in P3-S3, workflow-visible), and the R18 coordination reading shows the full split
topology boots with the live-suite blockers being toolchain/test-isolation (source_pkey
UniqueViolation, ModuleNotFoundError), not netns. The sole condition that would re-open
topology: **new hosted evidence** — e.g., tier-1 R18 re-retrieval contradicting the
coordination reading, or the exact anchored marker recurring on a clean runner under the
corrected F1 status contract with the 3-attempt budget exhausted. Per T7 R11/F4, that
outcome argues for F4 escalation (hosted-runner/daemon issue), never more retries, never a
topology change without a new DD (C remains gated). This T8 confirms that posture.

### Addressed risks (T6 → T7 disposition)

1. **Artifact integrity — duplicate T5 + physical out-of-order T5/T5/T7/T6.**
   T7 R1 designates the second T5 (IP-1–IP-10, lines 1506–1818) as canonical and merges
   three first-T5 details (evidence-dir layout, settle-window 60s/5s, daemon-reachability
   120s/5s); the consumer contract (quote F1–F10, never either T5 alone) is sound.
   **However** T7 was written before T6 existed; its "Section-state transparency"
   (lines 1828–1838) asserts "no T6 content exists in this corpus" — **now false**.
   Consumers must read T6 (risks) before T7 (resolutions) despite physical order, and must
   treat T7's resolutions as drafted against the Refiner's eleven-risk dispatch list, not
   against T6's actual text. **Assessment: PARTIALLY RESOLVED — the duplicate-T5 conflict
   is resolved; the physical-order/consumer hazard is NOT (see U8).**

2. **Correct PIPESTATUS idiom under `set -euo pipefail` (T6 §1, BLOCKING).**
   T7 R2/F1 mandates `bash --noprofile --norc -eo pipefail {0}` and "`rc=${PIPESTATUS[0]}`
   captured **on the line immediately after** every compose pipeline". Under `set -e`, a
   bare failing pipeline aborts the script before the capture line executes (GNU Bash
   manual — `set` builtin exception list: the shell exits unless the failing command is in
   a `while`/`until`/`if` condition, an `&&`/`||` list other than the final, a pipeline
   other than the last, or inverted with `!`; checked 2026-08-29). **T7 did not adopt the
   shielding idiom; the BLOCKING flaw survives verbatim.** The retry/reconcile branches
   remain dead code in the exact ON state F1 creates. **Assessment: NOT RESOLVED (U1).**

3. **Classify marker OR nonzero, never `rc` alone (T6 §2, HIGH).**
   T7 F4 (retry predicate = anchored regex present in visible compose output) and F7
   (classified re-up only when the exact regex is in the re-up's visible output; any other
   mismatch = hard failure) close the R15 compose-exit-0 class: the marker triggers the
   retry regardless of `rc`, and the R18 "pipefail OFF" vs "compose exit 0" ambiguity is
   moot because classification no longer depends on `rc`. **Assessment: RESOLVED.**

4. **One-shot restart loops / timeouts / `--no-deps` (T6 §3, HIGH).**
   T7 F5 (first non-zero `State.ExitCode` observed = HARD failure regardless of restart
   policy; inspect `ExitCode`/`RestartCount`/`Restarting`, not `State.Status` alone; every
   engine-level `docker wait` wrapped in `timeout 300`) is well-formed, including the
   restart-loop classifier (ExitCode 0 + RestartCount > 0 = failure). **But** T7 does not
   address the `up`-level hang: `depends_on: service_completed_successfully`
   (`compose.yaml:173,195,197,216,218`) makes any `up` for engine/dashboard/api/worker
   re-trigger the one-shot dependencies and block until they complete — and compose
   re-runs one-shot dependencies on EVERY `up` (docker/compose#10985 maintainer: "All
   `depends_on` conditions will trigger dependent service to be started"; #11808: every
   `up` recreates the one-shot, "20 minutes" per run; #12134 + #8913 + #9273 + #10596:
   hangs with `service_completed_successfully`; all checked 2026-08-29). With
   `restart: on-failure` and no max-retries (`compose.yaml:148,176`), a failing one-shot
   loops forever and batches 3/4's `up` blocks with no timeout (GitHub's 360-min job limit
   is the only bound). `--no-deps` on batches 3/4 (dependencies already satisfied by
   batch 2) and an explicit `timeout` on every compose `up` are **absent from T7**.
   **Assessment: PARTIALLY RESOLVED (U2).**

5. **Exact profile / full split topology and sandbox env parity (T6 §0-4, §6).**
   T7 F3 (four serialized batches, `--profile sandbox` pinned on Batch 4 and every
   full-set reconcile, `COMPOSE_PARALLEL_LIMIT=1` via env, `config --services` topology
   tripwire) resolves the topology-pinning conflict (my T6 §0 item 4). Verified against
   current Docker docs: `COMPOSE_PARALLEL_LIMIT` is "the maximum level of parallelism for
   concurrent engine calls", equivalent to `--parallel`, default `-1`, and "if flags are
   explicitly set on the command line, the associated environment variable is ignored"
   (docs.docker.com compose reference + envvars reference, checked 2026-08-29) — so the
   env-var choice and the =1 value are valid; the stale floor-of-2 fallback is correctly
   dropped. T7 F6 (own-process export of the minted JWT before Batch 4 + mirror to
   `$GITHUB_ENV`; mint failure = named hard failure; sandbox-runner env parity as option a
   with full worker-parity vars, option b documented) resolves the same-step GITHUB_ENV
   trap. Two residuals: (a) option a vs b is explicitly left to human judgment (Q1 below);
   (b) `::add-mask::` on the minted token is not mentioned (minor; LOW). **Assessment:
   RESOLVED at design level; option a/b remains an open human call.**

6. **Daemon preflight vs readiness (T6 §8, LOW).**
   T7 F2 (Class A daemon-reachability bounded wait 120s/5s routed through the SAME
   escalation channel; Class B capability-assertion immediate hard fail; PASS labeled a
   capability snapshot, never a readiness proof; gate remains F7's reconcile) matches the
   T6 disposition exactly, including the L9 no-fake-readiness naming trap. **Assessment:
   RESOLVED.**

7. **Diagnostics/upload/aggregate escalation (T6 §7, MEDIUM).**
   T7 F8 (one `umd-evidence/` dir per run, fixed layout, whole-dir artifact glob,
   capture-diagnostics collection-only under `if: always()`) and F10 (aggregate gate reads
   `escalation-verdict.txt`; verdict absent = FAIL) close the upload-list and gate-read-set
   gaps. Residuals: (a) `if-no-files-found: warn` at `validation.yml:539` is NOT changed to
   `error` — a wrapper that dies before writing the evidence dir still uploads nothing
   "successfully" (the gate still fails closed on the missing verdict, so this is evidence
   loss, not gate bypass); (b) the wrapper is not explicitly required to write
   `escalation-verdict.txt` on every death path including traps. **Assessment: PARTIALLY
   RESOLVED (U5).**

8. **Docker version marker drift (T6 §9, MEDIUM).**
   T7 F4 commits the negative-test matrix and F-R18 carries the re-validation obligation,
   but T7 does not pin or record the runner-image Docker version. New evidence checked
   2026-08-29: runner-images#13474 shipped Docker 29.1.5/Compose 2.40.3 on 2026-02-09;
   runner-images#13682 (containerd v2.2.1 healthcheck regression) forced rollback via PR
   #13708 (2026-02-20) to Docker 28.0.4/Compose 2.38.2; the current Ubuntu 24.04 image
   `20260823.283.1` = Docker 28.0.4, Compose 2.38.2, kernel 6.17.0-1022-azure
   (Ubuntu2404-Readme, checked 2026-08-29); issue #14105 (2026-05-15) tracks a pending v29
   re-update. So the F4 anchored regex currently runs against the SAME 28.x major it was
   validated on, but the version is volatile and a 29.x re-deployment is pending. The
   capability snapshot (`docker-capability.txt`, F2/F8) records versions, but no tripwire
   forces re-validation of the marker regex when the major version changes. **Assessment:
   PARTIALLY RESOLVED (U6).**

9. **R18 tier-1 retrieval (T6 §9).**
   T7 R11/F-R18 correctly upgrades the ledger reading to "corroborated at coordination
   tier, tier-1 GitHub re-retrieval pending" and makes re-retrieval a binding Phase 6 /
   Exec-Manager handoff obligation (AT-10); the ledger row is not finalized until updated.
   One caveat carried: the "pipefail was OFF" inference (exec-manager L105, researcher L8)
   is not directly observable from the coordination reading — compose-exit-0 (R15 class)
   produces the identical observable. F1's explicit contract makes the design independent
   of the inference, but the tier-1 re-retrieval should look for the actual step shell
   invocation to settle it. **Assessment: RESOLVED as a binding obligation (not yet
   executed — by design; blocks amendment finalization, not the workflow direction).**

10. **Sandbox AppArmor/userns distinct from netns (T6 §5, HIGH).**
    T7 R10/F9 (any `statx`/`fsmount`/`getcwd`/`vfork`/`clone`/`unshare` EPERM in sandbox
    logs = security-class failure, fail closed, NEVER consume netns budget; residual
    AppArmor/userns failure is a security-posture design question, never a netns retry)
    adopts the correct classification rule. Residuals: (a) T7 does NOT correct the profile
    misdescription — the actual `deploy/security/sandbox-seccomp.json` is
    `defaultAction: SCMP_ACT_ERRNO` with a single ungated ~415-syscall allowlist including
    `unshare` (line 413), `setns` (340), `mount` (204), `clone3` (46) with NO capability
    gate (re-verified 2026-08-29) — materially closer to `seccomp=unconfined` for
    namespace/mount/ptrace/bpf than "moby default" documentation implies, and no human
    security sign-off is required by T7; (b) F8's `sandbox-security.txt` does not specify
    the fields that would actually diagnose the live layer (sandbox-runner effective user,
    bwrap argv, host AppArmor state). **Assessment: PARTIALLY RESOLVED (U4).**

### Unresolved risks (final register)

- **U1 — PIPESTATUS capture unreachable under `set -e` (BLOCKING).** T7 F1 retains the
  self-defeating idiom. **Mechanism:** a bare failing pipeline exits the script before
  `rc=${PIPESTATUS[0]}` runs (bash `set -e` exception list; checked 2026-08-29). **Trigger:
  exactly the compose-failure condition F1 exists for.** **Blast radius:** the 3-attempt
  budget, classification, and escalation never run; the wrapper dies as a bare hard failure
  with no verdict. **Mitigation:** rewrite F1's status contract as
  `rc=0; docker compose … 2>&1 | tee "$log" || rc=${PIPESTATUS[0]}` (the `||` RHS is
  exempt from `set -e`; `PIPESTATUS[0]` still refers to the compose pipeline), or branch
  inside an `if`/`!` construct. This is a pattern-text fix for DDAuthor/Exec-Planner, not
  a design-direction change.

- **U2 — `up`-level hang and one-shot re-trigger (HIGH).** Compose re-runs
  `service_completed_successfully` dependencies on every `up` (#10985, #11808) and blocks
  on their completion with no timeout (#12134, #8913, #9273). T7's first-exit classifier
  (F5) and `timeout 300` on `docker wait` run AFTER the hanging `up` returns. **Mitigation
  to encode in F3/F5:** batches 3/4 must add `--no-deps` (dependencies satisfied by
  batch 2 — topology unchanged, verified by the F3 tripwire), and every compose `up`
  invocation must be wrapped in an explicit `timeout` with the F4/F5 named escalation.

- **U3 — job-level `defaults: run: shell: bash` blast radius (MEDIUM).** F1 flips the
  docker-e2e job default from `bash -e {0}` to `bash -eo pipefail {0}` (docs.github.com
  workflow-syntax table + actions/runner ADR 0277 + actions/runner#353 + github/docs#23853,
  checked 2026-08-29). Every pre-existing inline step (including pytest/tee steps) gains
  pipefail: pipelines whose tail masked an intermediate failure will now fail — correct
  behavior, but AT-1 does not audit those steps. **Mitigation:** a per-step audit list of
  the docker-e2e job as an amendment step (AT-11).

- **U4 — seccomp profile honesty + security sign-off (MEDIUM/HIGH for posture honesty).**
  The actual profile is an ungated allowlist, not "moby default + pivot_root"; T7 does not
  require honest re-documentation or a human security review, and does not specify the
  AppArmor/userns diagnostic fields. **Mitigation:** re-document the JSON honestly, obtain
  sign-off, and make `sandbox-security.txt` capture effective user / bwrap argv / host
  AppArmor state / profile digest (AT-15). Security-posture decision, not a netns one.

- **U5 — upload `if-no-files-found: warn` + verdict on death path (MEDIUM).** Change to
  `error` for the evidence dir; require the wrapper to write `escalation-verdict.txt`
  before ANY exit including trap paths (AT-14).

- **U6 — marker/version drift (MEDIUM).** Runner image Docker is 28.0.4 today with a
  pending v29 re-update (#14105); the F4 regex must be re-validated against the negative
  matrix whenever `docker-capability.txt` records a Docker major-version change (AT-13).

- **U7 — R18 tier-1 retrieval (OBLIGATION, blocks finalization).** Binding Phase 6 item;
  the shared ledger's "R18 NOT established" row (line 117) must be updated from GitHub
  before the amendment is finalized (AT-10).

- **U8 — artifact order integrity (PROCESS).** T5 duplicate + T7-before-T6 physical order;
  T7's "no T6 exists" statement is now false. The Refiner's final validation must record
  the canonical designation (T7 R1) and instruct consumers to read T6 before T7.

### Hosted evidence cited (exact, R10–R18)

R10/`33226227591` (daemon bind-mount netns marker, live pid), R11/`33226431905` (netns
retry then independent alembic.ini failure), R15/`33227518543` (compose up exited 0,
services Created — reconcile-as-gate), R16/`33228084721` (sandbox `statx`/`fsmount`
EPERM), R17/`33228376245` (sandbox `getcwd`/`vfork` EPERM, sandbox-runner restarting,
`ps -q` false absence), R18/`33228898244` (corroborated at coordination tier: topology
boots, registration PASS, 6 pass/4 FAIL toolchain blockers, marker swallowed by `tee`,
reconcile recovered fail-closed; **tier-1 GitHub re-retrieval pending — do not over-read**).

### Sources re-checked 2026-08-29 (tier / check date)

- [Tier 3] GNU Bash Reference Manual — `set` builtin exception list and `PIPESTATUS`
  (checked 2026-08-29) — basis for U1.
- [Tier 3] docs.docker.com compose CLI reference + envvars reference —
  `COMPOSE_PARALLEL_LIMIT`/`--parallel` semantics, flag-overrides-env (2026-08-29) — T6 §4
  resolved.
- [Tier 3] docker/compose#12134 (open; `--wait-timeout`/`--timeout` do not work with
  `service_completed_successfully`), #10985 (maintainer: every `up` re-triggers the
  dependency), #11808 (one-shot recreated every `up`), #8913/#9273/#10596 (hang family)
  (2026-08-29) — basis for U2.
- [Tier 3] moby/moby#50750 (netns bind-mount marker; 28.x prestart-hook removal),
  containerd/containerd#12141 (same error in CI), moby/moby#46490 (`lstat` class, excluded
  from F4) (2026-08-29) — marker classes.
- [Tier 3] actions/runner ADR 0277 + actions/runner#353 + github/docs#23853 (shell default
  `bash -e {0}` vs explicit `bash --noprofile --norc -eo pipefail {0}`) (2026-08-29) —
  basis for F1/U3.
- [Tier 3] actions/runner-images#13474 (Docker 29.1.5/Compose 2.40.3 shipped 2026-02-09),
  #13682 + PR #13708 (rollback to 28.0.4/2.38.2, 2026-02-20), #14105 (v29 re-update
  pending, 2026-05-15), Ubuntu2404-Readme image `20260823.283.1` (Docker 28.0.4, Compose
  2.38.2, kernel 6.17.0-1022-azure) (2026-08-29) — basis for U6.
- [Tier 3] Docker seccomp docs (capability-gated default allowlist) (2026-08-29) —
  context for U4.
- [Tier 1-local] `deploy/security/sandbox-seccomp.json` (ungated ~415-syscall allowlist,
  `SCMP_ACT_ERRNO`; `unshare`/`setns`/`mount`/`clone3` present without capability gates),
  `deploy/compose.yaml` (restart policies `on-failure` :148,:176; `unless-stopped` :251;
  `service_completed_successfully` :173,:195,:197,:216,:218; sandbox-runner env block
  lacks the three Hatchet vars; `profiles: ["sandbox"]` :235),
  `.github/workflows/validation.yml` (GITHUB_ENV mint :302-303 no add-mask; reconcile
  `|| true` :375-377; aggregate gate :497-509 reads three gate files only; upload list
  :526-539, `if-no-files-found: warn` :539) (all read 2026-08-29).

### Immutable-requirement check (L1–L9) and forbidden set

L1/L2/L4/L5: workflow-design change confirmed, no topology change (this verdict). L3: the
`2d84d07`/`e6b5c3f` reconciles are preserved and strengthened by F5/F7/F8; Task.md not
weakened. L6: adversarial review complete — this log is the record. L7: no code/workflow/
DD/plan edits by any turn, including this one. L8: handoff below. L9: full split Hatchet
topology (F3 pinning + tripwire), real callbacks (F6 real-token registration), mandatory
hosted validation (F7/F10 gates), no skips/stubs/fake readiness (F2 labeling + F5/F7
evidence), no second scheduler (single-owner wrapper; Hatchet sole scheduler). **Forbidden
set re-rejected here, verbatim: Hatchet Lite, DinD/socket mounts,
privileged/unconfined broad bypass, skipping sandbox, optional/trigger-level gate, fake
readiness, second scheduler, host networking, blanket retry, `--wait` sole gate.** U1–U8
introduce none of these; U2's `--no-deps` does not change topology (verified by F3's
tripwire), and U4's options remain bounded (named unconfined for sandbox-runner only, or
documented honest gated OS-isolation) — never blanket bypass.

### Human questions requiring judgment

- **Q1 (blocks next hosted run): sandbox-runner role/env** — option a (mandatory release
  gate, FULL Hatchet env parity with `worker`; T7's canonical default) vs option b (named
  profile-gated capability reported `configured-unavailable`/`gated`, excluded from
  `required_running`). Security-posture/product call (T4 Q2; carried unchanged). Our
  recommendation: option a — the workflow already forces `--profile sandbox` and L9's
  mandatory-sandbox wording; option b must be a conscious, documented decision, never
  silent.
- **Q2 (blocks finalization): R18 tier-1 re-retrieval** — re-fetch `33228898244` from
  GitHub, update the ledger row, diff against exec-manager L105 / researcher L8; settle
  whether the step shell invocation shows pipefail OFF vs compose-exit-0. Binding Phase 6
  obligation (AT-10).
- **Q3: reconcile settle-window** — F7 proposes 60s/5s (T4 Q3). Approve or adjust.
- **Q4: daemon-reachability budget** — F2 proposes 120s/5s (T4 Q4). Approve or adjust.
- **Q5: `COMPOSE_PARALLEL_LIMIT=1` via env** — F3 proposes =1 (T4 Q5); measure wall time
  on the first green runs; record the actual `docker compose version` in
  `docker-capability.txt`.
- **Q6 (NEW, security sign-off): the actual seccomp profile** — the JSON is an ungated
  ~415-syscall allowlist with namespace/mount/ptrace/bpf syscalls ungated by capability:
  either re-document it honestly and have a human security review sign off, or narrow the
  profile — and decide the AppArmor/userns residual (named unconfined for sandbox-runner
  only vs documented honest gated OS-isolation). This is a security-posture decision, not
  a netns one; never a netns retry.
- **Q7 (NEW): `--no-deps` + `timeout` on every `up`** — approve encoding U2's mitigation
  into F3/F5, or consciously accept the #12134/#10985 hang risk with the GitHub 360-min
  job limit as the only bound.
- **Q8 (NEW): job-level shell default audit** — approve the per-step pipefail audit of the
  docker-e2e job (U3/AT-11) as an amendment step before flipping
  `defaults: run: shell: bash`.

### Acceptance evidence (what the amendment must prove)

- AT-1..AT-10 (T7) — with **AT-1 amended**: assert the shielding idiom fixture
  (`false | tee log` under the script's own `bash -eo pipefail` invocation yields
  `rc=1`, the script continues, and the retry branch is reachable) — this is the direct
  regression test for U1.
- **AT-11 (new):** per-step pipefail audit list for the docker-e2e job (U3).
- **AT-12 (new):** batches 3/4 use `--no-deps`; the F3 `config --services` tripwire still
  resolves the full 8-service set for every batch command line (U2 — topology unchanged).
- **AT-13 (new):** `docker-capability.txt` records Docker/Compose versions; a major-version
  mismatch vs the negative-matrix-validated set flags re-validation of the F4 regex (U6).
- **AT-14 (new):** upload uses `if-no-files-found: error` for the evidence dir; a
  wrapper-death fixture (trap path) still produces `escalation-verdict.txt` (U5).
- **AT-15 (new):** `sandbox-security.txt` captures sandbox-runner effective user, bwrap
  argv, host AppArmor state, and the profile digest (U4).
- Phase 6 gate: AT-10 R18 tier-1 re-retrieval + ledger row update (U7).

### Handoff to Refiner / DDAuthor / Exec-Manager (L8)

Distill F1–F10 + F-R18 with the U1–U8 resolutions into the Plan K amendment and the DD
amendment (A + minimal C remains the anchor; workflow-only). **U1 is a pattern-text
correction (shielding idiom) that must land in F1 before DDAuthor writes the amendment.**
U2/U3/U5/U6 require small F3/F5/F8/F10 additions and the new AT-11..AT-15. U7 is a Phase 6
obligation. Q1–Q8 are human decisions; Q1 and Q2 block execution/finalization
respectively. No topology, scheduler, or evidence-surface changes; no code/workflow edits
were made by any turn (L7). Artifacts: this section is the final adversarial risk register;
the T5 duplicate and the T7-before-T6 physical order must be recorded in the Refiner's
final validation (U8). **Decision restated: workflow-only Plan K amendment, no topology
change, unless new hosted evidence proves otherwise (per the conditions in "Final
decision").**
