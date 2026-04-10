"""Tick Throttle — limits process_tick frequency per symbol.

Matches original backend: max 1 process_tick per 500ms per symbol.
Between throttled calls, only lightweight state updates occur.
"""

from __future__ import annotations

import time


class TickThrottle:
    """Per-symbol tick throttle."""

    def __init__(self, min_interval: float = 0.5):
        """
        Args:
            min_interval: Minimum seconds between full process_tick calls.
                          Default 0.5s (500ms) matches original backend.
        """
        self._min_interval = min_interval
        self._last_process: dict[str, float] = {}

    def should_process(self, symbol: str) -> bool:
        """Check if symbol is ready for full processing.

        Returns:
            True if enough time has passed since last full process.
        """
        now = time.monotonic()
        last = self._last_process.get(symbol, 0.0)
        if now - last >= self._min_interval:
            self._last_process[symbol] = now
            return True
        return False

    def time_since_last(self, symbol: str) -> float:
        """Seconds since last full process for symbol."""
        now = time.monotonic()
        last = self._last_process.get(symbol, 0.0)
        return now - last

    def reset(self, symbol: str = "") -> None:
        """Reset throttle state."""
        if symbol:
            self._last_process.pop(symbol, None)
        else:
            self._last_process.clear()

    @property
    def min_interval(self) -> float:
        return self._min_interval
