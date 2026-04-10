"""Latency Tracker — tracks p50/p95/p99/max latency per symbol.

Matches original backend metrics:
- p50: Median tick processing latency
- p95: 95th percentile
- p99: 99th percentile
- max: Maximum observed
- samples: Total samples
- warning/critical: Threshold alerts
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class LatencyStats:
    p50: float
    p95: float
    p99: float
    max_latency: float
    samples: int
    warning: bool  # p95 > 50ms
    critical: bool  # p99 > 100ms


class LatencyTracker:
    """Per-symbol latency tracking."""

    def __init__(
        self,
        warning_threshold_ms: float = 50.0,
        critical_threshold_ms: float = 100.0,
        max_samples: int = 10000,
    ):
        self._warning_threshold = warning_threshold_ms
        self._critical_threshold = critical_threshold_ms
        self._max_samples = max_samples
        self._latencies: dict[str, list[float]] = {}

    def record(self, symbol: str, latency_ms: float) -> None:
        """Record a latency measurement."""
        if symbol not in self._latencies:
            self._latencies[symbol] = []

        self._latencies[symbol].append(latency_ms)
        if len(self._latencies[symbol]) > self._max_samples:
            self._latencies[symbol] = self._latencies[symbol][-self._max_samples:]

    def record_start(self, symbol: str) -> float:
        """Record start time, returns timestamp."""
        return time.monotonic()

    def record_end(self, symbol: str, start_time: float) -> None:
        """Record end time, calculates and stores latency."""
        latency_ms = (time.monotonic() - start_time) * 1000
        self.record(symbol, latency_ms)

    def get_stats(self, symbol: str) -> LatencyStats:
        """Get latency statistics for a symbol."""
        latencies = self._latencies.get(symbol, [])
        if not latencies:
            return LatencyStats(
                p50=0.0, p95=0.0, p99=0.0, max_latency=0.0,
                samples=0, warning=False, critical=False,
            )

        sorted_lat = sorted(latencies)
        n = len(sorted_lat)

        p50 = sorted_lat[int(n * 0.50)]
        p95 = sorted_lat[int(n * 0.95)] if n > 1 else sorted_lat[0]
        p99 = sorted_lat[int(n * 0.99)] if n > 1 else sorted_lat[0]
        max_lat = sorted_lat[-1]

        return LatencyStats(
            p50=round(p50, 2),
            p95=round(p95, 2),
            p99=round(p99, 2),
            max_latency=round(max_lat, 2),
            samples=n,
            warning=p95 > self._warning_threshold,
            critical=p99 > self._critical_threshold,
        )

    def get_all_stats(self) -> dict[str, LatencyStats]:
        """Get stats for all symbols."""
        return {sym: self.get_stats(sym) for sym in self._latencies}

    def reset(self, symbol: str = "") -> None:
        """Reset latency data."""
        if symbol:
            self._latencies.pop(symbol, None)
        else:
            self._latencies.clear()
