# UMD sandbox-runner host profile (Plan E, P2-S1)

The decomposition pipeline executes untrusted media-processing stages. Sandboxing
is the **only** mechanism that reconciles media extraction with the authority and
security gates. This file documents the VALIDATED sandbox posture and the exactly-one
place a differently privileged posture is permitted.

## Hard rules (apply to every runner, every environment)
1. **Never `--privileged`.** No UMD component uses Docker `privileged: true`, `--privileged`,
   or an equivalent all-capability grant. Bubblewrap executions in-process likewise never
   add privileged capabilities (see `bwrap.build_bwrap_argv`: read-only binds, `--unshare-all`,
   `--die-with-parent`, no capability adds).
2. **No API secrets in images.** The sandbox image and runtime profiles contain zero
   credential values; all secrets are injected by the operator (env / Docker secrets).
3. All sandbox executions are **denied** (not soft-failed) when the isolation primitive is
   unavailable; a denial is observable (`sandbox.denials` metric, see P1-S1).

## Bare-metal / VM profile (primary, first-class — SS.baremetal)
| Setting | Value |
|---------|-------|
| Runtime identity | dedicated unprivileged system user (`umd-sandbox`), no login shell |
| Filesystem | read-only bind of the OCFL root; scratch on tmpfs/memfd (never world-writable) |
| Isolation | Linux user namespace + `unshare` (network/filesystem), via `bubblewrap` (GATED on `probe_capabilities().bubblewrap_available`) |
| Network | none for pure-media stages; documented egress list only for model stages |
| seccomp | restrictive profile (see `deploy/security/sandbox-seccomp.json`) |
| AppArmor | confined profile when deployed under a distro with AppArmor |
| Validation gate | a startup probe proves isolation primitives are present; otherwise sandbox *denials* spike and provider stages refuse to start |

## Container profile (SS.container) — the Compose `sandbox-runner` service
The container profile is deliberately **non-privileged** in the Compose baseline:
read-only root, `no-new-privileges`, `cap_drop: [ALL]`, a tmpfs scratch, seccomp, and a
capability-dropped runtime. This is the *documented validated* posture that the
`security_opt` block in `deploy/compose.yaml` realizes.

> **The one documented exception.** A deployment that requires bubblewrap-over-
> user-namespaces inside a container must add only the **minimal** capability the
> platform actually needs to create user namespaces (e.g. `SYS_ADMIN` on kernels
> with restricted unpriv userns) — **and nothing else**, never a blanket
> `--privileged`/`privileged: true`. That exception is recorded in a per-deployment
> `SANDBOX_HOST_PROFILE` amendment and re-validates the sandbox test suite before
> promotion. If your platform grants unprivileged user namespaces by default
> (common on modern kernels), you do **not** need it at all.

## Validation
- `tests/test_recovery_phaseE.py::test_sandbox_argv_never_privileged` asserts the
  in-process bwrap argv for the media stage never contains `--privileged` and
  `build_bwrap_argv` never grants extra capabilities.
- `tests/test_deployment_phaseE.py::test_compose_sandbox_not_privileged` asserts the
  Compose `sandbox-runner` service does not set `privileged: true`.
- The Bubblewrap sandbox itself is GATED on `probe_capabilities().bubblewrap_available`
  (wired in P1); when unavailable, stages report `policy_denied`, never a silent pass.