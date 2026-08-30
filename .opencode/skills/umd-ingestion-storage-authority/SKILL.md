---
name: umd-ingestion-storage-authority
description: UMD ingestion command path duplication (application/ingestion.py dead vs routers/sources.py live), OCFL bootstrap/readiness wiring (SourceStore.create, readiness_probe unused at runtime, /v1/ready projection-only), ingestion transaction drift (4+ txs, TOCTOU sha512 race, ledger complete_and_append fix), and authority ownership map (ledger=only semantic authority, evidence/segments via repositories, membership divergence). Load before touching sources.py, application/ingestion.py, storage/ocfl, repositories.py, ledger.py, or /v1/ready/health.
---

# UMD Ingestion / Storage / Authority

## Mental Model
UMD's authority stack: OCFL owns immutable source bytes → Postgres typed tables own source/work/segment/evidence rows → the append-only Postgres semantic ledger is the ONLY semantic write authority → disposable Tier-1 projections replay the ledger. The DD (artifacts/designs/pending/DD-universal-media-decomposer.md:45, 111-123) assigns command handlers + transaction boundaries to the `application` layer, but the live code routes ingestion through the REST router instead, and several ownership/transaction seams diverge from the DD.

## Coverage
**Documented:** ingestion command path duplication, OCFL bootstrap + readiness gaps, ingestion transaction boundaries + TOCTOU, authority ownership (ledger vs evidence/segments/membership), fix points.
**Not yet documented:** how SourceAliased/alignment reads consume memberships (nothing reads them today); GC/orphan policy for OCFL objects and evidence rows.
**Last extended:** 2026-08-30

## Key Findings

### Duplicate ingestion command path (dead app handler vs live router)
- `src/umd/application/ingestion.py:75-155` — `IngestionCommandHandler.ingest`, docstring "Versioned ingestion command path (P3-S4)". ONLY test callers (`test_ingestion.py`); grep `IngestionCommandHandler` in src/ = 1 match (the definition). Dead in production.
- `src/umd/api/routers/sources.py:164-252` — `_submit_source` re-implements the same command inline: `put_immutable` (:185), `find_source_by_sha512` (:199), `ensure_work`/`ensure_source` (:209-223), `record_source_ingested` (:224), `_dispatch` (:240). Never imports the handler.
- Divergence: app path calls `add_membership(role="primary")` (ingestion.py:128); REST path NEVER calls `add_membership` (repositories.py:432-438) → REST-ingested sources have no `source_membership` rows (tables.py:193 unique). Nothing reads memberships at runtime (grep `.memberships(` in src = 0) → latent defect.
- Divergence: job_id (app = uuid4 placeholder, no dispatch; REST = `job-{source_id[:12]}` + real dispatch sources.py:239-240); idempotency key (app = user-supplied; REST = `uuid5(NAMESPACE_URL, f"ingest:{source_id}")` :234); created_by; source_id format (str(uuid4()) vs hex).
- `src/umd/ingestion/__init__.py` = scaffold placeholder.

### OCFL bootstrap readiness
- Bootstrap OK: `SourceStore.create` (storage/ocfl/store.py:116-154) — idempotent, flock-serialized, staging-in-root then move; used by `build_source_store` (api/entrypoints.py:19-21) at API and worker start (deploy/cli.py:81). compose shares `ocfl-data:/data/ocfl` api (:87) + worker (:128), `UMD_OCFL__ROOT=/data/ocfl` (:24).
- GAP: `deploy/startup.py:108-167` `readiness_probe` includes an OCFL component (namaste + inventory) but is NOT wired at runtime — docker-entrypoint.sh (16-25) runs only migrations; `/v1/ready` (api/routers/system.py:93-111) and `/v1/health` (:86-90) check projections + scheduler only. OCFL root status invisible after startup; a degraded/lost root is never surfaced.

### Transaction drift (ingestion)
- Ingestion = OCFL FS write + ≥4 separate DB transactions (ensure_work, ensure_source, ledger append, dispatch). DD:50 says application owns transaction boundaries.
- Drift windows: orphan OCFL object (benign, no GC); orphan work row; source-row-without-SourceIngested (silent; only a client retry heals via sha512 dedup + deterministic uuid5 key); ledger-ok-but-dispatch-failed → job FAILED (application/jobs.py:117-122) + 500.
- TOCTOU: `find_source_by_sha512` (repositories.py:396-405) then `ensure_source` (:407-430) in separate txs; `source.sha512` UNIQUE (tables.py:136) → concurrent identical uploads: second `ensure_source` IntegrityError → unhandled 500. `ensure_source` has NO on_conflict_do_nothing.
- Ledger fix already exists: `complete_and_append` (ledger.py:94-120) + `_append_all_events_on` (:122-213); docstring :83-86 explicitly says side-effect anchors must share the append connection. Ingestion does not use it.
- Evidence/segments: written by stage work in OWN transactions (evidence.record repositories.py:229-290, segment put :54-76) BEFORE StageCompleted `complete_and_append` (stage_execution.py:273-333). Crash → re-run dedups (uq_evidence_identity, migrations 0003); abandoned jobs leave orphan evidence rows.

### Authority ownership
- DD:45, 111-123 ownership invariants; app.py:272-273; system.py:147 `semantic_authority: tier0-ledger; projections never authoritative`; docs/consistency.md. Ledger append-only enforced by DB trigger (migrations 0001:34-50).
- Reality: evidence + segments written DIRECTLY by stage work repositories (DD-consistent "stage artifact writer" but no application command layer; executor is de facto command); source/work rows written by the ROUTER (api layer), not `application`; membership writer ambiguous (app path writes, REST doesn't, nothing reads). USER_OVERRIDE authority precedence: poison.py:96-108 + reducer (docs/consistency.md:104).

## Critical Invariants
- Ledger rows are immutable (DB trigger) — never UPDATE/DELETE `semantic_event`.
- `source.ocfl_ref` and `source.sha512` are UNIQUE (tables.py:134,136) — dedup logic must handle concurrency.
- Projections are never authoritative; Tier-0 `current_state` commits in the append transaction.
- Ingestion must never silently lose a SourceIngested event — the ledger append is the completion signal.

## Sources
- src/umd/application/ingestion.py, src/umd/api/routers/sources.py, src/umd/api/entrypoints.py, src/umd/api/app.py, src/umd/api/routers/system.py
- src/umd/storage/ocfl/store.py, src/umd/storage/postgres/{repositories.py,ledger.py,tables.py}, src/umd/jobs/{stage_execution.py,production.py,runner.py,hatchet.py}, src/umd/application/jobs.py, src/umd/deploy/{cli.py,startup.py}
- deploy/compose.yaml, deploy/docker-entrypoint.sh, migrations/0001_initial_core.py
- artifacts/designs/pending/DD-universal-media-decomposer.md (45, 50, 111-123), docs/consistency.md
