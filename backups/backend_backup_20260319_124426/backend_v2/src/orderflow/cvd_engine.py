"""
CVD engine — Cumulative Volume Delta with slope and divergence.

CVD = cumulative sum of (ask_vol - bid_vol) from session open.
Slope = linear regression over 20-candle window.
Divergence = price/CVD disagreement.
"""

from typing import List, Optional

import numpy as np

from src.config.engine_config import CFG


class CVDEngine:
    """
    Cumulative Volume Delta tracking.

    Maintains running CVD, calculates slope, detects divergence.
    """

    def __init__(self):
        self._cvd: float = 0.0
        self._cvd_series: List[float] = []
        self._price_highs: List[float] = []
        self._price_lows: List[float] = []

    def update(self, delta: int) -> None:
        """
        Append delta to running CVD.

        Args:
            delta: ask_vol - bid_vol for the current tick
        """
        self._cvd += delta
        self._cvd_series.append(self._cvd)

    def get_current(self) -> float:
        """Get current CVD value."""
        return self._cvd

    def get_slope(self, window: int = CFG.cvd_slope_window) -> float:
        """
        Calculate CVD slope over rolling window.

        Uses linear regression on the last N CVD values.
        Returns slope as CVD change per candle.
        """
        if len(self._cvd_series) < window:
            return 0.0

        recent = self._cvd_series[-window:]
        x = np.arange(len(recent))
        y = np.array(recent)

        # Linear regression
        if len(x) < 2:
            return 0.0

        slope, _ = np.polyfit(x, y, 1)
        return float(slope)

    def detect_divergence(
        self,
        price_extremes: List[float],
        lookback: int = CFG.cvd_divergence_lookback,
    ) -> Optional[str]:
        """
        Detect CVD divergence.

        Bullish divergence: price makes new low, CVD does not.
        Bearish divergence: price makes new high, CVD does not.

        Returns "BULLISH", "BEARISH", or None.
        """
        if len(self._cvd_series) < lookback or len(price_extremes) < lookback:
            return None

        recent_cvd = self._cvd_series[-lookback:]
        recent_prices = price_extremes[-lookback:]

        # Find extremes
        cvd_min_idx = recent_cvd.index(min(recent_cvd))
        cvd_max_idx = recent_cvd.index(max(recent_cvd))
        price_min_idx = recent_prices.index(min(recent_prices))
        price_max_idx = recent_prices.index(max(recent_prices))

        # Bullish divergence: price new low, CVD higher
        if price_min_idx == len(recent_prices) - 1:
            if cvd_min_idx < len(recent_cvd) - 1:
                if recent_cvd[-1] > recent_cvd[cvd_min_idx]:
                    return "BULLISH"

        # Bearish divergence: price new high, CVD lower
        if price_max_idx == len(recent_prices) - 1:
            if cvd_max_idx < len(recent_cvd) - 1:
                if recent_cvd[-1] < recent_cvd[cvd_max_idx]:
                    return "BEARISH"

        return None

    def update_price_extreme(self, price: float) -> None:
        """Track price extremes for divergence detection."""
        self._price_highs.append(price)
        self._price_lows.append(price)

    def reset(self) -> None:
        """Reset for new session."""
        self._cvd = 0.0
        self._cvd_series.clear()
        self._price_highs.clear()
        self._price_lows.clear()