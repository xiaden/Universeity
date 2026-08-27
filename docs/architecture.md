# Architecture and Ownership

The Universal Media Decomposer is a single modular FastAPI service plus an
optional Hatchet-backed worker, sharing one container image. PostgreSQL is the
transactional authority for source metadata, the deterministic segment registry,
the append-only semantic event ledger, Tier-0 current state, job/stage records,
and the Tier-1 exact-search and vector projections. An **OCFL 1.1-compatible
object store** is the sole authority for immutable source bytes and derived
artifact bytes. A dedicated **sandbox-runner** executes untrusted parsers and
model/extraction subprocesses. Optional local Ollama (and gated vLLM) plus
remote adapters implement the provider contract.

## Four-layer pipeline

```text
OCFL source bytes -> Postgres evidence/segments -> Postgres semantic ledger -> disposable read projections
                         |                         |                         |
                    source-native retrieval   audit / reducer          Tier-0 + Tier-1 query/search
```

1. **OCFL source bytes** — `SourceStore.put_immutable` writes content-addressed
   (sha512) immutable objects; `get_range` returns bounded slices. User
   filenames are never storage keys.
2. **Typed relational core** (Postgres) — source/work/continuity membership,
   segment registry, evidence, entities/mentions, semantic assertions, jobs.
3. **Append-only semantic ledger** — the sole semantic write authority. API
   commands and workers append versioned events; nothing mutates or deletes.
4. **Disposable projections** — Tier-0 `current_state` (same-transaction with
   event append), Tier-1 exact-search and vector projections (replayed from
   checkpoints, blue/green rebuildable). Projection failure cannot alter the
   ledger.

## Deployable topology

```text
             ┌───────────────────────────────────────────────┐
   HTTP ───► │ API container (role=api)                      │
             │  routers → application commands → services    │
             └───────┬───────────────────┬───────────────────┘
                     │ writes            │ reads
        ┌────────────▼──────────┐   ┌────▼──────────────────────┐
        │ PostgreSQL 18.6/17    │   │ OCFL object store         │
        │  ledger + Tier-0/1    │   │  source/derived bytes     │
        │  projections, pgvector│   │  (fs or MinIO-compatible) │
        └───────────────────────┘   └───────────────────────────┘
        ┌───────────────────────┐   ┌───────────────────────────┐
        │ Hatchet worker         │   │ sandbox-runner (opt-in)   │
        │  (gated durable runner)│   │  bubblewrap, non-privileged│
        └───────────────────────┘   └───────────────────────────┘
```

API and worker share one image and scale separately. The sandbox-runner is a
security boundary, not a business service. The design deliberately avoids
service-per-capability microservice decomposition.

## Module ownership map

| Module | Responsibility |
|---|---|
| `umd.api` | FastAPI routers, Pydantic v2 schemas, auth, pagination, RFC 7807 errors, consistency headers, rate limiting |
| `umd.application` | Command handlers, transaction boundaries, idempotency, read-your-writes tokens |
| `umd.domain` | Typed source/work/continuity/edition/segment/evidence/entity/temporal/spatial models, invariants, locator parsing |
| `umd.storage` | OCFL adapter, PostgreSQL repositories, semantic ledger, current-state reducer, artifact references, projection checkpoints |
| `umd.ingestion`, `umd.segmentation` | Content validation, format dispatch, deterministic segmenters |
| `umd.extractors` | Sandboxed text/image/audio/video/subtitle implementations |
| `umd.analysis` | Structural analyzers and semantic event construction |
| `umd.resolution`, `umd.alignment` | Candidate generation, persisted linkage, reversible resolution, many-to-many correspondence |
| `umd.jobs` | In-repository stage DAG/lineage, runner adapter, invalidation planner, stage manifests |
| `umd.models` | `ModelProvider` (completion\|embedding), local/remote adapters, call records |
| `umd.projections` | Single-writer current-state, search, and vector projection builders; bounded relational query |
| `umd.raster`, `umd.audio`, `umd.video`, `umd.subtitle` | Modality pipelines (Phase A/B/C) |
| `umd.provenance`, `umd.audit`, `umd.observability`, `umd.security` | Evidence links, audit explanations, metrics/traces/reports, sandbox/archive policy |
| `umd.recovery`, `umd.deploy` | Independent backup/restore/replay, migration + startup + CLI |

## Data authority / ownership invariants

| Data | Sole authority | Allowed writers / forbidden paths |
|---|---|---|
| Raw source bytes and fixity | OCFL object storage | Ingestion/storage adapter only; never graph/semantic payload blobs; never user filenames as keys |
| Source descriptors, work membership, segment registry, locators | PostgreSQL typed tables | Ingestion/segment command path; no model/provider or projection writes |
| Derived evidence bytes | OCFL derived objects plus Postgres references | Stage artifact writer; the graph never holds the only copy |
| Semantic assertions, alignments, resolution, overrides, locks, invalidation, audit | Append-only Postgres semantic ledger | Command/event path only; no in-place `UPDATE` or direct projection writes |
| Tier-0 winners / entity map | Postgres `current_state` / `current_entity_map` | Same transaction as event append through the shared reducer |
| Exact/vector/search and bounded graph-like reads | Replay-built Postgres projections | Projection builders only; no API mutation path |
| Job/stage execution | Hatchet plus Postgres `stage_run` and `job_run_audit` | Worker/job adapter; semantic lifecycle audit is in Postgres |
| Model/provider configuration | Versioned configuration/registry | Provider adapter; calls never embed provider assumptions in the semantic schema |

## Architectural invariants enforced by tests

- **No projection writes outside builders.** The API boundary never writes a
  projection store; projections are rebuilt explicitly through
  `ReplayDriver`/builders after semantic writes.
- **No direct semantic mutation.** The append-only trigger denies `UPDATE` /
  `DELETE` on `semantic_event` and `embedding`.
- **One reducer.** `reduce_current_state(current_row, event)` is pure, total,
  deterministic, and used by both the append transaction and replay builders —
  so Tier-0 and Tier-1 cannot drift by different logic (a shared-mode risk that
  bounded the design accepts and tests).
- **Refusing to explain the authority as a side effect of a read.** Sources of
  report data are always the operational tables named by the design doc, never
  Tier-0.

## Why projections are disposable

Every Tier-1 projection is a repairable read model. Because the semantic ledger
is complete and append-only, any projection can be wiped and replayed from
`seq=0` and produce a checksum-equivalent result (verified by the replay test
suite). This is why no projection is an authority and why direct projection
writes are forbidden: an authoritative projection would be a second semantic
authority and would recreate the dual-write failure modes the design rejects.