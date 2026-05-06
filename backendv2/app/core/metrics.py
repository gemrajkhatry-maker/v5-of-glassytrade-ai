"""MetricsRegistry — simple metrics collection for counters, gauges, histograms.

Extracted from core_components.py to enable dependency injection and testing.
"""
from __future__ import annotations

import threading
from typing import Any


class MetricsRegistry:
    """Simple metrics registry for counters, gauges, histograms.
    
    Thread-safe. Used for observability endpoints and telemetry.
    """
    
    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}
    
    def counter(self, name: str, value: float = 1.0) -> None:
        """Increment a counter by value (default 1.0)."""
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + value
    
    def gauge(self, name: str, value: float) -> None:
        """Set a gauge to value (overwrites previous)."""
        with self._lock:
            self._gauges[name] = value
    
    def histogram(self, name: str, value: float) -> None:
        """Record a histogram value."""
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = []
            self._histograms[name].append(value)
    
    def get_counter(self, name: str) -> float:
        """Get a counter value (returns 0 if not found)."""
        with self._lock:
            return self._counters.get(name, 0)
    
    def snapshot(self) -> dict[str, Any]:
        """Return a snapshot of all metrics.
        
        Returns:
            Dict with 'counters', 'gauges', and 'histograms' keys.
            Histograms show count of values recorded.
        """
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {k: len(v) for k, v in self._histograms.items()}
            }
