"""profile classifier — AMT analysis service.

Based on amt_docs section 2.2 (Profile shapes):
- P shape: Volume concentrated at top (resistance)
- b shape: Volume concentrated at bottom (support)
- D shape: Normal bell curve distribution
- B shape: Bimodal (two peaks)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ProfileShape(str, Enum):
    P = "P"  # Top heavy (resistance)
    B = "b"  # Bottom heavy (support)
    D = "D"  # Bell curve (normal)
    BIMODAL = "B"  # Two peaks


@dataclass(frozen=True)
class POCMigration:
    """POC migration tracking."""
    migration_type: str  # "POC_RISING_BULLISH", "POC_FALLING_BEARISH", "NONE"
    poc_vs_price: str  # "ALIGNED", "DIVERGENT", "NONE"


@dataclass(frozen=True)
class ProfileClassification:
    """Complete profile classification result."""
    shape: ProfileShape
    poc_migration: POCMigration


def classify_shape(levels: list) -> ProfileShape:
    """
    Classify volume profile shape.
    
    P: Volume concentrated at top (above median price)
    b: Volume concentrated at bottom (below median price)
    D: Normal distribution around POC
    B: Two distinct peaks
    """
    if not levels or len(levels) < 3:
        return ProfileShape.D

    total_volume = sum(getattr(l, 'volume', 0) for l in levels)
    if total_volume == 0:
        return ProfileShape.D

    # Calculate median price
    prices = [getattr(l, 'price', 0) for l in levels]
    median_price = sum(prices) / len(prices)

    # Calculate volume above/below median
    vol_above = sum(getattr(l, 'volume', 0) for l in levels if getattr(l, 'price', 0) > median_price)
    vol_below = sum(getattr(l, 'volume', 0) for l in levels if getattr(l, 'price', 0) < median_price)

    ratio = vol_above / total_volume if total_volume > 0 else 0.5

    if ratio > 0.6:
        return ProfileShape.P  # Top heavy
    elif ratio < 0.4:
        return ProfileShape.B  # Bottom heavy

    return ProfileShape.D


def track_poc_migration(
    levels: list,
    prev_poc: float | None = None,
    current_price: float | None = None,
) -> POCMigration:
    """
    Track POC migration and divergence from price.
    
    Returns:
        POCMigration with migration type and price relationship
    """
    # Find current POC (level with max volume)
    if not levels:
        return POCMigration(migration_type="NONE", poc_vs_price="NONE")

    current_poc = max(levels, key=lambda l: getattr(l, 'volume', 0)).price if levels else 0

    # Determine migration type
    migration_type = "NONE"
    if prev_poc is not None:
        if current_poc > prev_poc:
            migration_type = "POC_RISING_BULLISH"
        elif current_poc < prev_poc:
            migration_type = "POC_FALLING_BEARISH"

    # Check divergence
    poc_vs_price = "NONE"
    if current_price is not None:
        if current_poc < current_price * 0.98:
            poc_vs_price = "ALIGNED"  # Price above POC, typical bullish
        elif current_poc > current_price * 1.02:
            poc_vs_price = "DIVERGENT"  # Price below POC could diverge
        else:
            poc_vs_price = "ALIGNED"

    return POCMigration(
        migration_type=migration_type,
        poc_vs_price=poc_vs_price,
    )


def classify_profile(
    levels: list,
    prev_poc: float | None = None,
    current_price: float | None = None,
) -> ProfileClassification:
    """
    Complete profile classification.
    
    Args:
        levels: Volume profile levels
        prev_poc: Previous POC for migration tracking
        current_price: Current price for divergence detection
    
    Returns:
        ProfileClassification with shape and POC migration
    """
    shape = classify_shape(levels)
    poc_migration = track_poc_migration(levels, prev_poc, current_price)

    return ProfileClassification(
        shape=shape,
        poc_migration=poc_migration,
    )

