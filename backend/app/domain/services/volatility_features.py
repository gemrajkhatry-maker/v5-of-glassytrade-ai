"""IV/VIX/PCR Feature Provider — volatility regime features for ML models.

Provides 6 new features for the ML feature vector:
  india_vix_normalized: raw VIX / 20.0
  vix_regime: 0 (LOW), 1 (NORMAL), 2 (ELEVATED), 3 (SPIKE)
  iv_rank: (current - 20d_min) / (20d_max - 20d_min) × 100
  iv_percentile: % of 20-day history below current IV
  pcr_oi: put_oi / call_oi
  pcr_signal_normalized: (pcr_oi - 0.95) / 0.95
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class VIXRegime(str, Enum):
    LOW = "LOW"  # VIX < 12
    NORMAL = "NORMAL"  # 12 <= VIX < 18
    ELEVATED = "ELEVATED"  # 18 <= VIX < 25
    SPIKE = "SPIKE"  # VIX >= 25


@dataclass(frozen=True)
class VolatilityFeatures:
    """Immutable snapshot of volatility features for ML input."""

    india_vix_raw: float = 0.0
    india_vix_normalized: float = 0.0
    vix_regime: VIXRegime = VIXRegime.NORMAL  # enum
    vix_regime_name: str = "NORMAL"
    iv_rank: float = 50.0
    iv_percentile: float = 50.0
    pcr_oi: float = 1.0
    pcr_signal_normalized: float = 0.0

    def to_feature_dict(self) -> dict[str, float]:
        """Convert to flat feature dict for ML input."""
        regime_map = {
            VIXRegime.LOW: 0,
            VIXRegime.NORMAL: 1,
            VIXRegime.ELEVATED: 2,
            VIXRegime.SPIKE: 3,
        }
        return {
            "india_vix_normalized": self.india_vix_normalized,
            "vix_regime": float(regime_map.get(self.vix_regime, 1)),
            "iv_rank": self.iv_rank,
            "iv_percentile": self.iv_percentile,
            "pcr_oi": self.pcr_oi,
            "pcr_signal_normalized": self.pcr_signal_normalized,
        }


class VolatilityFeatureProvider:
    """Provides IV/VIX/PCR features for ML models.

    Computes features from raw market data (VIX value, IV history, option chain OI).
    Can be queried per-symbol to get current feature snapshot.
    """

    def __init__(self) -> None:
        self._vix_history: list[float] = []
        self._iv_history: dict[str, list[float]] = {}  # underlying -> 20d IV history

    def update_vix(self, vix_value: float) -> None:
        """Update VIX value (called per tick or per bar)."""
        self._vix_history.append(vix_value)
        # Keep 20-day history
        if len(self._vix_history) > 20 * 78:  # 78 bars per day
            self._vix_history = self._vix_history[-20 * 78 :]

    def update_iv(self, underlying: str, iv_value: float) -> None:
        """Update IV for an underlying (called per bar)."""
        if underlying not in self._iv_history:
            self._iv_history[underlying] = []
        self._iv_history[underlying].append(iv_value)
        # Keep 20-day history
        if len(self._iv_history[underlying]) > 20 * 78:
            self._iv_history[underlying] = self._iv_history[underlying][-20 * 78 :]

    def get_features(
        self,
        underlying: str,
        vix_value: float = 0.0,
        current_iv: float = 0.0,
        total_put_oi: float = 0.0,
        total_call_oi: float = 0.0,
    ) -> VolatilityFeatures:
        """Compute current volatility features.

        Args:
            underlying: Symbol underlying (NIFTY, BANKNIFTY, etc.)
            vix_value: Current India VIX value
            current_iv: Current implied volatility for the underlying
            total_put_oi: Total put open interest
            total_call_oi: Total call open interest

        Returns:
            VolatilityFeatures snapshot
        """
        # VIX features
        india_vix_normalized = vix_value / 20.0 if vix_value > 0 else 1.0
        vix_regime = self._classify_vix_regime(vix_value)

        # IV Rank
        iv_history = self._iv_history.get(underlying, [])
        if len(iv_history) >= 2 and current_iv > 0:
            iv_min = min(iv_history)
            iv_max = max(iv_history)
            if iv_max > iv_min:
                iv_rank = ((current_iv - iv_min) / (iv_max - iv_min)) * 100
            else:
                iv_rank = 50.0

            # IV Percentile
            below_count = sum(1 for iv in iv_history if iv < current_iv)
            iv_percentile = (below_count / len(iv_history)) * 100
        else:
            iv_rank = 50.0
            iv_percentile = 50.0

        # PCR
        if total_call_oi > 0:
            pcr_oi = total_put_oi / total_call_oi
        else:
            pcr_oi = 1.0
        pcr_signal = (pcr_oi - 0.95) / 0.95

        return VolatilityFeatures(
            india_vix_raw=vix_value,
            india_vix_normalized=india_vix_normalized,
            vix_regime=vix_regime,
            vix_regime_name=vix_regime.name,
            iv_rank=round(iv_rank, 1),
            iv_percentile=round(iv_percentile, 1),
            pcr_oi=round(pcr_oi, 3),
            pcr_signal_normalized=round(pcr_signal, 3),
        )

    def get_risk_adjustments(self, vix_regime: VIXRegime) -> dict:
        """Get risk adjustments based on VIX regime.

        Returns dict with ML threshold adjustment and size multiplier.
        """
        if vix_regime == VIXRegime.LOW:
            return {
                "ml_threshold_adjust": 0.05,  # tighter (harder to pass)
                "size_multiplier": 0.80,  # reduce size 20%
                "sl_multiplier": 1.0,
                "block_tier_a": False,
            }
        elif vix_regime == VIXRegime.SPIKE:
            return {
                "ml_threshold_adjust": 0.0,
                "size_multiplier": 0.50,  # reduce size 50%
                "sl_multiplier": 1.5,  # widen SL 1.5x
                "block_tier_a": True,  # block Tier A entry
            }
        else:  # NORMAL or ELEVATED
            return {
                "ml_threshold_adjust": 0.0,
                "size_multiplier": 1.0,
                "sl_multiplier": 1.0,
                "block_tier_a": False,
            }

    @staticmethod
    def _classify_vix_regime(vix_value: float) -> VIXRegime:
        """Classify VIX into regime."""
        if vix_value < 12:
            return VIXRegime.LOW
        elif vix_value < 18:
            return VIXRegime.NORMAL
        elif vix_value < 25:
            return VIXRegime.ELEVATED
        else:
            return VIXRegime.SPIKE
