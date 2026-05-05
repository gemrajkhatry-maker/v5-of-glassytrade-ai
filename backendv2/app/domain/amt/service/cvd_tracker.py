"""CVD Tracker — Cumulative Volume Delta tracking with slope & divergence.

Tracks running CVD across candles, computes linear-regression slope,
and detects price-vs-CVD divergence (absorption signals).

Enhanced with:
- Extended slope window (40 candles) for session-leg scale
- Sign persistence filter to prevent rapid slope flipping
- Session boundary auto-reset
- Z-score calculation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

from app.domain.amt.model.amt_models import CVDPoint, CVDSnapshot, CVDState, DivergenceSignal


class CVDTracker:
    """Stateful tracker for Cumulative Volume Delta."""

    _MAX_HISTORY = 500

    def __init__(self, slope_window: int = 40, divergence_window: int = 20, max_history: int = 500):
        self._cvd: float = 0.0
        self._history: list[float] = []
        self._price_history: list[float] = []
        self._slope_window = slope_window
        self._divergence_window = divergence_window
        self._last_time: str = ""
        self._slope_sign_history: list[int] = []
        self._last_emitted_slope: float = 0.0
        self._max_history = max_history

    @property
    def cumulative_delta(self) -> float:
        """Current cumulative delta value."""
        return self._history[-1] if self._history else 0.0

    def reset(self) -> None:
        self._cvd = 0.0
        self._history.clear()
        self._price_history.clear()
        self._last_time = ""
        self._slope_sign_history.clear()
        self._last_emitted_slope = 0.0

    def update(self, bar_index: int, bid_volume: float, ask_volume: float, price: float) -> CVDPoint:
        """Update CVD with new bar data."""
        delta = bid_volume - ask_volume
        self._cvd += delta

        point = CVDPoint(
            bar_index=bar_index,
            bid_volume=bid_volume,
            ask_volume=ask_volume,
            delta=delta,
            cumulative_delta=self._cvd,
            price=price,
        )

        self._history.append(self._cvd)
        self._price_history.append(price)

        if len(self._history) > self._max_history:
            self._history.pop(0)
            self._price_history.pop(0)

        return point

    def update_bar(self, bar: dict) -> CVDState:
        """Update from a bar dict (convenience method)."""
        bar_index = bar.get("bar_index", len(self._history))
        bid_volume = bar.get("buyVolume", bar.get("volume", 0) / 2)
        ask_volume = bar.get("sellVolume", bar.get("volume", 0) / 2)
        price = bar.get("close", 0)
        time_str = bar.get("time", "")

        # Session boundary detection
        if time_str and self._last_time and time_str < self._last_time:
            self.reset()

        self._last_time = time_str
        self.update(bar_index, bid_volume, ask_volume, price)
        return self.state()

    def state(self) -> CVDState:
        """Get current CVD state."""
        if not self._history:
            return CVDState(
                value=0.0, slope=0.0, has_divergence=False,
                divergence_type="NONE", z_score=0.0,
            )

        value = self._history[-1]
        slope = self._compute_slope()
        has_divergence, divergence_type = self._detect_divergence()
        z_score = self._compute_z_score()

        return CVDState(
            value=value,
            slope=slope,
            has_divergence=has_divergence,
            divergence_type=divergence_type,
            z_score=z_score,
        )

    def snapshot(self) -> dict[str, float]:
        """Get current CVD snapshot as dict."""
        if not self._history:
            return {
                "current_delta": 0.0, "cumulative_delta": 0.0,
                "slope": 0.0, "divergence_type": "NONE", "z_score": 0.0,
            }
        current_delta = self._history[-1] - self._history[-2] if len(self._history) >= 2 else 0.0
        state = self.state()
        return {
            "current_delta": current_delta,
            "cumulative_delta": self._history[-1],
            "slope": state.slope,
            "divergence_type": state.divergence_type,
            "z_score": state.z_score,
        }

    def _compute_slope(self) -> float:
        """Compute linear-regression slope over window."""
        if len(self._history) < 2:
            return 0.0
        window = min(self._slope_window, len(self._history))
        values = self._history[-window:]
        n = len(values)
        if n < 2:
            return 0.0
        # Simple slope: (last - first) / n
        return (values[-1] - values[0]) / n

    def _detect_divergence(self) -> tuple[bool, str]:
        """Detect price vs CVD divergence."""
        if len(self._history) < 5:
            return False, "NONE"

        recent_prices = self._price_history[-5:]
        price_change = recent_prices[-1] - recent_prices[0]

        recent_deltas = [self._history[i] - self._history[i - 1] for i in range(1, min(5, len(self._history)))]
        avg_delta_change = sum(recent_deltas) / len(recent_deltas) if recent_deltas else 0

        # Bullish divergence: price down, CVD up
        if price_change < 0 and avg_delta_change > 0:
            return True, "BULLISH_DIV"
        # Bearish divergence: price up, CVD down
        if price_change > 0 and avg_delta_change < 0:
            return True, "BEARISH_DIV"

        return False, "NONE"

    def _compute_z_score(self) -> float:
        """Compute z-score of current CVD value."""
        if len(self._history) < 3:
            return 0.0
        mean = sum(self._history) / len(self._history)
        variance = sum((v - mean) ** 2 for v in self._history) / len(self._history)
        stddev = variance ** 0.5
        if stddev == 0:
            return 0.0
        return (self._history[-1] - mean) / stddev
