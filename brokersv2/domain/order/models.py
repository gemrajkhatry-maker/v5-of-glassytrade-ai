"""
Order domain models and state machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, TYPE_CHECKING

from brokersv2.core.types import (
    OrderId,
    Symbol,
    OrderSide,
    OrderType,
    OrderStatus,
    CorrelationId,
)

if TYPE_CHECKING:
    from brokersv2.domain.instrument.models import CanonicalInstrument


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


class OrderStateMachine:
    """
    Order state machine with validation.
    
    Enforces valid state transitions:
    NEW → VALIDATED → SENT → ACKNOWLEDGED → OPEN → 
        PARTIALLY_FILLED → FILLED
                ↓
        CANCEL_PENDING → CANCELLED
                ↓
            REJECTED
                ↓
            EXPIRED
    """
    
    # Valid transitions: from_state -> list of allowed next states
    _transitions = {
        OrderStatus.NEW: [OrderStatus.VALIDATED, OrderStatus.REJECTED],
        OrderStatus.VALIDATED: [OrderStatus.SENT, OrderStatus.REJECTED],
        OrderStatus.SENT: [OrderStatus.ACKNOWLEDGED, OrderStatus.REJECTED],
        OrderStatus.ACKNOWLEDGED: [OrderStatus.OPEN, OrderStatus.REJECTED],
        OrderStatus.OPEN: [
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCEL_PENDING,
        ],
        OrderStatus.PARTIALLY_FILLED: [
            OrderStatus.FILLED,
            OrderStatus.CANCEL_PENDING,
        ],
        OrderStatus.CANCEL_PENDING: [OrderStatus.CANCELLED],
        # Terminal states - no transitions
        OrderStatus.FILLED: [],
        OrderStatus.CANCELLED: [],
        OrderStatus.REJECTED: [],
        OrderStatus.EXPIRED: [],
    }
    
    @classmethod
    def can_transition(cls, from_status: OrderStatus, to_status: OrderStatus) -> bool:
        """Check if transition is valid."""
        return to_status in cls._transitions.get(from_status, [])
    
    @classmethod
    def transition(cls, order: Order, new_status: OrderStatus, reason: Optional[str] = None) -> bool:
        """
        Perform state transition with validation.
        
        Returns True if transition was successful.
        """
        if not cls.can_transition(order.status, new_status):
            return False
        
        order.status = new_status
        order.updated_at = datetime.now()
        if reason:
            order.remarks = f"{reason}: {order.remarks}" if order.remarks else reason
        return True


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