# Operational Runbooks

Expanded from the Phase-1 catalog of eight operational cards
(`src/umd/operations/runbooks.py`). Each card states its **trigger**, the
**service path** it maps to, and its **steps**. Runbooks are the human/ops
counterpart to the deterministic automation; executing them never weakens an
authority, provider, or security gate.

## cancel-job

- **Trigger:** an in-flight long-running job must be stopped.
- **Service:** `JobService.cancel(job_id, stage=None, reason)` → `POST
  /v1/jobs/{job_id}/cancel`.
- **Steps:** (1) identify the job id; (2) cancel; (3) dependent stages are
  recorded as cancelled (`cancelled_stages`); (4) re-run via retry if a partial
  result is salvageable. Cancellation is never a semantic mutation; the ledger
  is untouched.

## retry-failed-stage

- **Trigger:** a stage failed transiently (or after a bounded backoff) and the
  input/configuration is known good.
- **Service:** `JobService.retry(...)` → `POST /v1/jobs/{job_id}/retry`;
  also `POST /v1/sources/{id}/rerun` and `/v1/segments/{id}/rerun` for
  selective reruns.
- **Steps:** (1) confirm the failure is transient (not a deterministic
  malformed-input poison); (2) retry with a fresh work registry; (3) verify via
  `GET /v1/jobs/{job_id}` that previously-completed stages are not repeated;
  (4) if deterministic input failure, quarantine the segment and let independent
  branches continue.

## restart-resume

- **Trigger:** the service/process restarted mid-job.
- **Service:** `DurableStageExecutor.claim` + `SemanticLedger.complete_and_append`
  (effectively-once).
- **Steps:** the job resumes at the **last committed stage**; completed stages
  are not repeated (stage-run wins via the idempotency-key unique insert). No
  operator action needed beyond confirming `/v1/report` shows the expectation.
  Guarantee: stage completion is effectively-once under duplicate submissions.

## duplicate-stage-submission

- **Trigger:** a stage was submitted twice (retry, replay, or concurrent
  worker).
- **Service:** `StageRunRepository.claim` (`INSERT ... ON CONFLICT DO NOTHING`)
  + effective-once append.
- **Steps:** confirm the second submission short-circuited (no double-complete,
  no duplicate evidence). If artifacts were double-written, the content-addressed
  store deduplicates and a single winning row governs.

## projection-rebuild

- **Trigger:** a Tier-1 projection is behind, poisoned, or must be recreated
  after a schema/code change.
- **Service:** `ProjectionController.rebuild(builder, wipe=True)` via
  `ReplayDriver`; `ReindexCoordinator` caps concurrency and minimum interval.
- **Steps:** (1) wipe the projection; (2) replay from the ledger checkpoint to
  head; (3) honor the rebuild budget (`max_events`, `max_seconds`); (4) report
  the budget and completion. While rebuilding, tokened reads return the
  documented 503 `rebuild-in-progress` contract — never stale data. After
  rebuild, verify checksum-equivalent replay.

## poison-pause

- **Trigger:** the reducer hit an authority-relevant poison event.
- **Service:** `poison.classify` → `on_pause` + `paused()` + pause alerts.
- **Steps:** (1) the projection pauses, stays paused (never auto-applies the
  poison), and surfaces `pause_reason`; (2) triage the poison event and its
  causation; (3) if it is non-authoritative machine noise, quarantine/count it;
  (4) only a deliberate `force_resume`/rebuild resumes. Do not rebuild over an
  unresolved authoritative poison event — that is a release-blocking condition.

## queue-burst

- **Trigger:** ingestion/worker queue depth exceeds a healthy envelope.
- **Service:** concurrency cap + token-bucket limiting. (The `queue.depth`
  gauge is defined in the metric registry but no code path records it — treat
  it as not emitted; rely on the `429`+`Retry-After` backpressure signals.)
- **Steps:** (1) confirm rate limiting is rejecting with `429`+`Retry-After`
  (expected backpressure); (2) confirm concurrency caps are applying; (3) if a
  projection is rebuilding, honor `Retry-After` and avoid hammer reads; (4) if
  sustained, scale workers or backpressure producers instead of disabling the
  limiter.

## token-wait-backoff

- **Trigger:** a client token-bearing read gets a 503 while awaiting projection
  catch-up.
- **Service:** `ConsistencyGuard.ensure_read` + bounded `RetryPolicy`
  (no amplification, never stale).
- **Steps:** (1) read `x-consistency`; (2) `transient-lag` → back off with
  `Retry-After` and retry (projection is catching up); (3) `rebuild-in-progress`
  → honor the long `Retry-After` and poll rebuild/job status instead of
  hammering reads; (4) never retry in a tight loop — the guard is bounded and
  the policy never re-executes committed stages.