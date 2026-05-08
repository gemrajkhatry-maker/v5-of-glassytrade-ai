"""Options Analytics events and data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional


class OptionType(Enum):
    """Option type classification."""
    CALL = "call"
    PUT = "put"


class Moneyness(Enum):
    """Option moneyness classification."""
    ITM = "in_the_money"
    ATM = "at_the_money"
    OTM = "out_of_the_money"


@dataclass(frozen=True)
class OptionContract:
    """Immutable option contract data."""
    symbol: str
    underlying: str
    strike: float
    expiry: datetime
    option_type: OptionType
    ltp: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    volume: int = 0
    open_interest: int = 0
    implied_volatility: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    
    @property
    def moneyness(self) -> Moneyness:
        """Classify option moneyness based on strike vs underlying price."""
        # Simplified - would need underlying price for accurate classification
        return Moneyness.OTM
    
    @property
    def mid_price(self) -> float:
        """Mid price between bid and ask."""
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return self.ltp
    
    @property
    def spread(self) -> float:
        """Bid-ask spread."""
        return self.ask - self.bid if (self.bid > 0 and self.ask > 0) else 0.0
    
    @property
    def spread_percentage(self) -> float:
        """Spread as percentage of mid price."""
        mid = self.mid_price
        if mid > 0:
            return (self.spread / mid) * 100.0
        return 0.0


@dataclass(frozen=False)
class StrikeLevel:
    """Single strike level with call and put."""
    strike: float
    call: Optional[OptionContract] = None
    put: Optional[OptionContract] = None
    call_oi: int = 0
    put_oi: int = 0
    call_volume: int = 0
    put_volume: int = 0
    
    @property
    def total_oi(self) -> int:
        """Total open interest at this strike."""
        return self.call_oi + self.put_oi
    
    @property
    def pcr_oi(self) -> float:
        """Put-Call ratio by OI."""
        if self.call_oi > 0:
            return self.put_oi / self.call_oi
        return 0.0
    
    @property
    def pcr_volume(self) -> float:
        """Put-Call ratio by volume."""
        if self.call_volume > 0:
            return self.put_volume / self.call_volume
        return 0.0


@dataclass(frozen=True)
class OptionChainEvent:
    """Option chain snapshot event."""
    underlying: str
    timestamp: datetime
    expiry: datetime
    strikes: List[StrikeLevel]
    atm_strike: float = 0.0
    underlying_price: float = 0.0
    
    @property
    def total_call_oi(self) -> int:
        """Total call OI across all strikes."""
        return sum(s.call_oi for s in self.strikes)
    
    @property
    def total_put_oi(self) -> int:
        """Total put OI across all strikes."""
        return sum(s.put_oi for s in self.strikes)
    
    @property
    def chain_pcr(self) -> float:
        """Chain-wide put-call ratio."""
        total_call = self.total_call_oi
        if total_call > 0:
            return self.total_put_oi / total_call
        return 0.0


@dataclass(frozen=True)
class GreeksSnapshot:
    """Greeks snapshot for an option."""
    symbol: str
    timestamp: datetime
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float = 0.0
    implied_vol: float = 0.0
    underlying_price: float = 0.0
    strike: float = 0.0


@dataclass(frozen=True)
class OIEvent:
    """Open interest change event."""
    underlying: str
    timestamp: datetime
    strike: float
    option_type: OptionType
    oi_change: int
    current_oi: int
    volume: int
    price: float


@dataclass(frozen=True)
class IVSurfaceEvent:
    """Implied volatility surface point."""
    underlying: str
    timestamp: datetime
    strike: float
    expiry: datetime
    implied_vol: float
    moneyness: float  # strike / underlying_price
    days_to_expiry: int
