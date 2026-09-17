"""Frozen OHLCV bar shared across all quant detectors."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_INTERVAL_SEC = 300  # canonical default bar interval (5 minutes)
BIAS_INTERVAL_SEC = 900  # 15-minute bias layer (Fabio top-down: 15m → 5m → 1m)


@dataclass(frozen=True)
class Bar:
    time: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    delta: float = 0.0
    oi: float = 0.0
    vwap: float = 0.0  # volume-weighted average price accumulated by BarAggregator
