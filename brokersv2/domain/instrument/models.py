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
    
    def underlying_symbol(self) -> str:
        """Extract underlying symbol from full symbol.
        
        For options: NIFTY29JAN24000CE -> NIFTY
        For futures: NIFTY29JANFUT -> NIFTY
        For equities: RELIANCE -> RELIANCE
        """
        if self.is_option() or self.is_future():
            # Extract underlying by removing date, strike, and option type
            # Pattern: UNDERLYING + DDMMM + STRIKE + CE/PE (or FUT)
            import re
            # Match: letters + digits + letters (date) + optional digits + optional CE/PE/FUT
            match = re.match(r'^([A-Z]+?)(?:\d{2}[A-Z]{3})', self.symbol)
            if match:
                return match.group(1)
        return self.symbol
    
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

        Segment, instrument type, and tick size are inferred from the exchange
        and symbol suffix so that F&O instruments are correctly classified
        without requiring a full registry lookup:

        - Exchange NFO / BFO  → segment = FNO
        - Exchange MCX        → segment = COMMODITY, type = COMM
        - Exchange CDS        → segment = CURRENCY
        - Symbol ends in CE/PE → type = OPTION, tick_size = 0.05
        - Symbol ends in FUT   → type = FUTURE, tick_size = 0.05
        - Otherwise            → type = EQUITY, tick_size = 0.05 (NSE default)

        For precise lot_size, freeze_quantity and tick_size use
        ``from_symbol_via_mapper()`` which resolves from the instrument registry.

        Args:
            symbol_str: String like "NSE:RELIANCE", "NFO:NIFTY24APR25000CE"
            exchange: Default exchange if not embedded in symbol_str
        """
        import re

        if ":" in symbol_str:
            parts = symbol_str.split(":", 1)
            exchange_str = parts[0].upper()
            symbol = parts[1].upper()
            exchange = Exchange(exchange_str)
        else:
            symbol = symbol_str.upper()
            if exchange is None:
                exchange = Exchange.NSE

        # --- Segment inference ---
        if exchange in (Exchange.NFO, Exchange.BFO):
            segment = Segment.FNO
        elif exchange == Exchange.MCX:
            segment = Segment.COMMODITY
        elif exchange == Exchange.CDS:
            segment = Segment.CURRENCY
        else:
            segment = Segment.EQUITY

        # --- Instrument type inference ---
        if segment == Segment.COMMODITY:
            instrument_type = InstrumentType.COMM
            tick_size = Decimal("0.01")
        elif symbol.endswith("CE") or symbol.endswith("PE"):
            instrument_type = InstrumentType.OPTION
            tick_size = Decimal("0.05")
        elif symbol.endswith("FUT"):
            instrument_type = InstrumentType.FUTURE
            tick_size = Decimal("0.05")
        elif segment == Segment.FNO:
            # F&O symbol that doesn't match CE/PE/FUT — treat as future by default
            instrument_type = InstrumentType.FUTURE
            tick_size = Decimal("0.05")
        else:
            instrument_type = InstrumentType.EQUITY
            tick_size = Decimal("0.05")

        # --- Option type ---
        option_type: Optional[OptionType] = None
        if instrument_type == InstrumentType.OPTION:
            option_type = OptionType.CALL if symbol.endswith("CE") else OptionType.PUT

        # --- Expiry parsing (best-effort, covers monthly and weekly NSE formats) ---
        # Monthly: UNDERLYING + DDMMM + STRIKE + CE/PE   e.g. NIFTY29APR25000CE
        # Weekly:  UNDERLYING + YY + M + DD + STRIKE + CE/PE  e.g. NIFTY2441825000CE
        expiry: Optional[date] = None
        if instrument_type in (InstrumentType.OPTION, InstrumentType.FUTURE):
            monthly = re.match(r'^([A-Z]+?)(\d{2}[A-Z]{3})', symbol)
            if monthly:
                try:
                    from datetime import datetime as _dt
                    expiry = _dt.strptime(monthly.group(2), "%d%b").replace(
                        year=_dt.now().year
                    ).date()
                except ValueError:
                    pass

        return cls(
            internal_uid=InternalUid(str(uuid.uuid4())),
            symbol=Symbol(symbol),
            exchange=exchange,
            segment=segment,
            instrument_type=instrument_type,
            lot_size=1,  # Registry lookup required for accurate lot size
            tick_size=tick_size,
            option_type=option_type,
            expiry=expiry,
        )

    @classmethod
    def from_symbol_via_mapper(
        cls,
        symbol_str: str,
        mapper: "IInstrumentMapper",  # type: ignore[name-defined]
        exchange: Optional[Exchange] = None,
    ) -> "CanonicalInstrument":
        """
        Resolve symbol via the instrument registry (O(1) lookup) and fall back
        to ``from_symbol()`` heuristics when not found.

        This is the preferred resolution path for any live-trading code path.
        """
        # Build the lookup key as "EXCHANGE:SYMBOL"
        if ":" in symbol_str:
            exch_str, sym = symbol_str.split(":", 1)
            exch = Exchange(exch_str.upper())
        else:
            sym = symbol_str.upper()
            exch = exchange or Exchange.NSE

        canonical = mapper.symbol_to_canonical(sym, exch)
        if canonical is not None:
            return canonical

        # Fall back to heuristic inference with a warning
        import logging as _log
        _log.getLogger(__name__).warning(
            "Instrument %s:%s not found in registry — using heuristic inference; "
            "lot_size and freeze_quantity may be incorrect.",
            exch.value, sym,
        )
        return cls.from_symbol(symbol_str, exchange=exch)
    
    def __hash__(self) -> int:
        """Hash by internal_uid for O(1) lookups."""
        return hash(self.internal_uid)
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CanonicalInstrument):
            return NotImplemented
        return self.internal_uid == other.internal_uid