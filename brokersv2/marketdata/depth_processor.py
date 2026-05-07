"""L2/L3 depth processor with orderbook reconstruction and metrics."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Optional
from collections import deque

from brokersv2.domain.market.events import DepthEvent, DepthLevel


class BookState(Enum):
    """Orderbook state classification."""
    BUY_PRESSURE = "BUY_PRESSURE"
    SELL_PRESSURE = "SELL_PRESSURE"
    BALANCED = "BALANCED"


class DepthProcessorError(Exception):
    """Base exception for depth processor errors."""
    pass


class StaleDepthError(DepthProcessorError):
    """Raised when depth event is stale."""
    pass


class InvalidDepthEvent(DepthProcessorError):
    """Raised when depth event is invalid (out of order, wrong security, etc.)."""
    pass


@dataclass(frozen=True)
class OrderBookLevel:
    """Single level in the orderbook."""
    price: Decimal
    quantity: int
    orders: int


@dataclass(frozen=True)
class OrderBookSnapshot:
    """Snapshot of orderbook at a point in time."""
    security_id: str
    symbol: str
    exchange: str
    timestamp: datetime
    sequence: int
    is_snapshot: bool
    book: "OrderBook"


@dataclass
class OrderBook:
    """Real-time orderbook representation."""
    security_id: str
    symbol: str
    exchange: str
    timestamp: datetime
    sequence: int
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]

    @classmethod
    def from_depth_event(cls, event: DepthEvent) -> "OrderBook":
        """Create OrderBook from depth event."""
        bids = tuple(
            OrderBookLevel(price=level.price, quantity=level.quantity, orders=level.orders)
            for level in event.bids
        )
        asks = tuple(
            OrderBookLevel(price=level.price, quantity=level.quantity, orders=level.orders)
            for level in event.asks
        )
        return cls(
            security_id=event.security_id,
            symbol=event.symbol,
            exchange=event.exchange,
            timestamp=event.timestamp,
            sequence=event.sequence,
            bids=bids,
            asks=asks,
        )

    @property
    def best_bid(self) -> Optional[OrderBookLevel]:
        """Get best bid level."""
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> Optional[OrderBookLevel]:
        """Get best ask level."""
        return self.asks[0] if self.asks else None

    @property
    def mid_price(self) -> Optional[Decimal]:
        """Calculate mid price."""
        if self.best_bid and self.best_ask:
            return (self.best_bid.price + self.best_ask.price) / Decimal("2")
        return None

    @property
    def spread(self) -> Optional[Decimal]:
        """Calculate spread."""
        if self.best_bid and self.best_ask:
            return self.best_ask.price - self.best_bid.price
        return None

    @property
    def spread_bps(self) -> Optional[float]:
        """Calculate spread in basis points."""
        if self.best_bid and self.best_ask and self.best_bid.price > 0:
            spread = self.best_ask.price - self.best_bid.price
            return float(spread / self.best_bid.price * 10000)
        return None

    @property
    def total_bid_quantity(self) -> int:
        """Total bid quantity across all levels."""
        return sum(level.quantity for level in self.bids)

    @property
    def total_ask_quantity(self) -> int:
        """Total ask quantity across all levels."""
        return sum(level.quantity for level in self.asks)

    @property
    def imbalance(self) -> float:
        """Calculate book imbalance (-1 to +1)."""
        total = self.total_bid_quantity + self.total_ask_quantity
        if total == 0:
            return 0.0
        return (self.total_bid_quantity - self.total_ask_quantity) / total

    @property
    def weighted_mid_price(self) -> Optional[Decimal]:
        """Calculate volume-weighted mid price."""
        if self.best_bid and self.best_ask:
            bid_weight = self.best_ask.quantity
            ask_weight = self.best_bid.quantity
            total_weight = bid_weight + ask_weight
            if total_weight > 0:
                return (
                    self.best_bid.price * bid_weight +
                    self.best_ask.price * ask_weight
                ) / total_weight
        return None

    @property
    def book_state(self) -> BookState:
        """Determine book state based on quantity imbalance."""
        bid_qty = self.total_bid_quantity
        ask_qty = self.total_ask_quantity
        total = bid_qty + ask_qty

        if total == 0:
            return BookState.BALANCED

        imbalance = abs(bid_qty - ask_qty) / total

        if imbalance < 0.1:  # Within 10%
            return BookState.BALANCED
        elif bid_qty > ask_qty:
            return BookState.BUY_PRESSURE
        else:
            return BookState.SELL_PRESSURE


class DepthProcessor:
    """
    Processes L2/L3 depth events and maintains real-time orderbook state.
    
    Features:
    - Sequence validation and gap detection
    - Stale event detection
    - Orderbook reconstruction
    - Book state tracking
    - Historical snapshots
    """

    def __init__(
        self,
        security_id: str,
        stale_threshold_seconds: float = 5.0,
        max_sequence_gap: int = 10,
        history_size: int = 100,
    ):
        self._security_id = security_id
        self._stale_threshold = timedelta(seconds=stale_threshold_seconds)
        self._max_sequence_gap = max_sequence_gap
        self._history_size = history_size

        self._current_book: Optional[OrderBook] = None
        self._last_timestamp: Optional[datetime] = None
        self._last_sequence: int = 0
        self._history: deque[OrderBookSnapshot] = deque(maxlen=history_size)
        self._total_updates: int = 0

    def process_depth(self, event: DepthEvent) -> Optional[OrderBookSnapshot]:
        """
        Process a depth event and update orderbook.
        
        Returns OrderBookSnapshot if successful.
        Raises:
            - DepthProcessorError: security_id mismatch
            - InvalidDepthEvent: out of order or sequence gap
            - StaleDepthError: event timestamp is stale
        """
        # Validate security ID
        if event.security_id != self._security_id:
            raise DepthProcessorError(
                f"security_id mismatch: expected {self._security_id}, "
                f"got {event.security_id}"
            )

        # Check for stale events
        if self._last_timestamp is not None:
            time_diff = event.timestamp - self._last_timestamp
            if time_diff > self._stale_threshold:
                raise StaleDepthError(
                    f"Stale depth event: {time_diff.total_seconds():.1f}s > "
                    f"{self._stale_threshold.total_seconds():.1f}s threshold"
                )

        # Sequence validation (skip for snapshots if first event)
        if self._last_sequence > 0 or not event.is_snapshot:
            if event.sequence <= self._last_sequence:
                raise InvalidDepthEvent(
                    f"Out of order depth event: sequence {event.sequence} <= "
                    f"last {self._last_sequence}"
                )

            # Check for sequence gaps
            if not event.is_snapshot:
                gap = event.sequence - self._last_sequence
                if gap > self._max_sequence_gap:
                    raise InvalidDepthEvent(
                        f"Sequence gap too large: {gap} > {self._max_sequence_gap}"
                    )

        # Build orderbook
        book = OrderBook.from_depth_event(event)

        # Update state
        self._current_book = book
        self._last_timestamp = event.timestamp
        self._last_sequence = event.sequence
        self._total_updates += 1

        # Create snapshot
        snapshot = OrderBookSnapshot(
            security_id=event.security_id,
            symbol=event.symbol,
            exchange=event.exchange,
            timestamp=event.timestamp,
            sequence=event.sequence,
            is_snapshot=event.is_snapshot,
            book=book,
        )

        # Add to history
        self._history.append(snapshot)

        return snapshot

    def get_current_book(self) -> Optional[OrderBook]:
        """Get current orderbook state."""
        return self._current_book

    def get_book_history(self, limit: Optional[int] = None) -> list[OrderBookSnapshot]:
        """Get historical book snapshots."""
        if limit is None:
            return list(self._history)
        return list(self._history)[-limit:]

    def get_metrics(self) -> dict:
        """Get depth processor metrics."""
        book = self._current_book
        return {
            "security_id": self._security_id,
            "total_updates": self._total_updates,
            "current_sequence": self._last_sequence,
            "best_bid": {
                "price": str(book.best_bid.price),
                "quantity": book.best_bid.quantity,
                "orders": book.best_bid.orders,
            } if book and book.best_bid else None,
            "best_ask": {
                "price": str(book.best_ask.price),
                "quantity": book.best_ask.quantity,
                "orders": book.best_ask.orders,
            } if book and book.best_ask else None,
            "spread": str(book.spread) if book and book.spread else None,
            "spread_bps": book.spread_bps if book else None,
            "imbalance": book.imbalance if book else None,
            "book_state": book.book_state.value if book else None,
        }
