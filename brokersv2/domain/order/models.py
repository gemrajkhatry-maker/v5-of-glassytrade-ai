"""
Order domain models and state machine.

The OrderStateMachine defined here is the single canonical source for
order lifecycle transition rules.  The older oms/order_machine.py is
kept as a deprecated compatibility shim for test code that directly
imported OrderState / OrderEvent / OrderStateMachine from that module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from brokersv2.core.types import (
    OrderId,
    Symbol,
    OrderSide,
    OrderType,
    OrderStatus,
    ProductType,
    OrderValidity,
    AmoTime,
    CorrelationId,
)

if TYPE_CHECKING:
    from brokersv2.domain.instrument.models import CanonicalInstrument


@dataclass(frozen=True)
class StateTransition:
    """Immutable record of a single order state transition."""
    order_id: str
    from_status: OrderStatus
    to_status: OrderStatus
    timestamp: datetime
    reason: Optional[str] = None


@dataclass
class Order:
    """
    Order aggregate root.
    
    Represents an order through its entire lifecycle.
    """
    order_id: OrderId
    instrument: "CanonicalInstrument"
    side: OrderSide
    quantity: Decimal
    order_type: OrderType = OrderType.MARKET
    price: Optional[Decimal] = None
    trigger_price: Optional[Decimal] = None

    # Indian market–specific order attributes
    product_type: ProductType = ProductType.CNC
    validity: OrderValidity = OrderValidity.DAY
    after_market_order: bool = False
    amo_time: Optional[AmoTime] = None
    disclosed_quantity: Optional[int] = None

    # Lifecycle
    status: OrderStatus = OrderStatus.NEW
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # Execution tracking
    filled_quantity: Decimal = Decimal("0")
    average_fill_price: Optional[Decimal] = None
    fills: list = field(default_factory=list)

    # Metadata
    correlation_id: Optional[CorrelationId] = None
    broker_order_id: Optional[str] = None
    remarks: Optional[str] = None
    
    @property
    def remaining_quantity(self) -> Decimal:
        """Quantity remaining to be filled."""
        return self.quantity - self.filled_quantity
    
    @property
    def is_complete(self) -> bool:
        """Check if order is in a terminal state."""
        return self.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        )
    
    def add_fill(self, quantity: Decimal, price: Decimal) -> None:
        """Record a fill."""
        self.fills.append({
            "quantity": quantity,
            "price": price,
            "timestamp": datetime.now(),
        })
        self.filled_quantity += quantity
        
        # Update average price
        if self.average_fill_price is None:
            self.average_fill_price = price
        else:
            total_cost = self.average_fill_price * (self.filled_quantity - quantity) + price * quantity
            self.average_fill_price = total_cost / self.filled_quantity
        
        if self.filled_quantity >= self.quantity:
            self.status = OrderStatus.FILLED
        else:
            self.status = OrderStatus.PARTIALLY_FILLED
        
        self.updated_at = datetime.now()
    
    def update_status(self, new_status: OrderStatus) -> bool:
        """
        Update order status with validation.
        
        Args:
            new_status: New status to transition to
            
        Returns:
            True if transition was successful, False otherwise
        """
        return OrderStateMachine.transition(self, new_status)


class OrderStateMachine:
    """
    Canonical order state machine with full transition history tracking.

    Lifecycle:
        NEW → VALIDATED → SENT → ACKNOWLEDGED → OPEN
                                                  ├→ PARTIALLY_FILLED → FILLED
                                                  ├→ FILLED
                                                  └→ CANCEL_PENDING → CANCELLED
        Any non-terminal state may also transition to REJECTED or EXPIRED.

    The classmethods (can_transition / transition) are used by the Order
    aggregate directly.  For per-order history tracking, create a machine
    instance and drive it via record_transition().
    """

    _transitions = {
        OrderStatus.NEW: [OrderStatus.VALIDATED, OrderStatus.REJECTED],
        OrderStatus.VALIDATED: [OrderStatus.SENT, OrderStatus.REJECTED],
        OrderStatus.SENT: [OrderStatus.ACKNOWLEDGED, OrderStatus.REJECTED],
        OrderStatus.ACKNOWLEDGED: [OrderStatus.OPEN, OrderStatus.REJECTED],
        OrderStatus.OPEN: [
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCEL_PENDING,
            OrderStatus.REJECTED,
        ],
        OrderStatus.PARTIALLY_FILLED: [
            OrderStatus.FILLED,
            OrderStatus.CANCEL_PENDING,
            OrderStatus.REJECTED,
        ],
        OrderStatus.CANCEL_PENDING: [OrderStatus.CANCELLED],
        # Terminal states — no further transitions.
        OrderStatus.FILLED: [],
        OrderStatus.CANCELLED: [],
        OrderStatus.REJECTED: [],
        OrderStatus.EXPIRED: [],
    }

    def __init__(self, order_id: str) -> None:
        self._order_id = order_id
        self._history: List[StateTransition] = []
        self._state_changed_at: datetime = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Class-level helpers (used by Order aggregate)
    # ------------------------------------------------------------------

    @classmethod
    def can_transition(cls, from_status: OrderStatus, to_status: OrderStatus) -> bool:
        """Return True if the transition from → to is valid."""
        return to_status in cls._transitions.get(from_status, [])

    @classmethod
    def transition(
        cls,
        order: "Order",
        new_status: OrderStatus,
        reason: Optional[str] = None,
    ) -> bool:
        """
        Perform and record a state transition on an Order aggregate.

        Returns True if the transition was applied, False if invalid.
        """
        if not cls.can_transition(order.status, new_status):
            return False

        old_status = order.status
        order.status = new_status
        order.updated_at = datetime.now()
        if reason:
            order.remarks = f"{reason}: {order.remarks}" if order.remarks else reason

        # Record in the order's machine instance if present.
        if hasattr(order, "_state_machine") and order._state_machine is not None:
            order._state_machine.record_transition(old_status, new_status, reason)

        return True

    # ------------------------------------------------------------------
    # Instance-level history (audit trail)
    # ------------------------------------------------------------------

    def record_transition(
        self,
        from_status: OrderStatus,
        to_status: OrderStatus,
        reason: Optional[str] = None,
    ) -> None:
        """Append a StateTransition to the history log."""
        self._state_changed_at = datetime.now(timezone.utc)
        self._history.append(
            StateTransition(
                order_id=self._order_id,
                from_status=from_status,
                to_status=to_status,
                timestamp=self._state_changed_at,
                reason=reason,
            )
        )

    def get_history(self) -> List[StateTransition]:
        """Return a copy of the full transition history."""
        return list(self._history)

    def time_in_state(self) -> float:
        """Seconds elapsed since the last recorded state change."""
        return (datetime.now(timezone.utc) - self._state_changed_at).total_seconds()

    def __repr__(self) -> str:
        return f"<OrderStateMachine order_id={self._order_id!r}>"


@dataclass
class Fill:
    """Fill details."""
    fill_id: str
    order_id: OrderId
    quantity: Decimal
    price: Decimal
    timestamp: datetime
    liquidity: str = "UNKNOWN"  # MAKER or TAKER
    instrument: Optional["CanonicalInstrument"] = None