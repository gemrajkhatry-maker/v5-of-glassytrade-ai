"""Latency Tracker — tick-to-signal latency measurement.

Tracked per symbol with rolling 1000-sample window.
Alert thresholds: p99 > 50ms = warning, p99 > 200ms = critical.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class LatencySnapshot:
    """Immutable snapshot of latency metrics."""

    p50: float
    p95: float
    p99: float
    max_ms: float
    sample_count: int
    warning: bool  # p99 > 50ms
    critical: bool  # p99 > 200ms


class LatencyTracker:
    """Per-symbol latency tracker with rolling window.

    Uses deque(maxlen=1000) — no memory growth.
    """

    def __init__(self, window_size: int = 1000) -> None:
        self._window_size = window_size
        self._samples: dict[str, deque[float]] = {}

    def record(self, symbol: str, latency_ms: float) -> None:
        """Record a latency sample in milliseconds."""
        if symbol not in self._samples:
            self._samples[symbol] = deque(maxlen=self._window_size)
        self._samples[symbol].append(latency_ms)

    def get_snapshot(self, symbol: str) -> LatencySnapshot:
        """Get latency metrics for a symbol."""
        samples = self._samples.get(symbol)
        if not samples:
            return LatencySnapshot(
                p50=0,
                p95=0,
                p99=0,
                max_ms=0,
                sample_count=0,
                warning=False,
                critical=False,
            )

        sorted_s = sorted(samples)
        n = len(sorted_s)
        p50 = sorted_s[int(n * 0.50)]
        p95 = sorted_s[int(n * 0.95)]
        p99 = sorted_s[min(int(n * 0.99), n - 1)]
        max_ms = sorted_s[-1]

        return LatencySnapshot(
            p50=round(p50, 2),
            p95=round(p95, 2),
            p99=round(p99, 2),
            max_ms=round(max_ms, 2),
            sample_count=n,
            warning=p99 > 50,
            critical=p99 > 200,
        )

    def get_all_snapshots(self) -> dict[str, LatencySnapshot]:
        """Get latency metrics for all tracked symbols."""
        return {sym: self.get_snapshot(sym) for sym in self._samples}

    def get_summary(self) -> dict:
        """Get summary across all symbols."""
        result = {}
        for sym in self._samples:
            snap = self.get_snapshot(sym)
            result[sym] = {
                "p50": snap.p50,
                "p95": snap.p95,
                "p99": snap.p99,
                "max": snap.max_ms,
                "samples": snap.sample_count,
                "warning": snap.warning,
                "critical": snap.critical,
            }
        return result

    def reset(self) -> None:
        self._samples.clear()
