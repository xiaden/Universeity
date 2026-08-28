# Model / Provider Contracts

Provider behavior is exposed through a single `ModelProvider` contract with
`completion` and `embedding` responsibilities. Every provider call is a
recorded call: versions, configuration digest, in/out tokens, error, and
latency are retained for audit and per-evidence `generated_by` metadata. **The
semantic schema never depends on a specific provider or model**; a provider is a
substitutable adapter completing typed operations, not a layer that owns
semantic authority. gated entries are labeled and reported gated by
`GET /v1/capabilities`.

## Capability report (v1 defaults echoed by `/v1/capabilities`)

- **Embedding provider**: `umd-deterministic-local` (active fallback).
- **Vector backend**: `exact_fallback` active (`exact-fallback-in-process`);
  `pgvector_hnsw` **gated/inactive** below the 0.8.2 extension gate.
- **Semantic authority**: `tier0-ledger; projections never authoritative`.
- **Linkage** (`umd-reference-linkage`): splink **gated**/not active.
- **Alignment** (`umd-reference-aligner`): vecalign **gated**/not active.
- **Raster OCR** (`umd-reference-ocr`): active default (in-process, deterministic
  template/rule matching — no pixels fabricated, no identity claim). Tesseract is
  reported **configured-but-unavailable** when the `tesseract` binary is absent,
  never active; PaddleOCR remains a named **GATE**.
- **Raster spatial** (`umd-reference-spatial`): active (panel/region + bounded
  face/object observations as `candidate_kind=observation` only).
- Modality / provider configuration is versioned; `relationships_bounded=true`,
  `query_max_depth` and `query_max_limit` are reported from the live settings.

## Provider table

| Provider | Role | Posture |
|---|---|---|
| tesseract | raster OCR enhancer | **configured-but-unavailable** when the `tesseract` binary is absent (reported, never active); reference OCR active in base |
| PaddleOCR | raster OCR enhancer | **GATED** (`umd-raster.ocr.PADDLE_GATE`); reference OCR active in base |
| faster-whisper | ASR | **GATED** — pinned offline weights; best-effort filter signals |
| pyannote | diarization | **GATED + legal gate** (`UMD_DIARIZATION_LEGAL_GATE`, pinned weights) |
| PySceneDetect | video scene enhancer | **GATED** (`UMD_SCENE_ENGINE_PYSCENEDETECT`); reference ffmpeg scene in base |
| PyAV | video decode enhancer | **GATED** (`UMD_VIDEO_DECODE_PYAV`); reference ffmpeg in base |
| splink + DuckDB | interpretable linkage | **GATED** — pinned DuckDB 1.3.x on >=3x planner regression; blocking keys benchmarked |
| vecalign | cross-source alignment | **GATED** — **parallel-text-only** in v1 |
| pgvector-HNSW | vector search | **GATED** below `vector_hnsw_min_version` (>=0.8.2); CVE-2026-3172 floor |
| vLLM | online LLM | **GATED** via `UMD_VLLM_ENABLED` |
| Ollama | local embedding/LLM host | optional compose profile (`gpu`) |
| Hatchet | durable DAG runner | **GATED** — exact release pin v0.50.0 is a build gate; in-process runner is the local/job facade |

## Substitution and honesty

- A provider that is not provisioned reports as **gated**, never active.
- The **exact-fallback in-process** embedder/search is the active default when
  no vector backend is gated open — it is not a silent stub, and `/v1/search`
  reports the active `engine` and `vector_backend` in every response.
- The `ModelProvider` contract is the boundary: swapping a provider (local
  deterministic ↔ remote ↔ vLLM) requires only an adapter change, and no change
  to the semantic schema or query language.

## Licensing / CVE gates

See [security.md](security.md) and
`deploy/security/{CVE_WATCH,LICENSE_REVIEW}.md`: every gated model and AGPL-adjacent
dependency carries an explicit legal/cve review as a build/release gate.