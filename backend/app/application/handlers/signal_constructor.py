"""Signal Constructor — Builds trade signals from LLM decisions.

Responsibilities:
- Signal construction from LLM output
- Signal validation
- Signal metadata enrichment
- Trade thesis building
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.domain.trading.models.enums import SignalType, Source, SetupType
from app.domain.trading.models.entities import Signal

# Import error handling utilities
from shared.error_handling import (
    handle_errors,
    safe_execute,
    ErrorContext,
    SignalError,
)

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, AMTResult

logger = logging.getLogger(__name__)


class SignalConstructor:
    """Constructs trade signals from LLM decisions.

    This module encapsulates all signal-building logic, providing a single
    source of truth for signal construction across the codebase.
    """

    def construct_signal(
        self,
        direction: str,
        tick: OHLC,
        amt_result: AMTResult,
        ai_result: dict,
        setup_type: SetupType = SetupType.TREND_MODEL,
        data: list[OHLC] | None = None,
        risk_sl_pct: float | None = None,
        session_context: str = "",
        confidence: str = "Medium",
        session_risk_pct: float | None = None,
        inside_extreme: bool = False,
        tick_size: float = 0.05,
    ) -> Signal | None:
        """Construct a trade signal from LLM decision.

        Args:
            direction: Trade direction (LONG/SHORT)
            tick: Current tick data
            amt_result: AMT analysis result
            ai_result: LLM analysis result
            setup_type: Setup type (TREND_MODEL/MEAN_REVERSION)
            data: Historical OHLC data
            risk_sl_pct: Risk-based stop loss percentage
            session_context: Session context string
            confidence: Confidence level (High/Medium/Low)
            session_risk_pct: Dynamic session risk percentage

        Returns:
            Signal object or None if construction fails
        """
        from app.domain.fabio_ai.services.entry_gate import build_entry_signal
        from app.domain.fabio_ai.services.trade_thesis import build_trade_thesis

        try:
            # Build signal using the main entry gate function
            signal = build_entry_signal(
                direction=direction,
                tick=tick,
                amt_result=amt_result,
                ai_result=ai_result,
                setup_type=setup_type,
                data=data,
                risk_sl_pct=risk_sl_pct,
                session_context=session_context,
                confidence=confidence,
                session_risk_pct=session_risk_pct,
                inside_extreme=inside_extreme,
                tick_size=tick_size,
            )

            if signal is None:
                logger.warning("Signal construction returned None")
                return None

            # Enrich signal with additional metadata
            enriched_signal = self._enrich_signal_metadata(
                signal=signal,
                direction=direction,
                tick=tick,
                amt_result=amt_result,
                ai_result=ai_result,
                setup_type=setup_type,
                confidence=confidence,
                data=data,
            )

            return enriched_signal

        except Exception as e:
            logger.error("Signal construction failed: %s", e, exc_info=True)
            return None

    def _enrich_signal_metadata(
        self,
        signal: Signal,
        direction: str,
        tick: OHLC,
        amt_result: AMTResult,
        ai_result: dict,
        setup_type: SetupType,
        confidence: str,
        data: list[OHLC] | None = None,
    ) -> Signal:
        """Enrich signal with additional metadata.

        Args:
            signal: Base signal to enrich
            direction: Trade direction (LONG/SHORT)
            tick: Current tick data
            amt_result: AMT analysis result
            ai_result: LLM analysis result
            setup_type: Setup type
            confidence: Confidence level
            data: Historical OHLC for footprint analysis

        Returns:
            Enriched signal
        """
        # Build trade thesis
        from app.domain.fabio_ai.services.trade_thesis import build_trade_thesis
        from app.domain.fabio_ai.services.entry_gates.grading import compute_grade_score

        thesis = build_trade_thesis(
            tick=tick,
            amt_result=amt_result,
            setup_type=setup_type,
            session_context=ai_result.get("session_context", ""),
            invalidation_level=signal.stop_loss,
        )

        # Calculate conviction multiplier
        conviction_multiplier = self._calculate_conviction_multiplier(
            amt_result=amt_result,
            confidence=confidence,
        )

        # Compute confluence grade score (A/B/C setup grade)
        # Score breakdown: +1 per confirming factor (CVD slope, no divergence,
        # session/setup alignment, profile shape, VWAP bias, imbalance alignment)
        grade_score = compute_grade_score(
            direction=direction,
            tick=tick,
            amt_result=amt_result,
            setup_type=setup_type,
            profile_shape=amt_result.profile_shape,
        )

        # Enrich metadata
        if signal.metadata is None:
            signal.metadata = {}

        signal.metadata.update(
            {
                "trade_thesis": thesis.to_metadata(),
                "conviction_multiplier": conviction_multiplier,
                "setup_type": setup_type.value,
                "confidence": confidence,
                "market_state": amt_result.market_state,
                "aggression": amt_result.aggression,
                "cvd_slope": amt_result.cvd_slope,
                "profile_shape": amt_result.profile_shape,
                "grade_score": grade_score,
            }
        )

        return signal

    def _calculate_conviction_multiplier(
        self,
        amt_result: AMTResult,
        confidence: str,
    ) -> float:
        """Calculate conviction multiplier based on market conditions.

        Args:
            amt_result: AMT analysis result
            confidence: Confidence level

        Returns:
            Conviction multiplier (0.5 to 1.25)
        """
        # Base multiplier from confidence
        base_multiplier = {
            "High": 1.0,
            "Medium": 0.75,
            "Low": 0.5,
        }.get(confidence, 0.5)

        # LVN play boost
        lvn_multiplier = 1.0
        if amt_result.lvn_play:
            lvn_multiplier = 1.25

        return base_multiplier * lvn_multiplier

    def validate_signal(self, signal: Signal) -> tuple[bool, str]:
        """Validate a constructed signal.

        Args:
            signal: Signal to validate

        Returns:
            Tuple of (valid: bool, reason: str)
        """
        if signal is None:
            return False, "Signal is None"

        # Check required fields
        if not signal.type:
            return False, "Signal type is missing"

        if not signal.price or signal.price <= 0:
            return False, "Invalid signal price"

        if not signal.stop_loss or signal.stop_loss <= 0:
            return False, "Invalid stop loss"

        if not signal.take_profit or signal.take_profit <= 0:
            return False, "Invalid take profit"

        # Check R:R ratio
        risk = abs(signal.price - signal.stop_loss)
        reward = abs(signal.take_profit - signal.price)

        if risk <= 0:
            return False, "Invalid risk calculation"

        rr_ratio = reward / risk
        if rr_ratio < 1.0:
            return False, f"R:R ratio too low: {rr_ratio:.2f}"

        return True, "Signal is valid"

    def create_flat_signal(
        self,
        tick: OHLC,
        rationale: str = "No trade setup",
    ) -> dict:
        """Create a flat (no trade) signal for logging.

        Args:
            tick: Current tick data
            rationale: Rationale for staying flat

        Returns:
            Flat signal dictionary
        """
        return {
            "direction": "FLAT",
            "price": tick.close if tick else 0,
            "rationale": rationale,
            "confidence": "Medium",
            "timestamp": tick.time if tick else "",
        }
