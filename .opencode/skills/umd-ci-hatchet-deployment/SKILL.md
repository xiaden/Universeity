---
name: umd-ci-hatchet-deployment
description: UMD GitHub Actions CI reality and Hatchet worker/scheduler deployment pins — run 33164294061 job results, the 14 postgres-job failures (python-multipart/ffmpeg/pg_dump/compose-interpolation, all environment defects with uncommitted working-tree fixes), the docker-e2e compose-up failure, the REAL ghcr.io Hatchet image paths (hatchet-engine/hatchet-lite/hatchet-admin/hatchet-migrate vs the WRONG top-level hatchet-dev/hatchet pin in deploy/compose.yaml:104), SDK 1.38.1 ↔ server v0.105.2 pairing reality, the app.py DurableDAGRunner interim wiring that makes test_api_boundary_e2e skip, the CapabilityReporter connectivity-probe gap that keeps the scheduler permanently non-active, and the (now repaired) test_live_hatchet_* live shape tests. Load when debugging CI runs, fixing validation.yml, pinning the Hatchet image, or planning Plan J live-worker validation.
---

# UMD CI & Hatchet Deployment Reality

## Mental Model
CI is a 5-job GitHub Actions workflow (.github/workflows/validation.yml): Ruff lint, Mypy strict, Unit (no DB, `-m "not postgres"`), PostgreSQL integration (postgres:17 service container, full suite), Docker E2E (native compose, no DinD/socket). The Hatchet worker is a GATED candidate subsystem: SDK 1.38.1 + server v0.105.2 are pinned but the production API still runs on the in-process DurableDAGRunner, so /v1/capabilities NEVER reports an active scheduler and the public-boundary E2E skips. The compose pin `ghcr.io/hatchet-dev/hatchet` is WRONG — the real public images live at sub-paths.

## Coverage
**Documented:** run 33164294061 job conclusions; all 14 postgres-job failure root causes; working-tree-uncommitted fixes; docker-e2e step-6 failure; ghcr.io image-path reality; SDK/server release pairing; API runner wiring; defective live tests; follow-up verification 2026-08-28 (live manifest probes for all 5 sub-path images at v0.105.2; SDK 1.38.1 ClientConfig env surface incl. HATCHET_CLIENT_HOST_PORT + JWT-only token; lite vs split topology env requirements; cli.py :7070 host_port hardcode vs lite 7077; validate_hatchet_live.sh URL/port assumptions; hatchet.py:56 wrong image path; working-tree fix safety verdict).
**Not yet documented:** the actual docker-e2e step-6 error text (log not captured locally; API shows only step conclusion); exact v0.105.2-tag env surface (keyset-file vs SERVER_ENCRYPTION_MASTER_KEY; SERVER_MSGQUEUE_KIND=postgres validity) — must be read from the v0.105.2 tag docs/compose, not current docs.
**Last extended:** 2026-08-28 (repair-research follow-up)

## Key Findings

### CI run 33164294061 job results (GitHub API, repo xiaden/Universeity)
- Ruff lint: **PASS**; Mypy strict: **PASS**; Unit (no DB): **FAIL**; PostgreSQL integration: **FAIL** (14 failed / 550 passed / 17 skipped); Docker E2E: **FAIL at step 6** ("Build API/worker image and start pinned Compose stack", 36s — immediate, not the 240s worker gate).

### All 14 postgres-job failures are environment/package defects — NOT product-assertion failures
- 7× `python-multipart` missing: `test_api_contract.py::test_multipart_upload_ingest_and_job_completes`, `::test_multipart_missing_file_422`; `test_phase4_heterogeneous_ingestion.py::test_text/image/audio/subtitle_through_public_api`. Root cause: python-multipart==0.0.32 is in the WORKING TREE pyproject.toml + deploy/pins/runtime.txt but was NOT in the committed tree at a6b1a62 (qa-test-analyzer L25 flagged this pre-push). src/umd/api/routers/sources.py calls request.form() for the /v1/sources multipart branch.
- 5× `ffmpeg` missing: `test_phase4_heterogeneous_ingestion.py::test_video_composes_scenes_subtitles_audio_baseline`; `test_production_media_branches.py::test_production_registry_video_branch_commits_scenes_and_subtitles`, `::..._honest_asr_gate_when_unavailable`; `test_video_subtitle_integration.py::test_video_inventory_and_audio_branch`, `::test_embedded_subtitle_tracks_extracted_and_evidence`, `::test_dialogue_video_audio_reaches_asr_and_subtitles_independent`. Hosted runner has no ffmpeg; committed validation.yml has no install step (working tree adds one).
- 1× `pg_dump` missing: `test_separation_ownership.py::test_postgres_backup_restore_boundary` — hardcoded `/usr/lib/postgresql/17/bin/pg_dump` absent on runner; working tree adds conftest `_resolve_pg_bin()` (UMD_PG_BIN > which(pg_dump) > fallback) + postgresql-client-17 install.
- 1× compose interpolation: `test_deployment_phaseE.py::test_docker_compose_config_when_daemon_present` — HATCHET_COOKIE_SECRET/HATCHET_MASTER_KEY unset in test env (`${VAR:?}` in compose.yaml); working tree adds env.setdefault. Also fails in the Unit job (not postgres-marked).

### docker-e2e step-6 failure = WRONG ghcr.io image path (GENUINE deployment gap)
- deploy/compose.yaml:104 pins `ghcr.io/hatchet-dev/hatchet:${HATCHET_VERSION:-v0.105.2}` — the TOP-LEVEL image is **403 DENIED / nonexistent** on ghcr.io (verified via token+manifest probes; astral-sh/uv control gets a token, hatchet-dev/hatchet does not).
- The REAL public images (all 200 OK, v0.105.2 tag exists): `ghcr.io/hatchet-dev/hatchet/hatchet-engine:v0.105.2`, `hatchet-lite`, `hatchet-admin`, `hatchet-migrate` (per official docs.hatchet.run/self-hosting/docker-compose).
- SDK/server pairing is REAL: hatchet-sdk==1.38.1 on PyPI (2026-08-25, requires-python <4,>=3.10); server v0.105.2 is a real GitHub release (2026-08-25T15:54:16Z, "Hatchet 0.105.2" binary assets); py/1.38.1 tag exists in the same repo. Both released same day — contemporaneous pair, but still unproven end-to-end (no live cluster test yet).

### API still wires DurableDAGRunner — boundary E2E skips even when compose is up
- src/umd/api/app.py:167-168 wires `DurableDAGRunner(executor=..., store=job_store)` — the interim in-process runner, NOT ProductionDAGRunner/Hatchet.
- src/umd/jobs/capability.py: scheduler status ∈ {gated, configured-but-unavailable, disabled, reference-only, active}; NEVER active without a live reachable cluster (lines 13-17, 66-79).
- tests/test_api_boundary_e2e.py `_require_production_path` (lines ~113-136) SKIPS unless /v1/capabilities reports an active scheduler/worker — so even a green docker-e2e cannot prove the production worker path today. Exec-manager log L82 note (a) confirms: rewire to ProductionDAGRunner is REQUIRED before release evidence.
- Handoff HATCHET_LIVE_VALIDATION_HANDOFF.md §6: the three `test_live_hatchet_*` shape tests are DEFECTIVE (use _RecordingClient + executor=None → no stage_run rows, callbacks_bound=False); must be repaired (bound real executor + real SDK client) or excluded honestly; primary release evidence = test_boundary_restart_duplicate_retry_and_consistency.

### Handoff §6 DEFECT REPORT is STALE — the 3 live shape tests are ALREADY repaired
- Current committed tests/test_hatchet_live.py (unmodified in the working tree) builds a REAL DurableStageExecutor via `_build_executor(umd_db)` (lines 70-89), a REAL SDK client via `_real_client()` (~291-310: ClientConfig(token=..., host_port=`<url-host>:7070`) default 7070), and polls Postgres with `_poll_until` for stage_run/StageCompleted (lines 920-1006). The handoff §6 "RecordingClient + executor=None cannot pass" report describes the Plan I P4-S1 state and is now FALSE on disk.
- What remains unproven is LIVE EXECUTION: no run has ever executed against a real cluster, so SDK-surface mismatches (task-name namespacing, run_workflow payload shape, gRPC host_port routing) are untested. The honest gate is "run live and fix what surfaces", NOT "rewrite the tests". The CI-repair adversarial log (T1, 2026-08-28) makes the same two corrections.

### CapabilityReporter has NO connectivity probe (active is unreachable by construction)
- src/umd/jobs/capability.py `_scheduler_report()` (lines 46-84) only checks `find_spec("hatchet_sdk")` + env presence; with env+SDK it returns `configured-but-unavailable` (lines 75-84). The docstring claims "a reachable client is the only thing that flips it to active" but NO reachability check exists in code. Consequence: even after rewiring app.py to ProductionDAGRunner against a fully live stack, /v1/capabilities never reports active → test_api_boundary_e2e `_require_production_path` still skips. A real connectivity probe (gRPC admin health / admin roundtrip) is a REQUIRED repair.

### Compose worker service cannot configure OR run (two independent gaps)
- deploy/compose.yaml:81-99 worker service env block has ONLY UMD_ROLE + the umd-api-env anchor — NO UMD_HATCHET_SERVER_URL/UMD_HATCHET_TOKEN/HATCHET_CLIENT_HOST_PORT. .env.example has no UMD_HATCHET_* entries either, so env_file adds nothing. Worker exits 2 "not configured" even when the live gate is ON.
- deploy/Dockerfile runs `pip install .` (base deps only); hatchet-sdk lives in the optional `worker` extra (pyproject.toml:79-81). The worker container image therefore LACKS hatchet_sdk → cli.worker() exits 2 "hatchet_sdk not installed". Dockerfile (or a worker build stage) must install the worker extra.

### Compose hatchet service is non-functional even after the image-path fix
- deploy/compose.yaml:101-111 sets only SERVER_AUTH_COOKIE_SECRET/SERVER_ENCRYPTION_MASTER_KEY; NO DATABASE_URL/msgqueue env, NO hatchet-migrate + hatchet-admin quickstart config bootstrap, NO published ports, NO config volume. Neither the split topology (migrate→admin→engine+dashboard) nor hatchet-lite (needs DATABASE_URL, grpc 7077, dashboard 8888, /config volume) can start from this service as written. Official compose: engine maps 7077:7070 and dashboard 8080:80; lite dashboard 8888 + grpc 7077; token provisioning via `hatchet-admin token create --config /hatchet/config --tenant-id <uuid>` (docs.hatchet.run/self-hosting/docker-compose, checked 2026-08-28 via Context7).

### Uncommitted validation.yml converts the live worker gate to OPT-IN
- Working-tree diff: docker-e2e job gains `UMD_VALIDATE_LIVE_WORKER: "${UMD_VALIDATE_LIVE_WORKER:-false}"`; "Build API image and start pinned Compose stack (db + api)" (up db api only unless true); "Wait for worker/scheduler readiness (gate, opt-in)" with `if: env.UMD_VALIDATE_LIVE_WORKER == 'true'`. This is EXACTLY the anti-pattern the CI-repair DD lists ("weakening the live worker gate by opt-in or excluding worker/hatchet from default Docker E2E"). It is an honest deferral (committed gate could never pass) but per R4/R6/R7 the repair must RESTORE a fail-closed gate with a working topology, not ship the opt-in default.

### Stale docs claims (contradict implemented behavior; Plan J P3 must fix)
- README.md:9-11 + 161-165 claim public routes pass an empty work registry to SynchronousRunner which "records requested stages as complete without invoking modality work" — FALSE: SynchronousRunner (src/umd/api/runner.py) is dead code, zero production imports (verified by grep), banned by test_production_architecture.py; production runs DurableDAGRunner over the real StageWorkRegistryFactory registry.
- README.md:90 "469 passed, 4 skipped" stale (Plan G QA R3 measured 555/3/14; CI 550/14/17); README.md:120 "migrations 0001–0006" stale (0007 exists); docs/providers.md:44 Hatchet row says pin v0.50.0 (stale — candidate v0.105.2) and "in-process runner is the local/job facade" (stale).

### R&D workflow state for the CI repair (R8) — partially complete
- Done (2026-08-28): CI-repair DD stub (problem statement + R1-R6 constraints + anti-patterns, no architecture/decision), adversarial log T1 ideator (approaches A Commit-and-Wire top pick, B Split-Job, C Prove-Then-Run, D Lite; technology validation table), rnd-architect options report.
- NOT done: adversarial T2-T8 (counter-ideator/improver/counter-improver), complexity advisor, estimator, DDAuthor (final DD), PatternEnforcer. rnd-counter-ideator/improver logs dated 2026-08-25 belong to the MAIN DD process, not the CI-repair.

### worker_ready_line honesty invariant
- src/umd/jobs/hatchet.py worker_ready_line returns EXACT string `worker ready: registered {N} Hatchet workflows (candidate, pending Plan J live validation)`; cli.py prints it with flush=True BEFORE the blocking worker.start() (SDK 1.38.1 Worker.start() runs run_forever() and never returns); test_no_fake_gated_ready_claim scans cli.py for bare "worker ready". Wait script greps "worker ready: registered". Never remove the "(candidate, pending Plan J live validation)" suffix while unproven.

## Follow-up Verification (2026-08-28)

### Live image manifests at v0.105.2 — all sub-paths 200 OK
- Probed ghcr.io/v2/hatchet-dev/hatchet/<img>/manifests/v0.105.2: hatchet-lite 200, hatchet-lite-dev 200, hatchet-engine 200, hatchet-admin 200, hatchet-migrate 200. Only the top-level `hatchet-dev/hatchet` path is denied. `hatchet-lite-dev` exists (auth compiled out, fixed worker token) — the CI-friendliest option.

### Topology facts (docs.hatchet.run/self-hosting/docker-compose + /self-hosting/hatchet-lite)
- **Split (production)**: `hatchet-migrate` (needs DATABASE_URL, runs first) → `hatchet-admin` quickstart (generates `/hatchet/config` + certs; env: DATABASE_URL, SERVER_MSGQUEUE_RABBITMQ_URL or SERVER_MSGQUEUE_KIND=postgres, SERVER_AUTH_COOKIE_*, SERVER_GRPC_*, SERVER_INTERNAL_CLIENT_INTERNAL_GRPC_BROADCAST_ADDRESS) → `hatchet-engine` (grpc 7070 default; `--config /hatchet/config`) + `hatchet-dashboard` (8080). RabbitMQ optional.
- **hatchet-lite (single container)**: needs DATABASE_URL (Postgres as DB+msgqueue by default), SERVER_GRPC_BIND_ADDRESS=0.0.0.0, SERVER_GRPC_INSECURE=t, SERVER_GRPC_PORT=7077, SERVER_URL, SERVER_AUTH_COOKIE_*; dashboard 8888, grpc 7077; `/config` volume; docs example does NOT use SERVER_AUTH_COOKIE_SECRET/SERVER_ENCRYPTION_MASTER_KEY (UMD compose's required ${VAR:?} vars come from the split-admin flow, not lite).

### SDK 1.38.1 config surface (sdks/python/hatchet_sdk/config.py + client.py @ py/1.38.1)
- `ClientConfig(BaseSettings)` with env_prefix `HATCHET_CLIENT_` → env var `HATCHET_CLIENT_HOST_PORT` is the correct override name (cli.py:105 checks it — correct).
- `DEFAULT_HOST_PORT = "localhost:7070"`.
- Token REQUIRED and must be a **valid JWT** (must start with `ey`; config.py:263-272; tenant_id is derived from the JWT). `umd-ci-token` (validation.yml default) is NOT a JWT → ClientConfig raises → worker can never register. The live gate needs a real token (dev-image fixed token or `hatchet-admin token create`).
- When `host_port` is not explicitly set, the SDK derives it from the token's `grpc_broadcast_address` JWT claim (config.py:287-288) — but cli.py:104-106 ALWAYS overrides host_port to `<url-host>:7070` unless HATCHET_CLIENT_HOST_PORT is set, so the JWT-derived address is bypassed.
- `Hatchet.__init__(config=ClientConfig)`, `self.admin`, `self.runs` (RunsClient with admin_client()) all exist — matches umd.jobs.hatchet.py's `runs.admin_client().run_workflow` submission path.

### UMD code gaps (concrete, must be coordinated)
- **cli.py:104-106 hardcodes `host_port=<url-hostname>:7070`** → breaks hatchet-lite (grpc 7077 per docs example) and breaks split topology when the URL host is the dashboard (not the engine). Fix options: set `HATCHET_CLIENT_HOST_PORT=<engine-host>:<port>` in compose worker env, or configure lite with SERVER_GRPC_PORT=7070, or drop the override and rely on the JWT broadcast claim (requires correct SERVER_GRPC_BROADCAST_ADDRESS at token-issue time).
- **validate_hatchet_live.sh:29 default `UMD_HATCHET_SERVER_URL=http://hatchet:8080`** assumes dashboard-on-8080 topology; lite dashboard is 8888; split dashboard is a separate service. URL hostname feeds cli.py's host_port derivation, so URL choice and topology must agree.
- **src/umd/jobs/hatchet.py:56 `HATCHET_SERVER_IMAGE` still the WRONG top-level path** and is surfaced as `server_image` by /v1/capabilities — must change together with deploy/compose.yaml:104 (P1-S3 pin test enforces cross-surface agreement).
- Current compose `hatchet` service env (only SERVER_AUTH_COOKIE_SECRET/SERVER_ENCRYPTION_MASTER_KEY, no DATABASE_URL, no msgqueue, no config step) matches NEITHER topology — the service is non-functional even after the image-path fix.

### Working-tree fix safety verdict
- python-multipart==0.0.32 VERIFIED real (PyPI 2026-06-04, py3-none-any wheel, requires-python >=3.10, not yanked, Apache-2.0) — safe pin, fixes 7 failures.
- validation.yml ffmpeg + PGDG noble-pgdg postgresql-client-17 + `UMD_PG_BIN` via GITHUB_ENV: sound and correctly ordered (env set before the test step; pg_dump 17 ↔ postgres:17 service match).
- conftest `_resolve_pg_bin()`: sound — `Path(pg_dump).resolve().parent` follows the alternatives symlink to the versioned dir.
- test_deployment_phaseE `env.setdefault` for HATCHET_COOKIE_SECRET/HATCHET_MASTER_KEY: sound, mirrors the CI workflow env, interpolation-only.
- docker-e2e restructure (db+api default; worker gate opt-in `UMD_VALIDATE_LIVE_WORKER`): honest deferral, NOT weakening of a passing gate (step 6 always failed pre-fix). CAVEAT: the opt-in live gate is **guaranteed-fail if enabled today** — compose.yaml:104 image can't be pulled and UMD_HATCHET_TOKEN=umd-ci-token isn't a JWT.

## Critical Invariants
- Do not ship `UMD_VALIDATE_LIVE_WORKER` opt-in as the final posture — the live worker gate must be fail-closed release evidence with a working topology (image path, worker env, SDK install, real JWT token), per CI-repair DD anti-patterns.
- Do NOT add a capability "connectivity probe" that returns active without a real gRPC/admin roundtrip — `active` must require a genuinely reachable cluster (CONTRACTS.md:63).
- The 3 live shape tests are already repaired (real client+executor) — never re-report them as RecordingClient/executor=None defects; the open proof obligation is live execution.
- Do not weaken the HONESTY CONTRACT: no unconditional skips, no stubs replacing real execution, no claiming gated behavior as active; every skip must be a named permitted gate with CI proof (Plan J Problem Statement + DoD matrix rules).
- Worker container env (UMD_HATCHET_SERVER_URL/UMD_HATCHET_TOKEN/HATCHET_CLIENT_HOST_PORT) and Dockerfile worker-extra install are REQUIRED compose/Dockerfile changes; the current worker service/image cannot start under any topology.
- Historical suite must run unmodified/unweakened in CI — the workflow only selects/runs it.
- The hatchet image pin fix must use the correct sub-path (hatchet-engine or hatchet-lite), not the nonexistent top-level path; both SDK and server pins must stay lockstep-bumped with a new DAG universe + drain per handoff upgrade rule.
- Docker E2E must not fake worker readiness; the worker gate only counts when the worker genuinely registers with a reachable cluster.
- UMD_HATCHET_TOKEN must be a real JWT (ey-prefix) for any live run; the umd-ci-token placeholder can never register.
- cli.py host_port, compose worker env (HATCHET_CLIENT_HOST_PORT) and the chosen server topology (lite 7077 vs split engine 7070/dashboard 8080) must be changed together — a URL/port mismatch yields a worker that cannot connect.
- compose.yaml:104 and src/umd/jobs/hatchet.py:56 (HATCHET_SERVER_IMAGE) must be fixed together; the P1-S3 pin test enforces cross-surface agreement and /v1/capabilities surfaces server_image.

## Sources
- CI: run 33164294061 via GitHub Actions API (job+step conclusions); /tmp/postgres-ci.log (test-postgres full output)
- Files: .github/workflows/validation.yml (committed a6b1a62 vs working tree), deploy/compose.yaml, deploy/Dockerfile, deploy/pins/runtime.txt, pyproject.toml, src/umd/api/app.py, src/umd/jobs/capability.py, src/umd/jobs/hatchet.py, src/umd/deploy/cli.py, tests/test_api_boundary_e2e.py, tests/test_hatchet_live.py, tests/conftest.py, tests/test_deployment_phaseE.py, tests/test_separation_ownership.py
- External: ghcr.io token+manifest probes; pypi.org/pypi/hatchet-sdk/1.38.1/json; api.github.com/repos/hatchet-dev/hatchet/releases/tags/v0.105.2; docs.hatchet.run/self-hosting/docker-compose
- Artifacts: artifacts/designs/parts/universal-media-decomposer/HATCHET_LIVE_VALIDATION_HANDOFF.md; artifacts/plans/pending/TASK-universal-media-decomposer-J-api-boundary-ci-release.md
- Logs: support-researcher L3; exec-manager L80-L84; qa-test-analyzer L25-L27
