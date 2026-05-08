"""
Order Book Analytics - Imbalance Calculator.

Calculates order book imbalance, volume delta, and divergence detection.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from brokersv2.analytics.order_book.engine import OrderBookEngine


@dataclass
class ImbalanceRecord:
    """Historical imbalance record."""
    timestamp: datetime
    imbalance: float
    volume_delta: int
    bid_volume: int
    ask_volume: int


class ImbalanceCalculator:
    """
    Calculate and track order book imbalance.
    
    Features:
    - Basic imbalance: (bid_vol - ask_vol) / total
    - Price-weighted imbalance
    - Volume delta tracking
    - Cumulative imbalance history
    - Divergence detection
    
    Usage:
        engine = OrderBookEngine(symbol="RELIANCE")
        calc = ImbalanceCalculator(engine, divergence_threshold=0.7)
        
        imbalance = calc.get_imbalance()
        has_divergence, _ = calc.check_divergence()
    """
    
    def __init__(
        self,
        order_book: "OrderBookEngine",
        divergence_threshold: float = 0.7,
        history_size: int = 100,
    ):
        """
        Initialize imbalance calculator.
        
        Args:
            order_book: Order book engine to analyze
            divergence_threshold: Threshold for divergence alert (0-1)
            history_size: Maximum history size
        """
        self.order_book = order_book
        self.divergence_threshold = divergence_threshold
        self.history_size = history_size
        self.history: List[ImbalanceRecord] = []
    
    def get_imbalance(self) -> float:
        """
        Calculate current order book imbalance.
        
        Returns:
            Imbalance ratio from -1.0 (all asks) to 1.0 (all bids)
        """
        bid_volume = sum(qty for qty, _ in self.order_book.bids.values())
        ask_volume = sum(qty for qty, _ in self.order_book.asks.values())
        total_volume = bid_volume + ask_volume
        
        if total_volume == 0:
            return 0.0
        
        return (bid_volume - ask_volume) / total_volume
    
    def get_price_weighted_imbalance(self) -> float:
        """
        Calculate price-weighted imbalance.
        
        Volume closer to spread has higher weight.
        
        Returns:
            Price-weighted imbalance ratio
        """
        if not self.order_book.bids or not self.order_book.asks:
            return 0.0
        
        best_bid = max(self.order_book.bids.keys())
        best_ask = min(self.order_book.asks.keys())
        mid_price = (best_bid + best_ask) / 2
        
        # Calculate weighted volumes
        bid_weighted = 0
        ask_weighted = 0
        
        for price, (qty, _) in self.order_book.bids.items():
            distance = abs(price - mid_price)
            weight = 1.0 / (1.0 + distance)  # Closer = higher weight
            bid_weighted += qty * weight
        
        for price, (qty, _) in self.order_book.asks.items():
            distance = abs(price - mid_price)
            weight = 1.0 / (1.0 + distance)
            ask_weighted += qty * weight
        
        total_weighted = bid_weighted + ask_weighted
        if total_weighted == 0:
            return 0.0
        
        return (bid_weighted - ask_weighted) / total_weighted
    
    def get_volume_delta(self) -> int:
        """
        Calculate volume delta (bid - ask).
        
        Returns:
            Volume delta (positive = bid heavy, negative = ask heavy)
        """
        bid_volume = sum(qty for qty, _ in self.order_book.bids.values())
        ask_volume = sum(qty for qty, _ in self.order_book.asks.values())
        
        return bid_volume - ask_volume
    
    def record_snapshot(self) -> ImbalanceRecord:
        """
        Record current imbalance snapshot.
        
        Returns:
            Recorded imbalance data
        """
        bid_volume = sum(qty for qty, _ in self.order_book.bids.values())
        ask_volume = sum(qty for qty, _ in self.order_book.asks.values())
        
        record = ImbalanceRecord(
            timestamp=datetime.now(timezone.utc),
            imbalance=self.get_imbalance(),
            volume_delta=self.get_volume_delta(),
            bid_volume=bid_volume,
            ask_volume=ask_volume,
        )
        
        self.history.append(record)
        
        # Trim history
        if len(self.history) > self.history_size:
            self.history = self.history[-self.history_size:]
        
        return record
    
    def get_cumulative_imbalance(self, window: int = 10) -> float:
        """
        Calculate cumulative average imbalance.
        
        Args:
            window: Number of recent snapshots to average
        
        Returns:
            Average imbalance over window
        """
        if not self.history:
            return 0.0
        
        recent = self.history[-window:]
        return sum(r.imbalance for r in recent) / len(recent)
    
    def check_divergence(self) -> Tuple[bool, float]:
        """
        Check if current imbalance diverges from threshold.
        
        Returns:
            Tuple of (has_divergence, current_imbalance)
        """
        current = self.get_imbalance()
        has_divergence = abs(current) >= self.divergence_threshold
        
        return has_divergence, current
    
    def clear_history(self) -> None:
        """Clear imbalance history."""
        self.history.clear()
    
    def get_imbalance_trend(self, window: int = 5) -> str:
        """
        Determine imbalance trend direction.
        
        Args:
            window: Number of snapshots to analyze
        
        Returns:
            "increasing", "decreasing", or "stable"
        """
        if len(self.history) < 2:
            return "stable"
        
        recent = self.history[-window:]
        if len(recent) < 2:
            return "stable"
        
        # Simple linear trend
        first_half = sum(r.imbalance for r in recent[:len(recent)//2])
        second_half = sum(r.imbalance for r in recent[len(recent)//2:])
        
        diff = second_half - first_half
        
        if abs(diff) < 0.05:
            return "stable"
        elif diff > 0:
            return "increasing"
        else:
            return "decreasing"
