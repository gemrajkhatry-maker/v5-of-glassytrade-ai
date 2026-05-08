"""
Order Book Engine - Core.

Full L2 order book reconstruction with price-time priority.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple


class Side(Enum):
    """Order side."""
    BID = "bid"
    ASK = "ask"


class OrderAction(Enum):
    """Order action type."""
    ADD = "add"
    MODIFY = "modify"
    CANCEL = "cancel"
    TRADE = "trade"


@dataclass
class PriceLevel:
    """Price level in order book."""
    price: float
    quantity: int
    order_count: int


@dataclass
class Trade:
    """Executed trade."""
    price: float
    quantity: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class OrderBookSnapshot:
    """Snapshot of order book state."""
    symbol: str
    bids: List[PriceLevel]
    asks: List[PriceLevel]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


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
    
    def __init__(self, symbol: str, max_depth: int = 20):
        """
        Initialize order book engine.
        
        Args:
            symbol: Trading symbol
            max_depth: Maximum price levels per side (default: 20)
        """
        self.symbol = symbol
        self.max_depth = max_depth
        
        # Price levels: price -> (quantity, order_count)
        self.bids: Dict[float, Tuple[int, int]] = {}
        self.asks: Dict[float, Tuple[int, int]] = {}
        
        # Order tracking: order_id -> (price, quantity, side)
        self.orders: Dict[str, Tuple[float, int, Side]] = {}
        
        # Trade history
        self.trades: List[Trade] = []
    
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
            bids=sorted_bids,
            asks=sorted_asks,
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
        """Clear all orders and trades."""
        self.bids.clear()
        self.asks.clear()
        self.orders.clear()
        self.trades.clear()
    
    def __repr__(self) -> str:
        return (
            f"OrderBookEngine(symbol={self.symbol!r}, "
            f"bids={len(self.bids)}, asks={len(self.asks)}, "
            f"orders={self.order_count})"
        )
