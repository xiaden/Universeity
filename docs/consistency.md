# Consistency, Read-Your-Writes Tokens, DAG/Invalidation, and Overrides

## Read-your-writes consistency

Every accepted semantic mutation returns a **read-your-writes token** (the
ledger `seq`). Tier-1 reads (`POST /v1/query/structured`,
`POST /v1/query/semantic`, `POST /v1/search`) accept an opaque
`consistency_token` in the request body.

**Tokened reads** wait behind a bounded semaphore for the projection to catch up
to the token, bounded by `lag_budget_seconds * lag_wait_multiplier` (default
cap `<=1s` budget, up to ~2x). Three outcomes:

| Outcome | HTTP | Headers | Meaning |
|---|---|---|---|
| Caught up | `200` | — | projection applied `seq >= token`; the read is fresh |
| Not caught up (projection behind, not paused) | `503` | `Retry-After`, `x-consistency: transient-lag` | transient lag; retry with backoff |
| Projection paused (authority rebuild in progress) | `503` | `Retry-After >= 30s`, `x-consistency: rebuild-in-progress`, `x-rebuild-estimate` | never serve (possibly stale) pre-rebuild state |

The guard **never returns stale post-correction answers** — if it cannot reach
the token within the budget it fails with the 503 contract instead of serving
old data.

`GET /v1/ready` surfaces the same rebuild state as a deterministic 503 RFC 7807
error with `code=not_ready`, `retryable=true`, and
`x-consistency: rebuild-in-progress`.

**Untokened reads** are served immediately but the response embeds `freshness`
metadata (`applied_seq`, `ledger_tail`, `lag`, `status`, `paused`,
`pause_reason`).

### Client backoff guidance

Token-bearing query clients must implement exponential backoff with full jitter
for 503s, using `Retry-After` and distinguishing `transient-lag` from
`rebuild-in-progress` via the `x-consistency` header. Retries never re-execute
committed stages — idempotency keeps retries safe (no amplification). A
`rebuild-in-progress` (long `Retry-After`) should direct clients to poll
job/rebuild status rather than hammer reads.

### Projection poison / pause

A projection may pause when it hits an authority-relevant poison event. Paused
projections surface `pause_reason` to token-bearing reads and to `/v1/health`
and `/v1/ready`. A paused projection stays paused until explicitly resumed —
it **never auto-applies poison**. Non-authoritative machine noise may be
quarantined and counted instead.

## Durable stage execution and the DAG

The v1 DAG is:

```text
INGEST -> FORMAT_ANALYSIS -> BASIC_SEGMENTATION -> LOW_LEVEL_EXTRACTION
  -> STRUCTURAL_ANALYSIS -> ENTITY_RESOLUTION -> CROSS_SOURCE_ALIGNMENT
  -> SEMANTIC_RECONCILIATION -> CURRENT/SEARCH PROJECTION
```

Independent branches fan out by segment and modality. `HallucinationFiltered`
is its own versioned dependency edge: changing thresholds selectively
reclassifies ASR-derived outputs.

- The **in-repository DAG definition is the single lineage source** and
  generates `stage_dependency(stage, depends_on_stage, evidence_class)`.
  Hatchet is the sole v1 runner for the explicit DAG, and only for durable
  deployment; in-process execution (the API job facade) is deterministic and
  pollable for local use.
- Each stage run has a deterministic idempotency key derived from
  source/segment, stage, input evidence refs, stage schema,
  extractor/decoder/provider versions, and configuration digest.
- Winning `stage_run` insertion (`UNIQUE(idempotency_key)`), artifact
  references, and `StageCompleted` append happen in **one PostgreSQL
  transaction**; a crash cannot commit completion without evidence.
- `job_run_audit` records start/retry/fail/complete/cancel independently of
  semantic replay.
- Transient failures retry with bounded backoff; deterministic malformed-input
  failures quarantine and permit independent branches; authority projection
  failures pause and alert.
- Stage completion is effectively-once under duplicate submissions.

## Invalidation and selective rerun

`Invalidated` records identify causation, scope, stage, and affected refs. The
pure `InvalidationPlanner` (`InvalidationPlanner.plan(...)`) is
**descendant-only** — it traverses only descendants in the lineage graph, so:

- Re-running speaker resolution does not re-run OCR/ASR/segmentation.
- A filter-version bump reclassifies ASR descendants.
- A correction schedules only affected resolution/presence/alignment/reconcilia
  tion/projection assets.
- Unaffected extraction/evidence is retained.

REST: `POST /v1/sources/{id}/rerun` (selective rerun of a whole source),
`POST /v1/segments/{id}/rerun` (a single segment/stage), and
`POST /v1/claims/{ref}/invalidate`.

## Overrides, edits, and locks

- `OverrideApplied` / `CorrectionApplied` append events via the command path and
  return read-your-writes tokens; they never write a projection directly.
- `Locked` / `Unlocked` gate winner selection in the reducer.
- `POST /v1/segments/{id}/edit`, `/split`, `/merge` record boundary/edit events
  and schedule dependent work.
- The reducer applies `USER_OVERRIDE` precedence per authority/lock rules.
- All edits are structurally append-only and reversible; history is retained so
  audit can explain current, prior, actor, evidence, generated-by, and change
  cause.