"""Metric record helpers for the DD observability list (P1-S1).

One call site per required metric so the surfaces (:mod:`umd.api.consistency`,
:mod:`umd.projections.base`, :mod:`umd.projections.vector`, sandbox/logging and
the report builder) record observability without duplicating name/label
knowledge. All metrics land in the process-wide :data:`METRICS` registry and are
emitted by the ``/v1/metrics`` boundary.

DD list -> registry mapping:

* queue depth                  -> gauge ``queue.depth``
* stage duration               -> histogram ``stage.duration_seconds``
* retries / failures           -> counters ``stage.retries`` / ``stage.failures``
* model calls/tokens/cost      -> counter ``model.calls`` (+ histogram tokens/cost)
* parser exit classes          -> counter ``parser.exit`` (label ``exit_class``)
* cache hits                   -> counter ``cache.hits`` / ``cache.misses``
* projection lag/checkpoints   -> gauge ``projection.lag`` + counter ``projection.checkpoint``
* stale / 503 responses        -> counters ``http.stale`` / ``http.503``
* HNSW maintenance             -> counter ``vector.hnsw.maintenance``
* sandbox denials              -> counter ``sandbox.denials``
"""

from __future__ import annotations

from umd.observability.metrics import METRICS, Gauge, Histogram


def set_queue_depth(depth: float) -> None:
    """Record the scheduler queue depth (gauge)."""
    METRICS.gauge("queue.depth", description="Scheduler queue depth.").set(depth)


def observe_stage_duration(stage: str, seconds: float) -> None:
    """Record one stage's wall duration (histogram, labelled by stage)."""
    METRICS.histogram(
        "stage.duration_seconds", description="Stage wall-clock duration.", labels={"stage": stage}
    ).observe(seconds)


def record_stage_retry(stage: str, _attempt: int) -> None:
    METRICS.counter(
        "stage.retries", description="Transient stage retries.", labels={"stage": stage}
    ).inc()


def record_stage_failure(stage: str, kind: str) -> None:
    METRICS.counter(
        "stage.failures", description="Stage failures.", labels={"stage": stage, "kind": kind}
    ).inc()


def record_model_call(model: str) -> None:
    METRICS.counter("model.calls", description="Model invocations.", labels={"model": model}).inc()


def record_model_tokens(model: str, input_tokens: int, output_tokens: int) -> None:
    METRICS.histogram(
        "model.tokens", description="Model token usage.", labels={"model": model}
    ).observe(float(input_tokens + output_tokens))


def record_model_cost(model: str, cost: float) -> None:
    METRICS.histogram(
        "model.cost", description="Model call cost.", labels={"model": model}
    ).observe(cost)


def record_parser_exit(exit_class: str) -> None:
    METRICS.counter(
        "parser.exit", description="Parser exit classes.", labels={"exit_class": exit_class}
    ).inc()


def record_cache_hit() -> None:
    METRICS.counter("cache.hits", description="Cache hits.").inc()


def record_cache_miss() -> None:
    METRICS.counter("cache.misses", description="Cache misses.").inc()


def set_projection_lag(projection: str, lag: int) -> None:
    METRICS.gauge(
        "projection.lag",
        description="Projection lag behind the ledger.",
        labels={"projection": projection},
    ).set(float(lag))


def record_projection_checkpoint(projection: str, _applied_seq: int) -> None:
    METRICS.counter(
        "projection.checkpoint",
        description="Projection checkpoints written.",
        labels={"projection": projection},
    ).inc()


def record_projection_pause(projection: str) -> None:
    METRICS.counter(
        "projection.pause",
        description="Authority-poison projection pauses.",
        labels={"projection": projection},
    ).inc()


def record_stale_response(projection: str) -> None:
    METRICS.counter(
        "http.stale",
        description="Stale (post-correction) reads refused.",
        labels={"projection": projection},
    ).inc()


def record_503(origin: str) -> None:
    METRICS.counter(
        "http.503", description="Read-your-writes 503 responses.", labels={"origin": origin}
    ).inc()


def record_hnsw_maintenance(action: str) -> None:
    METRICS.counter(
        "vector.hnsw.maintenance",
        description="HNSW maintenance operations.",
        labels={"action": action},
    ).inc()


def record_sandbox_denial(reason: str) -> None:
    METRICS.counter(
        "sandbox.denials", description="Sandbox policy denials.", labels={"reason": reason}
    ).inc()


def projection_lag_gauge(projection: str) -> Gauge:
    return METRICS.gauge(
        "projection.lag",
        description="Projection lag behind the ledger.",
        labels={"projection": projection},
    )


def stage_duration_histogram() -> Histogram:
    return METRICS.histogram("stage.duration_seconds", description="Stage wall-clock duration.")


__all__ = [
    "set_queue_depth",
    "observe_stage_duration",
    "record_stage_retry",
    "record_stage_failure",
    "record_model_call",
    "record_model_tokens",
    "record_model_cost",
    "record_parser_exit",
    "record_cache_hit",
    "record_cache_miss",
    "set_projection_lag",
    "record_projection_checkpoint",
    "record_projection_pause",
    "record_stale_response",
    "record_503",
    "record_hnsw_maintenance",
    "record_sandbox_denial",
    "projection_lag_gauge",
    "stage_duration_histogram",
]
