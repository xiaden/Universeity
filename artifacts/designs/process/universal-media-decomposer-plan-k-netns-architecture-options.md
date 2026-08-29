# Plan K Netns Failure — Bounded Architecture and Workflow Options

**Status:** `DONE` — workflow-only amendment recommended  
**Date:** 2026-08-29  
**Author:** `rnd-architect`  
**Scope:** Decide whether recurring GitHub Actions Docker network-namespace failures require changing the UMD/Hatchet architecture or only the hosted startup workflow. This report is read-only: it does not edit production code, workflows, or plans.

## Decision

**Decision: do not redesign the UMD or Hatchet topology. Amend Plan K and its hosted workflow contract only.**

Adopt the bounded **hybrid workflow** in Option D:

1. retain the full split Hatchet topology, native hosted Docker engine, real worker callbacks, mandatory sandbox, and one Hatchet scheduler;
2. perform Docker/Compose health and version preflight;
3. start the existing topology in serialized dependency batches;
4. retry only the exact Docker daemon netns marker with a small bounded budget;
5. reconcile every service by status, exit code, restart count, and error/log evidence;
6. collect daemon, network, container, and sandbox diagnostics before teardown; and
7. classify sandbox seccomp/AppArmor/userns failures as independent hard failures, never as transient netns failures.

This is a **Plan K workflow-design amendment**, not a product architecture or deployment-topology change. The current evidence shows a daemon-side namespace lifecycle race amplified by simultaneous startup, plus independent sandbox security/profile failures. It does not show that Compose service topology, Hatchet split topology, or the scheduler choice causes the netns disappearance.

## Immutable constraints

The following remain unchanged in every viable option:

- full split Hatchet topology (`hatchet-migrate`, `hatchet-admin`, `hatchet-engine`, `hatchet-dashboard`);
- Hatchet is the sole v1 scheduler; no second scheduler or in-process release double;
- real SDK client, worker callback registration, callback-owned durable completion, and real stage execution;
- hosted GitHub validation is mandatory and authoritative;
- no skipped mandatory tests, stubs, fake readiness, weakened assertions, or `continue-on-error` on evidence-producing gates;
- no DinD, host Docker socket mount, blanket `privileged`, `seccomp=unconfined`, or blanket AppArmor bypass;
- named Postgres/OCFL volumes survive restart validation; `down -v` is final teardown only;
- `Task.md` §40 items 1–35 remain the release matrix, with no unresolved mandatory `FAIL`.

## Evidence boundary

### Hosted evidence

| Run | Exact observation | Interpretation |
|---|---|---|
| R10 — run `33226227591` | `bind-mount /proc/4009/ns/net -> /var/run/docker/netns/06d21594cf1f: no such file or directory` during roughly ten concurrent default-bridge starts | Docker daemon/container-runtime namespace lifecycle failure before application code. |
| R11 — run `33226431905` | Same netns marker, followed by an independent `alembic.ini` failure | Netns handling must not swallow or relabel unrelated application failures. |
| R15 — run `33227518543` | `docker compose up` returned zero while required services remained `Created` | Workflow must not trust Compose's aggregate exit code; explicit state reconciliation is required. |
| R16 — run `33228084721`, job `99035605497` | Sandbox bwrap hit `statx`/`fsmount` `EPERM` | Independent custom-seccomp/profile failure, not evidence of netns causation. |
| R17 — run `33228376245`, job `99036443345` | No daemon netns marker; `sandbox-runner=restarting`, `getcwd`/`vfork` `EPERM`; `migrate/admin` appeared absent under `ps -q` | Independent sandbox failure plus a workflow observability bug: `ps -q` omitted exited one-shots. |
| R18 — run `33228898244`, job `99037936832` | Topology reached readiness after the moby-default seccomp and `ps -a` reconciliation fixes; one netns marker was recovered by the retry/reconcile path; worker registered 9 workflows; live suite then found host SDK absence and fixed-source uniqueness collisions | Strong evidence that full topology can boot without redesign, while the existing retry wrapper still needs correction and later test failures are not netns failures. |

Sources for the above evidence: `artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-plan-k-netns-workflow.md:94-139`, `artifacts/logs/support-debugger.log.jsonl:L4-L5`, `artifacts/logs/support-researcher.log.jsonl:L6-L8`, and `artifacts/logs/support-librarian.log.jsonl:L19-L20`.

### Repository evidence

- Current workflow startup and reconciliation: `.github/workflows/validation.yml:309-385`.
- Current flow already has a bounded three-attempt intent and exact `bind-mount /proc/` marker: `.github/workflows/validation.yml:315-345`.
- Current reconciliation checks `ps -a -q` and running/exited states, but suppresses reconciliation output and exit status with `>/tmp/compose-reconcile.log 2>&1 || true`: `.github/workflows/validation.yml:346-382`.
- The initial `compose up ... | tee /tmp/compose-up.log` lacks `set -o pipefail`, so the `if` may observe `tee` rather than Docker Compose's exit status; the intended retry branch is therefore not reliable: `.github/workflows/validation.yml:322-341`.
- The current Compose file has no custom network or `network_mode`: `deploy/compose.yaml:37-62,135-221`. The split Hatchet services booted in R11, so a topology change is not supported by the evidence.
- The approved topology and release obligations are fixed by `artifacts/designs/pending/DD-universal-media-decomposer-ci-repair.md:146-195,404-429`, `artifacts/designs/parts/universal-media-decomposer/CONTRACTS.md:58-67`, and `artifacts/plans/pending/TASK-universal-media-decomposer-K-ci-repair-release-gate.md:1-14,46-70`.
- The authoritative product specification remains `Task.md:1641-1692` (DoD 1–35), especially durable restart, Docker deployment, heterogeneous real media, no hidden skips, and final adversarial rerun.

## Root-cause separation

### Docker daemon netns race

The R10/R11 signature names a transient `/proc/<pid>/ns/net` source disappearing while Docker is creating or binding a network namespace under `/var/run/docker/netns`. It occurs during container start, before API, Hatchet, worker, or media code executes. The random transient PID and namespace ID, recurrence during concurrent default-bridge starts, and successful later full-topology boot make a daemon/container-runtime lifecycle race the best-supported classification.

This remains a **workflow reliability and observability problem**: reduce simultaneous starts, retry only the exact marker, and verify resulting state. Retrying must not convert every Compose failure into a transient.

### Sandbox seccomp/AppArmor/userns failure

R16 and R17 are process-level `EPERM` failures inside `sandbox-runner` while bubblewrap starts the worker. They explain crash loops and restart states, not Docker's missing `/proc/<pid>/ns/net` source. The amended Plan K contract already requires the complete Docker/Moby default seccomp allowlist plus required bubblewrap syscalls; R18 shows that this fixed the observed seccomp/getcwd/vfork class sufficiently for the topology to reach worker registration.

AppArmor and user-namespace restrictions remain a separate possible blocker. They must be tested and reported independently. A daemon netns retry is not allowed to retry a sandbox `EPERM`, and a sandbox failure is not evidence that host networking or privileged mode is required.

### Why topology causality is not established

Compose uses its ordinary project bridge network and service-name DNS. R11 demonstrates that the full split topology can start, while R10 demonstrates failure during concurrent creation. No evidence identifies `hatchet-engine`, dashboard, API, or a custom network driver as the source of the namespace disappearance. Replacing the topology would discard the required same-stack proof without addressing the observed daemon lifecycle window.

## Options

## Option A — Keep current retry/reconciliation, with only correctness fixes

### Architecture

- **Layer:** hosted workflow only.
- **Entry point:** `.github/workflows/validation.yml` Docker E2E startup block.
- **New modules:** none.
- **Data flow:** preflight → one full `compose up` → exact-marker retry → `ps -a` state reconciliation → existing readiness/live gates.

### Implementation sketch

Repair the existing wrapper rather than changing its shape: enable `pipefail`, preserve the Compose exit code separately from log capture, remove `|| true` from the retry decision, and retain the exact marker match. Keep the current `ps -a` check, but emit the reconciliation log and fail when the required state is not reached.

### Integration points

| Existing surface | Change | Risk |
|---|---|---|
| `validation.yml:322-345` | Make the current exact-marker retry real | Low |
| `validation.yml:346-383` | Stop hiding reconciliation failure/output | Low |
| Existing live gates | No semantic change | Low |

### Pros

- Smallest change and preserves the approved topology exactly.
- Directly addresses the R15 “Compose exited 0 but containers stayed Created” failure.
- Does not add a new network, scheduler, or release-evidence surface.

### Cons

- Concurrently creates approximately ten containers, preserving the race amplifier observed in R10.
- A single batch makes failures harder to attribute to dependency order.
- It does not independently prove Docker health/version capability before spending the startup budget.
- It can still confuse a service crash, one-shot nonzero exit, or security denial with a generic missing-state retry unless classification is added.

### When to choose

Choose only when minimizing workflow diff is more important than reducing the race window and the hosted runner has demonstrated stable cold-start behavior. This is viable but weaker than the bounded hybrid.

## Option B — Serialized staged startup plus health/version preflight and diagnostics

### Architecture

- **Layer:** hosted workflow orchestration.
- **Entry point:** `.github/workflows/validation.yml` and existing diagnostic scripts.
- **New modules:** no product modules; optionally one workflow helper script for state classification.
- **Batches:**
  1. `docker version`, `docker info`, `docker compose version`, image manifest/digest preflight, and network capability snapshot;
  2. `db`, then `hatchet-migrate` and `hatchet-admin`, requiring health, exit code 0, and generated config;
  3. `hatchet-engine` and `hatchet-dashboard`, requiring engine/dashboard health and the configured gRPC route;
  4. `api`, requiring `/v1/ready`;
  5. `worker` and mandatory `sandbox-runner`, requiring real registration, no restart loop, and no security `EPERM`.

### Implementation sketch

Each batch uses the same exact-marker retry wrapper, but only the affected batch is retried. After every `up`, inspect each container with `docker inspect` for `State.Status`, `State.ExitCode`, `State.Error`, `RestartCount`, and `State.OOMKilled`; retain `docker compose ps -a`, `docker network inspect`, and service logs. A `Created` state after a matching netns marker is recoverable within the bounded budget. `Exited` nonzero, `restarting`, OOM, `EPERM`, invalid config, failed health, and missing one-shot completion are hard failures with no retry relabeling.

### Integration points

| Existing surface | Change | Risk |
|---|---|---|
| `validation.yml` startup block | Replace simultaneous start with dependency batches | Medium: ordering must match config/JWT dependencies |
| `.github/scripts/preflight-hatchet-images.sh` | Run before any container creation; retain digest evidence | Low |
| `.github/scripts/capture-diagnostics.sh` | Add daemon/info/network/state/restart/error evidence | Low |
| Existing readiness/live gates | Remain mandatory and unchanged in meaning | Low |
| `deploy/compose.yaml` | No topology change | None |

### Pros

- Narrows the daemon race window without changing production topology.
- Makes the R15 false-success class and one-shot lifecycle explicit.
- Separates image/daemon problems, migration/config problems, engine routing problems, worker registration, and sandbox security failures.
- Produces evidence useful for deciding whether a future hosted-runner escalation is warranted.

### Cons

- Longer cold-start time and more workflow steps.
- More state-machine logic can itself drift if not kept bounded and tested.
- Health endpoints are not scheduler execution proof; real callback/live gates must still run.
- Does not guarantee the hosted daemon never exhibits the race; it only makes recovery bounded and attribution honest.

### When to choose

Choose when the primary need is to make the existing same-stack release proof deterministic and diagnosable while preserving all immutable constraints.

## Option C — Topology or execution-environment redesign

This option groups materially different proposals because they all change the validated deployment surface or trust boundary.

### Variants

- **Hatchet Lite:** replace the split control plane in CI with the single-container Lite image.
- **Host networking:** use `network_mode: host` or equivalent to avoid a per-container bridge namespace.
- **DinD or Docker socket:** move Compose under a nested daemon or grant a container access to the host daemon.
- **Privileged/unconfined:** grant `privileged: true`, `seccomp=unconfined`, or blanket AppArmor relaxation.
- **Different orchestration shape:** run services outside Compose or add another scheduler/queue.

### Architecture and integration points

These require changes to `deploy/compose.yaml`, `.github/workflows/validation.yml`, credentials/security policy, and the release evidence contract. Lite changes Hatchet ports/config/auth and is explicitly rejected by the approved DD and handoff as sole release evidence. Host networking changes network isolation and port semantics. DinD/socket changes the Docker trust boundary. Privileged/unconfined changes the sandbox security contract. A second scheduler violates the sole-Hatchet constraint.

### Pros

- Could avoid one particular bridge/network-namespace path or reduce service count.
- Lite may start faster; a dedicated runner or alternate daemon may be more reproducible.

### Cons

- No hosted evidence establishes the current split topology as causal; this is speculative remediation.
- Lite proves a different topology (ports, config, auth, persistence/operational behavior) and cannot close the same-stack gate.
- Host networking removes container network isolation and is not a repair for a daemon lifecycle race; it also creates port-collision constraints.
- DinD/socket mounts increase privilege and create a second Docker control boundary; socket mounting exposes the host daemon to the container.
- Privileged/unconfined broad bypass directly contradicts the untrusted-media sandbox requirements in `Task.md:1375-1394` and hides, rather than diagnoses, seccomp/AppArmor/userns defects.
- A different scheduler or topology would invalidate Hatchet callback, restart, auth, migration, and gRPC-routing evidence and violate the immutable ledger.

### When to choose

Only after per-run daemon/runtime evidence proves a persistent hosted-runner limitation that the workflow cannot mitigate, and only through a new approved architectural decision. The current evidence does not meet that threshold.

## Option D — Bounded hybrid workflow amendment (recommended)

### Architecture

- **Layer:** workflow and release-observability design only.
- **Entry points:** `validation.yml` startup block, `preflight-hatchet-images.sh`, `capture-diagnostics.sh`, and Plan K's amended startup contract.
- **Topology:** exactly the existing full split Compose stack.
- **Scheduler:** exactly Hatchet; no alternate execution path.
- **Retry policy:** exact daemon marker only, bounded per batch; no blanket retry.
- **Recovery:** fresh post-attempt reconciliation, with service-class-specific terminal failure.

### Data flow

```text
docker version/info/compose version + image manifests/digests
  -> db health
  -> migrate/admin exited(0) + config volume
  -> engine/dashboard health + gRPC route
  -> api /v1/ready
  -> worker real registration
  -> sandbox no-restart/security checks
  -> live Hatchet callbacks and public HTTP E2E
  -> stop/start persistence
  -> diagnostics and machine-readable release summary
```

### Exact amended workflow contract

1. **Preflight:** record Docker client/server versions, Compose version, runner kernel/security facts available without privileged inspection, exact image references/digests, and default network identity. A preflight failure is a named hard failure.
2. **Serialization:** start only the minimum dependency batch. Do not start API/worker/sandbox until Hatchet config, tenant JWT, engine, and dashboard prerequisites are complete.
3. **Exact retry:** retry only an observed Docker daemon error matching the full netns marker (`bind-mount /proc/<pid>/ns/net -> /var/run/docker/netns/<id>: no such file or directory`, allowing variable PID/ID). Do not retry based on “not running”, timeout, `EPERM`, OOM, invalid config, missing image, nonzero one-shot exit, or generic text.
4. **Exit-code preservation:** use `pipefail` or explicit status capture around `tee`; never allow logging pipelines to turn Compose failure into success. Never hide reconciliation `up` output or status.
5. **Reconciliation:** after each attempt, inspect all required services with `ps -a` plus `docker inspect`. Long-lived services must be `running`, one-shots must be `exited` with exit code 0, and no required service may be `restarting`, `dead`, OOM-killed, or carrying a nonempty daemon error.
6. **State evidence:** record container ID, status, exit code, restart count, error, health status, network membership, and relevant log tail per service. `Created` after the exact daemon marker may be retried; unexplained `Created` is a hard failure.
7. **Security classification:** `statx`, `fsmount`, `getcwd`, `vfork`, `clone`, `unshare`, or related `EPERM` in sandbox logs is a sandbox profile/AppArmor/userns failure. It must fail the run and route to security/profile diagnosis, never consume netns retry budget.
8. **Readiness:** the worker log line is only a candidate signal. The release gate also requires engine-visible nonzero registrations, real callback execution, authoritative Postgres rows, and the public HTTP scenario. No readiness text, version ping, or capability string alone passes.
9. **Mandatory sandbox:** keep `--profile sandbox` and require the sandbox contract; do not make sandbox optional merely to avoid its failure. Any missing sandbox Hatchet environment or restart loop is a release failure to fix, not a skip.
10. **Diagnostics:** run `capture-diagnostics.sh` under `if: always()` before teardown, including `docker info`, `docker version`, Compose state, `docker network inspect`, all service inspect JSON, daemon-visible errors where available, seccomp/AppArmor/userns observations, logs, JUnit, DB dump, OCFL fixity, and gate verdicts.
11. **Teardown:** preserve named volumes through all restart assertions; use `stop/start` for the tested restart and `down -v` only after evidence upload.
12. **Escalation:** if the exact marker exceeds the bounded budget on a clean runner, or recurs after serialized startup, preserve the complete evidence and escalate as a hosted runner/daemon issue. Do not silently enlarge the budget or change topology.

### Integration points

| Existing surface | Change type | Risk |
|---|---|---|
| `validation.yml:242-385` | Staged batches, correct status capture, classified reconciliation | Medium |
| `preflight-hatchet-images.sh` | Add Docker/Compose/network facts beside existing image facts | Low |
| `capture-diagnostics.sh:16-23` | Add inspect/network/daemon evidence; keep helper non-masking | Low |
| `deploy/compose.yaml` | Preserve unchanged topology and security controls | None |
| Plan K P3-S3 / release gates | Amend workflow contract only | Low |

### Pros

- Addresses both known workflow defects: concurrent-start amplification and false success from incomplete state propagation.
- Preserves the exact same-stack full split Hatchet proof and all Task.md obligations.
- Makes netns, one-shot lifecycle, worker failure, and sandbox security failures independently diagnosable.
- Keeps recovery bounded, so repeated daemon instability remains visible rather than becoming an infinite retry.

### Cons

- Most workflow logic of the non-topology options and slower startup.
- Requires careful shell status handling and richer diagnostics.
- A genuine hosted Docker daemon defect may still require runner escalation after the workflow budget is exhausted.
- Does not remove the need to fix non-netns failures already observed in R18 (host SDK provisioning and test fixture idempotency).

### When to choose

Choose when same-stack release evidence is immutable, the failure is pre-application and intermittent, and the goal is deterministic diagnosis without weakening security or gates. Those are the current conditions.

## Tradeoff matrix

Scores are architectural judgments, not runtime measurements. Higher is better; risk is scored as safety (5 = lowest risk).

| Criterion | A: current pattern corrected | B: serialized staged startup | C: topology redesign | D: bounded hybrid |
|---|---:|---:|---:|---:|
| Preserves full split Hatchet evidence | 5 | 5 | 1–3 | 5 |
| Preserves sole scheduler/real callbacks | 5 | 5 | 2–5 | 5 |
| Reduces simultaneous netns race window | 2 | 4 | 3 | 5 |
| Detects Compose false-success states | 4 | 5 | 3 | 5 |
| Distinguishes netns from sandbox/security errors | 2 | 4 | 2 | 5 |
| Security posture | 5 | 5 | 1–3 | 5 |
| Workflow simplicity | 5 | 3 | 1–3 | 3 |
| Diagnostic quality | 2–3 | 4 | 3 | 5 |
| Files/workflow surface touched | ~2 | ~3–4 | ~5–8 | ~3–4 |
| Estimated workflow-only effort | small | medium | not bounded | medium |
| Hosted regression risk (5 = safer) | 3 | 4 | 1–2 | 5 |
| Standalone fit for current release contract | 4 | 5 | 1–2 | 5 |
| **Disposition** | viable, weaker | viable | reject pending new evidence | **recommended** |

## Explicit rejection decisions

| Proposal | Decision | Evidence-based reason |
|---|---|---|
| Hatchet Lite in release CI | Reject | Different ports/config/auth/operational topology; conflicts with same-stack evidence in `HATCHET_LIVE_VALIDATION_HANDOFF.md:10-13,232-241` and DD rejection at `DD-universal-media-decomposer-ci-repair.md:197-205`. |
| Host networking | Reject for this incident | Changes isolation and port semantics without proving it fixes the daemon's namespace lifecycle race; Docker documents that host mode shares the host network namespace. |
| DinD or host socket mount | Reject | Violates approved native-engine boundary and expands the Docker trust boundary; it is not necessary to prove the existing topology. |
| `privileged: true`, seccomp unconfined, blanket AppArmor unconfined | Reject | Masks independent sandbox failures and violates least-privilege/untrusted-media requirements. Narrow, evidence-backed profile changes remain security work, not netns retry. |
| Skip sandbox or make live gate optional | Reject | Directly violates L9, Plan K, Task.md DoD 31/33, and the no-silent-skip contract. |
| Fake readiness, recording client, second scheduler | Reject | Cannot establish real Hatchet callback execution or durable authority. |
| Retry all startup failures | Reject | R11's Alembic failure, R16/R17 security `EPERM`, and R18's later SDK/test failures demonstrate distinct classes that must remain visible. |

## Official technology evidence (checked 2026-08-29)

These are reference citations, not hosted execution evidence.

1. **Docker Compose networking:** Docker documents that Compose creates a default bridge network, services discover one another by service name, and network membership/connectivity should be checked with `docker network inspect` and in-container probes: [Compose networking](https://docs.docker.com/compose/how-tos/networking). This supports preserving service-name networking and adding inspection, not replacing it with host networking.
2. **Docker daemon diagnostics:** Docker's daemon troubleshooting guidance describes disappearing/broken Docker networks as an infrastructure/interface concern and recommends inspecting daemon state/logs: [Daemon troubleshooting](https://docs.docker.com/engine/daemon/troubleshoot/). This supports capturing daemon/network evidence and bounded escalation; it does not establish a UMD topology defect.
3. **Docker seccomp:** Docker documents that the default seccomp profile is a compatibility-oriented allowlist, that `clone`, `setns`, and `unshare` are restricted by default, and that disabling the default profile is not recommended: [Seccomp profiles](https://docs.docker.com/engine/security/seccomp/). This supports treating sandbox `EPERM` as a distinct security-profile diagnosis and rejecting `unconfined` as a blanket fix.
4. **Docker AppArmor:** Docker documents `docker-default` as the default container AppArmor profile and distinguishes container policy from the daemon: [AppArmor profiles](https://docs.docker.com/engine/security/apparmor/). Therefore AppArmor observations must be collected separately from daemon netns errors.
5. **Docker user namespaces/rootless:** Docker documents userns-remap limitations, including interactions with host PID/NET sharing, privileged containers, and volume ownership; rootless mode has additional unsupported features and user-namespace prerequisites: [userns-remap](https://docs.docker.com/engine/security/userns-remap/) and [rootless troubleshooting](https://docs.docker.com/engine/security/rootless/troubleshoot/). This supports not switching to host networking, rootless, or privileged execution speculatively.
6. **Docker host networking:** Docker documents that `network_mode: host` shares the host networking namespace and removes container IP allocation: [Host network driver](https://docs.docker.com/engine/network/drivers/host/). It is therefore a topology/security change, not a neutral retry implementation.
7. **GitHub-hosted execution:** GitHub documents that service containers on hosted Linux runners require explicit port mapping when the job runs directly on the runner, while container jobs use a shared network: [Docker service containers](https://docs.github.com/en/actions/tutorials/use-containerized-services/use-docker-service-containers). This supports keeping the native runner job and making endpoint/port evidence explicit; it does not justify DinD or socket mounts.

## Plan K amendment and Exec-Manager handoff

The next implementation artifact should amend **only Plan K's workflow/release-gate steps**, preserving all product and topology steps:

1. replace the current simultaneous startup with Option D's batch state machine;
2. make `pipefail`/exit-code preservation mandatory around every logged Compose command;
3. keep the exact-marker retry bounded and parameterized, with no generic retries;
4. require `ps -a` plus inspect status/exit/restart/error/health/network evidence;
5. add Docker daemon/version/network diagnostics before and after startup;
6. classify seccomp/AppArmor/userns `EPERM` separately and fail closed;
7. retain full split Hatchet, sandbox, real callbacks, live HTTP, restart persistence, and zero-skipped mandatory gates;
8. push the amended implementation and retrieve a new hosted run. The run URL, SHA, job ID, attempt, logs, and artifacts are the only release evidence.

R18 does **not** close the release gate: it proves the topology/reconciliation direction, but its live suite still failed for host SDK provisioning and fixed-source uniqueness collisions. Those are separate implementation/test repairs and must not be relabeled as netns.

## Final schema

```yaml
status: DONE
decision: WORKFLOW_ONLY_PLAN_K_AMENDMENT
artifact: artifacts/designs/process/universal-media-decomposer-plan-k-netns-architecture-options.md
recommended_option: "D: bounded hybrid workflow amendment"
architecture_change_required: false
topology_change_required: false
preserves:
  full_split_hatchet: true
  real_callbacks: true
  mandatory_hosted_validation: true
  no_skips_stubs_fake_readiness: true
  no_second_scheduler: true
evidence:
  baseline_run: 33164294061
  netns_runs: [33226227591, 33226431905, 33227518543, 33228084721, 33228376245, 33228898244]
  latest_netns_job: 99037936832
  release_gate_closed: false
research_gaps:
  - "Whether the exact marker recurs after serialized batches and corrected pipefail must be established by the next pushed hosted run."
  - "If recurrence survives the bounded workflow budget, obtain runner/daemon-level evidence and escalate rather than changing topology speculatively."
```
