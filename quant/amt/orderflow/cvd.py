"""CVD Tracker — Cumulative Volume Delta tracking with slope & divergence.

Tracks running CVD across candles, computes its slope as EMA3(CVD) − EMA9(CVD)
(spec §6.2; linear-regression slope removed), and detects price-vs-CVD
divergence (absorption signals).

Enhanced with:
- Sign persistence filter to prevent rapid slope flipping
"""

from __future__ import annotations

from dataclasses import dataclass

from quant.contracts.value_objects import OHLC
from quant.amt import compute as mc
from quant.contracts.constants import CVD_SLOPE_EXTENDED_WINDOW, CVD_SLOPE_PERSISTENCE_BARS
from quant.contracts.timezones import epoch_to_iso


# ---------------------------------------------------------------------------
# Value Objects
# ---------------------------------------------------------------------------


def _ema(values: list[float], period: int) -> float:
    """EMA over ``values`` with alpha = 2/(period+1), seeded at values[0]."""
    if not values:
        return 0.0
    alpha = 2.0 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = alpha * v + (1 - alpha) * ema
    return ema


def direction_of_signed(value: float | None, *, epsilon: float = 0.0) -> str | None:
    """Map a signed order-flow value to the direction it supports.

    Returns ``"LONG"``/``"SHORT"``, or ``None`` when the value is absent or
    inside ``epsilon`` of flat (indeterminate).

    This exists so CVD slope, OFI, normalised delta and any future signed flow
    metric share ONE sign convention. Before it, three call sites each tested
    the sign themselves and disagreed about whether a flat reading was
    supportive (see the review's P0-5 / P1-11 findings).
    """
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric != numeric:  # NaN is indeterminate, never a direction
        return None
    if numeric > epsilon:
        return "LONG"
    if numeric < -epsilon:
        return "SHORT"
    return None


@dataclass(frozen=True)
class CVDState:
    """Snapshot of the CVD tracker at a point in time."""

    value: float  # Current cumulative delta
    slope: float  # EMA3(CVD) − EMA9(CVD) with sign persistence
    has_divergence: bool  # Price vs CVD divergence detected?
    divergence_type: str  # "BULLISH_DIV" | "BEARISH_DIV" | "NONE"
    z_score: float = 0.0  # Z-score of divergence strength


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

    def __init__(
        self, slope_window: int = CVD_SLOPE_EXTENDED_WINDOW, divergence_window: int = 20
    ) -> None:
        self._cvd: float = 0.0
        self._history: list[float] = []  # CVD values
        self._price_history: list[float] = []  # Close prices
        self._slope_window = slope_window
        self._divergence_window = divergence_window
        self._last_time: str = ""
        # Slope sign persistence filter
        self._slope_sign_history: list[int] = []  # +1, -1, or 0 per bar
        self._last_emitted_slope: float = 0.0

    # -- public API ----------------------------------------------------------

    def reset(self) -> None:
        self._cvd = 0.0
        self._history.clear()
        self._price_history.clear()
        self._last_time = ""
        self._slope_sign_history.clear()
        self._last_emitted_slope = 0.0

    def update(self, candle: OHLC) -> CVDState:
        """Consume one candle and return the updated state.

        Automatically resets at session boundaries (detected by time going
        backwards, which indicates a new trading day/session).
        """
        candle_time = epoch_to_iso(candle.time)
        if candle_time == self._last_time:
            return self.state()

        # Session boundary detection: time going backwards = new session
        if self._last_time and candle_time < self._last_time:
            self.reset()
        self._last_time = candle_time

        self._cvd += float(candle.delta)
        self._history.append(self._cvd)
        self._price_history.append(float(candle.close))

        # Cap history to prevent unbounded growth
        if len(self._history) > self._MAX_HISTORY:
            trim = len(self._history) - self._MAX_HISTORY
            self._history = self._history[trim:]
            self._price_history = self._price_history[trim:]

        self._compute_slope(advance_persistence=True)
        return self.state()

    def export_state(self) -> dict:
        """Persistable snapshot of CVD rolling state for mid-session restart."""
        return {
            "cvd": self._cvd,
            "history": list(self._history),
            "price_history": list(self._price_history),
            "last_time": self._last_time,
            "slope_sign_history": list(self._slope_sign_history),
            "last_emitted_slope": self._last_emitted_slope,
        }

    def import_state(self, data: dict | None) -> None:
        if not data:
            return
        self._cvd = float(data.get("cvd") or 0.0)
        self._history = [float(x) for x in (data.get("history") or [])]
        self._price_history = [float(x) for x in (data.get("price_history") or [])]
        self._last_time = str(data.get("last_time") or "")
        self._slope_sign_history = [int(x) for x in (data.get("slope_sign_history") or [])]
        self._last_emitted_slope = float(data.get("last_emitted_slope") or 0.0)

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

    def _compute_slope(self, *, advance_persistence: bool = False) -> float:
        """EMA3(CVD) − EMA9(CVD) with sign persistence filter.

        The raw slope is the difference of a 3-period and 9-period EMA over
        the CVD history (spec §6.2). The emitted slope only changes sign after
        the new sign persists for CVD_SLOPE_PERSISTENCE_BARS consecutive bars.
        This prevents rapid flipping like +33k → +5k → -3k → -7k. Persistence
        advances only when explicitly requested by ``update()``.
        """
        history = list(self._history)
        if len(history) < 3:
            return 0.0

        raw_slope = _ema(history, 3) - _ema(history, 9)

        # Track sign: +1 for positive, -1 for negative, 0 for near-zero
        if raw_slope > 0.01:
            current_sign = 1
        elif raw_slope < -0.01:
            current_sign = -1
        else:
            current_sign = 0

        # When reading state() without advancing, evaluate persistence against a
        # virtual sign history that includes the current sign — same result as
        # update() would emit for this history without mutating.
        sign_history = list(self._slope_sign_history)
        if advance_persistence:
            self._slope_sign_history.append(current_sign)
            sign_history = list(self._slope_sign_history)
        else:
            sign_history = sign_history + [current_sign]

        if len(sign_history) < CVD_SLOPE_PERSISTENCE_BARS:
            if advance_persistence:
                self._last_emitted_slope = raw_slope
            return raw_slope

        recent_signs = sign_history[-CVD_SLOPE_PERSISTENCE_BARS:]
        if all(s == current_sign for s in recent_signs):
            if advance_persistence:
                self._last_emitted_slope = raw_slope
            return raw_slope

        return self._last_emitted_slope

    def _detect_divergence(self) -> tuple[str, float]:
        """Detect price-vs-CVD divergence (MLX-accelerated)."""
        w = self._divergence_window
        if len(self._history) < w or len(self._price_history) < w:
            return "NONE", 0.0
        return mc.divergence_detect(
            self._price_history[-w:],
            self._history[-w:],
        )
