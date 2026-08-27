# Universal Media Decomposer cross-plan contracts

These contracts are derived from the approved DD and are binding across plans A–F. Implementations may package them differently, but may not weaken their ownership, provenance, versioning, or consistency semantics.

## Core and storage

- `SourceStore.put_immutable(stream, descriptor) -> SourceManifest` — writes content-addressed OCFL bytes, verifies sha512 fixity, never uses a user filename as a key.
- `SourceStore.get_range(source_ref, start=0, length=None, *, version=None) -> NativeRepresentation` — returns a bounded slice (capped to `max_read_buffer_bytes`) plus full-object fixity metadata (sha512 + size), honoring `@v` version selection.
- `SourceRepository.create_source(manifest, descriptor) -> Source` — owns source/work/continuity/edition/translation/adaptation membership in PostgreSQL.
- `SegmentRegistry.register(batch) -> SegmentBatch` — deterministic stable segment IDs and versioned locators; byte offsets alone are invalid.
- `LocatorResolver.resolve(locator, version_policy) -> SourceRange` — resolves bare and explicit `@v` locators, reports drift, and quarantines `PATH_UNRESOLVED` rather than silently repairing.
- `EvidenceRepository.record(batch) -> EvidenceBatch` — stores references to OCFL-derived artifacts with source locator, extraction stage, tool/decoder/model versions, configuration digest, and confidence/quality metadata.

## Plugin and stage envelopes

- `Ingestor.ingest(descriptor, immutable_input) -> SourceManifest`
- `Segmenter.segment(manifest) -> SegmentBatch`
- `Extractor.extract(stage_input) -> EvidenceBatch`
- `Analyzer.analyze(stage_input) -> StageOutput`
- `Reconciler.reconcile(stage_input) -> StageOutput` — typed Analyzer sub-interface, not a second framework.
- `Aligner.align(left_refs, right_refs, context) -> AlignmentEvents`
- `Resolver.resolve(candidates, policy) -> ResolutionEvents`
- `ModelProvider.invoke(request{mode, model, prompt, input_refs}) -> StructuredModelResult` — `mode` is `completion|embedding`; local and remote adapters are interchangeable.
- `ProjectionBuilder.replay(event_batch, checkpoint) -> ProjectionCheckpoint` — projection builders are the only writers to their projection stores.

Every stage input carries source/evidence refs, locator version, stage schema version, extractor/decoder/renderer/provider versions, configuration digest, and DAG universe. Every output carries artifact/evidence refs, semantic events where applicable, confidence/uncertainty, generated-by metadata, warnings, and metrics.

## Semantic authority and audit

- `SemanticLedger.append(events, expected_version, idempotency_key) -> CommitResult(seq, read_your_writes_token)` — append-only PostgreSQL authority; no direct semantic UPDATE.
- `reduce_current_state(current_row, event) -> current_row` — pure, total, deterministic, bounded to indexed operations; the same implementation serves inline Tier-0 and replay. (`CurrentStateReducer.reduce(state, event)` is a thin alias/wrapper over the same pure per-row reducer.)
- `AuditService.explain(subject, as_of, causation, correlation) -> ChangeExplanation` — explains current, prior, actor, evidence, generated-by, and change cause.
- `StageRunRepository.claim(idempotency_key, manifest) -> StageRunClaim` — PostgreSQL `UNIQUE(idempotency_key)` is authoritative; handler checks it before side effects.
- `JobRunAudit.record(attempt) -> JobAuditRecord` — separate operational audit stream/table, not semantic replay input.
- `InvalidationPlanner.plan(causation, scope, stage, lineage) -> StageTargets` — descendant-only, pure planning; unaffected extraction/evidence is retained.

`MERGE`, `SPLIT`, `ALIAS`, `ReferenceRebound`, `OverrideApplied`, `CorrectionApplied`, `Locked`, `Unlocked`, `Invalidated`, `LocatorRebased`, `Aligned`, `ContradictionRecorded`, `HallucinationFiltered`, and stage completion events are versioned payloads. Historical payloads are immutable and replayable through upcasters. SPLIT enumerates every reference at split-time, assigns or quarantines ambiguous targets, and never deletes mentions.

## Query, retrieval, and API

- `QueryService.structured(query) -> ProvenanceBearingPage` — typed filters, confidence/continuity/time scope, bounded traversal, result kind labels.
- `QuestionService.answer(question, constraints) -> StructuredAnswer` — compiles supported questions to typed operations; never answers from unstructured-only RAG.
- `SearchService.hybrid(query, filters) -> KindTaggedSearchPage` — exact `tsvector/pg_trgm` plus pgvector; immutable append-only embedding rows are separate from churned metadata.
- `EvidenceRepository.get(locator_or_range) -> NativeRepresentation` — text, image crop/panel, frame/clip metadata, audio clip, or subtitle event with neighboring context, evidence, claims, and provenance.
- `API` exposes versioned REST for ingest, source metadata/segments/analysis/report, locators, evidence/claims, entities, edits/overrides/locks, alignment, jobs, rerun/invalidation, structured/semantic query, search, audit, health, readiness, capabilities, and version.

Mutations return a read-your-writes token. Token-bearing Tier-1 reads wait only within the bounded lag budget, then return `503` with `Retry-After` and `x-consistency: transient-lag` or `rebuild-in-progress`; they never return stale post-correction answers. Untokened reads expose freshness metadata. Errors are RFC 7807-compatible and collections are cursor/page paginated.

## Modality and security contracts

- Text/book: TXT, Markdown, EPUB, viable text PDF; image-only PDF routes to raster/OCR; deterministic document/chapter/section/paragraph/sentence/token spans and evidence-linked structural semantics.
- Raster/sequential art: bounded Pillow decode/metadata, deterministic page/region/panel ordering, OCR, spatial observations, object/person candidates, descriptions, IIIF-compatible crops.
- Audio: sandboxed decode/chunking, VAD before faster-whisper ASR, word/time ranges, language, music/SFX, speaker candidates, timing, four-signal hallucination filter, transcription-scoped confidence, promotion ban, and `HallucinationFiltered` dependency edge.
- Video: sandboxed PTS-native demux, tracks, scenes/shots/frames, audio branch, independent embedded subtitle sources, bounded visual/environment/object/temporal observations; unsupported codecs quarantine.
- Subtitles: independent SRT/ASS/WebVTT/TTML/SAMI/MicroDVD/MPL2/TMP sources; language, timing, styles, speaker/sign/song/typesetting, HI/SDH, encoding, translation differences; mandatory `X-TIMESTAMP-MAP` normalization before pysubs2.
- `SandboxRunner.run(argv, limits, policy) -> SandboxResult` — array arguments only, read-only spool, archive allowlists, traversal/symlink rejection, bounded CPU/memory/fd/pid/time/duration/pixels/decompressed size, parser failure containment. PyAV/FFmpeg, pandoc, OCR, ASR, diarization, subtitle parsing, linkage, and archive extraction never run in the API process.

## Non-negotiable limits and extension paths

V1 graph-like queries are bounded Postgres traversal; Neo4j/GQL, RDF-star, and XTDB are replay-only future extensions behind interfaces. pgvector is monitored at 5M/10M/50M thresholds and may migrate behind `VectorIndex`. Locator stability is bounded by content/parser/decoder/renderer stability; drift is versioned, detectable, rebased, or quarantined. Vecalign is parallel-text-only; adaptations use temporal/embedding/LLM methods with assumptions. Pyannote weights/license, Hatchet pin, splink/DuckDB benchmark, bubblewrap/AppArmor profile, FFmpeg/PyAV CVE watch, AGPL dependencies, and local OCFL spool behavior are explicit build/release gates, not silently resolved.
