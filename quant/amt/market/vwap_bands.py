"""Unified VWAP band computation — shared between AMT analyzer and auction coordinator.

Ponytail: stdlib-only, one function, no new dependencies. Reuses the 2σ
formula both components already implement, just in one place.
"""
import math
from typing import Optional


def compute_vwap_bands(
    typical_price: float,
    vwap: float,
    volume: float,
    volume_total: float,
    sigma: float = 2.0,
) -> dict[str, float]:
    """Compute 2σ VWAP bands for triple-A edge anti-climax guard.

    Formula: band = vwap ± σ * typical_price * sqrt(1 - volume/volume_total)
    This matches the AMT analyzer's 2σ estimation used in gate_triple_a_edge().

    Args:
        typical_price: typical price measure (close, or (high+low+close)/3)
        vwap: accumulated volume-weighted average price
        volume: current candle volume
        volume_total: cumulative volume up to this point
        sigma: number of standard deviations (default 2.0 for anti-climax guard)

    Returns:
        dict with "upper_2" and "lower_2" keys
    """
    if volume_total <= 0 or volume < 0:
        return {"upper_2": 0.0, "lower_2": 0.0}

    # Use close as typical_price proxy when nothing else available
    tp = typical_price if typical_price and typical_price > 0 else abs(vwap)

    # Volume-proportional std dev: when volume is full, std dev → 0
    # when volume is zero, std dev → max (price * 1.0)
    vol_ratio = volume / volume_total if volume_total > 0 else 0
    std_dev = abs(tp) * math.sqrt(max(0, 1 - vol_ratio))

    upper = vwap + sigma * std_dev
    lower = vwap - sigma * std_dev

    return {"upper_2": upper, "lower_2": lower}
