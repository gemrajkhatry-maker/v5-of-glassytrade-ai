"""
Canonical instrument models - immutable, strongly-typed, exchange-agnostic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from brokersv2.core.types import (
    Exchange,
    Segment,
    InstrumentType,
    OptionType,
    InternalUid,
    Symbol,
)


@dataclass(frozen=True)
class CanonicalInstrument:
    """
    Immutable canonical instrument representation.
    
    This is the core domain model that ALL higher layers use.
    Broker-specific identifiers (security_id, exchange_segment) are NEVER exposed.
    
    Examples:
    - NSE:RELIANCE
    - NSE:NIFTY
    - NSE:NIFTY24APR25000CE
    """
    internal_uid: InternalUid
    symbol: Symbol
    exchange: Exchange
    segment: Segment
    instrument_type: InstrumentType
    lot_size: int
    tick_size: Decimal
    
    # Optional fields for derivatives
    expiry: Optional[date] = None
    strike: Optional[Decimal] = None
    option_type: Optional[OptionType] = None
    isin: Optional[str] = None
    
    # Trading session info
    freeze_quantity: Optional[int] = None
    
    def is_option(self) -> bool:
        """Check if this is an option."""
        return self.instrument_type == InstrumentType.OPTION
    
    def is_future(self) -> bool:
        """Check if this is a future."""
        return self.instrument_type == InstrumentType.FUTURE
    
    def is_equity(self) -> bool:
        """Check if this is an equity."""
        return self.instrument_type == InstrumentType.EQUITY
    
    def is_index(self) -> bool:
        """Check if this is an index."""
        return self.instrument_type == InstrumentType.INDEX
    
    def canonical_symbol(self) -> str:
        """Return canonical representation: EXCHANGE:SYMBOL"""
        return f"{self.exchange.value}:{self.symbol}"
    
    @classmethod
    def create_equity(
        cls,
        symbol: str,
        exchange: Exchange,
        lot_size: int = 1,
        tick_size: Decimal = Decimal("0.01"),
    ) -> CanonicalInstrument:
        """Factory for equity instruments."""
        return cls(
            internal_uid=InternalUid(str(uuid.uuid4())),
            symbol=Symbol(symbol),
            exchange=exchange,
            segment=Segment.EQUITY,
            instrument_type=InstrumentType.EQUITY,
            lot_size=lot_size,
            tick_size=tick_size,
        )
    
    @classmethod
    def create_option(
        cls,
        symbol: str,
        exchange: Exchange,
        expiry: date,
        strike: Decimal,
        option_type: OptionType,
        lot_size: int = 1,
        tick_size: Decimal = Decimal("0.01"),
    ) -> CanonicalInstrument:
        """Factory for option instruments."""
        return cls(
            internal_uid=InternalUid(str(uuid.uuid4())),
            symbol=Symbol(symbol),
            exchange=exchange,
            segment=Segment.FNO,
            instrument_type=InstrumentType.OPTION,
            lot_size=lot_size,
            tick_size=tick_size,
            expiry=expiry,
            strike=strike,
            option_type=option_type,
        )
    
    @classmethod
    def create_future(
        cls,
        symbol: str,
        exchange: Exchange,
        expiry: date,
        lot_size: int = 1,
        tick_size: Decimal = Decimal("0.01"),
    ) -> CanonicalInstrument:
        """Factory for future instruments."""
        return cls(
            internal_uid=InternalUid(str(uuid.uuid4())),
            symbol=Symbol(symbol),
            exchange=exchange,
            segment=Segment.FNO,
            instrument_type=InstrumentType.FUTURE,
            lot_size=lot_size,
            tick_size=tick_size,
            expiry=expiry,
        )
    
    @classmethod
    def from_symbol(
        cls,
        symbol_str: str,
        exchange: Optional[Exchange] = None,
    ) -> CanonicalInstrument:
        """
        Parse canonical symbol string "EXCHANGE:SYMBOL" into instrument.
        
        Args:
            symbol_str: String like "NSE:RELIANCE" or "RELIANCE"
            exchange: Default exchange if not in symbol_str
        
        Returns:
            CanonicalInstrument (with defaults for unknown symbols)
        """
        if ":" in symbol_str:
            parts = symbol_str.split(":", 1)
            exchange_str = parts[0].upper()
            symbol = parts[1].upper()
            exchange = Exchange(exchange_str)
        else:
            symbol = symbol_str.upper()
            if exchange is None:
                exchange = Exchange.NSE
        
        return cls(
            internal_uid=InternalUid(str(uuid.uuid4())),
            symbol=Symbol(symbol),
            exchange=exchange,
            segment=Segment.EQUITY,
            instrument_type=InstrumentType.EQUITY,
            lot_size=1,
            tick_size=Decimal("0.01"),
        )
    
    def __hash__(self) -> int:
        """Hash by internal_uid for O(1) lookups."""
        return hash(self.internal_uid)
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CanonicalInstrument):
            return NotImplemented
        return self.internal_uid == other.internal_uid