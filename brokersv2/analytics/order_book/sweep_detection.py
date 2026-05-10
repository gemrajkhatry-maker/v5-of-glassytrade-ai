"""Order Book Sweep Detection."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from brokersv2.analytics.order_book.events import PriceLevel

logger = logging.getLogger(__name__)


class SweepDirection(Enum):
    """Direction of sweep."""
    BID = "bid"
    ASK = "ask"


@dataclass(frozen=True)
class SweepEvent:
    """Detected sweep event."""
    timestamp: datetime
    symbol: str
    direction: SweepDirection
    levels_consumed: int
    total_volume_swept: int
    price_impact: float
    start_price: float
    end_price: float
    
    @property
    def is_bid_sweep(self) -> bool:
        """Check if this is a bid sweep."""
        return self.direction == SweepDirection.BID
    
    @property
    def is_ask_sweep(self) -> bool:
        """Check if this is an ask sweep."""
        return self.direction == SweepDirection.ASK


class SweepDetector:
    """
    Detects liquidity sweeps in order book.
    
    A sweep occurs when a large order consumes multiple price levels,
    indicating aggressive trading activity.
    
    Features:
    - Multi-level sweep detection
    - Volume threshold tracking
    - Price impact calculation
    - Configurable thresholds
    """
    
    def __init__(
        self,
        min_levels: int = 3,
        min_volume: int = 1000,
    ):
        """
        Initialize sweep detector.
        
        Args:
            min_levels: Minimum levels consumed to trigger
            min_volume: Minimum volume swept to trigger
        """
        self._threshold_levels = min_levels
        self._threshold_volume = min_volume
    
    def detect_bid_sweep(
        self,
        before_bids: List[PriceLevel],
        after_bids: List[PriceLevel],
        asks: Optional[List[PriceLevel]] = None,
        symbol: str = "",
    ) -> Optional[SweepEvent]:
        """
        Detect sweep on bid side.
        
        Args:
            before_bids: Bid levels before event
            after_bids: Bid levels after event
            asks: Current ask levels (for context)
            symbol: Instrument symbol
            
        Returns:
            SweepEvent if detected, None otherwise
        """
        return self._check_side_sweep(
            before_bids, after_bids, symbol, SweepDirection.BID, descending=True
        )
    
    def detect_ask_sweep(
        self,
        bids: Optional[List[PriceLevel]] = None,
        before_asks: List[PriceLevel] = None,
        after_asks: List[PriceLevel] = None,
        symbol: str = "",
    ) -> Optional[SweepEvent]:
        """
        Detect sweep on ask side.
        
        Args:
            bids: Current bid levels (for context)
            before_asks: Ask levels before event
            after_asks: Ask levels after event
            symbol: Instrument symbol
            
        Returns:
            SweepEvent if detected, None otherwise
        """
        if before_asks is None or after_asks is None:
            return None
            
        return self._check_side_sweep(
            before_asks, after_asks, symbol, SweepDirection.ASK, descending=False
        )
    
    def check_sweep(
        self,
        old_book: List[PriceLevel],
        new_book: List[PriceLevel],
        symbol: str = "UNKNOWN",
    ) -> Optional[SweepEvent]:
        """
        Check if a sweep occurred between old and new book states.
        
        Args:
            old_book: Previous book state (bid or ask side)
            new_book: Current book state (same side)
            symbol: Instrument symbol
            
        Returns:
            SweepEvent if sweep detected, None otherwise
        """
        if not old_book or not new_book:
            return None
        
        # Detect which direction (based on price ordering)
        # Bids are sorted descending, asks are sorted ascending
        if old_book[0].price > old_book[-1].price if len(old_book) > 1 else True:
            # Bids (descending order)
            direction = SweepDirection.BID
            return self._check_side_sweep(
                old_book, new_book, symbol, direction, descending=True
            )
        else:
            # Asks (ascending order)
            direction = SweepDirection.ASK
            return self._check_side_sweep(
                old_book, new_book, symbol, direction, descending=False
            )
    
    def _check_side_sweep(
        self,
        old_book: List[PriceLevel],
        new_book: List[PriceLevel],
        symbol: str,
        direction: SweepDirection,
        descending: bool,
    ) -> Optional[SweepEvent]:
        """
        Check for sweep on one side of the book.
        
        Args:
            old_book: Previous state
            new_book: Current state
            symbol: Instrument symbol
            direction: Sweep direction
            descending: True for bids, False for asks
            
        Returns:
            SweepEvent if detected, None otherwise
        """
        # Count levels consumed and volume removed
        levels_consumed = 0
        volume_swept = 0
        start_price = old_book[0].price if old_book else 0.0
        end_price = start_price
        
        old_idx = 0
        new_idx = 0
        
        while old_idx < len(old_book):
            old_level = old_book[old_idx]
            
            # Find corresponding new level
            if new_idx < len(new_book) and new_book[new_idx].price == old_level.price:
                new_level = new_book[new_idx]
                quantity_removed = old_level.quantity - new_level.quantity
                
                if quantity_removed > 0:
                    volume_swept += int(quantity_removed)
                    # If level completely removed or significantly reduced
                    if new_level.quantity == 0 or quantity_removed > old_level.quantity * 0.9:
                        levels_consumed += 1
                        end_price = old_level.price
                
                new_idx += 1
            else:
                # Level completely removed
                levels_consumed += 1
                volume_swept += int(old_level.quantity)
                end_price = old_level.price
            
            old_idx += 1
        
        # Check if sweep thresholds met (BOTH must be met)
        if levels_consumed < self._threshold_levels or volume_swept < self._threshold_volume:
            return None
        
        # Calculate price impact (absolute price difference)
        price_impact = abs(start_price - end_price)
        
        sweep = SweepEvent(
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            direction=direction,
            levels_consumed=levels_consumed,
            total_volume_swept=volume_swept,
            price_impact=price_impact,
            start_price=start_price,
            end_price=end_price,
        )
        
        logger.info(
            f"Sweep detected: {direction.value} sweep on {symbol}, "
            f"{levels_consumed} levels, {volume_swept} volume, "
            f"{price_impact:.2f}% impact"
        )
        
        return sweep
