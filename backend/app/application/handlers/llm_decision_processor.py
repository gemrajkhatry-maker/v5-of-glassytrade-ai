"""LLM decision processor - extracted from llm_entry_handler.py.

Handles LLM decision processing, safety nets, and signal building.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class LLMDecisionProcessor:
    """Process LLM decisions with safety nets and gate validation."""

    def __init__(self, allow_short: bool = False, journal=None):
        self._allow_short = allow_short
        self._journal = journal

    def apply_safety_nets(
        self,
        direction: str,
        confidence: float,
        rationale: str,
        tick: Any,
        amt_result: Any,
    ) -> tuple:
        """Apply post-LLM safety nets: buy-only mode, VWAP extreme check."""
        # Buy-only mode
        if direction == "SHORT" and not self._allow_short:
            logger.info("BUY-ONLY mode: SHORT blocked → FLAT")
            direction = "FLAT"
            rationale = "System in BUY-ONLY mode"

        # VWAP EXTREME check: LONG at >+2σ is suspicious
        if (
            direction == "LONG"
            and amt_result.vwap_upper_2 > 0
            and tick.close >= amt_result.vwap_upper_2 * 1.01
        ):
            logger.info(
                "VWAP EXTREME: LONG at >+2σ — institutional anomaly (price=%.2f, band=%.2f)",
                tick.close,
                amt_result.vwap_upper_2,
            )
            confidence = 0.3
            rationale += " [VWAP extreme: >+2σ]"

        return direction, confidence, rationale

    def check_direction_mismatch(
        self,
        agent_decision: Any,
        direction: str,
        symbol: str,
        session: Any,
        worker_queue: Any,
    ) -> bool:
        """Check if agent decision conflicts with LLM direction. Returns True if mismatch."""
        if (
            agent_decision
            and agent_decision.direction in ("LONG", "SHORT")
            and agent_decision.direction != direction
        ):
            if self._journal:
                self._journal.log_rejection(
                    symbol=symbol,
                    reason="AGENT_DIRECTION_MISMATCH",
                    amt=session.last_amt,
                    llm_direction=direction,
                )
            # Signal that AI is done
            try:
                worker_queue.put_nowait(None)
            except Exception:
                pass
            return True
        return False

    def mark_ai_done(self, session: Any) -> None:
        """Reset session AI flag."""
        try:
            with session._lock:
                session._ai_running = False
                session._llm_status = "AVAILABLE"
        except Exception:
            pass

    def persist_decision(
        self,
        storage: Any,
        symbol: str,
        direction: str,
        confidence: str,
        rationale: str,
        input_prompt: str,
        raw_output: str,
        market_state: str,
        aggression: str,
        tick: Any,
        amt_result: Any,
        profile_shape: str,
        setup_type: Any,
        strategy_hint: str,
    ) -> None:
        """Persist LLM decision to storage."""
        if not storage:
            return

        try:
            storage.save_llm_decision(
                {
                    "symbol": symbol,
                    "direction": direction,
                    "confidence": confidence,
                    "rationale": rationale,
                    "input_prompt": input_prompt,
                    "raw_output": raw_output,
                    "market_state": market_state,
                    "aggression": aggression,
                    "price": tick.close,
                    "vah": amt_result.value_area_high,
                    "val": amt_result.value_area_low,
                    "poc": amt_result.poc,
                    "delta": tick.delta,
                    "volume": tick.volume,
                    "profile_shape": profile_shape,
                    "setup_type": setup_type.value if hasattr(setup_type, 'value') else str(setup_type),
                    "strategy_hint": strategy_hint,
                }
            )
        except Exception:
            logger.warning("LLM decision persistence to storage failed", exc_info=True)


def update_llm_memory(session: Any, direction: str, rationale: str) -> None:
    """Update LLM memory buffer on session."""
    summary = f"{direction}: {rationale[:100]}..."
    if not hasattr(session, "_llm_memory"):
        session._llm_memory = []
    session._llm_memory.append(summary)
    if len(session._llm_memory) > 5:
        session._llm_memory = session._llm_memory[-5:]