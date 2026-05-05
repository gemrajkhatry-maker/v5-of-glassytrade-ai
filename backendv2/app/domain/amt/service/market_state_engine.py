"""market state engine — AMT analysis service.

Based on amt_docs FR-04 (2-state model).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MarketState(str, Enum):
    BALANCED = "BALANCED"
    IMBALANCED = "IMBALANCED"


class MarketZone(str, Enum):
    NEAR_VAH = "NEAR_VAH"
    NEAR_VAL = "NEAR_VAL"
    NEAR_POC = "NEAR_POC"
    OUTSIDE_VA = "OUTSIDE_VA"


@dataclass(frozen=True)
class MarketStateResult:
    """Market state result."""
    state: MarketState
    zone: MarketZone
    confidence: float
    is_extreme: bool
    va_high: float
    va_low: float
    poc: float


def detect_market_state(
    price: float,
    vp_levels: dict,
    leg_profile: dict | None = None,
    vwap: float = 0,
    vwap_stddev: float = 0,
) -> MarketStateResult:
    """
    Detect market state based on price location and volume profile.
    
    Args:
        price: Current price
        vp_levels: Dict with 'vah', 'val', 'poc'
        leg_profile: Active leg profile (optional)
        vwap: Volume Weighted Average Price
        vwap_stddev: VWAP standard deviation
    
    Returns:
        MarketStateResult with state classification
    """
    vah = vp_levels.get("vah", 0)
    val = vp_levels.get("val", 0)
    poc = vp_levels.get("poc", 0)

    if vah == 0 or val == 0 or poc == 0:
        return MarketStateResult(
            state=MarketState.BALANCED,
            zone=MarketZone.NEAR_POC,
            confidence=0.5,
            is_extreme=False,
            va_high=vah,
            va_low=val,
            poc=poc,
        )

    # Use leg profile if active
    if leg_profile and leg_profile.get("active"):
        vah = leg_profile.get("vah", vah)
        val = leg_profile.get("val", val)
        poc = leg_profile.get("poc", poc)

    # Determine zone
    va_mid = (vah + val) / 2
    
    # Upper portion of VA
    if price > vah:
        zone = MarketZone.OUTSIDE_VA
        state = MarketState.IMBALANCED
    # Lower portion of VA
    elif price < val:
        zone = MarketZone.OUTSIDE_VA
        state = MarketState.IMBALANCED
    # Upper half inside VA
    elif price > va_mid:
        zone = MarketZone.NEAR_VAH
        state = MarketState.BALANCED
    # Lower half inside VA
    elif price < va_mid:
        zone = MarketZone.NEAR_VAL
        state = MarketState.BALANCED
    # Near POC (exact mid)
    else:
        zone = MarketZone.NEAR_POC
        state = MarketState.BALANCED

    # Check for extreme deviation
    is_extreme = False
    if vwap > 0 and vwap_stddev > 0:
        deviation = abs(price - vwap) / vwap_stddev
        is_extreme = deviation >= 3.0

    # Determine confidence
    confidence = 0.85 if state == MarketState.IMBALANCED else 0.80

    return MarketStateResult(
        state=state,
        zone=zone,
        confidence=confidence,
        is_extreme=is_extreme,
        va_high=vah,
        va_low=val,
        poc=poc,
    )

