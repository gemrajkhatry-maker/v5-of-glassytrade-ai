"""Regime classification for agent pipeline.

Extracted from agent_pipeline.py for separation of concerns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.domain.trading.model.value_objects import OHLC
from app.domain.trading.model.enums import MarketStateCodec
from app.domain.trading.model.value_objects import AMTResult

logger = logging.getLogger(__name__)


def _to_float(value: object) -> float:
    """Cast numeric-like values to float with a safe default."""

    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


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
    tick: OHLC | str | None,
    session_name: str = "",
) -> RegimeState:
    """Classify regime using the rule set currently used by the pipeline."""
    if len(data) < 20:
        logger.info("Regime: DEAD — only %d candles (need 20)", len(data))
        return RegimeState("DEAD", False, False, 0.0)

    # Support legacy callers that pass market state directly.
    if isinstance(tick, str):
        market_state = tick
        tick = data[-1] if data else None
    else:
        market_state = getattr(amt_result, "market_state", "")

    if not tick:
        logger.info("Regime: DEAD — no tick available")
        return RegimeState("DEAD", False, False, 0.0)

    alpha = 2.0 / 21
    ema_vol = _to_float(data[-20].volume)
    for d in data[-19:]:
        ema_vol = alpha * _to_float(d.volume) + (1.0 - alpha) * ema_vol

    latest_bar = data[-1]
    latest_vol = _to_float(
        latest_bar.volume
        if latest_bar.time != tick.time
        else (data[-2].volume if len(data) >= 2 else _to_float(tick.volume))
    )
    vol_ratio = latest_vol / ema_vol if ema_vol > 0 else 0

    if tick.close <= 0 or vol_ratio < 0.01:
        logger.info(
            "Regime: DEAD — ltp=%.2f, vol_ratio=%.3f (latest_vol=%.0f, ema=%.0f)",
            tick.close,
            vol_ratio,
            latest_vol,
            ema_vol,
        )
        return RegimeState("DEAD", False, False, 0.0)

    atr_pct_scale = 1.0
    atr5 = sum(_to_float(d.high) - _to_float(d.low) for d in data[-5:]) / 5
    atr20 = sum(_to_float(d.high) - _to_float(d.low) for d in data[-20:]) / 20
    atr_ratio = atr5 / atr20 if atr20 > 0 else 1.0

    if atr_ratio > 3.0:
        return RegimeState("VOLATILE", True, True, 0.5 * atr_pct_scale)

    if MarketStateCodec.is_imbalanced(market_state):
        return RegimeState("TRENDING", True, True, 1.0 * atr_pct_scale)

    return RegimeState("BALANCED", True, True, 1.0 * atr_pct_scale)