"""Volume Profile Engine."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

from brokersv2.analytics.profile.events import (
    VolumeProfile,
    VolumeProfileLevel,
)


class VolumeProfileEngine:
    """
    Build and analyze volume profiles.
    
    Features:
    - Volume at each price level
    - Point of Control (POC)
    - Value Area High/Low (VAH/VAL)
    - VWAP calculation
    """

    def __init__(self, symbol: str):
        self.symbol = symbol
        self._levels: Dict[float, VolumeProfileLevel] = {}

    @property
    def level_count(self) -> int:
        """Number of price levels."""
        return len(self._levels)

    @property
    def total_volume(self) -> float:
        """Total volume across all levels."""
        return sum(level.volume for level in self._levels.values())

    @property
    def profile_range(self) -> float:
        """Price range of profile."""
        if not self._levels:
            return 0.0
        prices = list(self._levels.keys())
        return max(prices) - min(prices)

    def get_level(self, price: float) -> Optional[VolumeProfileLevel]:
        """Get volume level at price."""
        return self._levels.get(price)

    def get_volume_at_price(self, price: float) -> float:
        """Get volume at specific price."""
        level = self._levels.get(price)
        return level.volume if level else 0.0

    def get_poc(self) -> Optional[float]:
        """Get Point of Control (price with highest volume)."""
        if not self._levels:
            return None
        
        max_volume = 0
        poc_price = None
        
        for price, level in self._levels.items():
            if level.volume > max_volume:
                max_volume = level.volume
                poc_price = price
        
        return poc_price

    def get_value_area(self, percentage: float = 70.0) -> tuple:
        """
        Get Value Area High and Low.
        
        Args:
            percentage: Percentage of volume to include (default 70%)
            
        Returns:
            Tuple of (VAH, VAL) prices
        """
        if not self._levels:
            return (0.0, 0.0)
        
        # Sort levels by price
        sorted_levels = sorted(self._levels.values(), key=lambda x: x.price)
        target_volume = self.total_volume * (percentage / 100.0)
        
        # Start from POC and expand outward
        poc = self.get_poc()
        if poc is None:
            return (0.0, 0.0)
        
        # Simple approach: find range that contains target volume
        cumulative = 0.0
        vah = max(self._levels.keys())
        val = min(self._levels.keys())
        
        for level in sorted_levels:
            cumulative += level.volume
            if cumulative >= target_volume:
                vah = level.price
                break
        
        cumulative = 0.0
        for level in reversed(sorted_levels):
            cumulative += level.volume
            if cumulative >= target_volume:
                val = level.price
                break
        
        return (vah, val)

    def get_vwap(self) -> Optional[float]:
        """Get Volume Weighted Average Price."""
        if self.total_volume == 0:
            return None
        
        total_value = sum(level.price * level.volume for level in self._levels.values())
        return total_value / self.total_volume

    def add_volume(
        self,
        price: float,
        volume: float,
        buy_volume: float = 0.0,
        sell_volume: float = 0.0,
    ) -> None:
        """
        Add volume at price level.
        
        Args:
            price: Price level
            volume: Total volume
            buy_volume: Buy volume
            sell_volume: Sell volume
        """
        if price in self._levels:
            existing = self._levels[price]
            self._levels[price] = VolumeProfileLevel(
                price=price,
                volume=existing.volume + volume,
                buy_volume=existing.buy_volume + buy_volume,
                sell_volume=existing.sell_volume + sell_volume,
            )
        else:
            self._levels[price] = VolumeProfileLevel(
                price=price,
                volume=volume,
                buy_volume=buy_volume,
                sell_volume=sell_volume,
            )

    def build_profile(self, session_date: Optional[datetime] = None) -> VolumeProfile:
        """Build complete volume profile."""
        if session_date is None:
            session_date = datetime.now()
        
        levels = sorted(self._levels.values(), key=lambda x: x.price)
        poc = self.get_poc() or 0.0
        vah, val = self.get_value_area()
        
        return VolumeProfile(
            symbol=self.symbol,
            session_date=session_date,
            levels=levels,
            poc_price=poc,
            vah_price=vah,
            val_price=val,
            total_volume=self.total_volume,
        )

    def reset(self) -> None:
        """Reset engine."""
        self._levels.clear()
