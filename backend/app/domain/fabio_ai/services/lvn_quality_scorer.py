"""LVN Quality Scorer — prioritize LVN levels per Fabio AMT spec (FR-02-10).

Scoring formula:
  quality = thinness_score × 0.60 + proximity_score × 0.40

  thinness_score: How thin is this LVN relative to neighbors (0-1)
    - Lower LVN volume relative to neighbors = higher score
    - Formula: 1.0 - (lvn_volume / max(neighbor_avg, 1))

  proximity_score: How close is this LVN to current price (0-1)
    - Closer = higher score
    - Formula: 1.0 - (distance / max_distance_in_range)

Higher quality = better LVN for entry targeting.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.domain.trading.models.value_objects import VolumeProfileLevel

logger = logging.getLogger(__name__)


@dataclass
class LVNQuality:
    """Quality score for a single LVN level."""

    price: float
    quality: float  # 0.0-1.0 (higher = better)
    thinness: float  # 0.0-1.0
    proximity: float  # 0.0-1.0
    volume: float  # Raw volume at this level


def score_lvn_quality(
    lvn_price: float,
    profile: list[VolumeProfileLevel],
    current_price: float,
    price_range: float,
) -> LVNQuality | None:
    """Score LVN quality using thinness + proximity (FR-02-10).

    Args:
        lvn_price: The LVN price level to score.
        profile: Full volume profile.
        current_price: Current market price.
        price_range: Full price range (vah - val or similar).

    Returns:
        LVNQuality with scores, or None if profile is invalid.
    """
    if not profile or price_range <= 0:
        return None

    # Find the LVN bucket (closest match)
    tick = profile[1].price - profile[0].price if len(profile) > 1 else 0.05
    lvn_idx = None
    min_diff = float("inf")
    for i, p in enumerate(profile):
        diff = abs(p.price - lvn_price)
        if diff <= tick and diff < min_diff:
            lvn_idx = i
            min_diff = diff
    if lvn_idx is None:
        return None

    lvn_vol = profile[lvn_idx].volume

    # Thinness score: how thin vs neighbors
    # Look at ±2 buckets around LVN
    neighbor_vols = []
    for offset in range(-2, 3):
        idx = lvn_idx + offset
        if 0 <= idx < len(profile) and idx != lvn_idx:
            neighbor_vols.append(profile[idx].volume)

    if neighbor_vols:
        neighbor_avg = sum(neighbor_vols) / len(neighbor_vols)
        if neighbor_avg > 0:
            thinness = max(0.0, 1.0 - (lvn_vol / neighbor_avg))
        else:
            thinness = 1.0
    else:
        thinness = 0.5

    # Proximity score: closer to current price = higher
    distance = abs(lvn_price - current_price)
    proximity = max(0.0, 1.0 - (distance / price_range))

    # Combined quality
    quality = thinness * 0.60 + proximity * 0.40

    return LVNQuality(
        price=lvn_price,
        quality=quality,
        thinness=thinness,
        proximity=proximity,
        volume=lvn_vol,
    )


def rank_lvns(
    lvns: list[float],
    profile: list[VolumeProfileLevel],
    current_price: float,
    vah: float,
    val: float,
) -> list[LVNQuality]:
    """Rank all LVNs by quality. Best first."""
    price_range = max(vah - val, 1e-9)
    scored = []
    for lvn in lvns:
        q = score_lvn_quality(lvn, profile, current_price, price_range)
        if q is not None:
            scored.append(q)
    scored.sort(key=lambda x: x.quality, reverse=True)
    return scored
