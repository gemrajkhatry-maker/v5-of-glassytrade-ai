"""Candle Aggregator — incremental tick-to-OHLCV builder.

Handles:
- Partial candle building from ticks
- Time-boundary detection (1-min, 5-min, 15-min)
- Delta approximation (NSE: body-ratio method; MCX: from broker data)
- Multi-timeframe simultaneous aggregation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from appv2.domain.models.tick import Tick
from appv2.domain.models.ohlc import OHLC

logger = logging.getLogger(__name__)


@dataclass
class PartialCandle:
    """In-progress candle being built from ticks."""
    symbol: str
    time: str  # Candle open time (ISO)
    open: float = 0.0
    high: float = 0.0
    low: float = float("inf")
    close: float = 0.0
    volume: float = 0.0
    prev_cum_volume: float = 0.0  # Cumulative volume at start of candle
    first_tick_time: float = 0.0  # Unix timestamp of first tick


class CandleAggregator:
    """Aggregates ticks into OHLCV candles for multiple timeframes.

    Usage:
        agg = CandleAggregator(intervals=[60, 300])  # 1-min, 5-min
        candle = agg.add_tick(tick)  # Returns completed candle or None
    """

    def __init__(self, intervals: list[int] | None = None):
        """
        Args:
            intervals: Candle intervals in seconds. Default: [60] (1-min).
        """
        self._intervals = intervals or [60]
        # Per-symbol, per-interval partial candle
        self._partials: dict[str, dict[int, PartialCandle]] = {}

    def add_tick(self, tick: Tick) -> dict[int, OHLC | None]:
        """Process a tick and return any completed candles.

        Returns:
            Dict mapping interval_seconds → completed OHLC (or None if still building).
        """
        results: dict[int, OHLC | None] = {}
        sym = tick.symbol

        if sym not in self._partials:
            self._partials[sym] = {}

        for interval in self._intervals:
            if interval not in self._partials[sym]:
                self._partials[sym][interval] = PartialCandle(
                    symbol=sym,
                    time="",
                )

            completed = self._update_partial(
                partial=self._partials[sym][interval],
                tick=tick,
                interval=interval,
            )
            results[interval] = completed

        return results

    def _update_partial(
        self, partial: PartialCandle, tick: Tick, interval: int
    ) -> OHLC | None:
        """Update a partial candle. Returns completed OHLC if candle closed."""
        import time

        tick_time = _parse_tick_time(tick)
        if tick_time <= 0:
            return None

        candle_open_time = _floor_to_interval(tick_time, interval)
        candle_open_str = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(candle_open_time))

        # Check if this tick belongs to a new candle
        is_new_candle = (
            partial.time == "" or
            candle_open_time > _parse_iso_time(partial.time)
        )

        completed: OHLC | None = None
        if is_new_candle and partial.time != "":
            # Previous candle is complete
            completed = OHLC(
                symbol=partial.symbol,
                time=partial.time,
                open=partial.open,
                high=partial.high,
                low=partial.low if partial.low != float("inf") else partial.open,
                close=partial.close,
                volume=partial.volume,
                delta=_approximate_delta(partial),
            )
            logger.debug(
                "Candle completed: %s %s O=%.2f H=%.2f L=%.2f C=%.2f V=%.0f",
                partial.symbol, partial.time,
                completed.open, completed.high, completed.low, completed.close, completed.volume,
            )
            # Reset partial for new candle
            partial.time = ""
            partial.open = 0.0
            partial.high = 0.0
            partial.low = float("inf")
            partial.close = 0.0
            partial.volume = 0.0

        # Initialize new candle
        if partial.time == "":
            partial.time = candle_open_str
            partial.open = tick.ltp
            partial.high = tick.ltp
            partial.low = tick.ltp
            partial.close = tick.ltp
            partial.prev_cum_volume = tick.volume  # Save BEFORE computing volume
            partial.first_tick_time = tick_time
            partial.volume = 0.0  # First tick: volume is 0 (cumulative reference point)

        # Update candle with tick
        partial.high = max(partial.high, tick.ltp)
        partial.low = min(partial.low, tick.ltp)
        partial.close = tick.ltp
        partial.volume = max(0.0, tick.volume - partial.prev_cum_volume)

        return completed

    def get_current_candle(self, symbol: str, interval: int) -> OHLC | None:
        """Get the in-progress candle for a symbol + interval."""
        if symbol not in self._partials:
            return None
        p = self._partials[symbol].get(interval)
        if p is None or p.time == "":
            return None
        return OHLC(
            symbol=p.symbol,
            time=p.time,
            open=p.open,
            high=p.high,
            low=p.low if p.low != float("inf") else p.open,
            close=p.close,
            volume=p.volume,
        )

    def reset(self, symbol: str) -> None:
        """Reset all partial candles for a symbol (e.g., at session boundary)."""
        if symbol in self._partials:
            self._partials[symbol] = {}


# ── Helpers ────────────────────────────────────────────────────────────

def _parse_tick_time(tick: Tick) -> float:
    """Parse tick's LTT into Unix timestamp."""
    import time as _time
    if tick.ltt:
        try:
            return float(tick.ltt)
        except (ValueError, TypeError):
            pass
    return _time.time()


def _floor_to_interval(ts: float, interval: int) -> float:
    """Floor a Unix timestamp to the nearest interval boundary."""
    return int(ts // interval) * interval


def _parse_iso_time(iso_str: str) -> float:
    """Parse ISO time string to Unix timestamp (UTC)."""
    import calendar
    import time as _time
    try:
        dt = _time.strptime(iso_str, "%Y-%m-%dT%H:%M:%S")
        return calendar.timegm(dt)  # UTC, not localtime
    except (ValueError, TypeError):
        return 0.0


def _approximate_delta(partial: PartialCandle) -> float:
    """Approximate delta for NSE (no taker_buy_volume available).

    Body-ratio method: delta = volume × (close - open) / range
    If range is 0, delta = 0.
    """
    rng = partial.high - partial.low
    if rng == 0:
        return 0.0
    body = partial.close - partial.open
    return partial.volume * (body / rng)
