"""Initial Balance Engine — tracks IB High/Low/Mid of first N minutes.

IB Build Window:
  NSE: 09:15-09:45 (first 30 minutes)
  MCX: 09:00-09:30

IB_HIGH = highest high of all bars within build window
IB_LOW  = lowest low of all bars within build window
IB_MID  = (IB_HIGH + IB_LOW) / 2
IB_WIDTH = IB_HIGH - IB_LOW

IB features for ML:
  ib_location:       0 = INSIDE, 1 = ABOVE, -1 = BELOW, null = BUILDING
  ib_width_pct:      IB_WIDTH / (session ATR(5) * spot) — normalized
  ib_position_pct:   (price - IB_LOW) / IB_WIDTH — 0% = at low, 100% = at high
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from quant.contracts.value_objects import OHLC

logger = logging.getLogger(__name__)


class IBLocation(str, Enum):
    INSIDE = "INSIDE"
    ABOVE = "ABOVE"
    BELOW = "BELOW"
    BUILDING = "BUILDING"


@dataclass(frozen=True)
class IBState:
    """Immutable IB state snapshot."""

    ib_high: float
    ib_low: float
    ib_mid: float
    ib_width: float
    is_complete: bool
    location: IBLocation
    ib_position_pct: float  # 0-100, where price is within IB


class InitialBalanceEngine:
    """Tracks Initial Balance for a symbol.

    IB is the high/low of the first N minutes of the trading session.
    Used for structural setups and IB breakout scalps (Phase 4).
    """

    def __init__(self, ib_minutes: int = 30) -> None:
        self._ib_minutes = ib_minutes
        self._ib_high: float = 0.0
        self._ib_low: float = float("inf")
        self._session_open_time: str = ""
        self._complete: bool = False

    @property
    def is_complete(self) -> bool:
        return self._complete

    @property
    def ib_high(self) -> float:
        return self._ib_high

    @property
    def ib_low(self) -> float:
        return self._ib_low if self._ib_low != float("inf") else 0.0

    @property
    def ib_mid(self) -> float:
        return (self.ib_high + self.ib_low) / 2

    @property
    def ib_width(self) -> float:
        return self.ib_high - self.ib_low

    def reset(self) -> None:
        """Reset at session start."""
        self._ib_high = 0.0
        self._ib_low = float("inf")
        self._session_open_time = ""
        self._complete = False

    def update(self, candle: OHLC) -> IBState:
        """Update IB with new candle. Returns current IB state."""
        if not self._session_open_time:
            self._session_open_time = candle.time

        # Update IB high/low (BEFORE marking complete, so the last candle of the window is included)
        if not self._complete:
            self._ib_high = max(self._ib_high, float(candle.high))
            self._ib_low = min(self._ib_low, float(candle.low))

        # Check if IB window has elapsed
        if not self._complete:
            try:
                open_dt = datetime.fromisoformat(self._session_open_time)
                curr_dt = datetime.fromisoformat(candle.time)
                elapsed = (curr_dt - open_dt).total_seconds() / 60
                if elapsed >= self._ib_minutes:
                    self._complete = True
                    logger.info(
                        "IB complete: high=%.1f low=%.1f width=%.1f",
                        self.ib_high,
                        self.ib_low,
                        self.ib_width,
                    )
            except (ValueError, TypeError):
                pass

        # Classify price location
        c_price = float(candle.close)
        if not self._complete:
            location = IBLocation.BUILDING
            position_pct = 0.0
        elif c_price > self.ib_high:
            location = IBLocation.ABOVE
            position_pct = 100.0
        elif c_price < self.ib_low:
            location = IBLocation.BELOW
            position_pct = 0.0
        else:
            location = IBLocation.INSIDE
            if self.ib_width > 0:
                position_pct = ((c_price - self.ib_low) / self.ib_width) * 100
            else:
                position_pct = 50.0

        return IBState(
            ib_high=self.ib_high,
            ib_low=self.ib_low,
            ib_mid=self.ib_mid,
            ib_width=self.ib_width,
            is_complete=self._complete,
            location=location,
            ib_position_pct=round(position_pct, 1),
        )

    def classify_breakout(self, candle: OHLC) -> str:
        """Classify IB breakout direction.

        Returns: "LONG_BREAKOUT", "SHORT_BREAKOUT", or ""
        """
        if not self._complete:
            return ""

        c_high = float(candle.high)
        c_low = float(candle.low)
        prev_close = float(candle.open)  # approximate

        if c_high > self.ib_high and prev_close <= self.ib_high:
            return "LONG_BREAKOUT"
        elif c_low < self.ib_low and prev_close >= self.ib_low:
            return "SHORT_BREAKOUT"
        return ""

    def get_state(self) -> dict:
        """Get state for serialization."""
        return {
            "ib_high": self.ib_high,
            "ib_low": self.ib_low,
            "ib_mid": self.ib_mid,
            "ib_width": self.ib_width,
            "is_complete": self._complete,
        }
