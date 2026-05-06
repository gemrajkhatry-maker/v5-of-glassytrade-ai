"""Per-symbol rolling latency metrics for data-path and inference timing."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class LatencySnapshot:
    p50: float
    p95: float
    p99: float
    max_ms: float
    sample_count: int
    warning: bool
    critical: bool


class LatencyTracker:
    def __init__(self, window_size: int = 1000) -> None:
        self._window_size = int(window_size)
        self._samples: dict[str, deque[float]] = {}

    def record(self, symbol: str, latency_ms: float) -> None:
        if symbol not in self._samples:
            self._samples[symbol] = deque(maxlen=self._window_size)
        self._samples[symbol].append(float(latency_ms))

    def get_snapshot(self, symbol: str) -> LatencySnapshot:
        samples = self._samples.get(symbol)
        if not samples:
            return LatencySnapshot(0.0, 0.0, 0.0, 0.0, 0, False, False)

        sorted_samples = sorted(samples)
        n = len(sorted_samples)
        p50 = sorted_samples[int(n * 0.50)]
        p95 = sorted_samples[min(int(n * 0.95), n - 1)]
        p99 = sorted_samples[min(int(n * 0.99), n - 1)]
        max_ms = sorted_samples[-1]

        return LatencySnapshot(
            p50=round(p50, 2),
            p95=round(p95, 2),
            p99=round(p99, 2),
            max_ms=round(max_ms, 2),
            sample_count=n,
            warning=p99 > 50.0,
            critical=p99 > 200.0,
        )

    def get_all_snapshots(self) -> dict[str, LatencySnapshot]:
        return {symbol: self.get_snapshot(symbol) for symbol in self._samples}

    def get_summary(self) -> dict:
        return {
            symbol: {
                "p50": snap.p50,
                "p95": snap.p95,
                "p99": snap.p99,
                "max": snap.max_ms,
                "samples": snap.sample_count,
                "warning": snap.warning,
                "critical": snap.critical,
            }
            for symbol, snap in self.get_all_snapshots().items()
        }

    def reset(self) -> None:
        self._samples.clear()

