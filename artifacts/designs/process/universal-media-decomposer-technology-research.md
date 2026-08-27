# Universal Media Decomposer API — Technology & Design Research Report

**Date:** 2026-08-25
**Author:** support-researcher
**Scope:** Greenfield architecture research. Read-only w.r.t. production code. No implementation, no plan, no final DD — this is upstream evidence for the design author.
**Authority:** `Task.md` (41 sections, `/workspace/Universeity/Task.md`, lines 1–1738). No ADRs/ASRs/DDs/plans exist (confirmed by `artifacts/logs/support-librarian.log.jsonl` line L1, 2026-08-25T10:09:21Z).

---

## Executive Summary

The Universal Media Decomposer API does not need one database — it needs a **clear ownership model across several stores**, with the semantic layer governed by an **append-only event/semantic log** and the graph/vector/search projections being **derived, disposable, and rebuildable** from that log. This is the only way to satisfy `Task.md` §22 ("avoid duplicating authoritative data across stores without a clear ownership model") while also meeting §15 (append-only semantic editing), §21 (versioning/audit), §7 (user overrides), §29 (reversible entity resolution), and §31/§23 (durable, restartable DAG jobs).

Key 2026 facts that change the technology landscape:

- **Kùzu is discontinued** — acquired by Apple (Oct 2025), GitHub repo archived, extension server gone. It must NOT be chosen for greenfield ($1 only flags this via the youngju/rizlabs write-ups; verified on github.com/kuzudb/kuzu).
- **Neo4j Community** remains the most mature property-graph engine but is **GPLv3 and single-node**; clustering, HA, and hot backups are commercial-only (neo4j.com/open-core-and-neo4j, operations-manual). A single-node graph is acceptable at first but is a licensing/HA constraint to plan around.
- **Apache AGE** (Postgres-backed Cypher) has **severe raw-executor performance problems** in independent 2026 benchmarks (≈78 RPS under load, 6/8 complex "differentiation" queries stuck >20 min; ~55% openCypher coverage). Not a safe default for graph-heavy semantic QA.
- **Memgraph** is only production-safe in **in-memory** modes; its disk mode is experimental and there is an open PR to remove `ON_DISK_TRANSACTIONAL`. In-memory ⇒ OOM-cliff under memory cgroup limits for a large media corpus.
- **RDF 1.2** (W3C, Candidate Recommendation 2026-04-07) finally standardizes **triple terms (RDF-star)** — statements-about-statements, i.e. exactly the "this claim has evidence, confidence, and was produced by step X" shape `Task.md` §2 and §13 demand.
- **GQL** (ISO/IEC 39075) is the standardized successor to Cypher; most property engines target support by end-2026. Prefer engines/abstractions that converge on GQL/Cypher.
- **Append-only / bitemporal / time-travel** is a first-class, mature category now: **XTDB 2.x** (MPL-2.0, SQL:2011 bitemporal, Postgres-wire, object storage) is a strong fit for the audit/versioning layer and is itself event-sourced. **OCFL 1.1** gives a standards-based content-addressed (sha512) layout for immutable blobs.
- **Durable execution** has a clear default (**Temporal**) and a lighter Postgres-native alternative (**Hatchet**); **Dagster** adds asset-lineage-driven selective recompute + freshness/invalidation on top of a DAG.
- Media ingestion is a portfolio problem: there is **no single library** for all modalities; the right answer is a **plugin/ingester matrix** (PyMuPDF/pdfplumber for PDF, ebooklib for EPUB, PaddleOCR/Tesseract for OCR, faster-whisper + pyannote for ASR/diarization, PyAV/ffmpeg/PySceneDetect for video, pysubs2 for subtitles, **pandoc** for universal text). Sandboxing via **nsjail/bubblewrap/gVisor** + rlimits/cgroups/timeouts.

**Recommended baseline stack (design-author input, not a decision):**
Python 3.11+ service (FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic); **PostgreSQL + pgvector** as the operational structured/vector store; **OCFL-structured object storage (MinIO/S3/FS)** for immutable blobs; **append-only semantic log in Postgres** as the authority for semantics/provenance/overrides/audit; **Temporal (or Hatchet) + Dagster-style asset graph** for durable decomposition jobs; a **disposable graph projection** (Neo4j CE, or Memgraph once disk-mode stabilizes, or relational + recursive CTE if Cypher is not needed) rebuilt from the semantic log; **Ollama (local, OpenAI-compatible) + optional vLLM + remote OpenAI/Anthropic** behind a ModelProvider interface; **nsjail/bubblewrap** around untrusted parsers.

A full adversarial comparison (alternatives, failure modes, maturity, ops, migration) is in §6.

---

## 1. Q1 — Coherent production architecture & technology choices

### 1.1 The central architectural principle: single-owner, derived projections

`Task.md` §22 lists six store categories and forbids duplicating authority without an ownership model. The cleanest way to satisfy this — and to make §29 (reversible resolution), §15/§21 (append-only editing + history), §7 (overrides), and §34/§35 (adversarial review) tractable — is:

```
SOURCE TRUTH   OCFL object store (blobs, content-addressed, immutable, versioned)
SEGMENT TRUTH  Postgres tables (sources, segments; deterministic, keyed by stable locators)
SEMANTIC TRUTH Append-only semantic log in Postgres (assertions, overrides, edits, confidence, provenance)  ← THE AUTHORITY
PIPELINE STATE Durable job engine (Temporal/Hatchet) + per-stage artifact records in Postgres
AUDIT/HISTORY  The semantic log itself (bitemporal via transaction-time columns) + optional XTDB witness
EMBEDDINGS     Postgres + pgvector columns; derived from evidence text/audio/image (not authoritative)
GRAPH          Derived projection (Neo4j CE / Memgraph / relational-RCTE) rebuilt from the semantic log
SEARCH         Derived projection (pg_trgm + tsvector + pgvector hybrid) rebuilt from the semantic log
USER EDITS     In the semantic log (append-only); never a destructive in-place write
```

Rule that prevents cross-store authority duplication: **only the semantic log is authoritative for semantics; every graph node/edge, every embedding, every search hit is a materialized view of the log, tagged with the log version it was built from, and rebuildable by replay.** Entity merging (§29) is *not* a physical graph rewrite — it is a `MERGE` record in the log; the graph projection applies merge/split and is regenerated. This is the standard **event-sourced / CQRS** pattern and is what makes "merge must be reversible" literal: the log keeps both the merge and the constituent mentions forever.

### 1.2 Layer-by-layer comparison (2026, primary sources)

#### Immutable source/blob storage
| Option | Facts | Verdict |
|---|---|---|
| **OCFL 1.1 layout** on FS/MinIO/S3 | Content-addressed digests (sha256/sha512), versioned inventory.json, rebuildable, storage-diverse (ocfl.io/1.1/spec). | **Recommended** as the *layout contract* so blobs stay portable/recoverable and dedup-friendly. |
| Plain object store (MinIO/S3/FS) | Simple, cheap, scalable. Lacks OCFL's versioning/parseability guarantees out of the box. | Fine substrate; layer OCFL on top. |
| Git-LFS / DVC cache | Versioned but couples to git, awkward for large binary workloads. | Not preferred for the blob truth layer. |

Sources: https://ocfl.io/1.1/spec/, https://ocfl.io/

#### Structured relational state
PostgreSQL is the mature default: ACID, JSONB for extensible payloads, tsvector/pg_trgm for exact+fuzzy text search, arrays, and pgvector extension for vectors — all in one transactional store. This supports §10/§36 ("typed core concepts + extensible assertions") without a graph engine: typed tables (sources, segments, entities, claims/semantic assertions) + a generic `assertion(subject, predicate, object, confidence, authority, provenance)` table + JSONB payload for open extension. Relational recursive CTEs (RCTE) are surprisingly fast for OLTP looks-ups (2026 benchmarks) but are impractical for variable-length path and shortest-path queries (see §5.4). So the relational store is the *operational truth*; heavy graph traversal is offloaded to a projection.

#### Graph semantics
| Option | License/Maturity | Fit |
|---|---|---|
| **Neo4j CE** | GPLv3, single-node; EE (clustering/HA/backups) commercial | Most mature Cypher/GQL trajectory. Single-node OK for greenfield; plan licensing/HA. |
| Memgraph | BSL→Apache (delay window); in-memory only for production (disk experimental, PR #3360 to remove it) | Fast Cypher, but OOM-cliff + licensing; risky for large media graphs. |
| Apache AGE | Apache 2.0, PG extension | Co-tenancy with pgvector, but raw Cypher executor slow & ~55% openCypher coverage (2026). |
| ArangoDB (multi-model) | Apache 2.0 community; AQL + ArangoSearch vector (3.12+, 2025) | Document+graph+vector in one engine; not Cypher (GQL) — lock-in to AQL. |
| Relational + recursive CTE | PG | No new store; weak on VLE/shortestPath. Good fallback when graph depth is bounded. |
| Kuzu | **Archived (Apple, Oct 2025)** | **Avoid.** |
| RDF triple stores (GraphDB/Stardog/Jena) | SPARQL + RDF 1.2 | Best if you want full W3C provenance interop (PROV-O, RDF 1.2 triple terms); heavier and less common for UI-driven apps. |

Sources: https://neo4j.com/open-core-and-neo4j/, neo4j operations-manual, github.com/memgraph/memgraph (PR #3360, storage modes docs), github.com/apache/age, github.com/kuzudb/kuzu.

**Recommendation:** keep the semantic authority in Postgres; make the graph a *projection*. Choose Neo4j CE if Cypher/GQL traversal and GDS-style algorithms matter to §17 QA; otherwise relational-RCTE is enough for the first release and avoids a second authoritative store.

#### Vector / search
- **pgvector** (Postgres extension, `/pgvector/pgvector`): HNSW index over `vector`, `halfvec`, `sparsevec`, `bit`; exact nearest neighbor is available by disabling the index scan (`SET LOCAL enable_indexscan = off`); tune recall via `hnsw.ef_search`. Co-tenancy with relational truth avoids a separate vector DB authority. (docs via Context7.)
- Dedicated: **Qdrant**, **Milvus**, **Weaviate**, **LanceDB** — separate infra, better at very large scale / filtering, but adds a second authority that must be kept in sync. **Vespa / OpenSearch** additionally give BM25+kNN hybrid in one system.
- Recommendation: **pgvector** for the first release (single store, transactional consistency with the log); promote to a dedicated engine only if scale demands. Do exact search for provenance-critical "show me the exact sentence" and HNSW for semantic recall.

#### Audit / append-only / versioning
- **Recommended:** the append-only semantic log in Postgres; every write appends a row with monotonic sequence id + transaction-time; no in-place UPDATE of semantic truth (mirrors §15 "prefer append-only/versioned"). Audit API is a query over the log.
- **XTDB 2.x** (MPL-2.0, GA Jun 2025; 2.2 with multi-db, leader election, Postgres logical-replication source, Kafka source, OpenTelemetry): a drop-in bitemporal SQL:2011 database, Postgres-wire, that gives "what did we know, and when" and "as-of" joins with *zero* history tables/triggers. It can be a **secondary witness / time-travel projection** of the semantic log, or even the primary semantic store — but it is Clojure/JVM with its own ops surface and "100% PG compatibility is not the goal." Source: github.com/xtdb/xtdb (v2.0.0 release), xtdb.com/blog/launching-xtdb-v2.

#### Durable jobs & decomposition DAG
See §3.6. Candidates: **Temporal** (durable execution, event history, replay, activities+retries, reset/versioning; battle-tested; heavier ops — needs its own backend), **Hatchet** (Postgres-native queue+DAG, MIT, self-host Lite single image, built-in observability; younger, no deterministic code-replay), **Dagster** (software-defined assets, dependency lineage, freshness policies, auto-materialize — best fit for *selective recompute from invalidation* in §6/§16), **Celery/RQ** (simple queues, not durable-workflow-grade), **DBOS** (Postgres-is-the-control-plane). Decision matrix in §6.

### 1.3 Technology choices — comparison via primary/current docs
All covered inline above, with citations. The governing rule is §22's ownership model; every choice is forced through "which store is authoritative for X."

---

## 2. Q2 — Ingestion/extraction tooling per modality

Everything below treats uploaded media as **untrusted** (§32). Every extractor is a **plugin** behind an interface (§25) and runs **sandboxed, bounded** (§2.7).

### 2.1 Text / book (TXT, Markdown, EPUB, viable PDF)
| Need | Library | Facts / caveats |
|---|---|---|
| TXT | stdlib | trivial. |
| Markdown | **pandoc** (universal converter, invoked as sandboxed subprocess) or `mistune` (pure-Python AST) | pandoc is the most robust for arbitrary Markdown → normalized AST; pin version; subprocess in sandbox. |
| EPUB | **ebooklib** | Reads EPUB2/3 spine/manifest/items; **AGPL-3.0** (github.com/aerkalov/ebooklib) — a licensing obligation; acceptable if the project ships AGPL-compatible or isolates it in a sandboxed worker. Use EPUB CFI for locators (§3.1). |
| PDF (text-viable) | **PyMuPDF** vs **pdfplumber** vs **pypdf** | PyMuPDF is ~10× faster (≈180 pages/s) but **AGPL-3.0 or paid** (pymupdf.io blog; pypi license). pdfplumber is **MIT** but slow (~18 pages/s), better tables. pypdf is BSD, simple. Choose pdfplumber/pypdf for a permissive stack; PyMuPDF only if AGPL acceptable or licensed. "PDF where text extraction is viable" (§26) → detect text-layer presence; else route to OCR. |
| Detect text-layer / page render fallback | PyMuPDF / MuPDF, pdfplumber | page-to-image for image-only PDF path. |
| Doc structure (chapters/paragraphs/sentences) | own segmentation over extracted text; `spaCy`/`pySBD` for sentence split | Deterministic first; LLM only for semantics (§13 — prefer deterministic before expensive). |

### 2.2 Raster images (sequential art incl. manga/comic/webtoon)
| Need | Library | Facts / caveats |
|---|---|---|
| decode/crop/metadata | **Pillow** (+ `piexif` for EXIF) | BSD. RGB(A); EXIF. Bounded decode (decompression bombs — Pillow has a size guard; still enforce limits). |
| OCR | **PaddleOCR 3.x** (Apache 2.0; PP-OCRv6, ~50-lang single model, strong scene/CJK/vertical) | Better than Tesseract for scene text, manga bubbles, CJK/vertical. ~500MB deps. Python API `PaddleOCR(...).predict(img)`. |
| OCR (edge/clean-text) | **Tesseract 5.5** (Apache 2.0; 100+ langs, LSTM; runs on CPU, tiny) | Use for clean printed text / low-resource; pair with pytesseract. |
| OCR (structured docs) | **PaddleOCR-VL / Mistral OCR / Qwen2.5-VL** (VLM) | Structured markdown output; needs GPU; heavier. Reserve for complex layouts. |
| regions/panels/bubbles/reading order | `manga-ocr`? No — use **PaddleOCR detection boxes** + own panel segmentation (CV) + page segmentation | Panel detection is typically custom CV (OpenCV contours) + reading-order inference; can be LLM-assisted at the semantic layer. |
| objects/people/faces | **OpenCV** (Apache 2.0) + optional **Ultralytics YOLO** / **InsightFace** | Apache-2.0 for YOLO (AGPL caveat: Ultralytics moved to AGPL-3.0 since Aug 2024 — verify; choose a permissive fork or use OpenCV DNN). |
| descriptions (alt evidence) | VLM (local Ollama / remote) | semantic, confidence-bearing. |

### 2.3 Audio
| Need | Library | Facts / caveats |
|---|---|---|
| decode | **PyAV** (BSD, bundles FFmpeg) or ffmpeg binary | PyAV = Python bindings over FFmpeg libs; no separate ffmpeg install. |
| ASR | **faster-whisper** (MIT, CTranslate2; up to 4× faster; `large-v3-turbo` ≈8× speedup, int8 CPU) | Local/self-hostable, word timestamps, language detection, built-in Silero VAD. Verified via github.com/SYSTRAN/faster-whisper. |
| language ID | faster-whisper `language` / `langdetect` / Lingua | ASR detection first (cheap). |
| speakers / diarization | **pyannote.audio** 3.x (MIT code, but **gated HuggingFace models** — accept conditions + token; 3.1 removes onnxruntime) | Strong diarization. Note: gated model access must be configured; keep token out of code. Alternative: NeMo (Apache 2.0) speaker diarization. |
| VAD | **silero-vad** (MIT) | used by faster-whisper; standalone too. |
| music / sound events | **librosa** (ISC) + **essentia** (AGPL — caution) or **OpenL3 / YamNet** | librosa for features; essentia is AGPL so avoid unless isolated/licensed; OpenL3/YamNet (TensorFlow, Apache-2.0/Apache-2.0-ish) for audio tagging. |
| music source separation | **demucs** (MIT) | isolate stems if needed. |

### 2.4 Video
| Need | Library | Facts / caveats |
|---|---|---|
| demux/decode/sample frames | **PyAV** (BSD, FFmpeg) / ffmpeg | robust; get PTS-native timestamps (VFR-correct). |
| scene/shot detection | **PySceneDetect 0.7.1** (BSD-3; PyAV/OpenCV backends, VFR support; Content/Adaptive/Threshold/Histogram/Hash detectors; ffmpeg `split_video`) | Verified: scenedetect.com/docs, github.com/Breakthrough/PySceneDetect. |
| audio track / subtitle demux | ffmpeg (`-map`) / PyAV | Extract embedded audio → ASR; extract embedded subtitle tracks → pysubs2 ({§27}). |
| ASR / diarization | same as §2.3 (faster-whisper on the extracted audio) | reuse audio pipeline. |
| visible entities / objects / faces | OpenCV + YOLO + InsightFace; VLM descriptions | video frames as images → image pipeline. |

### 2.5 Independent subtitle tracks
| Need | Library | Facts / caveats |
|---|---|---|
| parse SRT/ASS/WebVTT/TTML/SAMI/MicroDVD/MPL2/TMP | **pysubs2** (MIT) | Full format coverage; preserves timing, styles, speaker labels, SDH markers; treat each track as an independent evidence source (§27) — do NOT flatten. |
| embedded track extraction | ffmpeg (`-map 0:s`) → per-track files, then pysubs2 | preserves language + track metadata. |
| SDH/HI detection | heuristic on styling/tags + optional classification | keep as track-level metadata, not merged into a single subtitle representation. |

### 2.6 Container / codec / format concerns
- Use **ffprobe/MediaInfo** (MediaInfo is BSD-2? — verify; ffprobe is part of ffmpeg LGPL/GPL build) for format detection and stream inventory before choosing an ingester.
- Pin FFmpeg/PyAV minor versions; container/codec handling is a known source of C parser bugs → sandbox it (§2.7).
- "Arbitrary media container" (§1) → route through ffprobe → plugin dispatcher by detected type; unknown → generic binary blob + metadata (never fail the whole service).

### 2.7 Sandboxing & bounded resources (all modalities) — §32
| Layer | Mechanism | Facts |
|---|---|---|
| Process isolation | **nsjail** (Apache-2.0; namespaces, rlimits, seccomp-bpf via Kafel, cgroups v1/v2, time/mem/CPU/fd/pid limits, chroot/pivot_root) | Best fit for bounded *subprocess* execution of untrusted parsers (pandoc, ffmpeg, tesseract, etc.). |
| | **bubblewrap** (LGPL-2.0; user+mount namespaces, seccomp, read-only binds) | Unprivileged; used by Flatpak. |
| VM-grade | **gVisor `runsc`** (Apache-2.0 OCI runtime; application kernel in Go; limits host kernel surface) | Full sandboxed containers; heavier. |
| cgroup + rlimit + timeout in-process | Python `resource` module (RLIMIT_AS/CPU/NOFILE), `subprocess` timeouts, container memory/CPU cgroup limits | Enforce at every layer; never rely on one. |
| Upload guards | size limits, max file count, safe archive extraction (explicit allowlist, no symlink/path traversal), never trust filename | §32 + §8 path traversal prevention; map each upload to an OCFL object keyed by content hash, never by user filename. |

Sources: github.com/google/nsjail (nsjail.dev), github.com/containers/bubblewrap, github.com/google/gvisor (gvisor.dev), python `resource` docs.

---

## 3. Q3 — Sound designs for the hard problems

### 3.1 Stable source-native locators
Reference the *normalized, deterministic representation*, not raw bytes, and keep locators stable across reprocessing (§9). Standards to adopt/adapt:
- **EPUB CFI 1.1** (`epubcfi(...)` fragment; structural path + offsets + ranges; text-location assertions for drift) — the canonical way to address any point/range in an EPUB. `https://idpf.org/epub/linking/cfi/`, `https://w3c.github.io/epub-specs/epub33/epubcfi/`. EPUB 3.3 is a W3C Rec (2026-01-13).
- **W3C Media Fragments URI 1.0** (W3C Rec 2012) — temporal `t=start,end`, spatial `xywh=x,y,w,h`, track `track=`, named `id=` — the portable syntax for time-based and region-based media. `https://www.w3.org/TR/media-frags/`.
- **IIIF Image API 3.0** — region `x,y,w,h` / `pct:` / `square`, canonical spatial crops for images/pages. `https://iiif.io/api/image/3.0/`.
- **W3C Web Annotation Data Model** (Rec 2017) — body/target/selector/TextQuoteSelector/TextPositionSelector — the natural container for "this evidence supports this claim" and for user corrections as anchored annotations. `https://www.w3.org/TR/annotation-model/`.
- Custom `source://` scheme (§9 examples): encode **content address of the source + deterministic structural path** (e.g. `source://<source_id>/chapter/4/paragraph/18`), where `<source_id>` is derived from a content hash so it never collides across re-uploads. For time media, embed Media-Fragments-compatible `t=` components. **Stability** comes from (a) deterministic segmentation (parsers keyed by structural index, not by model output) and (b) versioned handling of edit-list/drift (CFI's text-location assertions; store locator version + identity, never byte offsets alone).

### 3.2 Many-to-many multilingual/adaptation alignment (§4, §5, §12)
- **Store alignment as typed, confidence-bearing assertions linking segments** (edges in the semantic log), never by merging evidence. Use Web Annotation selectors + a `CORRESPONDS_TO`/`ADAPTATION_OF`/`CONTRADICTS` vocabulary (§5) as first-class typed relationships.
- **Sentence-level alignment:** **Vecalign** (linear-time approximate DP over multilingual embeddings, LASER; supports 1-many/many-1/many-many blocks; ~100 languages) — best structural fit for §12's many-to-many requirement. github.com/thompsonb/vecalign, ACL D19-1136.
- **Word-level alignment** (for entity/term correspondence): **awesome-align** (mBERT) or **SimAlign** (embedding-based, no parallel data) — helpful for alias/entity bridging (github.com/neulab/awesome-align; SimAlign EMNLP 2020).
- **Temporal alignment** (audio/video ↔ subtitles ↔ each other): DTW/interval matching over timecodes + ASR/subtitle text. Keep correspondence many-to-many and confidence-bearing (§12).
- **Translation-aware semantic similarity** for novel↔adaptation: multilingual embeddings + (optional) LLM reconciliation producing *shared semantic intent + multiple realizations* (§11, §28) — never collapse into one authoritative sentence.

### 3.3 Reversible entity resolution (§29)
- **Never physically merge** mentions. The canonical entity is a *derived node*; a `MERGE`/`SPLIT`/`ALIAS` record in the semantic log links the constituent mentions; the graph projection applies it; **reversal is a new log record + projection rebuild** (trivially reversible, audit-preserved).
- **Scoring:** probabilistic record linkage via **splink** (MIT, Fellegi-Sunter, term-frequency adjustments, unsupervised, DuckDB backend, interpretable match weights) — great for name/alias/transliteration candidate scoring; supports embedding-derived features for semantic fuzzy matching. github.com/moj-analytical-services/splink.
- **Candidate generation:** blocking keys (normalized name, transliteration, soundex, face-cluster id, speaker embedding cluster id) + LSH (MinHash) to bound comparisons.
- **Multiple signals:** text aliases (エミリア/Emilia/half-elven girl), **speaker embeddings** (face_cluster / speaker_07), **visual identity** (face clusters via InsightFace) — merge into one entity while preserving every alias/evidence path (§29 example).
- **Unnamed / later-resolved identities:** represent as `unknown_N` placeholder entities with candidate sets (§14) that resolve to a canonical entity when a new log record links them.

### 3.4 Typed + extensible semantic assertions (§10, §36)
- Avoid both extremes (§36): a typed core (sources, segments, entities, typed relationships like `speaks`/`present_in`/`CORRESPONDS_TO`) **plus** an extensible generic assertion mechanism.
- **Model:** a typed table `semantic_assertion(subject_ref, predicate, object_ref, confidence, authority, scope, valid_from/to, created_seq, generated_by, supersedes_seq)` + a JSONB payload for open extension; predicates reference a **controlled vocabulary that can grow without schema migration** (a `predicates` dictionary table).
- **Provenance on assertions / statements-about-statements:** RDF 1.2 **triple terms** (RDF-star) are the W3C-standardized way to attach evidence/confidence/source to an assertion (§2: "What claims this? Which source supports it? What confidence?"). You don't have to go full RDF-store — but if you do, RDF 1.2 (CR 2026-04-07) + SHACL gives validated, extensible typed assertions. `https://www.w3.org/TR/rdf12-concepts/`, `https://www.w3.org/TR/rdf12-shacl/`.
- **PROV-O / PROV-DM** (W3C Rec 2013) give the standard vocabulary for `wasGeneratedBy`, `wasDerivedFrom`, `used`, agent/tool/version — map `generated_by` semantics to it for interop. `https://www.w3.org/TR/prov-o/`.
- **Confidence/uncertainty** (§14): store candidate sets (e.g. `speaker_candidates`) as structured JSON on the assertion; graph queries accept confidence thresholds.

### 3.5 Append-only overrides/history (§7, §15, §21)
- The semantic log is append-only: **user overrides are explicit assertions with `authority = USER_OVERRIDE` and precedence over machine inference**, stored as new records (never mutating the machine record). "Do not mutate model output invisibly" (§7) is satisfied structurally.
- **Bitemporal view:** transaction-time (system) + valid-time (narrative/claim currency). Postgres transaction-time columns on the log give "why does the graph believe X / what did it believe / what changed" (§21) for free. For full SQL:2011 bitemporal time-travel, add **XTDB** as a witness (see §1.2).
- Operations §15 (edit/override/merge/split/reassociate/lock/unlock/invalidate/rerun) all become log records with associated dependency-invalidation events.

### 3.6 Durable restartable jobs + DAG invalidation (§6, §16, §23)
- **Model decomposition as an explicit DAG of steps** (INGEST → FORMAT ANALYSIS → SEGMENTATION → EXTRACTION → STRUCTURAL → RESOLUTION → ALIGNMENT → RECONCILIATION → GRAPH) — §6.
- **Each stage is independently rerunnable; changing a stage invalidates only dependent descendants** (§6, §16) and does NOT force re-ingestion. Persistent per-source/per-segment artifact records let a failed late stage retry without repeating expensive early extraction (§23).
- **Job engine options:**
  - **Temporal** — durable execution (event history + replay = survives process/container restart), activities with automatic retries, workflow reset/versioning for selective re-run. Heaviest ops (own backend). Verified via /temporalio/documentation.
  - **Hatchet** — Postgres-native durable queue + **DAG workflows**, retries, per-worker slot control, rate limits, built-in UI/OpenTelemetry; self-host Lite = single Docker image. Lighter; younger; no deterministic code-replay (idempotency is on the user). 
  - **Dagster** — if invalidation is the dominant concern, **software-defined assets + dependency lineage + freshness policies + auto-materialize** natively express "when entity X changes, only its downstream assets recompute." This maps §16 almost one-to-one. Not a durable-workflow engine by itself (runs in-process/webserver+daemon), so combine with a queue for restart durability.
- **Recommendation:** adopt a **job engine + asset graph** pair: use **Temporal** for durable step execution (or Hatchet for lighter ops), and maintain an explicit **stage-dependency graph** (Dagster-style software-defined assets — source → segment → per-step derived artifact) so selective invalidation/rerun is declarative. Persist the DAG definition + per-stage state so it survives restart.

### 3.7 Structured graph queries (§18)
- Task allows GraphQL / Cypher / typed REST / custom DSL — "choose based on implementation quality and extensibility."
- **Recommendation:** expose a **typed REST query API** (deterministic, pageable, provenance-bearing) as the primary contract, **plus** a graph query surface (Cypher/GQL if a graph engine is adopted, or a recursive-CTE-backed typed query layer if not). This keeps consumers independent of storage (§1, §37) and returns structured provenance. If a dedicated graph engine is used, expose a constrained/subset GQL/Cypher endpoint.
- **GQL** is the ISO/IEC 39075 successor to Cypher, targeting completion across major engines by end-2026 — prefer engines/abstractions converging on it to avoid Cypher-vendor lock-in.

### 3.8 Exact + semantic search (§20)
- Both required and must label result kind (source evidence / semantic interpretation / canonical entity).
- **Exact/source:** PostgreSQL `tsvector` + **pg_trgm** (fuzzy/exact phrase, character-level), plus structured filters on locator components (timestamp, chapter/page, event id).
- **Semantic:** pgvector HNSW over evidence-text/audio/image embeddings; option to **hybrid-rank** (BM25/tsvector + cosine) with configurable fusion; exact search available by disabling the index (pgvector) for provenance-critical hits.
- **Kind tagging** is metadata on each indexed row (source vs semantics vs canonical), surfaced in results.

### 3.9 Local/self-hostable vs remote model providers (§13, §28 in DoD)
- Make models **swappable behind a `ModelProvider` interface**; do not bind to one vendor (§13). Record model/version/prompt-version/input-evidence/output/confidence/timestamp/dependency-step for every model call (§13, §21).
- **Local/self-hostable:** **Ollama** (llama.cpp, OpenAI-compatible `/v1/chat/completions` + `/v1/embeddings`, plus Anthropic Messages API since Jan 2026; easy CPU/dev; single-user concurrency) — the lowest-barrier local path satisfying DoD #28; **vLLM** (high-throughput, OpenAI-compatible, Linux/GPU, embeddings + JSON mode; production-grade) for scale; **TGI** alternative; **sentence-transformers / ONNX Runtime** for embeddings offline.
- **Remote:** OpenAI / Anthropic / Azure via the same OpenAI-compatible contract. Use **LiteLLM** as a router/abstraction over all backends behind one API.
- **Rule:** local-first for deterministic/small tasks; route to remote only via the provider interface; never let a model become "an opaque database" (§13) — every model call emits structured, provenance-carrying results into the log.

---

## 4. Q4 — API / deployment / testing / security / observability & repo layout

### 4.1 API layer
- **FastAPI** (OpenAPI-native, Pydantic v2 validation) — generates the OpenAPI doc §24 requires (`POST /sources/*`, segments, analysis status, rerun/invalidation, entities, claims, relationships, alignment, semantic QA, structured query, search, provenance, audit, health, capabilities). Stable IDs (ULID/UUIDv7), pagination everywhere, structured errors (RFC 7807 problem+json), capability/version endpoint.
- **API neutrality (§37):** no audiobook/subtitle/game/screenplay/video-gen terminology in the contract; endpoints stop at ingestion, decomposition, evidence, semantics, knowledge, provenance, querying, editing, reprocessing.

### 4.2 Deployment
- **Docker + Docker Compose** (DoD #31, §38): `api`, `worker`(s), `postgres`(+pgvector), `minio` (OCFL blobs), `temporal`/`hatchet`, optional `ollama`/`vllm`, `nginx`/traefik reverse proxy; `healthz` endpoints; config via env; migrations via Alembic run on boot/CI.
- Local dev: `docker compose up` + seed/fixture tooling; documented dev & prod setups (§38).

### 4.3 Testing
- **Unit:** locators, segments, assertions, provenance, merge/split reversibility, dependency invalidation, overrides, confidence, alignment, multilingual aliases, versioning, structured queries (§34).
- **Integration:** synthetic heterogeneous media (book, translated book, images/comic pages, multi-speaker audio, dialogue video, multiple subtitle tracks/languages, HI/SDH, adaptations, contradictions, missing/reordered events) (§34).
- **E2E:** ingest several related heterogeneous sources → decompose → align → resolve → graph → answer → return source refs → user corrects entity → invalidate descendants → rerun only affected → new answer reflects correction → audit explains change (DoD #30).
- **Adversarial correctness review (DoD #34)** must specifically probe provenance loss, source/semantic conflation, irreversible merges, invalidation errors, stale semantics, broken locators, cross-language collapse, adaptation conflation, race conditions, job restart, cross-store inconsistency, unsafe media handling.

### 4.4 Security (§32)
No shell interpolation; subprocess args as lists; sandbox (nsjail/bubblewrap/gVisor) around dangerous parsers; rlimits/cgroups/timeouts/file-size/archive-safe-extraction/path-traversal prevention; never trust filenames (OTF content-addressed object keys); structured errors/logs; per-request tracing.

### 4.5 Observability (§33)
structlog structured logs; job status + per-stage timing + per-stage cost/time; model-invocation metrics; failure counts; queue depth; cache hit rate; per-source decomposition report ("why is this slow/incomplete"); Prometheus metrics + OpenTelemetry traces (optional, plan-compatible with Temporal/Hatchet/XTDB).

### 4.6 Repository layout (greenfield)
```
/workspace/Universeity/
  Task.md
  pyproject.toml
  src/umd_api/
    api/            # FastAPI routers (sources, segments, claims, graph, search, provenance, audit, jobs, health, capabilities)
    core/           # domain model, stable IDs, locators, error types
    ingestion/      # POST /sources handling, OCFL blob writes, upload guards
    extractors/     # per-modality plugins: text, epub, pdf, image, audio, video, subtitle
    segmentation/   # deterministic segmenters + locator generation
    semantics/      # typed core + extensible assertions, predicates vocab
    provenance/     # PROV-O-aligned provenance, assertion evidence
    resolution/     # entity resolution (splink-style), blocking, merge/split records
    alignment/      # Vecalign/dtword aligners, correspondence assertions
    graph/          # projection build/traversal (Neo4j CE or RCTE), graph query API
    search/         # pgvector + tsvector + pg_trgm hybrid, kind-tagged results
    audit/          # semantic log queries, bitemporal/as-of views, XTDB witness
    jobs/           # stage-DAG definition, Temporal/Hatchet workers, Dagster assets, invalidation
    models/         # ModelProvider interface, registry, local(Ollama/vLLM)+remote backends
    storage/        # object store + relational + vector access, ownership model
  migrations/       # Alembic
  tests/            # unit/ integration/ e2e  (+ synthetic media fixtures)
  docs/             # architecture, models, locators, DAG, invalidation, provider ifaces, ownership, API, deployment, plugins, limitations, diagrams
  docker/  docker-compose.yml  Dockerfile  .env.example
```
Every Task.md section (1–41) maps onto one or more of the above; none is silently omitted (see §5 mapping).

---

## 5. Answered Questions (mapped to Task.md)

1. **Architecture that separates the four layers & avoids cross-store authority duplication (Q1).** Event-sourced semantic log (Postgres) as the single semantic authority + derived, rebuildable graph/vector/search projections + OCFL blobs + durable job engine. Each store's ownership explicitly defined (§22): blobs=OCFL; segments=Postgres; semantics/overrides/audit=log; embeddings=pgvector (derived); graph=projection; jobs=job engine state. §1, §2, §9, §10, §22.
2. **Concrete ingestion/extraction stack (Q2).** As in §2: pysubs2/pandoc/ebooklib/PyMuPDF-or-pdfplumber; Pillow+PaddleOCR/Tesseract (+CV/YOLO); PyAV+ffmpeg+faster-whisper+pyannote+silero; PyAV+Pyscenedetect+subtitle-demux; sandboxed via nsjail/bubblewrap/gVisor+rlimits/cgroups/timeouts. §26, §27, §32.
3. **Sound designs for the hard problems (Q3).** §3: EPUB CFI/Media-Fragments/IIIF/Web-Annotation locators; Vecalign word/sentence + DTW alignment with many-to-many confidence-bearing correspondence; reversible resolution via log-only merge/split + splink scoring; typed+extensible assertions (RDF 1.2 triple terms / PROV-O / JSONB); append-only overrides/history (bitemporal); stage-DAG + Temporal/Hatchet + Dagster selective invalidation; typed REST + GQL/Cypher query; pgvector hybrid + tsvector exact search; ModelProvider with Ollama/vLLM local + remote. §4, §5, §6, §7, §11, §12, §13, §14, §15, §16, §18, §20, §21, §28, §29, §30, §31, §36.
4. **API/deploy/test/security/observability/repo structure (Q4).** §4 above covers §24, §34, §32, §33, §38, §39, §40/DoD, §37.

---

## 6. Adversarial technology comparison (for §35)

| Concern | Chosen / leading | Credible alternative | Benefits | Failure modes / maturity | Ops complexity | Data-migration | Surviving risks |
|---|---|---|---|---|---|---|---|
| Graph engine | Neo4j CE (projection) | Relational-RCTE; Memgraph; ArangoDB; Kuzu(✗) | Mature Cypher/GQL | CE single-node, GPLv3; Kuzu archived; Memgraph OOM+disk-mode churn; AGE slow executor | Medium (Neo4j server) | None (projection rebuilds from log) | Cyber/HA licensing; GQL still landing |
| Vector | pgvector | Qdrant/Milvus/LanceDB; OpenSearch/Vespa | Co-tenancy, exact search | HNSW approximate (tune ef_search); scale ceiling single PG | Low | None (same store) | Very-large-scale recall/throughput |
| Blob truth | OCFL over FS/MinIO | S3 raw; DVC | Standard layout, content-addressing, versioning | OCFL tooling maturity; AGPL/Q2 deps n/a | Low | None | Large blob cost; GC |
| Semantic authority/audit | Postgres append-only log | XTDB 2 (as primary or witness); Dolt; event-store | SQL, JSONB, single authority | Rely on own log correctness (make atomic) | Low | None | Trigger-free auditing is DIY → XTDB witness optional |
| Durable jobs | Temporal (+Dagster assets) | Hatchet; DBOS; Celery | Replay/retry/reset, battle-tested | Temporal ops overhead; Dagster not durable by itself | High (Temporal) / Low (Hatchet) | Low | Job engine vendor; deterministic-replay discipline |
| Model serving | Ollama (local) + vLLM (scale) + remote; LiteLLM router | TGI; ONNX-RT; sentence-transformers | Self-host (DoD #28), swappable | Ollama single-user concurrency; vLLM Linux/GPU | Medium | None (interface) | GPU availability; gated models (pyannote) |
| OCR | PaddleOCR (scene/CJK) + Tesseract (clean) | VLM OCR (PaddleOCR-VL, Mistral OCR) | CJK/vertical + structured | ~500MB deps; VLM needs GPU | Medium | None | Accuracy on noisy manga; layout |
| Subtitle | pysubs2 (MIT) per-track | ffmpeg demux + own | preserves track identity §27 | format edge cases | Low | None | SDH/sign/type detection |
| PDF | pdfplumber/pypdf (MIT/BSD) | PyMuPDF(AGPL) | permissive license | pdfplumber slower | Low | None | PyMuPDF AGPL if speed needed |

**Maturity & licensing watch-items:** PyMuPDF & ebooklib & essentia are AGPL (Q2 — verify per stack). Kuzu discontinued. Memgraph BSL + in-RAM. Neo4j CE single-node GPLv3. pyannote models gated. YOLO (Ultralytics) AGPL since 2024 — prefer permissive fork or OpenCV DNN if needed.

---

## 7. Open questions (design author should resolve)

1. **Job engine:** Temporal (robust, heavy ops) vs Hatchet (Postgres-native, lighter, younger) vs roll-own PG queue — the author should trade ops budget vs durability guarantees. Dagster is a complement, not a replacement.
2. **Graph engine or not:** is a dedicated graph engine (Neo4j CE, single-node) worth the license/ops for §17 deep traversal vs relational-RCTE (bounded-depth)? Drives whether GQL/Cypher becomes a public surface.
3. **Semantic slice:** plain typed core + JSONB assertions (simpler) vs RDF 1.2 triple terms + SHACL (richer interop, heavier). Either meets §36; confidence-of-`confidence` and provenance-on-provenance favors triple-term semantics.
4. **XTDB role:** as primary semantic store (Postgres-wire, bitemporal out of the box) vs secondary witness over a Postgres log. JVM ops cost vs "no triggers/audit-tables".
5. **AGPL tolerance** for PDF/EPUB/essentia — acceptable if FF/sandbox-isolated and project is AGPL-compatible, or avoid (choose MIT/BSD equivalents).
6. **GPU profile** for ASR/diarization/VLM in the local/self-hostable path — hardware budget determines whether OLLAMA/VLLM/PaddleOCR-VL are viable vs CPU-only Tesseract/faster-whisper int8.

---

## 8. Recommendations for the caller (design author / planner)

1. **Adopt the event-sourced semantic-log + rebuildable-projections architecture** — it is the single design move that simultaneously satisfies §7, §15, §21, §22, §28, §29 and makes §16/§34 tractable. Do NOT make the graph DB the authority.
2. **Do not pick Kuzu; be cautious with Memgraph (in-memory/disk churn) and Apache AGE (executor performance).** Neo4j CE (single-node, GPLv3) or relational-RCTE are the safe graph choices for greenfield; treat the graph as a projection.
3. **Start with PostgreSQL + pgvector as the single operational structured+vector store**, OCFL for blobs, and only add a dedicated graph/vector engine when measured scale demands it — this keeps cross-store authority minimal.
4. **Use the specified per-modality libraries with license care** (Q2), run every untrusted parser in nsjail/bubblewrap/gVisor with cgroups/rlimits/timeouts, and treat embedded subtitle tracks as independent evidence sources (pysubs2, no flattening).
5. **Make model providers a first-class swappable interface** (Ollama-local / vLLM / remote via LiteLLM) meeting DoD #28 without vendor lock-in (§13).
6. **Map every Task.md section to a repo module and test** (§5) so no requirement is silently omitted; build the synthetic heterogeneous-media fixtures for integration/E2E early.
7. **Paths NOT to take:** single monolithic opaque pipeline (§6 violated); graph DB as semantic authority (§22/§29 violated); destructive in-place semantic updates (§15 violated); relying on Neo4j Enterprise features in CE (§1.2); YOLO-AGPL or PyMuPDF/ebooklib in a non-AGPL-compatible distribution without isolation (§2).

---

## 9. Sources

**Specifications / standards**
- Task.md — `/workspace/Universeity/Task.md` (lines 1–1738). Artifact baseline: `/workspace/Universeity/artifacts/logs/support-librarian.log.jsonl` (L1).
- RDF 1.2 Concepts — https://www.w3.org/TR/rdf12-concepts/ (CR snapshot 2026-04-07); N-Triples/N-Quads/Turtle updates.
- PROV-O / PROV-DM — https://www.w3.org/TR/prov-o/, https://www.w3.org/TR/prov-dm/ (Rec 2013).
- W3C Media Fragments URI 1.0 — https://www.w3.org/TR/media-frags/ (Rec 2012).
- EPUB CFI 1.1 — https://idpf.org/epub/linking/cfi/, https://w3c.github.io/epub-specs/epub33/epubcfi/; EPUB 3.3 — https://www.w3.org/TR/epub-33/ (Rec 2026-01-13).
- IIIF Image API 3.0 — https://iiif.io/api/image/3.0/.
- OCFL 1.1 — https://ocfl.io/1.1/spec/.
- GQL — ISO/IEC 39075 (industry status 2026: broad engine support targeting end-2026; per youngju.dev 2026 graph roundup).

**Databases / storage**
- Neo4j open-core — https://neo4j.com/open-core-and-neo4j/; operations-manual (CE vs EE).
- Memgraph storage modes docs — https://memgraph.com/docs/fundamentals/data-durability, deployment/best-practices; PR #3360 "Remove ON_DISK_TRANSACTIONAL".
- Apache AGE — https://github.com/apache/age; 2026 discussion #2305 (PG18, roadmap, cadence).
- Kuzu archived — https://github.com/kuzudb/kuzu.
- XTDB 2.0 — https://github.com/xtdb/xtdb (v2.0.0 release); https://xtdb.com/blog/launching-xtdb-v2.
- pgvector — https://github.com/pgvector/pgvector (HNSW/halfvec/sparsevec/bit, exact search, ef_search); Context7 `/pgvector/pgvector`.
- 2026 graph/vector/AGE benchmarks (directional, vendor-adjacent): jaesolshin.com/posts/graph-db-benchmark-8-engines/; rizlabs.com/can-one-postgresql-replace-your-graph-database; youngju.dev 2026 graph roundup.

**Jobs / orchestration**
- Temporal — /temporalio/documentation (durable execution, event history, replay, reset, retries).
- Hatchet — https://hatchet.run/versus/hatchet-vs-temporal; dreaming.press/posts/tool-highlight-hatchet; youngju.dev 2026 workflow roundup.
- Dagster — https://docs.dagster.io (software-defined assets, freshness, auto-materialize); Context7 `/websites/dagster_io`.

**Extraction / ML**
- PyMuPDF — https://pypi.org/project/pymupdf/ (AGPL/commercial); pymupdf.io/blog (AGPL); pdfplumber — https://pypi.org/project/pdfplumber/ (MIT); pypdf (BSD).
- ebooklib — https://github.com/aerkalov/ebooklib (AGPL-3.0).
- pysubs2 — https://github.com/tkarabela/pysubs2 (MIT).
- PaddleOCR — https://github.com/PaddlePaddle/PaddleOCR (Apache 2.0; PP-OCRv5/v6, PaddleOCR-VL); Tesseract 5 — tesseract-ocr (Apache 2.0); EasyOCR (Apache 2.0).
- faster-whisper — https://github.com/SYSTRAN/faster-whisper (MIT; CTranslate2; large-v3-turbo; int8 CPU; PyAV).
- pyannote.audio — https://github.com/pyannote/pyannote-audio (MIT); gated models — https://huggingface.co/pyannote/speaker-diarization-3.1.
- PySceneDetect — https://github.com/Breakthrough/PySceneDetect, https://www.scenedetect.com/docs (BSD-3; PyAV backend; VFR).
- PyAV — https://github.com/PyAV-Org/PyAV (BSD; FFmpeg bindings).
- Vecalign — https://github.com/thompsonb/vecalign; ACL D19-1136. awesome-align — https://github.com/neulab/awesome-align. SimAlign — EMNLP 2020 (aclanthology.org/2020.findings-emnlp.147).
- splink — https://github.com/moj-analytical-services/splink; Fellegi-Sunter topic guide.
- Ollama / vLLM — llmbestpractices.com/ai-agents/ollama-serving; open-techstack.com/blog/vllm-vs-ollama-2026; docs.vllm.ai openai_compatible_server; gigagpu.com openai-compatible guide.

**Sandboxing**
- nsjail — https://github.com/google/nsjail (nsjail.dev); bubblewrap — https://github.com/containers/bubblewrap; gVisor — https://github.com/google/gvisor (gvisor.dev).

**API/framework**
- FastAPI — Context7 `/websites/fastapi_tiangolo` (OpenAPI, Pydantic v2).
