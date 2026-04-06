"""Signal Coordinator — Entry signal generation and validation.

Extracted from trading_session.py to separate entry decision logic
from session lifecycle management.

Single Responsibility: Answer the question 'Should we enter now?'
Does NOT manage positions, storage, or LLM orchestration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from app.domain.constants import (
    AGENT_DECISION_THRESHOLD,
    CONFIDENCE_HIGH_THRESHOLD,
    CONFIDENCE_LOW_THRESHOLD,
)

from app.domain.trading.models.enums import MarketStateCodec, SetupType

logger = logging.getLogger(__name__)


@dataclass
class EntryEvaluation:
    """Result of entry signal evaluation."""

    should_enter: bool
    direction: str  # "LONG", "SHORT", or "FLAT"
    probability: float
    timing: str  # "ENTER_NOW", "WAIT", "SKIP"
    reason: str
    conviction: str  # "HIGH", "MEDIUM", "LOW", "NONE"
    setup_type: str  # "MEAN_REVERSION", "TREND_CONTINUATION", "NONE"


class SignalCoordinator:
    """Evaluates market conditions and produces entry signals.

    Single responsibility: Answer the question 'Should we enter now?'
    Does NOT manage positions, storage, or LLM orchestration.
    """

    # Conviction thresholds (from Fabio's methodology)
    HIGH_CONVICTION_PROB = 0.65  # Strong edge, execute regardless
    MEDIUM_CONVICTION_PROB = AGENT_DECISION_THRESHOLD  # Needs structural confirmation
    MIN_PROB_FOR_ENTRY = AGENT_DECISION_THRESHOLD      # Minimum to even consider

    def evaluate_entry(
        self,
        agent_decision: Any,  # AgentDecision from probability engine
        amt_result: Any,  # AMTResult from amt_analyzer
        tick: Any,  # Current OHLC tick
        session_info: Any,  # SessionInfo from session_context
        confirmation_strong: bool,  # From three_align_check
        is_new_candle: bool,
        is_overseer_running: bool,
        has_position: bool,
        allow_short: bool = False,  # Whether SHORT direction is allowed
    ) -> EntryEvaluation:
        """Evaluate whether to enter a trade NOW.

        This is the SINGLE decision point for all entry logic.
        All checks happen here — no scattered logic.
        """

        # 1. Basic availability checks
        if has_position:
            return EntryEvaluation(
                should_enter=False,
                direction="FLAT",
                probability=0,
                timing="SKIP",
                reason="Position already open",
                conviction="NONE",
                setup_type="NONE",
            )

        if is_overseer_running:
            return EntryEvaluation(
                should_enter=False,
                direction="FLAT",
                probability=0,
                timing="WAIT",
                reason="Overseer processing",
                conviction="NONE",
                setup_type="NONE",
            )

        # 2. Agent decision check
        if agent_decision is None:
            return EntryEvaluation(
                should_enter=False,
                direction="FLAT",
                probability=0,
                timing="SKIP",
                reason="No agent decision",
                conviction="NONE",
                setup_type="NONE",
            )

        # Extract from AgentDecision (frozen dataclass)
        _type = type(agent_decision).__name__
        _id = id(agent_decision)

        # Direct attribute access for frozen dataclass
        agent_dir = agent_decision.direction
        agent_prob = float(agent_decision.probability)
        agent_timing = agent_decision.timing

        # Only log when we have a real decision (not FLAT)
        if agent_dir != "FLAT":
            logger.info(
                "COORDINATOR: dir=%s P=%.3f timing=%s id=%s",
                agent_dir,
                agent_prob,
                agent_timing,
                _id,
            )

        if agent_dir == "FLAT":
            return EntryEvaluation(
                should_enter=False,
                direction="FLAT",
                probability=agent_prob,
                timing="SKIP",
                reason="Agent says no edge",
                conviction="NONE",
                setup_type="NONE",
            )

        # NOTE: timing check removed — if we have direction + probability >= 0.55,
        # the entry is valid. The run_entry check already verified this.

        # 3. Conviction assessment based on probability
        if agent_prob >= CONFIDENCE_HIGH_THRESHOLD:
            conviction = "HIGH"
        elif agent_prob >= AGENT_DECISION_THRESHOLD:
            conviction = "MEDIUM"
        elif agent_prob >= CONFIDENCE_LOW_THRESHOLD:
            conviction = "LOW"
        else:
            return EntryEvaluation(
                should_enter=False,
                direction="FLAT",
                probability=agent_prob,
                timing="SKIP",
                reason=f"Probability too low (P={agent_prob:.3f} < {AGENT_DECISION_THRESHOLD})",
                conviction="NONE",
                setup_type="NONE",
            )

        # 4. Session permission check
        if not getattr(session_info, "allow_entry", False):
            return EntryEvaluation(
                should_enter=False,
                direction="FLAT",
                probability=agent_prob,
                timing="SKIP",
                reason="Session does not allow entry",
                conviction="NONE",
                setup_type="NONE",
            )

        # 4. Direction validation
        if agent_dir == "SHORT":
            # Check if SHORT is allowed
            if not allow_short:
                return EntryEvaluation(
                    should_enter=False,
                    direction="FLAT",
                    probability=agent_prob,
                    timing="SKIP",
                    reason="SHORT not allowed",
                    conviction="NONE",
                    setup_type="NONE",
                )

        # 5. Conviction assessment — aligned with run_entry threshold (0.55)
        if agent_prob >= CONFIDENCE_HIGH_THRESHOLD:
            conviction = "HIGH"
            should_enter = True
        elif agent_prob >= AGENT_DECISION_THRESHOLD:
            conviction = "MEDIUM"
            should_enter = True  # run_entry allows P >= 0.55
        elif agent_prob >= CONFIDENCE_LOW_THRESHOLD:
            conviction = "LOW"
            should_enter = True  # Allow with warning
        else:
            conviction = "NONE"
            should_enter = False

        if not should_enter:
            return EntryEvaluation(
                should_enter=False,
                direction="FLAT",
                probability=agent_prob,
                timing="SKIP",
                reason=f"Insufficient conviction (P={agent_prob:.3f})",
                conviction=conviction,
                setup_type="NONE",
            )

        # 6. Determine setup type
        if amt_result.market_state == "BALANCED":
            setup_type = "MEAN_REVERSION"
        elif amt_result.market_state == "IMBALANCED":
            setup_type = "TREND_CONTINUATION"
        else:
            setup_type = "NONE"

        return EntryEvaluation(
            should_enter=True,
            direction=agent_dir,
            probability=agent_prob,
            timing="ENTER_NOW",
            reason=f"{conviction} conviction: P={agent_prob:.3f}, edge={agent_prob - 0.5:.3f}",
            conviction=conviction,
            setup_type=setup_type,
        )
