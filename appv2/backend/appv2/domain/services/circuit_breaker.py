"""Circuit Breaker — per-symbol circuit breaker with cooldown.

After N consecutive losses → cooldown for M minutes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


class CircuitBreaker:
    """Per-symbol circuit breaker."""

    def __init__(
        self,
        max_consecutive_losses: int = 5,
        cooldown_minutes: int = 30,
    ):
        self._max_losses = max_consecutive_losses
        self._cooldown_sec = cooldown_minutes * 60
        self._consecutive_losses: int = 0
        self._cooldown_start: float = 0.0
        self._is_open: bool = False

    @property
    def is_open(self) -> bool:
        """True if circuit breaker is tripped (trading blocked)."""
        if self._is_open:
            # Check if cooldown expired
            if time.time() - self._cooldown_start >= self._cooldown_sec:
                self._reset()
                return False
            return True
        return False

    def record_loss(self) -> None:
        self._consecutive_losses += 1
        if self._consecutive_losses >= self._max_losses:
            self._is_open = True
            self._cooldown_start = time.time()

    def record_win(self) -> None:
        self._consecutive_losses = 0

    def _reset(self) -> None:
        self._is_open = False
        self._consecutive_losses = 0
        self._cooldown_start = 0.0

    @property
    def remaining_cooldown_seconds(self) -> float:
        if not self._is_open:
            return 0.0
        remaining = self._cooldown_sec - (time.time() - self._cooldown_start)
        return max(0.0, remaining)
