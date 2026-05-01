"""LLM signal processor - extracted from llm_entry_handler.py.

Handles signal building, validation, and processing.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class LLMSignalProcessor:
    """Process and validate LLM-generated signals."""

    def __init__(self, allow_short: bool = False):
        self._allow_short = allow_short

    def process_build_signal(
        self,
        symbol: str,
        session: Any,
        tick: Any,
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
        """Process and build signal dictionary."""
        signal = {
            'symbol': symbol,
            'direction': direction,
            'setup_type': setup_type,
            'confidence': confidence,
            'sl_price': sl_price,
            'tp_price': tp_price,
            'qty': qty,
            'entry_price': entry_price,
            'rationale': rationale,
            'agent': agent,
        }
        
        # Validate direction if short not allowed
        if direction == 'SHORT' and not self._allow_short:
            logger.warning(f"SHORT not allowed for {symbol}, converting to FLAT")
            signal['direction'] = 'FLAT'
        
        return signal

    def check_direction_mismatch(
        self,
        agent_decision: dict,
        direction: str,
        symbol: str,
        session_info: dict,
    ) -> str | None:
        """Check for direction mismatches and return warning if found."""
        regime = session_info.get('market_state', '')
        
        # LLM direction should align with regime
        if regime == 'BALANCED' and direction == 'LONG':
            return f"LLM LONG in BALANCED regime for {symbol}"
        elif regime == 'IMBALANCED' and direction == 'SHORT':
            return f"LLM SHORT in IMBALANCED regime for {symbol}"
        
        return None

    def apply_safety_nets(
        self,
        direction: str,
        confidence: float,
        rationale: str,
        symbol: str,
    ) -> tuple[str, float, str]:
        """Apply safety net checks to signal."""
        # Confidence bounds
        confidence = max(0.0, min(1.0, confidence))
        
        # Minimum confidence threshold
        if confidence < 0.55:
            logger.info(f"Low confidence {confidence:.2f} for {symbol}, rejecting")
            return 'FLAT', 0.0, "Confidence below threshold"
        
        return direction, confidence, rationale

    def mark_ai_done(self, session: Any, worker_queue: Any) -> None:
        """Mark AI processing as done for the session."""
        if hasattr(session, 'mark_done'):
            session.mark_done()
        if worker_queue:
            try:
                worker_queue.put(None)
            except Exception:
                pass