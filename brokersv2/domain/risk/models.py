"""
Risk domain models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, TYPE_CHECKING

from brokersv2.core.types import Symbol

if TYPE_CHECKING:
    from brokersv2.domain.instrument.models import CanonicalInstrument


@dataclass
class RiskLimits:
    """Portfolio-level risk limits."""
    max_position_size: Decimal = Decimal("1000000")  # Max exposure per position
    max_daily_loss: Decimal = Decimal("50000")  # Daily loss limit
    max_orders_per_second: int = 10
    max_open_orders: int = 50
    max_positions: int = 100

    # Order constraints
    min_price: Decimal = Decimal("0.01")
    max_price: Decimal = Decimal("1000000")

    # Price deviation bands
    # NSE index derivatives (F&O): ±5% intraday band per SEBI circular
    price_deviation_pct: Decimal = Decimal("5")
    # Equity cash segment: ±10% circuit breaker applies
    equity_price_deviation_pct: Decimal = Decimal("10")


@dataclass
class PositionRisk:
    """Risk state for a single position."""
    instrument: "CanonicalInstrument"
    quantity: Decimal
    avg_price: Decimal
    current_price: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal = Decimal("0")
    
    # Risk metrics
    exposure: Decimal = field(init=False)
    pnl_pct: Decimal = field(init=False)
    
    def __post_init__(self):
        self.exposure = abs(self.quantity) * self.avg_price
        if self.avg_price > 0:
            self.pnl_pct = ((self.current_price - self.avg_price) / self.avg_price) * 100 * (
                1 if self.quantity > 0 else -1
            )
        else:
            self.pnl_pct = Decimal("0")


@dataclass
class RiskViolation:
    """Risk violation event."""
    violation_type: str  # "position_limit", "daily_loss", "duplicate_order", etc.
    instrument: Optional[Symbol] = None
    current_value: Optional[Decimal] = None
    limit_value: Optional[Decimal] = None
    message: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    
    def is_blocking(self) -> bool:
        """Check if this violation should block order execution."""
        blocking_types = ["position_limit", "daily_loss", "duplicate_order", "freeze_quantity"]
        return self.violation_type in blocking_types


@dataclass
class RiskCheckResult:
    """Result of a risk check."""
    approved: bool
    violations: list = field(default_factory=list)
    reasons: list = field(default_factory=list)