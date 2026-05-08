"""
Incremental Update Handler for L2 market data.

Processes incremental order book updates:
- Apply deltas to existing book state
- Handle order additions, modifications, cancellations
- Maintain book consistency
- Detect and handle gaps in update stream
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple
from decimal import Decimal

logger = logging.getLogger(__name__)


class UpdateType(Enum):
    """Type of order book update."""
    ADD = "add"  # New order added
    MODIFY = "modify"  # Existing order modified (quantity/price)
    CANCEL = "cancel"  # Order cancelled
    TRADE = "trade"  # Trade executed (order filled)
    SNAPSHOT = "snapshot"  # Full book snapshot (reset)


@dataclass
class OrderUpdate:
    """Individual order update."""
    
    order_id: str
    update_type: UpdateType
    price: Decimal
    quantity: int
    side: str  # "bid" or "ask"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    trade_price: Optional[Decimal] = None  # For trade updates
    trade_quantity: Optional[int] = None  # For trade updates


@dataclass
class IncrementalBatch:
    """Batch of incremental updates."""
    
    security_id: str
    symbol: str
    sequence_start: int
    sequence_end: int
    updates: List[OrderUpdate] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    @property
    def update_count(self) -> int:
        """Number of updates in batch."""
        return len(self.updates)
    
    @property
    def has_gap(self) -> bool:
        """Check if there's a gap in sequence."""
        if not self.updates:
            return False
        expected_range = self.sequence_end - self.sequence_start + 1
        return expected_range != self.update_count


class OrderBookState:
    """
    Maintains current state of order book from incremental updates.
    
    Tracks:
    - Bid/ask levels with order counts
    - Total quantity at each level
    - Last update sequence number
    """
    
    def __init__(self, security_id: str, symbol: str):
        self.security_id = security_id
        self.symbol = symbol
        self.last_sequence: int = 0
        self.last_update_time: Optional[datetime] = None
        
        # Order book state: price -> (quantity, order_count)
        self.bids: Dict[Decimal, Tuple[int, int]] = {}
        self.asks: Dict[Decimal, Tuple[int, int]] = {}
        
        # Order tracking: order_id -> (price, quantity, side)
        self.orders: Dict[str, Tuple[Decimal, int, str]] = {}
    
    def apply_batch(self, batch: IncrementalBatch) -> int:
        """
        Apply batch of incremental updates.
        
        Args:
            batch: Batch of updates to apply
            
        Returns:
            Number of updates applied
            
        Raises:
            SequenceGapError: If there's a gap in sequence numbers
        """
        # Check sequence continuity
        if self.last_sequence > 0 and batch.sequence_start != self.last_sequence + 1:
            raise SequenceGapError(
                f"Sequence gap detected: expected {self.last_sequence + 1}, "
                f"got {batch.sequence_start}"
            )
        
        applied = 0
        for update in batch.updates:
            self._apply_update(update)
            applied += 1
        
        self.last_sequence = batch.sequence_end
        self.last_update_time = batch.timestamp
        
        logger.debug(
            f"Applied {applied} updates to {self.symbol} "
            f"sequence={batch.sequence_start}-{batch.sequence_end}"
        )
        
        return applied
    
    def _apply_update(self, update: OrderUpdate) -> None:
        """Apply single update to book state."""
        if update.update_type == UpdateType.ADD:
            self._handle_add(update)
        elif update.update_type == UpdateType.MODIFY:
            self._handle_modify(update)
        elif update.update_type == UpdateType.CANCEL:
            self._handle_cancel(update)
        elif update.update_type == UpdateType.TRADE:
            self._handle_trade(update)
        elif update.update_type == UpdateType.SNAPSHOT:
            self._handle_snapshot(update)
    
    def _handle_add(self, update: OrderUpdate) -> None:
        """Handle new order addition."""
        book = self.bids if update.side == "bid" else self.asks
        
        # Add to book level
        if update.price in book:
            qty, count = book[update.price]
            book[update.price] = (qty + update.quantity, count + 1)
        else:
            book[update.price] = (update.quantity, 1)
        
        # Track order
        self.orders[update.order_id] = (update.price, update.quantity, update.side)
    
    def _handle_modify(self, update: OrderUpdate) -> None:
        """Handle order modification."""
        if update.order_id not in self.orders:
            logger.warning(f"Modify unknown order: {update.order_id}")
            return
        
        old_price, old_qty, side = self.orders[update.order_id]
        book = self.bids if side == "bid" else self.asks
        
        # Remove old quantity
        if old_price in book:
            qty, count = book[old_price]
            book[old_price] = (qty - old_qty, count)
            if book[old_price][1] == 0:
                del book[old_price]
        
        # Add new quantity (price may have changed)
        new_price = update.price
        if new_price in book:
            qty, count = book[new_price]
            # Only increment count if this is a different price level
            if new_price != old_price:
                book[new_price] = (qty + update.quantity, count + 1)
            else:
                # Same price, just update quantity
                book[new_price] = (qty + update.quantity, count)
        else:
            book[new_price] = (update.quantity, 1)
        
        # Update order tracking
        self.orders[update.order_id] = (new_price, update.quantity, side)
    
    def _handle_cancel(self, update: OrderUpdate) -> None:
        """Handle order cancellation."""
        if update.order_id not in self.orders:
            logger.warning(f"Cancel unknown order: {update.order_id}")
            return
        
        old_price, old_qty, side = self.orders[update.order_id]
        book = self.bids if side == "bid" else self.asks
        
        # Remove quantity from book
        if old_price in book:
            qty, count = book[old_price]
            book[old_price] = (qty - old_qty, count - 1)
            if book[old_price][1] == 0:
                del book[old_price]
        
        # Remove order tracking
        del self.orders[update.order_id]
    
    def _handle_trade(self, update: OrderUpdate) -> None:
        """Handle trade execution."""
        if update.trade_price is None or update.trade_quantity is None:
            return
        
        # Trade reduces order quantity
        if update.order_id in self.orders:
            old_price, old_qty, side = self.orders[update.order_id]
            book = self.bids if side == "bid" else self.asks
            
            new_qty = max(0, old_qty - update.trade_quantity)
            
            # Update book
            if old_price in book:
                qty, count = book[old_price]
                book[old_price] = (qty - update.trade_quantity, count)
                if book[old_price][0] <= 0:
                    del book[old_price]
            
            # Update or remove order
            if new_qty == 0:
                del self.orders[update.order_id]
            else:
                self.orders[update.order_id] = (old_price, new_qty, side)
    
    def _handle_snapshot(self, update: OrderUpdate) -> None:
        """Handle full book snapshot (reset)."""
        # Clear existing state
        self.bids.clear()
        self.asks.clear()
        self.orders.clear()
        
        # Snapshot is treated as ADD for the price level
        book = self.bids if update.side == "bid" else self.asks
        book[update.price] = (update.quantity, 1)
        self.orders[update.order_id] = (update.price, update.quantity, update.side)
    
    def get_best_bid(self) -> Optional[Tuple[Decimal, int]]:
        """Get best bid price and quantity."""
        if not self.bids:
            return None
        best_price = max(self.bids.keys())
        qty, _ = self.bids[best_price]
        return (best_price, qty)
    
    def get_best_ask(self) -> Optional[Tuple[Decimal, int]]:
        """Get best ask price and quantity."""
        if not self.asks:
            return None
        best_price = min(self.asks.keys())
        qty, _ = self.asks[best_price]
        return (best_price, qty)
    
    def get_spread(self) -> Optional[Decimal]:
        """Get bid-ask spread."""
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        if best_bid and best_ask:
            return best_ask[0] - best_bid[0]
        return None
    
    def get_mid_price(self) -> Optional[Decimal]:
        """Get mid price."""
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        if best_bid and best_ask:
            return (best_bid[0] + best_ask[0]) / 2
        return None
    
    def get_book_depth(self) -> Dict[str, int]:
        """Get total book depth."""
        bid_depth = sum(qty for qty, _ in self.bids.values())
        ask_depth = sum(qty for qty, _ in self.asks.values())
        return {
            "bid_depth": bid_depth,
            "ask_depth": ask_depth,
            "total_depth": bid_depth + ask_depth,
            "bid_levels": len(self.bids),
            "ask_levels": len(self.asks),
        }


class IncrementalUpdateHandler:
    """
    Handler for incremental order book updates.
    
    Manages:
    - Multiple order book states
    - Sequence validation
    - Gap detection and recovery
    - Book state snapshots
    
    Usage:
        handler = IncrementalUpdateHandler()
        
        # Process update batch
        handler.process_batch(batch)
        
        # Get book state
        state = handler.get_book_state("RELIANCE")
    """
    
    def __init__(self):
        self._book_states: Dict[str, OrderBookState] = {}
        self._stats = {
            "batches_received": 0,
            "updates_applied": 0,
            "gaps_detected": 0,
            "errors": 0,
        }
    
    def process_batch(self, batch: IncrementalBatch) -> int:
        """
        Process batch of incremental updates.
        
        Args:
            batch: Batch to process
            
        Returns:
            Number of updates applied
        """
        self._stats["batches_received"] += 1
        
        try:
            # Get or create book state
            if batch.security_id not in self._book_states:
                self._book_states[batch.security_id] = OrderBookState(
                    security_id=batch.security_id,
                    symbol=batch.symbol,
                )
            
            state = self._book_states[batch.security_id]
            
            # Apply batch
            applied = state.apply_batch(batch)
            self._stats["updates_applied"] += applied
            
            return applied
            
        except SequenceGapError as e:
            self._stats["gaps_detected"] += 1
            logger.error(f"Sequence gap: {e}")
            raise
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Error processing batch: {e}")
            raise
    
    def get_book_state(self, security_id: str) -> Optional[OrderBookState]:
        """Get order book state for security."""
        return self._book_states.get(security_id)
    
    def get_active_books(self) -> List[str]:
        """Get list of securities with active books."""
        return list(self._book_states.keys())
    
    def get_stats(self) -> Dict[str, int]:
        """Get handler statistics."""
        return self._stats.copy()
    
    def reset(self) -> None:
        """Reset all book states and stats."""
        self._book_states.clear()
        self._stats = {
            "batches_received": 0,
            "updates_applied": 0,
            "gaps_detected": 0,
            "errors": 0,
        }


class SequenceGapError(Exception):
    """Raised when a gap in sequence numbers is detected."""
    pass
