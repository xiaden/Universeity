# Universal Media Decomposer — Operational Documentation

This directory documents the Universal Media Decomposer (UMD), a
provenance-preserving media decomposition and semantic knowledge service. Every
document here is written to match the implemented source exactly — the versioned
`/v1` REST surface, the layer-authority invariants, the gated/provider posture,
and the accepted v1 boundaries. Nothing in this documentation implies a
downstream media-generation product: the service is API-neutral infrastructure
for ingesting arbitrary media, deriving evidence, and reconciling semantic
knowledge while preserving traceability to immutable source bytes.

## Layer authority (non-negotiable)

```
OCFL source bytes -> PostgreSQL evidence/segments -> append-only semantic ledger -> disposable projections
     |                            |                          |                          |
 source-native retrieval     typed relational core      audit / reducer          Tier-0 + Tier-1 query/search
```

The append-only PostgreSQL **semantic ledger is the only semantic write
authority**. API commands and workers append versioned events; they never write
graph/search/vector state directly. Tier-0 `current_state` is updated in the
same transaction as an accepted event. Tier-1 projections (exact-search, vector,
current-state) replay the ledger from checkpoints and are blue/green rebuildable.
Projection failure can never erase or alter the ledger. V1 graph-like queries
are bounded typed PostgreSQL traversals — there is no mandatory Neo4j/RDF/vector
database in v1.

## Document map

| Document | Covers |
|---|---|
| [architecture.md](architecture.md) | Layer/module ownership map, data authority table, four-layer pipeline, why projections are disposable |
| [data-model.md](data-model.md) | Typed relational core, append-only event envelope, upcaster policy, provenance, multilingual/adaptation/continuity, temporal/spatial semantics, audit |
| [locators.md](locators.md) | `source://` locator grammar, lifecycle, drift, `@v` versioning, reversible resolution, storage ownership |
| [consistency.md](consistency.md) | Read-your-writes tokens, bounded Tier-1 waiter, 503 classes, DAG/invalidation, overrides/locks |
| [api.md](api.md) | Every `/v1` endpoint: method, path, request/response, headers |
| [query-search.md](query-search.md) | Typed structured + semantic query, exact/fuzzy/hybrid search, pagination, RFC 7807 errors |
| [deployment.md](deployment.md) | Compose topology, Dockerfile, migration, backup/restore/replay, environment configuration |
| [testing.md](testing.md) | Test layers, how to run the suite, live-Postgres vs conditional tests |
| [security.md](security.md) | Sandbox posture, untrusted-input handling, CVE/license watch, auth/rate-limit |
| [observability.md](observability.md) | Structured logs, metrics, spans, per-source reports, `/v1/metrics` |
| [providers.md](providers.md) | Model provider contract, gated vs active providers, substitution |
| [plugins.md](plugins.md) | Authoring plugin stages and modality pipelines behind the stage contracts |
| [fixtures.md](fixtures.md) | Deterministic media fixture generation (no committed binaries) |
| [limitations.md](limitations.md) | Accepted v1 boundaries and honest non-goals |
| [extensions.md](extensions.md) | Deferred extension paths with measured triggers and ownership invariants |
| [runbooks.md](runbooks.md) | Operational procedures: cancel, retry, restart, rebuild, poison, burst, token-wait |
| [examples/](examples/README.md) | Maintained curl + Python client examples (public `/v1` contracts only) |

## Honesty posture

This documentation is disciplined about what is **true** versus what is
**gated/deferred**. Provider entries that require a licensing or build gate
(`faster-whisper`, `pyannote`, `PySceneDetect`, `splink`/DuckDB, `vecalign`,
pgvector-HNSW, `vLLM`, `Hatchet`) are always labeled `GATED` and never described
as active unless the capability endpoint reports them active. Nothing here
fabricates an active authority, provider, or projection that is not actually
running in this deployment.