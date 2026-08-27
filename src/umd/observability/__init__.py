"""Observability: structured JSON logging, metrics, traces, reports.

Phase C (P1-S2) delivers the structured correlation/job/source/stage logger
(:mod:`umd.observability.logging`). Metrics/traces/decomposition-report surfaces
are wired in later phases but compose with the same correlation context.
"""

from umd.observability.logging import (
    CorrelationContext,
    JsonLogFormatter,
    StructuredLogger,
    get_logger,
    log_parser_exit,
)

__all__ = [
    "CorrelationContext",
    "JsonLogFormatter",
    "StructuredLogger",
    "get_logger",
    "log_parser_exit",
]
