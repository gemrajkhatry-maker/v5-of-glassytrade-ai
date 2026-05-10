"""LLM entry handler.

Coordinates LLM inference for trade direction gating in v2.
This is a standalone application-layer handler that outputs a parsed
LLM decision and optionally persists it to storage.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import queue
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Any

from app.domain.amt.service.regime_detector import RegimeDetector
from app.domain.fabio_ai.services.llm_response_parser import LLMResponseParser
from app.domain.fabio_ai.services.session_phase_gate import SessionPhaseInfo, get_session_phase
from app.domain.shared.port import ILLMInference, IStorage, LLMNotReadyError
from app.domain.trading.model.value_objects import AMTResult, OHLC
from app.runtime.pipeline.events import Signal
from app.application.service.llm_decision_repository import LLMDecisionRepository
from app.application.service.llm_context_builder import LLMContextBuilder

from app.shared.timezones import IST



logger = logging.getLogger(__name__)


def _to_ist_datetime(timestamp: float | int | str | datetime | None) -> datetime:
    """Convert timestamp to IST datetime (helper for market open calculations)."""
    if isinstance(timestamp, datetime):
        dt = timestamp
    elif timestamp is None:
        dt = datetime.now(tz=IST)
    else:
        if isinstance(timestamp, str):
            ts = float(timestamp)
        else:
            ts = float(timestamp)
        if ts > 1_000_000_000_000:
            dt = datetime.fromtimestamp(ts / 1_000_000_000, tz=IST)
        else:
            dt = datetime.fromtimestamp(ts, tz=IST)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


_MCX_COMMODITIES = (
    "GOLD",
    "GOLDM",
    "SILVER",
    "SILVERM",
    "CRUDEOIL",
    "CRUDEOILM",
    "NATURALGAS",
    "COPPER",
    "ZINC",
    "ALUMINIUM",
    "LEAD",
    "NICKEL",
)


_LLMReadyStateCallback = Callable[[str, "LLMDecision"], None]

from app.domain.fabio_ai.model.llm_decision import LLMDecision





def _is_mcx_symbol(symbol: str) -> bool:
    if not symbol:
        return False
    first_token = symbol.split(" ")[0].upper()
    return first_token in _MCX_COMMODITIES








def _normalize_direction(value: object) -> str:
    if not value:
        return "FLAT"
    text = str(value).strip().upper()
    if text in {"LONG", "BUY", "B", "UP", "1"}:
        return "LONG"
    if text in {"SHORT", "SELL", "S", "DOWN", "-1"}:
        return "SHORT"
    if text in {"FLAT", "HOLD", "WAIT", "NONE"}:
        return "FLAT"
    return text.split()[0] if text else "FLAT"


def _normalize_confidence(value: object) -> str:
    if value is None:
        return "Medium"
    text = str(value).strip()
    if not text:
        return "Medium"
    lower = text.lower()
    if lower in {"high", "h", "strong"}:
        return "High"
    if lower in {"low", "weak", "l"}:
        return "Low"
    if lower in {"none", "fallback", "flat", "unknown"}:
        return "Low"

    try:
        num = float(text.replace("%", ""))
    except ValueError:
        return "Medium"
    if 0 <= num <= 1:
        num = num * 100.0
    if num >= 85:
        return "High"
    if num >= 60:
        return "Medium"
    return "Low"


def _first_float(obj: dict[str, object], keys: tuple[str, ...]) -> float:
    for key in keys:
        value = obj.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


class LLMEntryHandler:
    """Application-layer orchestrator for LLM-assisted entry checks."""

    def __init__(
        self,
        llm: ILLMInference,
        storage: IStorage | None = None,
        allow_short: bool = False,
        llm_timeout: float = 15.0,
        exchange: str = "MCX",
        on_decision_ready: _LLMReadyStateCallback | None = None,
    ) -> None:
        self._llm = llm
        self._storage = storage
        self._decision_repo = LLMDecisionRepository(storage) if storage is not None else None
        self._context_builder = LLMContextBuilder(storage=storage, exchange=exchange)
        self._allow_short = allow_short
        self._llm_timeout = llm_timeout
        self._exchange = exchange
        self._on_decision_ready = on_decision_ready

        self._regime_detectors: dict[str, RegimeDetector] = {}
        self._llm_queues: dict[str, queue.Queue[Any]] = {}
        self._worker_threads: dict[str, threading.Thread] = {}
        self._workers_lock = threading.Lock()

        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

        # Cooldown and state-tracking are intentionally separate:
        # - _last_eval_time: last enqueue time for should_run() cooldown checks
        # - _last_consistency_time: last completed LLM decision for 60s consistency guard
        self._last_eval_time: dict[str, float] = {}
        self._last_consistency_time: dict[str, float] = {}
        self._last_direction: dict[str, str] = {}
        self._last_confidence: dict[str, str] = {}

    def _get_regime_detector(self, symbol: str) -> RegimeDetector:
        if symbol in self._regime_detectors:
            return self._regime_detectors[symbol]
        with self._workers_lock:
            if symbol not in self._regime_detectors:
                self._regime_detectors[symbol] = RegimeDetector()
            return self._regime_detectors[symbol]

    def session_market_for_symbol(self, symbol: str) -> str:
        if not symbol:
            return "NSE"
        return "MCX" if _is_mcx_symbol(symbol) else "NSE"

    def _build_session_phase_block_result(
        self,
        session_info: SessionPhaseInfo,
        symbol: str,
        market_state_str: str,
        amt_result: AMTResult,
        tick,
    ) -> dict[str, object]:
        del symbol, amt_result
        return {
            "direction": "FLAT",
            "confidence": "High",
            "rationale": f"Market in {session_info.session_name} phase. Entries blocked by session rules.",
            "input_prompt": f"[SESSION_GATE] phase={session_info.session_name}",
            "raw_output": "SESSION_PHASE_BLOCKED",
            "market_state": market_state_str,
        }

    def _save_session_block_decision(
        self,
        symbol: str,
        market_state_str: str,
        amt_result: AMTResult,
        tick,
        tick_trace_id: str = "",
    ) -> None:
        decision = LLMDecision(
            direction="FLAT",
            confidence="High",
            rationale=f"Market in {market_state_str}. Entries blocked.",
            input_prompt="[SESSION_GATE] no entry",
            raw_output="SESSION_PHASE_BLOCKED",
            market_state=market_state_str,
            tick_trace_id=tick_trace_id,
        )
        try:
            self._save_llm_decision(symbol, decision, amt_result, [tick] if tick is not None else [])
        except Exception:
            logger.debug("Session block persistence failed", exc_info=True)








    @staticmethod
    def _resolve_fallback_direction(session, amt_result) -> str:
        if not session:
            return "FLAT"
        ad = getattr(session, "_agent_decision", None)
        if ad and getattr(ad, "direction", "FLAT") != "FLAT":
            return ad.direction
        if str(getattr(amt_result, "signal", "FLAT")).upper() in {"LONG", "BUY"}:
            return "LONG"
        if str(getattr(amt_result, "signal", "FLAT")).upper() in {"SHORT", "SELL"}:
            return "SHORT"
        return "FLAT"

    @staticmethod
    def _compute_journal_attribution(_agent, direction: str) -> str:
        if _agent is None:
            return "llm_only"
        if getattr(_agent, "direction", "FLAT") == direction and direction != "FLAT":
            return "llm_plus_quant_agree"
        if getattr(_agent, "direction", "FLAT") in {"", "FLAT", direction}:
            return "llm_only"
        return "llm_override_quant"



    @staticmethod
    def _is_extreme_volatility(amt_result) -> bool:
        if float(getattr(amt_result, "price_velocity", 0.0)) > 5.0:
            return True
        if abs(float(getattr(amt_result, "cvd_slope", 0.0))) > 100.0:
            return True
        return False

    @staticmethod
    def _check_direction_mismatch(_agent, direction: str, symbol: str, session, worker_queue, tick_trace_id: str = "") -> bool:
        del symbol, session, worker_queue, tick_trace_id
        if not _agent:
            return False
        return bool(_agent.direction != "FLAT" and _agent.direction != direction)

    @staticmethod
    def _parse_llm_response(raw: str, direction_hint: str) -> tuple[str, str, str]:
        """Parse LLM raw response using the extracted parser service with fallbacks."""
        # Empty input handling
        if not raw or not raw.strip():
            return direction_hint, "Medium", ""

        # 1. Try JSON extraction via parser service
        parsed = LLMResponseParser.parse(raw)
        if parsed is not None:
            direction = parsed["direction"]  # already uppercase
            # Normalize confidence to title case using module-level function
            confidence = _normalize_confidence(parsed["confidence"])
            rationale = parsed["rationale"]
            logger.debug("[PARSER] JSON success dir=%s conf=%s", direction, confidence)
            return direction, confidence, rationale

        # 2. Try colon-based key-value lines (Direction: LONG, Confidence: Medium, Rationale: ...)
        payload: dict[str, str] = {}
        for line in raw.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if not value:
                continue
            payload.setdefault(key, value)
        if payload:
            direction = _normalize_direction(
                payload.get("direction") or payload.get("signal") or payload.get("action"),
            )
            confidence = _normalize_confidence(
                payload.get("confidence")
                or payload.get("score")
                or payload.get("probability")
                or payload.get("prob")
            )
            rationale = (
                payload.get("rationale")
                or payload.get("reason")
                or payload.get("analysis")
                or raw[:500]
            )
            logger.debug("[PARSER] key=value success dir=%s conf=%s", direction, confidence)
            return direction, confidence, rationale

        # 3. Fallback keyword scan
        up = raw.upper()
        if "LONG" in up or "BUY" in up:
            direction = "LONG"
        elif "SHORT" in up or "SELL" in up:
            direction = "SHORT"
        elif "FLAT" in up or "HOLD" in up:
            direction = "FLAT"
        else:
            direction = direction_hint
        confidence = "Medium"
        rationale = raw[:500]
        logger.debug("[PARSER] fallback keyword dir=%s", direction)
        return direction, confidence, rationale

    @staticmethod
    def _sanitize_rationale(raw_rationale: str, direction: str) -> str:
        """Sanitize rationale using the extracted parser service."""
        return LLMResponseParser.sanitize(raw_rationale, direction)

    def should_run(
        self,
        signal: Signal,
        amt_result: AMTResult,
        has_position: bool,
        ai_running: bool,
    ) -> bool:
        if not signal.symbol:
            return False
        if signal.type == "NO_TRADE":
            return False
        if ai_running:
            return False
        if has_position:
            return False
        try:
            if self._llm.is_ready() is False:
                return False
        except LLMNotReadyError:
            return False
        except Exception:
            return False

        if float(getattr(amt_result, "poc", 0.0) or 0.0) <= 0:
            return False
        if float(getattr(amt_result, "value_area_high", 0.0) or 0.0) <= 0:
            return False

        if (getattr(amt_result, "market_state", "") or "").upper() == "DEAD":
            return False

        now = time.time()
        last = self._last_eval_time.get(signal.symbol, 0.0)
        if (now - last) < 30.0:
            return False

        return True

    def run_entry(
        self,
        signal: Signal,
        amt_result: AMTResult,
        candles: list[OHLC],
        tick_trace_id: str = "",
    ) -> LLMDecision | None:
        """Queue LLM work item for one symbol and return immediately."""
        symbol = signal.symbol
        if not symbol:
            return None

        self._last_eval_time[symbol] = time.time()

        session_phase = get_session_phase(signal.timestamp, self._exchange, symbol)
        context = self._build_context(
            signal=signal,
            amt_result=amt_result,
            candles=candles,
            session_phase=session_phase,
        )

        market_state = str(getattr(amt_result, "market_state", "UNKNOWN"))
        if session_phase and not session_phase.allow_entry:
            block_payload = self._build_session_phase_block_result(
                session_phase,
                symbol,
                market_state,
                amt_result,
                candles[-1] if candles else None,
            )
            decision = LLMDecision(
                direction=str(block_payload.get("direction", "FLAT")),
                confidence=str(block_payload.get("confidence", "High")),
                rationale=str(block_payload.get("rationale", "")),
                input_prompt=str(block_payload.get("input_prompt", "")),
                raw_output=str(block_payload.get("raw_output", "SESSION_PHASE_BLOCKED")),
                market_state=str(block_payload.get("market_state", market_state)),
                tick_trace_id=tick_trace_id,
            )
            self._save_llm_decision(symbol, decision, amt_result, candles)
            self._save_session_block_decision(
                symbol,
                market_state_str=market_state,
                amt_result=amt_result,
                tick=candles[-1] if candles else None,
                tick_trace_id=tick_trace_id,
            )
            if self._on_decision_ready is not None:
                self._on_decision_ready(symbol, decision)
            return decision

        if market_state.upper() == "DEAD":
            decision = LLMDecision(
                direction="FLAT",
                confidence="High",
                rationale="DEAD market: reduced liquidity",
                input_prompt="[DEAD_MARKET] bypassed LLM due to dead regime",
                raw_output="DEAD_MARKET",
                market_state=market_state,
                tick_trace_id=tick_trace_id,
            )
            self._save_llm_decision(symbol, decision, amt_result, candles)
            if self._on_decision_ready is not None:
                self._on_decision_ready(symbol, decision)
            return decision

        with self._workers_lock:
            if symbol not in self._llm_queues:
                self._llm_queues[symbol] = queue.Queue(maxsize=10)
                worker = threading.Thread(
                    target=self._worker_loop,
                    args=(symbol,),
                    daemon=True,
                    name=f"llm-entry-worker-{symbol}",
                )
                self._worker_threads[symbol] = worker
                worker.start()

        item = {
            "symbol": symbol,
            "signal": signal,
            "amt_result": amt_result,
            "candles": list(candles),
            "context": context,
            "session_phase": session_phase,
            "tick_trace_id": tick_trace_id,
            "enqueue_time": time.time(),
            "market_state": market_state,
        }

        try:
            self._llm_queues[symbol].put_nowait(item)
        except queue.Full:
            logger.warning("LLM queue full, dropping item for %s", symbol)
            self._last_eval_time[symbol] = time.time()
            decision = LLMDecision(
                direction="FLAT",
                confidence="Low",
                rationale="LLM request dropped due to queue full",
                input_prompt=context,
                raw_output="WORKER_QUEUE_FULL",
                market_state=market_state,
                tick_trace_id=tick_trace_id,
            )
            self._save_llm_decision(symbol, decision, amt_result, candles)
            if self._on_decision_ready is not None:
                self._on_decision_ready(symbol, decision)
            return decision
        return None

    def _build_context(
        self,
        signal: Signal,
        amt_result: AMTResult,
        candles: list[OHLC],
        session_phase: SessionPhaseInfo,
    ) -> str:
        """Build JSON prompt context used for LLM inference."""
        return self._context_builder.build(signal, amt_result, candles, session_phase)





    def _save_llm_decision(
        self,
        symbol: str,
        decision: LLMDecision,
        amt_result: AMTResult,
        candles: list[OHLC],
    ) -> None:
        # Update in-memory tracking for consistency guard
        self._last_direction[symbol] = decision.direction
        self._last_confidence[symbol] = decision.confidence

        if self._decision_repo is None:
            return
        try:
            self._decision_repo.save(symbol, decision, amt_result, candles)
        except Exception:
            logger.debug("LLM decision persistence failed", exc_info=True)

    def _apply_safety_nets(
        self,
        symbol: str,
        direction: str,
        confidence: str,
        rationale: str,
        signal: Signal,
        amt_result: AMTResult,
    ) -> tuple[str, str, str]:
        if direction == "SHORT" and not self._allow_short:
            return "FLAT", confidence, "System in BUY-ONLY mode"
        if direction == "LONG":
            entry = float(signal.entry)
            session_vwap = float(getattr(amt_result, "session_vwap", 0.0))
            vwap_upper2 = float(getattr(amt_result, "vwap_upper_2", 0.0))
            if session_vwap > 0.0 and vwap_upper2 > 0.0 and entry >= vwap_upper2 * 1.01:
                return (
                    direction,
                    "Low",
                    f"{rationale} [VWAP extreme: > +2σ]",
                )
        return direction, confidence, rationale

    def _worker_loop(self, queue_symbol: str) -> None:
        with self._workers_lock:
            worker_queue = self._llm_queues.get(queue_symbol)
        if worker_queue is None:
            return

        while True:
            item = worker_queue.get()
            if item is None:
                break

            task_done = False
            try:
                enqueue_time = float(item["enqueue_time"])
                symbol = str(item["symbol"])
                signal = item["signal"]
                amt_result = item["amt_result"]
                candles = item["candles"]
                context = str(item["context"])
                tick_trace_id = str(item.get("tick_trace_id", ""))
                session_phase = item["session_phase"]
                market_state = str(item.get("market_state", ""))

                if time.time() - enqueue_time > 20.0:
                    decision = LLMDecision(
                        direction="FLAT",
                        confidence="Low",
                        rationale="LLM request stale",
                        input_prompt=context,
                        raw_output="STALE_REQUEST",
                        market_state=market_state,
                        tick_trace_id=tick_trace_id,
                    )
                    self._save_llm_decision(symbol, decision, amt_result, candles)
                    if self._on_decision_ready is not None:
                        self._on_decision_ready(symbol, decision)
                    continue

                if not self._llm.is_ready():
                    raise RuntimeError("LLM not ready")

                predict_future = self._executor.submit(
                    self._llm.predict,
                    "Assess this AMT signal as LONG/SHORT/FLAT with confidence.",
                    context,
                )
                raw_output: str
                try:
                    raw_output = predict_future.result(timeout=self._llm_timeout)
                except concurrent.futures.TimeoutError:
                    predict_future.cancel()
                    raw_output = "TIMEOUT_FALLBACK"
                    direction = "FLAT"
                    confidence = "Low"
                    rationale = "LLM inference timeout, fallback to no-trade"
                else:
                    if not isinstance(raw_output, str):
                        raw_output = str(raw_output)
                    direction, confidence, rationale = self._parse_llm_response(
                        raw_output,
                        signal.type,
                    )
                now = time.time()

                previous_direction = self._last_direction.get(symbol, signal.type)
                previous_confidence = self._last_confidence.get(symbol, "Medium")
                previous_eval_time = self._last_consistency_time.get(symbol, 0.0)

                if now - previous_eval_time < 60.0:
                    direction = previous_direction
                    confidence = previous_confidence
                    rationale = "Held from previous evaluation (cooldown active)"
                else:
                    if (
                        previous_confidence == "High"
                        and _normalize_confidence(confidence) in {"Low", "None"}
                        and direction == "FLAT"
                    ):
                        direction = previous_direction
                        confidence = previous_confidence
                        rationale = "CONSISTENCY GUARD: prevented High→Low flip"
                    else:
                        rationale = self._sanitize_rationale(rationale, direction)
                        direction, confidence, rationale = self._apply_safety_nets(
                            symbol,
                            direction,
                            _normalize_confidence(confidence),
                            rationale,
                            signal,
                            amt_result,
                        )
                        self._last_consistency_time[symbol] = now
                    self._last_direction[symbol] = direction
                    self._last_confidence[symbol] = confidence

                decision = LLMDecision(
                    direction=direction,
                    confidence=confidence,
                    rationale=rationale,
                    input_prompt=context,
                    raw_output=raw_output,
                    market_state=market_state,
                    tick_trace_id=tick_trace_id,
                )
                self._save_llm_decision(symbol, decision, amt_result, candles)
                if self._on_decision_ready is not None:
                    self._on_decision_ready(symbol, decision)

                _ = session_phase, tick_trace_id
            except Exception:
                logger.exception("LLM worker failed", exc_info=True)
                symbol = str(item.get("symbol", queue_symbol)) if isinstance(item, dict) else queue_symbol
                amt_result = item.get("amt_result") if isinstance(item, dict) else None
                candles = item.get("candles") if isinstance(item, dict) else []
                signal = item.get("signal") if isinstance(item, dict) else None
                market_state = (
                    str(item.get("market_state", ""))
                    if isinstance(item, dict)
                    else ""
                )
                fallback_direction = _normalize_direction(
                    signal.type if signal is not None else "FLAT"
                )
                fallback_decision = LLMDecision(
                    direction=fallback_direction,
                    confidence="Low",
                    rationale="LLM worker failed; falling back to existing signal direction",
                    input_prompt=str(item.get("context", "")),
                    raw_output="WORKER_ERROR",
                    market_state=market_state,
                    tick_trace_id=str(item.get("tick_trace_id", "")) if isinstance(item, dict) else "",
                )
                if signal is not None and amt_result is not None and isinstance(candles, list):
                    self._save_llm_decision(symbol, fallback_decision, amt_result, candles)
                if self._on_decision_ready is not None:
                    self._on_decision_ready(symbol, fallback_decision)
            finally:
                if not task_done:
                    worker_queue.task_done()

    def record_stop_out(self, level: float, direction: str, session_phase: int, symbol: str) -> None:
        self._get_regime_detector(symbol).record_failed_entry(level, direction, session_phase)

    def record_successful_exit(self, symbol: str = "") -> None:
        self._get_regime_detector(symbol).record_successful_exit()

    def clear_failed_entries(self, symbol: str = "") -> None:
        if symbol:
            self._get_regime_detector(symbol).clear_failed_entries()
        else:
            with self._workers_lock:
                for det in self._regime_detectors.values():
                    det.clear_failed_entries()

    def cleanup(self) -> None:
        self._executor.shutdown(wait=False)
        with self._workers_lock:
            for q in self._llm_queues.values():
                try:
                    q.put_nowait(None)
                except queue.Full:
                    pass
            threads = list(self._worker_threads.values())
            for thread in threads:
                try:
                    thread.join(timeout=1.0)
                except RuntimeError:
                    pass

# Compatibility aliases for existing tests
_get_session_phase = get_session_phase
_SessionPhaseInfo = SessionPhaseInfo
