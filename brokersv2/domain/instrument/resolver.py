"""
Instrument Resolver - High-level instrument resolution utilities.

Provides convenient methods for:
- Resolving instruments from various formats
- ATM/OTM/ITM strike calculations
- Nearest expiry resolution
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from brokersv2.core.types import Exchange, OptionType
from brokersv2.domain.instrument.models import CanonicalInstrument
from brokersv2.domain.instrument.registry import InstrumentRegistry


class InstrumentResolver:
    """
    High-level instrument resolution utilities.
    
    Wraps InstrumentRegistry with convenience methods for common operations.
    """
    
    def __init__(self, registry: InstrumentRegistry):
        """
        Initialize resolver with registry.
        
        Args:
            registry: InstrumentRegistry instance
        """
        self._registry = registry
    
    def resolve(self, symbol_str: str) -> Optional[CanonicalInstrument]:
        """
        Resolve instrument from symbol string (e.g., "NSE:RELIANCE").
        
        Args:
            symbol_str: Symbol string in "EXCHANGE:SYMBOL" format
            
        Returns:
            CanonicalInstrument or None
        """
        if ":" in symbol_str:
            exchange_str, symbol = symbol_str.split(":", 1)
            try:
                exchange = Exchange(exchange_str.upper())
                return self._registry.lookup_by_symbol(symbol, exchange)
            except ValueError:
                return None
        else:
            # Try default exchange (NSE)
            return self._registry.lookup_by_symbol(symbol_str, Exchange.NSE)
    
    def resolve_option(
        self,
        underlying: str,
        expiry: Optional[date],
        strike: Decimal,
        option_type: OptionType,
        exchange: Exchange = Exchange.NSE,
    ) -> Optional[CanonicalInstrument]:
        """
        Resolve option instrument.
        
        If expiry is None, resolves to nearest expiry.
        
        Args:
            underlying: Underlying symbol (e.g., "NIFTY")
            expiry: Expiry date (None for nearest)
            strike: Strike price
            option_type: CALL or PUT
            exchange: Exchange
            
        Returns:
            CanonicalInstrument or None
        """
        if expiry is None:
            # Find nearest expiry
            expiries = self._registry.get_expiries(underlying, exchange)
            if not expiries:
                return None
            expiry = min(expiries)
        
        # Get options chain for this expiry
        chain = self._registry.get_options_chain(underlying, exchange, expiry)
        
        # Find matching strike and type
        for instrument in chain:
            if (instrument.strike == strike and 
                instrument.option_type == option_type):
                return instrument
        
        return None
    
    def get_atm_strike(
        self,
        underlying: str,
        exchange: Exchange,
        expiry: date,
        underlying_price: Decimal,
    ) -> Optional[Decimal]:
        """
        Calculate ATM strike for given underlying price.
        
        ATM = nearest available strike to underlying price.
        
        Args:
            underlying: Underlying symbol
            exchange: Exchange
            expiry: Expiry date
            underlying_price: Current underlying price
            
        Returns:
            ATM strike price or None
        """
        chain = self._registry.get_options_chain(underlying, exchange, expiry)
        if not chain:
            return None
        
        # Get unique strikes
        strikes = sorted(set(inst.strike for inst in chain))
        
        # Find nearest strike
        return min(strikes, key=lambda s: abs(s - underlying_price))
    
    def get_otm_strikes(
        self,
        underlying: str,
        exchange: Exchange,
        expiry: date,
        underlying_price: Decimal,
        distance: int = 1,
    ) -> tuple[Optional[Decimal], Optional[Decimal]]:
        """
        Get OTM (Out of The Money) strikes.
        
        OTM Call = ATM + (distance * step_size)
        OTM Put  = ATM - (distance * step_size)
        
        Args:
            underlying: Underlying symbol
            exchange: Exchange
            expiry: Expiry date
            underlying_price: Current price
            distance: Steps from ATM
            
        Returns:
            Tuple of (OTM call strike, OTM put strike)
        """
        atm = self.get_atm_strike(underlying, exchange, expiry, underlying_price)
        if atm is None:
            return None, None
        
        chain = self._registry.get_options_chain(underlying, exchange, expiry)
        if not chain:
            return None, None
        
        strikes = sorted(set(inst.strike for inst in chain))
        atm_idx = strikes.index(atm)
        
        # OTM Call (higher strike)
        otm_call_idx = atm_idx + distance
        otm_call = strikes[otm_call_idx] if otm_call_idx < len(strikes) else None
        
        # OTM Put (lower strike)
        otm_put_idx = atm_idx - distance
        otm_put = strikes[otm_put_idx] if otm_put_idx >= 0 else None
        
        return otm_call, otm_put
    
    def get_itm_strikes(
        self,
        underlying: str,
        exchange: Exchange,
        expiry: date,
        underlying_price: Decimal,
        distance: int = 1,
    ) -> tuple[Optional[Decimal], Optional[Decimal]]:
        """
        Get ITM (In The Money) strikes.
        
        ITM Call = ATM - (distance * step_size)
        ITM Put  = ATM + (distance * step_size)
        
        Args:
            underlying: Underlying symbol
            exchange: Exchange
            expiry: Expiry date
            underlying_price: Current price
            distance: Steps from ATM
            
        Returns:
            Tuple of (ITM call strike, ITM put strike)
        """
        atm = self.get_atm_strike(underlying, exchange, expiry, underlying_price)
        if atm is None:
            return None, None
        
        chain = self._registry.get_options_chain(underlying, exchange, expiry)
        if not chain:
            return None, None
        
        strikes = sorted(set(inst.strike for inst in chain))
        atm_idx = strikes.index(atm)
        
        # ITM Call (lower strike)
        itm_call_idx = atm_idx - distance
        itm_call = strikes[itm_call_idx] if itm_call_idx >= 0 else None
        
        # ITM Put (higher strike)
        itm_put_idx = atm_idx + distance
        itm_put = strikes[itm_put_idx] if itm_put_idx < len(strikes) else None
        
        return itm_call, itm_put
