"""
Order Book Engine - Core.

Full L2 order book reconstruction with price-time priority.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# Import canonical types from events module
from brokersv2.analytics.order_book.events import (
    PriceLevel,
    OrderBookSnapshot,
    OrderBookEvent,
    OrderBookEventType,
)
# Import analytics modules
from brokersv2.analytics.order_book.liquidity import LiquidityMetricsEngine
from brokersv2.analytics.order_book.imbalance import ImbalanceCalculator
from brokersv2.analytics.order_book.queue_pressure import QueuePressureAnalyzer
from brokersv2.analytics.order_book.sweep_detection import SweepDetector


# Keep local enums for backward compatibility
class Side:
    """Order side."""
    BID = "bid"
    ASK = "ask"


class OrderAction:
    """Order action type."""
    ADD = "add"
    MODIFY = "modify"
    CANCEL = "cancel"
    TRADE = "trade"


# Backward compatibility: Trade dataclass
from dataclasses import dataclass as _dataclass

@_dataclass
class Trade:
    """Trade record for backward compatibility."""
    price: float
    quantity: int
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)


class OrderBookEngine:
    """
    Core order book engine with L2 reconstruction.
    
    Features:
    - Full order book from incremental updates
    - Price-time priority
    - Order tracking by ID
    - Depth management (max levels)
    - Spread and mid-price calculation
    - Trade recording
    
    Usage:
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order("1", 2500.0, 100, Side.BID)
        engine.modify_order("1", quantity=150)
        engine.cancel_order("1")
        
        snapshot = engine.get_snapshot()
    """
    
    def __init__(self, symbol: str, max_depth: int = 20, max_events: int = 10000):
        """
        Initialize order book engine.
        
        Args:
            symbol: Trading symbol
            max_depth: Maximum price levels per side (default: 20)
            max_events: Maximum event history size (default: 10000)
        """
        self.symbol = symbol
        self.max_depth = max_depth
        self.max_events = max_events
        
        # Price levels as dicts: price -> (quantity, order_count)
        self.bids: Dict[float, Tuple[int, int]] = {}
        self.asks: Dict[float, Tuple[int, int]] = {}
        
        # Order tracking: order_id -> (price, quantity, side)
        self.orders: Dict[str, Tuple[float, int, Side]] = {}
        
        # Trade history
        self.trades: List[Trade] = []
        
        # Event tracking (for tests)
        self._events: List[OrderBookEvent] = []
        self._sequence: int = 0
        
        # Analytics engines (lazy initialization)
        self._liquidity: Optional[LiquidityMetricsEngine] = None
        self._imbalance: Optional[ImbalanceCalculator] = None
        self._queue_pressure: Optional[QueuePressureAnalyzer] = None
        self._sweep_detector: Optional[SweepDetector] = None
    
    @property
    def bid_levels(self) -> int:
        """Number of bid price levels."""
        return len(self.bids)
    
    @property
    def ask_levels(self) -> int:
        """Number of ask price levels."""
        return len(self.asks)
    
    @property
    def best_bid(self) -> Optional[PriceLevel]:
        """Best bid price level."""
        if not self.bids:
            return None
        best_price = max(self.bids.keys())
        qty, count = self.bids[best_price]
        return PriceLevel(price=best_price, quantity=qty, order_count=count)
    
    @property
    def best_ask(self) -> Optional[PriceLevel]:
        """Best ask price level."""
        if not self.asks:
            return None
        best_price = min(self.asks.keys())
        qty, count = self.asks[best_price]
        return PriceLevel(price=best_price, quantity=qty, order_count=count)
    
    @property
    def spread(self) -> Optional[float]:
        """Bid-ask spread."""
        if self.best_bid and self.best_ask:
            return self.best_ask.price - self.best_bid.price
        return None
    
    @property
    def mid_price(self) -> float:
        """Mid price = (best_bid + best_ask) / 2."""
        if self.best_bid and self.best_ask:
            return (self.best_bid.price + self.best_ask.price) / 2.0
        return 0.0
    
    @property
    def events(self) -> List[OrderBookEvent]:
        """List of all generated order book events (for testing)."""
        return self._events.copy()
    
    @property
    def liquidity(self) -> LiquidityMetricsEngine:
        """Liquidity metrics engine."""
        if self._liquidity is None:
            self._liquidity = LiquidityMetricsEngine(self)
        return self._liquidity
    
    @property
    def imbalance_calculator(self) -> ImbalanceCalculator:
        """Imbalance calculator."""
        if self._imbalance is None:
            self._imbalance = ImbalanceCalculator(self)
        return self._imbalance
    
    # Convenience properties for tests
    @property
    def total_bid_quantity(self) -> int:
        """Total bid quantity across all levels."""
        return sum(qty for qty, _ in self.bids.values())
    
    @property
    def total_ask_quantity(self) -> int:
        """Total ask quantity across all levels."""
        return sum(qty for qty, _ in self.asks.values())
    
    @property
    def total_bid_notional(self) -> float:
        """Total bid notional value."""
        return sum(p * qty for p, (qty, _) in self.bids.items())
    
    @property
    def spread_percentage(self) -> Optional[float]:
        """Spread as percentage of mid price."""
        if self.best_bid and self.best_ask:
            mid = (self.best_bid.price + self.best_ask.price) / 2
            if mid > 0:
                return (self.spread / mid) * 100
        return None
    
    @property
    def quantity_imbalance(self) -> float:
        """Order book quantity imbalance."""
        return self.imbalance_calculator.get_imbalance()
    
    @property
    def notional_imbalance(self) -> float:
        """Notional-weighted imbalance."""
        bid_notional = self.total_bid_notional
        ask_notional = sum(p * qty for p, (qty, _) in self.asks.items())
        total = bid_notional + ask_notional
        if total == 0:
            return 0.0
        return (bid_notional - ask_notional) / total
    
    # Ladder methods
    def get_bid_ladder(self, depth: int = 5) -> List[PriceLevel]:
        """Get bid ladder up to specified depth."""
        bid_list = [
            PriceLevel(price=p, quantity=q, order_count=c)
            for p, (q, c) in self.bids.items()
        ]
        bid_list.sort(key=lambda x: x.price, reverse=True)
        return bid_list[:depth]
    
    def get_ask_ladder(self, depth: int = 5) -> List[PriceLevel]:
        """Get ask ladder up to specified depth."""
        ask_list = [
            PriceLevel(price=p, quantity=q, order_count=c)
            for p, (q, c) in self.asks.items()
        ]
        ask_list.sort(key=lambda x: x.price)
        return ask_list[:depth]
    
    def get_cumulative_bid_quantity(self, depth: int = 5) -> int:
        """Get cumulative bid quantity up to depth."""
        ladder = self.get_bid_ladder(depth)
        return int(sum(level.quantity for level in ladder))
    
    def get_cumulative_ask_quantity(self, depth: int = 5) -> int:
        """Get cumulative ask quantity up to depth."""
        ladder = self.get_ask_ladder(depth)
        return int(sum(level.quantity for level in ladder))
    
    def get_cumulative_bid_notional(self, depth: int = 5) -> float:
        """Get cumulative bid notional up to depth."""
        ladder = self.get_bid_ladder(depth)
        return sum(level.price * level.quantity for level in ladder)
    
    def get_cumulative_ask_notional(self, depth: int = 5) -> float:
        """Get cumulative ask notional up to depth."""
        ladder = self.get_ask_ladder(depth)
        return sum(level.price * level.quantity for level in ladder)
    
    # Sweep detection methods
    def check_sweep(self, quantity: float, side: str) -> bool:
        """Check if order would sweep multiple levels.
        
        Args:
            quantity: Order quantity
            side: "BUY" or "SELL"
            
        Returns:
            True if order would consume 2+ price levels
        """
        levels_crossed = self.get_sweep_levels_crossed(quantity, side)
        return levels_crossed >= 2
    
    def get_sweep_levels_crossed(self, quantity: float, side: str) -> int:
        """Get number of levels a market order would cross.
        
        Args:
            quantity: Order quantity
            side: "BUY" or "SELL"
            
        Returns:
            Number of price levels consumed
        """
        if side == "BUY":
            ladder = self.get_ask_ladder(depth=self.max_depth)
        else:  # SELL
            ladder = self.get_bid_ladder(depth=self.max_depth)
        
        levels_crossed = 0
        remaining_qty = quantity
        
        for level in ladder:
            if remaining_qty <= 0:
                break
            remaining_qty -= level.quantity
            levels_crossed += 1
        
        return levels_crossed
    
    # Weighted pricing methods
    def top_of_book_ratio(self) -> float:
        """Calculate top-of-book pressure ratio.
        
        Returns:
            Ratio of best bid quantity to best ask quantity
        """
        if self.best_bid and self.best_ask and self.best_ask.quantity > 0:
            return self.best_bid.quantity / self.best_ask.quantity
        return 0.0
    
    def weighted_mid_price(self) -> float:
        """Calculate volume-weighted mid price.
        
        Returns:
            Mid price weighted by best bid/ask quantities.
            More liquidity on one side pulls the price toward that side.
        """
        if not self.best_bid or not self.best_ask:
            return 0.0
        
        total_qty = self.best_bid.quantity + self.best_ask.quantity
        if total_qty == 0:
            return (self.best_bid.price + self.best_ask.price) / 2
        
        # Weight toward side with MORE liquidity
        # If bid has 300 and ask has 100, weight should pull toward bid
        bid_weight = self.best_bid.quantity / total_qty  # 0.75 in this case
        ask_weight = self.best_ask.quantity / total_qty  # 0.25 in this case
        
        # Higher bid weight = price closer to bid
        return self.best_bid.price * bid_weight + self.best_ask.price * ask_weight
    
    def bid_vwap(self) -> float:
        """Calculate volume-weighted average price for bids.
        
        Returns:
            VWAP of all bid levels
        """
        if not self.bids:
            return 0.0
        
        total_value = sum(p * qty for p, (qty, _) in self.bids.items())
        total_qty = sum(qty for qty, _ in self.bids.values())
        
        if total_qty == 0:
            return 0.0
        
        return total_value / total_qty
    
    def ask_vwap(self) -> float:
        """Calculate volume-weighted average price for asks.
        
        Returns:
            VWAP of all ask levels
        """
        if not self.asks:
            return 0.0
        
        total_value = sum(p * qty for p, (qty, _) in self.asks.items())
        total_qty = sum(qty for qty, _ in self.asks.values())
        
        if total_qty == 0:
            return 0.0
        
        return total_value / total_qty
    
    def estimate_market_impact(self, quantity: float, side: str) -> float:
        """Estimate average execution price for market order.
        
        Args:
            quantity: Order quantity
            side: "BUY" or "SELL"
            
        Returns:
            Estimated average execution price
        """
        if side == "BUY":
            ladder = self.get_ask_ladder(depth=self.max_depth)
        else:  # SELL
            ladder = self.get_bid_ladder(depth=self.max_depth)
        
        if not ladder:
            return 0.0
        
        total_value = 0.0
        filled_qty = 0
        remaining_qty = quantity
        
        for level in ladder:
            if remaining_qty <= 0:
                break
            
            fill_qty = min(remaining_qty, level.quantity)
            total_value += level.price * fill_qty
            filled_qty += fill_qty
            remaining_qty -= fill_qty
        
        if filled_qty == 0:
            return 0.0
        
        return total_value / filled_qty
    
    def _emit_event(
        self,
        event_type: OrderBookEventType,
        updated_levels: Optional[List[PriceLevel]] = None,
        metadata: Optional[Dict] = None,
    ) -> OrderBookEvent:
        """Generate and store an order book event."""
        self._sequence += 1
        event = OrderBookEvent(
            event_type=event_type,
            symbol=self.symbol,
            timestamp=datetime.now(timezone.utc),
            sequence=self._sequence,
            updated_levels=updated_levels or [],
            metadata=metadata or {},
        )
        self._events.append(event)
        
        # Trim event history if exceeds limit
        if len(self._events) > self.max_events:
            self._events = self._events[-self.max_events:]
        
        return event
    
    @property
    def snapshot(self) -> OrderBookSnapshot:
        """Current order book snapshot."""
        # Convert dict to list of PriceLevels
        bid_list = [
            PriceLevel(price=p, quantity=q, order_count=c)
            for p, (q, c) in self.bids.items()
        ]
        bid_list.sort(key=lambda x: x.price, reverse=True)
        
        ask_list = [
            PriceLevel(price=p, quantity=q, order_count=c)
            for p, (q, c) in self.asks.items()
        ]
        ask_list.sort(key=lambda x: x.price)
        
        return OrderBookSnapshot(
            symbol=self.symbol,
            timestamp=datetime.now(timezone.utc),
            bids=bid_list[:self.max_depth],
            asks=ask_list[:self.max_depth],
            sequence=self._sequence,
        )
    
    def take_snapshot(self) -> OrderBookSnapshot:
        """Take a snapshot of current order book state."""
        snapshot = self.snapshot
        # Emit snapshot event with the snapshot object
        self._emit_event(
            OrderBookEventType.SNAPSHOT,
            updated_levels=snapshot.bids + snapshot.asks,
        )
        # Attach snapshot to the last event
        if self._events:
            # Create new event with snapshot (events are frozen dataclasses)
            last_event = self._events.pop()
            event_with_snapshot = OrderBookEvent(
                event_type=last_event.event_type,
                symbol=last_event.symbol,
                timestamp=last_event.timestamp,
                sequence=last_event.sequence,
                snapshot=snapshot,
                updated_levels=last_event.updated_levels,
                metadata=last_event.metadata,
            )
            self._events.append(event_with_snapshot)
        return snapshot
    
    def update_bid(self, level: PriceLevel) -> None:
        """Update bid price level (list-based interface for tests)."""
        price = level.price
        # Store level even with negative quantity (validation is upstream)
        if level.quantity != 0:
            self.bids[price] = (level.quantity, level.order_count)
        elif price in self.bids:
            del self.bids[price]
        
        # Emit event
        self._emit_event(
            OrderBookEventType.BID_UPDATE,
            updated_levels=[level],
        )
    
    def update_ask(self, level: PriceLevel) -> None:
        """Update ask price level (list-based interface for tests)."""
        price = level.price
        # Store level even with negative quantity (validation is upstream)
        if level.quantity != 0:
            self.asks[price] = (level.quantity, level.order_count)
        elif price in self.asks:
            del self.asks[price]
        
        # Emit event
        self._emit_event(
            OrderBookEventType.ASK_UPDATE,
            updated_levels=[level],
        )
    
    def add_order(
        self,
        order_id: str,
        price: float,
        quantity: int,
        side: Side,
    ) -> None:
        """
        Add order to book.
        
        Args:
            order_id: Unique order identifier
            price: Order price
            quantity: Order quantity
            side: BID or ASK
        """
        book = self.bids if side == Side.BID else self.asks
        
        # Add to price level
        if price in book:
            qty, count = book[price]
            book[price] = (qty + quantity, count + 1)
        else:
            book[price] = (quantity, 1)
        
        # Track order
        self.orders[order_id] = (price, quantity, side)
    
    def modify_order(
        self,
        order_id: str,
        price: Optional[float] = None,
        quantity: Optional[int] = None,
    ) -> None:
        """
        Modify existing order.
        
        Args:
            order_id: Order to modify
            price: New price (optional)
            quantity: New quantity (optional)
        """
        if order_id not in self.orders:
            return
        
        old_price, old_qty, side = self.orders[order_id]
        new_price = price if price is not None else old_price
        new_qty = quantity if quantity is not None else old_qty
        
        book = self.bids if side == Side.BID else self.asks
        
        # If price changed, remove from old level and add to new level
        if new_price != old_price:
            # Remove from old price level
            if old_price in book:
                qty, count = book[old_price]
                new_level_qty = qty - old_qty
                if new_level_qty <= 0:
                    del book[old_price]
                else:
                    book[old_price] = (new_level_qty, count)
            
            # Add to new price level
            if new_price in book:
                qty, count = book[new_price]
                book[new_price] = (qty + new_qty, count + 1)
            else:
                book[new_price] = (new_qty, 1)
        else:
            # Price didn't change, just update quantity at this level
            if new_price in book:
                qty, count = book[new_price]
                book[new_price] = (qty - old_qty + new_qty, count)
        
        # Update order tracking
        self.orders[order_id] = (new_price, new_qty, side)
    
    def cancel_order(self, order_id: str) -> None:
        """
        Cancel order from book.
        
        Args:
            order_id: Order to cancel
        """
        if order_id not in self.orders:
            return
        
        price, quantity, side = self.orders[order_id]
        book = self.bids if side == Side.BID else self.asks
        
        # Remove from price level
        if price in book:
            qty, count = book[price]
            book[price] = (qty - quantity, count - 1)
            if book[price][1] == 0:
                del book[price]
        
        # Remove order tracking
        del self.orders[order_id]
    
    def record_trade(self, price: float, quantity: int) -> None:
        """
        Record trade execution.
        
        Args:
            price: Trade price
            quantity: Trade quantity
        """
        trade = Trade(price=price, quantity=quantity)
        self.trades.append(trade)
        
        # Reduce quantity at price level (try bids first, then asks)
        for book in [self.bids, self.asks]:
            if price in book:
                qty, count = book[price]
                new_qty = max(0, qty - quantity)
                if new_qty == 0:
                    del book[price]
                else:
                    book[price] = (new_qty, count)
                break
    
    def get_snapshot(self) -> OrderBookSnapshot:
        """
        Get current order book snapshot.
        
        Returns:
            OrderBookSnapshot with sorted price levels
        """
        # Sort bids descending (highest first)
        sorted_bids = sorted(
            [PriceLevel(price=p, quantity=q, order_count=c) 
             for p, (q, c) in self.bids.items()],
            key=lambda x: x.price,
            reverse=True
        )[:self.max_depth]
        
        # Sort asks ascending (lowest first)
        sorted_asks = sorted(
            [PriceLevel(price=p, quantity=q, order_count=c) 
             for p, (q, c) in self.asks.items()],
            key=lambda x: x.price
        )[:self.max_depth]
        
        return OrderBookSnapshot(
            symbol=self.symbol,
            timestamp=datetime.now(timezone.utc),
            bids=sorted_bids,
            asks=sorted_asks,
            sequence=self._sequence,
        )
    
    def get_spread(self) -> Optional[float]:
        """
        Calculate bid-ask spread.
        
        Returns:
            Spread (ask - bid) or None if book is empty
        """
        if not self.bids or not self.asks:
            return None
        
        best_bid = max(self.bids.keys())
        best_ask = min(self.asks.keys())
        
        return best_ask - best_bid
    
    def get_mid_price(self) -> Optional[float]:
        """
        Calculate mid price.
        
        Returns:
            (best_bid + best_ask) / 2 or None if book is empty
        """
        spread = self.get_spread()
        if spread is None:
            return None
        
        best_bid = max(self.bids.keys())
        return best_bid + spread / 2
    
    @property
    def order_count(self) -> int:
        """Get total number of orders in book."""
        return len(self.orders)
    
    def clear(self) -> None:
        """Clear all orders, trades, and events."""
        self.bids.clear()
        self.asks.clear()
        self.orders.clear()
        self.trades.clear()
        self._events.clear()
        self._sequence = 0
    
    def __repr__(self) -> str:
        return (
            f"OrderBookEngine(symbol={self.symbol!r}, "
            f"bids={len(self.bids)}, asks={len(self.asks)}, "
            f"orders={self.order_count})"
        )
