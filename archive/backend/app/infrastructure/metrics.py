"""Metrics Collector — tracks inference latency, signal counts, P&L, cache hits.

Exposes metrics as a dict for the /api/v1/metrics endpoint.
"""

from __future__ import annotations

import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field


class MetricsCollector:
    """Singleton metrics collector for the trading pipeline."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._lock = threading.Lock()
        self._inference_latencies: list[float] = []
        self._signal_counts: dict[str, int] = defaultdict(int)
        self._total_pnl: float = 0.0
        self._cache_hits: int = 0
        self._cache_misses: int = 0
        self._regime_changes: int = 0
        self._ticks_processed: int = 0
        self._start_time = time.time()
        self._initialized = True

    def record_inference_latency(self, latency_seconds: float) -> None:
        with self._lock:
            self._inference_latencies.append(latency_seconds)
            if len(self._inference_latencies) > 1000:
                self._inference_latencies = self._inference_latencies[-500:]

    def record_signal(self, direction: str) -> None:
        with self._lock:
            self._signal_counts[direction] += 1

    def record_pnl(self, pnl: float) -> None:
        with self._lock:
            self._total_pnl += pnl

    def record_cache_hit(self) -> None:
        with self._lock:
            self._cache_hits += 1

    def record_cache_miss(self) -> None:
        with self._lock:
            self._cache_misses += 1

    def record_regime_change(self) -> None:
        with self._lock:
            self._regime_changes += 1

    def record_tick(self) -> None:
        with self._lock:
            self._ticks_processed += 1

    def snapshot(self) -> dict:
        """Return current metrics as a dict."""
        with self._lock:
            latencies = self._inference_latencies.copy()
            total_cache = self._cache_hits + self._cache_misses

            avg_latency = sum(latencies) / len(latencies) if latencies else 0
            p50 = sorted(latencies)[len(latencies) // 2] if latencies else 0
            p95_idx = int(len(latencies) * 0.95)
            p95 = sorted(latencies)[p95_idx] if latencies else 0

            return {
                "uptime_seconds": time.time() - self._start_time,
                "ticks_processed": self._ticks_processed,
                "inference": {
                    "count": len(latencies),
                    "avg_latency_s": round(avg_latency, 3),
                    "p50_latency_s": round(p50, 3),
                    "p95_latency_s": round(p95, 3),
                },
                "signals": dict(self._signal_counts),
                "total_pnl": round(self._total_pnl, 2),
                "cache": {
                    "hits": self._cache_hits,
                    "misses": self._cache_misses,
                    "hit_rate": round(self._cache_hits / total_cache, 3) if total_cache > 0 else 0,
                },
                "regime_changes": self._regime_changes,
            }
