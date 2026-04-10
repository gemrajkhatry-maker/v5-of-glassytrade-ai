"""Flash Crash Protector — monitors price velocity and triggers circuit breakers.

Monitors:
- Price velocity (ticks per second × price change magnitude)
- Large single-tick price jumps
- Volume spikes on single ticks

Levels:
  NORMAL: No action
  ELEVATED: Pause new entries for 60 seconds
  FLASH_CRASH: Halt all trading, close positions, alert

Based on the old system's flash_crash_protector.py (124 lines).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from collections import deque
from enum import Enum

logger = logging.getLogger(__name__)


class FlashCrashLevel(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    FLASH_CRASH = "FLASH_CRASH"


@dataclass(frozen=True)
class FlashCrashState:
    level: FlashCrashLevel
    price_velocity: float  # Points per second
    tick_velocity: float  # Ticks per second
    largest_tick: float  # Largest single-tick price move
    alert_message: str = ""


class FlashCrashProtector:
    """Protects against flash crashes and extreme volatility.

    Usage:
        protector = FlashCrashProtector()
        state = protector.update_tick(price=100.0, volume=100)
        if state.level != FlashCrashLevel.NORMAL:
            # Take protective action
    """

    def __init__(
        self,
        elevated_velocity_threshold: float = 10.0,  # Points/sec
        flash_crash_velocity_threshold: float = 50.0,  # Points/sec
        single_tick_jump_threshold: float = 5.0,  # Single-tick move in points
        volume_spike_multiplier: float = 10.0,  # Volume × average = spike
        lookback_window: float = 5.0,  # Seconds to look back
    ):
        self._elevated_vel = elevated_velocity_threshold
        self._flash_crash_vel = flash_crash_velocity_threshold
        self._tick_jump = single_tick_jump_threshold
        self._volume_spike = volume_spike_multiplier
        self._lookback = lookback_window

        self._price_history: deque[tuple[float, float]] = deque()  # (timestamp, price)
        self._tick_times: deque[float] = deque()
        self._avg_volume: float = 0.0
        self._volume_samples: deque[float] = deque(maxlen=100)
        self._largest_tick: float = 0.0
        self._level: FlashCrashLevel = FlashCrashLevel.NORMAL
        self._alert_level_since: float = 0.0
        self._flash_crash_triggered: bool = False

    def update_tick(self, price: float, volume: float = 0.0) -> FlashCrashState:
        """Process a new tick and check for flash crash conditions.

        Args:
            price: Current price (LTP)
            volume: Current tick volume
        """
        now = time.time()

        # Track price history
        self._price_history.append((now, price))
        self._tick_times.append(now)

        # Trim lookback window
        cutoff = now - self._lookback
        while self._price_history and self._price_history[0][0] < cutoff:
            self._price_history.popleft()
        while self._tick_times and self._tick_times[0] < cutoff:
            self._tick_times.popleft()

        # Track volume
        if volume > 0:
            self._volume_samples.append(volume)
            if len(self._volume_samples) >= 10:
                self._avg_volume = sum(self._volume_samples) / len(self._volume_samples)

        # Calculate price velocity (points per second)
        velocity = self._calculate_velocity()

        # Calculate tick velocity (ticks per second)
        tick_velocity = self._calculate_tick_velocity()

        # Check for single-tick price jump
        tick_jump = 0.0
        if len(self._price_history) >= 2:
            prices = [p for _, p in self._price_history]
            if len(prices) >= 2:
                tick_jump = abs(prices[-1] - prices[-2])
                self._largest_tick = max(self._largest_tick, tick_jump)

        # Check for volume spike
        vol_spike = False
        if self._avg_volume > 0 and volume > 0:
            vol_spike = volume > self._avg_volume * self._volume_spike

        # Determine level
        prev_level = self._level

        if velocity >= self._flash_crash_vel or tick_jump >= self._tick_jump * 3:
            self._level = FlashCrashLevel.FLASH_CRASH
            self._flash_crash_triggered = True
        elif velocity >= self._elevated_vel or vol_spike or tick_jump >= self._tick_jump:
            self._level = FlashCrashLevel.ELEVATED
            if prev_level == FlashCrashLevel.NORMAL:
                self._alert_level_since = now
        else:
            # Check if we can return to normal
            if self._level != FlashCrashLevel.NORMAL:
                # Need 30 seconds of calm to return to normal
                if now - self._alert_level_since >= 30:
                    self._level = FlashCrashLevel.NORMAL

        # Build alert message
        alert = ""
        if self._level == FlashCrashLevel.FLASH_CRASH:
            alert = (
                f"FLASH CRASH DETECTED — Velocity: {velocity:.1f} pts/s, "
                f"Largest tick: {self._largest_tick:.2f}"
            )
            logger.critical(alert)
        elif self._level == FlashCrashLevel.ELEVATED:
            alert = (
                f"ELEVATED VOLATILITY — Velocity: {velocity:.1f} pts/s, "
                f"Tick velocity: {tick_velocity:.0f} ticks/s"
            )
            logger.warning(alert)

        return FlashCrashState(
            level=self._level,
            price_velocity=round(velocity, 2),
            tick_velocity=round(tick_velocity, 1),
            largest_tick=round(self._largest_tick, 2),
            alert_message=alert,
        )

    def _calculate_velocity(self) -> float:
        """Calculate price velocity (points per second) over lookback window."""
        if len(self._price_history) < 2:
            return 0.0

        first_ts, first_price = self._price_history[0]
        last_ts, last_price = self._price_history[-1]

        time_span = last_ts - first_ts
        if time_span <= 0:
            return 0.0

        return abs(last_price - first_price) / time_span

    def _calculate_tick_velocity(self) -> float:
        """Calculate ticks per second over lookback window."""
        if len(self._tick_times) < 2:
            return 0.0

        time_span = self._tick_times[-1] - self._tick_times[0]
        if time_span <= 0:
            return 0.0

        return len(self._tick_times) / time_span

    @property
    def level(self) -> FlashCrashLevel:
        return self._level

    @property
    def is_flash_crash(self) -> bool:
        return self._level == FlashCrashLevel.FLASH_CRASH

    @property
    def should_halt_trading(self) -> bool:
        return self._level in (FlashCrashLevel.ELEVATED, FlashCrashLevel.FLASH_CRASH)

    @property
    def should_close_positions(self) -> bool:
        return self._level == FlashCrashLevel.FLASH_CRASH

    def reset(self) -> None:
        self._price_history.clear()
        self._tick_times.clear()
        self._volume_samples.clear()
        self._largest_tick = 0.0
        self._level = FlashCrashLevel.NORMAL
        self._alert_level_since = 0.0
        self._flash_crash_triggered = False
        self._avg_volume = 0.0
