# Universal Media Decomposer API — Design Document

**Status:** Draft  
**Author:** rnd-dd-author  
**Created:** 2026-08-25  

**Related Documents:**
- [Authoritative requirements](Task.md) — Task.md §§1–41, lines 1–1739.
- [Technology and design research](artifacts/designs/process/universal-media-decomposer-technology-research.md) — Current technology, standards, modality, security, and storage evidence.
- [Complete adversarial log](artifacts/designs/process/universal-media-decomposer-adversarial-log.md) — All eight refinement turns T1–T8, surviving risks, human questions, and final patterns.
- [Architecture options](artifacts/designs/process/universal-media-decomposer-architecture-options.md) — Option A recommendation, ownership map, contracts, proof obligations, and rejected alternatives.
- [Complexity review](artifacts/designs/process/universal-media-decomposer-complexity-review.md) — Justified complexity and v1 simplifications: no Dagster and no mandatory graph/RDF projections.
- [Final effort estimate](artifacts/designs/process/universal-media-decomposer-final-estimate.md) — EPIC sizing, dependencies, permanent work, gates, and immutable DD_REQUIRED confirmation.
- [Support librarian log](artifacts/logs/support-librarian.log.jsonl) — L1 greenfield baseline; no prior ADR/ASR/DD/plan constraints.
- [Support researcher log](artifacts/logs/support-researcher.log.jsonl) — L1 pointer to the technology research artifact.

---

## Scope

Greenfield, API-neutral infrastructure service for arbitrary media ingestion, evidence extraction, semantic interpretation, provenance-preserving reconciliation, structured/graph-like querying, source retrieval, editing, and selective reprocessing. v1 covers text/book (TXT, Markdown, EPUB, viable text PDFs), raster images/sequential-art composition, audio, video, and independent subtitle tracks. It is not designed around audiobook, subtitle-generation, game, screenplay, or video-generation consumers.

---

## Problem Statement

Build a production-ready service that accepts heterogeneous source media and progressively derives addressable segments, direct evidence, interpretations, and reconciled knowledge without collapsing those layers. Every derived result must remain traceable to immutable source bytes and exact locators, with model/version/confidence/audit metadata. Multiple languages, editions, adaptations, continuities, and subtitle tracks must coexist as distinct realizations and be alignable many-to-many. Humans must be able to inspect, correct, lock, split, merge, invalidate, and selectively rerun results while retaining history. The design is implementation-ready and preserves the immutable DD_REQUIRED gate; it does not claim that production code has been implemented.

---

## Architecture

## Selected architecture

Use Option A from the architecture analysis: one modular FastAPI service and worker image, PostgreSQL as the transactional authority for source metadata, deterministic segment registry, append-only semantic event ledger, Tier-0 current-state projection, job/stage records, and pgvector/full-text projections; an OCFL 1.1-compatible object store is authoritative for immutable source and derived artifact bytes. Hatchet is the v1 durable DAG runner; its exact release is a build gate. A dedicated sandbox-runner executes untrusted parsers and model/extraction subprocesses. Optional local Ollama (and later vLLM) plus remote adapters implement the provider contract.

The four layers are non-negotiable and have separate contracts and owners:

```text
OCFL source bytes -> Postgres evidence/segments -> Postgres semantic ledger -> disposable read projections
                         |                         |                    |
                    source-native retrieval   audit/reducer          Tier-0 + Tier-1 query/search
```

The semantic ledger is the only semantic write authority. API commands and workers append versioned events; they never write graph/search/vector state directly. Tier-0 `current_state` is updated in the same transaction as an accepted semantic event. Tier-1 exact-search and pgvector projections replay the ledger from checkpoints and are blue/green rebuildable. V1 bounded graph-like queries use typed Postgres semantic/current-state tables and indexed bounded traversal; a separate graph projection/builder is deferred until a measured need for unbounded traversal or graph algorithms. A shared pure, total `reduce_current_state(current_row, event)` is used by the append transaction and replay builders. Projection failure cannot erase or alter the ledger.

### Module and ownership map

- `api`: FastAPI routers, Pydantic v2 request/response schemas, authentication/authorization, pagination, RFC 7807 errors, consistency headers, OpenAPI.
- `application`: command handlers, transaction boundaries, idempotency, read-your-writes tokens, authorization policy, query-cost limits.
- `domain`: typed source/work/continuity/edition/translation/adaptation/segment/evidence/entity/temporal/spatial models, invariants, stable IDs, locator parsing.
- `storage`: OCFL adapter, PostgreSQL repositories, semantic ledger, current-state reducer, artifact references, projection checkpoints.
- `ingestion` and `segmentation`: content validation, format dispatch, deterministic modality segmenters and locator generation.
- `extractors`: sandboxed text, image, audio, video, and subtitle implementations. Adapters own third-party libraries; core contracts do not.
- `analysis`: structural analyzers and semantic event construction.
- `resolution` and `alignment`: candidate generation, persisted linkage model, reversible resolution, many-to-many correspondence.
- `jobs`: one in-repository stage DAG/lineage definition, Hatchet adapter, invalidation planner, stage manifests and restart behavior. Dagster is not in v1 and has no scheduler role.
- `models`: `ModelProvider` with `mode=completion|embedding`; local/remote adapters, call records, and provider registry. `Embedder` is a typed wrapper over this contract; `Reconciler` is an Analyzer sub-interface, not a parallel framework.
- `projections`: single-writer current-state, search, and vector projection builders; bounded graph-like v1 reads use typed Postgres tables. Neo4j, RDF-star, and XTDB adapters, including any separate graph builder, remain future contracts, not v1 dependencies.
- `provenance`, `audit`, `observability`, `security`: evidence links/PROV-aligned metadata, audit explanations, metrics/traces/reports, sandbox and archive policy.

The deployable topology deliberately avoids service-per-capability decomposition: API and workers may share an image and scale separately; the sandbox-runner is a security boundary, not a business service. Implementation dependencies are: foundation/config/OCFL/Postgres and event schemas -> domain/ledger/locators -> DAG and stage contracts -> text/image and audio/video/subtitle pipelines -> resolution/alignment -> query/search/projections -> hardening, fixtures, documentation, and full verification. This ordering is guidance for downstream planning, not an implementation plan.

---

## Design Goals

- Preserve source/evidence/interpretation/knowledge separation and exact provenance for every derived object.
- Make semantic corrections, overrides, merges, splits, contradictions, and audit history structurally append-only and reversible.
- Support independent, restartable DAG stages and selective descendant invalidation without repeating unaffected extraction.
- Keep source representations, languages, translations, editions, adaptations, continuities, and subtitle tracks distinct while exposing explicit alignment and shared semantic intent.
- Ship real v1 modality pipelines, not only plugin interfaces.
- Provide deterministic source-native retrieval, typed structured queries, bounded graph-like semantic QA, and hybrid exact/vector search with result-kind and provenance labels.
- Keep providers, extractors, storage, and future graph engines swappable behind tested contracts.
- Operate securely on untrusted uploads with bounded resources, structured failure handling, and actionable observability.
- Make local development and self-hosted deployment reproducible with Docker/Compose, migrations, fixtures, OpenAPI, examples, and runbooks.

## Non-goals and explicit v1 boundaries

- No downstream-consumer-specific generation features or domain-specific ontology.
- No opaque RAG corpus as semantic authority; natural-language QA must compile to typed operations and return evidence.
- No destructive mutation of machine results or physical deletion of mentions.
- No mandatory Neo4j, RDF/RDF-star, GraphDB, XTDB, dedicated vector database, or Dagster deployment in v1.
- No claim of arbitrary-depth graph algorithms in v1; bounded-depth graph-like queries are implemented over Postgres. The graph projection interface and canonical export shape leave a phase-2 path.
- No guarantee that a locator survives changed bytes, changed EPUB structure, or decoder/renderer behavior; drift is versioned, detectable, rebasable, and quarantineable.
- No detector-grade guarantee for ASR hallucinations and no assumption that model confidence is semantic truth.
- No assumption that adaptation alignment is sentence-perfect; Vecalign is parallel-text-only in v1.

---

## Constraints

## Requirements traceability

The following is the normative mapping to `/workspace/Universeity/Task.md` §§1–41:

| Task areas | Design mechanism and proof obligation |
|---|---|
| §§1–2, 10–11, 21, 36 | Separate source/evidence/interpretation/knowledge contracts; immutable OCFL bytes; evidence-linked assertions; typed core plus extensible predicates; append-only ledger and audit API. Test claim -> evidence -> locator -> bytes and why/previous/change explanations. |
| §§3–5, 27–28 | API-neutral descriptors; work/continuity/edition/translation/adaptation membership; independent subtitle sources; source-specific realizations, omissions, reorderings, contradictions, and semantic-intent links. Test multilingual and adaptation fixtures without flattening. |
| §§6, 16, 23 | Explicit stage DAG and input manifests; per-stage idempotency and durable records; descendant-only invalidation; restart/cancel/retry/rerun tests. |
| §§7, 15, 29 | USER_OVERRIDE and edit/lock/merge/split/rebind/invalidate events; precedence in reducer; reversible merge and split-time reference enumeration; audit history. |
| §§8–9, 19 | Deterministic segment IDs and versioned `source://` locators; source-native text/crop/frame/audio/subtitle retrieval; old versions remain resolvable. |
| §§12–14, 30–31 | Confidence/candidate sets, contradiction/alternative states, temporal sequence versus chronology, flashbacks/unknown order, spatial/environment assertions, many-to-many alignment. |
| §§13, 25–26 | Concrete modality plugins and provider contracts; structured model-call provenance; local model path; sandboxed extraction. |
| §§17–20 | Typed structured REST, bounded graph-like relational traversal, semantic-question compiler, exact + hybrid vector search; every answer labels kind and support. |
| §§22, 28 | Sole-store ownership table; only Postgres ledger is semantic authority; all heavy projections are disposable and replayable. |
| §§24, 33 | OpenAPI, stable IDs, pagination, RFC 7807 errors, health/capabilities, logs/metrics/traces, stage and cost reports. |
| §§32, 34–35, 38–40 | Bubblewrap sandbox posture, adversarial fixtures, determinism/conformance and correction E2E tests, Docker/Compose/migrations/docs, final adversarial review and repair gate. |

### Ownership invariants

| Data | Sole authority | Allowed writers / forbidden paths |
|---|---|---|
| Raw source bytes and fixity | OCFL object storage | Ingestion/storage adapter only; never graph or semantic payload blobs; never user filenames as keys. |
| Source descriptors, work membership, segment registry, locators | PostgreSQL typed tables | Ingestion/segment command path; no model/provider or projection writes. |
| Derived evidence bytes | OCFL derived objects plus Postgres references | Stage artifact writer; graph never holds the only copy. |
| Semantic assertions, alignments, resolution, overrides, locks, invalidation, audit semantics | Append-only Postgres semantic ledger | Command/event path only; no in-place UPDATE or direct projection writes. |
| Tier-0 winners/entity map | Postgres `current_state` and `current_entity_map` | Same transaction as event append through shared reducer. |
| Exact/vector/search and bounded graph-like reads | Replay-built Postgres projections | Projection builders only; no API mutation path. |
| Job/stage execution | Hatchet plus Postgres `stage_run` and `job_run_audit` | Worker/job adapter; semantic audit of lifecycle is in Postgres, not dependent on Hatchet audit features. |
| Model/provider configuration | Versioned configuration/registry | Provider adapter; calls cannot embed provider assumptions in semantic schema. |

The permanent complexity budget includes event upcasters, historical replay fixtures, projection checkpoints/blue-green rebuilds, sandbox CVE/profile maintenance, and consistency-state operations. These are product obligations, not one-time setup.

---

## Open Questions

These questions remain explicitly visible because evidence cannot settle them; they do not change the selected architecture.

1. **Pyannote commercial rights (Q1, high):** gated `speaker-diarization-3.1` and community weights may be vendored only after legal/commercial sign-off. If rights or unattended token access are unacceptable, use a non-gated fallback or defer diarization while retaining speaker-unknown candidates. Deadline: before first commercial deployment.
2. **Long rebuild response shape (Q2):** v1 accepts the tested single `503` contract, with `x-consistency: rebuild-in-progress`, long `Retry-After`, and optional estimate; clients should poll job/rebuild status rather than hammer reads. Revisit only if operations show this is inadequate.
3. **Sandbox targets (Q3):** bare metal/VM is first-class with bubblewrap and required Ubuntu profile setup. Docker/Kubernetes is conditional on user namespaces/capabilities; sandlock is only a future fallback after verifying that a maintained implementation exists and passes the sandbox spike.
4. **Hallucination containment depth (Q4):** v1 enforces the promotion ban and cheap evidence-backed `condition_on_previous_text=False`, beam-size policy for music-heavy audio, and Bag-of-Hallucinations/de-looping where available. Internal-state probing is phase 2 after measured FPR/FNR.
5. **Vecalign adaptation scope (Q5):** v1 accepts parallel-text-only Vecalign. Adaptations/subtitles use temporal/embedding retrieval and structured reconciliation; every alignment exposes its assumption.
6. Exact Hatchet, FFmpeg/PyAV, DuckDB, and sandbox package pins are selected and recorded by build gates, not invented here. A version bump creates a new manifest/DAG universe and follows migration/drain rules.

---

## Data model, events, and provenance

## Typed relational core

Use UUIDv7/ULID-compatible stable IDs (exact encoding is an implementation detail) and foreign keys for `work`, `continuity`, `source`, `source_membership`, `edition`, `segment`, `evidence`, `artifact`, `entity`, `entity_mention`, `predicate`, `semantic_assertion`, `current_state`, `current_entity_map`, `alignment`, `stage_run`, `job_run_audit`, `embedding`, `projection_checkpoint`, `quarantine`, and `locator_rebase`. Core fields are indexed and typed; extension fields use JSONB. A predicate dictionary permits new predicates without a migration. High-value relationships (`SPEAKS`, `PRESENT_IN`, `CORRESPONDS_TO`, `TRANSLATION_OF`, `ADAPTATION_OF`, `DERIVED_FROM`, `CONTRADICTS`, `ALIAS_OF`, `EXPANDS`, `OMITS`, `REORDERS`, `ALTERNATE_REALIZATION`) are validated vocabulary entries, not a closed ontology.

The typed vocabulary also covers the required semantic kinds and observations: work, continuity, source, edition, adaptation, translation, character, person, organization, location, object, concept, scene, event, action, utterance, relationship, state, emotion, goal, belief/knowledge, timeline, presence, speaker identity, alias, visual appearance, environment, music, sound, and cross-source correspondence. These remain typed kinds/predicates with evidence, scope/continuity, confidence/state, and generated-by metadata; new domain concepts use the predicate dictionary and extension fields rather than requiring a core-table migration.

Every evidence record identifies `source_id`, exact locator, evidence kind, language, track/edition metadata, raw/normalized representation references, extraction stage, tool/decoder/model versions, configuration digest, and confidence/quality metadata. Assertions contain subject/object references (typed IDs or structured values), predicate, authority, confidence, state (`UNKNOWN|AMBIGUOUS|CONFLICTING|PROBABLE|CONFIRMED|USER_CONFIRMED`), scope/continuity, valid-time/narrative-time fields, support and contradiction references, derivation, and generated-by metadata. Canonical structures are projections or assertions over realizations; they never replace source claims or fabricate canonical prose.

### Append-only event envelope

```text
semantic_event(
  seq BIGSERIAL, event_type, event_version, schema_url,
  tx_time, valid_time, authority, confidence,
  generated_by, correlation_id, causation_id,
  payload JSONB, idempotency_key, created_by
)
```

Payload schemas live under `schemas/events/<type>/v<n>.json`; historical rows are immutable. Breaking changes require a new version and a pure upcaster chain. CI replays every retained historical event fixture through every projection. Event types include `SourceIngested`, `SourceAliased`, `FormatAnalyzed`, `SegmentCreated`, `StageCompleted`, `JobRunAudit`, `EntityMentioned`, `EntityResolved(MERGE|SPLIT|ALIAS)`, `ReferenceRebound`, `Aligned`, `SemanticAsserted`, `ContradictionRecorded`, `OverrideApplied`, `CorrectionApplied`, `Locked`, `Unlocked`, `Invalidated`, `LocatorRebased`, and `HallucinationFiltered`. Job-run audit is committed as an auditable event/record but is excluded from semantic-state replay to avoid sequence inflation; its event type is handled explicitly by the projector policy.

`MERGE` records preserve mention-to-entity mappings and references known at merge time. `SPLIT` performs a deterministic query at split-time sequence over every reference kind, including references created during the merged lifetime; its payload carries explicit target assignments. Reassignments append `ReferenceRebound`; ambiguous alignment, override, candidate, or evidence references enter quarantine and are surfaced, never silently dropped. Merge/split is therefore a reversible projection operation, not deletion.

### Reducer and consistency

`reduce_current_state(current_row, event)` is I/O-free, total, deterministic, and bounded to indexed row operations. Winner selection is last-write-wins per `(entity_ref, predicate)` after authority/lock rules, with numeric confidence available for indexed threshold queries. Tier-0 is rebuilt by wiping and replaying the log in tests; event construction is tested separately so reducer determinism cannot hide malformed payloads. A mutation commits event and Tier-0 update atomically and returns `read_your_writes_token=seq`.

History/provenance/audit and Tier-0 reads are immediately consistent. Token-bearing Tier-1 reads wait behind a bounded semaphore up to `2 × configured lag budget` (default cap <=1 second). If not caught up, return `503`, `Retry-After`, and `x-consistency: transient-lag`; scheduled rebuilds return `503`, `Retry-After >=30s`, `x-consistency: rebuild-in-progress`, and optionally `x-rebuild-estimate`. Do not return stale post-correction results. Untokened reads include freshness/stale metadata. Projection poison events may be skipped only for non-authoritative machine noise after quarantine; overrides, merge/split, and other authority-relevant events pause the projection and return its pause reason to token-bearing reads.

---

## API and contracts

## REST contract

FastAPI generates versioned OpenAPI. All IDs are stable, collection responses are cursor/page paginated, and failures use RFC 7807-compatible structured errors with machine-readable `type`, `code`, `detail`, `correlation_id`, and retryability.

Core routes (exact route taxonomy is an adapter over descriptors):

- `POST /v1/sources/{kind}` and `POST /v1/sources` ingest a stream plus descriptor; return `source_id`, `work_id`, `job_id`, and consistency token.
- `GET /v1/sources/{id}`, `/sources/{id}/segments`, `/sources/{id}/analysis`, `/sources/{id}/report` retrieve metadata, segment trees, stage state, and decomposition report.
- `GET /v1/locators/{encoded}` resolves a locator and returns segment, bounded native representation, neighboring context, evidence, claims, and provenance. `GET /v1/segments/{id}/evidence` and `/claims` provide the same relations by ID.
- `GET/POST /v1/entities`, `/entities/{id}`; `POST /entities/{id}/merge`, `/split`, `/lock`, `/unlock`; alias edits append events.
- `GET/POST /v1/claims`, `/claims/{id}/override`, `/invalidate`, `/provenance`; explicit assertion, contradiction, evidence association/disassociation, and lock operations append events.
- `POST /v1/segments/{id}/edit`, `/split`, `/merge`, `/rerun` records boundary/edit events and schedules dependent work.
- `POST /v1/analysis/{id}/rerun`, `/sources/{id}/rerun`, `/claims/{id}/invalidate`; requests may specify a stage and scope. The planner chooses descendants.
- `GET /v1/jobs/{id}`, `/jobs/{id}/events`, `POST /v1/jobs/{id}/cancel|retry`; status includes stage, attempts, timing, errors, and artifact references.
- `POST /v1/query/structured` accepts typed filters for scenes, entities, utterances, evidence, contradictions, unresolved aliases, correspondences, confidence, continuity, temporal scope, bounded traversal depth, and result kind (`SOURCE_EVIDENCE|INTERPRETATION|CANONICAL_ENTITY`).
- `POST /v1/query/semantic` compiles supported natural-language questions into typed operations and returns answer items, interpretation, confidence, support claims, locators, alternatives, and unresolved/contradictory results. It cannot answer from an unstructured-only corpus.
- `POST /v1/search` supports exact phrase/name/locator/time/chapter/page filters and semantic/hybrid retrieval. Each result states whether it is source evidence, interpretation, or canonical entity.
- `GET /v1/audit/{subject}`, with `as_of`, causation, and correlation filters, answers why/current, prior state, and change cause.
- `GET /v1/health`, `/ready`, `/capabilities`, `/version` expose dependency health, feature/provider availability, schema/DAG versions, and limits.

`GET /v1/locators` resolves explicit `@vN` versions exactly. A bare locator resolves newest compatible locator version for the work/source; historical `@vN` remains addressable. Token-bearing query clients must implement exponential backoff with full jitter for 503 responses; response headers distinguish transient lag from rebuilds.

The repository must ship maintained, runnable client examples in addition to generated OpenAPI: a minimal `curl` flow and a Python or typed-client flow covering ingest, job polling, structured/semantic query, source-native locator retrieval, a user correction/override, and selective rerun. Examples use only versioned public contracts and demonstrate cursor pagination, RFC 7807 errors, read-your-writes tokens, and distinct `x-consistency: transient-lag` versus `x-consistency: rebuild-in-progress` 503 responses; they must not depend on a particular model provider or storage backend.

---

## Ingestion, segmentation, and modality pipelines

## Common pipeline contract

Each stage receives a manifest containing source/evidence refs, locator version, stage schema, extractor/decoder/render versions, provider version, configuration digest, and DAG universe. It emits structured artifact/evidence refs, semantic events, confidence/uncertainty, warnings, metrics, and generated-by metadata. Large media is processed by locator ranges/chunks, not whole-blob memory loads. Raw input is retained even when a parser fails.

The v1 DAG is `INGEST -> FORMAT_ANALYSIS -> BASIC_SEGMENTATION -> LOW_LEVEL_EXTRACTION -> STRUCTURAL_ANALYSIS -> ENTITY_RESOLUTION -> CROSS_SOURCE_ALIGNMENT -> SEMANTIC_RECONCILIATION -> CURRENT/SEARCH PROJECTION`. Independent branches fan out by segment and modality. `HallucinationFiltered` is its own versioned dependency edge: changing thresholds can selectively reclassify ASR-derived outputs.

### V1 modality depth contract

“Implemented” means the following bounded, tested baseline, not maximum-fidelity media understanding. Every baseline emits the common manifest/output envelope, preserves raw input, and can quarantine an item or unsupported feature without losing the source or unrelated branches. Capability responses identify which optional enhancements are enabled.

- **Text/book/sequential art:** TXT and viable text-PDF extracted text use the deterministic plain-text document/chapter/section/paragraph/sentence/token-span baseline; Markdown uses its native document/chapter/section/paragraph hierarchy and EPUB its native document/chapter/paragraph hierarchy. Dialogue/narration, entity and alias candidates, speaker candidates, events, locations, relationships, and semantic segments retain evidence links. Image-only PDF pages route to the raster/OCR path. Page/panel/region/bubble/caption structure is emitted where the source supports it.
- **Raster image:** bounded decode and metadata, deterministic page/region/panel ordering, OCR regions/text, spatial observations, and confidence-bearing object/person observations and descriptions where selected providers support them. Face identity remains a candidate observation and is never an automatic canonical identity.
- **Audio:** bounded decode/chunking, VAD, language identification, ASR utterances with word/time ranges, music/sound regions, speaker candidates, and timing. Diarization is an optional gated enhancement; without approved weights/license it emits `speaker_unknown_N` candidates and does not block the rest of the audio baseline.
- **Audio (including audiobook, podcast, and song sources):** the same bounded audio baseline applies without consumer-specific assumptions; chapter/track metadata, utterances, music, sound, and timing remain source-native evidence.
- **Video:** container/track inventory, PTS-native scene/shot/frame/time segments, audio extraction into the audio baseline, embedded subtitle extraction into independent subtitle sources, and bounded visual/environment/object plus temporal observations. Unsupported codecs are classified and quarantined rather than promised as universally decodable.
- **Subtitles:** independent SRT/ASS/WebVTT/TTML/SAMI/MicroDVD/MPL2/TMP parsing with language, timing, style, speaker, sign, song, and HI/SDH metadata preserved; non-UTF-8 handling and mandatory `X-TIMESTAMP-MAP` normalization are tested. A track is never flattened into another track or treated as authoritative.

Higher-fidelity VLM, diarization, forced alignment, detector coverage, and additional-container stages are extensions behind the same contracts. Their absence cannot silently promote weaker evidence into semantic truth.

### Text/book and composed sequential art

- TXT uses deterministic decoding/normalization with raw bytes retained. Markdown uses pinned sandboxed pandoc or a pure parser, producing normalized structure. EPUB uses ebooklib with explicit AGPL licensing review and EPUB CFI locators. Viable text PDFs use permissive pdfplumber/pypdf; pages without a usable text layer may be routed through the image/OCR path. PyMuPDF is not a default because its license requires a separate acceptance decision.
- Emit document/work/edition/chapter/section/paragraph/sentence/token-span segments; deterministic dialogue/narration segmentation first; semantic analysis emits entities, aliases, candidate speakers, events, locations, relationships, and semantic segments.
- Raster pages can compose with text extraction for manga/comic/webtoon-like sources; page/panel/region/speech-bubble/caption hierarchy remains source-specific.

### Raster images

Pillow handles bounded decode/metadata and crops. PaddleOCR is the preferred scene/CJK/vertical path, with Tesseract as a CPU/clean-text alternative; OpenCV/custom deterministic segmentation emits regions/panels/reading order. Object/person/face observations and spatial relationships are evidence-bearing, while descriptions are model interpretations with confidence and input locators. Every crop has an IIIF-compatible region selector.

### Audio

Decode and time segmentation run in the sandbox. VAD precedes ASR. faster-whisper is the self-hostable baseline with explicit decoder settings and word timestamps. The four-stage hallucination control is: VAD/no-speech classification; logprob/compression/no-speech gates; acoustic-energy correlation; and an auditable promotion ban. Add `condition_on_previous_text=False` where appropriate, beam-size policy for music-heavy audio, and BoH/de-looping where available. Filter decisions append `HallucinationFiltered` with all signals; raw ASR remains untrusted OCFL evidence and ASR confidence is transcription-scoped, never semantic truth.

Diarization/speaker embeddings use pyannote only behind the licensing/gating decision and vendored pinned weights; otherwise emit `speaker_unknown_N` candidates and use a documented fallback. Emit language, utterance/speaker-turn intervals, candidate speakers, music regions, sound events, timing, and semantic utterances.

### Video and independent subtitles

PyAV/FFmpeg demux/decode, PySceneDetect scene/shot detection, PTS-native frames, audio extraction, subtitle-track inventory, and image/audio branches run in the sandbox. Emit file/track/episode/scene/shot/frame/region/time segments, visible entities/environment/objects, ASR, speakers, temporal events, music/SFX, and all embedded-track metadata.

Every subtitle track is an independent source/evidence stream. Extract each track separately and preserve language, track/disposition, timing, styles, speaker labels, signs, songs, typesetting, HI/SDH markers, and translation differences. pysubs2 handles SRT/ASS/WebVTT/TTML/SAMI/MicroDVD/MPL2/TMP after normalization. A mandatory WebVTT pre-normalizer parses `X-TIMESTAMP-MAP=LOCAL:...,MPEGTS:N`, shifts cues by `N/90000 - LOCAL`, strips the header, and records the transformation. Non-UTF-8 input uses charset probing and surrogate-preserving handling; raw bytes remain authoritative. Subtitle, audio, video, and related-language/text correspondences are explicit assertions, never a flattened subtitle table.

---

## Locators and provenance

## Locator grammar and lifecycle

Canonical form:

`source://<work-or-source-id>/<modality>/<deterministic-segment-id>@v<segmenter>.<decoder>.<renderer>?frag=<selector>`

Segment IDs are deterministic from canonical source/work content identity, modality, and structural path; use a collision-resistant hash and URL-safe encoding. Structural paths are stable where content and parser versions are stable. Text uses EPUB CFI or structural selectors plus text-location assertions; image/page regions use IIIF `xywh`/`pct`; audio/video/subtitles use Media Fragments-compatible `t=start,end`, `track`, and optional spatial selectors. Byte offsets alone are forbidden.

OCFL uses sha512 content-addressed objects and inventory/fixity. `SourceAliased` groups byte-different reuploads/releases/transcodes into work membership without deduplicating them. `LocatorRebased` records old/new locators and affected references. If a structural path cannot resolve, quarantine it with `PATH_UNRESOLVED`; never drop or silently edit it. Decoder/renderer/segmenter changes create a new locator version and selective invalidation. Retrieval returns bounded source-native text, image crop/panel, frame/clip metadata, audio clip, or subtitle event plus normalized representation, neighboring context, evidence, claims, and provenance. The design makes locator drift visible and rerunnable; it cannot make changed content address-equivalent.

---

## Alignment, entity resolution, time, and contradictions

## Cross-source alignment

Store typed confidence-bearing many-to-many `Aligned` assertions; never merge evidence. Direct parallel novel/translation sentence alignment uses Vecalign, restricted to monotone parallel text and labeled `parallelity_assumption=PARALLEL_MONOTONE`. Word/term signals may use awesome-align/SimAlign. Adaptation, subtitle, and non-parallel sources use timecode/DTW, scene/chapter order, embeddings, entity/event overlap, speaker sequence, visual/audio correspondence, and optional model reconciliation, labeled `ADAPTATION` or `TEMPORAL`. Every alignment includes method, input refs, confidence, assumptions, omissions/additions/reordering/contradiction metadata, and continuity scope. One-to-many, many-to-one, many-to-many, omitted, and adaptation-only events are first-class.

## Reversible entity resolution

Persist every source mention, name/script/transliteration/title/nickname/OCR form, speaker label, face cluster, and unknown placeholder. Candidate generation uses normalized names, transliteration, soundex, high-cardinality speaker/face clusters, and MinHash/LSH. splink >=4.0.16 provides interpretable linkage scoring; train with a fixed seed, persist settings and trained m/u tables as an OCFL artifact, and use predict-only incremental runs. Benchmark current DuckDB versus 1.3.x at build; pin 1.3.x if blocking or u-estimation is >=3x slower than the baseline. Run linkage in bounded batches/sandbox.

A merge is a log record, not a delete. Aliases remain assertions. Unknown entities retain candidate sets and may later resolve. Split enumerates all references at split-time, carries assignments, emits `ReferenceRebound`, and quarantines ambiguous targets. Tests must prove all mentions and alignment/override/candidate/evidence references can be restored.

## Temporal/spatial semantics

Represent source-local media time, timecodes, narrative sequence, story chronology, valid-time intervals, flashbacks, simultaneous events, unknown order, and cross-source temporal correspondence separately. Represent locations, sublocations, participants, objects, visual/audio environment, weather, lighting, and relative positioning as provenance-bearing assertions, not only free text. Similar-looking realizations across continuities remain distinct and may CONTRADICT or ALTERNATE_REALIZATION.

---

## Jobs, invalidation, projections, and search

## Durable stage execution

Hatchet is the sole v1 runner for the explicit DAG. Dagster is absent; no second scheduler may decide recomputation. The in-repository DAG definition is the single lineage source and generates `stage_dependency(stage, depends_on_stage, evidence_class)`. Hatchet's exact version is pinned only after retry/cancel/restart shape tests; its engine idempotency is advisory.

Each stage run has a deterministic idempotency key from source/segment, stage, input evidence refs, stage schema, extractor/decoder/provider versions, and configuration digest. Winning `stage_run` insertion (`UNIQUE(idempotency_key)`), artifact references, and `StageCompleted` append happen in one PostgreSQL transaction; a crash cannot commit completion without evidence. `job_run_audit` records start/retry/fail/complete/cancel independently of semantic replay. Transient failures retry with bounded backoff; deterministic malformed-input failures quarantine and permit independent branches; authority projection failures pause and alert.

`Invalidated` records identify causation, scope, stage, and affected refs. The pure planner traverses only descendants in the lineage graph. Re-running speaker resolution does not re-run OCR/ASR/segmentation; a filter-version bump reclassifies ASR descendants; a correction schedules only affected resolution/presence/alignment/reconciliation/projection assets. DAG-version changes drain/cancel in-flight work before activating a new manifest universe.

## Tier-1 projections and search

Current-state, exact/full-text, and vector tables are rebuildable from the ledger and source/evidence registries. V1 bounded graph-like reads use the typed relational semantic/current-state tables; a future graph projection follows the same replay-only rule. Builders checkpoint applied `seq`, are idempotent, use canonical ordering, and publish blue/green versions with a grace period; connection pools set `search_path` at checkout. A non-authoritative poison event may be quarantined and counted; authority-relevant events pause the projection. No projection is an authority.

Use PostgreSQL tsvector/pg_trgm for exact phrase/name/fuzzy source search and structured locator filters. Store embeddings in a separate append-only `embedding` table, one immutable row per segment/model/evidence version; never UPDATE HNSW-indexed rows. pgvector 0.8.6 (at least 0.8.2) uses HNSW with exact-search fallback and scheduled concurrent reindexing. Keep vectors behind `VectorIndex`; measured 5M/10M/50M growth thresholds trigger review of halfvec/pgvectorscale/dedicated-store promotion. Hybrid ranking fuses exact and cosine scores and labels result kind.

The v1 structured query service compiles supported graph-like operations to indexed SQL and bounded recursive/iterative traversal; it supports the required scene/entity/utterance/evidence/correspondence/contradiction/unresolved-alias questions and confidence/continuity/time filters. Optional Neo4j CE or RDF-star projection adapters may be added later behind the same query/projection contract when measured unbounded traversal, graph algorithms, or RDF interoperability justifies their operational and licensing costs. XTDB is only a gated future witness, never a v1 dependency.

---

## Provider/plugin interfaces

Conceptual Python protocols (names are normative, implementation packaging may vary):

```text
Ingestor.ingest(descriptor, immutable_input) -> SourceManifest
Segmenter.segment(manifest) -> SegmentBatch
Extractor.extract(stage_input) -> EvidenceBatch
Analyzer.analyze(stage_input) -> StageOutput
Reconciler(Analyzer).reconcile(stage_input) -> StageOutput
Aligner.align(left_refs, right_refs, context) -> AlignmentEvents
Resolver.resolve(candidates, policy) -> ResolutionEvents
ModelProvider.invoke(request{mode, model, prompt/input_refs}) -> StructuredModelResult
Embedder = ModelProvider(mode=embedding)
ProjectionBuilder.replay(event_batch, checkpoint) -> ProjectionCheckpoint
LocatorResolver.resolve(locator, version_policy) -> SourceRange
QueryService.structured(query) -> ProvenanceBearingPage
QuestionService.answer(question, constraints) -> StructuredAnswer
```

All outputs carry evidence/locator refs, schema/tool/model/provider versions, configuration digest, confidence/uncertainty, warnings, and metrics. Model invocation records include model, version, prompt/instruction version, input evidence refs, structured output, timestamp, dependency stage, and cost/timing. Provider adapters include local Ollama for self-hosting, optional vLLM for higher-throughput deployments, and remote providers through a provider-neutral client/router. Provider substitution tests use the same fixture and contract; no provider is allowed to write semantic state directly. Storage adapters cover OCFL and Postgres first, with future object/vector/graph implementations hidden behind interfaces.

---

## Security and observability

Uploaded bytes, archives, filenames, codecs, subtitles, and derived parser inputs are untrusted. The API never shell-interpolates; subprocess arguments are arrays. File size/count, decompressed-size, duration, pixel, CPU, memory, fd, process, and timeout limits are enforced. Archive extraction uses explicit allowlists, rejects absolute/traversal/symlink escapes, and occurs only in the sandbox. User filenames never form paths or object keys.

The dedicated sandbox-runner uses bubblewrap with read-only binds, `--die-with-parent`, rlimits/cgroups, seccomp policy, isolated namespaces, and a local read-only spool staged from OCFL at task start; remote/FUSE mounts are not assumed to work in a user namespace. PyAV/FFmpeg, pandoc, OCR, ASR, diarization, subtitle parsing, linkage, and archive handling run in the sandbox, never in the API process. Bare metal/VM with the Ubuntu profile is first-class. A container runner may require documented minimal `SYS_ADMIN`, seccomp, and host AppArmor configuration and is never `--privileged`; managed Kubernetes is conditional. The sandlock alternative is unvalidated and cannot be presented as a shipped security guarantee until the sandbox spike proves maintenance and capability.

Pin Python to a tarfile-CVE-fixed release (3.12.11+ preferred, or equivalent fixed supported line), FFmpeg/PyAV to CVE-fixed builds, and maintain a standing CVE watch. The July-2026 FFmpeg/VobSub risk is contained by the boundary, not eliminated. AGPL dependencies (ebooklib, optional PyMuPDF, and any selected model/tool) require explicit distribution/license review; use permissive alternatives where practical.

Emit structured JSON logs with correlation/job/source/stage IDs; OpenTelemetry traces; metrics for queue depth, stage duration, retries/failures, model calls/tokens/cost, parser exit class, cache hits, projection lag/checkpoint, stale/503 responses, HNSW maintenance, and sandbox denials. A source decomposition report explains incomplete/slow stages, versions, warnings, resource use, and retry history. Hatchet OSS audit logs are not assumed; job-run audit is owned and retained by the application ledger.

---

## Deployment, migrations, fixtures, documentation, and rollout

## Packaging and persistence

Provide Dockerfile(s), Docker Compose for API/worker, Postgres 18.6 + pgvector 0.8.6, OCFL filesystem/MinIO-compatible object storage, Hatchet, and optional Ollama; configuration is environment-driven with `.env.example`. Alembic owns structural migrations. Event payload changes use schemas/upcasters and never rewrite historical events. Backups cover Postgres ledger/current state and OCFL inventories/bytes independently; restore verification replays the ledger and validates fixity.

The implementation should pin FastAPI 0.141.1, Pydantic v2 (2.13.x line), SQLAlchemy 2.0.x, ocfl-py 2.1.0, pysubs2 1.9.0, and other dependencies only after the stated build/license/CVE gates. Startup health checks distinguish ready, degraded, and rebuilding dependencies. Capability responses disclose enabled modalities, providers, sandbox posture, query depth, and projection freshness.

## Fixtures and documentation

Generate small deterministic media fixtures rather than committing large binaries: TXT/Markdown/EPUB/PDF, translated/adapted books, raster/comic pages with panel/bubble/CJK cases, multi-speaker audio, dialogue video with multiple tracks, SRT/ASS/WebVTT/TTML/SAMI/MicroDVD/MPL2/TMP including HI/SDH and nonzero `X-TIMESTAMP-MAP`, contradictory sources, missing/reordered events, and adaptation-only events. Add malformed containers, VobSub-like inputs, non-UTF-8 subtitles, zip bombs, tar traversal, VFR/edit-list, music-under-speech, and corrupt encodings. Lock fixture generation to the tested FFmpeg build.

Documentation must include architecture and ownership diagrams; source/evidence/semantic/graph-like models; event/upcaster policy; provenance and locators; DAG/invalidation and consistency semantics; overrides and reversible ER; multilingual/adaptation/continuity handling; provider/plugin authoring; storage/deployment/security/observability; endpoint/query examples; testing and known limitations. No design doc or API text may imply a downstream media-generation product.

## Rollout and versioning

1. Establish repository/runtime, OCFL fixity, Postgres migrations, event schemas/upcasters, reducer, and audit invariants.
2. Add deterministic locators/segments and ingestion descriptors, then wire the durable DAG and stage dedup/repair behavior.
3. Enable text/image pipelines, then audio/video/subtitle pipelines only after sandbox, FFmpeg, WebVTT, ASR-filter, and pyannote gates are satisfied.
4. Add resolution/alignment, Tier-0 and Tier-1 search/query projections, and provider substitution.
5. Run generated integration/E2E/adversarial suites, restore/replay checks, security review, and final correctness review before production.

A stage/model/decoder/locator/ontology change creates a versioned manifest/DAG universe. In-flight work is drained or canceled, old locators and events remain readable, and new derived artifacts supersede rather than mutate old ones. API versions are additive and explicitly versioned; breaking contract changes require a new API version and migration notes. Every event schema version remains replayable through an upcaster chain.

---

## Testing strategy and acceptance criteria

## Test layers

- **Unit/property:** stable ID and locator grammar/round-trip/version precedence; segment determinism; source-native range resolution; OCFL fixity; typed assertions/predicates; evidence/provenance traversal; confidence and candidate thresholds; temporal/spatial assertions; aliases and multilingual scripts; merge/split reversibility; split-time reference enumeration; `ReferenceRebound`; invalidation descendant selection; event idempotency; upcasters; reducer totality, <=5ms p99 Tier-0 target, and payload-construction conformance.
- **Projection/replay:** wipe current state and each Tier-1 projection, replay from `seq=0`, and compare canonical checksums. Assert no non-builder code can write projection stores, no authoritative event is skipped, blue/green swap has no stale pooled connections, and event versions all upcast. Deterministic stages are byte-exact; ASR/OCR/diarization/linkage use tolerance metrics and fixed fixture/model metadata.
- **Integration:** execute all v1 modality fixtures; verify chapters/paragraphs/sentences/dialogue/entities/events/locations; image metadata/OCR/regions/objects/spatial; audio language/ASR/turns/music/SFX/timing; video tracks/scenes/shots/frames/ASR/speakers/visible entities/environment/events; independent subtitle languages/styles/HI/SDH/signs/songs and timestamp-map correction.
- **Adversarial security:** malformed codec/container, VobSub, oversized declared allocations, zip bomb, tar traversal/symlink, path escape, non-UTF-8 subtitle, FUSE/remote-spool failure, timeout/OOM/fd/pid limit, parser crash, sandbox syscall denial, and API authorization/query-cost/rate-limit tests.
- **End-to-end mandatory path:** ingest several related heterogeneous sources -> decompose independently -> align -> resolve shared entities -> produce semantic graph-like answer -> return supporting locators -> apply user correction -> append override/invalidation -> prove unaffected OCR/ASR/segments retain IDs/checksums -> rerun only descendants -> assert corrected Tier-0 and Tier-1 answers (including confidence) are equivalent -> audit explains current/prior/change.
- **Operational:** cancel/retry/restart workers and sandbox containers; late-stage failure resumes without repeating successful stages; concurrent duplicate stage submissions yield one authoritative completion; projection pause/poison behavior; Postgres/OCFL restore and replay; provider substitution; Docker health/readiness and migration startup.

## Acceptance criteria

The DD is accepted for implementation only when the resulting release demonstrably: (1) preserves source/evidence/semantic/knowledge separation; (2) ingests all v1 modality inputs and retains independent subtitle tracks; (3) provides stable versioned locators and bounded source-native retrieval; (4) records evidence, model/tool/version/confidence/provenance and contradictions; (5) supports many-to-many alignment and reversible entity resolution across languages/adaptations; (6) supports all listed semantic/segment edits, overrides, locks, audit, invalidation, and selective reruns; (7) survives restart with durable jobs; (8) exposes OpenAPI typed REST, structured/semantic queries, exact/hybrid search, health/capabilities, pagination, and structured errors; (9) passes the correction -> invalidation -> selective-rerun cross-tier test; (10) passes Docker, migration, static/type/lint, unit, integration, E2E, adversarial security, and final review gates; and (11) never treats graph/vector/search projections or model output as unrecoverable authority.

---

## Limitations, extension paths, risks, and gates

## Accepted limitations and extensions

- **Bounded v1 graph traversal:** typed REST over Postgres covers required bounded questions. Add Neo4j CE or another GQL-compatible disposable projection only after measured unbounded traversal/graph-algorithm demand; add RDF-star projection only for funded interoperability; add XTDB witness only after its GA/compaction/CDC/read-path gate.
- **Vector scale:** pgvector is the v1 projection. Monitor vector count, recall, HNSW build memory, and write churn; review at 5M/10M/50M measured thresholds and migrate through `VectorIndex` without changing authority.
- **Locator drift:** content, EPUB structure, decoder, and renderer changes may invalidate locators. `@v`, `SourceAliased`, `LocatorRebased`, quarantine, and selective invalidation detect/manage it; they do not eliminate it. Forced alignment is a future audio extension.
- **ASR hallucinations:** filter signals are best-effort (the adversarial record reports weak detector performance). The enforceable control is raw-evidence retention, `HallucinationFiltered`, transcription-scoped confidence, and a prohibition on automatic semantic promotion. Internal-state detection is optional phase 2.
- **Adaptation alignment:** parallel-only Vecalign is intentional; nonparallel adaptations use less granular but more honest temporal/embedding/LLM evidence.
- **Reducer common mode:** one reducer avoids Tier-0/Tier-1 drift but can share a bug; pure/total contracts, payload tests, replay checks, and cross-tier E2E bound the risk.

## Surviving risk register and gates

- **U1 high:** pyannote weights/license is undeclared and gated; legal sign-off or non-gated/deferred fallback before commercial release.
- **U2 medium:** hallucination filter efficacy; measure FPR/FNR and enforce promotion ban.
- **U3 medium:** splink #3023/u-estimation and DuckDB planner risk; benchmark actual blocking keys and pin DuckDB 1.3.x on >=3x regression.
- **U4 medium:** bubblewrap/AppArmor/user namespace/capability matrix, especially Ubuntu 24.04 manual profile; sandbox spike required.
- **U5 medium:** filter threshold must carry its own version/input dependency and invalidate ASR descendants.
- **U6 medium:** SPLIT must enumerate references at split-time, not only the merge snapshot.
- **U7 low/medium:** OCFL remote/FUSE access; stage through local read-only spool and validate crash cleanup.
- **Hatchet medium:** exact release remains open; test retry/cancel/restart and retain mechanical Temporal fallback if workflows require deterministic multi-entity sagas or signal-heavy human waits.
- **FFmpeg/PyAV medium-high:** CVE stream; fixed pins, sandbox boundary, parser-policy CI, and standing watch.
- **pgvector medium-high:** CVE-2026-3172 requires >=0.8.2; separate immutable embedding table, concurrent reindex, and recall checks.
- **Upcasters medium:** permanent historical-schema/replay staffing and CI, never mutate historical events.
- **Licensing:** ebooklib/PyMuPDF/other AGPL or gated model terms are build/release gates, not silently accepted facts.

## Rejected alternatives

Mutable Neo4j authority plus changelog was rejected because it recreates dual-write/rebuildability failure and CE lacks authority-grade HA/backup/RBAC. RDF/GraphDB authority was rejected for v1 due to production licensing, RDF-star versus RDF 1.2 semantic uncertainty, second-authority/outbox lag, and operational cost; its projection path remains possible. XTDB authority was rejected because supplied evidence records no recursive CTE support, a compaction/readability issue, and a still-RC external-source path; it may become a gated witness. Kuzu is discontinued; Memgraph disk mode is unstable/in-memory risk; Apache AGE has unacceptable reported complex-query behavior for the default. Dedicated vector storage is deferred until measured scale. Dagster is omitted because Hatchet plus one in-repository lineage definition avoids two schedulers. A giant opaque pipeline and raw RAG semantic layer violate rerun/provenance requirements.

## Process gate

`DD_REQUIRED` is **IMMUTABLE**. All eight adversarial refinement turns **T1–T8 are complete**, and the DD carries their surviving risks, corrections, human questions, and build gates. This document is the canonical implementation design; it does not replace the complete adversarial log and does not claim implementation completion.

---

## Operational SLOs and release gates

Initial measurable targets (to be confirmed against deployment hardware during implementation) are: Tier-0 current-state p99 <=5 ms under the merge/override burst fixture; token-bearing Tier-1 reads never return data older than the requested token and fail with the documented 503 contract when the bounded wait expires; deterministic segment/locator/reducer/projection replay is checksum-equivalent; stage completion is effectively-once under duplicate submissions through the database key and transaction boundary; restart resumes at the last committed stage without repeating successful stages; source retrieval returns the requested bounded native range and fixity verifies; health/readiness identifies degraded dependencies; and every accepted semantic mutation has an audit explanation with actor, causation, prior/current state, evidence, and generated-by metadata.

Release is blocked by any lost provenance path, direct projection write, in-place semantic mutation, flattened subtitle track, unresolved authoritative poison event, non-reversible merge/split, stale post-correction token read, unsafe archive/path escape, missing local model path where required, failed cross-tier correction E2E, failed restore/replay, unreviewed gated model/license, unpinned vulnerable parser, or unverified sandbox target. The implementation must run static/type/lint checks and the complete automated suite before the final adversarial correctness review; any repair requires rerunning the full validation suite.

---

## References and evidence boundary

Primary references are the supplied artifacts and their cited standards/maintainer sources, checked in the upstream reports on 2026-08-25:

- `/workspace/Universeity/Task.md` §§1–41, lines 1–1739.
- `/workspace/Universeity/artifacts/designs/process/universal-media-decomposer-technology-research.md`.
- `/workspace/Universeity/artifacts/designs/process/universal-media-decomposer-adversarial-log.md` (T1–T8; complete process record).
- `/workspace/Universeity/artifacts/designs/process/universal-media-decomposer-architecture-options.md`.
- `/workspace/Universeity/artifacts/designs/process/universal-media-decomposer-complexity-review.md`.
- `/workspace/Universeity/artifacts/designs/process/universal-media-decomposer-final-estimate.md`.
- `/workspace/Universeity/artifacts/logs/support-librarian.log.jsonl` and `/workspace/Universeity/artifacts/logs/support-researcher.log.jsonl`.
- `/workspace/Universeity/artifacts/pending/DD-universal-media-decomposer.md` (manager input skeleton; superseded by this document).
- OCFL 1.1; EPUB CFI/EPUB 3.3; W3C Media Fragments; IIIF Image API 3.0; W3C Web Annotation; PROV-O/PROV-DM.
- FastAPI/Pydantic, PostgreSQL/pgvector, Alembic/SQLAlchemy, ocfl-py, Hatchet and Temporal documentation; modality maintainer sources for pandoc, ebooklib, pdfplumber/pypdf, Pillow, PaddleOCR/Tesseract, PyAV/FFmpeg, faster-whisper, pyannote, PySceneDetect, pysubs2, Vecalign, splink, Ollama/vLLM, and bubblewrap.
- The upstream adversarial citations for event-schema evolution and dual-write failures, pgvector CVE/scale, Hatchet audit/durability, WebVTT timestamp mapping, FFmpeg parser CVEs, ASR hallucination limits, and RDF-star/RDF 1.2 semantics are evidence boundaries rather than blanket technology guarantees. Exact build-time versions and legal status must be revalidated before release.

---
