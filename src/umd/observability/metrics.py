"""In-process metrics registry: counters / gauges / histograms (P1-S1).

The DD Security-and-observability contract requires metrics for queue depth,
stage duration, retries/failures, model calls/tokens/cost, parser exit classes,
cache hits, projection lag/checkpoints, stale/503 responses, HNSW maintenance,
and sandbox denials.

This module provides a small, thread-safe, label-enabled registry whose metrics
actually record and can be (a) snapshotted for a ``/v1/metrics`` boundary and
(b) emitted into the structured JSON logs alongside each correlation. No heavy
external metrics system is required: the registry is fully in-process and real.

External integrations (Prometheus text exposition / OTel exporter) are
*honest-gated* elsewhere: this registry never fabricates a live collector. It
only records in-process and exposes its snapshot — an honest, testable core.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal

MetricKind = Literal["counter", "gauge", "histogram"]

#: Immutable label key/value pair; ``frozenset`` order-independent dedup.
_Labels = frozenset[tuple[str, str]]


def _key(name: str, kind: MetricKind, labels: _Labels) -> tuple[str, MetricKind, _Labels]:
    return (name, kind, labels)


@dataclass
class _Metric:
    """Recorded state for one metric (name + kind + labels)."""

    name: str
    kind: MetricKind
    description: str
    labels: _Labels = field(default_factory=frozenset)
    created_ts: float = field(default_factory=time.time)
    # counter/gauge value; histogram uses the aggregate fields below.
    value: float = 0.0
    # histogram aggregates (mean derived from count+sum).
    count: int = 0
    sum_: float = 0.0
    min_: float | None = None
    max_: float | None = None


class Counter:
    """Handle to a labeled counter (``inc`` only)."""

    def __init__(self, registry: MetricRegistry, name: str, labels: _Labels) -> None:
        self._registry = registry
        self._name = name
        self._labels = labels

    @property
    def name(self) -> str:
        return self._name

    def inc(self, amount: float = 1.0) -> float:
        """Increment the counter by ``amount``; returns the new value."""
        return self._registry._inc(self._name, self._labels, amount)


class Gauge:
    """Handle to a labeled gauge (``set``/``inc``/``dec``)."""

    def __init__(self, registry: MetricRegistry, name: str, labels: _Labels) -> None:
        self._registry = registry
        self._name = name
        self._labels = labels

    @property
    def name(self) -> str:
        return self._name

    def set(self, value: float) -> float:
        return self._registry._set(self._name, self._labels, value)

    def inc(self, amount: float = 1.0) -> float:
        return self._registry._set(
            self._name, self._labels, self._registry._value(self._name, self._labels) + amount
        )

    def dec(self, amount: float = 1.0) -> float:
        return self._registry._set(
            self._name, self._labels, self._registry._value(self._name, self._labels) - amount
        )


class Histogram:
    """Handle to a labeled histogram (``observe`` records count/sum/min/max)."""

    def __init__(self, registry: MetricRegistry, name: str, labels: _Labels) -> None:
        self._registry = registry
        self._name = name
        self._labels = labels

    @property
    def name(self) -> str:
        return self._name

    def observe(self, value: float) -> None:
        self._registry._observe(self._name, self._labels, value)


class MetricRegistry:
    """Thread-safe, label-enabled metric registry.

    Callers obtain typed handles via :meth:`counter` / :meth:`gauge` /
    :meth:`histogram`. Handles are cheap and may be re-acquired; a handle for the
    same ``(name, kind, labels)`` shares the same recorded state.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._metrics: dict[tuple[str, MetricKind, _Labels], _Metric] = {}

    # -- handle factories --------------------------------------------------

    def counter(
        self,
        name: str,
        *,
        description: str = "",
        labels: dict[str, str] | None = None,
    ) -> Counter:
        self._ensure("counter", name, description, labels)
        return Counter(self, name, _freeze(labels))

    def gauge(
        self,
        name: str,
        *,
        description: str = "",
        labels: dict[str, str] | None = None,
    ) -> Gauge:
        self._ensure("gauge", name, description, labels)
        return Gauge(self, name, _freeze(labels))

    def histogram(
        self,
        name: str,
        *,
        description: str = "",
        labels: dict[str, str] | None = None,
    ) -> Histogram:
        self._ensure("histogram", name, description, labels)
        return Histogram(self, name, _freeze(labels))

    # -- mutation (used by handles) ---------------------------------------

    def _ensure(
        self, kind: MetricKind, name: str, description: str, labels: dict[str, str] | None
    ) -> None:
        key = _key(name, kind, _freeze(labels))
        with self._lock:
            if key not in self._metrics:
                self._metrics[key] = _Metric(
                    name=name, kind=kind, description=description, labels=_freeze(labels)
                )

    def _inc(self, name: str, labels: _Labels, amount: float) -> float:
        key = _key(name, "counter", labels)
        with self._lock:
            m = self._metrics.setdefault(
                key, _Metric(name=name, kind="counter", description="", labels=labels)
            )
            m.value += amount
            return m.value

    def _set(self, name: str, labels: _Labels, value: float) -> float:
        key = _key(name, "gauge", labels)
        with self._lock:
            m = self._metrics.setdefault(
                key, _Metric(name=name, kind="gauge", description="", labels=labels)
            )
            m.value = value
            return m.value

    def _value(self, name: str, labels: _Labels) -> float:
        key = _key(name, "gauge", labels)
        with self._lock:
            m = self._metrics.get(key)
            return m.value if m is not None else 0.0

    def _observe(self, name: str, labels: _Labels, value: float) -> None:
        key = _key(name, "histogram", labels)
        with self._lock:
            m = self._metrics.setdefault(
                key, _Metric(name=name, kind="histogram", description="", labels=labels)
            )
            m.count += 1
            m.sum_ += value
            if m.min_ is None or value < m.min_:
                m.min_ = value
            if m.max_ is None or value > m.max_:
                m.max_ = value

    # -- read / export -----------------------------------------------------

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        """Return a JSON-serialisable snapshot grouped by metric name.

        A single name may appear multiple times (once per distinct label set);
        each entry carries its kind, description, labels and record fields.
        """
        out: dict[str, list[dict[str, Any]]] = {}
        with self._lock:
            metrics = list(self._metrics.values())
        for m in metrics:
            entry: dict[str, Any] = {
                "name": m.name,
                "kind": m.kind,
                "description": m.description,
                "labels": dict(sorted(m.labels)),
            }
            if m.kind == "histogram":
                entry["count"] = m.count
                entry["sum"] = m.sum_
                entry["min"] = m.min_
                entry["max"] = m.max_
                entry["mean"] = (m.sum_ / m.count) if m.count else None
            else:
                entry["value"] = m.value
            out.setdefault(m.name, []).append(entry)
        return out

    def has(self, name: str, *, kind: MetricKind | None = None) -> bool:
        with self._lock:
            return any(k[0] == name and (kind is None or k[1] == kind) for k in self._metrics)

    def reset(self) -> None:
        """Clear all recorded metrics (used by tests / namespace teardown)."""
        with self._lock:
            self._metrics.clear()


def _freeze(labels: dict[str, str] | None) -> _Labels:
    return frozenset(sorted(labels.items()) if labels else [])


#: The process-wide default registry (wired into the API / surfaces by default).
METRICS = MetricRegistry()


__all__ = [
    "MetricRegistry",
    "Counter",
    "Gauge",
    "Histogram",
    "METRICS",
]
