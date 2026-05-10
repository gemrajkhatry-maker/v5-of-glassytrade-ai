"""Enhanced metrics collector with labels, histogram stats, and Prometheus output.

Complements the existing MetricsRegistry with richer functionality.
"""

from __future__ import annotations

import contextlib
import threading
import time
from typing import Any


def _labels_key(labels: dict[str, str] | None) -> str:
    """Create a deterministic key from labels dict."""
    if not labels:
        return ""
    return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))


class Counter:
    """Thread-safe monotonically increasing counter with optional labels."""

    def __init__(self, name: str, labels: dict[str, str] | None = None):
        self.name = name
        self.labels = labels or {}
        self._lock = threading.Lock()
        self._value = 0.0

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value += amount

    @property
    def value(self) -> float:
        with self._lock:
            return self._value

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "labels": dict(self.labels),
            "value": self.value,
        }


class Gauge:
    """Thread-safe gauge that can go up and down."""

    def __init__(self, name: str, labels: dict[str, str] | None = None):
        self.name = name
        self.labels = labels or {}
        self._lock = threading.Lock()
        self._value = 0.0

    def set(self, value: float) -> None:
        with self._lock:
            self._value = value

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value += amount

    def dec(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value -= amount

    @property
    def value(self) -> float:
        with self._lock:
            return self._value

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "labels": dict(self.labels),
            "value": self.value,
        }


class Histogram:
    """Track distribution of values with count, sum, min, max, avg, percentiles."""

    def __init__(self, name: str, labels: dict[str, str] | None = None):
        self.name = name
        self.labels = labels or {}
        self._lock = threading.Lock()
        self._values: list[float] = []

    def observe(self, value: float) -> None:
        with self._lock:
            self._values.append(value)

    @contextlib.contextmanager
    def time(self):
        start = time.perf_counter_ns()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
            self.observe(elapsed_ms)

    def _stats(self) -> dict[str, float]:
        if not self._values:
            return {"count": 0, "sum": 0.0, "min": 0.0, "max": 0.0, "avg": 0.0}
        sorted_v = sorted(self._values)
        n = len(sorted_v)
        def pct(ratio: float) -> float:
            idx = int(n * ratio)
            idx = max(0, min(idx, n - 1))
            return sorted_v[idx]
        return {
            "count": float(n),
            "sum": sum(sorted_v),
            "min": sorted_v[0],
            "max": sorted_v[-1],
            "avg": sum(sorted_v) / n,
            "p50": pct(0.50),
            "p95": pct(0.95),
            "p99": pct(0.99),
        }

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._values)

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "name": self.name,
                "labels": dict(self.labels),
                "stats": self._stats(),
            }


class MetricsCollector:
    """Registry for counters, gauges, and histograms with label support."""

    def __init__(self):
        self._lock = threading.RLock()
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}

    def counter(self, name: str, labels: dict[str, str] | None = None) -> Counter:
        key = f"{name}:{_labels_key(labels)}"
        with self._lock:
            if key not in self._counters:
                self._counters[key] = Counter(name, labels)
            return self._counters[key]

    def gauge(self, name: str, labels: dict[str, str] | None = None) -> Gauge:
        key = f"{name}:{_labels_key(labels)}"
        with self._lock:
            if key not in self._gauges:
                self._gauges[key] = Gauge(name, labels)
            return self._gauges[key]

    def histogram(self, name: str, labels: dict[str, str] | None = None) -> Histogram:
        key = f"{name}:{_labels_key(labels)}"
        with self._lock:
            if key not in self._histograms:
                self._histograms[key] = Histogram(name, labels)
            return self._histograms[key]

    @contextlib.contextmanager
    def timing(self, name: str, labels: dict[str, str] | None = None):
        h = self.histogram(name, labels)
        with h.time():
            yield

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "counters": [v.to_dict() for v in self._counters.values()],
                "gauges": [v.to_dict() for v in self._gauges.values()],
                "histograms": [v.to_dict() for v in self._histograms.values()],
            }

    def format_prometheus(self) -> str:
        """Format metrics as Prometheus text exposition format."""
        lines: list[str] = []
        with self._lock:
            for metric in self._counters.values():
                label_str = self._format_labels(metric.labels)
                lines.append(f"{metric.name}{label_str} {metric.value}")

            for metric in self._gauges.values():
                label_str = self._format_labels(metric.labels)
                lines.append(f"{metric.name}{label_str} {metric.value}")

            for metric in self._histograms.values():
                stats = metric.to_dict()["stats"]
                label_str = self._format_labels(metric.labels)
                lines.append(f"{metric.name}_count{label_str} {stats['count']}")
                lines.append(f"{metric.name}_sum{label_str} {stats['sum']}")
                if stats["count"] > 0:
                    lines.append(f"{metric.name}_min{label_str} {stats['min']}")
                    lines.append(f"{metric.name}_max{label_str} {stats['max']}")
                    lines.append(f"{metric.name}_avg{label_str} {stats['avg']}")
                    lines.append(f"{metric.name}_p50{label_str} {stats['p50']}")
                    lines.append(f"{metric.name}_p95{label_str} {stats['p95']}")
                    lines.append(f"{metric.name}_p99{label_str} {stats['p99']}")

        return "\n".join(lines)

    @staticmethod
    def _format_labels(labels: dict[str, str]) -> str:
        if not labels:
            return ""
        pairs = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{{{pairs}}}"

    def clear(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
