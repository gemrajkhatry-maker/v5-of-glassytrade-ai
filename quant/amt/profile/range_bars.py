"""ATR-dynamic range bars (spec §4) — DynamicRangeBarAggregator.

Range bars discretize continuous time into fixed-price-height bars. A range
bar closes as soon as ``high - low >= H_range`` and the next bar opens at the
previous close. This normalizes price action: low-volume chop produces fewer
bars and volatile spikes produce more, eliminating the time-distortion of
fixed-interval candles.

Per spec §4:

    H_raw  = ATR_14(1m Klines) x kappa_scale
    H_range = Quantize(H_raw, steps)

The ``ATRRangeCalculator`` maintains a rolling True-Range ATR(14) from
completed bar closes and computes the quantized range size. The
``DynamicRangeBarAggregator`` adapts ``BarAggregator`` to update its range
size from ATR after each completed bar.

Usage::

    calc = ATRRangeCalculator(atr_period=14, scale_factor=1.0)
    aggregator = DynamicRangeBarAggregator(
        interval_seconds=60, tick_size=0.05, calc=calc,
    )
    for tick in ticks:
        bar = aggregator.add_tick(tick)
        if bar is not None:
            calc.update(bar)          # update ATR from completed bar
            aggregator.apply_range_size(calc.range_size(0.05))
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from quant.aggregator import BarAggregator
from quant.bars import Bar
from quant.brokers.gateway import Tick

logger = logging.getLogger(__name__)

# Spec §4 quantization steps for H_range (price units). These are the CME
# standard range-bar steps; Indian instruments use the same ladder scaled by
# tick. The steps are applied per-tick: e.g. step=10 with tick=0.05 -> 0.5.
_DEFAULT_QUANT_STEPS = (2, 5, 10, 25, 50, 100, 200)


def _true_range(high: float, low: float, prev_close: float) -> float:
    """True Range: max(high-low, |high-prev_close|, |low-prev_close|)."""
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def _quantize(value: float, steps: tuple[int, ...]) -> float:
    """Quantize a raw ATR value to the nearest ladder step.

    Returns the smallest step that is >= value, capped at the largest step.
    If value is smaller than the smallest step, returns the smallest step.
    """
    for step in steps:
        if value <= step:
            return float(step)
    return float(steps[-1])


class ATRRangeCalculator:
    """Computes the dynamic range-bar height H_range from a rolling ATR(14).

    The calculator ingests completed bars and maintains a rolling buffer of
    True Ranges. ``range_size()`` returns the quantized range height for the
    current ATR, floored at ``min_ticks * tick_size`` so the bar can never be
    narrower than the exchange minimum.

    Args:
        atr_period: ATR lookback (default 14 per spec).
        scale_factor: kappa_scale multiplier applied to ATR (default 1.0).
        quant_steps: integer quantization ladder (price-quantized per tick).
        min_ticks: minimum range size in ticks (default 2).
    """

    def __init__(
        self,
        atr_period: int = 14,
        scale_factor: float = 1.0,
        quant_steps: tuple[int, ...] = _DEFAULT_QUANT_STEPS,
        min_ticks: int = 2,
    ) -> None:
        self._period = max(1, atr_period)
        self._scale = max(0.1, scale_factor)
        self._steps = quant_steps
        self._min_ticks = max(1, min_ticks)
        self._true_ranges: list[float] = []
        self._prev_close: float | None = None
        self._current_size: float | None = None

    def update(self, bar: Bar) -> None:
        """Ingest a completed bar and update the rolling ATR."""
        high = float(bar.high)
        low = float(bar.low)
        close = float(bar.close)

        if self._prev_close is not None:
            tr = _true_range(high, low, self._prev_close)
            self._true_ranges.append(tr)
            # Keep only the last `period` true ranges.
            if len(self._true_ranges) > self._period:
                self._true_ranges = self._true_ranges[-self._period :]

        self._prev_close = close
        # Invalidate cached size so it is recomputed on next query.
        self._current_size = None

    def raw_atr(self) -> float:
        """Return the current ATR (SMA of True Ranges). Returns 0 if insufficient."""
        if not self._true_ranges:
            return 0.0
        return sum(self._true_ranges) / len(self._true_ranges)

    def range_size(self, tick_size: float) -> float:
        """Compute the quantized range-bar height for the current ATR.

        H_raw  = ATR x scale_factor
        H_range = max(quantize(H_raw, steps) * tick_size, min_ticks * tick_size)

        The result is cached until the next ``update()``.
        """
        if self._current_size is not None:
            return self._current_size

        atr = self.raw_atr()
        if atr <= 0 or tick_size <= 0:
            # Insufficient history: fall back to a sensible minimum.
            self._current_size = self._min_ticks * tick_size
            return self._current_size

        h_raw = atr * self._scale
        # Quantize to the ladder (steps are in tick units), then convert to
        # price units via tick_size.
        step_units = _quantize(h_raw / tick_size, self._steps)
        h_range = step_units * tick_size
        # Floor at min_ticks.
        min_size = self._min_ticks * tick_size
        self._current_size = max(h_range, min_size)
        return self._current_size

    @property
    def bars_accumulated(self) -> int:
        """Number of bars ingested so far (0 until first bar closes)."""
        return len(self._true_ranges)


@dataclass
class RangeBarStats:
    """Stats emitted by DynamicRangeBarAggregator for observability."""

    bars_formed: int = 0
    current_range_size: float = 0.0
    last_atr: float = 0.0


class DynamicRangeBarAggregator:
    """Adapts BarAggregator to use an ATR-dynamic range size.

    Wraps a ``BarAggregator`` in range mode and updates its ``range_size``
    from an ``ATRRangeCalculator`` after each completed bar. This gives the
    spec §4 behavior: range bar height tracks recent volatility.

    Args:
        interval_seconds: Fallback interval for the underlying aggregator
            (used only if range mode is disabled).
        tick_size: Instrument tick size for quantization.
        calc: ATRRangeCalculator instance. If None, a default is created.
        min_ticks: Minimum range size in ticks.
    """

    def __init__(
        self,
        interval_seconds: int = 60,
        tick_size: float = 0.05,
        calc: ATRRangeCalculator | None = None,
        min_ticks: int = 2,
    ) -> None:
        self._tick_size = tick_size
        self._calc = calc or ATRRangeCalculator(min_ticks=min_ticks)
        # Start with a minimum range; it will be updated after the first bar.
        initial_size = self._calc.range_size(tick_size)
        self._inner = BarAggregator(
            interval_seconds=interval_seconds, range_size=initial_size
        )
        self._stats = RangeBarStats(current_range_size=initial_size)

    def add_tick(self, tick: Tick) -> Bar | None:
        """Process a tick. Returns a completed Bar if one closed."""
        bar = self._inner.add_tick(tick)
        if bar is not None:
            self._on_bar_closed(bar)
        return bar

    def _on_bar_closed(self, bar: Bar) -> None:
        """Update ATR and re-apply the range size after a bar closes."""
        self._calc.update(bar)
        new_size = self._calc.range_size(self._tick_size)
        self.apply_range_size(new_size)
        self._stats.bars_formed += 1
        self._stats.current_range_size = new_size
        self._stats.last_atr = self._calc.raw_atr()

    def apply_range_size(self, size: float) -> None:
        """Apply a new range size to the underlying aggregator."""
        self._inner.range_size = size
        self._stats.current_range_size = size

    @property
    def current_bar(self) -> Bar | None:
        """The currently forming, unclosed bar."""
        return self._inner.current_bar

    @property
    def interval_seconds(self) -> int:
        """Expose the underlying aggregator's interval for consumers that
        read it (exit_manager, decision_loop) via getattr."""
        return self._inner.interval_seconds

    @property
    def stats(self) -> RangeBarStats:
        """Current stats for observability."""
        return self._stats

    @property
    def calc(self) -> ATRRangeCalculator:
        """The underlying ATR calculator."""
        return self._calc
