"""Tick Processor — handles market data tick processing.

Ported from backend/app/application/services/tick_processor.py (327L).
OI tracking, order book building, range bar coordination, throttled state updates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.domain.trading.model.value_objects import OHLC, OrderBook, OrderBookLevel

logger = logging.getLogger(__name__)


@dataclass
class RangeBar:
    open: float = 0
    high: float = 0
    low: float = 0
    close: float = 0
    volume: float = 0
    buy_volume: float = 0
    sell_volume: float = 0
    is_complete: bool = False


class RangeBarBuilder:
    """Builds range bars from ticks. Bar closes when price range >= threshold."""

    def __init__(self, range_size: float = 3.0):
        self._range_size = range_size
        self._current: RangeBar | None = None
        self._completed: list[RangeBar] = []

    def update(self, price: float, volume: float = 0, buy_vol: float = 0, sell_vol: float = 0) -> RangeBar | None:
        """Update with new tick. Returns completed bar if closed."""
        completed = None
        if self._current is None:
            self._current = RangeBar(open=price, high=price, low=price, close=price, volume=volume, buy_volume=buy_vol, sell_volume=sell_vol)
            return None

        self._current.high = max(self._current.high, price)
        self._current.low = min(self._current.low, price)
        self._current.close = price
        self._current.volume += volume
        self._current.buy_volume += buy_vol
        self._current.sell_volume += sell_vol

        if self._current.high - self._current.low >= self._range_size:
            self._current.is_complete = True
            completed = self._current
            self._completed.append(completed)
            # Start new bar from close
            self._current = RangeBar(open=price, high=price, low=price, close=price)
        return completed

    @property
    def current_bar(self) -> RangeBar | None:
        return self._current

    @property
    def completed_bars(self) -> list[RangeBar]:
        return list(self._completed)

    def to_bars(self, bars: list) -> list[dict]:
        result = []
        for b in bars:
            result.append({"open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume, "buyVolume": b.buy_volume, "sellVolume": b.sell_volume})
        if self._current and not self._current.is_complete:
            c = self._current
            result.append({"open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume, "buyVolume": c.buy_volume, "sellVolume": c.sell_volume})
        return result


class CandleAggregator:
    """Aggregates ticks into time-based candles for footprint analysis."""

    def __init__(self, interval_seconds: int = 60):
        self._interval = interval_seconds
        self._current: dict | None = None
        self._completed: list[dict] = []

    def update(self, price: float, volume: float, timestamp_ms: float) -> dict | None:
        completed = None
        bucket = int(timestamp_ms / 1000 / self._interval)
        if self._current is None or self._current["bucket"] != bucket:
            if self._current:
                self._current["is_complete"] = True
                completed = self._current
                self._completed.append(completed)
            self._current = {"bucket": bucket, "open": price, "high": price, "low": price, "close": price, "volume": volume, "is_complete": False}
        else:
            self._current["high"] = max(self._current["high"], price)
            self._current["low"] = min(self._current["low"], price)
            self._current["close"] = price
            self._current["volume"] += volume
        return completed


class TickProcessor:
    """Processes incoming market data ticks."""

    def __init__(self, range_default_size: float = 3.0):
        self._range_default_size = range_default_size
        self._prev_oi: dict[str, int] = {}
        self._range_builders: dict[str, RangeBarBuilder] = {}

    def track_oi(self, symbol: str, oi: int) -> dict | None:
        """Track OI changes."""
        if oi <= 0:
            return None
        prev = self._prev_oi.get(symbol, 0)
        change = oi - prev if prev > 0 else 0
        self._prev_oi[symbol] = oi
        trend = "RISING" if change > 0 else "FALLING" if change < 0 else "FLAT"
        return {"oi": oi, "oi_change": change, "oi_trend": trend}

    def get_or_create_range_builder(self, symbol: str) -> RangeBarBuilder:
        if symbol not in self._range_builders:
            self._range_builders[symbol] = RangeBarBuilder(self._range_default_size)
        return self._range_builders[symbol]

    def build_order_book(self, bids: list[tuple], asks: list[tuple]) -> OrderBook:
        return OrderBook(
            bids=tuple(OrderBookLevel(price=p, quantity=q) for p, q in bids),
            asks=tuple(OrderBookLevel(price=p, quantity=q) for p, q in asks),
        )
