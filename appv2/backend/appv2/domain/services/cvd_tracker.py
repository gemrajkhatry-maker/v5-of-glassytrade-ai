"""CVD Tracker — Cumulative Volume Delta with slope and divergence detection.

Tracks cumulative delta (buy vol - sell vol) across the session.
Features:
- Incremental update per candle
- Slope calculation (40-bar window)
- Sign persistence filter
- Divergence detection (price vs CVD direction)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque
from appv2.config import constants as C


@dataclass
class CVDState:
    """Current CVD state."""
    cvd: float = 0.0  # Cumulative delta
    slope: float = 0.0  # Recent trend (per-bar)
    has_divergence: bool = False  # Price/CVD divergence detected
    sign_persistence: int = 0  # Consecutive bars with same sign


class CVDTracker:
    """Cumulative Volume Delta tracker."""

    def __init__(self, slope_window: int = C.CVD_SLOPE_WINDOW):
        self._cvd: float = 0.0
        self._slope_window = slope_window
        self._cvd_history: deque[float] = deque(maxlen=slope_window + 1)
        self._sign_persistence: int = 0
        self._last_sign: int = 0  # +1 or -1

    def update_candle(self, candle) -> CVDState:
        """Update CVD with a new candle's delta."""
        delta = getattr(candle, "delta", 0.0)
        self._cvd += delta
        self._cvd_history.append(self._cvd)

        # Compute slope
        slope = self._compute_slope()

        # Sign persistence
        sign = 1 if delta > 0 else (-1 if delta < 0 else 0)
        if sign == self._last_sign and sign != 0:
            self._sign_persistence += 1
        else:
            self._sign_persistence = 1 if sign != 0 else 0
            self._last_sign = sign

        return self.state()

    def _compute_slope(self) -> float:
        """Linear regression slope of CVD over window."""
        if len(self._cvd_history) < 4:
            return 0.0

        n = len(self._cvd_history)
        xs = list(range(n))
        ys = list(self._cvd_history)

        x_mean = sum(xs) / n
        y_mean = sum(ys) / n

        num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
        den = sum((x - x_mean) ** 2 for x in xs)

        if den == 0:
            return 0.0
        return num / den

    def check_divergence(self, price_direction: int) -> bool:
        """Check if CVD direction diverges from price direction.

        Args:
            price_direction: +1 for price up, -1 for price down.
        Returns:
            True if CVD is moving opposite to price.
        """
        cvd_direction = 1 if self._cvd > 0 else -1
        return cvd_direction != price_direction and abs(self._cvd) > 100

    def state(self) -> CVDState:
        return CVDState(
            cvd=self._cvd,
            slope=self._compute_slope(),
            has_divergence=False,  # Set by caller with price context
            sign_persistence=self._sign_persistence,
        )

    def reset(self) -> None:
        """Reset at session boundary."""
        self._cvd = 0.0
        self._cvd_history.clear()
        self._sign_persistence = 0
        self._last_sign = 0
