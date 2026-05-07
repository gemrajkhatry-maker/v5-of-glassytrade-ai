"""Order Book Engine - Full L2 reconstruction."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from brokersv2.analytics.order_book.events import (
    PriceLevel,
    OrderBookSnapshot,
    OrderBookEvent,
    OrderBookEventType,
)


class OrderBookEngine:
    """
    Full L2 order book reconstruction engine.
    
    Features:
    - Incremental depth processing
    - Bid/ask level management
    - Sorted price ladders
    - Event generation
    - Snapshot capture
    """

    def __init__(self, symbol: str, max_events: Optional[int] = None):
        self.symbol = symbol
        self.max_events = max_events
        self._bids: Dict[float, PriceLevel] = {}
        self._asks: Dict[float, PriceLevel] = {}
        self._events: List[OrderBookEvent] = []
        self._sequence = 0

    @property
    def bids(self) -> List[PriceLevel]:
        """Bid levels sorted descending by price."""
        return sorted(self._bids.values(), key=lambda x: x.price, reverse=True)

    @property
    def asks(self) -> List[PriceLevel]:
        """Ask levels sorted ascending by price."""
        return sorted(self._asks.values(), key=lambda x: x.price)

    @property
    def bid_levels(self) -> int:
        """Number of bid levels."""
        return len(self._bids)

    @property
    def ask_levels(self) -> int:
        """Number of ask levels."""
        return len(self._asks)

    @property
    def best_bid(self) -> Optional[PriceLevel]:
        """Best bid price level."""
        if not self._bids:
            return None
        return max(self._bids.values(), key=lambda x: x.price)

    @property
    def best_ask(self) -> Optional[PriceLevel]:
        """Best ask price level."""
        if not self._asks:
            return None
        return min(self._asks.values(), key=lambda x: x.price)

    @property
    def spread(self) -> Optional[float]:
        """Bid-ask spread."""
        if self.best_bid and self.best_ask:
            return self.best_ask.price - self.best_bid.price
        return None

    @property
    def mid_price(self) -> Optional[float]:
        """Mid price."""
        if self.best_bid and self.best_ask:
            return (self.best_bid.price + self.best_ask.price) / 2.0
        return None

    @property
    def events(self) -> List[OrderBookEvent]:
        """Event history."""
        return self._events

    @property
    def total_bid_quantity(self) -> float:
        """Total quantity across all bid levels."""
        return sum(level.quantity for level in self._bids.values())

    @property
    def total_ask_quantity(self) -> float:
        """Total quantity across all ask levels."""
        return sum(level.quantity for level in self._asks.values())

    @property
    def total_bid_notional(self) -> float:
        """Total notional value of bid side."""
        return sum(level.notional for level in self._bids.values())

    @property
    def total_ask_notional(self) -> float:
        """Total notional value of ask side."""
        return sum(level.notional for level in self._asks.values())

    @property
    def spread_percentage(self) -> Optional[float]:
        """Spread as percentage of mid price."""
        if self.spread is None or self.mid_price is None or self.mid_price == 0:
            return None
        return (self.spread / self.mid_price) * 100.0

    @property
    def quantity_imbalance(self) -> float:
        """
        Quantity imbalance: (bid_qty - ask_qty) / (bid_qty + ask_qty)
        
        Returns:
            float: Value in [-1, 1]. Positive = bid imbalance, Negative = ask imbalance
        """
        bid_qty = self.total_bid_quantity
        ask_qty = self.total_ask_quantity
        total = bid_qty + ask_qty
        
        if total == 0:
            return 0.0
        
        return (bid_qty - ask_qty) / total

    @property
    def notional_imbalance(self) -> float:
        """
        Notional-weighted imbalance: (bid_notional - ask_notional) / (bid_notional + ask_notional)
        
        Returns:
            float: Value in [-1, 1]
        """
        bid_notional = self.total_bid_notional
        ask_notional = self.total_ask_notional
        total = bid_notional + ask_notional
        
        if total == 0:
            return 0.0
        
        return (bid_notional - ask_notional) / total

    def get_bid_ladder(self, depth: int = 5) -> List[PriceLevel]:
        """Get top N bid levels."""
        return self.bids[:depth]

    def get_ask_ladder(self, depth: int = 5) -> List[PriceLevel]:
        """Get top N ask levels."""
        return self.asks[:depth]

    def get_cumulative_bid_quantity(self, depth: int = 5) -> float:
        """Get cumulative quantity for top N bid levels."""
        ladder = self.get_bid_ladder(depth)
        return sum(level.quantity for level in ladder)

    def get_cumulative_ask_quantity(self, depth: int = 5) -> float:
        """Get cumulative quantity for top N ask levels."""
        ladder = self.get_ask_ladder(depth)
        return sum(level.quantity for level in ladder)

    def get_cumulative_bid_notional(self, depth: int = 5) -> float:
        """Get cumulative notional for top N bid levels."""
        ladder = self.get_bid_ladder(depth)
        return sum(level.notional for level in ladder)

    def get_cumulative_ask_notional(self, depth: int = 5) -> float:
        """Get cumulative notional for top N ask levels."""
        ladder = self.get_ask_ladder(depth)
        return sum(level.notional for level in ladder)

    def check_sweep(self, quantity: float, side: str) -> bool:
        """
        Check if an order would sweep multiple price levels.
        
        Args:
            quantity: Order quantity
            side: "BUY" or "SELL"
            
        Returns:
            bool: True if order would sweep 2+ levels
        """
        levels_crossed = self.get_sweep_levels_crossed(quantity, side)
        return levels_crossed >= 2

    def get_sweep_levels_crossed(self, quantity: float, side: str) -> int:
        """
        Get number of price levels a market order would cross.
        
        Args:
            quantity: Order quantity
            side: "BUY" (crosses asks) or "SELL" (crosses bids)
            
        Returns:
            int: Number of levels that would be swept
        """
        if side == "BUY":
            ladder = self.asks  # Buy orders consume asks
        else:
            ladder = self.bids  # Sell orders consume bids
        
        remaining_qty = quantity
        levels_crossed = 0
        
        for level in ladder:
            if remaining_qty <= 0:
                break
            remaining_qty -= level.quantity
            levels_crossed += 1
        
        return levels_crossed

    def update_bid(self, level: PriceLevel) -> None:
        """
        Update bid level.
        
        If quantity is zero, level is removed.
        Generates BID_UPDATE event.
        """
        if level.quantity == 0:
            # Remove level
            self._bids.pop(level.price, None)
        else:
            # Update or add level
            self._bids[level.price] = level
        
        self._sequence += 1
        self._emit_event(OrderBookEventType.BID_UPDATE, [level])

    def update_ask(self, level: PriceLevel) -> None:
        """
        Update ask level.
        
        If quantity is zero, level is removed.
        Generates ASK_UPDATE event.
        """
        if level.quantity == 0:
            # Remove level
            self._asks.pop(level.price, None)
        else:
            # Update or add level
            self._asks[level.price] = level
        
        self._sequence += 1
        self._emit_event(OrderBookEventType.ASK_UPDATE, [level])

    def take_snapshot(self) -> OrderBookSnapshot:
        """Take complete order book snapshot."""
        snapshot = OrderBookSnapshot(
            symbol=self.symbol,
            timestamp=datetime.now(timezone.utc),
            bids=self.bids,
            asks=self.asks,
            sequence=self._sequence,
        )
        
        self._sequence += 1
        self._emit_event(OrderBookEventType.SNAPSHOT, snapshot=snapshot)
        
        return snapshot

    def _emit_event(
        self,
        event_type: OrderBookEventType,
        levels: Optional[List[PriceLevel]] = None,
        snapshot: Optional[OrderBookSnapshot] = None,
    ) -> None:
        """Emit order book event."""
        event = OrderBookEvent(
            event_type=event_type,
            symbol=self.symbol,
            timestamp=datetime.now(timezone.utc),
            sequence=self._sequence,
            snapshot=snapshot,
            updated_levels=levels,
        )
        self._events.append(event)
        
        # Enforce max_events limit
        if self.max_events and len(self._events) > self.max_events:
            self._events = self._events[-self.max_events:]

    def clear(self) -> None:
        """Clear entire order book."""
        self._bids.clear()
        self._asks.clear()
        self._events.clear()
        self._sequence = 0

    def top_of_book_ratio(self) -> Optional[float]:
        """Ratio of best bid quantity to best ask quantity."""
        if self.best_bid is None or self.best_ask is None:
            return None
        if self.best_ask.quantity == 0:
            return None
        return self.best_bid.quantity / self.best_ask.quantity

    def weighted_mid_price(self) -> Optional[float]:
        """
        Volume-weighted mid price.
        
        Weights best bid and ask by their quantities.
        """
        if self.best_bid is None or self.best_ask is None:
            return None
        
        total_qty = self.best_bid.quantity + self.best_ask.quantity
        if total_qty == 0:
            return self.mid_price
        
        return (
            (self.best_bid.price * self.best_bid.quantity +
             self.best_ask.price * self.best_ask.quantity) / total_qty
        )

    def bid_vwap(self) -> Optional[float]:
        """Volume-weighted average price of bid side."""
        if self.total_bid_quantity == 0:
            return None
        return self.total_bid_notional / self.total_bid_quantity

    def ask_vwap(self) -> Optional[float]:
        """Volume-weighted average price of ask side."""
        if self.total_ask_quantity == 0:
            return None
        return self.total_ask_notional / self.total_ask_quantity

    def estimate_market_impact(self, quantity: float, side: str) -> Optional[float]:
        """
        Estimate average execution price for market order.
        
        Args:
            quantity: Order quantity
            side: "BUY" or "SELL"
            
        Returns:
            float: Estimated average execution price, or None if insufficient liquidity
        """
        if side == "BUY":
            ladder = self.asks
        else:
            ladder = self.bids
        
        if not ladder:
            return None
        
        remaining_qty = quantity
        total_cost = 0.0
        
        for level in ladder:
            if remaining_qty <= 0:
                break
            
            exec_qty = min(remaining_qty, level.quantity)
            total_cost += exec_qty * level.price
            remaining_qty -= exec_qty
        
        if remaining_qty > 0:
            return None  # Insufficient liquidity
        
        return total_cost / quantity
