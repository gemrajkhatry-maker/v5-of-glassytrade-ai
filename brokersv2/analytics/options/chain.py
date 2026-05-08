"""Option Chain Engine - Normalization and processing."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from brokersv2.analytics.options.events import (
    OptionContract,
    OptionType,
    StrikeLevel,
    OptionChainEvent,
)


class OptionChainEngine:
    """
    Option chain normalization and processing.
    
    Features:
    - Strike ladder generation
    - ATM/ITM/OTM classification
    - Expiry management
    - OI aggregation
    - PCR calculations
    """

    def __init__(self, underlying: str):
        """
        Initialize option chain engine.
        
        Args:
            underlying: Underlying symbol (e.g., 'NIFTY')
        """
        self.underlying = underlying
        self._options: List[OptionContract] = []
        self._strike_levels: Dict[float, StrikeLevel] = {}
        self._underlying_price = 0.0
        self._atm_strike = 0.0

    @property
    def strike_count(self) -> int:
        """Number of strike levels."""
        return len(self._strike_levels)

    @property
    def atm_strike(self) -> float:
        """ATM strike price."""
        return self._atm_strike

    @property
    def total_call_oi(self) -> int:
        """Total call OI across all strikes."""
        return sum(level.call_oi for level in self._strike_levels.values())

    @property
    def total_put_oi(self) -> int:
        """Total put OI across all strikes."""
        return sum(level.put_oi for level in self._strike_levels.values())

    @property
    def chain_pcr(self) -> float:
        """Chain-wide put-call ratio by OI."""
        if self.total_call_oi > 0:
            return self.total_put_oi / self.total_call_oi
        return 0.0

    def add_option(self, option: OptionContract) -> None:
        """
        Add option contract to chain.
        
        Args:
            option: Option contract
        """
        self._options.append(option)

    def build_chain(self, underlying_price: float) -> None:
        """
        Build strike levels from option contracts.
        
        Args:
            underlying_price: Current underlying price
        """
        self._underlying_price = underlying_price
        self._strike_levels.clear()
        
        # Group options by strike
        for option in self._options:
            strike = option.strike
            
            if strike not in self._strike_levels:
                self._strike_levels[strike] = StrikeLevel(strike=strike)
            
            level = self._strike_levels[strike]
            
            if option.option_type == OptionType.CALL:
                level.call = option
                level.call_oi = option.open_interest
                level.call_volume = option.volume
            else:
                level.put = option
                level.put_oi = option.open_interest
                level.put_volume = option.volume
        
        # Find ATM strike
        if self._strike_levels:
            self._atm_strike = min(
                self._strike_levels.keys(),
                key=lambda s: abs(s - underlying_price)
            )

    def get_strike_level(self, strike: float) -> Optional[StrikeLevel]:
        """
        Get strike level data.
        
        Args:
            strike: Strike price
            
        Returns:
            Strike level or None
        """
        return self._strike_levels.get(strike)

    def get_all_strikes(self) -> List[float]:
        """Get all strike prices sorted ascending."""
        return sorted(self._strike_levels.keys())

    def get_expiry_dates(self) -> List[datetime]:
        """Get unique expiry dates sorted."""
        expiries = set()
        for option in self._options:
            expiries.add(option.expiry)
        return sorted(expiries)

    def filter_by_expiry(self, expiry: datetime) -> OptionChainEngine:
        """
        Filter chain by expiry date.
        
        Args:
            expiry: Expiry date to filter
            
        Returns:
            New filtered engine
        """
        filtered = OptionChainEngine(self.underlying)
        
        for option in self._options:
            if option.expiry == expiry:
                filtered.add_option(option)
        
        if self._underlying_price > 0:
            filtered.build_chain(self._underlying_price)
        
        return filtered

    def get_chain_event(self, expiry: datetime) -> OptionChainEvent:
        """
        Get option chain as event.
        
        Args:
            expiry: Expiry date
            
        Returns:
            Option chain event
        """
        filtered = self.filter_by_expiry(expiry)
        
        strikes = []
        for strike in filtered.get_all_strikes():
            level = filtered.get_strike_level(strike)
            if level:
                strikes.append(level)
        
        return OptionChainEvent(
            underlying=self.underlying,
            timestamp=datetime.now(),
            expiry=expiry,
            strikes=strikes,
            atm_strike=self._atm_strike,
            underlying_price=self._underlying_price,
        )
