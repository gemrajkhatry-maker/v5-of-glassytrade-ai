"""CVD Tracker — Cumulative Volume Delta tracking with slope & divergence.

Tracks running CVD across candles, computes its linear-regression slope,
and detects price-vs-CVD divergence (absorption signals).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.domain.trading.models.value_objects import OHLC


# ---------------------------------------------------------------------------
# Value Objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CVDState:
    """Snapshot of the CVD tracker at a point in time."""
    value: float               # Current cumulative delta
    slope: float               # Linear-regression slope over window
    has_divergence: bool       # Price vs CVD divergence detected?
    divergence_type: str       # "BULLISH_DIV" | "BEARISH_DIV" | "NONE"
    z_score: float = 0.0      # Z-score of divergence strength


# ---------------------------------------------------------------------------
# CVD Tracker
# ---------------------------------------------------------------------------

class CVDTracker:
    """Stateful tracker for Cumulative Volume Delta.

    Call ``update(candle)`` for each new bar. Query ``state()`` at any time
    to get the current CVD value, slope, and divergence status.
    """

    def __init__(self, slope_window: int = 14, divergence_window: int = 20) -> None:
        self._cvd: float = 0.0
        self._history: list[float] = []           # CVD values
        self._price_history: list[float] = []     # Close prices
        self._slope_window = slope_window
        self._divergence_window = divergence_window

    # -- public API ----------------------------------------------------------

    def reset(self) -> None:
        self._cvd = 0.0
        self._history.clear()
        self._price_history.clear()

    def update(self, candle: OHLC) -> CVDState:
        """Consume one candle and return the updated state."""
        # Delta = aggressive buys − aggressive sells
        # In the domain model: candle.delta already carries this value.
        self._cvd += candle.delta
        self._history.append(self._cvd)
        self._price_history.append(candle.close)
        return self.state()

    def state(self) -> CVDState:
        """Return the current CVD state without consuming new data."""
        slope = self._compute_slope()
        div_type, z = self._detect_divergence()
        return CVDState(
            value=self._cvd,
            slope=slope,
            has_divergence=div_type != "NONE",
            divergence_type=div_type,
            z_score=z,
        )

    @property
    def value(self) -> float:
        return self._cvd

    # -- internals -----------------------------------------------------------

    def _compute_slope(self) -> float:
        """Linear-regression slope of recent CVD values."""
        window = self._history[-self._slope_window:]
        n = len(window)
        if n < 3:
            return 0.0

        sum_x = sum_y = sum_xy = sum_xx = 0.0
        for i in range(n):
            sum_x += i
            sum_y += window[i]
            sum_xy += i * window[i]
            sum_xx += i * i

        denom = n * sum_xx - sum_x * sum_x
        if denom == 0:
            return 0.0
        return (n * sum_xy - sum_x * sum_y) / denom

    def _detect_divergence(self) -> tuple[str, float]:
        """Detect price-vs-CVD divergence over recent window.

        Bearish divergence: price makes Higher High, CVD makes Lower High
        Bullish divergence: price makes Lower Low, CVD makes Higher Low
        """
        w = self._divergence_window
        if len(self._history) < w or len(self._price_history) < w:
            return "NONE", 0.0

        prices = self._price_history[-w:]
        cvds = self._history[-w:]
        half = w // 2

        # Compare first-half vs second-half peaks/troughs
        p1_max = max(prices[:half])
        p2_max = max(prices[half:])
        c1_max = max(cvds[:half])
        c2_max = max(cvds[half:])

        p1_min = min(prices[:half])
        p2_min = min(prices[half:])
        c1_min = min(cvds[:half])
        c2_min = min(cvds[half:])

        # Z-score: magnitude of divergence relative to price volatility
        price_std = _std(prices)
        if price_std == 0:
            price_std = 1.0

        # Bearish divergence: price HH, CVD LH (absorption at top)
        if p2_max > p1_max and c2_max < c1_max:
            z = abs(p2_max - p1_max) / price_std
            return "BEARISH_DIV", z

        # Bullish divergence: price LL, CVD HL (absorption at bottom)
        if p2_min < p1_min and c2_min > c1_min:
            z = abs(p2_min - p1_min) / price_std
            return "BULLISH_DIV", z

        return "NONE", 0.0


def _std(values: list[float]) -> float:
    """Population standard deviation."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return math.sqrt(sum((v - mean) ** 2 for v in values) / n)
