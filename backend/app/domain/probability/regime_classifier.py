"""Regime classification for agent pipeline.

Extracted from agent_pipeline.py for separation of concerns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.domain.fabio_ai.services.amt_pipeline import AMTResult
from app.domain.trading.models.value_objects import OHLC

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegimeState:
    """Immutable regime classification result."""
    regime: str  # TRENDING, BALANCED, VOLATILE, DEAD
    allowed_long: bool
    allowed_short: bool
    risk_scale: float  # 0.0 = no risk, 1.0 = full risk


class RegimeHysteresis:
    """Adds hysteresis to prevent rapid regime flipping.

    Requires new regime to persist for `min_persistence` consecutive
    evaluations before switching.
    """

    def __init__(self, min_persistence: int = 3) -> None:
        self._min_persistence = min_persistence
        self._current_regime: str = ""
        self._candidate_regime: str = ""
        self._candidate_count: int = 0

    def apply(self, raw_regime: RegimeState) -> RegimeState:
        """Apply hysteresis filter to raw regime result."""
        # DEAD and VOLATILE always pass through immediately (safety)
        if raw_regime.regime in ("DEAD", "VOLATILE"):
            self._current_regime = raw_regime.regime
            self._candidate_regime = ""
            self._candidate_count = 0
            return raw_regime

        # First evaluation — accept immediately
        if not self._current_regime:
            self._current_regime = raw_regime.regime
            self._candidate_regime = ""
            self._candidate_count = 0
            return raw_regime

        # Same as current stable regime — confirm immediately
        if raw_regime.regime == self._current_regime:
            self._candidate_regime = ""
            self._candidate_count = 0
            return raw_regime

        # Different from current — track persistence
        if raw_regime.regime == self._candidate_regime:
            self._candidate_count += 1
        else:
            self._candidate_regime = raw_regime.regime
            self._candidate_count = 1

        if self._candidate_count >= self._min_persistence:
            logger.info(
                "Regime hysteresis: %s → %s (persisted %d evaluations)",
                self._current_regime, self._candidate_regime, self._candidate_count,
            )
            self._current_regime = self._candidate_regime
            self._candidate_regime = ""
            self._candidate_count = 0
            return raw_regime

        # Not yet stable — return current stable regime
        return RegimeState(
            regime=self._current_regime,
            allowed_long=raw_regime.allowed_long,
            allowed_short=raw_regime.allowed_short,
            risk_scale=raw_regime.risk_scale,
        )


def classify_regime(
    data: list[OHLC],
    amt_result: AMTResult,
    market_state: str,
    session_name: str,
) -> RegimeState:
    """Classify market regime based on volatility and structure.

    Args:
        data: OHLC price bars
        amt_result: AMT pipeline result
        market_state: Current market state string
        session_name: Trading session name

    Returns:
        RegimeState with classification results
    """
    # Dead market - no activity
    if amt_result.signal == "SKIP":
        return RegimeState("DEAD", allowed_long=False, allowed_short=False, risk_scale=0.0)

    # Volatile market - high ATR expansion
    atr = _calculate_atr(data)
    if atr > 0:
        recent_high = max(h.high for h in data[-10:]) if len(data) >= 10 else 0
        recent_low = min(h.low for h in data[-10:]) if len(data) >= 10 else 0
        range_pct = (recent_high - recent_low) / ((recent_high + recent_low) / 2) if (recent_high + recent_low) > 0 else 0
        if range_pct > 0.05:  # 5% range = volatile
            return RegimeState("VOLATILE", allowed_long=True, allowed_short=True, risk_scale=0.5)

    # Trending vs Balanced based on AMT signal
    if market_state == "IMBALANCED":
        return RegimeState("TRENDING", allowed_long=True, allowed_short=True, risk_scale=1.0)
    
    return RegimeState("BALANCED", allowed_long=True, allowed_short=True, risk_scale=1.0)


def _calculate_atr(data: list[OHLC], period: int = 14) -> float:
    """Calculate Average True Range."""
    if len(data) < period:
        return 0.0
    
    tr_list = []
    for i in range(1, len(data)):
        high = data[i].high
        low = data[i].low
        prev_close = data[i-1].close
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)
    
    if len(tr_list) < period:
        return 0.0
    
    return sum(tr_list[-period:]) / period