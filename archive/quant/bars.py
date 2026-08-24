"""Frozen OHLCV bar shared across all quant detectors."""

from __future__ import annotations

from dataclasses import dataclass


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
