"""Prometheus-style metrics registry for trading system.

Counterpart: app/infrastructure/metrics.py (business KPI dict for /api/v1/metrics).
Backed by ``prometheus_client`` (v0.26+). The public surface is identical to
the previous hand-rolled registry: the module exposes ``metrics`` (a
``MetricsRegistry`` singleton), the ``Metric``/``Counter``/``Histogram``/
``Gauge`` wrapper classes and the convenience metric objects, so existing
consumers do not need to change.
"""

from __future__ import annotations

import threading
from typing import Any

from prometheus_client import (
    CollectorRegistry,
    disable_created_metrics,
    generate_latest,
)
from prometheus_client import (
    Counter as _PromCounter,
)
from prometheus_client import (
    Gauge as _PromGauge,
)
from prometheus_client import (
    Histogram as _PromHistogram,
)

# Bucket boundaries matching the previous hand-rolled implementation.
# prometheus_client appends the +Inf bucket automatically.
_HISTOGRAM_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)

# Keep the exposition surface identical to the old registry (no _created series).
disable_created_metrics()

_FACTORIES = {"counter": _PromCounter, "gauge": _PromGauge, "histogram": _PromHistogram}


def _create_family(kind: str, name: str, help: str, labelnames: tuple[str, ...]) -> Any:
    kwargs: dict[str, Any] = {
        "name": name,
        "documentation": help,
        "registry": CollectorRegistry(),
    }
    if labelnames:
        kwargs["labelnames"] = list(labelnames)
    if kind == "histogram":
        kwargs["buckets"] = list(_HISTOGRAM_BUCKETS)
    return _FACTORIES[kind](**kwargs)


class Metric:
    """Base metric wrapper around a prometheus_client metric."""

    def __init__(self, name: str, help: str, labels: dict[str, str], child: Any) -> None:
        self.name = name
        self.help = help
        self.labels = dict(labels)
        self._child = child


class Counter(Metric):
    """Counter metric - only increases."""

    def inc(self, amount: float = 1.0) -> None:
        self._child.inc(amount)

    @property
    def value(self) -> float:
        for family in self._child.collect():
            for sample in family.samples:
                if not sample.name.endswith("_created"):
                    return sample.value
        return 0.0


class Histogram(Metric):
    """Histogram metric for distributions."""

    def observe(self, value: float) -> None:
        self._child.observe(value)

    @property
    def count(self) -> float:
        for family in self._child.collect():
            for sample in family.samples:
                if sample.name.endswith("_count"):
                    return sample.value
        return 0.0

    @property
    def sum_val(self) -> float:
        for family in self._child.collect():
            for sample in family.samples:
                if sample.name.endswith("_sum"):
                    return sample.value
        return 0.0


class Gauge(Metric):
    """Gauge metric - can go up or down."""

    def set(self, value: float) -> None:
        self._child.set(value)

    @property
    def value(self) -> float:
        for family in self._child.collect():
            for sample in family.samples:
                if not sample.name.endswith("_created"):
                    return sample.value
        return 0.0


class MetricsRegistry:
    """Thread-safe metrics registry backed by prometheus_client."""

    _instance: "MetricsRegistry | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "MetricsRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._metrics: dict[str, Metric] = {}
        self._families: dict[tuple[str, tuple[str, ...]], Any] = {}
        self._lock = threading.Lock()

    def counter(self, name: str, help: str, labels: dict[str, str] | None = None) -> Counter:
        """Get or create a counter."""
        return self._get(name, help, labels, "counter")

    def histogram(self, name: str, help: str, labels: dict[str, str] | None = None) -> Histogram:
        """Get or create a histogram."""
        return self._get(name, help, labels, "histogram")

    def gauge(self, name: str, help: str, labels: dict[str, str] | None = None) -> Gauge:
        """Get or create a gauge."""
        return self._get(name, help, labels, "gauge")

    def _get(self, name: str, help: str, labels: dict[str, str] | None, kind: str) -> Metric:
        labels = dict(labels) if labels else {}
        key = self._metric_key(name, labels)
        with self._lock:
            existing = self._metrics.get(key)
            if existing is not None:
                return existing

            sig = tuple(sorted(labels))
            fam_key = (name, sig)
            family = self._families.get(fam_key)
            if family is None:
                family = _create_family(kind, name, help, sig)
                self._families[fam_key] = family

            child = family.labels(**labels) if labels else family
            wrapper = {"counter": Counter, "gauge": Gauge, "histogram": Histogram}[kind](
                name, help, labels, child
            )
            self._metrics[key] = wrapper
            return wrapper

    def _metric_key(self, name: str, labels: dict[str, str]) -> str:
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def to_prometheus(self) -> str:
        """Export metrics in Prometheus text format."""
        with self._lock:
            families = list(self._families.values())
        blocks = [generate_latest(family).decode().rstrip("\n") for family in families]
        return "\n".join(blocks)

    @classmethod
    def reset(cls) -> None:
        """Drop all registered families (test isolation only)."""
        inst = cls._instance
        if inst is not None:
            with inst._lock:
                inst._metrics.clear()
                inst._families.clear()


# Global metrics registry
metrics = MetricsRegistry()


# Convenience functions for common metrics
ticks_processed = metrics.counter("ticks_processed_total", "Total ticks processed")
amt_duration = metrics.histogram("amt_pipeline_duration_seconds", "AMT pipeline execution time")
signals_generated = metrics.counter("signals_generated_total", "Signals generated")
errors_total = metrics.counter("errors_total", "Total errors")
active_positions = metrics.gauge("positions_active", "Currently open positions")

# Dashboard metrics — decision pipeline and trade execution tracking
decisions_evaluated = metrics.counter("decisions_evaluated_total", "Total entry decisions evaluated")
decisions_approved = metrics.counter("decisions_approved_total", "Entry decisions that passed gates")
decisions_blocked = metrics.counter("decisions_blocked_total", "Entry decisions blocked by gates")
trades_executed = metrics.counter("trades_executed_total", "Trades successfully executed")

