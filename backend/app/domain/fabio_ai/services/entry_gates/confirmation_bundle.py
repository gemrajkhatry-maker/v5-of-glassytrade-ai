"""Confirmation Bundle & Momentum Fade Filter.

FABIO RULE: "Aggression is the trigger."
Volume impulse is MANDATORY — no aggression = no trade.

Components:
1. Volume Impulse: current volume > EMA(20) × multiplier (MANDATORY)
2. Delta Pressure: |delta| / volume > 0.15 (institutional direction)
3. Spread Tightness: bid-ask spread <= 5 bps (liquidity)
"""

from __future__ import annotations

import logging
from datetime import datetime, time as _time
from typing import TYPE_CHECKING

from app.domain.services.candle_metrics import body as calc_body

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC

logger = logging.getLogger(__name__)


def check_confirmation_bundle(data: list, tick: OHLC, order_book=None) -> bool:
    """Confirmation Bundle (2/3): Volume Impulse + Delta Pressure + Spread Tightness.

    Need 2/3 overall, but volume impulse must be present.
    Returns True if bundle passes, False to BLOCK.
    """
    if not data or len(data) < 20:
        return False

    alpha = 2.0 / 21  # EMA(20)
    ema_vol = data[-20].volume
    for d in data[-19:]:
        ema_vol = alpha * d.volume + (1.0 - alpha) * ema_vol

    # FIX #7: Time-aware volume threshold for MCX afternoon lull (13:00-17:00 IST)
    multiplier = 1.5
    try:
        curr_time = datetime.fromisoformat(tick.time.replace("Z", "+05:30")).time()
        if _time(13, 0) <= curr_time <= _time(17, 0):
            multiplier = 1.0
            logger.debug(
                "MCX Lull detected (%.2f IST) - lowering volume multiplier to %.1f",
                curr_time.hour + curr_time.minute / 60,
                multiplier,
            )
    except (ValueError, TypeError):
        pass  # MCX lull detection failure — default multiplier used

    vol_impulse = tick.volume > (ema_vol * multiplier)

    if not vol_impulse:
        logger.debug(
            "Confirmation bundle BLOCKED: no volume impulse (vol=%.0f, ema=%.0f, mult=%.1f)",
            tick.volume, ema_vol, multiplier,
        )
        return False

    delta_ratio = abs(tick.delta) / tick.volume if tick.volume > 0 else 0
    delta_pressure = delta_ratio > 0.15

    spread_tight = False
    if order_book and order_book.bids and order_book.asks:
        best_bid = order_book.bids[0].price
        best_ask = order_book.asks[0].price
        spread = best_ask - best_bid
        mid = (best_ask + best_bid) / 2
        if mid > 0:
            spread_bps = spread / mid * 10000
            spread_tight = spread_bps <= 5.0
    else:
        # In Indian markets, spread data may not be available.
        spread_tight = True

    score = sum([vol_impulse, delta_pressure, spread_tight])
    logger.debug(
        "Confirmation bundle: vol_impulse=%s (vol=%.0f ema=%.0f), "
        "delta_pressure=%s (ratio=%.3f), spread_tight=%s -> %d/3",
        vol_impulse, tick.volume, ema_vol,
        delta_pressure, delta_ratio, spread_tight, score,
    )
    return score >= 2


def check_momentum_fade(data: list, tick: OHLC, direction: str) -> bool:
    """Returns True if entry should be BLOCKED because it fades a freight train.

    Fabio Rule: Do not short a 2.5 sigma bullish impulse on the first touch
    if it has no meaningful rejection wick. (Same for long on bearish impulse).
    """
    if not data or len(data) < 20 or tick.volume <= 0:
        return False

    alpha = 2.0 / 21  # EMA(20)
    ema_vol = data[-20].volume
    for d in data[-19:]:
        ema_vol = alpha * d.volume + (1.0 - alpha) * ema_vol

    # Is it a massive volume spike?
    if tick.volume < (ema_vol * 2.5):
        return False

    body_size = calc_body(tick.open, tick.high, tick.low, tick.close)
    candle_range = tick.high - tick.low

    # Must be a strong directional candle (body is large part of range)
    if candle_range <= 0 or body_size < (candle_range * 0.70):
        return False

    upper_wick = tick.high - max(tick.open, tick.close)
    lower_wick = min(tick.open, tick.close) - tick.low

    # Block SHORT entries against strong BULLISH momentum
    if direction == "SHORT" and tick.close > tick.open:
        if upper_wick < (body_size * 0.3):
            logger.warning(
                "BLOCKED: Attempting to SHORT into 2.5σ bullish momentum without rejection!"
            )
            return True

    # Block LONG entries against strong BEARISH momentum
    if direction == "LONG" and tick.close < tick.open:
        if lower_wick < (body_size * 0.3):
            logger.warning(
                "BLOCKED: Attempting to LONG into 2.5σ bearish momentum without rejection!"
            )
            return True

    return False


def compute_atr(data: list, period: int = 14) -> float:
    """Compute Average True Range over the last *period* bars.

    Uses True Range: max(H−L, |H−prevC|, |L−prevC|) to account for
    gaps between candles, which simple (H−L) misses.
    """
    if len(data) < 2:
        return 0.0
    window = data[-period:] if len(data) > period else data
    trs = []
    prev_close = data[-len(window) - 1].close if len(data) > period else window[0].close
    for c in window:
        high_low = c.high - c.low
        high_prev = abs(c.high - prev_close)
        low_prev = abs(c.low - prev_close)
        trs.append(max(high_low, high_prev, low_prev))
        prev_close = c.close
    return sum(trs) / len(trs) if trs else 0.0
