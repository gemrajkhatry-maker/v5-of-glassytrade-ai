"""Signal processing coordinator - extracted from trading_session.py.

Handles entry decision resolution and signal execution.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def resolve_entry_decision(
    session,
    symbol: str,
    tick,
    amt_result,
    market_state_str: str,
    session_info: dict,
    setup_type: Any,
    strategy_hint: str,
    profile_shape_str: str,
    gate_context: str,
    is_second_drive: bool,
    allow_short: bool,
    llm_handler,
    probability_engine,
    risk_coordinator,
) -> dict | None:
    """Resolve entry decision using LLM or fallback agents."""
    # Build session context for LLM
    session_context = {
        "symbol": symbol,
        "session_name": session_info.get("session_name", "UNKNOWN"),
        "force_exit": session_info.get("force_exit", False),
    }
    
    # Check if we should run entry analysis
    if not llm_handler.should_run(session, tick):
        return None
    
    # Get agent decision
    agent_decision = getattr(session, "_agent_decision", None)
    
    # Determine direction
    direction = "FLAT"
    confidence = "Low"
    rationale = ""
    
    # LLM decision path
    if agent_decision and agent_decision.direction != "FLAT":
        direction = agent_decision.direction
        confidence = "High"
        rationale = agent_decision.rationale or "Agent decision"
    
    if direction == "SHORT" and not allow_short:
        direction = "FLAT"
        rationale = "System in BUY-ONLY mode"
    
    return {
        "direction": direction,
        "confidence": confidence,
        "rationale": rationale,
        "agent_direction": agent_decision.direction if agent_decision else "FLAT",
    }


def execute_signal(
    symbol: str,
    signal,
    session,
    entry_coordinator,
    exit_coordinator,
    lifecycle_handler,
    event_logger,
) -> None:
    """Execute a trading signal."""
    if not signal or signal.direction == "FLAT":
        return
    
    # Check risk coordinator
    if not entry_coordinator.can_enter(symbol):
        return
    
    # Enter position
    entry_coordinator.enter_position(symbol, signal)
    
    # Log event
    event_logger.log_signal(
        symbol=symbol,
        direction=signal.direction,
        setup=signal.setup_type,
        confidence=signal.confidence,
        price=signal.entry_price,
        size=signal.qty,
        sl=signal.stop_loss,
        tp=signal.take_profit,
    )