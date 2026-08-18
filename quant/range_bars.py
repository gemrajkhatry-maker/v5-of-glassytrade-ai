"""ATR-Dynamic Range Bar Generator (spec §4).

Generates volatility-scaled range bars rather than fixed-time candles, eliminating
time distortion in low-volume chop and capturing clean institutional displacement.

Spec rules:
  RangeSize = max(k * ATR_14, min_ticks * tick_size)
  where k is typically 0.25..0.50 (responsive scalping) and min_ticks >= 4.
"""

from __future__ import annotations
from collections import deque
from typing import Optional

from quant.aggregator import BarAggregator
from quant.bars import Bar
from quant.brokers.gateway import Tick


class ATRRangeCalculator:
    """Computes dynamic range bar threshold from rolling 14-period True Range."""

    def __init__(
        self,
        period: int = 14,
        atr_multiplier: float = 0.35,
        min_ticks: int = 4,
        tick_size: float = 0.05,
    ) -> None:
        self.period = period
        self.atr_multiplier = atr_multiplier
        self.min_ticks = min_ticks
        self.tick_size = tick_size
        self._prev_close: Optional[float] = None
        self._tr_history: deque[float] = deque(maxlen=period)
        self._current_range_size: float = max(min_ticks * tick_size, 0.20)

    @property
    def range_size(self) -> float:
        return self._current_range_size

    def update_bar(self, bar: Bar) -> float:
        """Update ATR on each completed bar and recompute the dynamic range threshold."""
        high = float(bar.high)
        low = float(bar.low)
        close = float(bar.close)

        if self._prev_close is None:
            tr = high - low
        else:
            tr = max(
                high - low,
                abs(high - self._prev_close),
                abs(low - self._prev_close),
            )
        self._prev_close = close
        self._tr_history.append(tr)

        if len(self._tr_history) > 0:
            atr = sum(self._tr_history) / len(self._tr_history)
            min_floor = self.min_ticks * self.tick_size
            self._current_range_size = max(self.atr_multiplier * atr, min_floor)

        return self._current_range_size


class DynamicRangeBarAggregator:
    """Aggregates ticks into ATR-scaled range bars."""

    def __init__(
        self,
        atr_period: int = 14,
        atr_multiplier: float = 0.35,
        min_ticks: int = 4,
        tick_size: float = 0.05,
    ) -> None:
        self.calculator = ATRRangeCalculator(
            period=atr_period,
            atr_multiplier=atr_multiplier,
            min_ticks=min_ticks,
            tick_size=tick_size,
        )
        self._aggregator = BarAggregator(range_size=self.calculator.range_size)

    def add_tick(self, tick: Tick) -> Optional[Bar]:
        bar = self._aggregator.add_tick(tick)
        if bar is not None:
            new_range = self.calculator.update_bar(bar)
            self._aggregator.range_size = new_range
        return bar
