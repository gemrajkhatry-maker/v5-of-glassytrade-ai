"""Prometheus-style metrics registry for trading system."""

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Metric:
    """Base metric class."""
    name: str
    help: str
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class Counter(Metric):
    """Counter metric - only increases."""
    value: float = 0.0
    
    def inc(self, amount: float = 1.0) -> None:
        self.value += amount


@dataclass
class Histogram(Metric):
    """Histogram metric for distributions."""
    buckets: dict[float, int] = field(default_factory=lambda: defaultdict(int))
    sum_val: float = 0.0
    count: int = 0
    
    def observe(self, value: float) -> None:
        self.sum_val += value
        self.count += 1
        # Standard buckets: 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10
        for bucket in [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, float('inf')]:
            if value <= bucket:
                self.buckets[bucket] += 1
                break


@dataclass
class Gauge(Metric):
    """Gauge metric - can go up or down."""
    value: float = 0.0
    
    def set(self, value: float) -> None:
        self.value = value


class MetricsRegistry:
    """Thread-safe metrics registry."""
    
    _instance: "MetricsRegistry | None" = None
    _lock = threading.Lock()
    
    def __new__(cls) -> "MetricsRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        self._metrics: dict[str, Metric] = {}
        self._lock = threading.Lock()
    
    def counter(self, name: str, help: str, labels: dict[str, str] | None = None) -> Counter:
        """Get or create a counter."""
        key = self._metric_key(name, labels)
        with self._lock:
            if key not in self._metrics:
                self._metrics[key] = Counter(name=name, help=help, labels=labels or {})
            return self._metrics[key]
    
    def histogram(self, name: str, help: str, labels: dict[str, str] | None = None) -> Histogram:
        """Get or create a histogram."""
        key = self._metric_key(name, labels)
        with self._lock:
            if key not in self._metrics:
                self._metrics[key] = Histogram(name=name, help=help, labels=labels or {})
            return self._metrics[key]
    
    def gauge(self, name: str, help: str, labels: dict[str, str] | None = None) -> Gauge:
        """Get or create a gauge."""
        key = self._metric_key(name, labels)
        with self._lock:
            if key not in self._metrics:
                self._metrics[key] = Gauge(name=name, help=help, labels=labels or {})
            return self._metrics[key]
    
    def _metric_key(self, name: str, labels: dict[str, str] | None) -> str:
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"
    
    def to_prometheus(self) -> str:
        """Export metrics in Prometheus format."""
        lines = []
        with self._lock:
            for metric in self._metrics.values():
                lines.append(f"# HELP {metric.name} {metric.help}")
                lines.append(f"# TYPE {metric.name} {type(metric).__name__.lower()}")
                
                if isinstance(metric, Counter):
                    lines.append(f"{self._metric_key(metric.name, metric.labels)} {metric.value}")
                
                elif isinstance(metric, Gauge):
                    lines.append(f"{self._metric_key(metric.name, metric.labels)} {metric.value}")
                
                elif isinstance(metric, Histogram):
                    for bucket, count in metric.buckets.items():
                        le = "+Inf" if bucket == float('inf') else bucket
                        lines.append(f'{self._metric_key(metric.name, metric.labels)}_bucket{{le="{le}"}} {count}')
                    lines.append(f"{self._metric_key(metric.name, metric.labels)}_sum {metric.sum_val}")
                    lines.append(f"{self._metric_key(metric.name, metric.labels)}_count {metric.count}")
        
        return "\n".join(lines)


# Global metrics registry
metrics = MetricsRegistry()


# Convenience functions for common metrics
ticks_processed = metrics.counter("ticks_processed_total", "Total ticks processed")
amt_duration = metrics.histogram("amt_pipeline_duration_seconds", "AMT pipeline execution time")
signals_generated = metrics.counter("signals_generated_total", "Signals generated")
errors_total = metrics.counter("errors_total", "Total errors")
active_positions = metrics.gauge("positions_active", "Currently open positions")