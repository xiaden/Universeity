"""Structured JSON logging with correlation/job/source/stage context (P1-S2).

The DD observability contract (Task §33, DD Security and observability) requires
structured JSON logs carrying correlation/job/source/stage IDs so a source
decomposition report can explain why a stage was slow, failed, or quarantined.

This module provides a :class:`StructuredLogger` that emits newline-delimited
JSON records with a stable schema. It is a thin stdlib ``logging`` wrapper, so it
composes with existing handlers and needs no new dependency. Context fields are
thread-safe (``contextvars``) so per-correlation state does not leak between jobs.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any

from umd.observability.records import record_parser_exit, record_sandbox_denial

#: Per-correlation context carried on every emitted record. No mutable default
#: (B039 compliance): reads supply a fresh dict via ``.get({})``; writes always
#: replace with a copy.
_current: contextvars.ContextVar[dict[str, str]] = contextvars.ContextVar("umd_log_ctx")


@dataclass
class CorrelationContext:
    """Mutable context bound to a correlation for the duration of a scope."""

    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    job_id: str | None = None
    source_id: str | None = None
    stage_id: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    def to_map(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if self.job_id:
            out["job_id"] = self.job_id
        if self.source_id:
            out["source_id"] = self.source_id
        if self.stage_id:
            out["stage_id"] = self.stage_id
        if self.correlation_id:
            out["correlation_id"] = self.correlation_id
        out.update(self.extra)
        return out


class JsonLogFormatter(logging.Formatter):
    """Render a ``logging.LogRecord`` as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": record.created,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        ctx = _current.get({})
        if ctx:
            payload["context"] = ctx
        extra = getattr(record, "umd_fields", None)
        if extra:
            payload["fields"] = extra
        return json.dumps(payload, sort_keys=True, default=str)


class StructuredLogger:
    """A correlation-aware logger that emits JSON records to a target stream.

    ``bind_context`` / ``scope`` attach correlation/job/source/stage IDs to the
    current context; every log call carries them automatically.
    """

    def __init__(self, name: str = "umd", stream: Any | None = None) -> None:
        self._logger = logging.getLogger(name)
        self._logger.setLevel(logging.INFO)
        if not self._logger.handlers:
            handler = logging.StreamHandler(stream or sys.stderr)
            handler.setFormatter(JsonLogFormatter())
            self._logger.addHandler(handler)
            self._logger.propagate = False

    # -- context management -------------------------------------------------

    def bind(self, ctx: CorrelationContext | None = None, **fields: str) -> None:
        """Attach correlation fields to the current context (thread-local)."""
        if ctx is not None:
            _current.set(ctx.to_map())
        elif fields:
            merged = dict(_current.get({}))
            merged.update(fields)
            _current.set(merged)

    def clear(self) -> None:
        _current.set({})

    # -- emission -----------------------------------------------------------

    def _emit(self, level: int, msg: str, **fields: Any) -> None:
        rec = logging.LogRecord(self._logger.name, level, "", 0, msg, (), None)
        if fields:
            rec.umd_fields = fields
        self._logger.handle(rec)

    def info(self, msg: str, **fields: Any) -> None:
        self._emit(logging.INFO, msg, **fields)

    def warning(self, msg: str, **fields: Any) -> None:
        self._emit(logging.WARNING, msg, **fields)

    def error(self, msg: str, **fields: Any) -> None:
        self._emit(logging.ERROR, msg, **fields)


_default = StructuredLogger()


def get_logger(name: str = "umd") -> StructuredLogger:
    """Return the shared :class:`StructuredLogger` (or one bound to ``name``)."""
    if name == "umd":
        return _default
    return StructuredLogger(name)


def log_parser_exit(
    log: StructuredLogger,
    *,
    workload: str,
    exit_code: int,
    exit_class: str,
    timed_out: bool = False,
    policy_denied: bool = False,
    denial_reason: str | None = None,
) -> None:
    """Record a structured parser-exit event for metrics/correlation reporting."""
    fields: dict[str, Any] = {
        "workload": workload,
        "exit_code": exit_code,
        "exit_class": exit_class,
        "timed_out": timed_out,
        "policy_denied": policy_denied,
    }
    if denial_reason:
        fields["denial_reason"] = denial_reason
    if exit_class != "ok":
        log.warning("parser-exit", **fields)
    else:
        log.info("parser-exit", **fields)
    # Observability metrics (P1-S1): parser exit classes + sandbox denials.
    record_parser_exit(exit_class)
    if policy_denied:
        record_sandbox_denial(denial_reason or "policy-denied")
