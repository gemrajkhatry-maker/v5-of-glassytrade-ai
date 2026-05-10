"""
OMS Advanced - Super Orders (TWAP/VWAP Execution).

Algorithmic execution strategies for large orders.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from brokersv2.core.constants import SuperOrder as SuperOrderConstants


class SuperOrderType(Enum):
    """Super order execution types."""
    TWAP = "twap"  # Time-Weighted Average Price
    VWAP = "vwap"  # Volume-Weighted Average Price


class SuperOrderState(Enum):
    """Super order states."""
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class TWAPConfig:
    """TWAP execution configuration."""
    total_quantity: int
    duration_minutes: int
    slice_interval_seconds: int = SuperOrderConstants.DEFAULT_SLICE_INTERVAL

    @property
    def num_slices(self) -> int:
        """Calculate number of time slices."""
        return int(self.duration_minutes * 60 / self.slice_interval_seconds)

    @property
    def slice_quantity(self) -> int:
        """Calculate quantity per slice."""
        return max(1, self.total_quantity // self.num_slices)


@dataclass
class VWAPConfig:
    """VWAP execution configuration."""
    total_quantity: int
    participation_rate: float  # 0.0 to 1.0
    max_slice_quantity: Optional[int] = None


@dataclass
class ChildOrder:
    """Child order from super order slicing."""
    child_id: str
    price: float
    quantity: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SuperOrder:
    """Super order with algorithmic execution."""
    order_id: str
    symbol: str
    side: str
    order_type: SuperOrderType
    config: TWAPConfig | VWAPConfig
    state: SuperOrderState = SuperOrderState.ACTIVE
    total_quantity: int = 0
    filled_quantity: int = 0
    child_orders: List[ChildOrder] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        """Set total quantity from config."""
        self.total_quantity = self.config.total_quantity

    def calculate_next_slice(self, market_volume: Optional[int] = None) -> int:
        """
        Calculate next slice size.
        
        Args:
            market_volume: Current market volume (for VWAP)
        
        Returns:
            Slice quantity
        """
        remaining = self.total_quantity - self.filled_quantity
        
        if self.order_type == SuperOrderType.TWAP:
            return min(self.config.slice_quantity, remaining)
        
        elif self.order_type == SuperOrderType.VWAP:
            if market_volume is None:
                return min(SuperOrderConstants.DEFAULT_VWAP_SLICE, remaining)  # Default slice
            
            slice_qty = int(market_volume * self.config.participation_rate)
            
            if self.config.max_slice_quantity:
                slice_qty = min(slice_qty, self.config.max_slice_quantity)
            
            return min(slice_qty, remaining)
        
        return remaining

    def add_child_order(self, child: ChildOrder) -> None:
        """Add child order and update fill."""
        self.child_orders.append(child)
        self.filled_quantity += child.quantity
        self.updated_at = datetime.now(timezone.utc)
        
        if self.filled_quantity >= self.total_quantity:
            self.state = SuperOrderState.COMPLETED


class SuperOrderEngine:
    """
    Manage super orders with TWAP/VWAP execution.
    
    Features:
    - TWAP time-based slicing
    - VWAP volume-participation execution
    - Child order management
    - Execution monitoring
    - Auto-completion on full fill
    
    Usage:
        engine = SuperOrderEngine()
        
        # Submit TWAP order
        config = TWAPConfig(total_quantity=1000, duration_minutes=60)
        order = engine.submit_order("super_1", "RELIANCE", "BUY", SuperOrderType.TWAP, config)
        
        # Record child execution
        engine.record_child_order("super_1", "child_1", 2500.0, 16)
        
        # Monitor progress
        progress = engine.get_execution_progress("super_1")
    """
    
    def __init__(self):
        """Initialize super order engine."""
        self._orders: Dict[str, SuperOrder] = {}
    
    def submit_order(
        self,
        order_id: str,
        symbol: str,
        side: str,
        order_type: SuperOrderType,
        config: TWAPConfig | VWAPConfig,
    ) -> SuperOrder:
        """
        Submit new super order.
        
        Args:
            order_id: Unique order ID
            symbol: Trading symbol
            side: "BUY" or "SELL"
            order_type: TWAP or VWAP
            config: Execution configuration
        
        Returns:
            Created SuperOrder
        
        Raises:
            ValueError: If order_id already exists
        """
        if order_id in self._orders:
            raise ValueError(f"Order {order_id} already exists")
        
        order = SuperOrder(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            config=config,
        )
        
        self._orders[order_id] = order
        return order
    
    def cancel_order(self, order_id: str) -> None:
        """Cancel super order."""
        if order_id in self._orders:
            self._orders[order_id].state = SuperOrderState.CANCELLED
    
    def record_child_order(
        self,
        order_id: str,
        child_id: str,
        price: float,
        quantity: int,
    ) -> None:
        """
        Record child order execution.
        
        Args:
            order_id: Parent super order ID
            child_id: Child order ID
            price: Fill price
            quantity: Fill quantity
        """
        if order_id not in self._orders:
            return
        
        child = ChildOrder(
            child_id=child_id,
            price=price,
            quantity=quantity,
        )
        
        self._orders[order_id].add_child_order(child)
    
    def get_order(self, order_id: str) -> Optional[SuperOrder]:
        """Get order by ID."""
        return self._orders.get(order_id)
    
    def get_active_orders(self, symbol: Optional[str] = None) -> List[SuperOrder]:
        """
        Get all active super orders.
        
        Args:
            symbol: Filter by symbol (optional)
        
        Returns:
            List of active SuperOrders
        """
        active = [
            order for order in self._orders.values()
            if order.state == SuperOrderState.ACTIVE
        ]
        
        if symbol:
            active = [o for o in active if o.symbol == symbol]
        
        return active
    
    def get_execution_progress(self, order_id: str) -> Optional[dict]:
        """
        Get execution progress.
        
        Args:
            order_id: Super order ID
        
        Returns:
            Dict with filled, remaining, percent_complete
        """
        if order_id not in self._orders:
            return None
        
        order = self._orders[order_id]
        filled = order.filled_quantity
        total = order.total_quantity
        
        return {
            "filled": filled,
            "remaining": total - filled,
            "percent_complete": (filled / total * 100) if total > 0 else 0,
        }
    
    def get_average_fill_price(self, order_id: str) -> Optional[float]:
        """
        Calculate average fill price.
        
        Args:
            order_id: Super order ID
        
        Returns:
            Average fill price or None
        """
        if order_id not in self._orders:
            return None
        
        order = self._orders[order_id]
        
        if not order.child_orders:
            return 0.0
        
        total_value = sum(child.price * child.quantity for child in order.child_orders)
        total_quantity = sum(child.quantity for child in order.child_orders)
        
        if total_quantity == 0:
            return 0.0
        
        return total_value / total_quantity
    
    def clear_all(self) -> None:
        """Clear all super orders."""
        self._orders.clear()
