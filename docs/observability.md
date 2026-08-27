# Observability

## Structured logs

- `umd.observability.logging` emits structured JSON logs via a single app logger
  (`x-request-id` / `x-correlation-id`) so a request can be traced across api,
  worker, and sandbox-runner. Log level is configurable
  (`UMD_LOG_LEVEL`); logs never embed secrets, model weights paths, or raw
  content.

## Metrics

- `umd.observability.metrics` maintains an in-process metric registry
  (`METRICS.snapshot()`) exposed at `GET /v1/metrics`. Metrics recorded from
  within the service include:
  - `stage.*` — `stage.duration_seconds` (histogram), `stage.retries` and
    `stage.failures` (counters), recorded as they occur while building
    per-source reports and by the projection replay driver
  - `projection.lag` (gauge) and `projection.checkpoint` / `projection.pause`
    (counters) — freshness, checkpoints written, and authority-poison pauses
  - `http.stale` and `http.503` (counters) — post-correction stale reads refused
    and read-your-writes 503 responses
  - `parser.exit` (counter, labelled by `exit_class`) and `sandbox.denials`
    (counter, labelled by `reason`)
  - `vector.hnsw.maintenance` (counter, labelled by `action`) — HNSW gate probes

  The registry also defines record helpers for `queue.depth`, `model.calls` /
  `model.tokens` / `model.cost`, and `cache.hits` / `cache.misses`, but **no
  current code path records them** — they remain definition-only and are never
  emitted by `/v1/metrics` unless a future caller invokes them. Rebuild progress
  and rate-limit denials are likewise not exposed as metrics: the former is
  surfaced via the `/v1/ready` 503/`Retry-After` contract and the latter via the
  rate-limit `429` response, not the registry.
- OpenTelemetry export is **gated**: `otel_export_active:false` unless
  `UMD_OTEL_ENABLED` plus `opentelemetry-sdk` are present (the API reports the
  exact gate condition in `/v1/metrics`).

## Traces / spans

- `umd.observability.tracing` provides optional span context for stage and
  request boundaries. Spans remain cheap and are correlated via the shared
  request/correlation id.

## Health and readiness

- **`GET /v1/health`** returns `200 ok`/`degraded` with per-projection
  components (`projection:{name}`). A projection that is not fresh reports
  `degraded` with its `freshness.to_meta()` detail — so the service stays
  allocatable while a projection lags, without ever serving stale tokened reads.
- **`GET /v1/ready`** returns `200 {status: ready}` only when no projection is
  rebuilding; a rebuild-in-progress yields `503` with `x-consistency:
  rebuild-in-progress` and `Retry-After` so orchestrators do not place work
  against a paused projection.

## Per-source decomposition reports

`GET /v1/sources/{source_id}/report` (via the read-only
`SourceReportBuilder`) explains a source's decomposition outcome from the
operational tables — never Tier-0:

- per-`stage_run` status, attempts/retries/starts/completes/failures, timing
- `job_run_audit` retry/cancel history and artifact counts
- `configuration digest`, extractor/decoder/model versions, evidence references
- incomplete branches (stages cancelled/missing, jobs non-terminal)
- quarantine records under the source, rerun/invalidation causation.

The builder is read-only and emits the same stage-duration/retry/failure metrics
to `/v1/metrics` as it builds — so reports and the metric registry share one
source of truth.

## Operational runbook telemetry

The runbooks in [runbooks.md](runbooks.md) rely on the same instrumentation:
queue depth and concurrency caps, projection rebuild budget tracking, token-wait
backoff counting, and poison-pause alerts.