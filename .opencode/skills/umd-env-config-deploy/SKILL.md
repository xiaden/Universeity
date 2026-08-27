---
name: umd-env-config-deploy
description: UMD environment configuration and deployment env-var naming rules — the pydantic-settings nested-name invariant (UMD_POSTGRES__DSN, UMD_OCFL__ROOT, UMD_PROJECTION__*), the alembic os.environ seam, all single/double-underscore references across compose/.env.example/Makefile/entrypoint/tests/docs, the app_factory/build_source_store and /v1/ready 503 test seams. Load when touching env vars, config.py, deploy/, migrations/env.py, or tests that monkeypatch UMD_* vars.
---

# UMD Environment Configuration & Deployment Env Naming

## Mental Model
`src/umd/config.py` is the single authority: `Settings` uses `SettingsConfigDict(env_prefix="UMD_", env_nested_delimiter="__", env_file=".env", extra="ignore")` (config.py:137-142). Nested settings (postgres, ocfl, limits, api, auth, rate_limit, query_cost, consistency, rebuild, projection) therefore REQUIRE double-underscore env names: `UMD_POSTGRES__DSN`, `UMD_OCFL__ROOT`, `UMD_PROJECTION__VECTOR_HNSW_MIN_VERSION`. Single-underscore names (`UMD_POSTGRES_DSN`, `UMD_OCFL_ROOT`) are silently IGNORED (`extra="ignore"`) — defaults apply, no error. There is a second, independent read path: the Alembic seam (`migrations/env.py:24` reads `os.environ.get("UMD_POSTGRES_DSN")` via raw os.environ, bypassing pydantic), pinned by `startup.py:63-64,179-180` and `tests/conftest.py:84-85`. Always grep BOTH paths when renaming.

## Coverage
**Documented:** config.py invariant + all single/double-underscore reference sites (app, deploy, entrypoint, Makefile, .env.example, tests, docs); alembic env seam protocol; app_factory/build_source_store wiring; /v1/ready 503 mechanics; vector_hnsw_min_version dead setting; docs count claims (380 -> 411; 22 -> 23 tables).
**Not yet documented:** whether the amendment wires `vector_hnsw_min_version` into PgHNSWIndex min_version (currently dead); nothing else known.
**Last extended:** 2026-08-27

## Key Findings

### pydantic-settings nested env invariant
- **Location:** `src/umd/config.py:137-142` (Settings.model_config), `:25` dsn default, `:33` ocfl root default `./.ocfl-root`, `:129` vector_hnsw_min_version "0.8.2"
- **What:** `env_nested_delimiter="__"` + `extra="ignore"`. Nested env names are authoritative; wrong names fail silent.
- **Why it matters:** Any env change must use the `__` form or it has zero runtime effect. `test_config.py:20-27` proves the working convention (`UMD_OCFL__ROOT`, `UMD_LIMITS__MAX_UPLOAD_BYTES`).

### Single-underscore defect surface (silently ignored)
- **Location:** `deploy/compose.yaml:23` (UMD_POSTGRES_DSN), `:24` (UMD_OCFL_ROOT), `:29` (UMD_VECTOR_HNSW_MIN_VERSION); `.env.example:16,18-19,24,26`; `deploy/docker-entrypoint.sh:22` (mask); `Makefile:19` (UMD_OCFL_ROOT); `docs/deployment.md:32`; `tests/test_api_contract.py:709`
- **What:** All use single-underscore names pydantic never reads. Consequence: API falls back to default DSN `127.0.0.1:5432/umd` (wrong host inside compose) and default `./.ocfl-root` (bypasses /data/ocfl volume). `cli.py:22` migrate also reads settings -> container migrate also targets default.
- **Correct names:** `UMD_POSTGRES__DSN`, `UMD_POSTGRES__POOL_SIZE`, `UMD_POSTGRES__MAX_OVERFLOW`, `UMD_OCFL__ROOT`, `UMD_OCFL__LAYOUT`, `UMD_PROJECTION__VECTOR_HNSW_MIN_VERSION`, etc.
- **Edge:** `tests/test_deployment_phaseE.py:116` asserts literal `"UMD_POSTGRES_DSN"` in `docker-entrypoint.sh` — renames must update it or the test fails.

### Alembic os.environ seam (second read path)
- **Location:** `migrations/env.py:24`; `src/umd/deploy/startup.py:63-64, 179-180` (pin/restore), `:40-43` UMD_ALEMBIC_INI; `tests/conftest.py:84-85`
- **What:** env.py prefers `os.environ["UMD_POSTGRES_DSN"]` over `get_settings().postgres.dsn`, so run_migrations/conftest pin that env var during `alembic upgrade`. Bypasses pydantic entirely.
- **Why it matters:** Renaming the DSN var requires updating env.py + BOTH pin sites in startup.py + conftest in lockstep — or dropping the os.environ override entirely (cfg.set_main_option already carries the URL in run_migrations).

### app_factory / build_source_store wiring
- **Location:** `src/umd/api/entrypoints.py:19-21` build_source_store (`SourceStore(root=settings.ocfl.root)`), `:24-33` app_factory; `src/umd/api/app.py:57-64` engine_from_settings, `:128-194` create_app
- **What:** app_factory is the zero-arg uvicorn `--factory` entrypoint (`deploy/docker-entrypoint.sh:29`). build_source_store uses the PLAIN SourceStore ctor (assumes initialized root; ignores settings.limits upload caps — conftest fixture sets 512KB/4KB, app defaults 1GB/1MB).
- **Why it matters:** `tests/test_api_contract.py:702-721` monkeypatches the WRONG var `UMD_POSTGRES_DSN` (ignored) and asserts only DB-agnostic /v1/health(200) + /v1/version -> silent false positive that passes against the default DB.

### /v1/ready 503 mechanics (deterministic test seam)
- **Location:** `src/umd/api/routers/system.py:58-72` readiness; `src/umd/api/errors.py:81-86` ConsistencyLagError (status 503); `src/umd/api/consistency.py:41-72` FreshnessSnapshot (paused -> status "rebuild-in-progress")
- **What:** /v1/ready raises `ConsistencyLagError(code="not_ready", retryable=True, x-consistency=rebuild-in-progress, retry_after=settings.consistency.rebuild_retry_after 30.0)` when a projection checkpoint is paused. Pausing pattern: `ProjectionCheckpointStore(engine).save(ProjectionCheckpoint("current_tier1", applied_seq=0).paused(reason, 0))` (test_api_contract.py:232-240).
- **Note:** readiness 503 does NOT call record_503 (unlike ConsistencyGuard in consistency.py:140-150) — no http.503 metric increment.

### vector_hnsw_min_version is a dead setting
- **Location:** `src/umd/config.py:129`; `src/umd/projections/vector.py:37` (PGVECTOR_MIN_VERSION = "0.8.2"), `:242` (min_version param default); `src/umd/api/routers/system.py:82` (`PgHNSWIndex(engine)` w/o min_version)
- **What:** The setting is defined but never consumed; the HNSW gate uses the hardcoded constant. Env var (either spelling) has no runtime effect today. providers.md:33 implies configurability not delivered.

## Critical Invariants
- config.py:137-142 nested delimiter `__` is authoritative — never weaken to accept single-underscore names.
- Secrets never in source: compose/.env.example/entrypoint must keep `${...}` substitution or env injection only.
- /v1/health must keep returning 200 while dependencies degrade (compose healthcheck depends on it — compose.yaml:72-79).
- read-your-writes / 503 classes (transient-lag, rebuild-in-progress) and RFC 7807 problem+json shape must not change.

## Sources
- Files: src/umd/config.py, src/umd/api/entrypoints.py, src/umd/api/app.py, src/umd/api/routers/system.py, src/umd/api/errors.py, src/umd/api/consistency.py, src/umd/deploy/startup.py, src/umd/deploy/cli.py, migrations/env.py, src/umd/projections/vector.py, src/umd/storage/ocfl/store.py, deploy/compose.yaml, deploy/docker-entrypoint.sh, .env.example, Makefile, tests/test_api_contract.py, tests/test_config.py, tests/test_deployment_phaseE.py, tests/conftest.py, README.md, docs/{README,deployment,providers}.md
- Logs: support-researcher L2; support-librarian L4; qa-docs-analyzer L29; qa-reviewer L11; exec-planner L3