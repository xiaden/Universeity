"""Phase E / P1-S1–P1-S4: unit tests for the observability surface (no DB).

Covers the in-process metrics registry, the metric-record helpers mapping the DD
list, the tracer (honest OTel gate), the rebuild config, and the operational
runbook catalog. These run everywhere (no Postgres); the postgres operational
tests live in test_operational_phaseE.py.
"""

from __future__ import annotations

from umd.observability.metrics import METRICS, MetricRegistry
from umd.observability.records import (
    observe_stage_duration,
    record_503,
    record_cache_hit,
    record_parser_exit,
    record_projection_pause,
    record_sandbox_denial,
    set_projection_lag,
    set_queue_depth,
)
from umd.observability.tracing import Tracer
from umd.operations.runbooks import CATALOG

# ---------------------------------------------------------------------------
# metrics registry
# ---------------------------------------------------------------------------


def test_counter_gauge_histogram_aggregation() -> None:
    reg = MetricRegistry()
    counter = reg.counter("c", description="calls", labels={"kind": "x"})
    counter.inc()
    counter.inc(2)
    gauge = reg.gauge("g")
    gauge.set(5)
    hist = reg.histogram("h")
    hist.observe(1.0)
    hist.observe(3.0)

    snap = reg.snapshot()
    (c,) = snap["c"]
    assert c["value"] == 3.0
    assert c["labels"] == {"kind": "x"}
    (g,) = snap["g"]
    assert g["value"] == 5.0
    (h,) = snap["h"]
    assert h["count"] == 2 and h["sum"] == 4.0
    assert h["min"] == 1.0 and h["max"] == 3.0 and h["mean"] == 2.0


def test_labels_dedup_share_state() -> None:
    reg = MetricRegistry()
    reg.counter("n", labels={"k": "v"}).inc()
    reg.counter("n", labels={"k": "v"}).inc()
    (entry,) = reg.snapshot()["n"]
    assert entry["value"] == 2.0


def test_snapshot_serializable_kinds() -> None:
    reg = MetricRegistry()
    reg.gauge("a").set(1)
    reg.counter("a", labels={"stage": "s1"}).inc()
    snap = reg.snapshot()
    assert sorted(snap.keys()) == ["a"]
    assert {e["kind"] for e in snap["a"]} == {"counter", "gauge"}


def test_registry_reset() -> None:
    reg = MetricRegistry()
    reg.counter("x").inc()
    assert reg.has("x", kind="counter")
    reg.reset()
    assert not reg.has("x")


# ---------------------------------------------------------------------------
# metric-record helpers map the DD observability list into the registry
# ---------------------------------------------------------------------------


def test_records_map_dd_metrics_to_registry() -> None:
    import umd.observability.records as records

    reg = MetricRegistry()
    records.METRICS = reg  # redirect the helper module's registry for this test

    set_queue_depth(3)
    record_503(origin="transient-lag")
    record_503(origin="rebuild-in-progress")
    record_cache_hit()
    record_parser_exit("ok")
    record_parser_exit("TIMEOUT")
    record_sandbox_denial("cmd:not-allowed")
    set_projection_lag("current_tier1", 2)
    record_projection_pause("current_tier1")
    observe_stage_duration("CURRENT_STATE", 0.25)

    snap = reg.snapshot()
    assert snap["queue.depth"][0]["value"] == 3
    assert sum(e["value"] for e in snap["http.503"]) == 2
    assert snap["cache.hits"][0]["value"] == 1
    assert {e["labels"]["exit_class"] for e in snap["parser.exit"]} == {"ok", "TIMEOUT"}
    assert snap["sandbox.denials"][0]["value"] == 1
    assert snap["projection.lag"][0]["value"] == 2
    assert snap["projection.pause"][0]["value"] == 1
    assert snap["stage.duration_seconds"][0]["count"] == 1
    # restore the process-wide registry so other tests are unaffected
    records.METRICS = METRICS


def test_default_registry_is_process_one() -> None:
    import umd.observability.metrics as m

    assert METRICS is m.METRICS


def test_records_checkpoint_hnsw_and_503_wiring() -> None:
    """Issue #7: projection.checkpoint + vector.hnsw.maintenance + a real 503 all
    record into the registry through the production record helpers."""
    import umd.observability.records as records

    reg = MetricRegistry()
    records.METRICS = reg  # redirect (restored below)
    try:
        records.record_projection_checkpoint("current_tier1", 42)
        records.record_hnsw_maintenance("probe-gated")
        records.record_503(origin="transient-lag")
        records.set_projection_lag("search", 7)

        snap = reg.snapshot()
        assert snap["projection.checkpoint"][0]["value"] == 1
        assert snap["projection.checkpoint"][0]["labels"] == {"projection": "current_tier1"}
        assert snap["vector.hnsw.maintenance"][0]["value"] == 1
        assert snap["vector.hnsw.maintenance"][0]["labels"] == {"action": "probe-gated"}
        assert snap["http.503"][0]["value"] == 1
        assert snap["projection.lag"][0]["value"] == 7
    finally:
        records.METRICS = METRICS


# ---------------------------------------------------------------------------
# tracer: in-process spans with an honest OTel gate
# ---------------------------------------------------------------------------


def test_tracer_records_nested_spans(monkeypatch) -> None:
    monkeypatch.delenv("UMD_OTEL_ENABLED", raising=False)
    tracer = Tracer()
    assert tracer.export_active is False  # no collector dependency is fabricated
    assert tracer.capability()["traces"]["active"] is False

    with tracer.start_span("outer", job_id="j1"):
        with tracer.start_span("inner", stage="ingest"):
            inner_spans = tracer.in_flight()
            assert len(inner_spans) == 2
            inner_span = inner_spans[-1]
        assert inner_span is not None
    spans = tracer.spans()
    assert len(spans) == 2
    outer, inner = spans
    assert inner.parent_span_id == outer.span_id
    assert inner.attributes.get("stage") == "ingest"
    assert outer.duration_ms >= 0
    assert inner.trace_id == outer.trace_id


def test_tracer_spans_serializable() -> None:
    tracer = Tracer()
    with tracer.start_span("s", k="v"):
        pass
    d = tracer.spans()[-1].to_dict()
    assert set(d) == {
        "trace_id",
        "span_id",
        "parent_span_id",
        "name",
        "status",
        "duration_ms",
        "started",
        "attributes",
    }


# ---------------------------------------------------------------------------
# rebuild budget config
# ---------------------------------------------------------------------------


def test_rebuild_settings_defaults() -> None:
    from umd.config import Settings

    s = Settings()
    assert s.rebuild.max_events == 1_000_000
    assert s.rebuild.max_seconds == 3600.0
    assert s.rebuild.concurrent_rebuilds == 1
    assert s.rebuild.min_interval_seconds == 1.0


# ---------------------------------------------------------------------------
# runbook catalog (P1-S4)
# ---------------------------------------------------------------------------


def test_runbook_catalog_covers_operational_modes() -> None:
    expected = {
        "cancel-job",
        "retry-failed-stage",
        "restart-resume",
        "duplicate-stage-submission",
        "projection-rebuild",
        "poison-pause",
        "queue-burst",
        "token-wait-backoff",
    }
    assert set(CATALOG.ids()) == expected
    for card in CATALOG.list():
        assert card.title and card.service and card.steps
    assert CATALOG.get("token-wait-backoff").service.startswith("ConsistencyGuard")
