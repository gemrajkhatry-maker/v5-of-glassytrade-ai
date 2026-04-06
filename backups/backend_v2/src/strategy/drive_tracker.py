"""
Drive tracker — D1/D2/D3+ with rejection detection and momentum fade.

First Drive: trap move, never enter
Second Drive: re-test with fading momentum, only valid entry
Third Drive+: exhausted, avoid
"""

from dataclasses import dataclass
from typing import Dict, Optional

from src.config.engine_config import CFG
from src.core.candle_builder import Candle


@dataclass
class DriveResult:
    """Drive classification result."""

    drive_number: int  # 1, 2, or 3+
    entry_valid: bool
    rejection_detected: bool
    fading_momentum: bool


@dataclass
class LevelDriveState:
    """Drive state for a single level."""

    first_touch_price: float
    first_touch_volume: int
    first_touch_rejected: bool
    touch_count: int


class DriveTracker:
    """
    Track touches at key levels per Fabio's drive methodology.

    Maintains per-level touch history with rejection and momentum tracking.
    """

    def __init__(self):
        self._level_history: Dict[float, LevelDriveState] = {}

    def classify_drive(
        self,
        price: float,
        level: float,
        candle: Candle,
        direction: str,
    ) -> DriveResult:
        """
        Classify the current touch of a level.

        Args:
            price: Current price
            level: Key level being touched
            candle: Current candle
            direction: "LONG" or "SHORT"

        Returns:
            DriveResult with drive number and entry validity.
        """
        # Initialize level if not seen before
        if level not in self._level_history:
            self._level_history[level] = LevelDriveState(
                first_touch_price=price,
                first_touch_volume=candle.volume,
                first_touch_rejected=False,
                touch_count=1,
            )
            return DriveResult(
                drive_number=1,
                entry_valid=False,
                rejection_detected=False,
                fading_momentum=False,
            )

        state = self._level_history[level]
        state.touch_count += 1

        # Check for rejection on previous touch
        rejection = self.detect_rejection(candle, level, direction)

        # First Drive: check if rejected
        if state.touch_count == 2:
            state.first_touch_rejected = rejection

            if not rejection:
                # First drive not rejected, no entry on re-touch
                return DriveResult(
                    drive_number=2,
                    entry_valid=False,
                    rejection_detected=False,
                    fading_momentum=False,
                )

            # First drive rejected, second drive is valid entry
            fading = self.check_momentum_fade(candle.volume, state.first_touch_volume)
            return DriveResult(
                drive_number=2,
                entry_valid=True,
                rejection_detected=rejection,
                fading_momentum=fading,
            )

        # Third drive or more
        return DriveResult(
            drive_number=state.touch_count,
            entry_valid=False,
            rejection_detected=rejection,
            fading_momentum=False,
        )

    @staticmethod
    def detect_rejection(candle: Candle, level: float, direction: str) -> bool:
        """
        Detect rejection at a level.

        Wick through level but close on opposite side.

        Args:
            candle: Current candle
            level: Key level
            direction: Expected direction

        Returns:
            True if rejection detected.
        """
        if direction == "LONG":
            wick_through = candle.low < level
            close_opposite = candle.close > level
        else:  # SHORT
            wick_through = candle.high > level
            close_opposite = candle.close < level

        return wick_through and close_opposite

    @staticmethod
    def check_momentum_fade(current_volume: int, first_volume: int) -> bool:
        """
        Check if momentum is fading (D2 volume < D1 volume).

        Args:
            current_volume: Volume at current touch
            first_volume: Volume at first touch

        Returns:
            True if momentum is fading.
        """
        if first_volume <= 0:
            return False

        ratio = current_volume / first_volume
        return ratio <= CFG.drive_momentum_fade_threshold

    def reset(self) -> None:
        """Reset for new session."""
        self._level_history.clear()