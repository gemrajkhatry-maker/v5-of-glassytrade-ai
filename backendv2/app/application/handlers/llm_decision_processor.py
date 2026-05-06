"""LLM decision processor helpers."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class LLMDecisionProcessor:
    """Process LLM decisions with safety nets and persistence."""

    def __init__(self, allow_short: bool = False, journal=None):
        self._allow_short = allow_short
        self._journal = journal

    def apply_safety_nets(
        self,
        direction: str,
        confidence: float,
        rationale: str,
        tick,
        amt_result,
    ) -> tuple:
        if direction == "SHORT" and not self._allow_short:
            logger.info("BUY-ONLY mode: SHORT blocked → FLAT")
            direction = "FLAT"
            rationale = "System in BUY-ONLY mode"

        if (
            direction == "LONG"
            and float(getattr(amt_result, "vwap_upper_2", 0)) > 0
            and float(tick.close) >= float(amt_result.vwap_upper_2) * 1.01
        ):
            logger.info(
                "VWAP EXTREME: LONG at >+2σ — institutional anomaly (price=%.2f, band=%.2f)",
                float(tick.close),
                float(amt_result.vwap_upper_2),
            )
            confidence = 0.3
            rationale += " [VWAP extreme: >+2σ]"
        return direction, confidence, rationale

    def check_direction_mismatch(
        self,
        agent_decision,
        direction: str,
        symbol: str,
        session,
        worker_queue,
    ) -> bool:
        if agent_decision and getattr(agent_decision, "direction", None) in ("LONG", "SHORT"):
            if getattr(agent_decision, "direction") != direction:
                if self._journal is not None:
                    try:
                        self._journal.log_rejection(
                            symbol=symbol,
                            reason="AGENT_DIRECTION_MISMATCH",
                            amt=getattr(session, "last_amt", None),
                            llm_direction=direction,
                        )
                    except Exception:
                        pass
                try:
                    worker_queue.put_nowait(None)
                except Exception:
                    pass
                return True
        return False

    def mark_ai_done(self, session) -> None:
        try:
            with session._lock:
                session._ai_running = False
                session._llm_status = "AVAILABLE"
        except Exception:
            pass

    def persist_decision(
        self,
        storage,
        symbol: str,
        direction: str,
        confidence: str,
        rationale: str,
        input_prompt: str,
        raw_output: str,
        market_state: str,
        aggression: str,
        tick,
        amt_result,
        profile_shape: str,
        setup_type,
        strategy_hint: str,
    ) -> None:
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
                    "price": float(tick.close),
                    "vah": float(getattr(amt_result, "value_area_high", 0.0)),
                    "val": float(getattr(amt_result, "value_area_low", 0.0)),
                    "poc": float(getattr(amt_result, "poc", 0.0)),
                    "delta": float(getattr(tick, "delta", 0.0)),
                    "volume": float(getattr(tick, "volume", 0.0)),
                    "profile_shape": profile_shape,
                    "setup_type": str(getattr(setup_type, "value", setup_type)),
                    "strategy_hint": strategy_hint,
                }
            )
        except Exception:
            logger.warning("LLM decision persistence to storage failed", exc_info=True)


def update_llm_memory(session, direction: str, rationale: str) -> None:
    summary = f"{direction}: {rationale[:100]}..."
    if not hasattr(session, "_llm_memory"):
        session._llm_memory = []
    session._llm_memory.append(summary)
    if len(session._llm_memory) > 5:
        session._llm_memory = session._llm_memory[-5:]
