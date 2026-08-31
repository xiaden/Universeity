# Semantic Capability Parity Matrix — The Lantern Keeper

_Phase 3 of TASK-universal-media-decomposer-P-semantic-book-fixture-parity-e2e — produced from the oracle over the book fixture, augmented with the P3 production-verification evidence. Generated 2026-08-30T23:00:00Z (UTC)._

## Fixture identification

- Title: **The Lantern Keeper**
- Content shape: 2 chapters, 3 scenes (`At the Lamp Posts`, `The Warden's House`, `The Watchtower`), 3 distinct characters (`Mara`, `Ellis`, `Orin`), 4 aliases (`Moss`, `the apprentice`, `the cartographer`, `the warden`), 2 traits (`moss-green eyes` / Mara, `grey beard` / Orin), 1 relationship (Mara–Ellis siblings), narration + dialogue, multiple utterances, explicit + implicit speaker candidates, repeated presence, and one ambiguous narrator-never-confirmed fact.
- Evidence config digest (structural evidence): `umd-dispatch@1`
- Source SHA512 per format:
    - `txt`: `cc4ea6d9bb43926e73157c0fce68d9650c31343ea74c9522d6ec2757a31b048c0dec14510661a11052957446a06c6228a3a15fac245a49a65d097b98a051054f`
    - `markdown`: `f4ae873b78c029ce685da05b9a78f51ff6391b8c2392b4bc09a8ab2ba063a326f31bb1abfbdf6c6d1bb400f617bf4974bb99c4393276e3867b9cef210710bfad`
    - `epub`: `7fb5edb922e30f69274256260069d33bfabceea4d0c022826a726ba493a7c1762f534ec25ae6ae21589e850f3396e1c960c91d9a971566f05100aee4663273cc`

## Provider gate (honest — never faked as PASS)

`GATED` — no live provider is configured in this environment. The provider and hybrid rows below were exercised through the production seam using a registered **fake provider** (`fake_semantic`) whose observations carry **real provenance** (`provider`, `model`, `model_version`, `prompt_version`, `config_digest` recorded on the committed evidence). The unexecuted *live*-provider mode is reported honestly as `GATED` / `unexecuted_live_provider` and is **never** reported as PASS.

## Run modes actually executed (basis of this matrix)

- **deterministic** — real production `StageWork` composition over the book fixture through the hermetic app (`build_context(runner='hermetic')`, `StageWorkRegistryFactory`-built registry, all 9 stages), durable evidence + semantic events + replay projections. Verified in P3-S1/S2/S3.
- **provider / hybrid** — the same production seam with `FakeSemanticProvider` registered into `ProviderRegistry` + `settings.semantic.provider='fake_semantic'` + `.model='qwen-test'`; the provider is genuinely invoked (real model request) and its observations are committed as durable evidence with provider provenance (P3-S2).
- **Production typed-query gap (documented, not fabricated):** provider alias/trait observations are committed as *evidence* but are **not promoted** to `current_state` / `active_semantic_edge` / search in the current pipeline (`_Composer._reconciliation_input` runs a deterministic-only analyzer). Consequently the public typed surfaces (`ENTITY`, `RELATIONSHIP_EDGES`, `SEARCH`) return 0 for aliases/traits; the aliases/traits are retrievable through the public evidence surface with provider provenance.

## Parity matrix (walk × route)

# Semantic Capability Parity Matrix — The Lantern Keeper

- Fixture sha512: `epub=7fb5edb922e30f69274256260069d33bfabceea4d0c022826a726ba493a7c1762f534ec25ae6ae21589e850f3396e1c960c91d9a971566f05100aee4663273cc, markdown=f4ae873b78c029ce685da05b9a78f51ff6391b8c2392b4bc09a8ab2ba063a326f31bb1abfbdf6c6d1bb400f617bf4974bb99c4393276e3867b9cef210710bfad, txt=cc4ea6d9bb43926e73157c0fce68d9650c31343ea74c9522d6ec2757a31b048c0dec14510661a11052957446a06c6228a3a15fac245a49a65d097b98a051054f`
- Provider gate: `GATED` — no live provider configured; provider/hybrid modes exercised via a registered fake provider 'fake_semantic' (real provenance recorded per row); the unexecuted live-provider mode is reported honestly as GATED

| Walk | Route | Status | Authority | Confidence | State | Scope | #support | Gate | Notes |
|------|-------|--------|-----------|------------|-------|-------|----------|------|-------|
| 2a | deterministic | PASS | deterministic | 0.996 | PROBABLE | chapter/1, chapter/1/paragraph/1, chapter/1/paragraph/2, +331 more | 334 | - |  |
| 2a | provider | UNSUPPORTED | - | - | - | - | 0 | unexecuted_live_provider | provider produced no observations for this walk |
| 2a | hybrid | PASS | deterministic | 0.996 | PROBABLE | chapter/1, chapter/1/paragraph/1, chapter/1/paragraph/2, +331 more | 334 | unexecuted_live_provider | hybrid == deterministic U provider (no fabrication, no loss) |
| 2b | deterministic | PASS | deterministic | 0.300 | PROBABLE | chapter/1/paragraph/1, chapter/1/paragraph/2, chapter/1/paragraph/3, +6 more | 9 | - |  |
| 2b | provider | PASS | provider | 0.910 | PROBABLE | chapter/1/paragraph/1, chapter/1/section/1/paragraph/1, chapter/2/paragraph/14, +2 more | 5 | unexecuted_live_provider | evidence-supported extension of the deterministic baseline |
| 2b | hybrid | PASS | deterministic,provider | 0.529 | PROBABLE | chapter/1/paragraph/1, chapter/1/paragraph/2, chapter/1/paragraph/3, +10 more | 13 | unexecuted_live_provider | hybrid == deterministic U provider (no fabrication, no loss) |
| 2c | deterministic | UNSUPPORTED | - | - | - | - | 0 | - | deterministic path leaves this category ABSENT (honest degradation) |
| 2c | provider | PASS | provider | 0.888 | PROBABLE | chapter/1/paragraph/1, chapter/1/section/1/paragraph/1, chapter/2/paragraph/14, +2 more | 5 | unexecuted_live_provider | evidence-supported extension of the deterministic baseline |
| 2c | hybrid | PASS | provider | 0.888 | PROBABLE | chapter/1/paragraph/1, chapter/1/section/1/paragraph/1, chapter/2/paragraph/14, +2 more | 5 | unexecuted_live_provider | hybrid == deterministic U provider (no fabrication, no loss) |
| 2d | deterministic | PASS | deterministic | 0.300 | PROBABLE | chapter/1/paragraph/1, chapter/1/paragraph/2, chapter/1/paragraph/3, +6 more | 9 | - |  |
| 2d | provider | PASS | provider | 0.775 | PROBABLE | chapter/1/paragraph/1, chapter/1/paragraph/2, chapter/1/paragraph/3, +6 more | 9 | unexecuted_live_provider | evidence-supported extension of the deterministic baseline |
| 2d | hybrid | PASS | deterministic,provider | 0.511 | PROBABLE | chapter/1/paragraph/1, chapter/1/paragraph/2, chapter/1/paragraph/3, +6 more | 9 | unexecuted_live_provider | hybrid == deterministic U provider (no fabrication, no loss) |
| 2e | deterministic | PASS | deterministic | 0.657 | PROBABLE | chapter/1/paragraph/1, chapter/1/paragraph/2, chapter/1/paragraph/3, +34 more | 37 | - |  |
| 2e | provider | PASS | provider | 0.900 | PROBABLE | model_call:1130b91f06494f01b6f1bc4ff18e0248, model_call:41d886005f0141baa8cd5dd74b7c2f25, model_call:b3358a56205a4c37aa2d3ba806d69c84, +3 more | 6 | unexecuted_live_provider | evidence-supported extension of the deterministic baseline |
| 2e | hybrid | PASS | deterministic,provider | 0.667 | PROBABLE | chapter/1/paragraph/1, chapter/1/paragraph/2, chapter/1/paragraph/3, +40 more | 43 | unexecuted_live_provider | hybrid == deterministic U provider (no fabrication, no loss) |
| 2f | deterministic | UNSUPPORTED | - | - | - | - | 0 | - | deterministic path leaves this category ABSENT (honest degradation) |
| 2f | provider | PASS | provider | 0.900 | PROBABLE | chapter/1/paragraph/1, chapter/1/section/1/paragraph/1, chapter/2/paragraph/14, +2 more | 5 | unexecuted_live_provider | evidence-supported extension of the deterministic baseline |
| 2f | hybrid | PASS | provider | 0.900 | PROBABLE | chapter/1/paragraph/1, chapter/1/section/1/paragraph/1, chapter/2/paragraph/14, +2 more | 5 | unexecuted_live_provider | hybrid == deterministic U provider (no fabrication, no loss) |


## Walk definitions

- **2a** scene/structural segmentation · **2b** characters present in work · **2c** aliases · **2d** scene membership / repeated presence · **2e** narration + dialogue / utterances / speaker attribution · **2f** traits / descriptions.
- `#support` = count of distinct support refs/locators backing the walk claims. The oracle stores the full `support_refs` (evidence refs) on each row; the rendered table truncates them to the first few.

## P3 production-verification proof (public reads)

1. **Deterministic run (P3-S2 test):** via public HTTP — `SCENE` >= 3 structural scenes; `UTTERANCE` >= 1 with predicate `SPEAKS`; `RELATIONSHIP_EDGES` >= 1 with >= 3 distinct character subjects (`MENTIONED_IN`/`PRESENT_IN` → Mara/Ellis/Orin); `EVIDENCE` retrieved with locator + provenance; `CONTRADICTIONS` == 0 (the ambiguous narrator-never-confirmed statement is NOT authoritative). Search for `Mara`/`siblings`/`moss-green` honestly returns 0 (deterministic refs are content-hash UUIDs — documented gap).
2. **Provider-seam run (P3-S2 test):** the fake provider is invoked through the production stage (model request anchored to input refs); its observations are committed as durable evidence with provider provenance; the model-call record carries >= 2 aliases and >= 2 traits. Typed surfaces (`ENTITY`, search) honestly return 0 — provider observations are evidence, not promoted assertions.
3. **Correction/override (P3-S3 test):** a `USER_OVERRIDE` on a deterministic `SPEAKS` utterance survives a selective descendant rerun of `SEMANTIC_RECONCILIATION` (atomic Tier-0 read stays corrected, `data.authority == USER_OVERRIDE`); unaffected segment/evidence checksums are byte-stable; active relationship edges update (`RELATIONSHIP_EDGES` reflects the corrected `SPEAKS` with `USER_OVERRIDE` authority); historical events remain queryable (append-only ledger retains the superseded machine assertion).

## Repeatability / determinism

- Durable evidence identity keys on identity material `(source_id, locator, evidence_kind, config_digest)` (`uq_evidence_identity`), not random UUIDs — repeat production runs produce byte-identical evidence identity material and the same semantic event stream (`stage_run` claim dedup prevents re-execution of committed work).

## Scope & honesty notes

- No `src/umd` production code was modified in Phase 3. The only production-side limitation observed is the typed-query promotion gap described above (report only; `src/umd/jobs/production.py` `_Composer._reconciliation_input`).

## R follow-up (2026-08-31) — provider observation reconciliation promotion

This section records Plan R (TASK-universal-media-decomposer-R-provider-observation-reconciliation-promotion), which wires the already-validated, committed provider observations into the existing deterministic-plus-provider reconciliation input. It **supersedes** the pre-R promotion limitation stated in the rows above (line 23 "not promoted to current_state / active_semantic_edge / search"; line 71 "the only production-side limitation … typed-query promotion gap") — those historical rows are retained as pre-R evidence and are not edited.

- `_Composer._reconciliation_input` (`src/umd/jobs/production.py:1843`) now retains the deterministic baseline **and** hydrates only committed, validated `semantic_observations` evidence (`_hydrate_provider_observations`, production.py:398; category/type-discriminated `_classify_provider_observation`, production.py:383), never re-invoking a provider.
- Verified: provider aliases→`ALIAS_OF`/`KNOWN_AS`, traits→`HAS_TRAIT`, scene→`STARTS_AT`, presence→`PRESENT_IN`, utterance+speaker→`SPEAKS`/`UTTERED_IN`, emotions/states/context→`HAS_EMOTION`/`IN_STATE`/`HAS_CONTEXT`, supported `CO_OCCURS`→`CO_OCCURS`; unsupported `SIBLING_OF` and ambiguous "??" stay evidence-only.
- Provider candidates reach `current_state` (reducer-owned), replay-only `active_semantic_edge`, `RELATIONSHIP_EDGES`, semantic questions, and edge-derived exact/fuzzy/hybrid search — all via the existing command/ledger/reducer/replay/search-builder path (no direct projection writes; `SearchProjectionBuilder` remains the sole search writer).
- Live-provider route remains **`GATED` / `unexecuted_live_provider`** (no live provider in this environment); all provider-route evidence in this follow-up is from the registered fake provider carrying real provenance.
