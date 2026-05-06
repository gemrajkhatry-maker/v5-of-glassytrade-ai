"""Stateless quantitative detectors for momentum fade and aggressive rejection."""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Dict, Tuple

from app.domain.fabio_ai.services.entry_gates.confirmation_bundle import _to_float, _candle_body

if TYPE_CHECKING:
    from app.domain.trading.model.value_objects import OHLC

logger = logging.getLogger(__name__)


def detect_momentum_fade(
    data: list["OHLC"],
    tick: "OHLC",
    direction: str,
    ema_period: int = 20,
    volume_multiplier: float = 2.5,
    body_ratio_threshold: float = 0.70,
    wick_ratio_threshold: float = 0.3,
) -> Tuple[bool, Dict[str, float]]:
    """Detect momentum fade risk.

    Returns:
        (should_block, metrics)
    """
    metrics: Dict[str, float] = {"body_ratio": 0.0, "wick_ratio": 0.0, "ema_ratio": 0.0}

    if not data or len(data) < ema_period or _to_float(getattr(tick, "volume", 0), default=0.0) <= 0:
        return False, metrics

    alpha = 2.0 / (ema_period + 1)
    ema_vol = _to_float(getattr(data[-ema_period], "volume", 0), default=0.0)
    if ema_vol is None or ema_vol <= 0:
        return False, metrics

    for entry in data[-ema_period + 1 :]:
        ema_vol = alpha * _to_float(getattr(entry, "volume", 0), default=ema_vol) + (1.0 - alpha) * ema_vol

    if not math.isfinite(ema_vol):
        return False, metrics

    tick_volume = _to_float(getattr(tick, "volume", 0), default=0.0)
    if tick_volume is None or tick_volume < (ema_vol * volume_multiplier):
        return False, metrics
    metrics["ema_ratio"] = tick_volume / ema_vol if ema_vol > 0 else 0.0

    open_price = _to_float(getattr(tick, "open", 0.0), default=0.0)
    high = _to_float(getattr(tick, "high", 0.0), default=0.0)
    low = _to_float(getattr(tick, "low", 0.0), default=0.0)
    close = _to_float(getattr(tick, "close", 0.0), default=0.0)

    body_size = _candle_body(open_price, high, low, close)
    candle_range = high - low
    if candle_range <= 0:
        return False, metrics

    metrics["body_ratio"] = body_size / candle_range if candle_range > 0 else 0.0
    if body_size < (candle_range * body_ratio_threshold):
        return False, metrics

    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low
    if body_size > 0:
        metrics["wick_ratio"] = upper_wick / body_size

    if direction == "SHORT" and close > open_price and upper_wick < (body_size * wick_ratio_threshold):
        logger.debug(
            "Momentum fade detected: SHORT blocked with high bullish impulse (vol=%s, body=%s, wick=%s)",
            tick_volume,
            metrics["body_ratio"],
            metrics["wick_ratio"],
        )
        return True, metrics

    if direction == "LONG" and close < open_price and lower_wick < (body_size * wick_ratio_threshold):
        logger.debug(
            "Momentum fade detected: LONG blocked with high bearish impulse (vol=%s, body=%s, wick=%s)",
            tick_volume,
            metrics["body_ratio"],
            metrics["wick_ratio"],
        )
        return True, metrics

    return False, metrics

