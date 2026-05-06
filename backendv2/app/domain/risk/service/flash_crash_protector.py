"""Flash Crash Protection — price-velocity circuit breaker.

Addresses market safety gaps for v2:
- Elevated velocity: reduce aggressiveness (logged and exposed via velocity state)
- Flash crash: hard halt trading for that symbol until manual reset
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum


logger = logging.getLogger(__name__)


class VelocityLevel(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    FLASH_CRASH = "FLASH_CRASH"


@dataclass(frozen=True)
class VelocityState:
    """Current price velocity state."""

    level: VelocityLevel
    velocity_pct_per_sec: float
    is_halted: bool
    reason: str


class FlashCrashProtector:
    """Price-velocity circuit breaker.

    Monitors tick-to-tick percentage movement rate inside a short rolling window.
    Thresholds are percentage values converted to decimal points:
      - ELEVATED: > 0.5% in 5 seconds
      - FLASH_CRASH: > 2.0% in 5 seconds
    """

    def __init__(
        self,
        elevated_threshold_pct: float = 0.5,
        flash_threshold_pct: float = 2.0,
        window_seconds: int = 5,
    ) -> None:
        self._elevated_threshold = elevated_threshold_pct / 100.0
        self._flash_threshold = flash_threshold_pct / 100.0
        self._window_seconds = window_seconds
        self._price_history: list[tuple[float, float]] = []
        self._halted: bool = False
        self._halt_reason: str = ""

    def update(self, price: float, timestamp: float) -> VelocityState:
        """Update with latest observed price and return current velocity state."""
        if self._halted:
            return VelocityState(
                level=VelocityLevel.FLASH_CRASH,
                velocity_pct_per_sec=0.0,
                is_halted=True,
                reason=self._halt_reason,
            )

        if price <= 0:
            return VelocityState(
                level=VelocityLevel.NORMAL,
                velocity_pct_per_sec=0.0,
                is_halted=self._halted,
                reason=self._halt_reason,
            )

        self._price_history.append((timestamp, float(price)))

        # Keep only ticks within the active window.
        cutoff = timestamp - self._window_seconds
        self._price_history = [(t, p) for t, p in self._price_history if t >= cutoff]

        if len(self._price_history) < 2:
            return VelocityState(
                level=VelocityLevel.NORMAL,
                velocity_pct_per_sec=0.0,
                is_halted=self._halted,
                reason=self._halt_reason,
            )

        oldest_price = self._price_history[0][1]
        newest_price = self._price_history[-1][1]
        price_change = abs(newest_price - oldest_price) / max(oldest_price, 1.0)
        elapsed = max(timestamp - self._price_history[0][0], 0.001)
        velocity = price_change / elapsed

        if price_change >= self._flash_threshold:
            self._halted = True
            self._halt_reason = (
                f"Flash crash: {price_change:.1%} in {elapsed:.0f}s"
            )
            logger.warning("FLASH CRASH PROTECTOR: %s — HALTING", self._halt_reason)
            return VelocityState(
                level=VelocityLevel.FLASH_CRASH,
                velocity_pct_per_sec=velocity,
                is_halted=True,
                reason=self._halt_reason,
            )

        if price_change >= self._elevated_threshold:
            logger.info(
                "FLASH CRASH PROTECTOR: elevated velocity — %.1f%% in %.0fs",
                price_change * 100,
                elapsed,
            )
            return VelocityState(
                level=VelocityLevel.ELEVATED,
                velocity_pct_per_sec=velocity,
                is_halted=False,
                reason=f"Elevated: {price_change:.1%} in {elapsed:.0f}s",
            )

        return VelocityState(
            level=VelocityLevel.NORMAL,
            velocity_pct_per_sec=velocity,
            is_halted=False,
            reason="Normal velocity",
        )

    def reset(self) -> None:
        """Reset for new session / session restore."""
        self._price_history.clear()
        self._halted = False
        self._halt_reason = ""
