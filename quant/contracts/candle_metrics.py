"""Candle metrics — common candle pattern computations.

Extracts repeated body/wick/range computations into reusable helpers.
Used across: entry_gate, acceptance_rejection, break_detector,
lvn_play_detector, momentum_fade_gate, features, tick_delta.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quant.contracts.value_objects import OHLC


def body(o: float, h: float, lo: float, c: float) -> float:
    """Candle body size: abs(close - open)."""
    return abs(c - o)


def body_pct(o: float, h: float, lo: float, c: float) -> float:
    """Body as percentage of candle range: body / (high - low)."""
    rng = h - lo
    if rng <= 0:
        return 0.0
    return abs(c - o) / rng


def directional_body(o: float, h: float, lo: float, c: float) -> float:
    """Directional body ratio: (close - open) / (high - low).

    Returns: -1.0 (fully bearish) to +1.0 (fully bullish).
    """
    rng = h - lo
    if rng <= 0:
        return 0.0
    return (c - o) / rng


def upper_wick(o: float, h: float, lo: float, c: float) -> float:
    """Upper wick: high - max(open, close)."""
    return h - max(o, c)


def lower_wick(o: float, h: float, lo: float, c: float) -> float:
    """Lower wick: min(open, close) - low."""
    return min(o, c) - lo


def candle_range(o: float, h: float, lo: float, c: float) -> float:
    """Candle range: high - low."""
    return h - lo


def is_bullish(o: float, c: float) -> bool:
    """True if close > open (bullish candle)."""
    return c > o


def is_bearish(o: float, c: float) -> bool:
    """True if close < open (bearish candle)."""
    return c < o


def body_ohlc(candle: "OHLC") -> float:
    """Body size from OHLC object."""
    return abs(float(candle.close) - float(candle.open))


def body_pct_ohlc(candle: "OHLC") -> float:
    """Body percentage from OHLC object."""
    rng = float(candle.high) - float(candle.low)
    if rng <= 0:
        return 0.0
    return abs(float(candle.close) - float(candle.open)) / rng


def wick_rejection(candle: "OHLC", min_body_pct: float = 0.5) -> bool:
    """Check if candle shows wick rejection (long wick relative to body).

    A rejection candle has body < min_body_pct of total candle range.
    """
    return body_pct_ohlc(candle) < min_body_pct
