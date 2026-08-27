# Universal Media Decomposer API — Final Effort Estimate

**Status:** DONE — read-only estimation; evidence-backed from upstream artifacts. No code written, no plan created, no DD authored/amended.
**Date:** 2026-08-25
**Agent:** `rnd-estimator`
**Work item:** Implement the selected production-ready architecture (architecture-options **Option A**: FastAPI network service, PostgreSQL semantic event ledger + relational metadata authority, OCFL-compatible immutable source storage, typed core + extensible assertions, Tier-0/Tier-1 read projections, stable versioned locators, modality plugin pipelines, alignment/entity resolution, DAG selective invalidation + durable restartable jobs, structured + semantic querying, hybrid exact/vector search, model-provider adapters, sandbox/security, observability, Docker/Compose, migrations, OpenAPI/client examples, fixtures, docs, unit/integration/E2E/final-adversarial tests), with the complexity simplifications applied (no Dagster in v1, no mandatory Neo4j/RDF projection in v1, projection contracts retained, provider interfaces fused where safe, all named gates/limitations from the adversarial log preserved).
**Scope:** All application layers and operational artifacts required by `Task.md` §§1–40. Greenfield repository (support-librarian L1: zero prior ADRs/ASRs/DDs/plans; git has no commits).
**Evidence inputs:** `Task.md` (§§1–41, 1739 lines); technology-research.md; adversarial-log.md (T1–T8); architecture-options.md (Option A + ownership map + footprint estimate); complexity-review.md (F1–F5); `artifacts/designs/pending/DD-universal-media-decomposer.md` (constraint skeleton — confirmed present, not yet authored); support-librarian.log.jsonl (L1: greenfield baseline).

---

## Executive result

| | |
|---|---|
| **Size tier** | **EPIC** |
| **Confidence** | **MEDIUM** (tier = HIGH confidence; exact magnitudes ±20%) |
| **plan_needed** | **true** (weighted_chars ≫ 32K) |
| **dd_needed** | **true** (weighted_chars ≫ 80K) |
| **DD_REQUIRED** | **IMMUTABLE — confirmed** (see §5) |

This is a **multi-workflow, multi-layer, schema-heavy, multi-people** build. It does not fit in one reasoning pass, does not fit a single implementation stream, and cannot be set-path as a single plan. The scale is not a sign of design bloat — the complexity review independently confirms the elevation is overwhelmingly **requirement-mandated** and the chosen Option-A ledger+projections structure is the *simplest correct* design; the four accidental-complexity reductions (no Dagster, fence graph/RDF projections, fuse provider interfaces, carry named gates) are already incorporated into the scoped inventory below.

---

## 1. Formula inputs

| Input | Value | Basis |
|---|---|---|
| **Files — create** | 310 | Layer inventory in §3 |
| **Files — modify** | 0 | Greenfield (no existing code) |
| **Files — delete** | 0 | Greenfield |
| **Files — total** | 310 | |
| **Sections** (distinct edit locations) | 950 | Functions/methods/blocks/types across 20+ packages; avg ≈3 sections/file |
| **char_count** (edit-scope characters) | 1,740,000 | ≈43,400 lines × ≈40 chars/line (source + tests + schemas + migrations + config + docs) |
| **cognitive_weight** | 34.1 | 1 + 0.03×(950−1) + 0.015×(310−1) = 1 + 28.47 + 4.64 |
| **weighted_chars** | **59,300,000** | 1,740,000 × 34.1 ≈ **59.3M** |

**Threshold crossings (decisively):**

| Threshold | Value | Criteria |
|---|---|---|
| TRIVIAL | < 8K | — |
| SMALL | 8K–32K | — |
| MEDIUM | 32K–80K | — |
| LARGE | 80K–320K | — |
| **EPIC** | **≥320K** | **59.3M → ~185× over the EPIC floor** |

The magnitude is not sensitive to estimator error. Even halving char_count and halving the section count still yields ≈14.5M weighted chars (>45× over EPIC). The **EPIC tier is high-confidence** even though the per-layer allocation is uncertain by ±20%.

The architect's own footprint floor — "18–24 top-level packages/modules, 35–50 migrations, 10–16k lines including tests" — supports EPIC: the conservative core-source line count (layers A–G, §3) is already ≈26K lines before this estimate's test matrix (≈7.7K), event schemas (≈1K), migrations (≈2.4K), docs (≈4.2K), and operational tooling.

---

## 2. Missing-DD note

The DD skeleton exists at `artifacts/designs/pending/DD-universal-media-decomposer.md` (constraint-only input; header instructs "do NOT author the final DD here"). It has not yet been distilled by DDAuthor. Per the work item scope, this estimate does **not** author or amend that DD. The estimate assumes the future DD incorporates the complexity-review recommendations (F1–F5) and the adversarial-log T7/T8 canonical decisions (single shared `reduce_current_state`; `stage_run` UNIQUE-key dedup authority; `job_run_audit` off-stream; source:// `@v{}` locator versioning; bubblewrap sandbox posture; ocfl-py 2.1.0; splink ≥4.0.16; WebVTT `X-TIMESTAMP-MAP` pre-normalizer; 4-stage whisper filter + `HallucinationFiltered`; `ReferenceRebound` + split-time enumeration query). File/section counts below assume these are in scope as designed.

---

## 3. Phased breakdown with dependencies

Layer inventory (conservative; greenfield new-file counts). Dependencies are listed per phase; most implementation phases depend on Phase 0/1 foundations. Test phases run partially parallel to their subject layers.

| Phase | Layer(s) | Files | Sections | ~Chars | Depends on | Notes |
|---|---|---|---|---|---|---|
| P0 | Foundation & tooling: repo scaffold, `pyproject`, CI, base packages, Docker/Compose skeleton, OCFL (ocfl-py 2.1.0, `src/umd/storage/ocfl.py`), Postgres/Alembic bootstrap, event-envelope + migration tooling, upcaster framework, sandbox spike (bubblewrap platform matrix — **U4 gate**), structlog base | 26 | 70 | 130K | — | Includes ~15 config/CI/compose/runbook files; the sandbox spike is a named build-gate |
| P1 | Core domain + semantic ledger: domain models (sources, segments, locators, evidence, semantics, ontology, entities, temporal), `semantic_event` append + Tier-0 `current_state` via **single shared `reduce_current_state`**, event-schema catalogue (≈30 versioned JSON schemas + upcasters), `stage_run` UNIQUE-key dedup, `job_run_audit` off-stream, `source://@v{}` locator system, ingest command path (`POST /sources/*`), source descriptors/work membership | 52 | 170 | 290K | P0 | DoD base: source ingestion, stable segments, exact provenance, audit-why/prev/change |
| P2 | Decomposition DAG + durable jobs: Hatchet DAG definitions, lineage table + `InvalidationPlanner`, durable job API (submit/poll/cancel/retry/rerun), restart-after-crash, manifest pinning (stage_schema/extractor/decoder/locator/model versions), DAG-version namespacing, drain/cancel deploy policy | 12 | 55 | 100K | P1 | Depends on stage_run/manifest contract from P1; Hatchet pin = build-gate |
| P3 | Text & image pipelines: TXT/Markdown/EPUB/PDF extractors + text segmentation; EPUB CFI; image OCR (PaddleOCR/Tesseract), regions/panels, objects/people, spatial, descriptions; deterministic segmenters + locator generation; sandboxed execution | 24 | 85 | 160K | P1 (contracts), P0 (sandbox) | |
| P4 | Audio, video, subtitle pipelines (heaviest): decode, VAD-before-ASR, faster-whisper + 4-stage hallucination filter (`HallucinationFiltered`, transcription-scoped confidence + promotion ban), speaker/diarization (pyannote vendored weights — **U1/U5 gates**), scenes/shots/frames, subtitle parse (SRT/ASS/WebVTT/TTML/SAMI/MicroDVD/MPL2/TMP) + **WebVTT `X-TIMESTAMP-MAP` pre-normalizer**, independent-subtitle-track evidence, music/SFX, temporal events | 38 | 150 | 330K | P1, P3 | FFmpeg/PyAV CVE pins + watch (standing) |
| P5 | Entity resolution + alignment: splink ≥4.0.16 + blocking keys + persisted trained model + fixed seed + chunked predict (**U3 gate**); merge/split/`ReferenceRebound`/quarantine (split-time enumeration query — **U6**); Vecalign parallel-only + DTW/timecode + embedding-retrieval + LLM reconciliation; `parallelity_assumption` on every `Aligned` record | 23 | 100 | 200K | P1 (ledger), P3/P4 (evidence) | |
| P6 | Query / search / API surfaces: typed structured query, semantic QA compiler (returns provenance-bearing answers), hybrid search (tsvector/pg_trgm + pgvector on **separate immutable `embedding` table**), consistency contract (read-your-writes token, 503 + Retry-After + `x-consistency` class + jittered backoff), all REST routers, pagination, RFC 7807 errors, OpenAPI, stability/capabilities/health | 27 | 115 | 210K | P3/P4 (projection inputs), P1 (Tier-0/current_state) | Query surfaces overlap P3–P5 as projections come online |
| P7 | Projections + observability + security hardening: Tier-1 search/vector projection builders (blue/green, checkpoints), model-provider adapters (Ollama/vLLM/LiteLLM, `ModelProvider.mode ∈ {completion, embedding}` — fused Embedder), observability (metrics, traces, decomposition reports), sandbox per-parser seccomp policies, archive guards, Python CVE-fix pins | 23 | 105 | 200K | P1 (reducer), P4 (sandbox) | sandlock fallback **unvalidated** — verify |
| P8 | Tests full matrix + adversarial: unit suite (locators, segments, assertions, provenance, merge/split, invalidation, overrides, confidence, alignment, aliases, versioning, structured queries, reducer, dedup), integration synthetic heterogeneous/contradictory media, E2E correction→invalidation→selective-rerun (+ cross-tier Tier-0/Tier-1 equivalence assert), determinism harness (wipe→replay→diff **incl. Tier-0**), adversarial fixture generation (malformed containers, VobSub, non-UTF-8 subtitles, X-TIMESTAMP-MAP VTT, zip bombs, tar traversal), DoD #34 final review | 62 | 185 | 340K | All subject layers (P1–P7); runs partially parallel | Stage-scoped determinism: byte-exact for deterministic stages, tolerance-based for model stages |
| P9 | Docs + deployment + release: all §39 docs (architecture, source/evidence/semantic/graph models, provenance, locators, DAG, invalidation, overrides, alignment, multilingual, adaptations, provider interfaces, storage ownership, API, query, deployment, testing, plugin authoring, known limitations), Dockerfiles/compose finalization, migrations finalize, seed/fixture tooling, runbooks, health checks | 23 | 15 | 90K | P1–P8 | Known-limitations doc must carry the U-style gates + fundamental limits (locator drift, FFmpeg boundary, Vecalign scope, pyannote provisional) |

**Totals** — Files 310 · Sections 950 · Chars ≈1,740K → weighted ≈59.3M.

---

## 4. Effort/schedule (transparent planning aid only)

**These are rough planning heuristics, NOT a commitment.** Person counts are illustrative; the correctness-heavy nature (event-sourcing discipline, adversarial fixtures, real hardware-in-the-loop media pipelines) and the stage-scoped determinism test burden justify the upper end of a normal LOC/person-week range.

- **Assumed throughput:** ≈500–650 effective LOC/person-week sustained for this correctness-weighted work (realistic for greenfield with heavy test+adversarial burden; well below toy-project rates).
- **Estimated effort:** ≈96–110 person-weeks cumulative across phases (incl. P8's adversarial/test matrix and P9 packaging/docs). This is **≈22–26 person-months**, before management/buffer contingency of ~15–20%.
- **Illustrative calendar:** single-track ≈ **16–20 months**; with **3–4 engineers** working P3–P8 in parallel where the dependency graph permits → **≈9–14 months**. The network critical path is P0→P1→(P2 and P3/P4)→P5→P6→P8→P9; P4 (audio/video/subtitle) and P8 (tests) are the longest-feeding legs.

Key dependency constraints for any schedule:
1. P3–P5 all consume P1's evidence/semantic/provenance contracts — P1 is the gating foundation.
2. P4 (all three A/V/subtitle pipelines) is the single largest effort block and carries the highest open-gate count (pyannote, FFmpeg CVE, whisper filter).
3. P8 is the DoD gate (#30 E2E, #34 adversarial review, #35 repair-and-rerun) — it cannot be compressed and must not be the last-minute afterthought; it overlaps P3–P7.
4. P6's query surface depends on projections (P7) coming online; bare query/semantic-compiler work can start earlier.

---

## 5. Key risks and gates

Carried verbatim-in-spirit from the adversarial log (T6/T8) and complexity review. Each is a named gate, not silently resolved:

| # | Risk/Gate | Severity | Phase | Notes |
|---|---|---|---|---|
| U1 | pyannote weights license **UNDECLARED** (commercial/legal) | HIGH | P4 | Vendored-weights decision solves *access*, not *commercial rights*; keep 2.1-non-gated + deferred-diarization as funded fallbacks |
| U2 | Whisper hallucination filter is best-effort, not detector (F1 ≈23.6% on the signal trio) | MED | P4 | §14 promotion ban is the real control; optional BoH/delooping/beam-1; internal-state probing = phase-2 |
| U3 | splink #3023 u-estimation planner issue / DuckDB regression | MED | P5 | Build-gate: benchmark blocking keys vs 1.3.x baseline; pin DuckDB 1.3.x if ≥3× slower |
| U4 | bubblewrap host-profile install (Ubuntu 24.04 AppArmor) + container caps; **sandlock fallback unvalidated** | MED | P0/P7 | First-class target = bare metal/VM; managed K8s conditional; validate sandlock exists before relying on it |
| U5 | `HallucinationFiltered` no §16 dependency edge (threshold regime unversioned) | MED | P4 | Give the filter its own (version, input-evidence-refs) dependency edge |
| U6 | SPLIT reference enumeration must be a split-time query, not only the MERGE snapshot | MED | P5 | Deterministic enumeration query at split-time seq in the DD |
| U7 | In-sandbox OCFL access / FUSE mounts unreliable | LOW-MED | P7 | Local read-only spool of required OCFL range at task start |
| — | Hatchet pinned release is OPEN (pin ≥ fix trail #3860/#1507/#1620/#3243/#4372; watch #3674) | MED | P2 | Engine idempotency advisory; `stage_run` UNIQUE key + same-transaction event append is the authority |
| — | FFmpeg/PyAV CVE stream (VobSub RCE CVE-2026-64830 in our subtitle pipeline) | MED-HIGH | P4/P7 | In-sandbox demux/decode + CVE-fixed pins + standing watch; sandbox is the boundary, not elimination |
| — | pyvector/HNSW co-tenancy (CVE-2026-3172 + #875 100× UPDATE) | MED-HIGH | P6/P7 | Separate immutable `embedding` table; append-only rows; REINDEX CONCURRENTLY cadence; pin ≥0.8.2 (0.8.6) |
| — | Common-mode reducer risk (Tier-0/Tier-1 one implementation) | MED | P1/P7 | Pure/total contract + conformance tests + ≤5ms p99 Tier-0 budget; decided, accepted |
| — | Upcaster/event-schema discipline is a **permanent** budget, not one-time work | MED | P1+ | Every event change ships an upcaster + historical-replay test (Overeem 8/19 abandonment finding) |

**Fundamental limits (must be documented in DD, must not be sold as fixable):** locator stability bounded by content stability (EPUB CFI invalid-reference rule; decoder/renderer version drift — mitigated by `@v{}` + `SourceAliased`/`LocatorRebased`/quarantine, not eliminated); FFmpeg parse is boundary-not-elimination; Vecalign monotonicity restricts it to parallel text pairs; projection/rebuild scale is an ops budget (vector staircase 5M/10M/50M behind `VectorIndex`).

**Estimate-level uncertainty drivers:** diarization fallback choice (U1/Q1) changes P4 ±; sandbox platform decision (U4/Q3) changes P0/P7 ±; exact adversarial-fixture breadth and llm-client integration effort are the least-bounded line items. These shift layer magnitudes, **not** the EPIC tier.

---

## 6. Confirmation: DD_REQUIRED immutable

**DD_REQUIRED = TRUE and is declared immutable.** This follows from all three DD-trigger axes simultaneously:

1. **Weighted chars ≈59.3M ≫ 80K** (LARGE/EPIC threshold) — decisively exceeded.
2. **Architecturally novel** — event-sourced semantic ledger + single-writer projections + two-tier consistency contract is a structural departure from any default CRUD service; needs the distillable decision record (DD) before implementation.
3. **Incomplete/ambiguous-requirement dimension** — while `Task.md` is authoritative, the DD must resolve the distillation of T7/T8 canonical decisions and carry the named open gates/limitations without hiding them (complexity-review §7, F4).

The pending DD (`artifacts/designs/pending/DD-universal-media-decomposer.md`) is the DDAuthor deliverable that satisfies this gate. This estimate does **not** create, author, or amend it. Scope is finalized only after that DD is authored; per-layers here are sized on the assumption the DD incorporates the documented simplifications (no Dagster, graph/RDF projections fenced to contracts, fused provider protocols, named gates preserved).

---

*End of estimate. Read-only; no code, no plan, no DD amendment.*