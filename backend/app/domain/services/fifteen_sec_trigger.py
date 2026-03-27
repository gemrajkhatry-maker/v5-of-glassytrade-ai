"""15-Sec Trigger Engine — 3-condition scalp entry trigger.

The most latency-sensitive component in the system. Must run in < 5ms.

Conditions (ALL must be true):
  1. Large print detected (volume ≥ 3× rolling avg)
  2. No opposing absorption within 3 ticks
  3. 15-sec CVD flip (crosses zero)
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class TriggerDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"


@dataclass(frozen=True)
class TriggerResult:
    """Immutable result of 15-sec trigger evaluation."""

    triggered: bool
    direction: TriggerDirection
    large_print_detected: bool
    opposing_absorption: bool
    cvd_flip: bool
    print_volume: float
    avg_volume: float


class FifteenSecTriggerEngine:
    """3-condition scalp trigger engine.

    Designed for < 5ms latency. Uses EMA for rolling average (fast),
    deque for tick window (bounded memory).
    """

    def __init__(
        self,
        large_print_multiplier: float = 3.0,
        absorption_multiplier: float = 2.5,
        flip_magnitude_pct: float = 0.15,
        ema_alpha: float = 0.1,
        tick_window_size: int = 30,
    ) -> None:
        self._large_mult = large_print_multiplier
        self._absorb_mult = absorption_multiplier
        self._flip_pct = flip_magnitude_pct
        self._alpha = ema_alpha
        self._tick_window = deque(maxlen=tick_window_size)
        self._rolling_avg: float = 0.0
        self._initialized: bool = False

        # 15-sec bar state
        self._bar_cvd: float = 0.0
        self._prev_bar_cvd: float = 0.0
        self._bar_start: float = 0.0

    def update(
        self,
        price: float,
        volume: float,
        delta: float,
        timestamp: float,
    ) -> TriggerResult:
        """Process one tick and evaluate trigger conditions.

        Args:
            price: Last traded price
            volume: Tick volume
            delta: Signed delta (positive = buy, negative = sell)
            timestamp: Unix timestamp in seconds

        Returns:
            TriggerResult with all 3 condition evaluations
        """
        # Update rolling average (EMA) — store previous for large print check
        prev_avg = self._rolling_avg
        if not self._initialized:
            self._rolling_avg = volume
            prev_avg = volume
            self._initialized = True
        else:
            self._rolling_avg = (
                self._alpha * volume + (1 - self._alpha) * self._rolling_avg
            )

        self._tick_window.append(
            {
                "price": price,
                "volume": volume,
                "delta": delta,
                "time": timestamp,
            }
        )

        # Check 15-sec bar boundary
        if self._bar_start == 0:
            self._bar_start = timestamp
        elif timestamp - self._bar_start >= 15:
            self._prev_bar_cvd = self._bar_cvd
            self._bar_cvd = 0.0
            self._bar_start = timestamp

        self._bar_cvd += delta

        # Condition 1: Large print
        is_large = volume >= self._large_mult * prev_avg if prev_avg > 0 else False
        direction = TriggerDirection.NONE
        if is_large:
            direction = TriggerDirection.LONG if delta > 0 else TriggerDirection.SHORT

        # Condition 2: Opposing absorption check
        opposing_absorption = False
        if is_large and len(self._tick_window) >= 2:
            check_ticks = list(self._tick_window)[-4:-1]  # last 3 ticks before current
            for t in check_ticks:
                t_is_large = t["volume"] >= self._absorb_mult * prev_avg
                t_opposing = (delta > 0 and t["delta"] < 0) or (
                    delta < 0 and t["delta"] > 0
                )
                t_same_level = abs(t["price"] - price) < price * 0.001  # within 0.1%
                if t_is_large and t_opposing and t_same_level:
                    opposing_absorption = True
                    break

        # Condition 3: CVD flip
        cvd_flip = False
        if is_large and prev_avg > 0:
            flip_magnitude = abs(self._bar_cvd - self._prev_bar_cvd)
            if flip_magnitude >= self._flip_pct * prev_avg:
                if (
                    direction == TriggerDirection.LONG
                    and self._prev_bar_cvd < 0
                    and self._bar_cvd > 0
                ):
                    cvd_flip = True
                elif (
                    direction == TriggerDirection.SHORT
                    and self._prev_bar_cvd > 0
                    and self._bar_cvd < 0
                ):
                    cvd_flip = True

        # All 3 conditions must be true
        triggered = is_large and not opposing_absorption and cvd_flip

        return TriggerResult(
            triggered=triggered,
            direction=direction if triggered else TriggerDirection.NONE,
            large_print_detected=is_large,
            opposing_absorption=opposing_absorption,
            cvd_flip=cvd_flip,
            print_volume=volume,
            avg_volume=self._rolling_avg,
        )

    def reset(self) -> None:
        """Reset for new session."""
        self._tick_window.clear()
        self._rolling_avg = 0.0
        self._initialized = False
        self._bar_cvd = 0.0
        self._prev_bar_cvd = 0.0
        self._bar_start = 0.0
