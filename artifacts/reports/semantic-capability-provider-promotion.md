# Semantic Capability R — Provider Observation Reconciliation Promotion (Verification)

**Plan:** `TASK-universal-media-decomposer-R-provider-observation-reconciliation-promotion`
**Phase:** 4 (verification / artifact alignment of a feature plan)
**Status:** VERIFIED — mandatory Completion Criteria satisfied; live-provider / Docker / Hatchet / Kubernetes outcomes remain honestly `GATED`
**Date:** 2026-08-31
**Scope of this report:** narrowly the Plan R promotion wiring — evidence-backed provider observations reaching the reconciliation input, the existing reconciler/ledger/reducer/replay path, and the public structured/semantic/evidence/search surfaces. It is **not** a re-write of Q's release evidence or the parity matrix.

---

## 1. Evidence basis (exact commands)

| Gate | Command | Result |
|---|---|---|
| Ruff | `.venv/bin/ruff check src tests` | **All checks passed!** |
| Mypy (repo source gate) | `.venv/bin/mypy --strict src` | **Success: no issues found in 181 source files** |
| Focused suites | `UMD_TEST_POSTGRES=true .venv/bin/pytest -q tests/test_semantic_analysis.py tests/test_reconciliation.py tests/test_reconciliation_postgres.py tests/test_reconciliation_provider_promotion.py tests/test_resolution_mentions.py tests/test_resolution_service.py tests/test_active_edge_projection.py tests/test_search_edge_reconciliation.py tests/test_projection_phase2.py tests/test_api_contract.py tests/test_production_stage_registry.py tests/test_semantic_parity_oracle.py tests/test_semantic_book_fixture.py` | **173 passed, 0 skipped, 0 failed** (1 harmless StarletteDeprecationWarning) in 248.06s |
| **Full suite (authoritative)** | `UMD_TEST_POSTGRES=true .venv/bin/pytest -q` | **796 passed, 17 skipped, 0 failed** (1 warning) in 549.42s |

The full-suite aggregate is the authoritative release gate. **796 = 779 (Q baseline) + 12 Phase-2 + 4 Phase-3 net + 1 Phase-3 repaired stage-registry test = 17 net new passing over pre-R** (the Phase-3 net is `test_phase3_book_provider_semantic_questions_public_surface`, `…_search_after_replay_and_freshness_gates`, `…_evidence_reads_expose_observations_and_provenance`, plus the lockstep-updated `…_aliases_and_traits_through_production_seam`). The 17 skips are the same honest gates Q enumerated (§5 of `semantic-capability-verification.md`): 4 Docker/compose, 1 Docker daemon, 1 kubectl/Kubernetes, 5 no-live-Hatchet, 3 faster-whisper, 3 tesseract. **No skip was converted to a pass; no gate was weakened.**

---

## 2. Fake-provider exercised vs live-provider `GATED` (honest distinction)

**Fake-provider exercised behavior — PASS (with committed evidence).** All provider-route behavior below was driven through the real production seam (`_Composer._structural_analysis` → `_reconciliation_input` → `SemanticReconciler` → `SemanticCommandService.assert_semantic` → replay → edge/search builders) using a **registered fake provider** (`_LanternProvider` / `lantern_semantic` / `lantern-qwen`) whose observations are committed as durable evidence with **real provenance** (`provider`, `model`, `model_version`, `prompt_version`, `config_digest`). The provider is genuinely invoked once (`provider.calls == 1`) and is **never re-invoked** during reconciliation, replay, or search. These results are **PASS with evidence**, not fake readiness.

**Live-provider — `GATED`.** No live provider is configured in this environment. The unexecuted *live*-provider route remains **`GATED` / `unexecuted_live_provider`** and is **never reported as PASS**. Likewise Docker/compose, a live Hatchet cluster, and managed-Kubernetes remain **`GATED`** (see §5 of the Q report; re-confirmed by the 17 full-suite skips).

---

## 3. Historical pre-R evidence preserved (NOT rewritten)

- `artifacts/reports/semantic-capability-verification.md` — Q's release report. Its **§6 known limitation 1** ("Promotion gap: provider evidence is evidence-only", referencing `_Composer._reconciliation_input` running a deterministic-only analyzer) is **retained verbatim as historical pre-R evidence**; it is **not** rewritten to claim R's behavior.
- `artifacts/reports/semantic-capability-parity-matrix.md` — the Lantern Keeper parity matrix. Its **original run basis (lines 19–23) and all prior rows (lines 33–71) are retained unchanged**, including the pre-R "not promoted" statement (line 23) and "No `src/umd` production code was modified in Phase 3" scope note (line 71). A **clearly dated follow-up section** (§6 below) was appended rather than editing those rows.

---

## 4. R implementation mapped to the CONTRACTS.md:84 contract and the Completion Criteria

`CONTRACTS.md:84` (`_Composer._reconciliation_input`) is the binding contract the R implementation satisfies:

| CONTRACTS.md:84 clause | Implementation ref | Verified by (test) |
|---|---|---|
| "production reconciliation reuses the deterministic baseline" | `_reconciliation_input` retains the unchanged `SemanticTextAnalyzer(None, provider=None, model=None)` deterministic analyzer over the memoized dispatch | `test_p2s3_deterministic_unsupported_categories_unchanged_without_provider`; deterministic scene/1 STARTS_AT present in provider-enabled stream |
| "hydrates only committed, validated `semantic_observations` evidence from the preceding provider-aware analysis" | `_hydrate_provider_observations` (production.py:398) reads `self._evidence.get_by_source(src["id"])`; no raw/unvalidated model output consumed | `test_p2s1_*`, `test_p2s4_rejected_observations_degrade_to_baseline_with_warnings` |
| "never re-invokes a provider" | hydration is a pure projection over committed evidence; `provider.calls == 1` after the structural analysis and never grows during reconciliation/replay | `test_p2s5_reconciliation_is_idempotent_and_never_reinvokes_provider`, `test_p3s2_*` (`assert len(provider.calls)==1` after replay) |
| "category/type-discriminated, exact-segment-locator validated" | `_classify_provider_observation` (production.py:383) exact one-category-key match (zero=unknown, >1=ambiguous); exact `obs.segment.locator` membership in the reconciliation input's locator set | `test_p2s4_*` malformed/unknown/stale-support cases; `test_p2s1_*` exact locator support |
| "preserves each candidate's exact `SegmentEvidenceRef`, confidence, semantic state, and `GeneratedBy` provider/model/model-version/prompt/config metadata" | re-validation via `cls.model_validate(payload)` (strict, no repair); top-level `generated_by` keeps `path="deterministic"` stage provenance while each candidate carries provider identity; reconciler merges `_provenance()` | `test_p2s2_provider_events_retain_support_confidence_state_and_provenance` |
| "Provider and deterministic observations are unioned without fabrication; malformed, unsupported, stale, gated, unavailable, ambiguous, or invalid-support observations remain evidence/warnings and are not asserted" | deterministic buckets extended in-place; per-row warnings + one "provider configured but no evidence rehydrated" warning | `test_p2s3_provider_union_no_loss_no_dup`, `test_p2s4_unsupported_predicate_evidence_stays_evidence_only`, `test_p2s4_missing_model_degrades_with_honest_warning`, `test_p2s4_unregistered_provider_degrades_with_honest_warning` |
| "Provider entity/alias candidates may feed the existing pure `mentions_from_semantic`/`EntityResolutionService` bridge, retaining Plan N ledger-first string refs, nullable UUID FKs, unresolved ambiguity, and no fabricated entity rows or human-readable refs" | `_reconciliation_input` unions deterministic committed-evidence mentions with `mentions_from_semantic(analysis)`, deduped by `mention_id`; unchanged `EntityResolutionService` (Plan N rules) | `test_p2s1_*`, `test_resolution_*` unchanged; `test_phase3_book_provider_evidence_reads_…` (content-addressed refs, no human-readable refs) |
| "must not write ledger/projection stores directly" | seam is a pure reconciliation-input builder; materialization only via `SemanticCommandService.assert_semantic` (ledger) and replay builders | `test_p2s5_*` (zero current_state/semantic_assertion/search_document rows from the pure seam), `test_p3s1_*` (provider facts via ledger, not projections), `test_p3s5_*` (search empty until replay) |

**Completion Criteria mapping (P4-S4 full ledger in §7).** All five criteria are satisfied: (1) evidence-backed events for all supported fixture categories while deterministic stays present and malformed/unsupported/ambiguous stays non-promoted — PASS (P2-S1/S3/S4); (2) events, scalar current reads, replay edges, structured queries, semantic questions, evidence reads, and edge-derived exact/fuzzy/hybrid search expose provider candidates with exact support/provenance/confidence/state and bounded freshness — PASS (P2-S2, P3-S2..S6); (3) repeated runs/retries and wipe/replay converge without duplicate evidence/events or provider re-invocation; corrections/invalidations/locks/`USER_OVERRIDE` authority correct and immutable history retained — PASS (P2-S5/S6, P3-S5); (4) focused/Postgres/static/full-suite verification recorded observable results; optional live-provider/Docker/Hatchet outcomes remain `GATED` — PASS (§1); (5) no architecture/authority/topology/storage/projection-ownership/provider-gating/human-readable-ref constraint weakened — PASS (P4-S5 §8).

---

## 5. Verified public-surface behavior (with honest retained limitations)

Verified through the real hermetic app (`create_app(..., runner='hermetic')`) with `_LanternProvider` registered, over *The Lantern Keeper* book fixture, using `POST /v1/sources` → job-complete polling (provider invoked once):

- **Structured query — `POST /v1/query/structured`.** `RELATIONSHIP_EDGES` positively returns provider-backed edges: `KNOWN_AS` ('the apprentice'/'the cartographer'/'the warden'), `HAS_TRAIT` ('moss-green eyes'/'grey beard'), `ALIAS_OF` present, plus `STARTS_AT`/`PRESENT_IN`/`SPEAKS`/`UTTERED_IN`/`CO_OCCURS`. `EVIDENCE` reads expose provider semantic-observation evidence with exact locators and content-addressed (36-char UUID) refs.
- **Semantic question — `POST /v1/query/semantic`.** A relationship question built from a real provider `KNOWN_AS` edge compiles to `['RELATIONSHIP_EDGES']`, answers with `predicate=='KNOWN_AS'`, matching confidence, and `SOURCE_EVIDENCE` result-kind; `requires_edge_guard(...)` is `True` (edge freshness gate applies). 'who is the apprentice' compiles to `SEARCH_HYBRID` with an `INTERPRETATION` alternative (provider edge doc surfaced as a typed alternative). 'evidence' (limit 3) is bounded, all `SOURCE_EVIDENCE`.
- **Search — `POST /v1/search` (exact / fuzzy / hybrid).** Provider edge documents become visible **only after** the active-edge replay + search freshness gates: before `_build_all`, `moss-green` search returns 0 and `search_document` rows are 0 (reconciliation never writes search docs directly); after replay (`CurrentTierOneBuilder → ActiveSemanticEdgeProjectionBuilder → SearchProjectionBuilder`), exact/fuzzy/hybrid all return the provider text ('moss-green eyes', 'the apprentice', 'resolute'). Every search doc kind ∈ {INTERPRETATION, SOURCE_EVIDENCE, CANONICAL_ENTITY} — `SearchProjectionBuilder` is the **sole** search writer. A correction rebuild (`record_correction` 'moss-green eyes'→'emerald eyes') removes the stale provider doc and indexes the corrected value.
- **Evidence reads.** `provider.calls == 1`; `semantic_observations` evidence rows expose `tool_versions.provider`, per-observation `generated_by.path=='provider'` + provider/model, exact `chapter/` locators, and retained warnings; the unsupported `SIBLING_OF` observation stays evidence-only. Evidence refs are content-addressed UUIDs — no surface invents a human-readable reference or presents model output as authority.

**Honest limitations that RETAIN (not failures of the R wiring):**
1. `ENTITY` canonical `total == 0` — the book fixture emits **no `EntityResolved` events**, so there are no `CANONICAL_ENTITY` current_state rows; provider aliases surface as `KNOWN_AS`/`ALIAS_OF` **edges** (asserted positively), not as fabricated canonical entities. This is the *expected* honest non-promotion (the fixture intentionally lacks a resolution promotion step that would emit EntityResolved).
2. **'siblings' unsupported predicate** (`SIBLING_OF` is not a registered reconciler predicate) — the observation stays evidence-only; search for 'siblings' returns 0. Honest non-promotion.
3. **'Mara' content-hash ref** — the deterministic canonical ref for Mara is a content-addressed UUID, not display text, so a bare 'Mara' search returns 0 on the typed search surface (unchanged from the deterministic baseline; not an R regression).
4. **Question-surface `generated_by` empty on edge derivation** — the edge-derived question answer surfaces the edge's own provenance/confidence with provider identity on the *edge*, while the top-level question `generated_by` remains empty/stage-level; provider identity is carried on the edge derivation, not fabricated onto the question envelope.

---

## 6. Parity-matrix follow-up (added; original rows and run basis retained unchanged)

The following section was **appended** to `artifacts/reports/semantic-capability-parity-matrix.md` below the existing §5 ("Scope & honesty notes"). The original run basis (lines 19–23), parity table (lines 33–51), walk definitions, P3 production-verification proof, repeatability section, and scope/honesty notes (including the pre-R "not promoted" statement and "No `src/umd` production code was modified in Phase 3" note) are **retained verbatim** as historical pre-R evidence.

```markdown
## R follow-up (2026-08-31) — provider observation reconciliation promotion

This section records Plan R (TASK-universal-media-decomposer-R-provider-observation-reconciliation-promotion), which wires the already-validated, committed provider observations into the existing deterministic-plus-provider reconciliation input. It **supersedes** the pre-R promotion limitation stated in the rows above (line 23 "not promoted to current_state / active_semantic_edge / search"; line 71 "the only production-side limitation … typed-query promotion gap") — those historical rows are retained as pre-R evidence and are not edited.

- `_Composer._reconciliation_input` (`src/umd/jobs/production.py:1843`) now retains the deterministic baseline **and** hydrates only committed, validated `semantic_observations` evidence (`_hydrate_provider_observations`, production.py:398; category/type-discriminated `_classify_provider_observation`, production.py:383), never re-invoking a provider.
- Verified: provider aliases→`ALIAS_OF`/`KNOWN_AS`, traits→`HAS_TRAIT`, scene→`STARTS_AT`, presence→`PRESENT_IN`, utterance+speaker→`SPEAKS`/`UTTERED_IN`, emotions/states/context→`HAS_EMOTION`/`IN_STATE`/`HAS_CONTEXT`, supported `CO_OCCURS`→`CO_OCCURS`; unsupported `SIBLING_OF` and ambiguous "??" stay evidence-only.
- Provider candidates reach `current_state` (reducer-owned), replay-only `active_semantic_edge`, `RELATIONSHIP_EDGES`, semantic questions, and edge-derived exact/fuzzy/hybrid search — all via the existing command/ledger/reducer/replay/search-builder path (no direct projection writes; `SearchProjectionBuilder` remains the sole search writer).
- Live-provider route remains **`GATED` / `unexecuted_live_provider`** (no live provider in this environment); all provider-route evidence in this follow-up is from the registered fake provider carrying real provenance.
```

---

## 7. Requirement-mapping table (P4-S4)

| # | Mandatory requirement | Implementation ref | Test ref | Status |
|---|---|---|---|---|
| 1 | Provider candidates usable by reconciliation / query / search | `_hydrate_provider_observations` (production.py:398), `_reconciliation_input` (production.py:1843) | `test_p2s1_provider_categories_promote_to_reconciler_events`; `test_phase3_book_provider_aliases_and_traits_through_production_seam`; `test_phase3_book_provider_search_after_replay_and_freshness_gates`; `test_phase3_book_provider_semantic_questions_public_surface` | **PASS** |
| 2 | Deterministic baseline retained | unchanged `SemanticTextAnalyzer(None, provider=None, model=None)` in `_reconciliation_input`; union is additive | `test_p2s3_provider_union_no_loss_no_dup`; `test_p2s3_deterministic_unsupported_categories_unchanged_without_provider` | **PASS** |
| 3 | Exact refs / provenance / confidence retained | strict `cls.model_validate`; exact locators; reconciler `_provenance()` merges provider `GeneratedBy` | `test_p2s2_provider_events_retain_support_confidence_state_and_provenance`; `test_p3s2_…full_provenance`; `test_p3s6_…evidence_reads…` | **PASS** |
| 4 | Malformed / unsupported providers honest | `_classify_provider_observation` rejection; truthful warnings; no fabrication | `test_p2s4_rejected_observations_degrade_to_baseline_with_warnings`; `test_p2s4_unsupported_predicate_evidence_stays_evidence_only`; `test_p2s4_missing_model_…`; `test_p2s4_unregistered_provider_…` | **PASS** |
| 5 | Model never authority | hydration is evidence-only; promotion only via `assert_semantic` + ledger; reducer/replay authority unchanged | `test_p2s1_unsupported_and_ambiguous_stay_evidence_only_never_fabricated`; `test_p2s4_*`; `test_p3s1_*via_ledger_not_projections` | **PASS** |
| 6 | Idempotent retries | evidence-identity dedup; converging event set; no provider re-invocation | `test_p2s5_reconciliation_is_idempotent_and_never_reinvokes_provider`; `test_p3s2_*` | **PASS** |
| 7 | User overrides / locks preserved | `record_override` / lock outrank provider machine; mirror precedence; immutable history | `test_p2s6_user_override_wins_over_provider_machine_and_survives_rerun`; `test_p2s6_lock_blocks_provider_machine_and_selective_rerun_preserves_unrelated`; `test_p3s5_*` correction rebuild | **PASS** |
| 8 | No fabricated human-readable refs | Plan N string canonical refs; content-addressed evidence; no invented 'Mara said …' | `test_p3s6_…evidence_reads…` (36-char UUID refs); `test_phase3_book_provider_evidence_reads_expose_observations_and_provenance` | **PASS** |

---

## 8. Prohibited-change verification (P4-S5)

Verified against the working-tree diff and code scan (see §6 of the plan P4-S5 step for the full no-change statement):

- **No new DD / no research artifact:** no DD created; the only new artifact is this report.
- **No migration / database change:** no migration added; the R seam is a pure reconciliation-input projection over committed evidence (`migrations/` untouched).
- **No graph store:** `active_semantic_edge` is the existing replay-built Postgres projection (unchanged).
- **No direct projection writer:** the seam writes zero projection rows (P2-S5); `assert_semantic` (ledger) and the replay builders remain the only writers.
- **No Hatchet / job topology change:** canonical nine-stage DAG untouched (`set(registry)==STAGE_ORDER`); no scheduler/workflow change.
- **No OCFL authority change, no ledger-authority redesign:** source/ledger authority unchanged; `semantic_assertion` remains a mirror, not a competing authority.
- **No projection-ownership change:** reducer owns `current_state`; replay builders own edges/search; `SearchProjectionBuilder` remains the sole search writer.
- **No provider-gate weakening:** all honest provider/Docker/Hatchet/Kubernetes gates retained (17 skips unchanged).
- **No unrelated modality/provider-gate edits:** only the R-scoped semantic reconciliation promotion path changed.

---

## 9. Doc edits (P4-S3)

Docs were reviewed against the verified post-R behavior; **only proven-stale claims were edited**:

- **`docs/providers.md` (edited — 1 claim proven stale).** The provider-backed-path bullet previously read *"merged observations stay candidate/evidence (`can_auto_promote=false`) — the **model never writes semantic tables, projections, or authority state**."* The second clause remains true, but the first clause ("stay candidate/evidence") is proven stale by R. It was revised to state that the model/analyzer never writes semantic tables/projections/authority **directly**, while validated provider observations are rehydrated into the production reconciliation input (`_Composer._reconciliation_input`) and promoted to `SemanticAsserted` events / `current_state` / `active_semantic_edge` / search **through the existing command/ledger/reducer/replay path** — model output remaining a candidate/observation, never authority.
- **`docs/query-search.md` (not edited).** No "provider observations never reach query/search" claim and no post-R-stale description found; the typed-surface/edge/search mechanics are accurate.
- **`docs/data-model.md` (not edited).** No stale claim; the mirror/edge/search-reconciliation descriptions are accurate post-R.

Q's historical report and the parity matrix's original rows are preserved as historical pre-R evidence (see §3, §6).

---

## 10. Release conclusion

- **Full suite:** `UMD_TEST_POSTGRES=true .venv/bin/pytest -q` → **796 passed, 17 skipped, 0 failed** (all 17 skips honest gates).
- **Static gates:** ruff clean; `mypy --strict src` clean (181 files).
- **Architecture:** no prohibited redesign; CONTRACTS.md:84 satisfied; `SearchProjectionBuilder` remains the sole search writer; canonical nine-stage DAG untouched.
- **Honesty:** fake-provider behavior reported **PASS with evidence**; live-provider / Docker / Hatchet / Kubernetes remain **`GATED`**; Q's report and parity matrix preserved as historical pre-R evidence.

**Verdict: VERIFIED.** Plan R's provider observation reconciliation promotion satisfies the mandatory Completion Criteria and CONTRACTS.md:84, with live-provider/hosted outcomes honestly GATED for CI.
