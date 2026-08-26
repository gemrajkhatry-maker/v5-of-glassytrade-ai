"""Frozen OHLCV bar shared across all quant detectors."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_INTERVAL_SEC = 300  # canonical default bar interval (5 minutes)


@dataclass(frozen=True)
class Bar:
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    delta: float = 0.0
    oi: float = 0.0
    vwap: float = 0.0  # volume-weighted average price accumulated by BarAggregator
