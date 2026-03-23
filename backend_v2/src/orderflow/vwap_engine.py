"""
VWAP engine — Volume Weighted Average Price with σ bands.

VWAP = Σ(TP × Vol) / Σ(Vol)
σ = √(Σ(vol×(TP−VWAP)²) / Σvol)
"""

from typing import Optional

from src.config.engine_config import CFG
from src.core.candle_builder import Candle


class VWAPEngine:
    """
    VWAP calculation with standard deviation bands.
    """

    def __init__(self):
        self._cumulative_pv: float = 0.0
        self._cumulative_vol: int = 0
        self._cumulative_sq: float = 0.0
        self._vwap: float = 0.0
        self._sigma: float = 0.0

    def update(self, candle: Candle) -> None:
        """
        Update VWAP with a new candle.

        Args:
            candle: Closed candle data
        """
        # Typical price
        tp = (candle.high + candle.low + candle.close) / 3

        # Update cumulative values
        self._cumulative_pv += tp * candle.volume
        self._cumulative_vol += candle.volume
        self._cumulative_sq += candle.volume * ((tp - self._vwap) ** 2) if self._vwap > 0 else 0

        # Calculate VWAP
        if self._cumulative_vol > 0:
            self._vwap = self._cumulative_pv / self._cumulative_vol

        # Calculate sigma
        if self._cumulative_vol > 0:
            variance = self._cumulative_sq / self._cumulative_vol
            self._sigma = variance ** 0.5

    def get_vwap(self) -> float:
        """Get current VWAP value."""
        return self._vwap

    def get_sigma(self) -> float:
        """Get current sigma value."""
        return self._sigma

    def get_bands(self) -> dict:
        """
        Get VWAP with σ bands.

        Returns:
            Dict with vwap, sigma1_upper, sigma1_lower, sigma2_upper, sigma2_lower.
        """
        return {
            "vwap": self._vwap,
            "sigma1_upper": self._vwap + self._sigma * CFG.vwap_sigma_1,
            "sigma1_lower": self._vwap - self._sigma * CFG.vwap_sigma_1,
            "sigma2_upper": self._vwap + self._sigma * CFG.vwap_sigma_2,
            "sigma2_lower": self._vwap - self._sigma * CFG.vwap_sigma_2,
        }

    def is_at_extreme(self, price: float, sigma_mult: float = 2.0) -> bool:
        """
        Check if price is at VWAP extreme (beyond σ bands).

        Args:
            price: Current price
            sigma_mult: Sigma multiplier for extreme check

        Returns:
            True if price is beyond sigma_mult * sigma from VWAP.
        """
        if self._sigma <= 0:
            return False

        distance = abs(price - self._vwap)
        return distance > self._sigma * sigma_mult

    def reset(self) -> None:
        """Reset for new session."""
        self._cumulative_pv = 0.0
        self._cumulative_vol = 0
        self._cumulative_sq = 0.0
        self._vwap = 0.0
        self._sigma = 0.0