"""Tick size utilities — centralized rounding and tick calculations.

All price rounding, tick distance calculations, and tick-based
quantization should use these functions instead of inline math.
"""

from __future__ import annotations

import math


def round_to_tick(price: float, tick_size: float) -> float:
    """Round a price to the nearest tick boundary.

    Args:
        price: Raw price to round.
        tick_size: Instrument tick size (e.g., 0.05 for NIFTY options).

    Returns:
        Price rounded to nearest tick.

    Examples:
        >>> round_to_tick(100.07, 0.05)
        100.05
        >>> round_to_tick(100.08, 0.05)
        100.1
        >>> round_to_tick(6003.3, 1.0)
        6003.0
    """
    if tick_size <= 0:
        return price
    return round(price / tick_size) * tick_size


def round_up_to_tick(price: float, tick_size: float) -> float:
    """Round a price UP to the next tick boundary.

    Used for: SL for SHORT positions, TP for LONG positions.
    """
    if tick_size <= 0:
        return price
    return math.ceil(price / tick_size) * tick_size


def round_down_to_tick(price: float, tick_size: float) -> float:
    """Round a price DOWN to the next tick boundary.

    Used for: SL for LONG positions, TP for SHORT positions.
    """
    if tick_size <= 0:
        return price
    return math.floor(price / tick_size) * tick_size


def ticks_between(price1: float, price2: float, tick_size: float) -> float:
    """Calculate the number of ticks between two prices.

    Returns:
        Absolute tick distance (always positive).
    """
    if tick_size <= 0:
        return 0.0
    return abs(price1 - price2) / tick_size


def tick_decimals(tick_size: float) -> int:
    """Get the number of decimal places for a tick size.

    Examples:
        >>> tick_decimals(0.05)
        2
        >>> tick_decimals(1.0)
        0
        >>> tick_decimals(0.1)
        1
    """
    if tick_size >= 1:
        return 0
    s = f"{tick_size:.10f}".rstrip("0")
    if "." in s:
        return len(s.split(".")[1])
    return 0
