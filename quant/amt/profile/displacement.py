"""Displacement leg detection — extracted from AMTAnalyzer.

Single responsibility: detect directional displacement legs and compute
leg-level profile (POC, VAH, VAL, LVNs, swing delta).  No side effects.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from quant.amt.market.displacement import detect_displacement
from quant.amt.profile.volume_profile import create_profile
from quant.amt.profile.lvn import find_lvns as _find_lvns_raw
from quant.contracts.constants import (
    DISPLACEMENT_LOOKBACK, DELTA_PROFILE_BUCKETS, VALUE_AREA_PCT,
    LVN_PERCENTILE, LVN_MIN_SEPARATION,
)


def find_lvns(profile, config):
    """Thin wrapper — extracts prices from LVNLevel objects.
    Avoids circular import with analyzer.py."""
    levels = _find_lvns_raw(
        profile,
        lvn_threshold=config.LVN_THRESHOLD,
        smoothing_window=config.LVN_SMOOTHING,
        lvn_percentile=LVN_PERCENTILE,
        min_separation=LVN_MIN_SEPARATION,
    )
    return [l.price for l in levels]

if TYPE_CHECKING:
    from quant.contracts.value_objects import OHLC

logger = logging.getLogger(__name__)


def detect_displacement_leg(
    data: list[OHLC],
    config,
) -> dict:
    """Detect displacement and return leg profile data.

    Always builds a leg profile from the most recent directional move
    (consecutive same-direction candles from the end). The strict displacement
    flag is set when the move also meets range expansion criteria.
    """
    def _leg_result(*, has_displacement: bool, profile: list,
                    lvns: list, poc: float, vah: float, val: float,
                    swing_delta: float) -> dict:
        return {
            "has_displacement": has_displacement,
            "profile": profile,
            "lvns": lvns,
            "poc": poc,
            "vah": vah,
            "val": val,
            "swing_delta": swing_delta,
        }

    empty = _leg_result(has_displacement=False, profile=[], lvns=[],
                        poc=0.0, vah=0.0, val=0.0, swing_delta=0.0)
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

    is_disp = detect_displacement(data, config.DISPLACEMENT_MULTIPLIER)
    leg_profile = create_profile(leg_candles, buckets=DELTA_PROFILE_BUCKETS)
    if len(leg_profile) < 3:
        return _leg_result(
            has_displacement=is_disp, profile=leg_profile, lvns=[],
            poc=0.0, vah=0.0, val=0.0,
            swing_delta=sum(c.delta for c in leg_candles),
        )
    leg_lvns = find_lvns(leg_profile, config)

    # POC — VWAP tie-break (matches session logic)
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

    # Value Area (70%) — CME two-row pairs method (matches session logic)
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
    return _leg_result(
        has_displacement=is_disp,
        profile=leg_profile,
        lvns=leg_lvns,
        poc=leg_poc,
        vah=leg_vah,
        val=leg_val,
        swing_delta=sum(c.delta for c in leg_candles),
    )
