"""LVN/HVN detection — Low and High Volume Nodes.

Based on amt_docs and Fabio spec:
- LVN: Volume < 15% of mean (thin volume areas)
- HVN: Volume > 200% of mean (thick volume areas)
Uses percentile-based detection with smoothing and clustering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

from app.domain.amt.model.amt_models import VolumeProfileLevel


@dataclass(frozen=True)
class LVNLevel:
    """A detected Low Volume Node."""
    price: float
    strength: float  # 0 (weakest) to 1 (strongest)
    bucket_index: int


@dataclass(frozen=True)
class HVNLevel:
    """A detected High Volume Node (support/resistance zone)."""
    price: float
    strength: float  # Normalized: volume / mean_volume
    bucket_index: int


@dataclass
class VolumeNode:
    """Generic volume node (LVN or HVN)."""
    price: float
    volume: float
    node_type: str  # "LVN" or "HVN"
    strength: float
    bucket_index: int = 0


def _smooth_array(data: list[float], window: int = 3) -> list[float]:
    """Centered simple moving average smoothing."""
    if window <= 1 or len(data) < 3:
        return list(data)
    half = window // 2
    result = []
    for i in range(len(data)):
        start = max(0, i - half)
        end = min(len(data), i + half + 1)
        result.append(sum(data[start:end]) / (end - start))
    return result


def _percentile(values: list[float], pct: float) -> float:
    """Return the pct-th percentile (0-100) using linear interpolation."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    rank = pct / 100.0 * (n - 1)
    lo = int(rank)
    hi = lo + 1
    if hi >= n:
        return sorted_vals[-1]
    frac = rank - lo
    return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])


def detect_lvn_hvn(
    levels: tuple[VolumeProfileLevel, ...],
    lvn_threshold: float = 0.15,   # < 15% of mean (Fabio spec)
    hvn_threshold: float = 2.0,    # > 200% of mean (Fabio spec)
    min_separation: int = 3,       # Minimum index separation between nodes
    smoothing_window: int = 3,
) -> tuple[list[LVNLevel], list[HVNLevel]]:
    """
    Detect Low and High Volume Nodes from volume profile levels.

    Uses percentile-based detection with smoothing and clustering.

    Args:
        levels: Volume profile levels
        lvn_threshold: Ratio threshold for LVN (default 0.15 = 15%)
        hvn_threshold: Ratio threshold for HVN (default 2.0 = 200%)
        min_separation: Minimum index separation between nodes
        smoothing_window: Smoothing window size

    Returns:
        Tuple of (lvns, hvns) lists
    """
    if not levels:
        return ([], [])

    volumes = [level.volume for level in levels]
    mean_volume = sum(volumes) / len(volumes) if volumes else 0

    if mean_volume == 0:
        return ([], [])

    lvns: list[LVNLevel] = []
    hvns: list[HVNLevel] = []
    last_lvn_idx = -min_separation - 1
    last_hvn_idx = -min_separation - 1

    for i, level in enumerate(levels):
        vol_ratio = level.volume / mean_volume

        # LVN detection
        if vol_ratio < lvn_threshold:
            if i - last_lvn_idx > min_separation:
                strength = 1.0 - (vol_ratio / lvn_threshold)
                lvns.append(LVNLevel(
                    price=level.price,
                    strength=min(1.0, max(0.0, strength)),
                    bucket_index=i,
                ))
                last_lvn_idx = i

        # HVN detection
        elif vol_ratio > hvn_threshold:
            if i - last_hvn_idx > min_separation:
                strength = min(3.0, vol_ratio / hvn_threshold)
                hvns.append(HVNLevel(
                    price=level.price,
                    strength=strength,
                    bucket_index=i,
                ))
                last_hvn_idx = i

    return (lvns, hvns)


def detect_lvn_play(
    levels: tuple[VolumeProfileLevel, ...],
    bars: list[dict],
    lvn_nodes: tuple[VolumeNode, ...],
) -> dict | None:
    """
    Detect LVN play pattern.

    LVN play: Price tests an LVN and gets a reaction (bounce or break with volume).

    Returns:
        Dictionary with LVN play info or None
    """
    if not lvn_nodes or len(bars) < 10:
        return None

    lvn_prices = {node.price for node in lvn_nodes}

    for i, bar in enumerate(bars[-10:]):
        bar_low = bar.get("low", 0)
        bar_high = bar.get("high", 0)

        for lvn_price in lvn_prices:
            if bar_low <= lvn_price <= bar_high:
                bar_idx = len(bars) - 10 + i
                if bar_idx < len(bars) - 1:
                    next_bar = bars[bar_idx + 1]
                    reaction = next_bar.get("close", 0) - bar.get("close", 0)
                    bar_range = bar_high - bar_low
                    if abs(reaction) > bar_range * 0.5:
                        return {
                            "lvn_price": lvn_price,
                            "reaction": "BULLISH" if reaction > 0 else "BEARISH",
                            "strength": abs(reaction) / bar_range if bar_range > 0 else 0,
                        }

    return None
