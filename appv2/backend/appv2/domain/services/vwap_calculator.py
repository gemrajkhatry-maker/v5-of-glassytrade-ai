"""VWAP Calculator — session VWAP with sigma bands.

Features:
- Incremental update per candle
- Session boundary auto-reset
- Sigma bands: ±1σ, ±2σ
- Variance tracking for band computation
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class VWAPResult:
    """VWAP computation result with sigma bands."""
    vwap: float
    variance: float
    sigma: float
    upper_1: float  # +1σ
    lower_1: float  # -1σ
    upper_2: float  # +2σ
    lower_2: float  # -2σ


class VWAPCalculator:
    """Session VWAP with sigma bands — incremental computation.

    Usage:
        calc = VWAPCalculator()
        result = calc.update_candle(candle)  # OHLC candle
    """

    def __init__(self):
        self._cum_tp_vol: float = 0.0  # Σ(typical_price × volume)
        self._cum_vol: float = 0.0  # Σ(volume)
        self._cum_sq_vol: float = 0.0  # Σ(tp² × volume) — for variance
        self._last_time: str = ""

    def update_candle(self, candle) -> VWAPResult:
        """Update VWAP with a new candle.

        Args:
            candle: OHLC object with high, low, close, volume, time.
        """
        tp = (candle.high + candle.low + candle.close) / 3.0
        vol = float(candle.volume)

        # Session boundary detection
        if self._is_new_session(candle.time):
            self.reset()

        # Incremental update
        if vol > 0:
            self._cum_tp_vol += tp * vol
            self._cum_vol += vol
            self._cum_sq_vol += tp * tp * vol

        self._last_time = candle.time

        return self._compute_result(candle.close)

    def update_tick(self, price: float, volume: float, tick_time: str = "") -> VWAPResult:
        """Update VWAP with a single tick."""
        if volume <= 0:
            return self._compute_result(price)

        if self._is_new_session(tick_time):
            self.reset()

        self._cum_tp_vol += price * volume
        self._cum_vol += volume
        self._cum_sq_vol += price * price * volume

        if tick_time:
            self._last_time = tick_time

        return self._compute_result(price)

    def _compute_result(self, current_price: float) -> VWAPResult:
        if self._cum_vol <= 0:
            return VWAPResult(
                vwap=current_price,
                variance=0.0,
                sigma=0.0,
                upper_1=current_price,
                lower_1=current_price,
                upper_2=current_price,
                lower_2=current_price,
            )

        vwap = self._cum_tp_vol / self._cum_vol

        # Variance: E[X²] - E[X]²
        mean_sq = self._cum_sq_vol / self._cum_vol
        variance = max(0.0, mean_sq - vwap * vwap)
        sigma = math.sqrt(variance)

        return VWAPResult(
            vwap=vwap,
            variance=variance,
            sigma=sigma,
            upper_1=vwap + sigma,
            lower_1=vwap - sigma,
            upper_2=vwap + 2 * sigma,
            lower_2=vwap - 2 * sigma,
        )

    def _is_new_session(self, tick_time: str) -> bool:
        """Detect session boundary from timestamp."""
        if not tick_time or not self._last_time:
            return False
        # New day = new session
        try:
            return tick_time[:10] != self._last_time[:10]
        except (TypeError, IndexError):
            return tick_time < self._last_time  # Time went backwards

    def reset(self) -> None:
        """Reset for new session."""
        self._cum_tp_vol = 0.0
        self._cum_vol = 0.0
        self._cum_sq_vol = 0.0
        self._last_time = ""

    @property
    def cumulative_volume(self) -> float:
        return self._cum_vol
