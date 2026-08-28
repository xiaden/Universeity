# Hatchet Live Validation — Plan J Handoff

**Source plan:** `TASK-universal-media-decomposer-I-hatchet-worker-integration.md` (Plan I, Phase 4).
**Owner of execution:** Plan J's hosted GitHub Actions workflow (`.github/workflows/validation.yml`).
**Status:** CANDIDATE pin + procedure handed off. The live Compose run is **GATED** from the local
developer sandbox (no Docker daemon, no Hatchet server, no `UMD_HATCHET_SERVER_URL`/`UMD_HATCHET_TOKEN`).
This document is the exact runnable procedure Plan J executes and the release gate Plan J must fail
if the pinned scheduler does not perform real work.

> **Non-negotiable (DD + Plan I Problem Statement):** Hatchet is the SOLE v1 scheduler. The exact
> SDK/server release is pinned **only after** live retry/cancel/restart shape tests pass against the
> same Compose/CI stack. Local (no-server/no-SDK) capability is `configured-but-unavailable`/`gated` —
> **that is NOT release evidence.** Plan J must fail the release gate if the pinned scheduler does not
> perform real work.

---

## 1. The exact pin (CANDIDATE — PENDING live validation)

| Surface | Value |
|---|---|
| SDK (`hatchet-sdk`) | `==1.38.1` |
| Server image (`ghcr.io/hatchet-dev/hatchet`) | `:v0.105.2` |

Recorded (CANDIDATE / PENDING live validation) in:

- `deploy/pins/runtime.txt` — `hatchet-sdk==1.38.1`, `hatchet-server==0.105.2`
- `pyproject.toml` `[project.optional-dependencies] worker` — `hatchet-sdk==1.38.1`
- `deploy/compose.yaml` hatchet service — `image: ghcr.io/hatchet-dev/hatchet:${HATCHET_VERSION:-v0.105.2}`
- `src/umd/jobs/hatchet.py` — `HATCHET_SDK_VERSION = "1.38.1"`, `HATCHET_SERVER_IMAGE = "ghcr.io/hatchet-dev/hatchet:v0.105.2"`

The SDK line (1.x) and the server line (0.x) are different version lines and may differ numerically;
`test_hatchet_release_pin_is_single_validated_and_agreed` enforces *pair* agreement across all surfaces
and rejects `latest` and the historical `$${` interpolation.

**Upgrade rule (if the candidate fails live validation):** bump BOTH surfaces in lockstep (SDK `1.38.1`
↔ server `v0.105.2`), assign a **new DAG universe**, and **drain in-flight** runs before activating —
never bump one surface alone, never activate without draining.

---

## 2. Worker command

### Compose service (canonical)
`deploy/compose.yaml` `worker` service: same image as `api` (`deploy/Dockerfile`), `command: ["worker"]`,
`UMD_ROLE: worker`, `depends_on: db(healthy) + hatchet(started)`, volume `ocfl-data:/data/ocfl`.

### Container entrypoint
`deploy/docker-entrypoint.sh` `worker` role → `exec python -m umd.deploy.cli worker`.

### Manual invocation (equivalent, for a host worker / debugging)
```bash
export UMD_ROLE=worker
export UMD_HATCHET_SERVER_URL=http://<hatchet-host>:8080   # in-stack default http://hatchet:8080
export UMD_HATCHET_TOKEN=<token>
export UMD_POSTGRES__DSN=postgresql+psycopg://umd:umd@127.0.0.1:5432/umd
export UMD_OCFL__ROOT=/data/ocfl
python -m umd.deploy.cli worker
```
`umd.deploy.cli` has no console-script entry; it is invoked as `python -m umd.deploy.cli <role>`.

---

## 3. Readiness probe

The worker is **ready only** when real callbacks are bound to a `DurableStageExecutor` AND the SDK
client has connected. Signal surfaces:

- **Worker log line (the real readiness signal):**
  `worker ready: registered N Hatchet workflows (candidate, pending Plan J live validation)`
  — returned by `worker_ready_line(count)` in `src/umd/jobs/hatchet.py` and printed by `cli.worker()`
  IMMEDIATELY BEFORE the blocking `client.worker("umd-worker", workflows=handle.registered_workflows).start()`
  call with `flush=True` (manager correction: pinned SDK 1.38.1 `Worker.start()` runs the event loop
  forever and never returns, so printing after it would never emit and the readiness gate would time
  out). `HatchetWorkerFactory.start` collects every `client.task(wf_name)(handler)` binding into
  `WorkerHandle.registered_workflows`, `cli.py` counts from `handle.registered_workflows` and passes
  them via `workflows=`.
- **WorkerHandle gate** (`src/umd/jobs/hatchet.py`): `is_ready()` is `True` only when
  `bool(work_registry) and executor is not None`; with zero bound executors `client.start()` is never
  called and the process exits `2` via `cli.worker()`.
- **API endpoints** (`src/umd/api/routers/system.py`):
  - `/v1/health` — returns 200; `scheduler` `HealthComponent` is `degraded` unless the scheduler is `active`.
  - `/v1/ready` — projection-driven 200/503; surfaces the `scheduler` capability dict additively (never
    flips readiness from the scheduler).
  - `/v1/capabilities` — `scheduler.status` in `{gated, configured-but-unavailable, disabled,
    reference-only, active}`; **never `active`** without a live reachable cluster (`CapabilityReporter`,
    `src/umd/jobs/capability.py`).
- **Unavailable conditions (`cli.worker()` returns structured exit `2`):**
  - missing `hatchet_sdk` → `worker unavailable: hatchet_sdk not installed ...`
  - missing `UMD_HATCHET_SERVER_URL`/`UMD_HATCHET_TOKEN` → `worker unavailable: UMD_HATCHET_SERVER_URL / UMD_HATCHET_TOKEN not configured ...`
  - zero bound executors → `worker unavailable: no stage executors bound ...`

`.github/scripts/wait-for-worker.sh:35` already greps the worker log for **`worker ready: registered`**
and matches the emitted line — **no change needed there**. Do **NOT** grep for `worker started:` (the old,
removed signal; a stale probe would always time out on a correctly-running stack). Plan J must **NOT**
treat the ready line as release evidence until the real-SDK worker loop start is verified against the
pinned pair (`hatchet-sdk==1.38.1` / server `v0.105.2`) — the line is CANDIDATE / PENDING live validation.

---

## 4. Persistent-volume assumptions

Compose named volumes (`deploy/compose.yaml`):

| Volume | Mount | Persists |
|---|---|---|
| `ocfl-db` | `db:/var/lib/postgresql/data` | Postgres data (stage_run / job_run_audit / semantic_event / projections) across api/worker restarts |
| `ocfl-data` | `api`, `worker`:`/data/ocfl` | OCFL immutable-byte store (source objects, derived artifacts, evidence) |
| `umd-api-secrets` | `api:/run/secrets:ro` | API secrets |
| `sandbox-tmp` | sandbox-runner `/tmp` | (sandbox scratch; not a restart-persistence concern) |

**Must NOT be wiped between restart tests:** the `stage_run` rows (incl. `idempotency_key`),
`job_run_audit`, `semantic_event` (`StageCompleted`), and OCFL artifacts. The whole point of the
restart scenario is that these survive `docker compose restart api worker` and that completed expensive
stages are **not** re-executed (idempotency-key dedup, crash-resume, DAG-universe isolation).

> **Teardown note:** `.github/workflows/validation.yml` final step runs `docker compose down -v` (removes
> volumes). That is correct for the *scheduler-shape* run at the very end — but the api/worker **restart**
> mid-suite MUST use `stop`/`start` (NOT `down`/`up`), so the volumes persist across the restart being
> validated. Do not tear down volumes between the duplicate-submission and restart segments.

---

## 5. Failure-artifact commands (run on failure)

```bash
# Compose stack state + per-service logs (worker/api/hatchet/db)
docker compose -f deploy/compose.yaml ps -a
docker compose -f deploy/compose.yaml logs --no-color worker
docker compose -f deploy/compose.yaml logs --no-color api
docker compose -f deploy/compose.yaml logs --no-color hatchet
docker compose -f deploy/compose.yaml logs --no-color db

# Postgres logs + a logical dump (captures stage_run / job_run_audit / semantic_event state)
docker compose -f deploy/compose.yaml exec -T db pg_dump -U umd umd > /tmp/umd-dump.sql
docker compose -f deploy/compose.yaml logs --no-color db

# OCFL volume listing (namaste marker proves the store persisted)
docker compose -f deploy/compose.yaml exec -T api sh -c 'find /data/ocfl -maxdepth 2 | head -200; echo "namaste:"; cat /data/ocfl/0=ocfl_1.1 2>/dev/null || echo "NO NAMASTE"'

# API live probes
curl -fsS http://127.0.0.1:8080/v1/health
curl -fsS http://127.0.0.1:8080/v1/ready
curl -fsS http://127.0.0.1:8080/v1/capabilities

# pytest artifacts
pytest --junitxml=hatchet-live-junit.xml 2>&1 | tee hatchet-live.log
```
`.github/scripts/capture-diagnostics.sh deploy/compose.yaml <out_dir>` already dumps `ps`, per-service
logs, and the `/v1/health|ready|version|capabilities` probes; run it (and upload its `out_dir`) on failure.

---

## 6. Live shape suite invocation

**The three cluster-marked live shape tests** (the Plan I release gate) are in `tests/test_hatchet_live.py`:

- `test_live_hatchet_duplicate_and_restart_preserve_single_completion`
- `test_live_hatchet_retry_and_quarantine_single_authoritative_completion`
- `test_live_hatchet_universe_change_drains_and_rekeys`

They gate on `_require_live_hatchet()` (skip when `UMD_HATCHET_SERVER_URL`/`UMD_HATCHET_TOKEN` absent).
They assert on Postgres `stage_run` uniqueness, exactly one `StageCompleted` per stage, and DAG-universe
rekeying (no cross-universe aliasing).

```bash
export UMD_TEST_POSTGRES=true
export UMD_HATCHET_SERVER_URL=http://hatchet:8080   # in-stack service name
export UMD_HATCHET_TOKEN=<token>
# Full cluster/docker selection in the module:
.venv/bin/pytest tests/test_hatchet_live.py -m "cluster or docker" -q \
  --junitxml=hatchet-live-junit.xml 2>&1 | tee hatchet-live.log
```

**Restart scenario mid-suite** (prove persistence + no repeated committed stages):
```bash
docker compose -f deploy/compose.yaml stop api worker
docker compose -f deploy/compose.yaml start api worker
bash .github/scripts/wait-for-http.sh http://127.0.0.1:8080/v1/ready 240 5
bash .github/scripts/wait-for-worker.sh deploy/compose.yaml worker 240 5   # §3: greps 'worker ready: registered', no probe fix needed
# then re-run the duplicate/restart test (or the whole cluster selection) and assert stage_run rows unchanged
```

### ⚠️ DEFECT REPORT — the three dedicated shape tests cannot pass as written
I verified (Plan I P4-S1) that each of the three `test_live_hatchet_*` tests constructs a
**`_RecordingClient`** (an in-memory transport double) and calls `HatchetWorkerFactory.start(...,
executor=None, client=recording)`, then `worker.submit(...)` and asserts on `stage_run` rows. Two
facts make the tests unable to pass even against a live stack:

1. `submit_workflow_runs` (`src/umd/jobs/runner.py`) only records submissions on the client
   (`client.submit_workflow_run`) — it never invokes callbacks, so **no `stage_run` row is ever written**
   by the recording client.
2. With `executor=None`, `callbacks_bound` is `False` → no callbacks are registered → nothing can
   execute even if a callback were invoked.

Therefore `SELECT ... FROM stage_run WHERE job_id='live-*'` returns zero rows and the assertions
(`len(keys) == len(STAGE_ORDER)`, `n_complete == len(STAGE_ORDER)`, `len(universes) == 2`) fail. These
tests must be **repaired** (bound a real executor and either a real SDK client or a recording client that
invokes callbacks through the durable executor) before they can serve as the live shape gate. Per Plan I
constraints the test file is READ-ONLY in Phase 4, so this is reported — not fixed here. Plan J / the
release gate must treat these three tests as **needing repair** and must NOT treat a false-passing or
vacuously-skipped run as evidence.

**Genuine live-scheduler validation already available:** Plan J's public-boundary E2E
(`tests/test_api_boundary_e2e.py`, `test_boundary_restart_duplicate_retry_and_consistency`) drives the
REAL path end-to-end — HTTP `/v1/jobs` → `ProductionDAGRunner` → real Hatchet client → real worker
container → `DurableStageExecutor` → Postgres/OCFL — and asserts persistence across restart, no repeated
committed stages, and idempotent duplicate submission. **That** is real live validation of the pinned
scheduler and must be the primary release evidence; the dedicated shape tests above are secondary and
must be repaired.

---

## 7. Local (no-server/no-SDK) behavior — NOT release evidence

In the local developer sandbox (no Docker, no Hatchet server, no `UMD_HATCHET_SERVER_URL`/TOKEN):

- `cli.worker()` returns structured exit `2` with an actionable `worker unavailable:` message
  (missing SDK → `hatchet_sdk not installed`; missing env → `UMD_HATCHET_SERVER_URL / UMD_HATCHET_TOKEN
  not configured`). It never prints a ready claim.
- `CapabilityReporter.report().scheduler.status` is `gated` (SDK absent) or `configured-but-unavailable`
  (env absent, or env present but no live connectivity verified) — **never `active`**.
- The three `test_live_hatchet_*` tests SKIP (`no live Hatchet cluster`).

These are **`configured-but-unavailable`/`gated`** states — documented, observable, and correct — but
they are **NOT a successful scheduler validation and NOT release evidence.** Only Plan J's hosted live
run against the pinned Compose stack (real retry/cancel/restart shape tests passing) counts as release
evidence for the scheduler.

---

## 8. Release gate statement

Plan J MUST fail the release gate if any of the following hold:

- The pinned scheduler does not perform real work (live retry/cancel/restart shape tests do not pass
  against the same Compose/CI stack).
- The worker never becomes ready (`wait-for-worker.sh` times out / reports `worker unavailable`).
- Persistent volumes are wiped between restart segments (destroying the persistence/resume evidence).
- The three dedicated shape tests are treated as passed while still defective (§6) or vacuously skipped
  without a live cluster.
