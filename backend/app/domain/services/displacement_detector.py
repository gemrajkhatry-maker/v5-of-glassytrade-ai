"""Displacement Detector — impulsive move + acceptance/rejection detection.

Extracted from amt_analyzer.py for SRP compliance.

Detects:
  - Displacement: 3+ consecutive directional candles with range expansion
  - Acceptance: 2+ consecutive closes outside VA (above VAH or below VAL)
  - Displacement leg: profile of the most recent directional move
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, VolumeProfileLevel

from app.domain.constants import (
    DELTA_PROFILE_BUCKETS,
    DISPLACEMENT_LOOKBACK,
    VALUE_AREA_PCT,
)


def detect_displacement(
    data: list[OHLC],
    displacement_multiplier: float = 1.5,
) -> bool:
    """Check for impulsive move: 3+ candles with direction + range expansion.

    Formula: N>=3 consecutive candles, (N-1)/N directional,
    total leg range >= multiplier × avg_range, closes near extremes for 2/3.

    Args:
        data: Recent OHLCV candles
        displacement_multiplier: Range expansion threshold (default 1.5x)
    """
    if len(data) < 23:
        return False

    N = 3
    recent = data[-N:]

    # Direction check: at least (N-1) of N must be directional
    bullish_count = sum(1 for c in recent if c.close > c.open)
    bearish_count = sum(1 for c in recent if c.close < c.open)

    is_bullish = bullish_count >= N - 1
    is_bearish = bearish_count >= N - 1

    if not (is_bullish or is_bearish):
        return False

    # Range expansion: leg range >= multiplier × avg_range
    prev_data = data[-(20 + N) : -N]
    if len(prev_data) < 10:
        return False

    avg_range = sum(d.high - d.low for d in prev_data) / len(prev_data)
    leg_range = max(c.high for c in recent) - min(c.low for c in recent)

    if leg_range < avg_range * displacement_multiplier:
        return False

    # Efficiency check: closes near extremes for at least 2/3 of candles
    efficient_count = 0
    for c in recent:
        rng = c.high - c.low
        if rng == 0:
            efficient_count += 1
            continue
        if is_bullish and c.close >= c.low + 0.75 * rng:
            efficient_count += 1
        elif is_bearish and c.close <= c.low + 0.25 * rng:
            efficient_count += 1

    if efficient_count < math.ceil(N * 2 / 3):
        return False

    return True


def detect_acceptance(data: list[OHLC], vah: float, val: float) -> bool:
    """Check for acceptance: 2+ consecutive closes outside VA."""
    if len(data) < 2:
        return False

    recent = data[-2:]

    # Check acceptance above VAH
    if all(c.close > vah for c in recent):
        return True

    # Check acceptance below VAL
    if all(c.close < val for c in recent):
        return True

    return False


def detect_displacement_leg(data: list[OHLC], displacement_multiplier: float = 1.5) -> dict:
    """Detect displacement and return leg profile data.

    Identifies the most recent directional leg (consecutive same-direction candles)
    and builds a volume profile for that leg with POC/VA calculations.

    Args:
        data: List of OHLC candles
        displacement_multiplier: Range expansion threshold for displacement detection

    Returns:
        Dictionary with has_displacement, profile, lvns, poc, vah, val, swing_delta
    """
    empty = {
        "has_displacement": False,
        "profile": [],
        "lvns": [],
        "poc": 0.0,
        "vah": 0.0,
        "val": 0.0,
        "swing_delta": 0.0,
    }
    if len(data) < 5:
        return empty

    # Find the most recent directional leg: consecutive candles from end
    # that share the same direction (bull or bear)
    last = data[-1]
    is_bull = last.close >= last.open
    leg_candles = [last]
    opposite_tolerance = 1  # allow 1 reversal candle within leg
    opposite_count = 0
    for i in range(len(data) - 2, max(len(data) - DISPLACEMENT_LOOKBACK, -1), -1):
        c = data[i]
        if (c.close >= c.open) == is_bull:
            leg_candles.insert(0, c)
            opposite_count = 0
        else:
            opposite_count += 1
            if opposite_count > opposite_tolerance:
                break
            leg_candles.insert(0, c)  # include the reversal candle

    if len(leg_candles) < 2:
        return empty

    # Import here to avoid circular dependency
    from app.domain.services.volume_profile import create_profile
    from app.domain.services.lvn_detector import find_lvns as _find_lvns_extracted

    is_disp = detect_displacement(data, displacement_multiplier)
    leg_profile = create_profile(leg_candles, buckets=DELTA_PROFILE_BUCKETS)
    if len(leg_profile) < 3:
        return {
            "has_displacement": is_disp,
            "profile": leg_profile,
            "lvns": [],
            "poc": 0.0,
            "vah": 0.0,
            "val": 0.0,
            "swing_delta": sum(c.delta for c in leg_candles),
        }

    # Find LVNs for the leg profile
    leg_lvns = [lvn.price for lvn in _find_lvns_extracted(
        leg_profile,
        lvn_threshold=0.15,
        smoothing_window=3,
        lvn_percentile=0.25,
        min_separation=3,
    )]

    # POC — VWAP tie-break
    max_vol = max(p.volume for p in leg_profile)
    poc_candidates = [i for i, p in enumerate(leg_profile) if p.volume == max_vol]

    # Local Leg VWAP for tie-break
    leg_vol = sum(c.volume for c in leg_candles)
    leg_vwap = (
        sum(c.close * c.volume for c in leg_candles) / leg_vol
        if leg_vol > 0
        else leg_candles[-1].close
    )

    poc_idx = min(
        poc_candidates, key=lambda i: abs(leg_profile[i].price - leg_vwap)
    )
    leg_poc = leg_profile[poc_idx].price

    # Value Area (70%) — CME two-row pairs method
    total_volume = sum(p.volume for p in leg_profile)
    target_volume = total_volume * VALUE_AREA_PCT
    current_volume = max_vol
    up_idx, down_idx = poc_idx, poc_idx
    while current_volume < target_volume:
        up_pair = 0.0
        up_count = 0
        for k in range(1, 3):
            if up_idx + k < len(leg_profile):
                up_pair += leg_profile[up_idx + k].volume
                up_count += 1
        down_pair = 0.0
        down_count = 0
        for k in range(1, 3):
            if down_idx - k >= 0:
                down_pair += leg_profile[down_idx - k].volume
                down_count += 1
        if not up_count and not down_count:
            break
        if up_count and (not down_count or up_pair >= down_pair):
            for k in range(1, up_count + 1):
                if up_idx + 1 < len(leg_profile):
                    up_idx += 1
                    current_volume += leg_profile[up_idx].volume
        elif down_count:
            for k in range(1, down_count + 1):
                if down_idx - 1 >= 0:
                    down_idx -= 1
                    current_volume += leg_profile[down_idx].volume

    step = (
        leg_profile[1].price - leg_profile[0].price if len(leg_profile) > 1 else 0
    )
    half_step = step / 2
    leg_vah = leg_profile[up_idx].price + half_step
    leg_val = leg_profile[down_idx].price - half_step

    return {
        "has_displacement": is_disp,
        "profile": leg_profile,
        "lvns": leg_lvns,
        "poc": leg_poc,
        "vah": leg_vah,
        "val": leg_val,
        "swing_delta": sum(c.delta for c in leg_candles),
    }