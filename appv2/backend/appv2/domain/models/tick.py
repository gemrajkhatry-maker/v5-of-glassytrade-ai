"""Tick model — matches Dhan WebSocket packet fields (rc=2/4/8)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Tick:
    """Single tick from WebSocket feed.

    Maps to Dhan rc=2 (Ticker), rc=4 (Quote), rc=8 (Full) packets.
    """

    symbol: str
    ltp: float  # Last traded price
    ltq: float = 0.0  # Last traded quantity
    ltt: str = ""  # Last traded time
    atp: float = 0.0  # Average traded price (VWAP of session)
    volume: float = 0.0  # Cumulative volume
    total_buy_qty: float = 0.0
    total_sell_qty: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0  # Previous close
    oi: float = 0.0  # Open interest
    prev_oi: float = 0.0  # Previous OI

    # Depth (rc=8 only)
    best_bid: float = 0.0
    best_ask: float = 0.0
    best_bid_qty: float = 0.0
    best_ask_qty: float = 0.0

    @property
    def spread(self) -> float:
        return self.best_ask - self.best_bid if self.best_ask > 0 else 0.0

    @property
    def mid_price(self) -> float:
        if self.best_bid > 0 and self.best_ask > 0:
            return (self.best_bid + self.best_ask) / 2.0
        return self.ltp
