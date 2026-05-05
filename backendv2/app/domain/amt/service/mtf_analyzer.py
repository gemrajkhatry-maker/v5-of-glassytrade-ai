"""mtf analyzer — AMT analysis service.

Based on Phase 5 in amt_docs (Multi-Timeframe):
- Daily/hourly alignment detection
- Higher timeframe level tracking
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MTFAlignment(str, Enum):
    ALIGNED_BULLISH = "ALIGNED_BULLISH"
    ALIGNED_BEARISH = "ALIGNED_BEARISH"
    DIVERGENT = "DIVERGENT"
    NONE = "NONE"


@dataclass(frozen=True)
class MTFState:
    """Multi-timeframe analysis state."""
    daily_poc: float
    daily_vah: float
    daily_val: float
    hourly_poc: float
    hourly_vah: float
    hourly_val: float
    alignment: MTFAlignment


class MultiTimeframeAMTAnalyzer:
    """Analyze multi-timeframe AMT relationships."""

    def __init__(self):
        self._daily_state: MTFState | None = None
        self._hourly_state: MTFState | None = None

    def analyze(
        self,
        daily_profile: dict,
        hourly_profile: dict,
    ) -> MTFState:
        """
        Analyze daily and hourly alignment.
        
        Args:
            daily_profile: Daily volume profile levels
            hourly_profile: Hourly volume profile levels
        
        Returns:
            MTFState with alignment information
        """
        daily_poc = daily_profile.get("poc", 0)
        daily_vah = daily_profile.get("vah", 0)
        daily_val = daily_profile.get("val", 0)
        
        hourly_poc = hourly_profile.get("poc", 0)
        hourly_vah = hourly_profile.get("vah", 0)
        hourly_val = hourly_profile.get("val", 0)

        # Determine alignment
        alignment = self._determine_alignment(
            daily_poc, daily_vah, daily_val,
            hourly_poc, hourly_vah, hourly_val
        )

        state = MTFState(
            daily_poc=daily_poc,
            daily_vah=daily_vah,
            daily_val=daily_val,
            hourly_poc=hourly_poc,
            hourly_vah=hourly_vah,
            hourly_val=hourly_val,
            alignment=alignment,
        )

        self._daily_state = state
        self._hourly_state = state
        return state

    def _determine_alignment(
        self,
        daily_poc: float, daily_vah: float, daily_val: float,
        hourly_poc: float, hourly_vah: float, hourly_val: float,
    ) -> MTFAlignment:
        """Determine if daily and hourly are aligned."""
        # Check for zero values first
        if daily_poc == 0 or hourly_poc == 0:
            return MTFAlignment.NONE
        
        # Calculate VA mid for each timeframe
        daily_mid = (daily_vah + daily_val) / 2
        hourly_mid = (hourly_vah + hourly_val) / 2
        
        # Bullish: POC above VA mid
        daily_bullish = daily_poc > daily_mid
        hourly_bullish = hourly_poc > hourly_mid
        
        # Bearish: POC below VA mid
        daily_bearish = daily_poc < daily_mid
        hourly_bearish = hourly_poc < hourly_mid
        
        # Both bullish
        if daily_bullish and hourly_bullish:
            return MTFAlignment.ALIGNED_BULLISH
        
        # Both bearish
        if daily_bearish and hourly_bearish:
            return MTFAlignment.ALIGNED_BEARISH
        
        # Divergent
        return MTFAlignment.DIVERGENT

