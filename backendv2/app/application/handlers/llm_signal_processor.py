"""LLM signal processor helpers."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class LLMSignalProcessor:
    """Process and validate LLM-generated signals."""

    def __init__(self, allow_short: bool = False):
        self._allow_short = allow_short

    def process_build_signal(
        self,
        symbol: str,
        session,
        tick,
        direction: str,
        setup_type: str,
        confidence: float,
        sl_price: float,
        tp_price: float,
        qty: int,
        entry_price: float,
        rationale: str,
        agent: str = "llm",
    ) -> dict:
        signal = {
            "symbol": symbol,
            "direction": direction,
            "setup_type": setup_type,
            "confidence": confidence,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "qty": qty,
            "entry_price": entry_price,
            "rationale": rationale,
            "agent": agent,
        }
        if direction == "SHORT" and not self._allow_short:
            logger.warning("SHORT not allowed for %s, converting to FLAT", symbol)
            signal["direction"] = "FLAT"
        return signal

    def check_direction_mismatch(
        self,
        agent_decision,
        direction: str,
        symbol: str,
        session_info: dict,
    ) -> str | None:
        regime = session_info.get("market_state", "")
        if regime == "BALANCED" and direction == "LONG":
            return f"LLM LONG in BALANCED regime for {symbol}"
        if regime == "IMBALANCED" and direction == "SHORT":
            return f"LLM SHORT in IMBALANCED regime for {symbol}"
        return None

    def apply_safety_nets(
        self,
        direction: str,
        confidence: float,
        rationale: str,
        symbol: str,
    ) -> tuple[str, float, str]:
        confidence = max(0.0, min(1.0, confidence))
        if confidence < 0.55:
            logger.info("Low confidence %.2f for %s, rejecting", confidence, symbol)
            return "FLAT", 0.0, "Confidence below threshold"
        return direction, confidence, rationale

    def mark_ai_done(self, session, worker_queue) -> None:
        if hasattr(session, "mark_done"):
            session.mark_done()
        if worker_queue:
            try:
                worker_queue.put(None)
            except Exception:
                pass
