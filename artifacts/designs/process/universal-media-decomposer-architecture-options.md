# Universal Media Decomposer API — Implementation Architecture Options

**Status:** Architecture options analysis  
**Date:** 2026-08-25  
**Author:** `rnd-architect`  
**Authority:** `Task.md` §§1–41  
**Inputs:** `artifacts/designs/process/universal-media-decomposer-technology-research.md`; `artifacts/designs/process/universal-media-decomposer-adversarial-log.md` (T1–T8); `artifacts/logs/support-librarian.log.jsonl`  
**Scope:** Implementation-ready alternatives for a greenfield, API-neutral, provenance-preserving media decomposition service. This report does not implement production code and does not replace the pending DD.

## Executive summary

The architecture must make the four conceptual layers and their ownership explicit:

```text
immutable source bytes  ->  deterministic evidence/segments
                                  ->  provenance-bearing interpretations
                                  ->  query projections / knowledge graph
```

The strongest option is **Option A: Postgres semantic ledger with rebuildable projections**. It puts source bytes in an OCFL layout over object storage, deterministic source/segment truth and an append-only semantic log in PostgreSQL, and treats graph, vector, full-text, and RDF claim-graph stores as disposable projections. A shared pure reducer is used for transactional current-state reads and replay; the graph/vector/search builders are the only writers to their projections. This directly addresses the adversarial findings about dual writes, irreversible merges, projection drift, and audit loss.

The central bet is that the semantic ledger is more valuable as a recoverable authority than a graph engine is as an authority. Deep graph traversal remains available through a projection, while losing or migrating that projection does not lose provenance. The cost is explicit replay/projection operations, event-schema discipline, and a two-tier consistency contract.

Option B (RDF-star/GraphDB authority) is the most native claim/provenance representation but adds a second authoritative system, outbox ordering and drain failure modes, GraphDB Enterprise licensing, and semantic dependence on asserting RDF-star rather than RDF 1.2 triple terms. It is a credible challenger, not the low-risk default.

Option C (XTDB bitemporal authority) buys engine-level time travel but does not provide the proposed recursive graph-query mechanism, and the supplied adversarial review records a serious 2.1 compaction/readability failure while 2.2 remains release-candidate at the check date. It is suitable only as a future witness if its gate is met.

Option D (mutable Neo4j authority plus PostgreSQL changelog) has the best native traversal ergonomics but recreates the dual-write/rebuildability failure mode and puts the non-loss requirement on a single-node, GPLv3 Community Edition deployment. It is rejected as an authority, but Neo4j remains useful as an optional projection in A.

## Decision criteria and scoring

Scores are **1 (poor) to 5 (strong)**; higher is better. Scores are architecture-fit judgments grounded in the supplied research and T1–T8 adversarial record, not benchmark claims. “Migration risk” means risk of later changing the authority or recovering from a store failure; “operational simplicity” includes self-hosting burden and number of independently consistent authorities.

| Criterion | Weight | A: Ledger + projections | B: RDF-star authority | C: XTDB authority | D: Neo4j authority + changelog |
|---|---:|---:|---:|---:|---:|
| Provenance and correction correctness | 20% | 5 | 4 | 4 | 2 |
| Source/evidence/semantic separation | 15% | 5 | 4 | 4 | 3 |
| Selective invalidation and restartability | 15% | 5 | 3 | 3 | 3 |
| Operational simplicity/self-hostability | 15% | 4 | 2 | 2 | 2 |
| Modality/plugin extensibility | 10% | 5 | 4 | 4 | 3 |
| Query/search capability | 10% | 4 | 5 | 2 | 5 |
| Security/isolation | 5% | 4 | 3 | 3 | 3 |
| Scalability and migration risk | 10% | 4 | 3 | 2 | 2 |
| **Weighted total (/5)** | **100%** | **4.65** | **3.55** | **2.90** | **2.75** |

The score does not make A universally best. B should be reconsidered if standards-grade RDF interoperability is a product-defining requirement and production GraphDB Enterprise licensing is acceptable. D should be reconsidered only if graph-native writes are more important than authoritative replayability and an HA/backup-capable licensed graph deployment is funded. C should not be selected as the first authority under the supplied evidence.

## Shared foundation required by every viable option

The following are not optional variants; they are requirements imposed by `Task.md` and remain common infrastructure regardless of the semantic authority.

### API and domain boundaries

- Use an API-neutral source descriptor. Endpoint taxonomy (`/sources/book`, `/sources/video`, and so on) is an adapter, not the domain model.
- Keep `SourceMaterial`, `Evidence`, `Interpretation`, and `KnowledgeGraph` distinct in contracts and persistence.
- Use stable IDs (UUIDv7/ULID policy chosen at implementation time), pagination, structured errors, health, capabilities, and OpenAPI for REST.
- Treat each subtitle track as an independent source/evidence stream with language, disposition, style, timing, speaker labels, SDH/HI markers, signs, songs, and typesetting retained.
- Keep language, edition, translation, adaptation, release, continuity, and work relationships as data. They are not graph/database boundaries.

### Immutable source and deterministic locators

- Write raw uploads to content-addressed OCFL 1.1 objects over filesystem, MinIO, or S3. Never derive storage paths from user filenames.
- Store raw bytes and fixity metadata as source truth; Postgres stores references, not large blobs.
- Represent segment identity using a deterministic structural path plus a versioned locator. The supplied pattern is `source://<work-or-source>/<modality>/<segment-id>@v<locator-version>?frag=<selector>`.
- Use EPUB CFI for EPUB structure, IIIF-style regions for images/pages, and Media Fragments-compatible time/track/region selectors for audio/video/subtitle material. Treat locator stability as bounded by content and decoder/renderer versions, not as magic permanence.
- Re-ingested byte-different variants emit `SourceAliased`/work-membership records. Rebase references through explicit `LocatorRebased` records; quarantine unresolved paths rather than dropping or silently editing references. A bare locator resolves to the current version by documented precedence while historical versioned locators remain resolvable.

### Plugin and pipeline contract

Every plugin consumes a manifest and emits structured, provenance-bearing artifacts:

```text
StageInput {
  source_refs, evidence_refs, locator_version,
  stage_schema_version, extractor_version, decoder_version,
  model_provider_version, configuration_digest
}

StageOutput {
  artifact_refs, evidence_refs, semantic_events,
  confidence/uncertainty, generated_by, warnings, metrics
}
```

Required protocols/modules:

| Protocol | Responsibility |
|---|---|
| `Ingestor` | Validate media descriptor, write immutable bytes, detect format/streams, create source/work records |
| `Segmenter` | Produce deterministic addressable segments and locators |
| `Extractor` | Emit raw observations such as OCR, ASR, frames, audio intervals, subtitle events, layout, metadata |
| `Analyzer` | Produce structured interpretations with supporting evidence and confidence |
| `Aligner` | Produce many-to-many correspondence assertions with alignment method and assumption metadata |
| `Resolver` | Produce candidate sets and reversible alias/merge/split records; never delete mentions |
| `Reconciler` | Derive shared semantic intent while retaining source-specific realizations and contradictions |
| `ModelProvider` | Offer local/remote inference behind a provider-neutral call contract |
| `Embedder` | Produce versioned immutable embedding rows |
| `ProjectionBuilder` | Replay authority records into one named projection; no API writes |

The initial concrete matrix must include real implementations, not only protocols:

- Text/book: TXT, Markdown, EPUB, and viable text PDFs; structure, chapters, paragraphs, sentences, dialogue, entities, events, locations, relationships, and semantic segments.
- Image/sequential art: raster metadata, OCR, regions/panels, objects/people where possible, spatial relations, and descriptions.
- Audio: decode, segmentation, language, ASR, speaker observations/diarization, music/SFX, timing, and semantic utterances.
- Video: container/track inventory, audio and subtitle track extraction, scenes/shots/frames, ASR, speakers, visible entities, environment, objects, music/SFX, and temporal events.
- Subtitle: independent SRT/ASS/WebVTT/TTML/SAMI/MicroDVD/MPL2/TMP tracks. Normalize WebVTT `X-TIMESTAMP-MAP` before parsing; preserve raw bytes and encoding evidence.

The supplied research identifies representative choices: pdfplumber/pypdf for permissive PDF handling, ebooklib with explicit AGPL handling, pandoc in a sandbox for Markdown, Pillow plus PaddleOCR/Tesseract, PyAV/FFmpeg plus faster-whisper and pyannote (gated weights and license unresolved), PySceneDetect, and pysubs2. These are implementation inputs, not a license to skip the required sandbox and pin/watch process.

### Security and operations baseline

- Run dangerous parsers, archive extraction, PyAV/FFmpeg, OCR, ASR, diarization, and linkage in a dedicated sandbox runner, never in the API process.
- The final adversarial record favors bubblewrap with explicit container capabilities/profile requirements, with platform-specific fallback only after validation. Do not assume Ubuntu 24.04 has the needed AppArmor profile; document bare-metal/VM and managed-Kubernetes postures separately.
- Apply file-size/count limits, safe archive extraction inside the sandbox, rlimits/cgroups/timeouts, read-only binds, no shell interpolation, and structured failure classification.
- Pin FFmpeg/PyAV to CVE-fixed builds and maintain a CVE watch. Keep the raw media even when a parser fails.
- Emit structured logs, stage timing, model invocation metrics, queue depth, cache hits, per-stage cost/time, and a per-source decomposition report.
- Use generated adversarial fixtures in addition to clean synthetic media: malformed containers, VobSub-style inputs, non-UTF-8 subtitles, nonzero WebVTT timestamp maps, zip bombs, tar traversal payloads, VFR/edit-list cases, music-under-speech, and corrupt encodings.

## Option A: Postgres semantic ledger with rebuildable projections (recommended)

### Architecture

**Layers:** API/application → domain command handlers → source/segment stores and semantic ledger → durable stage execution → replay-built projections.

**Authority placement:**

```text
OCFL object storage       authoritative immutable source bytes/fixity
Postgres source tables    authoritative descriptors, work membership, segments, locators
Postgres semantic ledger  authoritative interpretations, edits, overrides, alignments,
                          resolution decisions, invalidations, and semantic audit history
Postgres current_state    transactional current winner read model, rebuilt by the same reducer
Postgres job_run_audit    job attempt history; not replayed as semantic events
pgvector/search tables    disposable evidence/semantic/canonical search projections
Neo4j (optional)          disposable deep-traversal graph projection
RDF-star (optional)       disposable claim/provenance graph projection
Hatchet                   durable execution state; API-level job audit remains authoritative
```

The semantic event envelope is versioned and append-only:

```text
semantic_event(
  seq, event_type, event_version, schema_url, tx_time, valid_time,
  authority, confidence, generated_by, correlation_id, causation_id,
  payload, idempotency_key
)
```

Event schemas live under `schemas/events/<type>/v<n>.json`. Breaking payload changes require an upcaster or a new event type; historical events are never edited. The `stage_run` table owns a Postgres `UNIQUE(idempotency_key)` constraint. The key insert, artifact references, and `StageCompleted` event are committed in one transaction. Hatchet deduplication is advisory; handler-level deduplication and the database are authoritative.

### Data flow

1. `POST /sources` streams an upload into an OCFL object, verifies fixity, creates a source descriptor and work membership, and returns a source/job ID.
2. Format analysis inventories tracks and routes the source to modality plugins.
3. Deterministic segmentation emits stable segment IDs and versioned locators into Postgres. Audio/video work is chunked by ranges; raw bytes remain in OCFL.
4. Sandboxed extraction reads a local read-only spool of the required OCFL range and emits evidence artifacts. Each output records input locators, tool/decoder versions, and artifact hashes.
5. Structural analysis, resolution, alignment, and reconciliation append typed semantic events. No stage writes the graph/search/vector stores directly.
6. Hatchet runs the explicit DAG. Dagster may declare asset lineage/freshness, but its auto-materialize daemon is disabled; Hatchet is the only runner.
7. Projection builders consume the semantic log from checkpoints, apply the shared reducer where relevant, and publish blue/green versions. A projection checkpoint includes the applied log position and manifest.
8. Query endpoints select Tier 0 for immediate winner/current-state paths, the log for history/provenance, and Tier 1 projections for graph/search-heavy paths.

### Invalidation and consistency

`Invalidated` records identify the affected source/segment/entity, stage, reason, and causation. The dependency graph selects descendants only. Unaffected source extraction and evidence remain valid. Stage manifests include schema, extractor, decoder, locator, model, and filter versions; a version bump creates a new DAG universe and drains/cancels in-flight work before switching.

The shared pure function `reduce_current_state(current_row, event)` is used by both the inline Tier-0 writer and Tier-1 replay. It is I/O-free, total, and bounded to indexed row operations. A merge/split has explicit mappings and a split-time deterministic enumeration of all references created while the merge was active. Reassignment emits `ReferenceRebound`; ambiguous references are quarantined.

Consistency contract:

- History/provenance/audit reads hit the ledger directly and are immediately consistent.
- Tier-0 current-state reads are committed in the same transaction as the event.
- A mutation returns `read_your_writes_token = seq`. Token-bearing Tier-1 requests wait behind bounded concurrency up to the configured budget. On timeout they return `503`, `Retry-After`, and `x-consistency: transient-lag` or `rebuild-in-progress`; they do not return stale post-correction answers. Untokened reads include a freshness/stale marker.
- Authority-relevant projection failures quarantine and pause the projection; they cannot silently skip a user override, merge, split, or equivalent event.

### Concrete query and retrieval surfaces

Primary API-neutral REST endpoints may include:

```text
POST /sources/{kind}
GET  /sources/{id}
GET  /sources/{id}/segments
GET  /locators/{encoded-locator}
GET  /segments/{id}/evidence
GET  /segments/{id}/claims
GET  /entities, /entities/{id}
GET  /claims/{id}, /claims/{id}/provenance
POST /claims/{id}/override
POST /entities/{id}/merge | /split
POST /analysis/{id}/rerun
POST /claims/{id}/invalidate
GET  /jobs/{id}, /jobs/{id}/events
POST /query/structured
POST /query/semantic
POST /search
GET  /audit/{subject}
GET  /health, /capabilities
```

`/query/structured` is a typed, bounded query API rather than raw database syntax. It supports scenes/entities/utterances/evidence/contradictions/unresolved aliases/correspondences, confidence thresholds, continuity scope, temporal scope, pagination, and result kind (`SOURCE_EVIDENCE`, `INTERPRETATION`, `CANONICAL_ENTITY`). An optional constrained Cypher/GQL adapter can target Neo4j, but the public contract does not depend on it.

`/query/semantic` compiles natural-language questions to typed operations and returns answer items, confidence, query interpretation, supporting claims, source locators, and unresolved/contradictory alternatives. It is not a free-form RAG answer path.

`/search` combines exact source-native search (`tsvector`, `pg_trgm`, locator filters) with versioned pgvector embeddings and hybrid ranking. Embeddings live in a separate append-only table, never on churned segment metadata; vectors are projections and can move to another engine behind `VectorIndex` when measured thresholds are exceeded.

### Initial implementation footprint

Estimated first production slice (architecture estimate, not an implementation promise): **18–24 top-level packages/modules, 35–50 migrations/schema artifacts, and roughly 10–16k lines including tests, adapters, and operational tooling**. The range is wide because media pipelines and sandbox harnesses dominate, not because the domain model is unclear. The service should begin with one deployable API and worker image plus separate sandbox-runner and Postgres/object-store dependencies; split deployment is an operational scaling choice rather than a service-boundary requirement.

### Pros

- Strongest structural guarantee that all semantic state can be reconstructed from one authority.
- Append-only corrections, user precedence, audit, merge/split reversal, and contradiction preservation are first-class rather than conventions.
- Deep graph, vector, and RDF representations remain available without making their engines authoritative.
- Postgres provides one transactional home for source descriptors, segments, semantic events, Tier-0 state, and pgvector during the first scale range.
- Plugin protocols and stage manifests isolate modality/model changes; local and remote model providers fit the same interface.
- Projection loss or migration is recoverable from the ledger; this materially lowers migration risk.

### Cons

- Event schema/upcaster discipline is mandatory and will be ongoing work. Historical fixtures and compatibility gates are part of the product.
- Projection lag, blue/green rebuilds, checkpoint management, and stale/fresh response semantics must be operated and explained to clients.
- The shared reducer removes tier divergence but creates common-mode risk: a reducer bug can affect Tier 0 and Tier 1 identically; conformance tests must test event construction separately.
- Hatchet has residual version/idempotency/retry risk in the supplied evidence. The ledger-side deduplication is mandatory, and Temporal remains a funded fallback if workflow complexity crosses the stated trigger.
- PostgreSQL/pgvector and an optional graph projection have eventual scale ceilings. Those ceilings are visible and migratable, not eliminated.

### When to choose

Choose A when provenance correctness, reversible edits, self-hosting, and migration safety are more important than making one graph engine the write API. It is the appropriate baseline for an infrastructure API expected to outlive individual model providers and graph/search products.

## Option B: RDF-star claim graph as semantic authority

### Architecture

Keep OCFL and Postgres source/segment truth, but make GraphDB Enterprise the semantic authority. Claims, qualifiers, confidence, references, authority, and PROV-O information are RDF-star statements and named graphs. A typed REST API compiles to SPARQL; direct SPARQL is private or tightly governed. An outbox in Postgres bridges assertion transactions to GraphDB. Temporal/Hatchet executes stages; graph snapshots and deltas provide audit.

The operational contract must explicitly pin **GraphDB's asserting RDF-star semantics**, not claim unverified RDF 1.2 triple-term conformance. GraphDB Free is not a production option according to its supplied license evidence. Apache Jena 6.1 is a license-free RDF 1.2 fallback, but the adversarial record labels that support experimental and therefore not a safe authority default.

### Data flow and interfaces

1. Ingest and segment in OCFL/Postgres as in A.
2. A command transaction writes an assertion and its provenance to Postgres outbox rows.
3. An ordered, idempotent drainer applies content-addressed RDF-star inserts/retractions to GraphDB and records status, retries, and poison rows.
4. REST structured queries execute against GraphDB; source-native retrieval resolves locators through Postgres/OCFL.
5. A snapshot/delta process produces bounded, resumable named-graph history. Authority precedence and reader lag are enforced in the API, not inferred from RDF-star presence.

Required additional interfaces are `RdfClaimWriter`, `OutboxDrainer`, `RdfSnapshotter`, `SparqlQueryGovernor`, and `RdfProjection/Export`. The outbox must specify ordering per entity/sequence key, retries, poison handling, read lag, divergence reconciliation, and which store wins when the bridge disagrees. Those are permanent complexity, not deployment detail.

### Pros

- RDF-star directly expresses claim-level references/qualifiers and has the strongest standards/interoperability story among the alternatives.
- Extensible predicates and PROV-O mapping reduce pressure for relational schema migrations.
- SPARQL is expressive for graph-shaped provenance and cross-source queries; RDF exports can serve standards-oriented consumers.
- Contradictory realizations and source-specific statements are natural data rather than exceptions.

### Cons

- Two authoritative-ish stores introduce transaction, ordering, lag, and divergence failure modes that A removes.
- GraphDB Enterprise licensing and cluster licensing are mandatory for production/HA; GraphDB Free is prohibited for production in the supplied evidence.
- The engine behavior is RDF-star/asserting, while RDF 1.2 triple terms are a different semantic model and the ecosystem is still evolving. Consumers must use API-enforced rank/authority filters or quoted statements can be misread as accepted truth.
- SPARQL operations, snapshot rebuilds, public query abuse controls, and outbox operations increase operational surface.
- Native RDF authority makes migration to a non-RDF engine costly even if Postgres remains structural truth.

### When to choose

Choose B only when RDF-native interoperability, standards-based exports, or RDF-specific tooling is a product requirement strong enough to fund GraphDB Enterprise and permanent outbox/drainer operations. A safer variation is to implement B's RDF-star model as a replay-built projection of A rather than as an authority; that variation is not a separate authority option because it is already an extension point in A.

## Option C: XTDB bitemporal semantic authority

### Architecture

Store semantic facts, corrections, alignments, and entity decisions in XTDB 2 with system-time and valid-time history. Keep OCFL and Postgres for source/segments, and use Temporal or Hatchet for jobs. Query through XTDB SQL and a typed REST layer; add Neo4j or another graph projection for deep traversal.

### Pros

- Bitemporal history and as-of queries are engine-level capabilities rather than custom audit tables.
- Append/supersede operations match correction and reversible-resolution semantics.
- SQL access is more familiar than SPARQL for many application teams.

### Cons and disqualifying evidence

- The supplied official XTDB SQL evidence says `WITH RECURSIVE` is not supported, so the proposed graph-query approach is unavailable. Deep traversal requires another projection, erasing the claimed simplicity.
- The adversarial log records XTDB 2.1 issue #5714: compaction can leave reads permanently failing until the data volume is dropped; the referenced fix is associated with 2.2, which was still RC at the check date. That is unacceptable for the first authoritative provenance store without a future verification gate.
- “PostgreSQL-compatible” is explicitly not 100% compatible; application assumptions about PostgreSQL transactions, extensions, and recursive queries cannot be transferred wholesale.
- JVM/Clojure operations and a less mature authority ecosystem add migration and staffing risk.
- Cross-assertion precedence rules and validation still need application logic.

### When to choose

Do not choose C as the first semantic authority under the supplied evidence. Consider it as an optional bitemporal witness/read model over A only after 2.2 is GA, issue #5714's fix is verified on the exact read/compaction path, the PgIndexer/CDC bridge is demonstrated end-to-end, and the SQL-dialect differences are catalogued. In that witness role, a failure cannot destroy semantic authority.

## Option D: Mutable Neo4j authority with PostgreSQL changelog mirror

### Architecture

Neo4j stores current semantic nodes/edges, evidence links, confidence, and provenance properties. The API performs Cypher mutations and writes a PostgreSQL changelog containing before/after deltas. Temporal runs decomposition, and invalidation walks graph dependency edges. Search/vector indexes are sidecars keyed by graph IDs.

### Pros

- Best direct traversal ergonomics for scenes/entities/relationships, variable-length paths, and graph-oriented QA.
- A single graph data model is intuitive for many-to-many alignment and correspondence.
- Native Cypher/GQL trajectory reduces the amount of query compilation needed.
- Immediate graph reads avoid projection lag for graph consumers.

### Cons and rejection

- The changelog is a mirror, not a reconstruction authority. A partial Neo4j/changelog write can leave neither side able to prove or rebuild the other, reproducing the dual-write failure documented in the supplied adversarial record.
- Reversible merge/split, complete history, and provenance become write-path conventions over a mutable authority rather than structural guarantees.
- Neo4j Community Edition is single-node and lacks the Enterprise HA/backup/RBAC capabilities expected of a production authority; relying on CE for “provenance never lost” is not credible.
- A graph authority makes graph-engine migration a semantic migration rather than a projection rebuild.
- API-level authorization and audit compensate for missing Community Edition controls, adding more custom code at the riskiest boundary.

### When to choose

Reject D as an authority. Reuse its strongest property—native traversal—inside A as a disposable, single-writer projection. If a future licensed HA graph service becomes operationally essential, it can be promoted as a read/query implementation without changing the semantic write contract.

## Recommended approach and rationale

### Recommendation

Adopt **Option A**, with these implementation-level commitments:

1. **One semantic write authority:** append-only versioned events in PostgreSQL. No API, worker, graph client, vector writer, or search writer may bypass the command/event path.
2. **Two explicit state tiers:** a transactional `current_state` projection for bounded winner reads and replay-built Tier-1 projections for graph/vector/search/RDF. Both use one `reduce_current_state` implementation.
3. **Source truth outside the database:** OCFL 1.1 layout over a replaceable object-store substrate; raw source bytes remain independently recoverable and fixity-checked.
4. **Durable jobs with database deduplication:** Hatchet is the primary runner based on the supplied workload/ops comparison, but engine idempotency is advisory. `stage_run` unique keys and same-transaction completion records are authoritative. Define and test Temporal migration triggers for deterministic multi-entity sagas or signal-heavy human workflows.
5. **Graph neutrality:** expose typed structured query REST first. Provide Neo4j CE only as an optional projection for deep traversal; provide RDF-star/Jena projections only when interoperability warrants them.
6. **Correctness before model confidence:** retain raw/model outputs as evidence, make confidence stage-scoped, prohibit transcription confidence from becoming semantic truth automatically, and record filter decisions. Whisper hallucination filters are best-effort; the promotion ban and provenance labeling are the real control.
7. **No silent repair:** rebase, merge, split, override, invalidation, quarantine, and reference rebinding are append-only records with auditable causation.

### Why this is the best fit

The requirements make recoverability, provenance, and corrections harder guarantees than graph traversal. A makes the hardest guarantees structural and keeps traversal/search replaceable. It also minimizes authority duplication: OCFL owns source bytes, Postgres owns source/segments/semantics, and every other representation can be deleted and rebuilt. The implementation cost is visible—schema evolution, projection lag, replay budgets, and job operations—and can be tested and monitored. B offers more native RDF semantics but pays an authority bridge forever; C and D put too much trust in current engine limitations for a first production authority.

## Ownership map (normative)

| Concern | Sole owner | Readers | Forbidden writer paths |
|---|---|---|---|
| Raw source bytes and fixity | OCFL object store | sandbox spooler, retrieval API | graph DB, semantic event payloads, user filenames |
| Source descriptors/work membership | Postgres source tables + semantic work events | API, segmenter, alignment | graph/search direct writes |
| Stable segments/locators | Postgres segment registry | extractors, retrieval, provenance | model providers, graph direct writes |
| Raw derived evidence artifacts | OCFL derived objects + Postgres artifact refs | analyzers, retrieval, audit | graph as sole copy |
| Semantic assertions/interpretations | append-only Postgres semantic ledger | reducer, audit, projections, API | in-place semantic UPDATE; graph/vector/search direct writes |
| User edits/overrides/locks | semantic ledger events | reducer, API, projections | hidden mutation of machine output |
| Entity identity mappings | semantic ledger resolution events + reducer map | alignment, query, projections | physical deletion/merge of mentions |
| Audit/history | semantic ledger + separate job-run audit | audit API, operators | projection-only history |
| Tier-0 current winners | Postgres `current_state`, derived in same command transaction | hot query paths | second reducer implementation |
| Graph traversal | optional Neo4j projection | typed query adapter | API/user mutations |
| RDF claim graph | optional replay-built RDF-star projection | export/query adapter | outbox-authoritative writes |
| Exact/full-text search | Postgres search projection | search API | authoritative semantic writes |
| Embeddings/vector index | append-only embedding projection | semantic search | in-place HNSW-table updates |
| Pipeline/job state | Hatchet plus Postgres stage/job records | jobs API, operators | semantic truth inferred solely from runner state |
| Model/provider configuration | provider registry/configuration | workers, audit | provider-specific assumptions in semantic schema |
| Security policy | API boundary + sandbox runner + deployment policy | all ingestion workers | parser execution in API process |

## Suggested repository structure and key interfaces

```text
artifacts/designs/                       # process and final design artifacts
schemas/
  events/<event-type>/v<n>.json          # immutable event payload contracts
  api/openapi.yaml
src/umd/
  api/                                   # REST routes, auth, pagination, errors
  application/                           # commands, transactions, consistency tokens
  domain/
    sources.py segments.py locators.py
    evidence.py semantics.py ontology.py
    entities.py alignment.py temporal.py
  storage/
    ocfl.py objects.py postgres.py
    semantic_ledger.py current_state.py
  ingestion/                             # descriptors, format dispatch, upload guards
  extractors/{text,image,audio,video,subtitle}/
  segmentation/                          # deterministic segmenters and locator versions
  analysis/                               # structural analyzers and semantic derivation
  resolution/                             # candidate generation, merge/split/rebind
  alignment/                              # Vecalign parallel-only, temporal/adaptation paths
  provenance/                             # PROV-O mapping, evidence links, audit views
  jobs/                                   # DAG definitions, Hatchet adapter, invalidation
  models/                                 # ModelProvider, local/remote adapters, call records
  projections/
    graph/ rdf/ search/ vectors/
    reducer.py checkpoints.py blue_green.py
  security/                               # sandbox command construction, archive guards
  observability/                          # logs, metrics, traces, decomposition reports
migrations/                               # structural Alembic migrations only
tests/
  unit/ integration/ e2e/ properties/
  fixtures/generators/ adversarial/
  Dockerfile compose.yml sandbox-runner/
  architecture/ models/ locators/ dag/ invalidation/
  plugins/ providers/ storage/ api/ deployment/ testing/
```

Key boundary signatures (conceptual, not implementation code):

```text
CommandHandler.handle(command, tx) -> CommitResult(seq, read_your_writes_token)
SemanticLedger.append(events, expected_version, idempotency_key) -> CommitResult
CurrentStateReducer.reduce(row, event) -> row                 # pure and shared
StageRunner.run(manifest, input_refs) -> StageRunResult       # idempotent handler
InvalidationPlanner.plan(causation, asset_graph) -> StageTargets
ProjectionBuilder.apply(event_batch, checkpoint) -> Checkpoint
LocatorResolver.resolve(locator, version_policy) -> SourceRange
EvidenceRepository.get(range) -> bounded source-native representation
ModelProvider.invoke(request) -> StructuredModelResult
Resolver.resolve(candidates, policy) -> ResolutionEvents
Aligner.align(left_refs, right_refs, context) -> AlignmentEvents
QueryService.structured(query) -> ProvenanceBearingPage
QuestionService.answer(question, constraints) -> StructuredAnswer
SearchService.hybrid(query, filters) -> KindTaggedSearchPage
AuditService.explain(subject, as_of) -> ChangeExplanation
```

The API/application layer owns authorization, consistency tokens, query cost limits, and command validation. Domain modules own invariants. Adapters own libraries and stores. Projection modules have write credentials unavailable to API readers, and an architecture test rejects imports of projection-store clients outside `src/umd/projections/`.

## Requirement coverage and implementation proof obligations

| `Task.md` area | A mechanism | Required proof/test |
|---|---|---|
| §§1–2, 10–11, 21, 36: layer separation/provenance | OCFL → evidence refs → ledger assertions → projections; generated-by and confidence on every derived result | provenance traversal from claim to raw locator; no graph-only claim; audit “why/previous/change” tests |
| §§3–5, 27: sources, multilingual/adaptations/subtitles | descriptors, work/continuity membership, independent tracks, typed correspondence/contradiction edges | translated/adapted sources and HI/SDH tracks remain distinct; many-to-many fixture |
| §§6, 16, 23: DAG/invalidation/jobs | explicit stage graph, manifests, stage artifacts, Hatchet durable execution, ledger dedup, descendant planner | late-stage failure does not redo earlier stage; targeted invalidation leaves unaffected checksums unchanged; restart/cancel/retry tests |
| §§7, 15, 29: editing/overrides/reversible resolution | append-only corrections, authority precedence, merge/split snapshots, split-time reference enumeration, `ReferenceRebound`, quarantine | merge→split restores mentions and every downstream reference; override wins and remains auditable |
| §§8–9, 19: segments/locators/retrieval | deterministic IDs, versioned source locators, OCFL range retrieval, rebase/quarantine policy | re-ingest stability, decoder-version drift detection, locator-to-source-native text/crop/frame/audio/subtitle retrieval |
| §§12–14, 30–31: alignment/uncertainty/time/space | typed confidence-bearing alignment, candidate sets, source/narrative/story time, spatial assertions | reordered/missing/adaptation events, unknown/conflicting states, confidence threshold query |
| §§13, 25–26: models/plugins/real pipelines | provider protocols, local Ollama path, modality adapters, structured model invocation events | provider substitution; actual TXT/Markdown/EPUB/PDF/image/audio/video/subtitle integration fixtures |
| §§17–20: questions/structured query/search | typed REST query, optional graph adapter, semantic compiler, exact+hybrid search with result kind | deterministic scene/entity/evidence queries; provenance-bearing semantic answers; exact and vector result classification |
| §§22, 28: storage/canonical semantics | ownership map; typed core + extensible predicates; rebuildable projections | delete/rebuild projections; store divergence checks; competing realizations remain visible |
| §§24, 33: API/operations | OpenAPI, stable IDs, pagination, structured errors, health/capabilities, logs/metrics/traces | contract tests and operational dashboards/report fixtures |
| §§32, 34, 35, 38–40: security/testing/deployment | sandbox runner, pinned dependencies, adversarial fixture matrix, Docker/Compose/migrations/docs | parser containment, traversal/zip bomb tests, deterministic-stage checksums, cross-tier E2E correction→invalidation→rerun |

Determinism claims must be stage-scoped: byte-exact checksums for segmentation, locators, structural outputs, Tier-0 replay, and canonical ordered graph export; tolerance-based metrics for ASR/OCR/diarization/model stages. The end-to-end test must compare corrected Tier-0 and Tier-1 answers, not only IDs.

## Rejected or demoted alternatives

| Alternative | Disposition | Reason |
|---|---|---|
| Mutable Neo4j authority + changelog | Rejected as authority; retained as A projection | Dual-write cannot guarantee replayability; CE lacks authority-grade HA/backup/RBAC; graph migration is expensive |
| XTDB 2 authority | Rejected for first release; optional gated witness | No recursive CTE in supplied docs; 2.1 compaction/readability incident; 2.2 RC and SQL compatibility limits |
| GraphDB Free production | Rejected | Supplied official license evidence prohibits production use |
| GraphDB RDF 1.2 triple-term authority | Rejected as stated | Supplied engine evidence establishes RDF-star asserting behavior, not true RDF 1.2 triple terms; use explicit RDF-star contract or a replay projection |
| Kùzu | Rejected | Supplied research says the project was archived/discontinued |
| Memgraph disk authority | Rejected | Supplied research identifies disk mode as experimental/in flux and in-memory operation as an OOM risk |
| Apache AGE as default graph execution | Rejected as default | Supplied 2026 evidence reports poor complex-query behavior and incomplete openCypher coverage |
| Dedicated vector DB on day one | Deferred | Adds synchronization/authority surface before measured pgvector scale requires it; retain `VectorIndex` escape hatch |
| Giant opaque pipeline | Rejected | Violates selective rerun, partial-failure recovery, and provenance of individual stages |
| Raw natural-language RAG as semantic layer | Rejected | Cannot provide deterministic evidence/semantic separation, structured provenance, or correction semantics |

## Unresolved risks and explicit gates

These are not silently resolved by choosing A:

1. **pyannote weights/license (high):** access is gated and the supplied adversarial record says the model card does not declare a commercial license. Treat vendored weights as provisional; obtain legal confirmation or fund a non-gated/fallback diarization path before commercial deployment.
2. **Whisper hallucination efficacy (medium):** supplied research says the common decoder signals are weak detectors. Ship raw untrusted ASR evidence, stage-scoped transcription confidence, `HallucinationFiltered` events, and a promotion ban. Measure false positive/negative rates; optionally add de-looping, a curated hallucination list, and `condition_on_previous_text=False` before considering internal-state probing.
3. **Hatchet release/idempotency (medium):** pin an exact release after testing the required retry/cancel/replay shapes. Keep Temporal migration triggers and shared stage interfaces ready.
4. **splink/DuckDB planner behavior (medium):** benchmark the actual blocking keys under splink ≥4.0.16. If performance is at least 3× worse than the 1.3.x baseline, pin the fallback DuckDB line identified in the supplied log; persist model parameters and use chunked prediction.
5. **Sandbox platform posture (medium):** validate bubblewrap user namespaces, AppArmor profiles, container capabilities, and read-only local spool behavior on every first-class deployment target. Do not rely on the unvalidated “sandlock” fallback without a maintenance check.
6. **FFmpeg/PyAV vulnerability stream (medium):** use in-sandbox execution, fixed-version pins, parser-specific policy tests, and a standing CVE watch. This contains rather than eliminates parser risk.
7. **Locator drift (medium):** decoder/renderer/version changes can invalidate coordinates or timestamps. Version locators, preserve old versions, trigger selective invalidation, and quarantine unresolvable rebases.
8. **Projection/replay scale (medium):** define per-projection rebuild budgets, checkpoints, snapshots only after measurement, blue/green swaps, poison-event policy, and thresholds for Neo4j/vector promotion. Projection failure must not compromise the ledger.
9. **Tier-0 common-mode reducer bug (medium):** keep reducer pure and total; separately test command/event payload correctness, replay determinism, and Tier-0/Tier-1 equivalence.
10. **OCFL remote access (low/medium):** sandbox stages should consume a read-only local spool, not assume FUSE/S3 mounts work inside user namespaces. Validate range staging and cleanup under crash/retry.

## Evidence boundary

All technology and risk claims in this report are limited to the supplied artifacts checked on 2026-08-25. In particular:

- Current-version, licensing, and support facts are taken from the technology research report and its cited primary sources, with corrections and gates from adversarial T1–T8.
- The final adversarial record explicitly marks A as implementation-ready for DD distillation, B/D as unsuitable authorities, and C as a conditional projection/witness pattern rather than an uncomplicated authority.
- Exact dependency versions for Hatchet, FFmpeg/PyAV, and the splink/DuckDB combination remain build-time gates, not invented fixed choices in this report.

**Conclusion:** A is the recommended implementation architecture; B is a funded standards-oriented challenger; C is a gated future witness; D is rejected as an authority but retained as a projection pattern. The pending DD should distill A's ownership and invariants, not merely copy its technology list.
