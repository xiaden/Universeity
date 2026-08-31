---
name: umd-semantic-capability-repairs
description: UMD semantic-capability repair surfaces — production text/book format dispatch gaps, deterministic vs provider-backed text analysis, placeholder entity resolution/reconciliation, multi-valued relationship representation, parity oracle design, and the tests/docs/fixtures that must change. Load when planning the semantic capability repairs (format routing, semantic analysis, entity resolution, reconciliation, multi-edge reads, parity oracle, book fixture/E2E).
---

# UMD Semantic Capability Repairs

## Mental Model
The production pipeline (`src/umd/jobs/production.py`) runs 9 stages (dag.py:30-40)
via a composed StageWork registry. For TEXT sources it currently bypasses the
extractor/dispatch layer entirely: `_parsed_text` always `normalize_txt(raw).text`
(UTF-8 decode with `errors="replace"`), `_basic_segmentation` always calls
`segment_txt`, and evidence is emitted against hardcoded `chapter/1/...` paths —
so Markdown/EPUB/PDF routing, format-correct segmentation, and multi-chapter
locator fidelity are all broken. Semantic stages are placeholders: ENTITY_RESOLUTION
creates ONE ALIAS canonical per source, SEMANTIC_RECONCILIATION asserts a single
`RECONCILED_SOURCE` predicate. The real primitives (ModelProvider, CandidateGenerator,
typed predicates, semantic_assertion table, QueryService) all exist but are not wired
into the text path. The repair ledger (caller-provided, NOT in repo) adds: provider-backed
semantic text analysis, >=3 canonical characters with aliases/ambiguity, rich KG
assertions + public query/search, active multi-edge read side, generic parity oracle
walking 2a-2f with a final parity matrix, a >=2-chapter book fixture, and a public
production StageWork E2E — all without new DBs/Neo4j/opaque LLM/audiobook schema.

## Coverage
**Documented:** production stage wiring & placeholder gaps; extractor/segmenter inventory;
analysis/text_structural limitations; ModelProvider/registry surface; resolution
candidate/mention machinery; reconciliation command path; tables that can host typed
semantics; projection/query/search surfaces; test/fixture/doc inventory.
**Not yet documented:** exact diff-level fix plans, the semantic-analysis prompt/parser
design, the parity oracle implementation, edge-projection migration DDL.
**Last extended:** 2026-08-30

## Key Findings

### Production text path bypasses dispatch and segmenters
- `_parsed_text` (src/umd/jobs/production.py:313-317) ALWAYS `normalize_txt(raw).text`
  regardless of `src["media_kind"]` — EPUB/PDF/Markdown bytes coerced via UTF-8
  `errors="replace"` (txt.py:80) = binary UTF-8 coercion, lossy for EPUB/PDF.
- `_parser_for` (production.py:319-324) maps markdown→"markdown", epub/pdf→fmt, else
  "txt" but is used ONLY for FORMAT_ANALYSIS metrics (line ~920), never for parsing.
- `_basic_segmentation` (production.py:940-969) always calls `segment_txt`; the
  correct `segment_markdown` (segmenters.py:239) and `segment_epub` (segmenters.py:347)
  exist but are never invoked from production.
- `dispatch.parse_document` (extractors/dispatch.py:63-78) HAS the correct routing
  table (txt→normalize_txt, markdown→parse_markdown, epub→extract_epub(path), pdf→
  detect_pdf_text) — production just never uses it for text.
- `_emit_low_level_text_evidence` (production.py:394-422) hardcodes doc path
  "document/1" and paragraph paths "chapter/1/section/1/paragraph/{idx}" — wrong
  chapter index for multi-chapter books; evidence.segment_id linkage depends on
  `_segment_row_ids` (337-351) matching those paths, else NULL.
- Evidence IDs are random UUIDs (`row_id = _uuid_hex()`, repositories.py:248) — the
  "deterministic IDs" requirement is unmet for evidence (dedup is via
  uq_evidence_identity (source_id, locator, evidence_kind, config_digest) ON CONFLICT
  DO NOTHING, repositories.py:212-290).

### Deterministic structural analysis is single-chapter
- `analyze_text` (analysis/text_structural.py:91-153) hardcodes chapter=1 in
  `_locator_for` (77-78) and emit path (117); only dialogue/narration text_span +
  entity candidates (capitalized runs appearing >1x in paragraph) + co-occurring
  relationship candidates (156-215). No scenes/utterances/speakers/traits/emotions/
  states/presence. Linkage to segments is by locator only, not segment_id.
- classify_dialogue + candidate_speaker (quoted/dash attribution) exist.

### Placeholder semantic stages
- `_candidate_mentions` (production.py:424-434) reads committed evidence
  quality.candidate_kind=="entity" → mention_text.
- `_entity_resolution` (1084-1111): ONE `entity:canonical:{src['id']}` ALIAS per
  source; empty-candidate path resolves ALIAS with entity_id=refs[0] (a
  `resolved_entities:` ref!) — pure placeholder. Real machinery unused:
  candidates.py (normalize_name/soundex/minhash/MentionBlockIndex.link),
  mentions.py (SourceMention, deterministic mention_id sha256, MentionService),
  linkage.py (reference model, splink gated).
- `_semantic_reconciliation` (1129-1147): single `assert_semantic("RECONCILED_SOURCE",
  subject_ref=f"reconciled_state:{src['id']}:current", object_ref=src["ocfl_ref"],
  confidence=0.95, state="PROBABLE")` — no typed KG assertions (no SPEAKS/PRESENT_IN/
  ALIAS_OF/... per entity/utterance).

### Provider layer exists but has no text-semantic wiring
- models/provider.py: ModelProvider protocol, ModelRequest (mode COMPLETION/EMBEDDING,
  prompt, prompt_version, config_digest), StructuredModelResult (model_version,
  provider, confidence 0-1), ModelCallRecord.to_evidence (131-183) records the call as
  EvidenceKind.METADATA with full record in quality — "evidence of the call, never a
  semantic assertion". ModelProviderUnavailable. registry.py ProviderRegistry +
  capability_report. Adapters: ollama/remote/vllm (gated UMD_VLLM_ENABLED). Only used
  for ASR/embeddings today; no semantic-analysis prompt/typed-parser exists.

### Typed semantics surface (usable as-is, no migration for predicates)
- EntityType enum (domain/models.py) already covers character, person, organization,
  location, object, concept, scene, event, action, utterance, relationship, state,
  emotion, goal, belief, timeline, presence, speaker_identity, alias,
  visual_appearance, environment, music, sound, correspondence, contradiction.
- PREDICATE_VOCABULARY: SPEAKS, PRESENT_IN, CORRESPONDS_TO, TRANSLATION_OF,
  ADAPTATION_OF, DERIVED_FROM, CONTRADICTS, ALIAS_OF, EXPANDS, OMITS, REORDERS,
  ALTERNATE_REALIZATION; EXTENDED_PREDICATES: MENTIONS, OCCURS_AT, KNOWN_AS,
  SPEAKER_OF, APPEARS_AS, PART_OF, SET_IN. register_predicate validates
  ^[A-Z][A-Z0-9_]{0,63}$ and Predicate model rejects unknown codes — new predicates
  need no migration.
- SemanticAssertion (domain/models.py) carries predicate_code, subject_ref,
  object_ref, authority, confidence, state, continuity_id, narrative_time, spatial,
  support_refs, contradiction_refs, derived_from, generated_by — full Task.md §2
  provenance shape. Event types incl. SemanticAsserted/OverrideApplied/Locked/
  Invalidated/EntityResolved/ReferenceRebound; SemanticEvent.prepare() validates
  against retained JSON schemas + upcasters (events.py).
- commands.py SemanticCommandService: assert_semantic, record_override (USER_OVERRIDE),
  lock/unlock, invalidate, entity_resolve(kind MERGE|SPLIT|ALIAS), record_alignment,
  rebase_locator, stage_completed.
- Tables (storage/postgres/tables.py): entity(328), entity_mention(346), predicate(388),
  semantic_assertion(398-444, indexed predicate/state/authority, support_refs/
  contradiction_refs/derivation JSONB), semantic_event(450), current_state(478, PK
  (entity_ref,predicate) single object_ref), current_entity_map(494), alignment(517),
  embedding(652), quarantine(686), projection_checkpoint(732).

### Multi-valued relationships: history exists, active read side does not
- current_state is ONE row per (entity_ref, predicate): last-write-wins; reducer
  (reducer.py) computes `alternatives` + `contradiction_refs` replay-only and scalar()
  persists ONLY entity_ref/predicate/object_ref/confidence/authority/state/seq.
- ALL assertions persist in semantic_assertion (append-only, immutable) — full history
  is there. Missing: an ACTIVE multi-edge read representation (e.g., replay-built
  edge projection table subject_ref/predicate/object_ref multi-row) and query support;
  QueryService (projections/query.py) reads only _cs (current_state) for
  ENTITY/UTTERANCE/CONTRADICTIONS/UNRESOLVED_ALIASES/TRAVERSAL, _seg for SCENE,
  _ev for EVIDENCE.

### Public query/search surfaces
- QueryService.structured kinds: ENTITY, UTTERANCE, SCENE, EVIDENCE, CORRESPONDENCE,
  CONTRADICTIONS, UNRESOLVED_ALIASES, TRAVERSAL (query.py:201-435); UTTERANCE reads
  predicates in {SPEAKS, SAYS, UTTERANCE, PRONUNCIATION} (query.py:43); SCENE reads
  segment_type in {scene, chapter, shot, frame, section, act} (query.py:46). Bounded
  report + 422 unmappable_scope. SearchProjectionBuilder (search.py:39-151) indexes
  EntityMentioned docs + utterance-predicate SemanticAsserted + CANONICAL_ENTITY rows
  (kind labels SOURCE_EVIDENCE|INTERPRETATION|CANONICAL_ENTITY). QuestionService
  (question.py) compiles UTTERANCE questions. These work once assertions exist.
- Search/query honors consistency tokens → 503 transient-lag, freshness, bounded limits.

### Tests / fixtures / docs inventory
- fixtures.py: FIXTURE_TXT (single "Chapter 1"), FIXTURE_MARKDOWN (1 H1 + 2 H2),
  epub_bytes (ONE spine item), pdf_text_bytes/pdf_image_only_bytes — NO >=2-chapter
  book fixture. Deterministic generators (stdlib zipfile, hand-assembled PDF).
- test_text_parsers.py (parser unit), test_text_segmentation.py (segment determinism +
  dialogue), test_production_stage_registry.py (stage resolution, config_digest dedup
  tests at 142-286), test_production_runner.py (retry/cancel/rerun; test_real_registry_
  retry_deduplicates_and_threads_evidence 342-438), test_api_contract.py (public HTTP
  surface incl. test_spec_first_production_ingestion_persists_real_output 876-940,
  merge/split contract 590-648, multipart ingest 1033), test_projection_phase2.py
  (wipe/replay equivalence, vector/exact search, structured query bounds),
  test_phase3_correction_e2e.py (correction→override→rerun cross-tier),
  test_resolution_merge_split.py (merge log-record, split rebound+quarantine,
  deterministic restoration). No public StageWork E2E over a multi-chapter book.
- docs/data-model.md, docs/query-search.md, docs/providers.md describe the target
  semantics (typed vocab, SPEAKS/PRESENT_IN predicates, provenance-bearing assertions,
  bounded queries) — docs are AHEAD of the text-path implementation.
- Task.md §10 KG list (scenes, utterances, presence, speaker identity, aliases, states,
  emotions, relationships) and DD §"Text/book and composed sequential art" +
  acceptance criteria (2),(4),(6) are the authority the repairs serve. DD mentions
  ebooklib (AGPL review) but code deliberately uses stdlib zipfile+xml (AGPL avoidance,
  asserted in test_text_parsers.py) — keep stdlib, do not reintroduce ebooklib.

### Parity oracle / repair ledger provenance
- No "Alexandria", "parity oracle", "2a-2f", "multi-valued", or "canonical characters"
  terms exist anywhere in repo docs — the repair ledger is caller-supplied, not on
  disk. "2a-2f" most plausibly maps to the caller's own requirement list items or the
  DD's V1-modality/acceptance sub-sections; MUST be confirmed with the caller before
  implementation.

## Critical Invariants
- Never route EPUB/PDF bytes through `normalize_txt` (errors="replace" destroys binary);
  dispatch.parse_document is the sanctioned per-format route.
- Evidence dedup depends on uq_evidence_identity (source_id, locator, evidence_kind,
  config_digest) — any new evidence emitter MUST set config_digest (never NULL).
- Segment registration is deterministic (deterministic_key sha512+path); evidence
  segment_id linkage must use _segment_row_ids paths that match the actual segmenter.
- Model call records are METADATA-kind evidence ("evidence of the call, never a
  semantic assertion"); semantic claims go through assert_semantic/entity_resolve
  command paths into the ledger — providers never write semantic state directly.
- current_state stays single-value (entity_ref, predicate) PK; multi-edge lives on the
  replay-built read side, never by mutating current_state semantics.
- No new DB, no Neo4j, no opaque LLM authority, no audiobook schema. Bounded queries,
  consistency tokens, quarantine, lock/override, invalidation, selective rerun,
  reversible merge/split must all keep working.

## Sources
- src/umd/jobs/production.py, dag.py; extractors/{dispatch,txt,markdown,epub,pdf}.py;
  segmentation/{segmenters,registry}.py; analysis/text_structural.py;
  models/provider.py, registry.py; resolution/{candidates,mentions,linkage,resolution}.py;
  domain/{models,events}.py; application/commands.py;
  storage/postgres/{tables,ledger,reducer,repositories}.py;
  projections/{base,current,query,search,question}.py
- tests/{fixtures,test_text_parsers,test_text_segmentation,test_production_stage_registry,
  test_production_runner,test_api_contract,test_projection_phase2,
  test_phase3_correction_e2e,test_resolution_merge_split}.py
- docs/{data-model,query-search,providers}.md; Task.md; DD-universal-media-decomposer.md
