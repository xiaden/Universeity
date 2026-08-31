# Model / Provider Contracts

Provider behavior is exposed through a single `ModelProvider` contract with
`completion` and `embedding` responsibilities. Every provider call is a
recorded call: versions, configuration digest, in/out tokens, error, and
latency are retained for audit and per-evidence `generated_by` metadata. **The
semantic schema never depends on a specific provider or model**; a provider is a
substitutable adapter completing typed operations, not a layer that owns
semantic authority. gated provider entries (linkage, alignment, OCR, ASR,
spatial) are labeled and reported gated by `GET /v1/capabilities`; the semantic
analyzer's provider posture is the exception and is disclosed via
`STRUCTURAL_ANALYSIS` stage warnings (see below) rather than the capability
report.

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
- **Semantic text analysis** (`umd-semantic-analysis@1`): deterministic/reference
  baseline **active by default** (in-process `umd-text-structural@2`; unsupported
  categories left ABSENT, nothing fabricated); the optional provider-backed path
  is **configured-only** — it activates only when `UMD_SEMANTIC__PROVIDER` and
  `UMD_SEMANTIC__MODEL` are set AND a registered provider resolves AND the
  invocation succeeds. Anything less degrades to the reference baseline with a
  truthful stage warning, never a fabricated "provider success". Semantic
  posture is disclosed via the `STRUCTURAL_ANALYSIS` stage warnings; `GET
  /v1/capabilities` does not yet carry a `semantic-analysis` key.
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
| semantic analysis (`umd-semantic-analysis@1`) | optional text understanding | **reference** deterministic baseline active by default; provider-backed path **configured-only** (`reference` default) — reported honestly via stage warnings, never fabricated as active |

## Semantic text-analysis provider

Semantic text understanding is composed in the `STRUCTURAL_ANALYSIS` production
stage (CONTRACTS.md:75). It is a single `SemanticTextAnalyzer.analyze(input) ->
SemanticAnalysisResult` contract with two paths: a **deterministic/reference
baseline** that is always the safe result, and an **optional provider-backed
path** that may add validated, evidence-tied typed observations on top. Both
paths return the same provider-neutral `SemanticAnalysisResult`, so callers see
one validated shape regardless of which path produced it.

### Configuration

| Setting | Env var | Default | Meaning |
|---|---|---|---|
| `semantic.provider` | `UMD_SEMANTIC__PROVIDER` | `reference` | Provider name for the optional semantic-analysis path. `reference` (or empty) ⇒ deterministic-only. |
| `semantic.model` | `UMD_SEMANTIC__MODEL` | *(none)* | Model id for the provider path; a configured provider with no model is treated as unsupported and degrades honestly. |

Per the pydantic-settings nested-name invariant these use the **double-
underscore** form (`UMD_SEMANTIC__PROVIDER`, `UMD_SEMANTIC__MODEL`);
single-underscore spellings are silently ignored. The provider path reuses the
existing `ProviderRegistry` adapters (ollama / remote / vLLM) as-is — no bespoke
client — so swapping the backing model is a config change, not a code change.

### Deterministic baseline (the reference provider)

The deterministic path (`umd.analysis.text_structural` `analyze_segments` /
`analyze_text`) consumes the Plan-L chapter-aware paragraph segment records and
produces:

* **dialogue / narration** — quoted spans or speaker-directive dashes;
* **candidate mentions** — low-confidence entity-mention, presence, and
  co-occurrence relationship candidates pinned to their exact segment;
* **scene boundaries** — deterministic structural approximations from chapter
  transitions (low confidence).

Categories the deterministic path cannot honestly support (aliases, traits,
emotions, states, context) are left **ABSENT** — never inferred or fabricated.

### Optional provider-backed path

The provider path is attempted only when a provider AND a model are configured.
It invokes the model with a **versioned** prompt (`semantic-analysis@2`), a
config digest encoding the prompt/parser/analyzer versions, and the exact input
segment locators, then **strict-parses** the output
(`umd.analysis.semantic_parser.parse_semantic_output`):

* only observations that validate into the typed contract are kept;
* every provider call is recorded as durable model-call `METADATA` evidence, and
  the validated observations as a separate evidence row;
* a candidate is promoted only when it carries an **exact segment locator** that
  exists in the analyzed input AND a confidence (`P2-S4`); anything else is
  rejected, never promoted;
* the **model/analyzer never writes semantic tables, projections, or authority
  state directly** — its validated observations are committed as durable
  evidence and, since Plan R, are rehydrated into the production reconciliation
  input (`_Composer._reconciliation_input` hydrates only committed, validated
  `semantic_observations` evidence, never re-invoking the provider) and promoted
  to `SemanticAsserted` events, `current_state`, `active_semantic_edge`, and
  search **through the existing command/ledger/reducer/replay path**. The model
  output itself remains a candidate/observation; it never becomes authority.

### Typed + validated output

`SemanticAnalysisResult` is the single validated contract. It carries provenance
(`GeneratedBy`: path, analyzer, provider/model/version, prompt version, config
digest) and these observation categories, each a confidence-scoped
(`confidence` 0..1) candidate tied to an exact `SegmentEvidenceRef`:

| Category | Field | Type |
|---|---|---|
| Scene boundaries | `scene_boundaries` | `SceneBoundary` |
| Entity / character mentions | `entity_mentions` | `EntityMention` |
| Normalized aliases | `aliases` | `NormalizedAlias` |
| Scene / segment presence | `presence` | `Presence` |
| Utterance boundaries | `utterances` | `Utterance` |
| Speaker candidates | `speaker_candidates` | `SpeakerCandidate` |
| Descriptive traits | `traits` | `DescriptiveTrait` |
| Relationship candidates | `relationships` | `RelationshipCandidate` |
| Emotion observations | `emotions` | `EmotionObservation` |
| State observations | `states` | `StateObservation` |
| Context observations | `context` | `ContextObservation` |

(`StateObservation` records the observed narrative state under the `observed_state`
field, distinct from the candidate's `ConfidenceState`.)

### Honest degradation

An **unavailable / unsupported / disabled / gated / malformed** provider never
produces a fabricated result: the analyzer retains the deterministic/reference
baseline and records a truthful warning (e.g. a configured provider with no
model, a provider that raises `ModelProviderUnavailable`, or output that fails
strict parsing). The model call itself is still audited, but nothing it returned
is promoted. This mirrors the OCR/ASR gate pattern: the reference baseline is the
deterministic active default, and the provider-backed path is reported honestly
via the stage warnings — never as an invented active capability.

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