"""Market-data utility services used by adapters."""

from __future__ import annotations


def compute_vwap_approx(high: float, low: float, close: float) -> float:
    """Compute typical-price proxy VWAP used when tick-level flow is unavailable."""
    return (high + low + close) / 3


def estimate_tick_delta(open_price: float, high: float, low: float, close: float, volume: float) -> float:
    """Approximate delta from candle body when taker side volume is unavailable."""
    spread = high - low
    if spread <= 0 or volume <= 0:
        return 0.0
    body_ratio = (close - open_price) / spread
    return body_ratio * volume
