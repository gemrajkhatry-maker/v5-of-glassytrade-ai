"""Domain detectors for Fabio AI trading logic.

All detectors are pure functions: no side effects, no state, no I/O.
Input → Output only.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Tuple, Dict, Any

from app.domain.services.candle_metrics import body as calc_body

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC


logger = logging.getLogger(__name__)


def detect_momentum_fade(
    data: list[OHLC],
    tick: OHLC,
    direction: str,
    ema_period: int = 20,
    volume_multiplier: float = 2.5,
    body_ratio_threshold: float = 0.70,
    wick_ratio_threshold: float = 0.3,
) -> Tuple[bool, Dict[str, float]]:
    """Detect momentum fade risk per Fabio Rule:

    "Don't short a 2.5 sigma bullish impulse on the first touch
    if it has no meaningful rejection wick. (Same for long on bearish impulse)."

    Returns:
        - bool: True if momentum fade is detected (i.e., entry should be BLOCKED)
        - dict: metrics used — 'body_ratio', 'wick_ratio', 'ema_ratio'
    """
    metrics: Dict[str, float] = {
        "body_ratio": 0.0,
        "wick_ratio": 0.0,
        "ema_ratio": 0.0,
    }

    # Guard: insufficient data
    if not data or len(data) < ema_period or tick.volume <= 0:
        return False, metrics

    # Compute EMA(20) volume
    alpha = 2.0 / (ema_period + 1)
    try:
        ema_vol = data[-ema_period].volume
        for d in data[-ema_period + 1 :]:
            ema_vol = alpha * d.volume + (1.0 - alpha) * ema_vol
    except (IndexError, ZeroDivisionError):
        return False, metrics

    # Guard: EMA must be finite
    if not math.isfinite(ema_vol):
        return False, metrics

    metrics["ema_ratio"] = tick.volume / ema_vol if ema_vol > 0 else 0.0

    # Is it a massive volume spike?
    if tick.volume < (ema_vol * volume_multiplier):
        return False, metrics

    # Compute candle body and range
    try:
        body_size = calc_body(tick.open, tick.high, tick.low, tick.close)
        candle_range = tick.high - tick.low
    except (ValueError, TypeError, OverflowError):
        return False, metrics

    # Guard: body and range must be finite
    if not (math.isfinite(body_size) and math.isfinite(candle_range)):
        return False, metrics

    metrics["body_ratio"] = body_size / candle_range if candle_range > 0 else 0.0

    # Check if it's a strong directional candle (body > 70% of range)
    if candle_range <= 0 or body_size < (candle_range * body_ratio_threshold):
        return False, metrics

    # Compute wicks
    try:
        upper_wick = tick.high - max(tick.open, tick.close)
        lower_wick = min(tick.open, tick.close) - tick.low
    except (ValueError, TypeError, OverflowError):
        return False, metrics

    # Guard: wicks must be finite
    if not (math.isfinite(upper_wick) and math.isfinite(lower_wick)):
        return False, metrics

    metrics["wick_ratio"] = (
        upper_wick / body_size if body_size > 0 else 0.0
    )

    # Block SHORT entries against strong BULLISH momentum (no rejection wick)
    if direction == "SHORT" and tick.close > tick.open:
        if upper_wick < (body_size * wick_ratio_threshold):
            logger.debug(
                "Momentum fade DETECTED: SHORT blocked — fading 2.5σ bullish impulse without rejection wick (vol=%.0f, ema=%.0f, body_ratio=%.3f, wick_ratio=%.3f)",
                tick.volume,
                ema_vol,
                metrics["body_ratio"],
                metrics["wick_ratio"],
            )
            return True, metrics

    # Block LONG entries against strong BEARISH momentum (no rejection wick)
    if direction == "LONG" and tick.close < tick.open:
        if lower_wick < (body_size * wick_ratio_threshold):
            logger.debug(
                "Momentum fade DETECTED: LONG blocked — fading 2.5σ bearish impulse without rejection wick (vol=%.0f, ema=%.0f, body_ratio=%.3f, wick_ratio=%.3f)",
                tick.volume,
                ema_vol,
                metrics["body_ratio"],
                metrics["wick_ratio"],
            )
            return True, metrics

    return False, metrics
