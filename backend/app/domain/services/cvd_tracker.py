"""CVDTracker — Cumulative Volume Delta tracker with slope and divergence.

Extracted from amt_analyzer.py for independent testing and config injection.

State maintained per symbol:
- Running CVD (cumulative delta)
- Bar delta accumulator (reset per bar)
- Rolling bar delta history (for slope computation)
- Slope computed via linear regression over rolling window

CVD slope states:
  |slope| < cvd_strong_slope (2.0)   → NEUTRAL
  |slope| < cvd_slope_warning (30)   → NORMAL
  |slope| < cvd_slope_hard_block (50)→ WARNING
  |slope| < cvd_slope_extreme (100)  → HARD_BLOCK
  |slope| ≥ cvd_slope_extreme (100)  → EXTREME
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CVDSnapshot:
    """Immutable snapshot of CVD state at any point in time."""

    cvd: float  # Cumulative volume delta
    bar_delta: float  # Current bar's accumulated delta
    slope: float  # Slope over rolling window
    state: str  # NEUTRAL/NORMAL/WARNING/HARD_BLOCK/EXTREME
    is_kill_signal: bool  # True if EXTREME
    direction: str  # "BULLISH"/"BEARISH"/"NEUTRAL"
    divergence: str  # "BULLISH"/"BEARISH"/"NONE"


class CVDTracker:
    """Tracks cumulative volume delta, slope, and divergence.

    Thread-safe: each symbol gets its own instance.
    """

    def __init__(
        self,
        rolling_bars: int = 20,
        strong_slope: float = 2.0,
        warning_threshold: float = 30.0,
        hard_block_threshold: float = 50.0,
        extreme_threshold: float = 100.0,
    ) -> None:
        self._rolling_bars = rolling_bars
        self._strong_slope = strong_slope
        self._warning = warning_threshold
        self._hard_block = hard_block_threshold
        self._extreme = extreme_threshold

        # State
        self._cvd: float = 0.0
        self._bar_delta: float = 0.0
        self._bar_deltas: deque[float] = deque(maxlen=rolling_bars)
        self._prev_bar_low: float = 0.0
        self._prev_bar_high: float = 0.0
        self._prev_cvd: float = 0.0

    def add_tick_delta(self, delta: float) -> None:
        """Accumulate a single tick delta into current bar."""
        self._bar_delta += delta
        self._cvd += delta

    def on_bar_close(self, bar_low: float, bar_high: float) -> CVDSnapshot:
        """Finalize current bar and compute CVD state.

        Args:
            bar_low: Current bar's low price (for divergence detection)
            bar_high: Current bar's high price (for divergence detection)

        Returns:
            CVDSnapshot with current CVD state
        """
        # Store bar delta in rolling history
        self._bar_deltas.append(self._bar_delta)

        # Compute slope
        slope = self._compute_slope()

        # Classify state
        state = self._classify_state(slope)

        # Detect divergence
        divergence = self._detect_divergence(bar_low, bar_high)

        # Direction
        if slope > self._strong_slope:
            direction = "BULLISH"
        elif slope < -self._strong_slope:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        snapshot = CVDSnapshot(
            cvd=self._cvd,
            bar_delta=self._bar_delta,
            slope=slope,
            state=state,
            is_kill_signal=(state == "EXTREME"),
            direction=direction,
            divergence=divergence,
        )

        # Reset bar accumulator
        self._prev_bar_low = bar_low
        self._prev_bar_high = bar_high
        self._prev_cvd = self._cvd
        self._bar_delta = 0.0

        return snapshot

    def _compute_slope(self) -> float:
        """Compute CVD slope via linear regression over rolling window.

        slope = Σ(xi - x̄)(yi - ȳ) / Σ(xi - x̄)²

        Where yi = bar delta values, xi = bar index, n = rolling_bars.
        """
        n = len(self._bar_deltas)
        if n < 2:
            return 0.0

        values = list(self._bar_deltas)
        x_mean = (n - 1) / 2.0
        y_mean = sum(values) / n

        numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return 0.0
        return numerator / denominator

    def _classify_state(self, slope: float) -> str:
        """Classify CVD state based on slope magnitude."""
        abs_slope = abs(slope)
        if abs_slope < self._strong_slope:
            return "NEUTRAL"
        if abs_slope < self._warning:
            return "NORMAL"
        if abs_slope < self._hard_block:
            return "WARNING"
        if abs_slope < self._extreme:
            return "HARD_BLOCK"
        return "EXTREME"

    def _detect_divergence(self, bar_low: float, bar_high: float) -> str:
        """Detect CVD divergence from price.

        BULLISH DIVERGENCE:
          price makes lower low BUT CVD makes higher low
          → smart money buying into weakness

        BEARISH DIVERGENCE:
          price makes higher high BUT CVD makes lower high
          → smart money selling into strength
        """
        if self._prev_bar_low == 0 or self._prev_bar_high == 0:
            return "NONE"

        # Bullish divergence: price lower low, CVD higher
        if bar_low < self._prev_bar_low and self._cvd > self._prev_cvd:
            return "BULLISH"

        # Bearish divergence: price higher high, CVD lower
        if bar_high > self._prev_bar_high and self._cvd < self._prev_cvd:
            return "BEARISH"

        return "NONE"

    def reset(self) -> None:
        """Reset all state (call at session open)."""
        self._cvd = 0.0
        self._bar_delta = 0.0
        self._bar_deltas.clear()
        self._prev_bar_low = 0.0
        self._prev_bar_high = 0.0
        self._prev_cvd = 0.0
