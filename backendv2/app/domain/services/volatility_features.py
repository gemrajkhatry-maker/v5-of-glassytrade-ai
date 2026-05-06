"""IV/VIX/PCR feature extraction for ML models."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class VIXRegime(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    SPIKE = "SPIKE"


@dataclass(frozen=True)
class VolatilityFeatures:
    india_vix_raw: float = 0.0
    india_vix_normalized: float = 0.0
    vix_regime: VIXRegime = VIXRegime.NORMAL
    vix_regime_name: str = "NORMAL"
    iv_rank: float = 50.0
    iv_percentile: float = 50.0
    pcr_oi: float = 1.0
    pcr_signal_normalized: float = 0.0

    def to_feature_dict(self) -> dict[str, float]:
        regime_map = {
            VIXRegime.LOW: 0.0,
            VIXRegime.NORMAL: 1.0,
            VIXRegime.ELEVATED: 2.0,
            VIXRegime.SPIKE: 3.0,
        }
        return {
            "india_vix_normalized": self.india_vix_normalized,
            "vix_regime": regime_map[self.vix_regime],
            "iv_rank": self.iv_rank,
            "iv_percentile": self.iv_percentile,
            "pcr_oi": self.pcr_oi,
            "pcr_signal_normalized": self.pcr_signal_normalized,
        }


class VolatilityFeatureProvider:
    """Rolling volatility state provider used by strategy/risk modules."""

    def __init__(self) -> None:
        self._vix_history: list[float] = []
        self._iv_history: dict[str, list[float]] = {}

    def update_vix(self, vix_value: float) -> None:
        self._vix_history.append(float(vix_value))
        if len(self._vix_history) > 20 * 78:
            self._vix_history = self._vix_history[-20 * 78 :]

    def update_iv(self, underlying: str, iv_value: float) -> None:
        bucket = self._iv_history.setdefault(underlying, [])
        bucket.append(float(iv_value))
        if len(bucket) > 20 * 78:
            self._iv_history[underlying] = bucket[-20 * 78 :]

    def get_features(
        self,
        underlying: str,
        vix_value: float = 0.0,
        current_iv: float = 0.0,
        total_put_oi: float = 0.0,
        total_call_oi: float = 0.0,
    ) -> VolatilityFeatures:
        india_vix_normalized = vix_value / 20.0 if vix_value > 0 else 1.0
        vix_regime = self._classify_vix_regime(vix_value)

        iv_history = self._iv_history.get(underlying, [])
        if len(iv_history) >= 2 and current_iv > 0:
            iv_min = min(iv_history)
            iv_max = max(iv_history)
            if iv_max > iv_min:
                iv_rank = ((current_iv - iv_min) / (iv_max - iv_min)) * 100
            else:
                iv_rank = 50.0
            below_count = sum(1 for iv in iv_history if iv < current_iv)
            iv_percentile = (below_count / len(iv_history)) * 100
        else:
            iv_rank = 50.0
            iv_percentile = 50.0

        pcr_oi = total_put_oi / total_call_oi if total_call_oi > 0 else 1.0
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
        if vix_regime == VIXRegime.LOW:
            return {"ml_threshold_adjust": 0.05, "size_multiplier": 0.80, "sl_multiplier": 1.0, "block_tier_a": False}
        if vix_regime == VIXRegime.SPIKE:
            return {"ml_threshold_adjust": 0.0, "size_multiplier": 0.50, "sl_multiplier": 1.5, "block_tier_a": True}
        return {"ml_threshold_adjust": 0.0, "size_multiplier": 1.0, "sl_multiplier": 1.0, "block_tier_a": False}

    @staticmethod
    def _classify_vix_regime(vix_value: float) -> VIXRegime:
        if vix_value < 12:
            return VIXRegime.LOW
        if vix_value < 18:
            return VIXRegime.NORMAL
        if vix_value < 25:
            return VIXRegime.ELEVATED
        return VIXRegime.SPIKE

