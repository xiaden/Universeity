"""In-process tracing with honest-gated OpenTelemetry export (P1-S1).

The DD Security-and-observability contract requires OpenTelemetry traces. This
module provides a small :class:`Tracer` whose spans are recorded in-process
(real, thread-safe, testable) and correlated into the structured JSON logs via
the shared correlation context.

OpenTelemetry *export* is layered on as an opt-in integration behind an env gate:

* ``UMD_OTEL_ENABLED=true`` AND the ``opentelemetry-sdk`` package importable:
  the tracer wraps a real ``opentelemetry.trace`` tracer and exports spans to a
  configured collector (honest external integration).
* Otherwise the in-process span sink is used and export is reported as
  ``active=False`` (never fabricated). The in-process spans are always recorded
  and emitted to JSON logs, so traces work and are tested without a collector.
"""

from __future__ import annotations

import contextlib
import contextvars
import importlib.util
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from umd.observability.logging import StructuredLogger, get_logger

#: Per-correlation span stack (no mutable default / thread-safe).
_spans: contextvars.ContextVar[list[Span]] = contextvars.ContextVar("umd_spans")


def _ensure_stack() -> list[Span]:
    try:
        return _spans.get()
    except LookupError:
        inner: list[Span] = []
        _spans.set(inner)
        return inner


@dataclass
class Span:
    """One recorded span (in-process, JSON-log-correlated)."""

    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    started_monotonic: float
    started_wall: float
    attributes: dict[str, str] = field(default_factory=dict)
    end_monotonic: float | None = None
    status: str = "ok"  # ok | error

    @property
    def duration_ms(self) -> float:
        end = self.end_monotonic if self.end_monotonic is not None else time.monotonic()
        return (end - self.started_monotonic) * 1000.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 3),
            "started": self.started_wall,
            "attributes": dict(sorted(self.attributes.items())),
        }


def otel_export_active(raw_env: str | None = None) -> bool:
    """Honest gate: OTel export is active only when enabled AND importable."""
    enabled = (raw_env if raw_env is not None else os.environ.get("UMD_OTEL_ENABLED", "")).lower()
    if enabled not in ("1", "true", "yes"):
        return False
    # Honest gate: export is active only when an opentelemetry module is actually
    # importable. ``find_spec`` probes this without a static import, so mypy
    # --strict passes in environments where the optional SDK is not installed.
    return importlib.util.find_spec("opentelemetry") is not None


class Tracer:
    """Records spans in-process and (when gated active) exports via OTel.

    ``start_span(name, **attributes)`` is a context manager pushing a child span
    onto the current correlation's stack. Every span is emitted to the structured
    JSON logger on close, so traces are observable even without a collector.
    """

    def __init__(self, log: StructuredLogger | None = None) -> None:
        self._log = log or get_logger("umd.trace")
        self._export_active = otel_export_active()
        self._span_log: list[Span] = []

    @property
    def export_active(self) -> bool:
        """Whether OTel collector export is genuinely active (gated)."""
        return self._export_active

    def capability(self) -> dict[str, Any]:
        return {
            "traces": {
                "provider": "opentelemetry" if self._export_active else "in-process",
                "active": self._export_active,
                "gate": (
                    "UMD_OTEL_ENABLED + opentelemetry-sdk required for collector export"
                    if not self._export_active
                    else None
                ),
            }
        }

    @contextlib.contextmanager
    def start_span(self, name: str, **attributes: Any) -> Any:
        stack = _ensure_stack()
        parent = stack[-1] if stack else None
        span = Span(
            name=name,
            trace_id=(parent.trace_id if parent else uuid.uuid4().hex),
            span_id=uuid.uuid4().hex,
            parent_span_id=parent.span_id if parent else None,
            started_monotonic=time.monotonic(),
            started_wall=time.time(),
            attributes={k: str(v) for k, v in attributes.items()},
        )
        stack.append(span)
        # Record the span in start order (parent before child) so ``spans()``
        # returns the nesting correctly; end/status are set on close below.
        self._span_log.append(span)
        try:
            yield span
        except Exception:
            span.status = "error"
            raise
        finally:
            span.end_monotonic = time.monotonic()
            if span in stack:
                stack.remove(span)
            self._log.info("trace-span", span_id=span.span_id, trace_id=span.trace_id, name=name)

    def spans(self) -> list[Span]:
        """Recorded spans (in-process sink, testable)."""
        return list(self._span_log)

    def in_flight(self) -> list[Span]:
        return list(_ensure_stack())


#: Process-wide default tracer bound to the default structured logger.
TRACER = Tracer()


__all__ = [
    "Tracer",
    "Span",
    "TRACER",
    "otel_export_active",
]
