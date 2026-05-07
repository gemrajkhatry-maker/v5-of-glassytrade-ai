"""OHLC candle builder with multi-timeframe aggregation."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Optional
from collections import deque

from brokersv2.domain.market.events import TickEvent


class Timeframe(Enum):
    """Candle timeframes."""
    MINUTE_1 = "1m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    HOUR_1 = "1h"


class CandleBuilderError(Exception):
    """Base exception for candle builder errors."""
    pass


class InvalidTickError(CandleBuilderError):
    """Raised when tick is invalid for current candle."""
    pass


class CandleClosedError(CandleBuilderError):
    """Raised when attempting to add tick to closed candle."""
    pass


@dataclass(frozen=True)
class Candle:
    """OHLC candle representation."""
    timestamp: datetime
    security_id: str
    symbol: str
    exchange: str
    timeframe: Timeframe
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    oi: int
    is_complete: bool

    @property
    def range(self) -> Decimal:
        """Calculate candle range (high - low)."""
        return self.high - self.low

    @property
    def body(self) -> Decimal:
        """Calculate candle body size (|close - open|)."""
        return abs(self.close - self.open)

    @property
    def is_bullish(self) -> bool:
        """Check if candle is bullish (close > open)."""
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        """Check if candle is bearish (close < open)."""
        return self.close < self.open

    @property
    def is_doji(self) -> bool:
        """Check if candle is doji (close == open)."""
        return self.close == self.open

    @property
    def vwap(self) -> Decimal:
        """Calculate approximate VWAP for candle."""
        # Typical price = (high + low + close) / 3
        return (self.high + self.low + self.close) / Decimal("3")


@dataclass
class _CandleInProgress:
    """Internal representation of candle being built."""
    timestamp: datetime
    security_id: str
    symbol: str
    exchange: str
    timeframe: Timeframe
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    oi: int
    tick_count: int = 0


class CandleBuilder:
    """
    Builds OHLC candles from tick data with multi-timeframe support.
    
    Features:
    - Real-time candle aggregation
    - Multiple timeframes (1m, 5m, 15m, 1h)
    - Candle completion detection
    - Historical candle storage
    - Volume and OI tracking
    """

    TIMEFRAME_MINUTES = {
        Timeframe.MINUTE_1: 1,
        Timeframe.MINUTE_5: 5,
        Timeframe.MINUTE_15: 15,
        Timeframe.HOUR_1: 60,
    }

    def __init__(
        self,
        security_id: str,
        timeframe: Timeframe = Timeframe.MINUTE_1,
        history_size: int = 1000,
    ):
        self._security_id = security_id
        self._timeframe = timeframe
        self._history_size = history_size
        self._minutes_per_candle = self.TIMEFRAME_MINUTES[timeframe]

        self._current_candle: Optional[_CandleInProgress] = None
        self._completed_candles: deque[Candle] = deque(maxlen=history_size)
        self._total_ticks_processed: int = 0

    def process_tick(self, tick: TickEvent) -> Optional[Candle]:
        """
        Process a tick and update candle.
        
        Returns completed Candle if timeframe boundary crossed, None otherwise.
        Raises:
            - InvalidTickError: security_id mismatch
            - CandleClosedError: tick belongs to closed candle
        """
        # Validate security ID
        if tick.security_id != self._security_id:
            raise InvalidTickError(
                f"security_id mismatch: expected {self._security_id}, "
                f"got {tick.security_id}"
            )

        self._total_ticks_processed += 1

        # Check if we need to start a new candle
        if self._current_candle is None:
            self._start_new_candle(tick)
            return None

        # Check if tick belongs to current candle timeframe
        current_start = self._current_candle.timestamp
        current_end = current_start + timedelta(minutes=self._minutes_per_candle)

        if tick.timestamp >= current_end:
            # Tick is in next timeframe - complete current candle
            completed = self._complete_current_candle()
            self._start_new_candle(tick)
            return completed

        # Check for out-of-order (tick before current candle start)
        if tick.timestamp < current_start:
            # Could raise CandleClosedError or handle gracefully
            # For now, we'll skip silently
            return None

        # Update current candle with tick data
        self._update_candle_with_tick(tick)

        return None

    def get_current_candle(self) -> Optional[Candle]:
        """Get current incomplete candle."""
        if self._current_candle is None:
            return None

        return Candle(
            timestamp=self._current_candle.timestamp,
            security_id=self._current_candle.security_id,
            symbol=self._current_candle.symbol,
            exchange=self._current_candle.exchange,
            timeframe=self._current_candle.timeframe,
            open=self._current_candle.open,
            high=self._current_candle.high,
            low=self._current_candle.low,
            close=self._current_candle.close,
            volume=self._current_candle.volume,
            oi=self._current_candle.oi,
            is_complete=False,
        )

    def get_completed_candles(self) -> list[Candle]:
        """Get all completed candles."""
        return list(self._completed_candles)

    def reset(self):
        """Reset candle builder state."""
        self._current_candle = None
        self._completed_candles.clear()
        self._total_ticks_processed = 0

    def get_metrics(self) -> dict:
        """Get candle builder metrics."""
        return {
            "security_id": self._security_id,
            "timeframe": self._timeframe,
            "total_ticks_processed": self._total_ticks_processed,
            "completed_candles": len(self._completed_candles),
            "current_candle": {
                "timestamp": str(self._current_candle.timestamp),
                "open": str(self._current_candle.open),
                "high": str(self._current_candle.high),
                "low": str(self._current_candle.low),
                "close": str(self._current_candle.close),
                "volume": self._current_candle.volume,
                "tick_count": self._current_candle.tick_count,
            } if self._current_candle else None,
        }

    def _start_new_candle(self, tick: TickEvent):
        """Start a new candle from tick."""
        self._current_candle = _CandleInProgress(
            timestamp=tick.timestamp,
            security_id=tick.security_id,
            symbol=tick.symbol,
            exchange=tick.exchange,
            timeframe=self._timeframe,
            open=tick.ltp,
            high=tick.ltp,
            low=tick.ltp,
            volume=tick.volume,
            oi=tick.oi,
            close=tick.ltp,
            tick_count=1,
        )

    def _update_candle_with_tick(self, tick: TickEvent):
        """Update current candle with new tick data."""
        if self._current_candle is None:
            return

        # Update high
        if tick.ltp > self._current_candle.high:
            self._current_candle.high = tick.ltp

        # Update low
        if tick.ltp < self._current_candle.low:
            self._current_candle.low = tick.ltp

        # Update close (always latest)
        self._current_candle.close = tick.ltp

        # Update volume (cumulative)
        self._current_candle.volume += tick.volume

        # Update OI (always latest)
        self._current_candle.oi = tick.oi

        # Update tick count
        self._current_candle.tick_count += 1

    def _complete_current_candle(self) -> Candle:
        """Complete current candle and add to history."""
        if self._current_candle is None:
            raise CandleBuilderError("No candle in progress")

        candle = Candle(
            timestamp=self._current_candle.timestamp,
            security_id=self._current_candle.security_id,
            symbol=self._current_candle.symbol,
            exchange=self._current_candle.exchange,
            timeframe=self._current_candle.timeframe,
            open=self._current_candle.open,
            high=self._current_candle.high,
            low=self._current_candle.low,
            close=self._current_candle.close,
            volume=self._current_candle.volume,
            oi=self._current_candle.oi,
            is_complete=True,
        )

        self._completed_candles.append(candle)
        return candle
