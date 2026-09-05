"""Dhan instrument entity."""

from dataclasses import dataclass
from datetime import date
from typing import Optional

from .value_objects import ExchangeSegment, InstrumentTypeEnum, OptionType


@dataclass(frozen=True)
class DhanInstrument:
    """
    Extended instrument with Dhan-specific fields.
    
    Represents a tradeable instrument on the Dhan platform with
    all the metadata required for trading and market data operations.
    
    Attributes:
        security_id: Dhan's unique numeric identifier for this instrument.
        trading_symbol: The trading symbol (e.g., "NIFTY23FEB18000CE").
        symbol: The underlying symbol (e.g., "NIFTY").
        exchange_segment: The exchange segment this instrument belongs to.
        instrument_type: The type of instrument (equity, future, option).
        expiry_date: Expiry date for derivatives (None for equity).
        strike: Strike price for options (None for non-options).
        option_type: Option type (CE/PE) for options (None for non-options).
        lot_size: Lot size for derivatives (1 for equity).
        tick_size: Minimum price movement.
        isin: ISIN code for equities.
        segment_name: Segment name from Dhan (e.g., "NIFTY").
    
    Example:
        >>> instrument = DhanInstrument(
        ...     security_id="12345",
        ...     trading_symbol="NIFTY23FEB18000CE",
        ...     symbol="NIFTY",
        ...     exchange_segment=ExchangeSegment.NSE_FNO,
        ...     instrument_type=InstrumentTypeEnum.INDEX_OPTION,
        ...     expiry_date=date(2023, 2, 23),
        ...     strike=18000.0,
        ...     option_type=OptionType.CALL,
        ...     lot_size=65
        ... )
    """
    security_id: str
    trading_symbol: str
    symbol: str
    exchange_segment: ExchangeSegment
    instrument_type: InstrumentTypeEnum
    expiry_date: Optional[date] = None
    strike: Optional[float] = None
    option_type: Optional[OptionType] = None
    lot_size: int = 1
    tick_size: float = 0.05
    isin: Optional[str] = None
    segment_name: Optional[str] = None
    
    @property
    def is_option(self) -> bool:
        """Check if this instrument is an option."""
        return self.instrument_type.is_option
    
    @property
    def is_future(self) -> bool:
        """Check if this instrument is a future."""
        return self.instrument_type.is_future
    
    @property
    def is_equity(self) -> bool:
        """Check if this instrument is equity."""
        return self.instrument_type.is_equity
    
    @property
    def is_index(self) -> bool:
        """Check if this instrument is an index."""
        return self.instrument_type.is_index
    
    @property
    def is_derivative(self) -> bool:
        """Check if this instrument is a derivative."""
        return self.is_option or self.is_future
    
    @property
    def is_call(self) -> bool:
        """Check if this is a call option."""
        return self.option_type == OptionType.CALL
    
    @property
    def is_put(self) -> bool:
        """Check if this is a put option."""
        return self.option_type == OptionType.PUT
    
    @property
    def display_name(self) -> str:
        """Get a human-readable display name."""
        if self.trading_symbol:
            return self.trading_symbol
        return f"{self.symbol}_{self.exchange_segment.name}"
    
    def __str__(self) -> str:
        """Return string representation."""
        return self.display_name
    
    def __repr__(self) -> str:
        """Return repr."""
        return (
            f"DhanInstrument(security_id={self.security_id!r}, "
            f"trading_symbol={self.trading_symbol!r}, "
            f"symbol={self.symbol!r})"
        )
