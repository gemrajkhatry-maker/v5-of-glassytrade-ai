"""Initial Balance Engine — tracks IB range with sticky break state."""

from __future__ import annotations

from dataclasses import dataclass, field
from appv2.config import constants as C


@dataclass
class IBState:
    is_complete: bool
    high: float
    low: float
    break_direction: str  # "" | "UP" | "DOWN"


class InitialBalanceEngine:
    """Tracks Initial Balance range for NSE/MCX.

    NSE: 60-min IB from 09:15
    MCX: 60-min IB from 09:00 (morning) or 19:30 (US session)
    """

    def __init__(self, ib_minutes: int = C.IB_MINUTES_NSE):
        self._ib_minutes = ib_minutes
        self._high: float = 0.0
        self._low: float = float("inf")
        self._candle_count: int = 0
        self._is_complete: bool = False
        self._break_direction: str = ""

    def update(self, candle) -> IBState:
        """Update IB with new candle."""
        if self._is_complete:
            # Check for break
            if self._break_direction == "" and self._high > 0:
                if candle.close > self._high:
                    self._break_direction = "UP"
                elif candle.close < self._low:
                    self._break_direction = "DOWN"
            return IBState(
                is_complete=True,
                high=self._high,
                low=self._low if self._low != float("inf") else 0.0,
                break_direction=self._break_direction,
            )

        self._high = max(self._high, candle.high)
        self._low = min(self._low, candle.low)
        self._candle_count += 1

        # IB complete after N candles (assuming 1-min candles)
        if self._candle_count >= self._ib_minutes:
            self._is_complete = True
            self._low = self._low if self._low != float("inf") else candle.low

        return IBState(
            is_complete=self._is_complete,
            high=self._high,
            low=self._low if self._low != float("inf") else 0.0,
            break_direction="",
        )

    def reset(self) -> None:
        self._high = 0.0
        self._low = float("inf")
        self._candle_count = 0
        self._is_complete = False
        self._break_direction = ""
