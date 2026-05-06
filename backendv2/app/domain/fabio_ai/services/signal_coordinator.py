"""Decision coordinator for entry gating."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.constants import AGENT_DECISION_THRESHOLD, CONFIDENCE_HIGH_THRESHOLD
from app.domain.shared.port import ILLMInference


@dataclass
class EntryEvaluation:
    should_enter: bool
    direction: str
    probability: float
    timing: str
    reason: str
    conviction: str
    setup_type: str


class SignalCoordinator:
    """Evaluate whether to enter immediately after upstream filters pass."""

    HIGH_CONVICTION_PROB = 0.65
    MEDIUM_CONVICTION_PROB = AGENT_DECISION_THRESHOLD
    MIN_PROB_FOR_ENTRY = AGENT_DECISION_THRESHOLD

    def evaluate_entry(
        self,
        agent_decision: Any,
        amt_result: Any,
        tick: Any,
        session_info: Any,
        confirmation_strong: bool,
        is_new_candle: bool,
        is_overseer_running: bool,
        has_position: bool,
        allow_short: bool = False,
    ) -> EntryEvaluation:
        if has_position:
            return EntryEvaluation(False, "FLAT", 0.0, "SKIP", "Position already open", "NONE", "NONE")

        if is_overseer_running:
            return EntryEvaluation(False, "FLAT", 0.0, "WAIT", "Overseer processing", "NONE", "NONE")

        if agent_decision is None:
            return EntryEvaluation(False, "FLAT", 0.0, "SKIP", "No agent decision", "NONE", "NONE")

        agent_dir = str(getattr(agent_decision, "direction", "FLAT")).upper()
        agent_prob = float(getattr(agent_decision, "probability", 0.0))

        if agent_dir == "FLAT":
            return EntryEvaluation(False, "FLAT", agent_prob, "SKIP", "Agent says no edge", "NONE", "NONE")

        if agent_prob >= CONFIDENCE_HIGH_THRESHOLD:
            conviction = "HIGH"
        elif agent_prob >= AGENT_DECISION_THRESHOLD:
            conviction = "MEDIUM"
        else:
            return EntryEvaluation(False, "FLAT", agent_prob, "SKIP", "Low probability", "NONE", "NONE")

        if not getattr(session_info, "allow_entry", True):
            return EntryEvaluation(False, "FLAT", agent_prob, "SKIP", "Session does not allow entries", "NONE", "NONE")

        if agent_dir == "SHORT" and not allow_short:
            return EntryEvaluation(False, "FLAT", agent_prob, "SKIP", "SHORT not allowed", "NONE", "NONE")

        setup_type = "MEAN_REVERSION" if str(amt_result.market_state) == "BALANCED" else "TREND_CONTINUATION"
        if not confirmation_strong:
            return EntryEvaluation(False, "FLAT", agent_prob, "WAIT", "Confirmation weak", "LOW", "NONE")

        return EntryEvaluation(True, agent_dir, agent_prob, "ENTER_NOW", "Ready to enter", conviction, setup_type)
