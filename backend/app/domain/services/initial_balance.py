"""Initial Balance Tracker — tracks IB high/low of first N minutes.

Extracted from amt_analyzer.py for independent testing.

IB Build Window:
  NSE: 09:15-09:45 (first 30 minutes)
  MCX: 09:00-09:30

IB_HIGH = highest high of all bars within build window
IB_LOW  = lowest low of all bars within build window
IB_MID  = (IB_HIGH + IB_LOW) / 2
IB_WIDTH = IB_HIGH - IB_LOW
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from app.domain.trading.models.value_objects import OHLC

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IBResult:
    """Initial Balance result."""

    ib_high: float
    ib_low: float
    ib_mid: float
    ib_width: float
    is_complete: bool


class InitialBalanceTracker:
    """Tracks Initial Balance — high/low of the first N minutes of session."""

    def __init__(self, ib_minutes: int = 10) -> None:
        self._ib_minutes = ib_minutes
        self._ib_high: float = 0.0
        self._ib_low: float = float("inf")
        self._session_open_time: str = ""
        self._complete: bool = False

    def reset(self) -> None:
        self._ib_high = 0.0
        self._ib_low = float("inf")
        self._session_open_time = ""
        self._complete = False

    def update(self, candle: OHLC) -> tuple[float, float, bool]:
        """Update IB tracking. Returns (ib_high, ib_low, is_complete)."""
        if self._complete:
            return self._ib_high, self._ib_low, True

        if not self._session_open_time:
            self._session_open_time = candle.time

        try:
            open_dt = datetime.fromisoformat(self._session_open_time)
            curr_dt = datetime.fromisoformat(candle.time)
            elapsed_minutes = (curr_dt - open_dt).total_seconds() / 60
            if elapsed_minutes >= self._ib_minutes:
                self._complete = True
                return self._ib_high, self._ib_low, True
        except (ValueError, TypeError):
            pass

        self._ib_high = max(self._ib_high, float(candle.high))
        self._ib_low = min(self._ib_low, float(candle.low))
        return self._ib_high, self._ib_low, False

    def get_result(self) -> IBResult:
        """Get current IB result."""
        return IBResult(
            ib_high=self._ib_high,
            ib_low=self._ib_low if self._ib_low != float("inf") else 0.0,
            ib_mid=(
                self._ib_high + (self._ib_low if self._ib_low != float("inf") else 0.0)
            )
            / 2,
            ib_width=self._ib_high
            - (self._ib_low if self._ib_low != float("inf") else 0.0),
            is_complete=self._complete,
        )
