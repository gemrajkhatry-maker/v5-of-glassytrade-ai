"""Option model — represents an options contract with Greeks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OptionContract:
    """Options contract metadata."""

    symbol: str  # Dhan format: "NIFTY 20 MAR 23400 CE"
    underlying: str  # "NIFTY"
    strike_price: float
    expiry_date: str  # "2025-03-20"
    option_type: str  # "CE" or "PE"
    lot_size: int

    # Market data
    ltp: float = 0.0
    volume: float = 0.0
    oi: float = 0.0
    prev_oi: float = 0.0
    bid: float = 0.0
    ask: float = 0.0

    # Greeks (from broker API or computed)
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    iv: float = 0.0  # Implied volatility

    @property
    def spread(self) -> float:
        return self.ask - self.bid if self.ask > 0 else 0.0

    @property
    def spread_bps(self) -> float:
        if self.ltp <= 0:
            return float("inf")
        return (self.spread / self.ltp) * 10_000

    @property
    def is_liquid(self) -> bool:
        return self.oi > 0 and self.spread_bps < 100  # < 1% spread

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "underlying": self.underlying,
            "strike_price": self.strike_price,
            "expiry_date": self.expiry_date,
            "option_type": self.option_type,
            "lot_size": self.lot_size,
            "ltp": self.ltp,
            "volume": self.volume,
            "oi": self.oi,
            "bid": self.bid,
            "ask": self.ask,
            "delta": self.delta,
            "gamma": self.gamma,
            "theta": self.theta,
            "vega": self.vega,
            "iv": self.iv,
            "spread_bps": round(self.spread_bps, 1),
            "is_liquid": self.is_liquid,
        }


@dataclass(frozen=True)
class OptionChain:
    """Full option chain for one underlying + expiry."""

    underlying: str
    expiry_date: str
    spot_price: float
    options: list[OptionContract]  # All strikes, both CE and PE

    def get_ce(self, strike: float) -> OptionContract | None:
        for opt in self.options:
            if opt.strike_price == strike and opt.option_type == "CE":
                return opt
        return None

    def get_pe(self, strike: float) -> OptionContract | None:
        for opt in self.options:
            if opt.strike_price == strike and opt.option_type == "PE":
                return opt
        return None

    def get_atm_strike(self) -> float:
        """Find nearest strike to spot price."""
        if not self.options:
            return 0.0
        strikes = set(o.strike_price for o in self.options)
        return min(strikes, key=lambda s: abs(s - self.spot_price))
