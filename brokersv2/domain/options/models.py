"""Options domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
import logging

from brokersv2.core.types import Exchange
from brokersv2.analytics.options.events import (
    OptionContract,
    OptionType,
    StrikeLevel,
)

logger = logging.getLogger(__name__)


@dataclass
class OptionChainData:
    """
    Normalized option chain data for an underlying.
    
    Acts as a container for all option contracts across strikes
    for a specific expiry.
    """
    underlying: str
    exchange: Exchange
    expiry_index: int = 0
    raw_data: Optional[Dict[str, Any]] = None
    
    # Populated during parsing
    expiry_date: Optional[datetime] = None
    underlying_price: float = 0.0
    
    # Option contracts organized by strike
    _options: List[OptionContract] = field(default_factory=list)
    _strike_levels: Dict[float, StrikeLevel] = field(default_factory=dict)
    
    def add_option(self, option: OptionContract) -> None:
        """Add an option contract to the chain."""
        self._options.append(option)
        
        # Build or update strike level
        strike = option.strike
        if strike not in self._strike_levels:
            self._strike_levels[strike] = StrikeLevel(strike=strike)
        
        level = self._strike_levels[strike]
        
        # Assign to call or put side
        if option.option_type == OptionType.CALL:
            level.call = option
            level.call_oi = option.open_interest
            level.call_volume = option.volume
        else:
            level.put = option
            level.put_oi = option.open_interest
            level.put_volume = option.volume
    
    @property
    def strikes(self) -> List[float]:
        """Get sorted list of available strikes."""
        return sorted(self._strike_levels.keys())
    
    @property
    def strike_count(self) -> int:
        """Number of strike levels."""
        return len(self._strike_levels)
    
    def get_strike_level(self, strike: float) -> Optional[StrikeLevel]:
        """Get strike level data for a specific strike."""
        return self._strike_levels.get(strike)
    
    def get_option(self, strike: float, option_type: OptionType) -> Optional[OptionContract]:
        """Get specific option contract by strike and type."""
        level = self._strike_levels.get(strike)
        if not level:
            return None
        return level.call if option_type == OptionType.CALL else level.put
    
    @property
    def atm_strike(self) -> float:
        """Find the ATM (at-the-money) strike."""
        if not self.strikes or self.underlying_price <= 0:
            return 0.0
        
        # Find closest strike to underlying price
        return min(self.strikes, key=lambda s: abs(s - self.underlying_price))
    
    @property
    def total_call_oi(self) -> int:
        """Total call OI across all strikes."""
        return sum(level.call_oi for level in self._strike_levels.values())
    
    @property
    def total_put_oi(self) -> int:
        """Total put OI across all strikes."""
        return sum(level.put_oi for level in self._strike_levels.values())
    
    @property
    def pcr_oi(self) -> float:
        """Put-Call ratio by open interest."""
        if self.total_call_oi > 0:
            return self.total_put_oi / self.total_call_oi
        return 0.0
    
    @property
    def total_call_volume(self) -> int:
        """Total call volume across all strikes."""
        return sum(level.call_volume for level in self._strike_levels.values())
    
    @property
    def total_put_volume(self) -> int:
        """Total put volume across all strikes."""
        return sum(level.put_volume for level in self._strike_levels.values())
    
    @property
    def pcr_volume(self) -> float:
        """Put-Call ratio by volume."""
        if self.total_call_volume > 0:
            return self.total_put_volume / self.total_call_volume
        return 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "underlying": self.underlying,
            "exchange": self.exchange.value if hasattr(self.exchange, 'value') else str(self.exchange),
            "expiry_index": self.expiry_index,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "underlying_price": self.underlying_price,
            "atm_strike": self.atm_strike,
            "strike_count": self.strike_count,
            "strikes": self.strikes,
            "total_call_oi": self.total_call_oi,
            "total_put_oi": self.total_put_oi,
            "pcr_oi": self.pcr_oi,
            "total_call_volume": self.total_call_volume,
            "total_put_volume": self.total_put_volume,
            "pcr_volume": self.pcr_volume,
            "timestamp": datetime.now().isoformat(),
        }
    
    def __repr__(self) -> str:
        return (
            f"OptionChainData(underlying={self.underlying!r}, "
            f"exchange={self.exchange}, "
            f"expiry={self.expiry_date}, "
            f"strikes={self.strike_count}, "
            f"underlying_price={self.underlying_price})"
        )
