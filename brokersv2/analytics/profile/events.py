"""Market Profile events and data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional


class ProfileType(Enum):
    """Type of market profile."""
    TPO = "tpo"
    VOLUME = "volume"
    SESSION = "session"
    ROLLING = "rolling"


class VolumeNodeType(Enum):
    """Volume node type."""
    HVN = "hvn"  # High Volume Node
    LVN = "lvn"  # Low Volume Node


@dataclass(frozen=True)
class TPOLevel:
    """TPO data at single price level."""
    price: float
    tpo_count: int
    tpo_letters: List[str]  # e.g., ['A', 'B', 'C']
    first_tpo_time: Optional[datetime] = None
    last_tpo_time: Optional[datetime] = None


@dataclass(frozen=True)
class VolumeProfileLevel:
    """Volume profile at single price level."""
    price: float
    volume: float
    buy_volume: float = 0.0
    sell_volume: float = 0.0


@dataclass(frozen=True)
class TPOProfile:
    """Complete TPO profile."""
    symbol: str
    session_date: datetime
    levels: List[TPOLevel]
    poc_price: float = 0.0  # Point of Control
    vah_price: float = 0.0  # Value Area High
    val_price: float = 0.0  # Value Area Low
    total_tpos: int = 0
    value_area_percentage: float = 70.0  # Standard 70%

    @property
    def level_count(self) -> int:
        return len(self.levels)

    @property
    def profile_range(self) -> float:
        """Range from high to low price."""
        if not self.levels:
            return 0.0
        prices = [level.price for level in self.levels]
        return max(prices) - min(prices)


@dataclass(frozen=True)
class VolumeProfile:
    """Complete volume profile."""
    symbol: str
    session_date: datetime
    levels: List[VolumeProfileLevel]
    poc_price: float = 0.0
    vah_price: float = 0.0
    val_price: float = 0.0
    total_volume: float = 0.0
    value_area_percentage: float = 70.0

    @property
    def level_count(self) -> int:
        return len(self.levels)

    @property
    def profile_range(self) -> float:
        if not self.levels:
            return 0.0
        prices = [level.price for level in self.levels]
        return max(prices) - min(prices)


@dataclass(frozen=True)
class VolumeNode:
    """High or Low Volume Node."""
    node_type: VolumeNodeType
    price: float
    volume: float
    strength: float  # Relative strength 0-1


@dataclass(frozen=True)
class ProfileEvent:
    """Market profile event."""
    event_type: ProfileType
    symbol: str
    timestamp: datetime
    data: Dict = field(default_factory=dict)
