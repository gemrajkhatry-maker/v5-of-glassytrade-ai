"""Latency models (P1a) — simulated time between order submission and fill.

Nautilus-style execution realism: a fill is recorded at the market instant the
venue actually filled it, which lags the signal/order instant by some latency.
The default is zero latency (backtest/paper behavior today); plugging in a
``FixedLatencyModel`` or ``UniformLatencyModel`` makes the recorded tape
reproduce the same submission→fill delay a live broker would show, so
backtest/paper parity extends to the timing domain.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Protocol


class LatencyModel(Protocol):
    """Deterministic latency between order submission and fill."""

    def apply(self, timestamp: datetime) -> datetime: ...


class ZeroLatencyModel:
    """No latency — the default (fills record at the order's own instant)."""

    def apply(self, timestamp: datetime) -> datetime:
        return timestamp


class FixedLatencyModel:
    """A constant latency applied to every fill timestamp."""

    def __init__(self, delay: timedelta | None = None, *, milliseconds: int = 0) -> None:
        if delay is not None:
            self._delay = delay
        else:
            self._delay = timedelta(milliseconds=milliseconds)

    def apply(self, timestamp: datetime) -> datetime:
        return timestamp + self._delay


class UniformLatencyModel:
    """Latency drawn uniformly from ``[min_ms, max_ms]`` per fill.

    ``rng`` (a ``random.Random``) makes the draw seed-reproducible so a
    backtest with a fixed seed produces an identical tape every run.
    """

    def __init__(self, min_ms: float, max_ms: float, *, rng: random.Random | None = None) -> None:
        if min_ms < 0 or max_ms < min_ms:
            raise ValueError(f"invalid latency bounds: [{min_ms}, {max_ms}]")
        self._min_ms = min_ms
        self._max_ms = max_ms
        self._rng = rng if rng is not None else random.Random()

    def apply(self, timestamp: datetime) -> datetime:
        ms = self._rng.uniform(self._min_ms, self._max_ms)
        return timestamp + timedelta(milliseconds=ms)


__all__ = ["FixedLatencyModel", "LatencyModel", "UniformLatencyModel", "ZeroLatencyModel"]
