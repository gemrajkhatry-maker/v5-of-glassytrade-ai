"""Volume Profile Service - consolidated profile operations.

Extracted from AMTAnalyzer to follow Single Responsibility Principle.
Handles profile creation, LVN/HVN detection, and persistence filtering.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import VolumeProfileLevel

logger = logging.getLogger(__name__)

from app.domain.services.lvn_detector import (
    find_lvns as _find_lvns_extracted,
    find_hvns as _find_hvns_extracted,
    LVNPersistenceTracker,
)
from app.domain.services.volume_profile import IncrementalVolumeProfile, create_profile
from app.domain.constants import (
    LVN_MIN_PERSISTENCE_BARS,
    LVN_REMOVAL_THRESHOLD,
    LVN_PERCENTILE,
    LVN_MIN_SEPARATION,
    HVN_PERCENTILE,
    HVN_MIN_SEPARATION,
    VALUE_AREA_PCT,
)


from dataclasses import dataclass


@dataclass
class VolumeProfileConfig:
    """Configuration for volume profile detection."""
    
    LVN_THRESHOLD: float = 0.15  # < 15% of mean
    HVN_THRESHOLD: float = 2.0   # > 200% of mean
    LVN_SMOOTHING: int = 3


class VolumeProfileService:
    """Consolidated volume profile operations.
    
    Extracted from AMTAnalyzer to follow Single Responsibility Principle.
    Handles profile creation, LVN/HVN detection with persistence filtering.
    """
    
    def __init__(self, config: VolumeProfileConfig | None = None) -> None:
        self.config = config or VolumeProfileConfig()
        self._lvn_tracker = LVNPersistenceTracker(
            min_bars=LVN_MIN_PERSISTENCE_BARS,
            removal_threshold=LVN_REMOVAL_THRESHOLD,
        )
    
    def find_lvns(self, profile: list["VolumeProfileLevel"]) -> list[float]:
        """Find Low Volume Nodes in profile.
        
        Args:
            profile: Volume profile levels
            
        Returns:
            List of LVN prices (filtered for persistence)
        """
        levels = _find_lvns_extracted(
            profile,
            lvn_threshold=self.config.LVN_THRESHOLD,
            smoothing_window=self.config.LVN_SMOOTHING,
            lvn_percentile=LVN_PERCENTILE,
            min_separation=LVN_MIN_SEPARATION,
        )
        
        # Apply persistence filter
        raw_lvns = [lvn.price for lvn in levels]
        return self._lvn_tracker.update(raw_lvns, profile)
    
    def find_hvns(self, profile: list["VolumeProfileLevel"]) -> list[float]:
        """Find High Volume Nodes in profile."""
        levels = _find_hvns_extracted(
            profile,
            hvn_threshold=self.config.HVN_THRESHOLD,
            smoothing_window=self.config.LVN_SMOOTHING,
            hvn_percentile=HVN_PERCENTILE,
            min_separation=HVN_MIN_SEPARATION,
        )
        return [hvn.price for hvn in levels]
    
    def reset_lvn_tracker(self) -> None:
        """Reset LVN persistence tracker (new session)."""
        self._lvn_tracker.reset()