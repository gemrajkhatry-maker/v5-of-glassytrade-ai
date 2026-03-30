"""LVN Play Detection — velocity spike + rejection candle + delta flip at LVN.

Detects LVN rejection plays: price touches a Low Volume Node, gets rejected
with a velocity spike and/or CVD delta flip.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.domain.services.candle_metrics import body as calc_body

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC


def detect_lvn_play(
    candle: OHLC,
    lvns: list[float],
    hvns: list[float],
    poc: float,
    baseline_vol: float,
    cvd_slope: float,
    prev_cvd_slope: float = 0.0,
) -> dict | None:
    """Detect LVN rejection play: velocity spike + rejection candle + delta flip at LVN.

    Returns play details dict or None if no play detected.
    """
    if not lvns or candle.volume <= 0:
        return None

    threshold = candle.close * 0.003  # 0.3% proximity

    # Find nearest LVN
    nearest_lvn = None
    nearest_dist = float("inf")
    for lvn in lvns:
        dist = abs(candle.close - lvn)
        if dist < threshold and dist < nearest_dist:
            nearest_lvn = lvn
            nearest_dist = dist

    if nearest_lvn is None:
        return None

    # Velocity spike: volume > 2x baseline
    velocity_ratio = candle.volume / baseline_vol if baseline_vol > 0 else 0.0
    has_velocity = velocity_ratio > 2.0

    # Rejection candle: wick > body
    body_size = calc_body(candle.open, candle.high, candle.low, candle.close)
    upper_wick = candle.high - max(candle.open, candle.close)
    lower_wick = min(candle.open, candle.close) - candle.low
    has_rejection = max(upper_wick, lower_wick) > body and body > 0

    # Delta flip: CVD slope sign change
    has_delta_flip = (cvd_slope * prev_cvd_slope < 0) if prev_cvd_slope != 0 else False

    # Need at least 2 of 3 conditions
    score = sum([has_velocity, has_rejection, has_delta_flip])
    if score < 2:
        return None

    # Determine direction from rejection
    if lower_wick > upper_wick:
        direction = "LONG"  # rejected lower prices -> bounce up
    else:
        direction = "SHORT"  # rejected higher prices -> move down

    # Target: POC or nearest HVN
    target = poc
    if hvns:
        if direction == "LONG":
            above_hvns = [h for h in hvns if h > candle.close]
            if above_hvns:
                target = min(above_hvns)
        else:
            below_hvns = [h for h in hvns if h < candle.close]
            if below_hvns:
                target = max(below_hvns)

    return {
        "lvn_price": nearest_lvn,
        "direction": direction,
        "target": target,
        "velocity_ratio": round(velocity_ratio, 2),
        "has_rejection": has_rejection,
        "has_delta_flip": has_delta_flip,
    }
