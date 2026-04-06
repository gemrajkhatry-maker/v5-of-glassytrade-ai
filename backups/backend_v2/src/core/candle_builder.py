"""
Candle builder — construct OHLCV candles from tick stream.

Returns Optional[Candle] on candle close (time boundary).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from src.core.tick_processor import Tick


@dataclass
class Candle:
    """OHLCV candle data."""

    open: float
    high: float
    low: float
    close: float
    volume: int
    buy_vol: int
    sell_vol: int
    delta: int
    timestamp: datetime
    candle_start: datetime
    candle_end: datetime


class CandleBuilder:
    """
    Build OHLCV candles from tick stream.

    Candles are built on time boundaries (e.g., 5-minute intervals).
    Returns a Candle when the current candle closes.
    """

    def __init__(
        self,
        interval_minutes: int = 5,
        symbol: str = "",
    ):
        self._interval = timedelta(minutes=interval_minutes)
        self._symbol = symbol
        self._current_candle: Optional[Candle] = None
        self._candle_start: Optional[datetime] = None

    def update(self, tick: Tick) -> Optional[Candle]:
        """
        Update with a new tick.

        Returns a Candle if the previous candle just closed, otherwise None.
        """
        # Determine candle boundary
        candle_start = self._get_candle_start(tick.timestamp)

        # Check if we need to close the current candle
        if self._candle_start and candle_start != self._candle_start:
            # Close current candle
            closed_candle = self._current_candle
            if closed_candle:
                closed_candle.candle_end = candle_start
            # Start new candle
            self._start_new_candle(tick, candle_start)
            return closed_candle

        # Update current candle
        if self._current_candle is None:
            self._start_new_candle(tick, candle_start)
        else:
            self._update_candle(tick)

        return None

    def _get_candle_start(self, timestamp: datetime) -> datetime:
        """Get the candle start time for a given timestamp."""
        minutes = timestamp.hour * 60 + timestamp.minute
        candle_minutes = (minutes // self._interval.total_seconds() * 60) * self._interval.total_seconds() // 60
        # Simplified: just truncate to interval boundary
        total_seconds = int(timestamp.timestamp())
        interval_seconds = int(self._interval.total_seconds())
        candle_seconds = (total_seconds // interval_seconds) * interval_seconds
        return datetime.fromtimestamp(candle_seconds)

    def _start_new_candle(self, tick: Tick, candle_start: datetime) -> None:
        """Start a new candle with the first tick."""
        self._candle_start = candle_start
        self._current_candle = Candle(
            open=tick.price,
            high=tick.price,
            low=tick.price,
            close=tick.price,
            volume=tick.volume,
            buy_vol=tick.ask_vol,
            sell_vol=tick.bid_vol,
            delta=tick.delta,
            timestamp=tick.timestamp,
            candle_start=candle_start,
            candle_end=candle_start + self._interval,
        )

    def _update_candle(self, tick: Tick) -> None:
        """Update current candle with a new tick."""
        if self._current_candle is None:
            return

        candle = self._current_candle
        candle.high = max(candle.high, tick.price)
        candle.low = min(candle.low, tick.price)
        candle.close = tick.price
        candle.volume += tick.volume
        candle.buy_vol += tick.ask_vol
        candle.sell_vol += tick.bid_vol
        candle.delta += tick.delta
        candle.timestamp = tick.timestamp

    def get_current_candle(self) -> Optional[Candle]:
        """Get the current (in-progress) candle."""
        return self._current_candle

    def force_close(self) -> Optional[Candle]:
        """Force close the current candle (e.g., at session end)."""
        candle = self._current_candle
        self._current_candle = None
        self._candle_start = None
        return candle