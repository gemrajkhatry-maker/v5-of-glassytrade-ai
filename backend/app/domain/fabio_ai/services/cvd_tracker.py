"""CVD Tracker — Cumulative Volume Delta tracking with slope & divergence.

Tracks running CVD across candles, computes its linear-regression slope,
and detects price-vs-CVD divergence (absorption signals).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.trading.models.value_objects import OHLC
from app.domain.fabio_ai.services import mlx_compute as mc


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

    # Maximum history length to prevent unbounded memory growth
    _MAX_HISTORY = 500

    def __init__(self, slope_window: int = 14, divergence_window: int = 20) -> None:
        self._cvd: float = 0.0
        self._history: list[float] = []           # CVD values
        self._price_history: list[float] = []     # Close prices
        self._slope_window = slope_window
        self._divergence_window = divergence_window
        self._last_time: str = ""

    # -- public API ----------------------------------------------------------

    def reset(self) -> None:
        self._cvd = 0.0
        self._history.clear()
        self._price_history.clear()
        self._last_time = ""

    def update(self, candle: OHLC) -> CVDState:
        """Consume one candle and return the updated state.

        Automatically resets at session boundaries (detected by time going
        backwards, which indicates a new trading day/session).
        """
        # Session boundary detection: time going backwards = new session
        if self._last_time and candle.time < self._last_time:
            self.reset()
        self._last_time = candle.time

        self._cvd += candle.delta
        self._history.append(self._cvd)
        self._price_history.append(candle.close)

        # Cap history to prevent unbounded growth
        if len(self._history) > self._MAX_HISTORY:
            trim = len(self._history) - self._MAX_HISTORY
            self._history = self._history[trim:]
            self._price_history = self._price_history[trim:]

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
        """Linear-regression slope of recent CVD values (MLX-accelerated)."""
        window = self._history[-self._slope_window:]
        if len(window) < 3:
            return 0.0
        return mc.linreg_slope(window)

    def _detect_divergence(self) -> tuple[str, float]:
        """Detect price-vs-CVD divergence (MLX-accelerated)."""
        w = self._divergence_window
        if len(self._history) < w or len(self._price_history) < w:
            return "NONE", 0.0
        return mc.divergence_detect(
            self._price_history[-w:],
            self._history[-w:],
        )
