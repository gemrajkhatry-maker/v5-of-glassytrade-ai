"""
Order Book Analytics - Liquidity Metrics Engine.

Calculates liquidity concentration, volume-at-price, and depth metrics.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from brokersv2.analytics.order_book.engine import OrderBookEngine, Side


@dataclass
class LiquiditySnapshot:
    """Snapshot of liquidity metrics."""
    timestamp: datetime
    bid_volume: int
    ask_volume: int
    total_volume: int
    bid_levels: int
    ask_levels: int
    bid_imbalance: float
    ask_imbalance: float
    bid_concentration_top3: float
    ask_concentration_top3: float
    bid_vwap: float
    ask_vwap: float


class LiquidityMetricsEngine:
    """
    Calculate liquidity metrics from order book.
    
    Features:
    - Bid/ask volume aggregation
    - Liquidity concentration analysis
    - Volume-at-price histogram
    - Liquidity imbalance calculation
    - Depth-of-book metrics
    - Volume-weighted average price
    
    Usage:
        engine = OrderBookEngine(symbol="RELIANCE")
        # ... add orders ...
        
        metrics = LiquidityMetricsEngine(engine)
        bid_volume = metrics.get_total_bid_volume()
        imbalance = metrics.get_liquidity_imbalance()
    """
    
    def __init__(self, order_book: "OrderBookEngine"):
        """
        Initialize liquidity metrics engine.
        
        Args:
            order_book: Order book engine to analyze
        """
        self.order_book = order_book
    
    def get_total_bid_volume(self) -> int:
        """Get total bid volume across all price levels."""
        return sum(qty for qty, _ in self.order_book.bids.values())
    
    def get_total_ask_volume(self) -> int:
        """Get total ask volume across all price levels."""
        return sum(qty for qty, _ in self.order_book.asks.values())
    
    def get_total_volume(self) -> int:
        """Get total book volume (bids + asks)."""
        return self.get_total_bid_volume() + self.get_total_ask_volume()
    
    def get_bid_levels(self) -> int:
        """Get number of bid price levels."""
        return len(self.order_book.bids)
    
    def get_ask_levels(self) -> int:
        """Get number of ask price levels."""
        return len(self.order_book.asks)
    
    def get_volume_at_price(self, price: float, side: "Side") -> int:
        """
        Get volume at specific price level.
        
        Args:
            price: Price level to query
            side: BID or ASK
        
        Returns:
            Volume at price (0 if price level doesn't exist)
        """
        from brokersv2.analytics.order_book.engine import Side
        
        book = self.order_book.bids if side == Side.BID else self.order_book.asks
        if price in book:
            qty, _ = book[price]
            return qty
        return 0
    
    def get_bid_concentration(self, top_n: int = 3) -> float:
        """
        Calculate bid liquidity concentration.
        
        Args:
            top_n: Number of top price levels to consider
        
        Returns:
            Concentration ratio (0.0 to 1.0)
        """
        from brokersv2.analytics.order_book.engine import Side
        
        total_volume = self.get_total_bid_volume()
        if total_volume == 0:
            return 0.0
        
        # Get top N levels by price (highest first for bids)
        sorted_levels = sorted(
            self.order_book.bids.items(),
            key=lambda x: x[0],
            reverse=True
        )[:top_n]
        
        top_volume = sum(qty for _, (qty, _) in sorted_levels)
        return top_volume / total_volume
    
    def get_ask_concentration(self, top_n: int = 3) -> float:
        """
        Calculate ask liquidity concentration.
        
        Args:
            top_n: Number of top price levels to consider
        
        Returns:
            Concentration ratio (0.0 to 1.0)
        """
        from brokersv2.analytics.order_book.engine import Side
        
        total_volume = self.get_total_ask_volume()
        if total_volume == 0:
            return 0.0
        
        # Get top N levels by price (lowest first for asks)
        sorted_levels = sorted(
            self.order_book.asks.items(),
            key=lambda x: x[0]
        )[:top_n]
        
        top_volume = sum(qty for _, (qty, _) in sorted_levels)
        return top_volume / total_volume
    
    def get_liquidity_imbalance(self) -> float:
        """
        Calculate liquidity imbalance.
        
        Returns:
            Imbalance ratio from -1.0 (all asks) to 1.0 (all bids)
            Formula: (bid_vol - ask_vol) / (bid_vol + ask_vol)
        """
        bid_volume = self.get_total_bid_volume()
        ask_volume = self.get_total_ask_volume()
        total_volume = bid_volume + ask_volume
        
        if total_volume == 0:
            return 0.0
        
        return (bid_volume - ask_volume) / total_volume
    
    def get_weighted_average_price(self, side: "Side") -> float:
        """
        Calculate volume-weighted average price.
        
        Args:
            side: BID or ASK
        
        Returns:
            VWAP for the specified side
        """
        from brokersv2.analytics.order_book.engine import Side
        
        book = self.order_book.bids if side == Side.BID else self.order_book.asks
        
        if not book:
            return 0.0
        
        total_volume = sum(qty for qty, _ in book.values())
        if total_volume == 0:
            return 0.0
        
        weighted_sum = sum(price * qty for price, (qty, _) in book.items())
        return weighted_sum / total_volume
    
    def get_snapshot(self) -> LiquiditySnapshot:
        """
        Get comprehensive liquidity snapshot.
        
        Returns:
            LiquiditySnapshot with all metrics
        """
        return LiquiditySnapshot(
            timestamp=datetime.now(timezone.utc),
            bid_volume=self.get_total_bid_volume(),
            ask_volume=self.get_total_ask_volume(),
            total_volume=self.get_total_volume(),
            bid_levels=self.get_bid_levels(),
            ask_levels=self.get_ask_levels(),
            bid_imbalance=self.get_liquidity_imbalance(),
            ask_imbalance=-self.get_liquidity_imbalance(),
            bid_concentration_top3=self.get_bid_concentration(top_n=3),
            ask_concentration_top3=self.get_ask_concentration(top_n=3),
            bid_vwap=self.get_weighted_average_price(
                side=self.order_book.bids and self.order_book.bids.keys() and "bid" or "ask"
            ),
            ask_vwap=self.get_weighted_average_price(
                side=self.order_book.asks and self.order_book.asks.keys() and "ask" or "bid"
            ),
        )
