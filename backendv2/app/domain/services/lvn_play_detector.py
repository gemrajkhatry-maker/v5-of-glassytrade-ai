"""LVN play detector for rejection + velocity + delta flip confirmation."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.domain.services.candle_metrics import body as calc_body

if TYPE_CHECKING:
    from app.domain.trading.model.value_objects import OHLC


def detect_lvn_play(
    candle: "OHLC",
    lvns: list[float],
    hvns: list[float],
    poc: float,
    baseline_vol: float,
    cvd_slope: float,
    prev_cvd_slope: float = 0.0,
) -> dict | None:
    """Return a dict describing an LVN rejection play, or None."""
    if not lvns or candle.volume <= 0:
        return None

    threshold = candle.close * 0.003
    nearest_lvn = None
    nearest_dist = float("inf")
    for lvn in lvns:
        dist = abs(candle.close - lvn)
        if dist <= threshold and dist < nearest_dist:
            nearest_lvn = lvn
            nearest_dist = dist

    if nearest_lvn is None:
        return None

    velocity_ratio = candle.volume / baseline_vol if baseline_vol > 0 else 0.0
    has_velocity = velocity_ratio > 2.0

    body_size = calc_body(candle.open, candle.high, candle.low, candle.close)
    upper_wick = candle.high - max(candle.open, candle.close)
    lower_wick = min(candle.open, candle.close) - candle.low
    has_rejection = max(upper_wick, lower_wick) > body_size and body_size > 0
    has_delta_flip = (cvd_slope * prev_cvd_slope < 0) if prev_cvd_slope != 0 else False

    score = sum([has_velocity, has_rejection, has_delta_flip])
    if score < 2:
        return None

    direction = "LONG" if lower_wick > upper_wick else "SHORT"
    target = poc
    if hvns:
        if direction == "LONG":
            above = [h for h in hvns if h > candle.close]
            if above:
                target = min(above)
        else:
            below = [h for h in hvns if h < candle.close]
            if below:
                target = max(below)

    return {
        "lvn_price": nearest_lvn,
        "direction": direction,
        "target": target,
        "velocity_ratio": round(velocity_ratio, 2),
        "has_rejection": has_rejection,
        "has_delta_flip": has_delta_flip,
    }

