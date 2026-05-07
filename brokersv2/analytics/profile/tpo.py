"""TPO (Time Price Opportunity) Profile Engine."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from brokersv2.analytics.profile.events import (
    TPOLevel,
    TPOProfile,
)


class TPOProfileEngine:
    """
    Build and analyze TPO profiles.
    
    Features:
    - TPO letter assignment per 30-min period
    - Point of Control (POC)
    - Value Area calculation
    - Profile range tracking
    """

    TPO_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    def __init__(self, symbol: str):
        self.symbol = symbol
        self._levels: Dict[float, TPOLevel] = {}

    @property
    def level_count(self) -> int:
        """Number of price levels."""
        return len(self._levels)

    @property
    def total_tpos(self) -> int:
        """Total TPO count across all levels."""
        return sum(level.tpo_count for level in self._levels.values())

    @property
    def profile_range(self) -> float:
        """Price range of profile."""
        if not self._levels:
            return 0.0
        prices = list(self._levels.keys())
        return max(prices) - min(prices)

    def get_level(self, price: float) -> Optional[TPOLevel]:
        """Get TPO level at price."""
        return self._levels.get(price)

    def get_poc(self) -> Optional[float]:
        """Get Point of Control (price with most TPOs)."""
        if not self._levels:
            return None
        
        max_tpos = 0
        poc_price = None
        
        for price, level in self._levels.items():
            if level.tpo_count > max_tpos:
                max_tpos = level.tpo_count
                poc_price = price
        
        return poc_price

    def add_tpo(self, price: float, letter: str, timestamp: datetime) -> None:
        """
        Add TPO at price level.
        
        Args:
            price: Price level
            letter: TPO letter (A, B, C, etc.)
            timestamp: Time of TPO
        """
        if price not in self._levels:
            self._levels[price] = TPOLevel(
                price=price,
                tpo_count=0,
                tpo_letters=[],
                first_tpo_time=timestamp,
                last_tpo_time=timestamp,
            )
        
        level = self._levels[price]
        letters = list(level.tpo_letters)
        letters.append(letter)
        
        new_first = level.first_tpo_time
        if timestamp < new_first:
            new_first = timestamp
        
        new_last = level.last_tpo_time
        if timestamp > new_last:
            new_last = timestamp
        
        # Update with new immutable instance
        self._levels[price] = TPOLevel(
            price=price,
            tpo_count=level.tpo_count + 1,
            tpo_letters=letters,
            first_tpo_time=new_first,
            last_tpo_time=new_last,
        )

    def build_profile(self, session_date: Optional[datetime] = None) -> TPOProfile:
        """Build complete TPO profile."""
        if session_date is None:
            session_date = datetime.now()
        
        levels = sorted(self._levels.values(), key=lambda x: x.price, reverse=True)
        poc = self.get_poc() or 0.0
        
        return TPOProfile(
            symbol=self.symbol,
            session_date=session_date,
            levels=levels,
            poc_price=poc,
            total_tpos=self.total_tpos,
        )

    def reset(self) -> None:
        """Reset engine."""
        self._levels.clear()
