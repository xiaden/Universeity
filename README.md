# Universal Media Decomposer

Universal Media Decomposer (UMD) is a provenance-first media analysis service
for turning heterogeneous source material into traceable evidence, semantic
claims, and queryable knowledge-graph data.

> **Repository status:** the persistence model, provenance contracts, modality
> libraries, projections, API contracts, recovery tooling, and validation suite
> are implemented. The current in-process API runner is a deterministic
> contract runner; it does not yet compose the modality workers into a
> production decomposition job. See [Known limitations](#known-limitations).

## What this repository guarantees

UMD keeps authority boundaries explicit:

```text
immutable OCFL source bytes
        ↓
typed PostgreSQL evidence and segments
        ↓
append-only semantic ledger + Tier-0 current state
        ↓
disposable replay-built projections
```

- Source bytes are stored by SHA-512 content identity in an OCFL-compatible
  store. Original filenames are metadata, not storage keys.
- Evidence, segments, locators, versions, and provenance are represented in
  typed PostgreSQL tables.
- Semantic events are append-only, versioned, auditable, and replayable.
- Tier-0 state is reduced atomically with its semantic event.
- Search, vector, and current-state projections are rebuildable and are never
  semantic authority.
- Corrections and overrides create new events; invalidation is descendant-only
  and reruns are idempotent.

The codebase includes reference implementations and explicit gates for text,
book/EPUB/PDF, sequential art, raster/OCR, audio/ASR, video, subtitles,
entity resolution, alignment, structured queries, semantic questions, and
hybrid search. Optional production integrations are marked **GATED** rather
than represented as active when they are unavailable.

## Quick start

### Requirements

- Python 3.13 (Python >= 3.12.11 is required by the security policy)
- PostgreSQL for the authoritative and integration-test paths
- `uv` or `pip`, plus the development tools installed by the project

Create an environment and install the project:

```bash
make install
```

Configure a local database and copy the documented settings surface:

```bash
cp .env.example .env
# Edit UMD_POSTGRES__DSN and UMD_OCFL__ROOT for your environment.
make migrate
```

Run the API locally with the ASGI server of your choice, for example:

```bash
uvicorn umd.api.entrypoints:app_factory --factory --reload
```

The versioned API is rooted at `/v1`. OpenAPI is available from the running
application at `/docs` and `/openapi.json`.

## Development commands

```bash
make install          # create .venv and install pinned dependencies
make lint             # ruff
make typecheck        # mypy --strict
make test             # tests that do not require PostgreSQL
make test-postgres    # full PostgreSQL-backed suite
make check            # lint + strict typecheck + default tests
make migrate          # apply Alembic migrations
```

The complete PostgreSQL-backed validation run in this workspace is:

```text
469 passed, 4 skipped, 0 failed
```

The four skips are conditional environment checks for Docker, Kubernetes, and
Tesseract. They are not silently counted as passing container or OCR runtime
validation.

## Repository map

```text
src/umd/
  api/             FastAPI application, routes, schemas, errors, consistency
  application/     ingestion and semantic command services
  domain/          events, entities, segments, locators, predicates
  storage/         OCFL source store and PostgreSQL authority
  ingestion/       source normalization and membership
  extractors/      text, book, PDF, EPUB, and sequential-art extraction
  segmentation/    stable segment identifiers and modality segmenters
  analysis/        confidence, contradiction, temporal/spatial semantics
  audio/           decode, VAD, ASR, filtering, speaker handling
  video/           stream inventory, PTS-native anchors, scene baselines
  subtitle/        independent track parsing and timestamp normalization
  resolution/      reversible entity resolution
  alignment/       many-to-many cross-source alignment
  jobs/            durable job records, DAG contracts, invalidation, recovery
  projections/     replay-built current, search, and vector projections
  models/          provider interfaces and adapters
  security/        sandbox policies and bounded execution
  observability/   logs, metrics, traces, and operational records

migrations/        Alembic migrations 0001–0006
schemas/           versioned event and API schemas
tests/             unit, integration, migration, ownership, API, and E2E tests
  docs/              API, architecture, deployment, providers, observability, and limits
deploy/            Docker/Compose, security posture, pins, and startup scripts
artifacts/         design document, contracts, research, and execution plans
```

## API surface

The `/v1` API provides versioned routes for:

- source ingestion, source details, segments, evidence, and bounded locator
  retrieval;
- entities, claims, corrections, aliases, splits, and alignments;
- jobs, stage events, cancellation, retry, rerun, and operational reports;
- structured queries, semantic questions, hybrid search, and source analysis;
- audit explanations, health/readiness, capabilities, and service version.

See [`docs/api.md`](docs/api.md) for request/response contracts, pagination,
RFC 7807 errors, authentication hooks, rate limits, consistency tokens, and
maintained curl/Python examples in [`docs/examples/`](docs/examples/).

## Deployment and recovery

Deployment material is under [`deploy/`](deploy/). Compose defines the API,
PostgreSQL, OCFL volume, optional model services, and a non-privileged sandbox
profile. Hatchet, pgvector HNSW, Docker/Kubernetes execution, and several model
providers are explicitly **GATED** until their build and runtime requirements
are validated in the target environment.

The recovery package supports PostgreSQL ledger/Tier-0 backup, independent
OCFL inventory and byte restoration, fixity checks, and replay equivalence
validation. See [`docs/deployment.md`](docs/deployment.md),
[`docs/observability.md`](docs/observability.md), and [`docs/runbooks.md`](docs/runbooks.md).

## Known limitations and release gates

This repository should not be described as a fully production-ready media
decomposition deployment yet:

1. **API-to-worker composition is incomplete.** The public source/rerun/retry
   routes currently pass an empty work registry to `SynchronousRunner`, whose
   contract implementation records requested stages as complete without
   invoking modality work. The modality functions exist and are tested as
   libraries, but a production `StageWork` composition is still required.
2. **Optional integrations remain gated.** Bubblewrap/seccomp hardening,
   faster-whisper, pyannote, PyAV, vLLM, splink/DuckDB, vecalign, pgvector HNSW,
   Docker, and Kubernetes require target-environment validation.
3. **OCR runtime is conditional.** The Tesseract adapter is covered by contract
   tests here, but the binary is not installed in every test environment.
4. **CI and release history are not included in this workspace.** Do not claim
   that examples execute in CI until a workflow is added and run on a capable
   host; the current evidence is local test output and static deployment checks.

These limitations are intentionally stated here rather than hidden behind a
green test count. The authoritative requirement and validation record is
[`Task.md`](Task.md), with the design and layer contracts in
[`artifacts/designs/pending/DD-universal-media-decomposer.md`](artifacts/designs/pending/DD-universal-media-decomposer.md)
and [`artifacts/designs/parts/universal-media-decomposer/CONTRACTS.md`](artifacts/designs/parts/universal-media-decomposer/CONTRACTS.md).

## License and security

Review dependency licenses and CVEs before deployment. Do not place secrets in
images or commit them to the repository. See [`docs/security.md`](docs/security.md),
[`deploy/security/`](deploy/security/), and the project dependency policy in
[`pyproject.toml`](pyproject.toml).
