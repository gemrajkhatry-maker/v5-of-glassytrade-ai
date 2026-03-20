"""LLM Worker — dedicated background thread for LLM inference per symbol.

Extracted from LLMEntryHandler._llm_worker_loop() to separate concerns:
- LLMEntryHandler: orchestration (should_run, queue management)
- LLMWorker: inference execution (prompt building, gate evaluation, signal generation)

Each symbol gets its own LLMWorker thread for parallel inference across symbols.

Usage:
    worker = LLMWorker(
        symbol="CRUDEOIL",
        gen_ai_service=gen_ai,
        event_bus=event_bus,
        gate_chain=gate_chain,
    )
    worker.start()
    worker.enqueue(item)
"""

from __future__ import annotations

import concurrent.futures
import logging
import queue
import threading
import time
from typing import TYPE_CHECKING

from app.config import settings
from app.domain.trading.models.enums import MarketStateCodec, SignalType, SetupType
from app.domain.trading.events import AIAnalysisCompleted
from app.domain.fabio_ai.services.gates.base import GateContext, GateChain
from app.domain.fabio_ai.services.entry_gate import (
    build_entry_signal,
    check_momentum_fade,
)
from app.domain.constants import (
    GRADE_EXTREME_THRESHOLD,
    STALENESS_TIMEOUT_SECONDS,
)

if TYPE_CHECKING:
    from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService
    from app.domain.ports.event_bus import EventBusPort

logger = logging.getLogger(__name__)


class LLMWorker:
    """Dedicated background thread for LLM inference.

    Processes queued LLM requests sequentially for a specific symbol.
    Handles prompt building, inference, gate evaluation, and signal generation.
    """

    def __init__(
        self,
        symbol: str,
        gen_ai_service: GenerativeAIService,
        event_bus: EventBusPort,
        gate_chain: GateChain | None = None,
        journal=None,
    ) -> None:
        self._symbol = symbol
        self._gen_ai_service = gen_ai_service
        self._event_bus = event_bus
        self._gate_chain = gate_chain
        self._journal = journal

        self._queue: queue.Queue = queue.Queue(maxsize=10)
        self._thread: threading.Thread | None = None
        self._predict_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def start(self) -> None:
        """Start the worker thread."""
        if self._thread and self._thread.is_alive():
            return

        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name=f"LLM-Worker-{self._symbol}",
        )
        self._thread.start()
        logger.info("LLM worker started for %s", self._symbol)

    def enqueue(self, item: dict) -> bool:
        """Enqueue an LLM request.

        Args:
            item: Dict with session, tick, amt_result, market_data_ai, etc.

        Returns:
            True if enqueued, False if queue is full.
        """
        try:
            item["enqueue_time"] = time.time()
            self._queue.put_nowait(item)
            return True
        except queue.Full:
            logger.warning("LLM queue full for %s — dropping request", self._symbol)
            return False

    def shutdown(self) -> None:
        """Shutdown the worker thread."""
        try:
            self._queue.put_nowait(None)  # Shutdown signal
        except queue.Full:
            pass

    def _loop(self) -> None:
        """Main worker loop — processes requests sequentially."""
        while True:
            try:
                item = self._queue.get()
                if item is None:
                    break  # Shutdown signal

                self._process(item)
                self._queue.task_done()

            except Exception as e:
                logger.error("LLM worker error for %s: %s", self._symbol, e, exc_info=True)
                try:
                    self._queue.task_done()
                except Exception:
                    pass

    def _process(self, item: dict) -> None:
        """Process a single LLM request."""
        session = item["session"]
        symbol = item["symbol"]
        tick = item["tick"]
        amt_result = item["amt_result"]
        market_data_ai = item["market_data_ai"]
        setup_type = item["setup_type"]
        session_info = item["session_info"]
        enqueue_time = item["enqueue_time"]

        # Staleness check
        if time.time() - enqueue_time > STALENESS_TIMEOUT_SECONDS:
            logger.warning("Dropping stale LLM request for %s", symbol)
            with session._lock:
                session._ai_running = False
            return

        # Model readiness check
        if not self._gen_ai_service.is_ready():
            with session._lock:
                session.last_ai_analysis = {
                    "direction": "FLAT",
                    "rationale": "Model loading...",
                    "confidence": "Low",
                }
                session._ai_running = False
            return

        # LLM inference
        fallback_direction = self._get_fallback_direction(session, amt_result)

        try:
            predict_future = self._predict_executor.submit(
                self._gen_ai_service.analyze_market,
                market_data_ai,
            )
            ai_result = predict_future.result(timeout=settings.LLM_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            predict_future.cancel()
            logger.warning("LLM timed out for %s", symbol)
            ai_result = {
                "direction": fallback_direction,
                "rationale": "Timeout fallback — quant signal",
                "confidence": "Medium",
                "input_prompt": "",
                "raw_output": "TIMEOUT_FALLBACK",
                "market_state": item.get("market_state_str", "Unknown"),
            }
        except Exception as e:
            logger.error("LLM inference failed for %s: %s", symbol, e, exc_info=True)
            with session._lock:
                session._ai_running = False
            return

        direction = ai_result.get("direction", "FLAT")
        confidence = ai_result.get("confidence", "Medium")

        # Apply gate chain if configured
        if self._gate_chain and direction in ("LONG", "SHORT"):
            gate_context = GateContext(
                tick=tick,
                amt_result=amt_result,
                session_data=session.data,
                cvd_slope=amt_result.cvd_slope,
                cvd_divergence=amt_result.cvd_divergence,
                direction=direction,
                cvd_threshold=self._get_cvd_threshold(),
            )
            gate_result = self._gate_chain.evaluate(gate_context)
            if not gate_result.passed:
                logger.info("Gate chain blocked %s for %s: %s", direction, symbol, gate_result.detail)
                direction = "FLAT"
                confidence = "Low"

        # BUY-only enforcement
        if direction == "SHORT" and not settings.ALLOW_SHORT:
            logger.info("BUY-ONLY mode: SHORT blocked for %s", symbol)
            direction = "FLAT"

        # Update session
        with session._lock:
            session.last_ai_analysis = {
                "direction": direction,
                "rationale": ai_result.get("rationale", ""),
                "confidence": confidence,
                "input_prompt": ai_result.get("input_prompt", ""),
                "raw_output": ai_result.get("raw_output", ""),
                "market_state": ai_result.get("market_state", "Unknown"),
                "aggression": ai_result.get("aggression", "0.00"),
            }
            session._ai_running = False

        # Persist LLM decision
        self._persist_decision(symbol, direction, confidence, ai_result, amt_result, tick, setup_type, session_info)

        # Publish event
        self._event_bus.publish(
            AIAnalysisCompleted(
                symbol=symbol,
                direction=direction,
                rationale=ai_result.get("rationale", ""),
                confidence=confidence,
            )
        )

        logger.info("LLM result for %s: direction=%s confidence=%s", symbol, direction, confidence)

    def _get_fallback_direction(self, session, amt_result) -> str:
        """Get fallback direction from agent decision or AMT signal."""
        agent = getattr(session, "_agent_decision", None)
        if agent and agent.direction != "FLAT":
            return agent.direction
        if amt_result.signal:
            return "LONG" if amt_result.signal.type == SignalType.BUY else "SHORT"
        return "FLAT"

    def _get_cvd_threshold(self) -> float:
        """Get market-specific CVD threshold."""
        from app.domain.constants import CVD_BLOCK_THRESHOLD_NSE, CVD_BLOCK_THRESHOLD_MCX
        if settings.SCANNER_MODE in ("nse", "nse_options"):
            return CVD_BLOCK_THRESHOLD_NSE
        return CVD_BLOCK_THRESHOLD_MCX

    def _persist_decision(self, symbol, direction, confidence, ai_result, amt_result, tick, setup_type, session_info) -> None:
        """Persist LLM decision to storage."""
        # Journal logging
        if self._journal:
            try:
                agent = getattr(ai_result.get("session"), "_agent_decision", None) if hasattr(ai_result, "session") else None
                self._journal.log_signal(
                    symbol=symbol,
                    amt={"poc": amt_result.poc, "vah": amt_result.value_area_high, "val": amt_result.value_area_low},
                    llm_direction=direction,
                    llm_confidence=confidence,
                    llm_rationale=ai_result.get("rationale", ""),
                    agent_direction=agent.direction if agent else "",
                    agent_regime=agent.regime if agent else "",
                )
            except Exception:
                logger.debug("Journal log_signal failed", exc_info=True)