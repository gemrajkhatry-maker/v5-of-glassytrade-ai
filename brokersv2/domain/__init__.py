"""
Domain layer - core business logic.
"""

# Import instrument first (no circular deps)
from brokersv2.domain.instrument import CanonicalInstrument, parse_symbol

# Then order (depends on instrument)
from brokersv2.domain.order.models import Order, OrderStateMachine, Fill

# Market models
from brokersv2.domain.market.models import Tick, Quote, MarketDepth, Candle, FullPacket

# Risk models
from brokersv2.domain.risk.models import RiskLimits, PositionRisk, RiskViolation, RiskCheckResult

__all__ = [
    # Instrument
    "CanonicalInstrument",
    "parse_symbol",
    # Order
    "Order",
    "OrderStateMachine",
    "Fill",
    # Market
    "Tick",
    "Quote",
    "MarketDepth",
    "Candle",
    "FullPacket",
    # Risk
    "RiskLimits",
    "PositionRisk",
    "RiskViolation",
    "RiskCheckResult",
]