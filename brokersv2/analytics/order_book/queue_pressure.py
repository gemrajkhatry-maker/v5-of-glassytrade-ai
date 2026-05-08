"""
Order Book Analytics - Queue Pressure Analyzer.

Analyzes queue dynamics, depletion rates, and pressure indicators.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from brokersv2.analytics.order_book.engine import OrderBookEngine, Side


@dataclass
class PressureSnapshot:
    """Snapshot of queue pressure state."""
    timestamp: datetime
    pressure_score: float
    bid_depth: int
    ask_depth: int
    depletion_rate: float
    is_replenishing: bool


class QueuePressureAnalyzer:
    """
    Analyze order book queue pressure.
    
    Features:
    - Queue position tracking
    - Queue depletion rate calculation
    - Queue replenishment detection
    - Pressure indicator (0-100 scale)
    - Pressure trend analysis
    
    Usage:
        engine = OrderBookEngine(symbol="RELIANCE")
        analyzer = QueuePressureAnalyzer(engine)
        
        pressure = analyzer.get_pressure_score()
        trend = analyzer.get_pressure_trend()
    """
    
    def __init__(
        self,
        order_book: "OrderBookEngine",
        history_size: int = 50,
    ):
        """
        Initialize queue pressure analyzer.
        
        Args:
            order_book: Order book engine to analyze
            history_size: Maximum snapshot history size
        """
        self.order_book = order_book
        self.history_size = history_size
        self.history: List[PressureSnapshot] = []
        self._queue_depth_history: List[int] = []
    
    def get_bid_queue_depth(self) -> int:
        """Get total bid queue depth."""
        return sum(qty for qty, _ in self.order_book.bids.values())
    
    def get_ask_queue_depth(self) -> int:
        """Get total ask queue depth."""
        return sum(qty for qty, _ in self.order_book.asks.values())
    
    def get_queue_depth_at_price(self, price: float, side: "Side") -> int:
        """
        Get queue depth at specific price level.
        
        Args:
            price: Price level to query
            side: BID or ASK
        
        Returns:
            Queue depth at price
        """
        from brokersv2.analytics.order_book.engine import Side
        
        book = self.order_book.bids if side == Side.BID else self.order_book.asks
        if price in book:
            qty, _ = book[price]
            return qty
        return 0
    
    def get_depletion_rate(self) -> float:
        """
        Calculate queue depletion rate.
        
        Returns:
            Rate of change (negative = depleting, positive = growing)
        """
        if len(self._queue_depth_history) < 2:
            return 0.0
        
        # Calculate rate of change
        recent = self._queue_depth_history[-10:]  # Last 10 samples
        if len(recent) < 2:
            return 0.0
        
        first = recent[0]
        last = recent[-1]
        
        if first == 0:
            return 0.0
        
        return (last - first) / first
    
    def _record_queue_depth(self, depth: int) -> None:
        """Record queue depth sample (for testing)."""
        self._queue_depth_history.append(depth)
        if len(self._queue_depth_history) > 100:
            self._queue_depth_history = self._queue_depth_history[-100:]
    
    def is_queue_replenishing(self) -> bool:
        """
        Detect if queue is being replenished.
        
        Returns:
            True if queue depth is increasing
        """
        rate = self.get_depletion_rate()
        return rate > 0.05  # 5% growth threshold
    
    def get_pressure_score(self) -> float:
        """
        Calculate pressure score (0-100 scale).
        
        Returns:
            0 = strong ask pressure, 50 = balanced, 100 = strong bid pressure
        """
        bid_depth = self.get_bid_queue_depth()
        ask_depth = self.get_ask_queue_depth()
        total_depth = bid_depth + ask_depth
        
        if total_depth == 0:
            return 0.0
        
        # Calculate ratio and scale to 0-100
        bid_ratio = bid_depth / total_depth
        return bid_ratio * 100.0
    
    def record_snapshot(self) -> PressureSnapshot:
        """
        Record current pressure snapshot.
        
        Returns:
            PressureSnapshot with current state
        """
        bid_depth = self.get_bid_queue_depth()
        ask_depth = self.get_ask_queue_depth()
        
        # Record total depth for depletion tracking
        self._record_queue_depth(bid_depth + ask_depth)
        
        snapshot = PressureSnapshot(
            timestamp=datetime.now(timezone.utc),
            pressure_score=self.get_pressure_score(),
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            depletion_rate=self.get_depletion_rate(),
            is_replenishing=self.is_queue_replenishing(),
        )
        
        self.history.append(snapshot)
        
        # Trim history
        if len(self.history) > self.history_size:
            self.history = self.history[-self.history_size:]
        
        return snapshot
    
    def get_pressure_trend(self, window: int = 5) -> str:
        """
        Determine pressure trend direction.
        
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
        
        # Compare first half to second half
        first_half = sum(s.pressure_score for s in recent[:len(recent)//2])
        second_half = sum(s.pressure_score for s in recent[len(recent)//2:])
        
        diff = second_half - first_half
        
        if abs(diff) < 5.0:  # Threshold for stability
            return "stable"
        elif diff > 0:
            return "increasing"
        else:
            return "decreasing"
    
    def clear_history(self) -> None:
        """Clear pressure history."""
        self.history.clear()
        self._queue_depth_history.clear()
