"""
Replay Types - Data structures for market data replay.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class ReplayEvent:
    """Single replay event containing candle or tick data."""
    timestamp: datetime
    symbol: str
    candle: Optional[dict] = None
    tick: Optional[dict] = None
    sequence: int = 0


@dataclass
class ReplayConfig:
    """Configuration for replay engine."""
    speed: float = 1.0
    from_date: str = ""
    to_date: str = ""
    timeframe: str = "5m"
    symbols: List[str] = field(default_factory=list)
    
    @property
    def is_valid(self) -> bool:
        """Check if config is valid."""
        return bool(
            self.from_date and
            self.to_date and
            self.timeframe and
            self.symbols and
            self.speed > 0
        )
