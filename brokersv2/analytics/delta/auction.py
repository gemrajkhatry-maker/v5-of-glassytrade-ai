"""Auction Analyzer."""

from __future__ import annotations

from datetime import datetime, timezone

from brokersv2.analytics.delta.events import AuctionEvent


class AuctionAnalyzer:
    """
    Analyze auction dynamics.
    
    Features:
    - Unfinished auction detection
    - Absorption detection
    - Rejection analysis
    - Auction completion ratio
    """

    def __init__(self):
        pass

    def check_auction(
        self,
        price: float,
        volume: float,
        is_high: bool,
        rejection_wick: float,
        price_movement: float = 0.0,
    ) -> AuctionEvent:
        """
        Analyze auction at price level.
        
        Args:
            price: Price level
            volume: Volume at level
            is_high: Whether this is a high price extreme
            rejection_wick: Wick size indicating rejection
            price_movement: Price movement from previous
            
        Returns:
            AuctionEvent with analysis results
        """
        timestamp = datetime.now(timezone.utc)
        
        # Unfinished auction: high volume at extreme with no rejection
        is_unfinished = (
            volume > 0
            and rejection_wick == 0.0
            and is_high
        )
        
        # Absorption: large volume with minimal price movement
        absorption_volume = volume if volume > 0 and abs(price_movement) < 2.0 else 0.0
        
        # Completion ratio (0-1): how complete the auction is
        # Higher volume + rejection = more complete
        if volume > 0:
            completion_ratio = min(1.0, rejection_wick / max(1.0, price_movement)) if price_movement > 0 else 0.5
        else:
            completion_ratio = 0.0
        
        return AuctionEvent(
            timestamp=timestamp,
            price=price,
            is_unfinished_auction=is_unfinished,
            absorption_volume=absorption_volume,
            rejection_wick=rejection_wick,
            completion_ratio=completion_ratio,
        )
