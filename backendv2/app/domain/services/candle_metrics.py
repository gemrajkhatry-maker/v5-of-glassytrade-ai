"""Reusable candle metric helpers."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.model.value_objects import OHLC


def body(o: float, h: float, l: float, c: float) -> float:
    return abs(c - o)


def body_pct(o: float, h: float, l: float, c: float) -> float:
    rng = h - l
    if rng <= 0:
        return 0.0
    return abs(c - o) / rng


def directional_body(o: float, h: float, l: float, c: float) -> float:
    rng = h - l
    if rng <= 0:
        return 0.0
    return (c - o) / rng


def upper_wick(o: float, h: float, l: float, c: float) -> float:
    return h - max(o, c)


def lower_wick(o: float, h: float, l: float, c: float) -> float:
    return min(o, c) - l


def candle_range(o: float, h: float, l: float, c: float) -> float:
    return h - l


def is_bullish(o: float, c: float) -> bool:
    return c > o


def is_bearish(o: float, c: float) -> bool:
    return c < o


def body_ohlc(candle: "OHLC") -> float:
    return abs(float(candle.close) - float(candle.open))


def body_pct_ohlc(candle: "OHLC") -> float:
    rng = float(candle.high) - float(candle.low)
    if rng <= 0:
        return 0.0
    return abs(float(candle.close) - float(candle.open)) / rng


def wick_rejection(candle: "OHLC", min_body_pct: float = 0.5) -> bool:
    return body_pct_ohlc(candle) < min_body_pct

