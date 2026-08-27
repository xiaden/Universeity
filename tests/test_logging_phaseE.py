"""Plan E (P1-S2): unit tests for the structured JSON logging surface (issue #6).

Covers ``StructuredLogger``, ``JsonLogFormatter``, ``CorrelationContext`` and
``log_parser_exit`` from :mod:`umd.observability.logging`:

* the JSON record shape (ts / level / logger / message, plus context + fields);
* correlation-id propagation through ``bind`` / ``clear`` and thread-safe context;
* the parser-exit record (info for ``ok``, warning otherwise) and its metric
  side-effects (``parser.exit`` + ``sandbox.denials``).

These run everywhere (no Postgres required).
"""

from __future__ import annotations

import io
import json
import uuid

from umd.observability.logging import (
    CorrelationContext,
    JsonLogFormatter,
    StructuredLogger,
    log_parser_exit,
)
from umd.observability.metrics import MetricRegistry


def _logger(stream: io.StringIO) -> StructuredLogger:
    # Unique name per call so each test binds a fresh handler to its own stream
    # (the stdlib logger keeps the first-attached handler otherwise).
    return StructuredLogger(name=f"umd.test-log.{uuid.uuid4().hex[:8]}", stream=stream)


def _emit(stream: io.StringIO) -> dict:
    """Return the most recent JSON record written to ``stream``."""
    lines = [ln for ln in stream.getvalue().strip().splitlines() if ln.strip()]
    return json.loads(lines[-1])


# ---------------------------------------------------------------------------
# Corollary: import-level symbols are exported
# ---------------------------------------------------------------------------


def test_correlation_context_to_map() -> None:
    ctx = CorrelationContext(correlation_id="c1", job_id="j1", source_id="s1", stage_id="st1")
    assert ctx.to_map() == {
        "correlation_id": "c1",
        "job_id": "j1",
        "source_id": "s1",
        "stage_id": "st1",
    }
    # Empty optional fields are omitted; extra fields are merged in.
    ctx2 = CorrelationContext(correlation_id="c2", extra={"k": "v"})
    assert ctx2.to_map() == {"correlation_id": "c2", "k": "v"}


# ---------------------------------------------------------------------------
# StructuredLogger JSON shape + correlation propagation
# ---------------------------------------------------------------------------


def test_structured_logger_json_shape() -> None:
    stream = io.StringIO()
    log = _logger(stream)
    log.info("hello", k="v")
    rec = _emit(stream)
    assert set(rec) == {"ts", "level", "logger", "message", "fields"}
    assert rec["level"] == "INFO"
    assert rec["logger"].startswith("umd.test-log")
    assert rec["message"] == "hello"
    assert rec["fields"] == {"k": "v"}
    log.clear()


def test_correlation_id_propagation() -> None:
    stream = io.StringIO()
    log = _logger(stream)
    log.bind(CorrelationContext(correlation_id="trace-42", job_id="job-9"))
    log.info("span started")
    rec = _emit(stream)
    assert rec["context"] == {"correlation_id": "trace-42", "job_id": "job-9"}
    # clear() drops the context for subsequent records.
    log.clear()
    log.info("after clear")
    rec2 = _emit(stream)
    assert "context" not in rec2


def test_context_fields_preserved_and_merged() -> None:
    stream = io.StringIO()
    log = _logger(stream)
    log.bind(stage_id="extract")
    log.info("stage work")
    rec = _emit(stream)
    assert rec["context"] == {"stage_id": "extract"}
    log.clear()


# ---------------------------------------------------------------------------
# log_parser_exit: record + metrics
# ---------------------------------------------------------------------------


def test_log_parser_exit_ok_record_and_metric() -> None:
    # Redirect the records module's registry so the real record_parser_exit /
    # record_sandbox_denial helpers feed a fresh registry (no cross-test leak).
    import umd.observability.records as records

    old_metrics = records.METRICS
    reg = MetricRegistry()
    records.METRICS = reg
    try:
        stream = io.StringIO()
        log = _logger(stream)
        log_parser_exit(log, workload="wrk", exit_code=0, exit_class="ok")
    finally:
        records.METRICS = old_metrics

    rec = _emit(stream)
    assert rec["level"] == "INFO"
    assert rec["message"] == "parser-exit"
    assert rec["fields"]["exit_class"] == "ok"
    assert rec["fields"]["exit_code"] == 0
    assert rec["fields"]["policy_denied"] is False
    assert reg.snapshot()["parser.exit"][0]["value"] == 1
    assert "sandbox.denials" not in reg.snapshot()


def test_log_parser_exit_non_ok_warning_and_denial_metric() -> None:
    import umd.observability.records as records

    old_metrics = records.METRICS
    reg = MetricRegistry()
    records.METRICS = reg
    try:
        stream = io.StringIO()
        log = _logger(stream)
        log_parser_exit(
            log,
            workload="wrk",
            exit_code=124,
            exit_class="TIMEOUT",
            timed_out=True,
            policy_denied=True,
            denial_reason="cmd:not-allowed",
        )
    finally:
        records.METRICS = old_metrics

    rec = _emit(stream)
    assert rec["level"] == "WARNING"
    assert rec["fields"]["exit_class"] == "TIMEOUT"
    assert rec["fields"]["timed_out"] is True
    assert rec["fields"]["denial_reason"] == "cmd:not-allowed"
    snap = reg.snapshot()
    assert snap["parser.exit"][0]["value"] == 1
    assert snap["sandbox.denials"][0]["value"] == 1


def test_log_parser_exit_calls_real_records() -> None:
    """log_parser_exit drives the real record_parser_exit / record_sandbox_denial
    into the records module's registry (redirected for isolation)."""
    import umd.observability.records as records

    old_metrics = records.METRICS
    reg = MetricRegistry()
    records.METRICS = reg
    try:
        stream = io.StringIO()
        log = _logger(stream)
        log_parser_exit(log, workload="w", exit_code=1, exit_class="ERROR")
        assert reg.snapshot()["parser.exit"][0]["value"] == 1
    finally:
        records.METRICS = old_metrics


def test_json_formatter_renders_exc_info() -> None:
    import logging

    formatter = JsonLogFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord("n", logging.ERROR, "", 0, "msg", (), sys_exc_info())
    text = formatter.format(record)
    payload = json.loads(text)
    assert "exc" in payload
    assert "ValueError" in payload["exc"]


def sys_exc_info():
    import sys

    return sys.exc_info()
