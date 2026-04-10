"""Tick Processor — OI tracking, depth building, range bar management.

Processes each tick to maintain:
- Open Interest tracking (change from previous)
- 5-level order book depth
- Range bar accumulation
- Footprint delta accumulation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from collections import deque
from appv2.domain.models.tick import Tick

logger = logging.getLogger(__name__)


@dataclass
class OIState:
    symbol: str
    current_oi: float
    prev_oi: float
    oi_change: float
    oi_change_pct: float


@dataclass
class DepthState:
    symbol: str
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float
    spread: float


@dataclass
class RangeBarData:
    """Range bar: opens when price moves by 'range_size' ticks."""
    symbol: str
    open_price: float
    high: float
    low: float
    close: float
    volume: float
    tick_count: int
    is_complete: bool


class TickProcessor:
    """Processes ticks for OI tracking, depth, and range bars.

    Usage:
        proc = TickProcessor(range_size=0.5)
        result = proc.process_tick(tick)
    """

    def __init__(self, range_size: float = 0.5):
        self._range_size = range_size
        self._prev_oi: dict[str, float] = {}
        self._prev_tick: dict[str, Tick] = {}
        self._range_bars: dict[str, RangeBarData] = {}

    def process_tick(self, tick: Tick) -> dict:
        """Process a single tick and return derived data.

        Returns dict with:
            - oi: OIState or None
            - depth: DepthState
            - range_bar: RangeBarData (if bar completed) or None
        """
        result = {"oi": None, "depth": None, "range_bar": None}

        # 1. OI tracking
        if tick.oi > 0:
            prev = self._prev_oi.get(tick.symbol, 0)
            oi_change = tick.oi - prev
            result["oi"] = OIState(
                symbol=tick.symbol,
                current_oi=tick.oi,
                prev_oi=prev,
                oi_change=oi_change,
                oi_change_pct=(oi_change / prev * 100) if prev > 0 else 0,
            )
            self._prev_oi[tick.symbol] = tick.oi

        # 2. Depth state
        if tick.best_bid > 0 and tick.best_ask > 0:
            result["depth"] = DepthState(
                symbol=tick.symbol,
                bid_price=tick.best_bid,
                bid_qty=tick.best_bid_qty,
                ask_price=tick.best_ask,
                ask_qty=tick.best_ask_qty,
                spread=tick.best_ask - tick.best_bid,
            )

        # 3. Range bar accumulation
        range_bar = self._update_range_bar(tick)
        if range_bar and range_bar.is_complete:
            result["range_bar"] = range_bar
            # Start new bar
            self._start_range_bar(tick.symbol, tick.ltp)

        self._prev_tick[tick.symbol] = tick
        return result

    def _update_range_bar(self, tick: Tick) -> RangeBarData | None:
        """Update range bar for symbol. Returns completed bar if threshold hit."""
        symbol = tick.symbol

        if symbol not in self._range_bars:
            self._start_range_bar(symbol, tick.ltp)
            return None

        bar = self._range_bars[symbol]

        # Update bar
        bar.high = max(bar.high, tick.ltp)
        bar.low = min(bar.low, tick.ltp)
        bar.close = tick.ltp
        bar.volume += max(0, tick.volume - self._prev_tick.get(symbol, tick).volume) if tick.volume > 0 else 0
        bar.tick_count += 1

        # Check if range threshold hit
        if bar.high - bar.low >= self._range_size:
            bar.is_complete = True
            return bar

        return None

    def _start_range_bar(self, symbol: str, price: float) -> None:
        """Start a new range bar."""
        self._range_bars[symbol] = RangeBarData(
            symbol=symbol,
            open_price=price,
            high=price,
            low=price,
            close=price,
            volume=0.0,
            tick_count=0,
            is_complete=False,
        )

    def get_current_range_bar(self, symbol: str) -> RangeBarData | None:
        return self._range_bars.get(symbol)

    def reset(self, symbol: str = "") -> None:
        """Reset processor state."""
        if symbol:
            self._prev_oi.pop(symbol, None)
            self._prev_tick.pop(symbol, None)
            self._range_bars.pop(symbol, None)
        else:
            self._prev_oi.clear()
            self._prev_tick.clear()
            self._range_bars.clear()
