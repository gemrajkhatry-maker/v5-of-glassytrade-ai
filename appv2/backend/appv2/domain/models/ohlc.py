"""OHLC candle model — float-based for high-speed computation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class OHLC:
    """Single OHLC candle with volume and delta.

    Float-based for performance. Immutable (frozen).
    """

    symbol: str
    time: str  # ISO 8601 or exchange timestamp string
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    delta: float = 0.0  # Buy vol - Sell vol (approximated for NSE)
    oi: float = 0.0  # Open interest (for futures/options)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open

    @property
    def typical_price(self) -> float:
        return (self.high + self.low + self.close) / 3.0

    def with_delta(self, new_delta: float) -> "OHLC":
        """Return copy with updated delta."""
        return OHLC(
            symbol=self.symbol,
            time=self.time,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            delta=new_delta,
            oi=self.oi,
        )
