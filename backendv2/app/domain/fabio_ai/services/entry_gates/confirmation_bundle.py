"""Confirmation bundle and momentum filters.

Fabio rule: aggression is the trigger. This module mirrors legacy v1 behavior
while avoiding brittle assumptions in decimal/float mixed OHLC payloads.
"""

from __future__ import annotations

import logging
from datetime import datetime, time as _time
from typing import TYPE_CHECKING

from app.domain.constants import CVD_SLOPE_HARD_BLOCK

if TYPE_CHECKING:
    from app.domain.trading.model.value_objects import OHLC

logger = logging.getLogger(__name__)


def _to_float(value, default: float | None = 0.0) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _candle_body(open_price: float, high: float, low: float, close: float) -> float:
    return abs(close - open_price)


def check_confirmation_bundle(data: list, tick: "OHLC", order_book=None) -> bool:
    """Three-point confirmation requiring volume impulse + delta pressure + spread.

    Requires at least 2 of the 3 signals; volume impulse is mandatory.
    """
    if not data or len(data) < 20:
        return False

    history = list(data[-20:])
    vol_values = [_to_float(getattr(item, "volume", None), default=None) for item in history]
    vol_values = [v for v in vol_values if v is not None]
    if len(vol_values) < 2:
        return False

    alpha = 2.0 / 21  # EMA(20)
    ema_vol = vol_values[0]
    for raw_volume in vol_values[1:]:
        ema_vol = alpha * raw_volume + (1.0 - alpha) * ema_vol

    multiplier = 1.5
    try:
        tick_time = getattr(tick, "time", "")
        if isinstance(tick_time, str) and "T" in tick_time:
            # Keep legacy MCX lull rule without failing on timezone shape differences.
            current_time = datetime.fromisoformat(tick_time.replace("Z", "+05:30")).time()
            if _time(13, 0) <= current_time <= _time(17, 0):
                multiplier = 1.0
    except (ValueError, TypeError):
        pass

    tick_volume = _to_float(getattr(tick, "volume", 0), default=0.0)
    tick_delta = _to_float(getattr(tick, "delta", 0), default=0.0)
    if tick_volume <= 0:
        return False

    vol_impulse = tick_volume > (ema_vol * multiplier)
    if not vol_impulse:
        logger.debug(
            "confirmation_bundle blocked: no volume impulse (vol=%.0f ema=%.0f mult=%.1f)",
            tick_volume,
            ema_vol,
            multiplier,
        )
        return False

    delta_ratio = abs(tick_delta) / tick_volume if tick_volume > 0 else 0.0
    delta_pressure = delta_ratio > 0.15

    spread_tight = False
    if order_book and getattr(order_book, "bids", None) and getattr(order_book, "asks", None):
        best_bid = _to_float(order_book.bids[0].price, default=0.0)
        best_ask = _to_float(order_book.asks[0].price, default=0.0)
        spread = (best_ask - best_bid) if best_ask >= best_bid else 0.0
        mid = (best_ask + best_bid) / 2 if best_ask > 0 and best_bid > 0 else 0.0
        spread_tight = (spread / mid * 10000) <= 5.0 if mid > 0 else False
    else:
        # In some environments order book is unavailable; treat as pass.
        spread_tight = True

    score = sum([vol_impulse, delta_pressure, spread_tight])
    logger.debug(
        "confirmation_bundle: vol=%0.0f ema=%0.0f delta_ratio=%0.3f spread_tight=%s score=%d/3",
        tick_volume,
        ema_vol,
        delta_ratio,
        spread_tight,
        score,
    )
    return score >= 2


def check_momentum_fade(data: list, tick: "OHLC", direction: str) -> bool:
    """Return True when momentum is too strong and rejection is absent."""
    if not data or len(data) < 20 or _to_float(getattr(tick, "volume", 0), default=0.0) <= 0:
        return False

    alpha = 2.0 / 21  # EMA(20)
    history = list(data[-20:])
    vol_values = [_to_float(getattr(item, "volume", None), default=None) for item in history]
    vol_values = [v for v in vol_values if v is not None]
    if len(vol_values) < 2:
        return False

    ema_vol = vol_values[0]
    for raw_volume in vol_values[1:]:
        ema_vol = alpha * raw_volume + (1.0 - alpha) * ema_vol

    tick_volume = _to_float(getattr(tick, "volume", 0), default=0.0)
    if tick_volume < (ema_vol * 2.5):
        return False

    open_price = _to_float(getattr(tick, "open", 0.0), default=0.0)
    high = _to_float(getattr(tick, "high", 0.0), default=0.0)
    low = _to_float(getattr(tick, "low", 0.0), default=0.0)
    close = _to_float(getattr(tick, "close", 0.0), default=0.0)

    body_size = _candle_body(open_price, high, low, close)
    candle_range = high - low
    if candle_range <= 0 or body_size < (candle_range * 0.70):
        return False

    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low

    if direction == "SHORT" and close > open_price and upper_wick < (body_size * 0.30):
        return True
    if direction == "LONG" and close < open_price and lower_wick < (body_size * 0.30):
        return True
    return False


def compute_atr(data: list, period: int = 14) -> float:
    """Average True Range helper, resilient to missing OHLC entries."""
    if len(data) < 2:
        return 0.0

    window = data[-period:] if len(data) > period else data
    if not window:
        return 0.0

    first = window[0]
    prev_close = _to_float(getattr(first, "close", 0.0), default=0.0)
    if len(data) > period and len(window) >= 2:
        prev_close = _to_float(getattr(data[-len(window) - 1], "close", prev_close), default=prev_close)

    trs: list[float] = []
    for candle in window:
        high = _to_float(getattr(candle, "high", 0.0), default=0.0)
        low = _to_float(getattr(candle, "low", 0.0), default=0.0)
        close = _to_float(getattr(candle, "close", 0.0), default=0.0)
        if high == 0.0 and low == 0.0 and prev_close == 0.0:
            prev_close = close
            continue
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        prev_close = close

    return sum(trs) / len(trs) if trs else 0.0


def detect_extreme_cvd(cvd_slope: float | None) -> bool:
    """Return True when CVD slope is extreme in either direction."""
    slope = _to_float(cvd_slope, default=0.0) or 0.0
    return abs(slope) >= CVD_SLOPE_HARD_BLOCK

