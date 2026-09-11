"""Asynchronous Volatility Sidecar (quant/sidecars/volatility/regime_filter.py).

Executes once every 15 minutes on completed 15-minute bars.
Analyzes Realized Volatility and ATR expansion paths.
Calculates the normalized quantile uncertainty spread:
    Q_spread = (p90 - p10) / p50
If Q_spread exceeds the 95th percentile threshold, sets macro_risk_cap = 0.5 in
SessionRiskAuthority, capping maximum portfolio risk during macroeconomic shocks.
Cannot initiate trades, cancel orders, or move stops.
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

from quant.execution.risk import SessionRiskAuthority

logger = logging.getLogger(__name__)


class VolatilityRegimeFilter:
    """15-minute background volatility and macro uncertainty estimator."""

    def __init__(
        self,
        risk_authority: Optional[SessionRiskAuthority] = None,
        q_spread_p95_threshold: float = 1.8,
    ) -> None:
        self._risk_authority = risk_authority
        self._q_spread_threshold = q_spread_p95_threshold
        self._last_q_spread: float = 0.0

    def evaluate_15m_bar(
        self,
        p10: float,
        p50: float,
        p90: float,
    ) -> float:
        """Calculate Q_spread and apply macro risk cap if exceeding threshold."""
        if p50 <= 1e-6:
            return 0.0

        q_spread = (p90 - p10) / p50
        self._last_q_spread = q_spread

        if q_spread > self._q_spread_threshold:
            logger.warning(
                "Macro volatility shock detected: Q_spread=%.2f > %.2f — capping macro risk to 0.5",
                q_spread,
                self._q_spread_threshold,
            )
            if self._risk_authority is not None:
                self._risk_authority.macro_risk_cap = 0.5
        else:
            if self._risk_authority is not None and self._risk_authority.macro_risk_cap < 1.0:
                self._risk_authority.macro_risk_cap = 1.0

        return q_spread

    @property
    def last_q_spread(self) -> float:
        return self._last_q_spread


__all__ = [
    "VolatilityRegimeFilter",
]
