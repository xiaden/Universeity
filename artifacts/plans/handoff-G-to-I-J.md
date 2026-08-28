# Handoff: Plan G -> Plan I (Hatchet worker) & Plan J (Docker/API boundary)

Status: **DONE** (Plan G Phase 4, P4-S3)
Date: 2026-08-28
Producer: exec-worker (Plan G Phase 4)

This is the authoritative handoff contract for the production registry/runner
construction that Plan G ships, so Plan I's Hatchet worker and Plan J's
Docker/API-boundary workflow can wire against it without re-deriving the
contract. Read `src/umd/jobs/production.py` **fresh** at wiring time — Plan H is
enriching the modality bindings concurrently.

---

## 1. Production runtime/registry construction contract

Canonical module: `src/umd/jobs/production.py`. Two public entry points:

```python
from umd.jobs.production import build_runtime, StageWorkRegistryFactory

runtime = build_runtime(**deps)          # -> ProductionRuntime
registry = StageWorkRegistryFactory.build(runtime)  # -> StageWorkRegistry (Mapping[str, StageWork])
```

### `build_runtime(...)` — the deps it takes (all keyword-only)

`build_runtime(*, engine, **optional)` returns a `ProductionRuntime` dataclass.
**Only `engine` (a SQLAlchemy Postgres engine) is required.** Optional fields
activate the real stage bindings; when absent the stage degrades to a
deterministic, provenance-bearing output derived from committed state (and
records a warning). Fields accepted:

- `engine` — Postgres engine (required; `ConfigurationError` if missing)
- `settings` — `umd.config.Settings` (limits/`raster` read via getattr)
- `source_store` — `umd.storage.ocfl.SourceStore` (get_range reads committed bytes)
- `commands` — `SemanticCommandService` (ledger command path for semantic events)
- `ledger` — `SemanticLedger`
- `segmenters` — dict e.g. `{"txt": segment_txt}`
- `sandbox` — `SubprocessSandboxRunner` (subprocess dispatch seam)
- `dispatch` — sandbox dispatch handler
- `providers` — `ProviderRegistry`
- `builders` — dict of Tier-1 projection builders keyed by `projection_name`
- `replay` — `ReplayDriver`
- `observability` — `StructuredLogger`
- `capabilities` — capability report dict
- `evidence` — `PostgresEvidenceRepository`
- `segments` — `PostgresSegmentStore`
- `artifacts` — artifact store (raster IIIF crops)

`ProductionRuntime.from_mapping(runtime)` coerces a raw dict or an existing
`ProductionRuntime`; a missing `engine` raises `ConfigurationError`.

### `StageWorkRegistryFactory.build(runtime)` semantics

- Composes **all 9 canonical `STAGE_ORDER` stages** (`INGEST`, `FORMAT_ANALYSIS`,
  `BASIC_SEGMENTATION`, `LOW_LEVEL_EXTRACTION`, `STRUCTURAL_ANALYSIS`,
  `ENTITY_RESOLUTION`, `CROSS_SOURCE_ALIGNMENT`, `SEMANTIC_RECONCILIATION`,
  `CURRENT_SEARCH_PROJECTION`) into callable `StageWork` — the same dict shape the
  `DAGRunner` protocol consumes.
- Honours a `'stages'` runtime filter: when present, asserts every canonical
  `STAGE_ORDER` stage is in the provided set; an absent canonical stage raises
  `ConfigurationError` (`ValueError`) — **never a silent success**.
- Stage work reads **committed upstream state only** (by source id / evidence
  refs), writes durable outputs through the ownership boundaries
  (`SegmentRegistry.register`, `PostgresEvidenceRepository.record`, the command
  path for semantic events, `ReplayDriver` for projections), and returns
  provenance-bearing `StageOutcome` refs. No subprocess dispatch in-process
  (sandbox seam owns it); no direct projection writes; semantic events flow only
  through the command path.

`ConfigurationError` is exported from `production.py`.

---

## 2. AppContext wiring (what Plan G assembles in `build_context`)

Module: `src/umd/api/app.py::build_context(settings, engine, source_store) -> AppContext`.

### `AppContext` fields

- `work_registry` field holds the composed production registry
  (`ctx.work_registry`), and is mirrored into `ctx.extra["work_registry"]`.
- `ctx.extra["job_store"]` holds the `PostgresJobRepository`.
- Routers that rerun/retry/invalidate (`rerun_source`, `retry_job`,
  `rerun_segment`) pass `work_registry=ctx.work_registry` (**never `{}`**).

### JobService construction

```python
jobs = JobService(
    store=job_store,                    # PostgresJobRepository(engine)
    runner=runner,                      # DurableDAGRunner(executor=..., store=job_store)
    commands=commands,                  # SemanticCommandService(ledger)
)
```

### Executor dependency wiring — mirror `tests/job_helpers.py::build_executor`

`build_context` wires exactly the real executor shape:

```python
executor = DurableStageExecutor(
    engine=engine,
    commands=SemanticCommandService(ledger),   # SemanticLedger(engine)
    ledger=ledger,
    stage_repo=StageRunRepository(engine),
    audit=JobRunAudit(engine),
    quarantine=PostgresQuarantine(engine),
    retry=RetryPolicy(),
    backoff=RealBackoff(RetryPolicy()),        # job_helpers uses NoWaitBackoff() for tests
)
runner = DurableDAGRunner(executor=executor, store=PostgresJobRepository(engine))
```

For exactness with the in-repo test harness, `tests/job_helpers.py::build_executor`
builds the same executor with `NoWaitBackoff()` and returns
`(executor, ledger)`; `build_context` uses `RealBackoff(RetryPolicy())` for the
production path.

### Planner/lineage

`InvalidationPlanner` over `STAGE_DEPENDENTS` (the sole invalidation lineage)
drives selective rerun. `JobService` defaults `planner=InvalidationPlanner()`
and `lineage=STAGE_DEPENDENTS` when not supplied.

---

## 3. Job lifecycle semantics

- **Submit** creates a durable `PENDING -> RUNNING` job, then
  `DurableDAGRunner.run_graph(...)` iterates `STAGE_ORDER` with dependency-gated
  evidence threading (each stage's manifest carries prior committed outputs as
  `evidence_refs`, feeding the linear evidence-class chain).
- **Executor claim-before-side-effect**: `DurableStageExecutor` claims the stage
  before any side effect, and `SemanticLedger.complete_and_append` commits
  `status=complete + artifact_refs + evidence_refs` in **one atomic** `stage_run`
  UPDATE. `stage_run.evidence_refs` column exists via migration `0007`.
- **Restart replay**: deterministic idempotency — the manifest idempotency
  material is job-independent (`job_id` excluded), so a duplicate/restart does
  NOT repeat committed expensive work (work called once, `replayed=True`,
  single `StageCompleted`).
- **Cancel**: whole-job cancel flips aggregate to `CANCELLED` (durable `break`);
  single-stage cancel marks the stage + transitive descendants cancelled
  (`cancelled_stages` closure), so the runner skips them.
- **Retry** (`retry_job`/`retry`): reschedules only non-complete stages — a failed
  late stage never repeats successful early extraction.
- **Selective rerun** (`rerun_stage`/`rerun_source`): descendant-only invalidation
  via `InvalidationPlanner.plan` over `STAGE_DEPENDENTS`; ancestors/other branches
  untouched.
- **StageQuarantinedError propagation**: deterministic malformed input raises
  `StageQuarantinedError`; the API `_dispatch` surfaces it as RFC 7807 `422`
  `stage_quarantined` (retryable=False); any other dispatch exception is a
  structured `500 dispatch_failed` (retryable=True). Never swallowed.

---

## 4. Interim execution mechanism (what Plan I replaces / keeps)

**Current state (interim, documented in `app.py` docstring):** submission drives
`DurableDAGRunner` **synchronously in the request**. The executor's atomic
`StageCompleted` ledger commits ARE the worker callbacks — a job never reports
completion without durable stage output. This is an interim path ONLY; Hatchet
remains the sole production scheduler.

**Plan I must replace/augment the trigger** with Hatchet worker registration so
jobs execute asynchronously outside the API process. Contract for the Hatchet
adapter (per `HATCHET_RUNNER_CONTRACT` in `src/umd/jobs/hatchet.py`):

- claim-before-side-effect, with a **UNIQUE idempotency_key** authority (dedup
  across concurrent/restarted claims);
- effective-once completion;
- bounded backoff/quarantine;
- restart-resume re-claim keys;
- drain/cancel before a new DAG universe.

Wire via `HatchetWorkerFactory` + `CapabilityReporter`, behind the same
`DAGRunner` protocol seam.

**What Plan I replaces:** the synchronous submit-trigger (the direct
`run_graph` call inside `JobService.submit`/the request path).

**What stays:** the `DAGRunner` protocol seam (`run_graph` signature), the
`DurableStageExecutor` claim/commit ownership, `STAGE_ORDER`/`STAGE_DEPENDENTS`
lineage, the `StageWorkRegistry` shape from `production.py`, the idempotency-key
semantics, and the JobService command facade. `DurableDAGRunner` remains
available as the executor-facing seam / test driver; Hatchet is the v1 scheduler.

---

## 5. Startup assumptions for Plan J (Docker/API boundary)

- **Env vars** — canonical nested-underscore naming:
  - `UMD_POSTGRES__DSN` (Postgres DSN)
  - `UMD_OCFL__ROOT` (OCFL root)
  - `UMD_PROJECTION__VECTOR_HNSW_MIN_VERSION` (pgvector HNSW gating)
- **Migrations**: alembic chain must run through `0007` — which adds
  `stage_run.evidence_refs` (idempotent `ADD COLUMN IF NOT EXISTS`). This column
  is required for atomic stage completion.
- **App entrypoint**: `app_factory()` is a zero-arg entrypoint.
- **Bounded upload**: `settings.limits.max_upload_bytes`, enforced with RFC 7807
  `413 upload_too_large` before any storage side effect.
- **Sandbox limits**: subprocess dispatch goes through the sandbox seam
  (`SubprocessSandboxRunner`); no in-process decoder/model invocation in the API
  process (enforced by the P3-S5 static guards).
- **Ingest forms**: bounded multipart upload (`file` + descriptors) AND the small
  inline-text JSON form (`SourceIngestRequest`). Bytes stored immutably via
  `source_store.put_immutable` BEFORE dispatch; `ocfl_ref` is the URN
  (`urn:umd:ocfl:source:sha512:...`), never the store path.
- **Test wiring**: `api_ctx` fixture = `create_app(engine, source_store, settings)`.
- **Acceptance probes**: the 3 G API contract tests
  (`tests/test_api_contract.py`) are the acceptance gate; the P3-S5 static guards
  are `tests/test_production_architecture.py` (16 tests, no Postgres needed).

---

## 6. Concurrency note

Plans H/I/J edit the shared tree concurrently. `production.py` modality bindings
may be enriched by Plan H (raster/video/audio branches). **Re-read
`src/umd/jobs/production.py` fresh when wiring** — the `build_runtime`/factory
contract above is stable, but the real modality branch implementations it binds
are under concurrent change.

---

## Measured counts (Plan G Phase 4 — current honest numbers)

- Static: **mypy --strict clean on 173 source files**; **ruff clean (src + tests)**.
- Focused Plan G suites: **49 passed** — registry 5 / runner 8 (incl. retry
  acceptance) / architecture 16 / api_contract 20.
- Job-lifecycle suites: **25 passed**.
- Full suite (`UMD_TEST_POSTGRES=true`): **555 passed / 3 failed / 14 skipped**.
  The 3 failures are `tests/test_phase4_heterogeneous_ingestion.py` — concurrent
  Plan H-I spec-first public-API tests (no active scheduler/worker yet), NOT Plan
  G regressions. The 14 skips are honest gates: no Docker/kubectl/tesseract/
  faster-whisper model cache/live Hatchet cluster, plus the Plan J spec-first
  e2e gate (all `active=False` with a `gate_reason`, none paper over failures).
- Defect fixed in Plan G scope: `_is_text_media()` in `production.py` now treats
  `media_kind` in `('text','txt','markdown','md')` as text, so `media_kind="txt"`
  (schema default, `format=None`) routes to the text segmentation branch instead
  of the media branch (was registering 0 segments).

> Fix cycle 2 (QA R2 MINORs M1/M2/M3) landed after these numbers were measured.
> The fixer's re-measured numbers are recorded below (same focused + full gates).

### Fixer re-measured numbers (fix cycle 2, QA R2 MINORs M1/M2/M3)

- Static: **mypy --strict clean on 173 source files**; **ruff clean (src + tests)**.
- Focused Plan G suites: **54 passed** — registry 6 (added M2 structural-digest
  dedup test) / runner 8 / architecture 16 / api_contract 24 (added 4 M1 route
  smoke tests: cancel, retry, segment rerun, RFC 7807 404).
- M1 route smoke tests all green (cancel -> 200 + cancelled, retry -> 200 +
  terminal complete, segment rerun -> 202 + ancestors untouched, unknown job ->
  RFC 7807 404 `not_found`).
- M2 structural-digest assertion green: STRUCTURAL_ANALYSIS evidence rows carry a
  non-null `config_digest` (`umd-txt@1`) and re-record dedups via
  `uq_evidence_identity` (created=0, DB count stays 1).
- Full suite not re-run by the fixer (localized changes to evidence digest + tests
  + docs; the 3 full-suite failures are concurrent Plan H-I spec-first tests, see
  the measured counts above).
