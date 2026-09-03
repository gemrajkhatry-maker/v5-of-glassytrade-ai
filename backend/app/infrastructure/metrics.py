"""Metrics Collector — tracks signal counts, P&L, cache hits.

Counterpart: app/core/metrics.py (Prometheus registry; do not merge — different purpose).
Exposes metrics as a dict for the /api/v1/metrics endpoint.
"""

from __future__ import annotations

import threading
import time
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
        self._signal_counts: dict[str, int] = defaultdict(int)
        self._total_pnl: float = 0.0
        self._cache_hits: int = 0
        self._cache_misses: int = 0
        self._regime_changes: int = 0
        self._ticks_processed: int = 0
        self._start_time = time.time()
        self._initialized = True

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

    @classmethod
    def reset(cls) -> None:
        """Reset singleton state (test isolation only — never call live)."""
        inst = cls._instance
        if inst is not None and getattr(inst, "_initialized", False):
            with inst._lock:
                inst._signal_counts.clear()
                inst._total_pnl = 0.0
                inst._cache_hits = 0
                inst._cache_misses = 0
                inst._regime_changes = 0
                inst._ticks_processed = 0

    def snapshot(self) -> dict:
        """Return current metrics as a dict. Keys are a stable contract for /api/v1/metrics — do not rename."""
        with self._lock:
            total_cache = self._cache_hits + self._cache_misses

            return {
                "uptime_seconds": time.time() - self._start_time,
                "ticks_processed": self._ticks_processed,
                "signals": dict(self._signal_counts),
                "total_pnl": round(self._total_pnl, 2),
                "cache": {
                    "hits": self._cache_hits,
                    "misses": self._cache_misses,
                    "hit_rate": round(self._cache_hits / total_cache, 3) if total_cache > 0 else 0,
                },
                "regime_changes": self._regime_changes,
            }
