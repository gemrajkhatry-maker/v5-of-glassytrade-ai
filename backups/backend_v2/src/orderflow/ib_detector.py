"""
IB detector — Initial Balance tracking and break detection.

IB = price range of first N candles of session (default 2).
Detects IB breaks with volume confirmation.
"""

from dataclasses import dataclass
from typing import Optional

from src.config.engine_config import CFG
from src.core.candle_builder import Candle


@dataclass
class IBResult:
    """Initial Balance detection result."""

    ib_set: bool
    ib_high: Optional[float]
    ib_low: Optional[float]
    ib_broken: bool
    break_direction: str  # "UP", "DOWN", "NONE"


class IBDetector:
    """
    Initial Balance tracking and break detection.
    """

    def __init__(self, ib_candles: int = CFG.ib_candles):
        self._ib_candles = ib_candles
        self._candle_count: int = 0
        self._ib_high: Optional[float] = None
        self._ib_low: Optional[float] = None
        self._ib_set: bool = False
        self._ib_broken: bool = False

    def update(self, candle: Candle, avg_vol: float) -> IBResult:
        """
        Update IB with a new candle.

        Args:
            candle: Closed candle data
            avg_vol: Average volume for break confirmation

        Returns:
            IBResult with current IB state.
        """
        self._candle_count += 1

        # Still building IB
        if self._candle_count <= self._ib_candles:
            if self._ib_high is None:
                self._ib_high = candle.high
                self._ib_low = candle.low
            else:
                self._ib_high = max(self._ib_high, candle.high)
                self._ib_low = min(self._ib_low, candle.low)

            # Mark IB as set after N candles
            if self._candle_count == self._ib_candles:
                self._ib_set = True

            return IBResult(
                ib_set=self._ib_set,
                ib_high=self._ib_high,
                ib_low=self._ib_low,
                ib_broken=False,
                break_direction="NONE",
            )

        # IB is set, check for breaks
        if not self._ib_set:
            return IBResult(
                ib_set=False,
                ib_high=self._ib_high,
                ib_low=self._ib_low,
                ib_broken=False,
                break_direction="NONE",
            )

        # Check for IB break
        break_direction = "NONE"
        volume_confirmed = candle.volume > avg_vol * CFG.ib_break_volume_mult

        if candle.close > self._ib_high and volume_confirmed:
            break_direction = "UP"
            self._ib_broken = True
        elif candle.close < self._ib_low and volume_confirmed:
            break_direction = "DOWN"
            self._ib_broken = True

        return IBResult(
            ib_set=self._ib_set,
            ib_high=self._ib_high,
            ib_low=self._ib_low,
            ib_broken=self._ib_broken,
            break_direction=break_direction,
        )

    def reset(self) -> None:
        """Reset for new session."""
        self._candle_count = 0
        self._ib_high = None
        self._ib_low = None
        self._ib_set = False
        self._ib_broken = False