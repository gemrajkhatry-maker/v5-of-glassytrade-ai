"""
OFI calculator — Order Flow Imbalance over rolling window.

OFI = (ask_vol - bid_vol) / total_vol, averaged over last N candles.
"""

from collections import deque
from typing import Optional

from src.config.engine_config import CFG
from src.core.tick_processor import Tick


class OFICalculator:
    """
    Order Flow Imbalance calculator.

    Tracks OFI over rolling window for aggression scoring.
    """

    def __init__(self, window: int = CFG.ofi_window):
        self._window = window
        self._ofi_history: deque = deque(maxlen=window)
        self._current_candle_delta: float = 0.0
        self._current_candle_volume: int = 0

    def update(self, tick: Tick) -> float:
        """
        Update OFI with a new tick.

        Args:
            tick: Normalized tick data

        Returns:
            Current OFI value (-1.0 to +1.0).
        """
        self._current_candle_delta += tick.delta
        self._current_candle_volume += tick.volume

        # Calculate OFI for current candle
        if self._current_candle_volume > 0:
            ofi = self._current_candle_delta / self._current_candle_volume
        else:
            ofi = 0.0

        return ofi

    def close_candle(self) -> None:
        """Called when a candle closes to add to history."""
        if self._current_candle_volume > 0:
            ofi = self._current_candle_delta / self._current_candle_volume
        else:
            ofi = 0.0

        self._ofi_history.append(ofi)

        # Reset for next candle
        self._current_candle_delta = 0.0
        self._current_candle_volume = 0

    def get_current(self) -> float:
        """Get current OFI value."""
        if self._current_candle_volume > 0:
            return self._current_candle_delta / self._current_candle_volume
        return 0.0

    def get_rolling_average(self) -> float:
        """Get rolling average OFI over window."""
        if not self._ofi_history:
            return 0.0
        return sum(self._ofi_history) / len(self._ofi_history)

    def is_aligned(self, direction: str) -> bool:
        """
        Check if OFI is aligned with direction.

        Args:
            direction: "LONG" or "SHORT"

        Returns:
            True if OFI supports the direction.
        """
        ofi = self.get_rolling_average()

        if direction == "LONG":
            return ofi > CFG.ofi_long_threshold
        elif direction == "SHORT":
            return ofi < CFG.ofi_short_threshold
        return False

    def reset(self) -> None:
        """Reset for new session."""
        self._ofi_history.clear()
        self._current_candle_delta = 0.0
        self._current_candle_volume = 0