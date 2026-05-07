"""Instrument Discovery - high-level search and filtering APIs."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import List, Optional, Set

from brokersv2.domain.instrument.registry import InstrumentRegistry
from brokersv2.domain.instrument.models import CanonicalInstrument
from brokersv2.core.types import Exchange, InstrumentType

logger = logging.getLogger(__name__)


class DiscoveryError(Exception):
    """Base exception for discovery errors."""
    pass


@dataclass
class SearchFilter:
    """Filter criteria for instrument search."""
    exchange: Optional[Exchange] = None
    instrument_type: Optional[InstrumentType] = None
    query: Optional[str] = None
    limit: int = 100


@dataclass
class SearchResult:
    """Result of instrument search."""
    instrument: Optional[CanonicalInstrument]
    match_score: float
    match_reason: str


class InstrumentDiscovery:
    """
    High-level instrument discovery and search APIs.
    
    Provides developer-friendly interfaces for:
    - Finding instruments by symbol, strike, expiry
    - Options chain retrieval
    - Futures chain retrieval
    - ATM strike calculation
    - Multi-criteria search
    - Active instrument filtering
    
    All operations use O(1) lookups from InstrumentRegistry.
    """

    def __init__(self, registry: InstrumentRegistry):
        """
        Initialize discovery with registry.
        
        Args:
            registry: InstrumentRegistry instance
        """
        self._registry = registry

    def find_equity(
        self,
        symbol: str,
        exchange: Exchange = Exchange.NSE,
    ) -> Optional[CanonicalInstrument]:
        """
        Find equity instrument by symbol.
        
        Args:
            symbol: Equity symbol (e.g., "RELIANCE", "TCS")
            exchange: Exchange (default: NSE)
            
        Returns:
            CanonicalInstrument or None if not found
        """
        return self._registry.lookup_by_symbol(symbol.upper(), exchange)

    def find_option(
        self,
        underlying: str,
        expiry: date,
        strike: Decimal,
        option_type: str,
        exchange: Exchange = Exchange.NFO,
    ) -> Optional[CanonicalInstrument]:
        """
        Find specific option by underlying, expiry, strike, and type.
        
        Args:
            underlying: Underlying symbol (e.g., "NIFTY", "BANKNIFTY")
            expiry: Expiry date
            strike: Strike price
            option_type: "CE" or "PE"
            exchange: Exchange (default: NFO)
            
        Returns:
            CanonicalInstrument or None if not found
        """
        # Get options chain for this expiry
        options = self._registry.get_options_chain(underlying, exchange, expiry)

        if not options:
            return None

        # Find matching strike and type
        for option in options:
            if (option.strike_price == strike and
                option.option_type and
                option.option_type.upper() == option_type.upper()):
                return option

        return None

    def get_option_chain(
        self,
        underlying: str,
        exchange: Exchange,
        expiry: date,
    ) -> List[CanonicalInstrument]:
        """
        Get full options chain for underlying and expiry.
        
        Args:
            underlying: Underlying symbol
            exchange: Exchange
            expiry: Expiry date
            
        Returns:
            List of option instruments (calls and puts)
        """
        return self._registry.get_options_chain(underlying, exchange, expiry)

    def get_futures_chain(
        self,
        underlying: str,
        exchange: Exchange,
    ) -> List[CanonicalInstrument]:
        """
        Get futures chain for underlying (all expiries).
        
        Args:
            underlying: Underlying symbol
            exchange: Exchange
            
        Returns:
            List of future instruments sorted by expiry
        """
        # Get all instruments for this exchange
        all_instruments = self._registry.get_instruments_by_exchange(exchange)

        # Filter futures for this underlying
        futures = [
            inst for inst in all_instruments
            if inst.is_future() and inst.underlying == underlying
        ]

        # Sort by expiry
        futures.sort(key=lambda x: x.expiry or date.max)

        return futures

    def get_nearest_expiry(
        self,
        underlying: str,
        exchange: Exchange,
        current_date: Optional[date] = None,
    ) -> Optional[date]:
        """
        Get nearest expiry date for underlying.
        
        Args:
            underlying: Underlying symbol
            exchange: Exchange
            current_date: Reference date (default: today)
            
        Returns:
            Nearest expiry date or None
        """
        if current_date is None:
            current_date = date.today()

        expiries = self._registry.get_expiries(underlying, exchange)

        if not expiries:
            return None

        # Find first expiry >= current_date
        for expiry in expiries:
            if expiry >= current_date:
                return expiry

        # If all expiries are in the past, return the last one
        return expiries[-1] if expiries else None

    def get_all_expiries(
        self,
        underlying: str,
        exchange: Exchange,
    ) -> List[date]:
        """
        Get all available expiry dates for underlying.
        
        Args:
            underlying: Underlying symbol
            exchange: Exchange
            
        Returns:
            Sorted list of expiry dates
        """
        return self._registry.get_expiries(underlying, exchange)

    def get_atm_strike(
        self,
        underlying: str,
        ltp: Decimal,
        exchange: Exchange,
    ) -> Optional[Decimal]:
        """
        Calculate ATM (At-The-Money) strike for given LTP.
        
        Finds the closest available strike price to the LTP.
        
        Args:
            underlying: Underlying symbol
            ltp: Last traded price
            exchange: Exchange
            
        Returns:
            ATM strike price or None
        """
        # Get all strikes from options chain
        # We'll use the nearest expiry to determine available strikes
        nearest_expiry = self.get_nearest_expiry(underlying, exchange)
        
        if not nearest_expiry:
            return None

        options = self._registry.get_options_chain(
            underlying, exchange, nearest_expiry
        )

        if not options:
            return None

        # Extract unique strikes
        strikes = set()
        for option in options:
            if option.strike_price:
                strikes.add(option.strike_price)

        if not strikes:
            return None

        # Find closest strike to LTP
        return min(strikes, key=lambda s: abs(s - ltp))

    def search_instruments(
        self,
        query: Optional[str] = None,
        exchange: Optional[Exchange] = None,
        instrument_type: Optional[InstrumentType] = None,
        limit: int = 100,
    ) -> List[CanonicalInstrument]:
        """
        Search instruments with multiple filters.
        
        Args:
            query: Symbol search query (case-insensitive)
            exchange: Filter by exchange
            instrument_type: Filter by type
            limit: Maximum results
            
        Returns:
            List of matching instruments
        """
        # Start with all instruments or filter by exchange
        if exchange:
            candidates = self._registry.get_instruments_by_exchange(exchange)
        else:
            candidates = self._registry.get_all_instruments()

        # Filter by instrument type
        if instrument_type:
            candidates = [
                inst for inst in candidates
                if inst.instrument_type == instrument_type
            ]

        # Filter by query (symbol search)
        if query:
            query_upper = query.upper()
            candidates = [
                inst for inst in candidates
                if query_upper in inst.symbol.upper()
            ]

        # Apply limit
        return candidates[:limit]

    def get_underlying_symbols(
        self,
        exchange: Optional[Exchange] = None,
    ) -> Set[str]:
        """
        Get all unique underlying symbols.
        
        Args:
            exchange: Filter by exchange (optional)
            
        Returns:
            Set of underlying symbols
        """
        if exchange:
            instruments = self._registry.get_instruments_by_exchange(exchange)
        else:
            instruments = self._registry.get_all_instruments()

        underlyings = set()
        for inst in instruments:
            if inst.underlying:
                underlyings.add(inst.underlying)
            else:
                # For equities, symbol is the underlying
                underlyings.add(inst.symbol)

        return underlyings

    def get_active_instruments(
        self,
        exchange: Exchange,
    ) -> List[CanonicalInstrument]:
        """
        Get active (non-expired) instruments for exchange.
        
        Args:
            exchange: Exchange
            
        Returns:
            List of active instruments
        """
        today = date.today()
        all_instruments = self._registry.get_instruments_by_exchange(exchange)

        # Filter out expired derivatives
        active = []
        for inst in all_instruments:
            if inst.is_equity():
                # Equities don't expire
                active.append(inst)
            elif inst.expiry and inst.expiry >= today:
                # Derivatives not yet expired
                active.append(inst)

        return active

    def get_lot_size(
        self,
        symbol: str,
        exchange: Exchange,
    ) -> Optional[int]:
        """
        Get lot size for instrument.
        
        Args:
            symbol: Instrument symbol
            exchange: Exchange
            
        Returns:
            Lot size or None if not found
        """
        instrument = self._registry.lookup_by_symbol(symbol, exchange)
        return instrument.lot_size if instrument else None

    def get_tick_size(
        self,
        symbol: str,
        exchange: Exchange,
    ) -> Optional[Decimal]:
        """
        Get tick size for instrument.
        
        Args:
            symbol: Instrument symbol
            exchange: Exchange
            
        Returns:
            Tick size or None if not found
        """
        instrument = self._registry.lookup_by_symbol(symbol, exchange)
        return instrument.tick_size if instrument else None
