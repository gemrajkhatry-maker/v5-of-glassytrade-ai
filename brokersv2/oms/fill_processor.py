"""Fill Processor - handles partial fills, average price calculation, execution stats."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

logger = logging.getLogger(__name__)


class FillProcessorError(Exception):
    """Base exception for fill processor errors."""
    pass


class InvalidFillError(FillProcessorError):
    """Raised when fill is invalid (overfill, zero quantity, etc.)."""
    pass


@dataclass(frozen=True)
class FillRecord:
    """Record of a single fill execution."""
    order_id: str
    fill_id: str
    timestamp: datetime
    quantity: int
    price: Decimal
    commission: Decimal
    exchange_order_id: str
    sequence: int = 0

    @property
    def value(self) -> Decimal:
        """Calculate fill value (quantity × price)."""
        return Decimal(str(self.quantity)) * self.price

    @property
    def net_value(self) -> Decimal:
        """Calculate net value (value + commission)."""
        return self.value + self.commission


@dataclass
class FillStats:
    """Statistics for order fills."""
    order_id: str
    fills: List[FillRecord] = field(default_factory=list)
    ordered_quantity: int = 0

    @property
    def total_filled(self) -> int:
        """Total quantity filled."""
        return sum(fill.quantity for fill in self.fills)

    @property
    def avg_fill_price(self) -> Decimal:
        """Calculate weighted average fill price."""
        if not self.fills:
            return Decimal("0")

        total_value = sum(fill.value for fill in self.fills)
        total_qty = self.total_filled

        if total_qty == 0:
            return Decimal("0")

        return total_value / Decimal(str(total_qty))

    @property
    def total_commission(self) -> Decimal:
        """Total commission paid."""
        return sum(fill.commission for fill in self.fills)

    @property
    def fill_count(self) -> int:
        """Number of fills."""
        return len(self.fills)

    @property
    def is_complete(self) -> bool:
        """Check if order is fully filled."""
        return self.total_filled >= self.ordered_quantity

    @property
    def fill_percentage(self) -> float:
        """Calculate fill percentage."""
        if self.ordered_quantity == 0:
            return 0.0
        return (self.total_filled / self.ordered_quantity) * 100


class FillProcessor:
    """
    Processes order fills and tracks execution statistics.
    
    Features:
    - Partial fill support
    - Weighted average price calculation
    - Fill sequence tracking
    - Overfill protection
    - Commission tracking
    - Duplicate fill ID detection
    """

    def __init__(self, order_id: str, ordered_quantity: int):
        """
        Initialize fill processor.
        
        Args:
            order_id: Order identifier
            ordered_quantity: Total quantity ordered
        """
        self._order_id = order_id
        self._ordered_quantity = ordered_quantity
        self._fills: List[FillRecord] = []
        self._total_filled: int = 0
        self._sequence: int = 0
        self._fill_ids: set = set()

    def process_fill(
        self,
        fill_id: str,
        quantity: int,
        price: Decimal,
        timestamp: Optional[datetime] = None,
        commission: Decimal = Decimal("0"),
        exchange_order_id: str = "",
    ) -> FillRecord:
        """
        Process a fill execution.
        
        Args:
            fill_id: Unique fill identifier
            quantity: Fill quantity
            price: Fill price
            timestamp: Fill timestamp (default: now)
            commission: Fill commission
            exchange_order_id: Exchange order ID
            
        Returns:
            FillRecord
            
        Raises:
            InvalidFillError: If fill is invalid
        """
        # Validate quantity
        if quantity <= 0:
            raise InvalidFillError(
                f"Invalid fill quantity: {quantity} (must be > 0)"
            )

        # Check for overfill
        if self._total_filled + quantity > self._ordered_quantity:
            raise InvalidFillError(
                f"Fill would exceed ordered quantity: "
                f"{self._total_filled} + {quantity} > {self._ordered_quantity}"
            )

        # Check for duplicate fill ID
        if fill_id in self._fill_ids:
            raise InvalidFillError(f"Duplicate fill ID: {fill_id}")

        # Increment sequence
        self._sequence += 1

        # Create fill record
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        fill = FillRecord(
            order_id=self._order_id,
            fill_id=fill_id,
            timestamp=timestamp,
            quantity=quantity,
            price=price,
            commission=commission,
            exchange_order_id=exchange_order_id,
            sequence=self._sequence,
        )

        # Record fill
        self._fills.append(fill)
        self._total_filled += quantity
        self._fill_ids.add(fill_id)

        logger.info(
            f"Fill processed: {self._order_id} - {quantity} @ {price} "
            f"({self._total_filled}/{self._ordered_quantity})"
        )

        return fill

    def get_fills(self) -> List[FillRecord]:
        """Get all fills in sequence order."""
        return list(self._fills)

    def get_stats(self) -> FillStats:
        """Get fill statistics."""
        return FillStats(
            order_id=self._order_id,
            fills=self._fills,
            ordered_quantity=self._ordered_quantity,
        )

    @property
    def total_filled(self) -> int:
        """Get total filled quantity."""
        return self._total_filled

    @property
    def remaining_quantity(self) -> int:
        """Get remaining quantity to fill."""
        return self._ordered_quantity - self._total_filled

    @property
    def is_filled(self) -> bool:
        """Check if order is fully filled."""
        return self._total_filled >= self._ordered_quantity

    def reset(self):
        """Reset fill processor."""
        self._fills.clear()
        self._total_filled = 0
        self._sequence = 0
        self._fill_ids.clear()

        logger.info(f"Fill processor reset for order {self._order_id}")

    def __repr__(self) -> str:
        return (
            f"FillProcessor(order_id='{self._order_id}', "
            f"filled={self._total_filled}/{self._ordered_quantity})"
        )
