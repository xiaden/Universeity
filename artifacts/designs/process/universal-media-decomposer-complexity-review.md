# Universal Media Decomposer API — Structural Complexity Review

**Status:** DONE — analysis complete; read-only (no code, no plan, no DD amendments)
**Date:** 2026-08-25
**Agent:** `rnd-complexity-advisor`
**Scope:** Proposed greenfield repository/service architecture: FastAPI boundary; PostgreSQL event-sourced semantic ledger and relational metadata; OCFL immutable blobs; rebuildable graph/vector/search projections; durable workflow/job engine; modality plugins and model-provider adapters; provenance/stable-locator contracts; alignment/entity resolution; security sandbox; observability; Docker/Compose and tests/docs.
**Inputs:**
- `Task.md` (§§1–41, lines 1–1739) — authoritative requirements, treated as non-negotiable
- `artifacts/designs/process/universal-media-decomposer-technology-research.md` (support-researcher)
- `artifacts/designs/process/universal-media-decomposer-adversarial-log.md` (T1–T8, all turns)
- `artifacts/designs/process/universal-media-decomposer-architecture-options.md` (Option A recommended)
- `artifacts/designs/pending/DD-universal-media-decomposer.md` (constraint skeleton)
- `artifacts/logs/support-librarian.log.jsonl` (L1: greenfield baseline, no prior ADRs/ASRs/DDs/plans)

---

## 1. Executive assessment

**The architecture is ELEVATED in complexity, but the elevation is overwhelmingly requirement-mandated, and the principal complexity driver — the event-sourced semantic ledger with rebuildable single-writer projections — is the *simplest correct* design for the stated requirements, not the most elaborate one available.** The adversarial record (T1–T8) already rejected the structurally simpler-looking alternatives (mutable graph authority, bitemporal engine authority, RDF co-authority) on documented evidence; my review independently confirms those rejections hold up.

The accidental complexity is concentrated and reducible in four specific places:

1. **Two orchestration systems (Hatchet runner + Dagster declaration) where one runner plus an in-repo lineage table would serve §16 with less machinery.**
2. **Optional projections (Neo4j graph, RDF claim graph) carried into the v1 footprint** despite the design's own evidence that relational + recursive CTE covers the first release and the projections are only needed when measured traversal demand appears.
3. **Two protocol near-aliases (Embedder ≈ ModelProvider; Reconciler ≈ Analyzer subtype)** that will cost naming and interface upkeep without adding capability.
4. **A large long-term tax position** — event-schema/upcaster discipline, projection lag/blue-green operations, single-reducer common-mode risk — that must be *budgeted* in the DD as product work rather than listed as one-time setup, or the §2 audit guarantee silently degrades (Overeem: 8/19 production event-sourced systems mutated events and forfeited their audit trail).

No simplification below violates Task.md. Each simplification still satisfies the requirement; what changes is *when* an extension point is built and *how much machinery is live on day one*. The single most important message to DDAuthor: **the DD should fence the v1 projection set to {current_state, pgvector, tsvector/pg_trgm} and name graph/RDF/dedicated-vector/XTDB-witness as phase-2 extensions behind the already-designed projection interfaces — not build them in v1.**

---

## 2. Method

This is a greenfield repository. There are no existing project patterns to compare against (`support-librarian.log.jsonl` L1 confirms zero prior artifacts). Per my role, the comparison baseline is therefore **the requirements themselves and the minimum machinery each requirement demands**, with the T1–T8 adversarial record treated as the project's own accumulated evidence.

For each architectural component I asked: *Does the requirement force this structure, or does the design volunteer it?* Findings are rated by confidence; MEDIUM means "check before acting — hidden justification may exist." The adversarial log already documented most of these components; my contribution is the *complexity calculus*: what earns its keep, what is redundant, and what the DD should phase or fuse.

Facts (requirement text, evidence citations, adversarial verdicts) are distinguished from judgment (my analysis) throughout.

---

## 3. Structure map

What the proposed architecture actually is (from architecture-options Option A + adversarial Final Patterns):

| Layer | Mechanism | Authority |
|---|---|---|
| Source bytes | OCFL 1.1 content-addressed objects (fs/MinIO/S3) | OCFL authoritative |
| Sources/segments/locators | Postgres relational tables; `source://` versioned locators | Postgres authoritative |
| Semantic facts | Append-only `semantic_event` log (13-field envelope, versioned payloads, upcasters) | **Single write path** |
| Current state | Tier-0 `current_state` table, same transaction as event append | Same tx as log |
| Graph/vector/search/RDF | Tier-1 projections, replay-built by single-writer builders, blue-green | Disposable, rebuildable |
| Jobs | Hatchet durable DAGs + `stage_run` UNIQUE-key dedup + `job_run_audit` off-stream | Engine advisory; log authoritative |
| Modality | 10 protocols (Ingestor…ProjectionBuilder) + concrete v1 matrix (text/image/audio/video/subtitle) | Contract-only |
| Security | bubblewrap sandbox-runner container; PyAV/FFmpeg/extraction in-sandbox | Boundary document |
| Query | Typed REST primary; optional Cypher/GQL adapter over graph projection; semantic QA compiler; hybrid search | — |

Deployment: one API+worker image (split is an ops scaling choice, explicitly not a service requirement) plus Postgres, object store, sandbox-runner, Hatchet. This is the correct anti-over-decomposition posture.

---

## 4. Justified complexity — what earns its keep

These components are *not* over-engineering. They are the minimal structure that makes hard requirements structural rather than conventional. Removing any of them breaks Task.md.

### 4.1 Event-sourced semantic ledger (§2, §7, §15, §21, §29)
**Justified. HIGH confidence.** The five hard requirements — provenance never lost (§2), overrides as first-class precedence data with no invisible mutation (§7), append-only/versioned editing (§15), audit answering why/prev/what-changed (§21), *reversible* entity merges (§29) — are the set that event sourcing exists to serve. The adversarial record's evidence is decisive here:
- The empirically documented alternative, mutable authority + changelog mirror, broke both recovery directions in Nat Pryce's production postmortem (T2, Approach B verdict).
- The empirical study of 19 production event-sourced systems found 8/19 abandoned immutability even when the pattern made it *structurally natural* (Overeem, JSS 2021); a by-convention discipline over a mutable store is the weaker bet (T2).

A DDAuthor tempted to "simplify" this to direct relational tables with an audit trail would be trading a structurally-guaranteed §29/§21 for a discipline-guaranteed one, and the DoD (#30, #34) demands those behaviors as *passing tests*. **This finding is the one to resist simplification on.** The correct response to its cost is to budget the discipline (see §7.1), not to abandon it.

Critically, the design already draws the *right* event boundary: the semantic log contains interpretations, edits, alignments, resolutions, overrides, invalidations, and stage completions — while deterministic derived data (segments, evidence artifacts, embeddings) lives in typed tables and OCFL blobs, not as events. This is not "event-source everything," and the DD must not drift in either direction (event-sourcing evidence rows would inflate seq and replay cost; classifying overrides as ordinary derived rows would forfeit §7).

### 4.2 Tier-0 current_state + Tier-1 projections (§7 hot path, §22 rebuildability)
**Justified. HIGH confidence.** §7 ("override then immediate query never returns pre-override truth") is a hard requirement, and a purely async projection can only meet it with unbounded waits or stale reads — both rejected on record (T4 concern 1; T5 Pattern 3). The Tier-0 same-transaction row is the *cheapest* correct mechanism for the hot path. The design correctly closes the Tier-0/Tier-1 divergence risk with a **single shared `reduce_current_state` function** (T7 Final Pattern 3) — one implementation, not two. This is a genuine simplification already made; it must not be undone in the DD, and the common-mode risk it swaps in (a reducer bug corrupts both tiers identically) is accepted and bounded by the pure/total-function contract and the ≤5ms p99 Tier-0 budget (T8, accepted).

### 4.3 Sandbox-runner separation (§32)
**Justified. HIGH confidence.** §32 mandates sandboxing of dangerous parsers and containment of parser failure. A separate `sandbox-runner` container (bubblewrap, documented caps, sandlock fallback) is a security boundary, not service decomposition — the API/worker image is expressly *not* privileged. The July-2026 FFmpeg CVE class (T6 R5.3) makes parser isolation a hard requirement, and PyAV's in-process FFmpeg means demux/decode must run in the sandboxed subprocess.

### 4.4 Plugin protocol set (§25) and the stage-DAG/job machinery (§6, §16, §23)
**Justified. HIGH confidence.** Task.md §25 *explicitly enumerates* ingestors, extractors, segmenters, analyzers, aligners, reconcilers, model providers, embedders, and storage backends. The 10-protocol list in architecture-options is a 1:1 map of that enumeration plus ProjectionBuilder, which is the honest name for the projection single-writer requirement (T2 critique A2). The DAG-with-`stage_run`-UNIQUE-key-dedup machinery looks heavy, but it answers documented, cited engine defects (Hatchet idempotency beta bugs #4129/#4454/#3674, DAG retry bugs #3860/#1507/#3243/#4372) — this is *hardened defensive complexity responding to evidence*, not speculative future-proofing.

### 4.5 Unified search/vector in Postgres (§20, §22)
**Justified. HIGH confidence.** The design's own research and the adversarial record identify a dedicated vector DB as a day-one anti-pattern (unnecessary sync/authority surface before measured pgvector scale). Keeping tsvector/pg_trgm + pgvector in one Postgres, with embeddings on a separate immutable table (T7 R3.4: resolves pgvector #875 100× UPDATE penalty), is the minimal config that satisfies §20. The `VectorIndex` interface is the escape hatch — defined, but not another engine.

---

## 5. Accidental complexity — findings

### F1 — Dagster + Hatchet: two orchestration systems carrying one load (MEDIUM)
**Location:** T5 Pattern 1 / architecture-options data flow (step 6: "Dagster may declare asset lineage/freshness… Hatchet is the only runner"; T4 concern 8: Dagster auto-materialize disabled in production).
**Concern:** Dagster's software-defined asset graph, freshness policies, and auto-materialize are its *raison d'être* — and the design disables all of them in production. What remains is "Dagster declares the DAG + lineage, Hatchet runs it." But the lineage information (§16: what downstream state becomes stale) already exists twice elsewhere: (a) Hatchet's DAG `parents` edges, and (b) stage manifests' `input_refs`/`evidence_refs`, which is what actually determines staleness (a stage depends on the evidence it consumed, not only on the stage name). Dagster therefore mirrors dependency data that is already live in two other places.
**Evidence:** T4 concern 8 explicitly flags the two-systems-racing risk ("both can decide when projection assets recompute"); T5 resolved it by neutering Dagster's schedulers — at which point Dagster is a graph-declaration library with a separate deployment surface, whose freshness engine (the one differentiator) is off.
**Simplification:** Drop Dagster from the v1 footprint. Define the stage DAG **once** in the Hatchet workflow definition, and derive the §16 dependency table (`stage_dependency(stage, depends_on_stage, evidence_class)`) from that same definition plus stage-manifest input classes. `InvalidationPlanner.plan(causation, lineage)` becomes a small pure function over one in-repo table, which is *less* machinery and easier to test than two tools whose schedulers must never both run. Re-introduce Dagster (or any asset-freshness tool) behind the existing projection interface only when a measured need for declarative freshness/freshness-policy ops appears.
**Risk introduced by simplification:** §16 planner correctness now depends on our own lineage table + planner instead of a maintained library. **Mitigation:** the lineage table is generated from the same DAG definitions Hatchet executes (single source of truth); the §34 fixtures for targeted invalidation (unaffected stage checksums unchanged) are the acceptance test; Temporal remains the fallback if orchestration deepens (unchanged).
**Confidence:** MEDIUM — a peer could justify Dagster as "the maintained declaration surface for lineage." The counter is that the design already made Hatchet the sole executor, which is the only place lineage must stay authoritative.

### F2 — Optional graph and RDF projections inside the v1 footprint (MEDIUM-HIGH)
**Location:** architecture-options ownership map + suggested repo structure (`projections/graph/`, `projections/rdf/`), initial footprint estimate (18–24 packages), and pattern text treating Neo4j as available in the first release.
**Concern:** The design's *own* evidence says the v1 query requirements are met without a graph engine: "relational video-CCTE… is enough for the first release and avoids a second authoritative store" (technology-research §1.2/§6); §18 explicitly permits a typed REST query API with no graph engine; the T4-recommended C-as-projection is deferred ("one more replay-built projection" — not a day-one requirement). Deep-traversal demand ("variable-length path, shortest path, graph algorithms") is a *measured* need, and the §17 QA examples are bounded-depth (2–3 hops). Building a Neo4j graph projection (builder, checkpoint, blue-green swap, Cypher/GQL adapter, ops of a second server, GPLv3 CE backup/HA gap) plus an RDF claim-graph projection (Jena experimental label on RDF 1.2; GraphDB EE licensing) adds two projection builders, two operational surfaces, and two license/ops conversations to a first release whose dominant cost is already the media pipelines.
**Simplification:** Fence v1 to **typed REST query over Postgres** (current_state + relational + bounded-depth SQL traversal/recursive CTE for the §17 examples), pgvector, and tsvector/pg_trgm. Keep the `ProjectionBuilder`, `VectorIndex`, and query-adapter interfaces as *contracts in the DD*, but do not implement the graph and RDF projection builders, checkpoint tables, or adapters until a documented query pattern exceeds bounded-depth SQL (trigger: a measured §17 query class needing unbounded path traversal or graph algorithms). The graph/RDF projections are then mechanical phase-2 work *because the interface boundary exists on paper*.
**Risk introduced by simplification:** §17 QA depth ceiling in v1; no graph algorithms; no RDF exports for standards-oriented consumers (which §37/§36 do not require in v1 — typed REST + typed core + extensible predicates satisfy them). **Mitigation:** the typed query contract must *not* promise unbounded traversal in v1; document the v1 query-depth guarantee and the promotion trigger in the DD's known-limitations section.
**Confidence:** MEDIUM-HIGH. The residual doubt is that depth-3 QA on a relational implementation needs careful SQL design; the risk is implementation effort, not architecture.

### F3 — Protocol near-aliases: Embedder ≈ ModelProvider; Reconciler ≈ Analyzer subtype (LOW-MEDIUM)
**Location:** architecture-options protocol table.
**Concern:** Task.md §25 mandates embedders and analyzers and reconcilers as interface categories, so neither can be *removed*. But the design can reduce the *number of distinct contracts*: an Embedder is a ModelProvider called with an embedding model + a storage directive (the append-only embedding table); a Reconciler emits reconciliation events much as an Analyzer emits analysis events. Keeping all three as fully separate protocols with separate registries, fixtures, and documentation multiplies interface upkeep without adding capability.
**Simplification:** Define `ModelProvider` with a `mode ∈ {completion, embedding}` and make `Embedder` an alias/typed wrapper, not a parallel contract. Define `Reconciler` as a sub-interface of `Analyzer` (same StageInput/StageOutput envelope, restricted event vocabulary) rather than a sibling protocol. This does not change the plugin matrix; it changes the number of *contract families* from 10 to 8 and matches the actual v1 implementations.
**Risk introduced:** negligible — purely a naming/interface-organization change; the modality matrix in §26 is unaffected.
**Confidence:** MEDIUM — if a future modality needs genuinely distinguishable reconciliation capability (contradiction-preserving merge semantics), the sub-interface can be promoted without breaking v1 plugins.

### F4 — Event-schema/upcaster discipline treated as setup rather than standing tax (MEDIUM)
**Location:** T5 Pattern 3; T2 critique A1; architecture-options con "event schema/upcaster discipline is mandatory and will be ongoing work."
**Concern:** This is not a code-complexity finding but a *budget* finding. The single most documented failure mode of the entire chosen pattern is schema drift (Overeem; Doomen projector coupling; both cited in T2). The design has the right artifacts (versioned envelopes, `schemas/events/*/v<n>.json`, colocated upcasters, CI back-compat gate) — but the DD must treat upcasting + historical-fixture conformance as a **permanent feature line with staffing and test budget**, not a one-time migration discipline, or the §2 audit guarantee quietly erodes. Every event schema change ships an upcaster + a historical-replay test; that cadence is part of the product.
**Simplification/action:** None (the machinery is correct); the complexity must be *acknowledged as permanent*, which is a scoping/planning requirement for DDAuthor, not a code change.

### F5 — Consistency contract surface (token + stale_at + 503/Retry-After classes) (JUSTIFIED — no action)
The read-your-writes token, in-band `x-consistency` classes, fail-fast-503, and mandatory jittered backoff look like API surface bloat, but each element answers a documented failure mode (T2 critique 6: stale reads violate §7; T6 R3.3/X6: retry amplification during rebuilds; T7: 409/425 rejected for documented reasons). This is *required* surface given §7 + async projections. **Keep as specified; resist future simplification** — a simpler "serve stale with a marker" contract would violate §7's hot path, and a single undifferentiated 503 has already been shown to mislead clients.

---

## 6. Specifically assessed concerns (from the review request)

| Concern | Verdict |
|---|---|
| Multi-store authority duplication | **Minimal and explicit.** One semantic write path (log + same-tx Tier-0); OCFL owns bytes; Hatchet is advisory (log/`stage_run` authoritative); graph/vector/search are expressly disposable. No twin authorities (the rejected B/C/D failure mode) exist in A. |
| Over-decomposition into services | **Avoided.** One API+worker image; sandbox-runner is a security boundary, not decomposition. No service-per-ability split. |
| Event sourcing vs direct relational state | **Justified.** §7/§15/§21/§29 are structurally served; the by-convention alternative is documented-weaker (8/19 abandonment rate; dual-write postmortem). Event boundary (semantics yes, derived evidence no) is correctly drawn. |
| Graph projection necessity | **Not needed in v1.** Typed REST + bounded-depth SQL satisfies §17/§18; defer graph/RDF projections behind interfaces (F2). |
| Workflow engine/DAG complexity | **One runner suffices in v1.** Hatchet executes the DAG; drop Dagster; derive lineage from the same DAG definition (F1). The `stage_run` dedup/audit machinery is justified defense against cited engine defects. |
| Plugin/interface proliferation | **Mostly requirements-mandated (§25).** Two near-aliases to fuse (F3). Do not shrink the modality matrix — §26 mandates real pipelines. |
| Separate search/vector/graph layers | **Search+vector unified in Postgres (good).** Graph/RDF deferred (F2); dedicated vector DB and XTDB witness already correctly deferred with gates. |
| Representative modality pipelines coherently shippable | **Yes, if v1 extraction fidelity is scoped per modality.** Text (structure+entities+semantics), image (metadata+OCR+regions+objects), audio (ASR+speaker candidates; diarization behind fallback gate), video (tracks+scenes+ASR+subtitle events) are coherent on the shared contract. The §26 list is *aspirational extraction breadth* — define per-modality v1 tiers in the DD so "coherently shipped" means depth-capped, tested, E2E-wired — not every §26 bullet at maximum fidelity. The E2E correction→invalidation→rerun test (DoD #30) is the coherence proof. |

---

## 7. Concrete limitations and extension paths the DD must state (not hide)

The recommendation is *not* to build these; it is to name them so the simplification is honest:

1. **Common-mode reducer risk**: one `reduce_current_state` serves Tier-0 and Tier-1; a bug corrupts both identically (accepted tradeoff, T8). State the pure/total contract and the conformance tests as product requirements.
2. **Locator stability is bounded by content stability, not by design**: EPUB CFI declares invalid references when structure shifts; ffmpeg/PyAV demuxer changes shift PTS-derived locators. Mitigation (versioning, `SourceAliased`/`LocatorRebased`, quarantine, selective invalidation) makes drift *detectable and re-runnable*, not impossible (T7 Final Pattern 2). Extension path: forced alignment (WhisperX-style phoneme) for audio drift — phase-2, gated.
3. **Async projection lag is a real availability cost**: token-bearing Tier-1 reads 503 during rebuilds (fail-fast, by contract). Extension path: long-rebuild routing through the §23 job/poll API (T8 Q2) is a documented alternative — keep the recommendation's single-503 contract for v1 but note the poll-API option.
4. **Vector scale ceiling**: pgvector <50M vectors; embeddings append-only means churn accumulates rows (REINDEX CONCURRENTLY cadence). Extension path: dedicated vector engine behind `VectorIndex` when measured thresholds breached (documented staircase 5M/10M/50M).
5. **Semantic event volume grows with semantic work** (not ops — the `job_run_audit` split resolved that): entity-stream growth under merge churn (Doomen 100k-event streams) is the cited risk; snapshots/checkpoints + bounded winner-resolution are the mitigations. State rebuild-budget expectations per projection.
6. **Open risks already carried** (from T8, correct to surface in the DD): pyannote weights license **undisclosed** (legal gate, U1); whisper hallucination filter is **best-effort** not detector-grade (F1 23.6% on the signal trio, U2); splink/DuckDB planner regression gate (U3); bubblewrap host-profile matrix (U4, Ubuntu 24.04 manual AppArmor profile); sandlock unvalidated (U8 checkpoint item). None block design distillation (T8 verdict) — all are named gates.
7. **§12 alignment depth for adaptation pairs is intentionally reduced** (Vecalign restricted to parallel text; adaptation paths use DTW/embedding/LLM) — a product-facing limitation the DD should state (T8 Q5 accepted).

---

## 8. Recommendations to DDAuthor (priority order)

1. **Keep the event-sourced ledger, Tier-0/Tier-1 split, single shared reducer, `stage_run` dedup authority, and `job_run_audit` off-stream split** — these are the correctly-designed core. Do not accept "simplify to direct relational + audit table" arguments; the evidence against that trade is in the adversarial log (T2) and empirical (Overeem 8/19).
2. **Cut Dagster from v1.** Derive the §16 lineage table from the single Hatchet DAG definition; test the planner with the §34 targeted-invalidation fixtures. (F1)
3. **Fence the v1 projection set: current_state + pgvector + tsvector/pg_trgm.** Keep the projection/vector/query interfaces in the DD as *contracts*; defer Neo4j graph, RDF claim-graph, dedicated vector engine, and XTDB witness behind stated triggers (unbounded traversal need; RDF interop requirement; measured vector scale; bitemporal witness value decision). (F2)
4. **Fuse Embedder into ModelProvider (mode flag) and Reconciler into Analyzer (sub-interface).** (F3)
5. **Define per-modality v1 extraction tiers** so "coherently shippable" means depth-capped and E2E-proof (DoD #30), not maximal §26 breadth. Diarization stays behind the pyannote gate fallback; the §14 promotion ban and transcription-scoped confidence are the real hallucination containment.
6. **Budget the upcaster/historical-fixture line as permanent product work** and state the v1 query-depth guarantee in known limitations. (F4/F2)
7. **Carry every T8 open item as a named gate** (pyannote license, Hatchet/FFmpeg/pyannote/bwrap/sandlock pins, splink build benchmark, platform sandbox matrix) with a milestone trigger — exactly as the adversarial record concludes. Do not resolve them silently in the DD.

---

## 9. Verdict

- **Complexity level: ELEVATED** (with respect to a fictional minimal API), **but justified** against Task.md's hard requirements.
- **Accidental complexity** (reducible): Dagster redundancy (F1), in-v1 optional projections (F2), protocol near-aliases (F3).
- **Justified complexity** (must keep): event-sourced semantic ledger + projections, Tier-0/Tier-1 with single reducer, sandbox boundary, plugin protocols, hardened job/dedup machinery, consistency contract.
- **Net**: the architecture is *simpler than it could be without violating Task.md* once F1–F3 are applied. The largest remaining cost is not structural — it is the permanent discipline budget (upcasting, projection ops, sandbox maintenance, CVE watch) that the DD must scope as ongoing product work.

*End of review.*