# Deployment and Operations

## Container

`deploy/Dockerfile` builds a single image (`python:3.13-slim`, non-root `umd`
user, `EXPOSE 8080`) from `pyproject.toml` pins + `alembic.ini` + `migrations`
+ `src`. It embeds **zero credential literals**; all runtime configuration is
injected via environment / Docker secrets / a mounted `.env`. The same base
image serves roles selected by container command:

- `api` — the FastAPI `/v1` service (UMD_ROLE `api`).
- `worker` — executes decomposition stages (connects to Hatchet).

`deploy/docker-entrypoint.sh` applies migrations at startup when
`UMD_RUN_MIGRATIONS_ON_START=1` (the compose default), then execs the role.

## Compose topology — `deploy/compose.yaml`

Services:

| Service | Image / role | Notes |
|---|---|---|
| `db` | `pgvector/pgvector:pg18` (target PostgreSQL 18.6 + pgvector >=0.8.2 / 0.8.6) | transactional authority; `ocfl-db` volume; healthcheck |
| `api` | local Dockerfile | `UMD_ROLE=api`; `ocfl-data` + secrets volumes; healthcheck on `/v1/health`; port `8080` |
| `worker` | local Dockerfile | `UMD_ROLE=worker`; depends on `db` + `hatchet` |
| `hatchet` | `ghcr.io/hatchet-dev/hatchet:${HATCHET_VERSION:-v0.50.0}` | durable DAG runner; requires `HATCHET_COOKIE_SECRET` + `HATCHET_MASTER_KEY` (exact pin is a build gate) |
| `sandbox-runner` | local Dockerfile (profile `sandbox`) | **non-privileged**: `read_only: true`, `no-new-privileges`, seccomp `sandbox-seccomp.json`, `cap_drop: [ALL]`, tmpfs `/scratch`; `UMD_SANDBOX_PROFILE=documented-validated-nonprivileged` |
| `ollama` | `ollama/ollama:latest` (profile `gpu`) | optional local embedding/LLM host |
| `minio` | `minio/minio:latest` (profile `s3bridge`) | optional S3-compatible OCFL substrate mount |

The `x-umd-api-env` anchor pins the DSN (`db:5432`), OCFL root (`/data/ocfl`),
migration-on-start, the HNSW gate
(`UMD_PROJECTION__VECTOR_HNSW_MIN_VERSION=0.8.2`), and the
**gated** provider switches (`UMD_VLLM_ENABLED`, `UMD_DIARIZATION_ENABLED`,
`UMD_ASR_ENGINE`) — all gated off/by default and enabled only through the `.env`
surface, never compiled in.

Local dev/CI in this sandbox runs PostgreSQL 17 with pgvector 0.8.0 where HNSW
stays gated; the compose target is the 18.6 + 0.8.6 release. Container-level
behavior is validated statically here and by the conditional Docker/K8s
integration tests (skipped, not silently passed, when no daemon is present).

## Configuration surface

All settings are environment-driven (`UMD_` prefix, nested with `__`;
`.env` file supported), defined in `src/umd/config.py`. Nested settings fields
are addressed by the canonical `__` names — e.g. `UMD_POSTGRES__DSN` ->
`settings.postgres.dsn`, `UMD_POSTGRES__POOL_SIZE` / `UMD_POSTGRES__MAX_OVERFLOW`,
`UMD_OCFL__ROOT`, `UMD_PROJECTION__VECTOR_HNSW_MIN_VERSION`. The
single-underscore nesting variant of these names is **silently ignored** by
pydantic-settings (`extra="ignore"`) and never configures a nested field; always
use `__`. Categories: `postgres`
(DSN/pool), `ocfl` (root/layout), `limits` (upload/range/read buffers), `api`
(version, contract_version, CORS), `auth` (api_keys, write_keys), `rate_limit`
(token bucket), `query_cost` (max_limit/default_limit/max_depth/min_confidence),
`consistency` (max_waiters, lag_wait_multiplier, retry_after values), `rebuild`
(max_events/max_seconds/concurrent/min interval), `projection`
(grace period, search limits, HNSW gate, hybrid weight). `legend`: every
constraint is validated (e.g. `lag_budget_seconds <= 1.0`, digest = `sha512`).
See `.env.example`.

## Migrations

Alembic chain (applied `alembic upgrade head`):

| Migration | Purpose |
|---|---|
| `0001_initial_core` | ledger, Tier-0, source/segment/evidence/entity/job/stage core, append-only trigger |
| `0002_jobs` | job/stage-run/audit operational tables |
| `0003_evidence_identity_unique` | evidence identity/uniqueness |
| `0004_projections` | projection checkpoints, search/vector projections |
| `0005_scope_filters` | structured-query scope filter support (continuity/temporal/spatial) |
| `0006_projection_wipe_gate` | transaction-scoped GUC opt-in for the single-writer vector projection wipe-and-replay reset |
| `0007_stage_run_evidence_refs` | authoritative evidence/artifact refs persisted on `stage_run` for atomic durable stage completion |
| `0008_active_semantic_edge` | active multi-edge relationship projection table (replay-built, single-writer) |
| `0009_search_scope` | `search_document` `work_id`/`continuity_id` scope columns for scoped canonical search |

Migrations ship in the image and run against the live DSN at startup — never a
baked offline schema that could silently diverge.

## Backup / restore / replay

- **Source bytes + fixity**: OCFL immutable objects. Backup the storage root
  (or MinIO bucket); restore re-validates sha512 per object.
- **Authority (ledger + operational)**: PostgreSQL. A point-in-time backup of
  the database restores the append-only semantic ledger, Tier-0, and
  operational/job tables.
- **Replay is the repair path**: any Tier-1 projection can be wiped and rebuilt
  from the ledger (`ReplayDriver` + builders); deterministic outputs are
  checksum-equivalent across replays.
- **Restart resumes at the last committed stage** without repeating completed
  stages (effectively-once, from the database key and transaction boundary).

## Rollout / release posture

- Provider/authority extensions are **GATED** (faster-whisper, pyannote,
  PySceneDetect, splink/DuckDB, vecalign, pgvector-HNSW, vLLM, Hatchet exact pin
  v0.50.0). No gate is silently assumed active.
- Release is blocked by any lost provenance path, direct projection write,
  in-place semantic mutation, flattened subtitle track, unresolved authoritative
  poison event, non-reversible merge/split, stale post-correction token read,
  unsafe archive/path escape, missing local model path, failed cross-tier
  correction E2E, failed restore/replay, unreviewed gated model/license,
  unpinned vulnerable parser, or unverified sandbox target.