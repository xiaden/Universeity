# Known Limitations and v1 Boundaries

These are **accepted** boundaries of the v1 implementation. The API and
documentation never hide them.

## Embedding dimension mismatch / hash collisions

- Provider embeddings use a fixed-dimension contract. Embedding **hash
  collisions**, dimension mismatches, and near-duplicate embeddings are handled
  by deduplication and NO-COW append-once storage — never by overwrite. A
  deterministic fallback vectors remain stable across dimension changes.

## v1 graph traversal is bounded

Typed REST over PostgreSQL covers the **bounded** questions v1 must answer.
There is no arbitrary-depth graph in v1; `max_depth` is capped (server-clamped)
and `relationships_bounded=true` is reported by `/v1/capabilities`. Any unbounded
traversal or graph-algorithm demand is deferred to a measured extension (see
[extensions.md](extensions.md)).

## Locator drift

Content, EPUB structure, decoder, and renderer changes may invalidate locators.
`@v`, `SourceAliased`, `LocatorRebased`, quarantine, and selective invalidation
detect and manage drift — they **do not eliminate it**. Forced audio alignment
is a deferred extension. (See [locators.md](locators.md).)

## ASR / hallucination filtering is best-effort

Filter signals are best-effort; detector performance is known-weak on the
adversarial record. The enforceable controls are: raw-evidence retention,
`HallucinationFiltered`, transcription-scoped confidence, and a **prohibition
on automatic semantic promotion**. Filter thresholds carry their own
version/input dependency and invalidate ASR descendants when changed.

## Adaptation alignment is parallel-only

Vecalign is **parallel-text-only** deliberately. Non-parallel adaptations use
less granular but more honest temporal/embedding/LLM evidence, labeled
`ADAPTATION`/`TEMPORAL` with explicit assumptions. (U-numbers in the risk
register track the associated u-estimation/blocking-key risks.)

## Reducer common mode

A single reducer avoids Tier-0/Tier-1 drift but can share a bug. Pure/total
contracts, payload tests, replay checks, and cross-tier E2E bound the risk.

## Projection / provider gates

The following are **not active in the base deployment** until their gates pass:
pgvector-HNSW (below 0.8.2), faster-whisper, pyannote (legal + pin), PySceneDetect,
splink/DuckDB, vecalign, vLLM, and Hatchet (exact pin v0.50.0). `/v1/capabilities`
always reports their true active/gated state.

## Operational taxes

- Locator drift management is a standing operational tax (not a one-time fix).
- Rebuilding a projection is budget-capped and single-writer; rebuilds take
  wall time during which tokened reads see the documented 503 contract.
- Remote/FUSE OCFL is staged through a local read-only spool with crash
  cleanup; setup/teardown has a small cost.

## Non-goals (explicit)

- No downstream media-generation product terminology (the service is
  API-neutral infrastructure).
- No semantic write outside the ledger; no projection is an authority.
- No pipelining a second scheduler in v1 (Dagster omitted; `Hatchet` plus one
  in-repository lineage definition avoids two schedulers).
- No flattening of subtitle tracks, editions, adaptations, or continuities.