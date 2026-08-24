"""Position sizing for agent pipeline.

Extracted from agent_pipeline.py for separation of concerns.
Kelly criterion and SL/TP adjustments.
"""

from __future__ import annotations

import math


def kelly_size(probability: float, win_loss_ratio: float = 1.5) -> float:
    """Calculate Kelly optimal position size.

    K = p - q/r where:
    - p = win probability
    - q = loss probability (1-p)
    - r = win/loss ratio

    Args:
        probability: Win probability
        win_loss_ratio: Average win / average loss ratio

    Returns:
        Fraction of capital [0, 1]
    """
    if probability <= 0 or probability >= 1:
        return 0.0
    if win_loss_ratio <= 0:
        win_loss_ratio = 1.0

    q = 1 - probability
    kelly = probability - q / win_loss_ratio
    
    # Cap at 25% for safety
    return max(0, min(kelly, 0.25))


def adjust_sl_tp(
    entry_price: float,
    direction: str,
    sl_distance: float,
    tp_distance: float,
    volatility: float,
) -> tuple[float, float, float, float]:
    """Adjust stop loss and take profit based on volatility.

    Args:
        entry_price: Entry price
        direction: LONG or SHORT
        sl_distance: Base SL distance
        tp_distance: Base TP distance
        volatility: Market volatility measure

    Returns:
        Tuple of (sl_price, tp_price, sl_adjust, tp_adjust)
    """
    # Adjust distances based on volatility
    vol_mult = max(1.0, volatility * 2)
    
    if direction == "LONG":
        sl_price = entry_price - sl_distance * vol_mult
        tp_price = entry_price + tp_distance / vol_mult
    else:
        sl_price = entry_price + sl_distance * vol_mult
        tp_price = entry_price - tp_distance / vol_mult

    return sl_price, tp_price, vol_mult, 1.0 / vol_mult