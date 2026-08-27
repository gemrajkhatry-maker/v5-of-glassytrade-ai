"""Displacement Detector — impulsive move + acceptance/rejection detection.

Extracted from amt_analyzer.py for SRP compliance.

Detects:
  - Displacement: 3+ consecutive directional candles with range expansion
  - Acceptance: 2+ consecutive closes outside VA (above VAH or below VAL)
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quant.contracts.value_objects import OHLC


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