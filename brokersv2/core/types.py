"""
Core types and protocols for brokersv2.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, NewType, Protocol, runtime_checkable, TYPE_CHECKING

if TYPE_CHECKING:
    from brokersv2.domain.instrument.models import CanonicalInstrument


# =============================================================================
# Exchange and Segment Types
# =============================================================================

class Exchange(str, Enum):
    """Supported exchanges."""
    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"
    BFO = "BFO"
    MCX = "MCX"
    INDEX = "INDEX"


class Segment(str, Enum):
    """Market segments."""
    EQUITY = "EQUITY"
    FNO = "FNO"  # Futures & Options
    COMMODITY = "COMMODITY"
    CURRENCY = "CURRENCY"


class InstrumentType(str, Enum):
    """Instrument types."""
    EQUITY = "EQUITY"
    FUTURE = "FUTURE"
    OPTION = "OPTION"
    INDEX = "INDEX"
    COMM = "COMM"


class OptionType(str, Enum):
    """Option types."""
    CALL = "CE"
    PUT = "PE"


class OrderSide(str, Enum):
    """Order side."""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Order types."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SLM = "SLM"


class OrderStatus(str, Enum):
    """Order lifecycle states."""
    NEW = "NEW"
    VALIDATED = "VALIDATED"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


# =============================================================================
# Domain Primitives
# =============================================================================

# Using NewType for type safety while maintaining simplicity
Symbol = NewType('Symbol', str)
SecurityId = NewType('SecurityId', str)
OrderId = NewType('OrderId', str)
PositionId = NewType('PositionId', str)
CorrelationId = NewType('CorrelationId', str)
InternalUid = NewType('InternalUid', str)


# =============================================================================
# Core Interfaces (Protocols)
# =============================================================================

@runtime_checkable
class IInstrumentMapper(Protocol):
    """Instrument mapping interface - core translation boundary."""
    
    def canonical_to_security_id(self, instrument: CanonicalInstrument) -> SecurityId:
        """Translate canonical instrument to broker security ID."""
        ...
    
    def security_id_to_canonical(self, security_id: SecurityId) -> Optional[CanonicalInstrument]:
        """Translate broker security ID to canonical instrument."""
        ...
    
    def symbol_to_canonical(self, symbol: str, exchange: Exchange) -> Optional[CanonicalInstrument]:
        """Translate symbol/exchange to canonical instrument."""
        ...
    
    def canonical_to_broker_mapping(self, instrument: CanonicalInstrument) -> Dict:
        """Get full broker-specific mapping for instrument."""
        ...