"""
Mapper Port - Protocol for symbol-to-security-id mapping.

This module defines the interface for mapping between trading symbols
and Dhan security IDs. Implementations typically use a cache or database.

Example:
    >>> from brokers.broker.dhan.ports import ISymbolMapper
    >>> from brokers.broker.dhan.domain import ExchangeSegment
    >>> 
    >>> # Get security ID for a symbol
    >>> security_id = await mapper.get_security_id("NIFTY23FEB18000CE", ExchangeSegment.NSE_FNO)
    >>> 
    >>> # Search for instruments
    >>> instruments = await mapper.search_instruments("NIFTY")
"""

from typing import Protocol, runtime_checkable, Optional, List
from datetime import date

from brokers.broker.dhan.domain import (
    ExchangeSegment,
    DhanInstrument,
)


# =============================================================================
# Symbol Mapper Protocol
# =============================================================================

@runtime_checkable
class ISymbolMapper(Protocol):
    """Protocol for symbol-to-security-id mapping.
    
    This protocol defines the interface for mapping between human-readable
    trading symbols and Dhan's internal security IDs. Implementations should:
        - Cache instrument data for performance
        - Support fuzzy search for symbol lookup
        - Handle option chain lookups by underlying and expiry
    
    All methods are async to support database/API lookups.
    
    Example:
        >>> class DhanSymbolMapper:
        ...     async def get_security_id(self, symbol: str, exchange: ExchangeSegment) -> Optional[str]:
        ...         # Lookup security ID from cache or API
        ...         pass
    """
    
    async def get_security_id(
        self, 
        symbol: str, 
        exchange: ExchangeSegment
    ) -> Optional[str]:
        """Get Dhan security ID for a trading symbol.
        
        Args:
            symbol: Trading symbol (e.g., "NIFTY23FEB18000CE")
            exchange: Exchange segment (NSE_FNO, NSE_CASH, etc.)
        
        Returns:
            Security ID if found, None otherwise
        
        Example:
            >>> security_id = await mapper.get_security_id(
            ...     "NIFTY23FEB18000CE",
            ...     ExchangeSegment.NSE_FNO
            ... )
            >>> print(security_id)  # "12345"
        """
        ...
    
    async def get_instrument(
        self, 
        security_id: str
    ) -> Optional[DhanInstrument]:
        """Get full instrument details by security ID.
        
        Args:
            security_id: Dhan security ID
        
        Returns:
            DhanInstrument if found, None otherwise
        
        Example:
            >>> instrument = await mapper.get_instrument("12345")
            >>> print(instrument.trading_symbol)  # "NIFTY23FEB18000CE"
        """
        ...
    
    async def search_instruments(
        self, 
        query: str, 
        exchange: Optional[ExchangeSegment] = None
    ) -> List[DhanInstrument]:
        """Search for instruments matching a query.
        
        Supports partial matching on trading symbol and symbol name.
        
        Args:
            query: Search query (e.g., "NIFTY", "BANK")
            exchange: Optional exchange filter
        
        Returns:
            List of matching instruments
        
        Example:
            >>> instruments = await mapper.search_instruments("NIFTY", ExchangeSegment.NSE_FNO)
            >>> for inst in instruments:
            ...     print(inst.trading_symbol)
        """
        ...
    
    async def get_option_instruments(
        self, 
        underlying: str, 
        expiry: date
    ) -> List[DhanInstrument]:
        """Get all option instruments for an underlying on a specific expiry.
        
        Args:
            underlying: Underlying symbol (e.g., "NIFTY", "BANKNIFTY")
            expiry: Expiry date
        
        Returns:
            List of option instruments (both CE and PE)
        
        Example:
            >>> from datetime import date
            >>> options = await mapper.get_option_instruments(
            ...     "NIFTY",
            ...     date(2024, 2, 22)
            ... )
        """
        ...
    
    async def refresh_cache(self) -> None:
        """Refresh the instrument cache.
        
        Should be called periodically to update instrument data
        with the latest from the exchange.
        
        Raises:
            DhanNetworkError: If refresh fails
        """
        ...
