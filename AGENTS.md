# Agent contract

## Workspace purpose

This repository owns the **Universal Media Decomposer (UMD)**: a provenance-first
Python service that ingests heterogeneous media, preserves evidence and source
locators, derives semantic knowledge, and exposes versioned query/retrieval APIs.
It is infrastructure for downstream systems, not an implementation of a specific
consumer product. Start with [`README.md`](README.md), [`Task.md`](Task.md), and
[`docs/README.md`](docs/README.md).

## Repository map

| Area | Purpose |
|---|---|
| `src/umd/` | Application source, organized by API/application/domain, storage, ingestion and segmentation, extractors and modality pipelines, analysis/resolution/alignment, jobs, projections, providers, provenance, security, and operations. |
| `migrations/` | Alembic schema history applied to the configured database. |
| `schemas/` | Retained, versioned event and API schemas. |
| `tests/` | Unit, storage, API, PostgreSQL, ownership/architecture, recovery, modality, deployment, and end-to-end tests. |
| `docs/` | Architecture, public API, data model, deployment, security, testing, providers, plugins, limits, extensions, runbooks, and examples. |
| `deploy/` | Docker image, Compose topology, startup/migration entrypoint, runtime pins, sandbox policy, and deployment validation. |
| `.github/workflows/` | Hosted validation and container publication policy. |
| `.github/scripts/` | CI preflight, diagnostics, live-worker, engine-proof, and release-evidence scripts. |
| `artifacts/designs/` | Design documents, decomposition material, and cross-plan contracts. |
| `artifacts/plans/` | Pending and completed implementation plans and handoffs. |
| `artifacts/logs/` | Historical agent and execution logs; useful context, not source authority. |
| `artifacts/requests/`, `artifacts/reports/` | Reserved context/report artifact locations; verify current contents before relying on them. |

## Start here by task

| Task | Start with | Also inspect |
|---|---|---|
| Public HTTP/API behavior | `src/umd/api/`, `docs/api.md` | `tests/test_api_contract.py`, `tests/test_api_boundary_e2e.py`, `docs/consistency.md` |
| Source ingestion, evidence, or storage | `src/umd/ingestion/`, `src/umd/storage/`, `src/umd/provenance/` | `docs/architecture.md`, `docs/data-model.md`, `tests/test_separation_ownership.py`, `tests/test_ledger_authority.py` |
| Semantic events, identity, alignment, or reconciliation | `src/umd/domain/`, `src/umd/analysis/`, `src/umd/resolution/`, `src/umd/alignment/`, `src/umd/reconciliation/` | `artifacts/designs/parts/universal-media-decomposer/CONTRACTS.md`, reducer/ledger/replay tests |
| Modality or plugin work | Relevant `src/umd/extractors/`, `audio/`, `video/`, `raster/`, `subtitle/`, or `segmentation/` package | `docs/plugins.md`, `docs/providers.md`, modality contract tests, `docs/security.md` |
| Jobs, reruns, invalidation, or workers | `src/umd/jobs/` | `docs/consistency.md`, `docs/runbooks.md`, `tests/test_production_runner.py`, `tests/test_hatchet_seam.py`, live Hatchet tests |
| Projections, search, or query | `src/umd/projections/` and query/search services | `docs/architecture.md`, `docs/query-search.md`, `tests/test_projection_phase2.py`, `tests/test_active_edge_projection.py` |
| Configuration, migrations, or deployment | `src/umd/config.py`, `.env.example`, `migrations/`, `deploy/` | `docs/deployment.md`, `tests/test_config.py`, `tests/test_migrations.py` |
| Security or untrusted input | `src/umd/security/`, `deploy/security/` | `docs/security.md`, `tests/test_archive_security.py`, `tests/test_sandbox_boundary.py`, `tests/test_no_shell_interpolation.py` |
| CI, image publishing, or release admission | `.github/workflows/validation.yml`, `.github/workflows/container-publish.yml` | `.github/scripts/`, `deploy/Dockerfile`, `deploy/compose.yaml`, `docs/deployment.md` |
| Design or planned implementation work | `artifacts/designs/` and `artifacts/plans/` | `Task.md`, the relevant DD/plan status, and `CONTRACTS.md` |

## Working rules

- Treat the repository as authoritative for implementation state. Verify source,
  tests, workflows, and current artifact status rather than relying on historical
  README counts, log summaries, search indexes, or generated context.
- Preserve the source/evidence/semantic separation and the authority boundaries
  in [`docs/architecture.md`](docs/architecture.md). Use the existing module and
  service seams before introducing parallel infrastructure.
- Settings are environment-driven. Nested pydantic-settings names use the
  double-underscore form documented in [`.env.example`](.env.example), such as
  `UMD_POSTGRES__DSN` and `UMD_OCFL__ROOT`; do not substitute single underscores.
- Treat optional providers and runtime integrations as **GATED** unless the
  capability and target-environment checks prove them active. Do not turn a
  reference implementation or skipped conditional test into release evidence.
- Event schemas, migrations, public API contracts, and cross-plan contracts are
  compatibility surfaces. Read their authoritative documents before changing
  them and preserve replay/idempotency behavior.
- Inspect `git status` before editing and do not overwrite unrelated changes,
  especially artifact logs or plan handoffs.

## Architecture boundaries

- **Authority chain:** OCFL owns immutable source and derived bytes; PostgreSQL
  typed tables own descriptors, membership, segments, and evidence references;
  the append-only semantic ledger is the semantic write authority; Tier-0/Tier-1
  projections are replay-built, disposable read models. See
  [`docs/architecture.md`](docs/architecture.md).
- **Semantic writes:** semantic changes enter through versioned ledger events and
  the command/event path. Do not mutate semantic history in place or write a
  projection directly from an API route, plugin, or provider.
- **Projection ownership:** projection builders are the only writers to their
  projection stores. Replay uses the shared deterministic reducer; projection
  failure must not alter ledger authority.
- **Layer ownership:** API routes handle the public boundary; application
  services own commands and transaction/idempotency seams; domain models own
  invariants; storage owns persistence; `umd.jobs` owns DAG/lineage and stage
  execution adapters. Keep these responsibilities in their existing layers.
- **Scheduling:** Hatchet is the v1 scheduler boundary where enabled; preserve
  the in-repository DAG as the lineage definition and do not add a second
  scheduler or bypass the worker/job adapter.
- **Execution security:** untrusted parsers, archives, media tools, and model
  subprocesses run through the bounded, non-privileged sandbox boundary, not in
  the API process. Sandbox commands use array arguments; archive validation must
  reject traversal, symlinks, ambiguity, and resource-limit violations before
  extraction.
- **Query scope:** v1 graph-like traversal remains bounded typed PostgreSQL
  traversal. Future graph systems are replay-only extensions, never new semantic
  authorities.

## Tooling and exploration

Use this file to narrow the likely subsystem before broad exploration. Prefer the
workspace's indexed, symbol-aware search/outline/read tools for navigation and
call relationships; then verify important conclusions in the actual source and
corresponding tests. Documentation, logs, plans, and search summaries are
pointers, not substitutes for source verification.

For deeper procedures, use the repository's task-specific guidance and skills,
especially the UMD guidance for environment/deployment, ingestion/storage
authority, public HTTP contracts, semantic capabilities, Hatchet scheduling, and
CI/deployment evidence. Do not copy those detailed procedures into this file.

## Validation and tests

The required local completion gate for ordinary source changes is:

```bash
make check                 # ruff + strict mypy + default no-DB pytest suite
```

The individual canonical commands are `make lint`, `make typecheck`, and
`make test`. For database-backed work, use a live PostgreSQL environment and run
at least:

```bash
make migrations-check
UMD_TEST_POSTGRES=true .venv/bin/pytest
```

`make test-postgres` runs the PostgreSQL-marked subset; it is not a substitute
for the full PostgreSQL-enabled suite when the changed behavior crosses the
full integration surface. `make migrate` applies migrations and is an operation,
not by itself a validation result.

Architecture and ownership checks are ordinary pytest modules, notably
`tests/test_production_architecture.py`, `tests/test_separation_ownership.py`,
`tests/test_ledger_authority.py`, and projection/replay tests. Add the relevant
API, security, recovery, modality, or documentation-example tests for the
changed surface. Conditional Docker, Kubernetes, provider, and live-Hatchet
checks are honest environment gates: a skip means that surface was not
validated.

The authoritative hosted matrix is
[`.github/workflows/validation.yml`](.github/workflows/validation.yml). It
includes Ruff, strict Mypy, unit/no-DB tests, PostgreSQL integration, and the
native Compose/live-worker/public-boundary/restart/engine-proof gate. Read the
workflow before changing CI validation or interpreting its results.

## Build, release, and CI

- `deploy/Dockerfile`, `deploy/compose.yaml`, and
  `deploy/docker-entrypoint.sh` define the image, service roles/topology, and
  startup migration behavior. Runtime configuration and credentials are
  injected through the environment or deployment secrets, not baked into the
  image.
- `.github/workflows/validation.yml` is the authoritative hosted validation
  workflow; `.github/scripts/` contains its fail-closed probes and diagnostic
  evidence collection.
- `.github/workflows/container-publish.yml` owns tag/manual publication policy,
  exact-commit validation admission, immutable image publication, SBOM and
  provenance/attestation verification, and digest-based alias promotion. Do not
  treat a local build or skipped live integration as release evidence.
- Dependency/runtime pins and security/license gates live under `pyproject.toml`,
  `deploy/pins/`, and `deploy/security/`; inspect those sources before changing
  release or provider behavior.

## Artifacts, design, and planning

- `Task.md` records the product requirements and durable conceptual model.
- `artifacts/designs/pending/` contains designs whose status must be read before
  treating them as accepted; `artifacts/designs/parts/` contains decomposition
  material and the binding cross-plan contracts at
  `artifacts/designs/parts/universal-media-decomposer/CONTRACTS.md`.
- `artifacts/plans/pending/` and `artifacts/plans/completed/` contain
  implementation-plan lifecycle state. Plans are not a substitute for source
  verification.
- `artifacts/requests/` is the context-snapshot location when request artifacts
  are produced; `artifacts/logs/` is historical process evidence; `artifacts/reports/`
  is for reports. Do not treat logs or reports as normative implementation state.
- No active `artifacts/requirements/` or `artifacts/decisions/` directories were
  found during regeneration; do not assume ASR/ADR infrastructure exists here.

## Security and safety

Read [`docs/security.md`](docs/security.md) and `deploy/security/` before
changing security-sensitive behavior. Untrusted media is hostile input. Preserve
bounded resource limits, non-root/non-privileged sandboxing, archive/path
validation, API read/write authorization, rate limiting, RFC 7807 error
redaction, auditability, and the rule that secrets and model-weight paths are
not committed or embedded in source, documentation, or images.

## Deeper guidance

- Architecture and ownership: [`docs/architecture.md`](docs/architecture.md)
- Public contracts: [`docs/api.md`](docs/api.md), [`docs/query-search.md`](docs/query-search.md), [`docs/consistency.md`](docs/consistency.md)
- Operations and deployment: [`docs/deployment.md`](docs/deployment.md), [`docs/runbooks.md`](docs/runbooks.md), [`docs/observability.md`](docs/observability.md)
- Security and extension boundaries: [`docs/security.md`](docs/security.md), [`docs/plugins.md`](docs/plugins.md), [`docs/limitations.md`](docs/limitations.md), [`docs/extensions.md`](docs/extensions.md)
- Requirements and cross-plan contracts: [`Task.md`](Task.md), [`artifacts/designs/parts/universal-media-decomposer/CONTRACTS.md`](artifacts/designs/parts/universal-media-decomposer/CONTRACTS.md)
- No subordinate `AGENTS.md` files were present at regeneration time. Keep this
  root file repository-wide; add a subordinate contract only when a subsystem
  develops genuinely local rules that should not burden every repository task.
