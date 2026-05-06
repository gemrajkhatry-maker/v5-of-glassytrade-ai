"""Initial Balance engine for legacy-compatible IB state."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.domain.trading.model.value_objects import OHLC


class IBLocation(str, Enum):
    INSIDE = "INSIDE"
    ABOVE = "ABOVE"
    BELOW = "BELOW"
    BUILDING = "BUILDING"


@dataclass(frozen=True)
class IBState:
    ib_high: float
    ib_low: float
    ib_mid: float
    ib_width: float
    is_complete: bool
    location: IBLocation
    ib_position_pct: float


class InitialBalanceEngine:
    """Track initial balance for the first `ib_minutes` of each session."""

    def __init__(self, ib_minutes: int = 30) -> None:
        self._ib_minutes = int(ib_minutes)
        self._ib_high: float = 0.0
        self._ib_low: float = float("inf")
        self._session_open_time: str = ""
        self._complete: bool = False
        self._last_time: str = ""

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
        return (self.ib_high + self.ib_low) / 2 if self.ib_high and self.ib_low else 0.0

    @property
    def ib_width(self) -> float:
        return max(0.0, self.ib_high - self.ib_low)

    def reset(self) -> None:
        self._ib_high = 0.0
        self._ib_low = float("inf")
        self._session_open_time = ""
        self._complete = False
        self._last_time = ""

    def update(self, candle: OHLC) -> IBState:
        if not self._session_open_time:
            self._session_open_time = candle.time

        if not self._complete:
            self._ib_high = max(self._ib_high, float(candle.high))
            self._ib_low = min(self._ib_low, float(candle.low))

        # mark complete at or after the configured window length
        if not self._complete:
            try:
                open_dt = datetime.fromisoformat(self._session_open_time)
                curr_dt = datetime.fromisoformat(candle.time)
                elapsed_min = (curr_dt - open_dt).total_seconds() / 60.0
                if elapsed_min >= self._ib_minutes:
                    self._complete = True
            except (TypeError, ValueError):
                pass

        price = float(candle.close)
        if not self._complete:
            location = IBLocation.BUILDING
            position_pct = 0.0
        elif price > self.ib_high:
            location = IBLocation.ABOVE
            position_pct = 100.0
        elif price < self.ib_low:
            location = IBLocation.BELOW
            position_pct = 0.0
        else:
            location = IBLocation.INSIDE
            position_pct = (
                ((price - self.ib_low) / self.ib_width) * 100.0 if self.ib_width > 0 else 50.0
            )

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
        """Classify breakout against completed IB."""
        if not self._complete:
            return ""
        c_high = float(candle.high)
        c_low = float(candle.low)
        prev_close = float(candle.open)

        if c_high > self.ib_high and prev_close <= self.ib_high:
            return "LONG_BREAKOUT"
        if c_low < self.ib_low and prev_close >= self.ib_low:
            return "SHORT_BREAKOUT"
        return ""

    def get_state(self) -> dict:
        return {
            "ib_high": self.ib_high,
            "ib_low": self.ib_low,
            "ib_mid": self.ib_mid,
            "ib_width": self.ib_width,
            "is_complete": self._complete,
        }

