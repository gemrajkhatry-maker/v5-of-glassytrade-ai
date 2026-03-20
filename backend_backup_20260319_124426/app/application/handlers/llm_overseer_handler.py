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
import queue
import threading
from typing import TYPE_CHECKING

from app.config import settings
from app.domain.fabio_ai.services.trade_manager import TradeManager, ExitReason
from app.domain.fabio_ai.services.prompt_builder import (
    OVERSEER_INSTRUCTION,
    OverseerAction,
    build_overseer_prompt,
    parse_overseer_response,
)

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, AMTResult
    from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService
    from app.domain.ports.event_bus import EventBusPort
    from app.domain.ports.storage import StoragePort
    from app.domain.ports.probability_inference import ProbabilityInferencePort

logger = logging.getLogger(__name__)

# Minimum seconds between overseer calls
# Fabio Gap #3: Reduced from 10s to 3s for faster position management
OVERSEER_COOLDOWN = 3.0

# ADD rate-limiting
ADD_COOLDOWN = 120.0  # 2 minutes between ADD actions
MAX_ADDS_PER_POSITION = 2  # Maximum ADDs per position lifetime


class LLMOverseerHandler:
    """Active position overseer — queries LLM every ~10s while a position is open."""

    OVERSEER_INSTRUCTION = OVERSEER_INSTRUCTION

    def __init__(
        self,
        gen_ai_service: GenerativeAIService,
        event_bus: EventBusPort,
        trade_manager: TradeManager,
        storage: StoragePort | None = None,
        probability_engine: ProbabilityInferencePort | None = None,
        session_risk_manager=None,
    ) -> None:
        self._gen_ai_service = gen_ai_service
        self._event_bus = event_bus
        self._trade_manager = trade_manager
        self._storage = storage
        self._probability_engine = probability_engine
        self._session_risk_manager = session_risk_manager
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self._predict_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        # Per-symbol worker queues for overseer inference
        self._llm_queues: dict[str, queue.Queue] = {}
        self._worker_threads: dict[str, threading.Thread] = {}
        self._workers_lock = threading.Lock()

        # ADD rate-limiting state
        self._last_add_time: float = 0.0
        self._add_count: int = 0

    def reset_position_state(self) -> None:
        """Reset per-position state — call when position closes."""
        self._last_add_time = 0.0
        self._add_count = 0

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
        session_info=None,
        footprint_candle=None,
    ) -> None:
        """Run overseer analysis in background thread."""
        with session._lock:
            session._last_overseer_time = time.time()
            session._overseer_running = True

        # Gather position state from TradeManager — filter by symbol
        with session._lock:
            open_ids = {p.id for p in session.portfolio.positions if p.status == "OPEN"}
        managed_position_ids = self._trade_manager.get_managed_position_ids(
            symbol=symbol,
            open_ids=open_ids,
        )
        if not managed_position_ids:
            with session._lock:
                session._overseer_running = False
            return

        position_id = managed_position_ids[0]

        # Ensure per-symbol queue and worker exist
        with self._workers_lock:
            if symbol not in self._llm_queues:
                self._llm_queues[symbol] = queue.Queue()
                wt = threading.Thread(
                    target=self._llm_worker_loop,
                    args=(symbol,),
                    daemon=True,
                    name=f"LLM-Overseer-{symbol}",
                )
                self._worker_threads[symbol] = wt
                wt.start()

        item = {
            "session": session,
            "symbol": symbol,
            "tick": tick,
            "amt_result": amt_result,
            "session_info": session_info,
            "footprint_candle": footprint_candle,
            "position_id": position_id,
            "enqueue_time": time.time(),
        }
        try:
            self._llm_queues[symbol].put_nowait(item)
            logger.debug(f"Queued LLM overseer analysis for {symbol}")
        except queue.Full:
            logger.warning(f"LLM Overseer queue full, dropping tracking for {symbol}")
            with session._lock:
                session._overseer_running = False

    def _llm_worker_loop(self, queue_symbol: str) -> None:
        """Dedicated background thread that processes LLM overseer requests sequentially for a specific symbol."""
        from app.config import settings as _settings

        with self._workers_lock:
            worker_queue = self._llm_queues.get(queue_symbol)

        if not worker_queue:
            logger.error(
                f"Overseer worker for {queue_symbol} started but no queue found!"
            )
            return

        while True:
            item = worker_queue.get()
            if item is None:
                worker_queue.task_done()
                break  # shutdown signal

            try:
                enqueue_time = item["enqueue_time"]
                session = item["session"]
                symbol = item["symbol"]
                tick = item["tick"]
                amt_result = item["amt_result"]
                session_info = item["session_info"]
                footprint_candle = item["footprint_candle"]
                position_id = item["position_id"]

                # Staleness check: Drop if sitting in queue > 30 seconds
                if time.time() - enqueue_time > 30.0:
                    logger.warning(f"Dropping stale LLM overseer request for {symbol}")
                    with session._lock:
                        session._overseer_running = False
                    continue

                if not self._gen_ai_service.is_ready():
                    with session._lock:
                        session._overseer_running = False
                    continue

                pos_state = self._trade_manager.get_position_state(
                    position_id, tick.close
                )
                if pos_state is None:
                    logger.debug(
                        "Overseer: position %s closed before worker started",
                        position_id,
                    )
                    with session._lock:
                        session._overseer_running = False
                    continue

                exit_probability = None
                if self._probability_engine and self._probability_engine.is_ready():
                    try:
                        from app.domain.probability.features import extract_features

                        data = getattr(session, "data", [])
                        if len(data) >= 20:
                            is_mcx = symbol.split()[0] in ["CRUDEOIL", "GOLD", "SILVER", "NATURALGAS", "COPPER"]
                            features = extract_features(
                                data,
                                amt_result,
                                tick,
                                getattr(session, "order_book", None),
                                is_mcx=is_mcx,
                            )
                            side = pos_state["side"]
                            prob_future = self._predict_executor.submit(
                                self._probability_engine.estimate, features
                            )
                            try:
                                estimate = prob_future.result(timeout=2.0)
                            except concurrent.futures.TimeoutError:
                                logger.warning(
                                    "Probability inference timed out in overseer"
                                )
                                estimate = None
                            if estimate is not None:
                                if side == "LONG":
                                    exit_probability = 1.0 - getattr(
                                        estimate, "p_long_target", 0.5
                                    )
                                else:
                                    exit_probability = 1.0 - getattr(
                                        estimate, "p_short_target", 0.5
                                    )
                                pos_state["exit_probability"] = exit_probability
                    except Exception:
                        logger.warning(
                            "Probability engine failed in overseer", exc_info=True
                        )

                prompt = build_overseer_prompt(
                    pos_state,
                    tick,
                    amt_result,
                    session_info=session_info,
                    footprint_candle=footprint_candle,
                )

                logger.info(
                    "LLM overseer starting for %s (%s from %.2f, unrealized=%.2f%%)",
                    symbol,
                    pos_state["side"],
                    pos_state["entry_price"],
                    pos_state["unrealized_pnl_pct"] * 100,
                )

                try:
                    adapter = self._gen_ai_service.llm_adapter
                    predict_future = self._predict_executor.submit(
                        adapter.predict,
                        self.OVERSEER_INSTRUCTION,
                        prompt,
                    )
                    try:
                        raw = predict_future.result(
                            timeout=_settings.LLM_TIMEOUT_SECONDS
                        )
                    except concurrent.futures.TimeoutError:
                        predict_future.cancel()
                        logger.warning(
                            "Overseer LLM timed out after %.0fs — defaulting to HOLD",
                            _settings.LLM_TIMEOUT_SECONDS,
                        )
                        raw = None
                except Exception as e:
                    logger.error(f"LLM inference exception: {e}", exc_info=True)
                    raw = None

                if not raw:
                    with session._lock:
                        session._overseer_running = False
                    continue

                decision = parse_overseer_response(raw, pos_state)
                logger.info(
                    "LLM overseer: %s (reason: %s)",
                    decision.action,
                    decision.reason[:80],
                )

                if (
                    exit_probability is not None
                    and exit_probability > 0.65
                    and decision.action == "HOLD"
                ):
                    # PnL guard: preserve alpha in profitable positions unless probability is very high
                    pnl_pct = pos_state.get("unrealized_pnl_pct", 0.0)
                    # Exit if: very high adverse prob (>0.80), OR moderate prob + not meaningfully profitable
                    should_exit = (exit_probability >= 0.80) or (
                        exit_probability > 0.65 and pnl_pct < 0.02
                    )
                    if should_exit:
                        logger.info(
                            "Probability override: P(adverse)=%.2f, PnL=%.1f%% — overriding HOLD→FULL_EXIT",
                            exit_probability,
                            pnl_pct * 100,
                        )
                        decision = OverseerAction(
                            action="FULL_EXIT",
                            reason=f"Probability model: {exit_probability:.0%} adverse + PnL {pnl_pct:.1%}",
                        )
                    else:
                        logger.info(
                            "Probability override SKIPPED: P(adverse)=%.2f but PnL=+%.1f%% — keeping HOLD",
                            exit_probability,
                            pnl_pct * 100,
                        )

                if decision.action == "ADD" and exit_probability is not None:
                    continuation_prob = 1.0 - exit_probability
                    if continuation_prob < 0.7:
                        logger.info(
                            "ADD blocked by probability: P(continuation)=%.2f < 0.70",
                            continuation_prob,
                        )
                        decision = OverseerAction(
                            action="HOLD",
                            reason="ADD blocked — insufficient continuation probability",
                        )

                self._execute_decision(decision, session, symbol, tick.close, pos_state)

                with session._lock:
                    overseer_info = session.last_ai_analysis or {}
                    overseer_info["overseer_action"] = decision.action
                    overseer_info["overseer_reason"] = decision.reason
                    overseer_info["input_prompt"] = prompt
                    overseer_info["raw_output"] = raw
                    session.last_ai_analysis = overseer_info

                if self._storage:
                    try:
                        self._storage.save_llm_decision(
                            {
                                "symbol": symbol,
                                "direction": decision.action,
                                "confidence": "Overseer",
                                "rationale": decision.reason,
                                "input_prompt": prompt[:500],
                                "raw_output": raw[:500],
                                "market_state": pos_state.get("market_state", ""),
                                "price": tick.close,
                            }
                        )
                    except Exception:
                        pass

                with session._lock:
                    session._overseer_running = False

            except Exception as e:
                logger.error(f"Worker loop fatal error: {e}", exc_info=True)
            finally:
                worker_queue.task_done()

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
                with session._lock:
                    adjusted = self._trade_manager.adjust_stop_loss(
                        position_id, decision.new_sl_price
                    )
                if adjusted:
                    logger.info(
                        "Overseer: tightened SL to %.2f for %s",
                        decision.new_sl_price,
                        position_id,
                    )
                else:
                    logger.info("Overseer: SL adjustment rejected (would widen risk)")

        elif decision.action == "PARTIAL_EXIT":
            if not pos_state.get("partial_taken"):
                with session._lock:
                    portfolio = session.portfolio
                    open_positions = [
                        p
                        for p in portfolio.positions
                        if p.status == "OPEN" and p.id == position_id
                    ]
                    if open_positions:
                        realized = portfolio.partial_close_position(
                            open_positions[0].id,
                            0.50,
                            current_price,
                            ExitReason.OVERSEER_PARTIAL,
                        )
                        logger.info(
                            "Overseer: partial exit for %s, realized=%.2f",
                            position_id,
                            realized,
                        )
                        self._trade_manager.adjust_stop_loss(
                            position_id, pos_state["entry_price"]
                        )
            else:
                logger.info("Overseer: partial already taken, ignoring PARTIAL_EXIT")

        elif decision.action == "FULL_EXIT":
            with session._lock:
                portfolio = session.portfolio
                open_positions = [
                    p
                    for p in portfolio.positions
                    if p.status == "OPEN" and p.id == position_id
                ]
                if open_positions:
                    portfolio.close_position(
                        position_id, current_price, ExitReason.OVERSEER_EXIT
                    )
                    self._trade_manager.unregister_position(position_id)
                    logger.info(
                        "Overseer: full exit for %s at %.2f", position_id, current_price
                    )
            self.reset_position_state()

        elif decision.action == "ADD":
            # Risk tier gate: block ADDs in cautious/defensive tiers
            if self._session_risk_manager:
                tier = self._session_risk_manager.current_tier
                if hasattr(tier, "name") and tier.name in ("CAUTIOUS", "DEFENSIVE"):
                    logger.info("Overseer: ADD blocked by risk tier %s", tier.name)
                    return

            # Rate-limiting: cooldown + max count
            now = time.time()
            if self._add_count >= MAX_ADDS_PER_POSITION:
                logger.info(
                    "Overseer: ADD rejected — max adds reached (%d/%d)",
                    self._add_count,
                    MAX_ADDS_PER_POSITION,
                )
                return
            if now - self._last_add_time < ADD_COOLDOWN and self._last_add_time > 0:
                logger.info(
                    "Overseer: ADD rejected — cooldown (%.0fs remaining)",
                    ADD_COOLDOWN - (now - self._last_add_time),
                )
                return

            if pos_state["unrealized_pnl_pct"] > 0 and not pos_state.get(
                "partial_taken"
            ):
                with session._lock:
                    self._last_add_time = now
                    self._add_count += 1
                logger.info(
                    "Overseer: ADD signal for %s — publishing pyramid signal (%d/%d)",
                    position_id,
                    self._add_count,
                    MAX_ADDS_PER_POSITION,
                )
            else:
                logger.info(
                    "Overseer: ADD rejected — not profitable or partial already taken"
                )

    def cleanup(self) -> None:
        """Shutdown thread pools on handler destruction."""
        for pool_attr in ("_executor", "_predict_executor"):
            pool = getattr(self, pool_attr, None)
            if pool:
                pool.shutdown(wait=False)
        with self._workers_lock:
            for q in self._llm_queues.values():
                try:
                    q.put_nowait(None)
                except queue.Full:
                    pass
