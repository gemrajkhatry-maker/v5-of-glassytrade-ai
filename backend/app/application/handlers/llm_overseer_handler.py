"""LLM Overseer Handler — conviction-based active position management.

While LLMEntryHandler fires once for entry and goes silent, this handler
continuously monitors open positions every ~10 seconds, asking the LLM
to evaluate whether to HOLD, TIGHTEN_SL, PARTIAL_EXIT, FULL_EXIT, or ADD.

Uses the same MLX predict() path as entry decisions with regex parsing
and an OverseerAction Pydantic model for internal type safety.

Design rationale (Fabio Valentini methodology):
- "Every tick down costs $500" — active monitoring, not set-and-forget
- Moves SL to breakeven quickly when profitable
- Pyramids into winners when absorption confirms direction
- Takes partials at targets, walks away after capturing the move
- Reads volume bubbles and CVD continuously while in trade
"""

from __future__ import annotations

import concurrent.futures
import logging
import time
from typing import TYPE_CHECKING

from app.domain.fabio_ai.services.trade_manager import TradeManager, ExitReason
from app.domain.fabio_ai.services.prompt_builder import (
    OverseerAction,
    build_overseer_prompt,
    parse_overseer_response,
)

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, AMTResult
    from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService
    from app.domain.ports.event_bus import EventBusPort
    from app.domain.ports.storage import StoragePort

logger = logging.getLogger(__name__)

# Minimum seconds between overseer calls
OVERSEER_COOLDOWN = 10.0


class LLMOverseerHandler:
    """Active position overseer — queries LLM every ~10s while a position is open."""

    OVERSEER_INSTRUCTION = (
        "You are an active trade manager following Fabio Valentini's orderflow methodology. "
        "You are managing an open position. Analyze the current market data and position state. "
        "Respond with exactly one action:\n"
        "Action: Hold — conviction unchanged, continue holding\n"
        "Action: Tighten SL {price} — move stop loss closer to protect profits\n"
        "Action: Partial Exit — take partial profits (50%)\n"
        "Action: Full Exit — close entire position immediately\n"
        "Action: Add — add to position (only if strongly convicted)\n"
        "Then a brief Reason: line explaining why."
    )

    def __init__(
        self,
        gen_ai_service: GenerativeAIService,
        event_bus: EventBusPort,
        trade_manager: TradeManager,
        storage: StoragePort | None = None,
    ) -> None:
        self._gen_ai_service = gen_ai_service
        self._event_bus = event_bus
        self._trade_manager = trade_manager
        self._storage = storage
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def should_run(
        self,
        last_overseer_time: float,
        overseer_running: bool,
        ai_running: bool,
        has_position: bool,
    ) -> bool:
        """Check if overseer should fire."""
        if not has_position:
            return False
        if overseer_running or ai_running:
            return False
        if not self._gen_ai_service.is_ready():
            return False
        if (time.time() - last_overseer_time) < OVERSEER_COOLDOWN:
            return False
        return True

    def run_overseer(
        self,
        session,
        symbol: str,
        tick: OHLC,
        amt_result: AMTResult,
    ) -> None:
        """Run overseer analysis in background thread."""
        session._last_overseer_time = time.time()
        session._overseer_running = True

        # Gather position state from TradeManager
        managed_positions = list(self._trade_manager._positions.values())
        if not managed_positions:
            session._overseer_running = False
            return

        mp = managed_positions[0]  # We manage one position at a time
        pos_state = self._trade_manager.get_position_state(mp.position_id, tick.close)
        if pos_state is None:
            session._overseer_running = False
            return

        # Build the overseer prompt (pure quant)
        prompt = build_overseer_prompt(pos_state, tick, amt_result)

        def _worker():
            try:
                logger.info(
                    "LLM overseer starting for %s (%s from %.2f, unrealized=%.2f%%)",
                    symbol, pos_state["side"], pos_state["entry_price"],
                    pos_state["unrealized_pnl_pct"] * 100,
                )

                # Use the same predict() path as entry decisions
                adapter = self._gen_ai_service.llm_adapter
                raw = adapter.predict(self.OVERSEER_INSTRUCTION, prompt)
                decision = parse_overseer_response(raw, pos_state)

                logger.info("LLM overseer: %s (reason: %s)", decision.action, decision.reason[:80])

                # Execute the decision
                self._execute_decision(decision, session, symbol, tick.close, pos_state)

                # Update session state for UI
                with session._lock:
                    overseer_info = session.last_ai_analysis or {}
                    overseer_info["overseer_action"] = decision.action
                    overseer_info["overseer_reason"] = decision.reason
                    session.last_ai_analysis = overseer_info

                # Persist
                if self._storage:
                    try:
                        self._storage.save_llm_decision({
                            "symbol": symbol,
                            "direction": decision.action,
                            "confidence": "Overseer",
                            "rationale": decision.reason,
                            "input_prompt": prompt[:500],
                            "raw_output": raw[:500],
                            "market_state": pos_state.get("market_state", ""),
                            "price": tick.close,
                        })
                    except Exception:
                        logger.debug("Failed to persist overseer decision", exc_info=True)

            except Exception as e:
                logger.error("LLM overseer failed: %s", e)
            finally:
                session._overseer_running = False

        self._executor.submit(_worker)

    # Prompt building and response parsing extracted to prompt_builder.py
    # Delegated via: build_overseer_prompt(), parse_overseer_response()

    # ------------------------------------------------------------------
    # Decision execution
    # ------------------------------------------------------------------

    def _execute_decision(
        self,
        decision: OverseerAction,
        session,
        symbol: str,
        current_price: float,
        pos_state: dict,
    ) -> None:
        """Execute the overseer's decision."""
        position_id = pos_state.get("position_id", "")

        if decision.action == "HOLD":
            return

        elif decision.action == "TIGHTEN_SL":
            if decision.new_sl_price and decision.new_sl_price > 0:
                adjusted = self._trade_manager.adjust_stop_loss(position_id, decision.new_sl_price)
                if adjusted:
                    logger.info("Overseer: tightened SL to %.2f for %s", decision.new_sl_price, position_id)
                else:
                    logger.info("Overseer: SL adjustment rejected (would widen risk)")

        elif decision.action == "PARTIAL_EXIT":
            if not pos_state.get("partial_taken"):
                with session._lock:
                    portfolio = session.portfolio
                    open_positions = [p for p in portfolio.positions if p.status == "OPEN" and p.id == position_id]
                    if open_positions:
                        realized = portfolio.partial_close_position(
                            open_positions[0].id, 0.50, current_price, ExitReason.OVERSEER_PARTIAL,
                        )
                        logger.info("Overseer: partial exit for %s, realized=%.2f", position_id, realized)
                        self._trade_manager.adjust_stop_loss(position_id, pos_state["entry_price"])
            else:
                logger.info("Overseer: partial already taken, ignoring PARTIAL_EXIT")

        elif decision.action == "FULL_EXIT":
            with session._lock:
                portfolio = session.portfolio
                open_positions = [p for p in portfolio.positions if p.status == "OPEN" and p.id == position_id]
                if open_positions:
                    portfolio.close_position(position_id, current_price, ExitReason.OVERSEER_EXIT)
                    self._trade_manager.unregister_position(position_id)
                    logger.info("Overseer: full exit for %s at %.2f", position_id, current_price)

        elif decision.action == "ADD":
            if pos_state["unrealized_pnl_pct"] > 0 and not pos_state.get("partial_taken"):
                logger.info("Overseer: ADD signal for %s — publishing pyramid signal", position_id)
            else:
                logger.info("Overseer: ADD rejected — not profitable or partial already taken")
