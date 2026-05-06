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
from app.domain.shared.port import ILLMInference, IStorage, LLMNotReadyError
from app.domain.trading.model.value_objects import AMTResult, OHLC
from app.runtime.pipeline.events import Signal
from app.shared.timezones import IST

logger = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class LLMDecision:
    """Structured output of the LLM entry helper."""

    direction: str
    confidence: str
    rationale: str
    input_prompt: str
    raw_output: str
    market_state: str
    tick_trace_id: str = ""


@dataclass(frozen=True)
class _SessionPhaseInfo:
    """Minimal session context used by the entry handler."""

    session_name: str
    phase_int: int
    allow_entry: bool
    allow_trend: bool
    session_market: str

    @property
    def session(self) -> str:
        return self.session_name


def _is_mcx_symbol(symbol: str) -> bool:
    if not symbol:
        return False
    first_token = symbol.split(" ")[0].upper()
    return first_token in _MCX_COMMODITIES


def _to_ist_datetime(timestamp: float | int | str | datetime | None) -> datetime:
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


def _get_session_phase(
    timestamp: float | int | str | datetime | None,
    market: str = "MCX",
    symbol: str = "",
) -> _SessionPhaseInfo:
    """NSE/MCX phase detector used by LLM entry handler."""
    dt = _to_ist_datetime(timestamp)
    m = market.upper()
    if _is_mcx_symbol(symbol):
        m = "MCX"
    elif m not in {"NSE", "MCX"}:
        m = "NSE"

    minutes = dt.hour * 60 + dt.minute
    if m == "NSE":
        if minutes < 9 * 60 + 15:
            return _SessionPhaseInfo("PRE_MARKET", 0, False, False, "NSE")
        if minutes < 9 * 60 + 30:
            return _SessionPhaseInfo("NSE_OPENING", 1, False, False, "NSE")
        if minutes < 11 * 60 + 30:
            return _SessionPhaseInfo("NSE_PRIMARY", 2, True, True, "NSE")
        if minutes < 14 * 60:
            return _SessionPhaseInfo("NSE_MIDDAY", 3, True, False, "NSE")
        if minutes < 15 * 60 + 15:
            return _SessionPhaseInfo("NSE_POWER_HOUR", 4, True, True, "NSE")
        if minutes < 15 * 60 + 30:
            return _SessionPhaseInfo("NSE_CLOSE", 5, False, False, "NSE")
        return _SessionPhaseInfo("POST_MARKET", 0, False, False, "NSE")

    # MCX
    if minutes < 9 * 60:
        return _SessionPhaseInfo("MCX_PRE_MARKET", 0, False, False, "MCX")
    if minutes < 9 * 60 + 15:
        return _SessionPhaseInfo("MCX_PRE_OPEN", 0, False, False, "MCX")
    if minutes < 14 * 60:
        return _SessionPhaseInfo("MCX_MORNING", 1, True, True, "MCX")
    if minutes < 18 * 60:
        return _SessionPhaseInfo("MCX_AFTERNOON", 2, True, True, "MCX")
    if minutes < 23 * 60:
        return _SessionPhaseInfo("MCX_EVENING", 3, True, True, "MCX")
    if minutes < 23 * 60 + 30:
        return _SessionPhaseInfo("MCX_CLOSE", 4, False, False, "MCX")
    return _SessionPhaseInfo("MCX_POST_MARKET", 0, False, False, "MCX")


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
        session_info: _SessionPhaseInfo,
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

    def _build_strategy_hint(self, amt_result, session_info, symbol: str | None = None, session=None) -> str:
        del session
        return self._derive_strategy_hint(
            signal=type("SignalLike", (), {"type": "NO_TRADE"})(),
            session_phase=session_info,
            amt_result=amt_result,
        ) + (f" Symbol={symbol}" if symbol else "")

    def _build_profile_description(self, amt_result) -> str:
        shape = str(getattr(amt_result, "profile_shape", "")).upper()
        return {
            "D": "D-shape (balanced, rotational)",
            "P": "P-shape (top-heavy, sellers may be trapped)",
            "B": "B-shape (bimodal / breakout-prone)",
            "b": "b-shape (bottom-heavy, buyer absorption)",
        }.get(shape, "")

    def _build_volume_bubble_summary(self, amt_result, tick) -> str:
        del tick
        bubbles = getattr(amt_result, "aggressive_prints", None)
        if not bubbles:
            return ""
        parts: list[str] = []
        try:
            for bubble in bubbles[-3:]:
                side = str(getattr(bubble, "side", "") or bubble.get("side", ""))
                price = float(getattr(bubble, "price", bubble.get("price", 0.0)))
                vol = float(getattr(bubble, "volume", bubble.get("volume", 0.0)))
                delta = float(getattr(bubble, "delta", bubble.get("delta", 0.0)))
                parts.append(f"{side} at {price:.0f} (vol {vol:.0f}, delta {delta:+.0f})")
        except Exception:
            logger.debug("Unable to build bubble summary", exc_info=True)
        return "; ".join(parts)

    def _get_amt_time_window(self, ist_now):
        hour = int(getattr(ist_now, "hour", 0))
        minute = int(getattr(ist_now, "minute", 0))
        return {
            "hour": hour,
            "minute": minute,
            "window": f"{hour:02d}:{minute:02d}",
            "elapsed_minutes": (hour * 60 + minute),
        }

    def _build_imbalance_summary(self, session) -> str:
        return ""

    def _load_episodic_memory(self) -> str:
        return self._build_episodic_memory()

    def _build_gate_context(self, amt_result, tick, session, session_info, agg_levels, fp_domain) -> str:
        del session, agg_levels, fp_domain
        market_state = str(getattr(amt_result, "market_state", "UNKNOWN"))
        return (
            f"[GATE CHECK] market={market_state}, session={session_info.session_name}, "
            f"tick={getattr(tick, 'close', 'n/a')}, reason=basic checks pending"
            if session_info and not session_info.allow_entry
            else ""
        )

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
    def _detect_option_type(symbol: str) -> str:
        if not symbol:
            return "UNKNOWN"
        upper = symbol.upper()
        if "CALL" in upper or upper.endswith("CE"):
            return "CALL"
        if "PUT" in upper or upper.endswith("PE"):
            return "PUT"
        return "UNKNOWN"

    @staticmethod
    def _enrich_market_context(market_data_ai: dict[str, object], amt_result) -> None:
        if float(getattr(amt_result, "aggression", 0.0)) < 1.0:
            market_data_ai["aggression_warning"] = "Weak aggression"
        if str(getattr(amt_result, "market_state", "")).upper() == "IMBALANCED":
            market_data_ai["drive_warning"] = "Imbalanced session"
        if abs(float(getattr(amt_result, "cvd_slope", 0.0))) > 50:
            market_data_ai["cvd_warning"] = "Extreme CVD slope"

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
        """Parse raw LLM output into direction, confidence, rationale."""
        fallback_direction = _normalize_direction(direction_hint)
        fallback_confidence = "Medium"
        text = (raw or "").strip()
        if not text:
            return fallback_direction, fallback_confidence, ""

        payload: dict[str, Any] = {}

        def _load_dict(candidate: str) -> dict[str, Any] | None:
            try:
                parsed = json.loads(candidate)
            except (json.JSONDecodeError, TypeError, ValueError):
                return None
            if isinstance(parsed, dict):
                return parsed
            return None

        parsed = _load_dict(text)
        if parsed is None:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if match:
                parsed = _load_dict(match.group(0))
        if isinstance(parsed, dict):
            payload = parsed
            direction = _normalize_direction(
                parsed.get("direction") or parsed.get("action") or parsed.get("signal") or ""
            )
            raw_confidence = (
                parsed.get("confidence")
                or parsed.get("score")
                or parsed.get("probability")
            )
            confidence = _normalize_confidence(raw_confidence)

            rationale = (
                str(parsed.get("rationale", "")).strip()
                or str(parsed.get("reason", "")).strip()
                or text
            )
            return direction, confidence, rationale

        for line in text.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip().lower()
            if not value:
                continue
            payload.setdefault(key, value.strip())

        if payload:
            direction = _normalize_direction(
                payload.get("direction") or payload.get("signal") or payload.get("action")
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
                or text
            )
            return direction, confidence, str(rationale)

        up = text.upper()
        if "LONG" in up or "BUY" in up:
            direction = "LONG"
        elif "SHORT" in up or "SELL" in up:
            direction = "SHORT"
        elif "FLAT" in up or "HOLD" in up:
            direction = "FLAT"
        else:
            direction = fallback_direction
        return direction, "Medium", text[:500]

    @staticmethod
    def _sanitize_rationale(raw_rationale: str, direction: str) -> str:
        """Strip JSON artifacts and normalize whitespace."""
        if not raw_rationale:
            return f"{direction} signal — no rationale provided"

        text = str(raw_rationale).strip()
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                parsed = None
            else:
                if isinstance(parsed, dict):
                    if "rationale" in parsed:
                        return str(parsed["rationale"]).strip() or f"{direction} signal"
                    if "analysis" in parsed:
                        return str(parsed["analysis"]).strip() or f"{direction} signal"
        if "{" in text and "}" in text:
            json_match = re.search(r"\{[^{}]*\"rationale\"[^{}]*\}", text, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group(0))
                    if isinstance(parsed, dict) and "rationale" in parsed:
                        return str(parsed["rationale"]).strip()
                except (json.JSONDecodeError, ValueError):
                    pass

        text = re.sub(r"\{[^}]*\}", "", text)
        text = text.replace("\\n", " ").replace("\\t", " ").replace('\\"', '"')
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return f"{direction} signal based on market analysis"
        return text

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

        session_phase = _get_session_phase(signal.timestamp, self._exchange, symbol)
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
                market_state=market_state,
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
        session_phase: _SessionPhaseInfo,
    ) -> str:
        """Build JSON prompt context used for LLM inference."""
        last_candle = candles[-1] if candles else None
        market_data_ai = self._build_market_data_ai(
            signal=signal,
            amt_result=amt_result,
            tick=last_candle,
            session_phase=session_phase,
            candles=candles,
        )
        return json.dumps(market_data_ai, default=str)

    def _build_episodic_memory(self) -> str:
        if self._storage is None:
            return ""
        try:
            trades = self._storage.get_recent_trades(5)
            if not isinstance(trades, list):
                return ""
            parts: list[str] = []
            for i, trade in enumerate(trades, start=1):
                if not isinstance(trade, dict):
                    continue
                side = str(trade.get("side", ""))
                pnl = float(trade.get("pnl", 0.0))
                reason = str(trade.get("reason", ""))
                sign = "+" if pnl >= 0 else ""
                parts.append(f"{i}) {side} {sign}Rs{pnl:.0f} ({reason})")
            return "; ".join(parts)
        except Exception:
            logger.debug("Failed to load episodic memory for LLM context", exc_info=True)
            return ""

    def _build_market_data_ai(
        self,
        signal: Signal,
        amt_result: AMTResult,
        tick,
        session_phase: _SessionPhaseInfo,
        candles: list[OHLC] | None = None,
    ) -> dict[str, object]:
        now = _to_ist_datetime(signal.timestamp)
        market_open = now.replace(
            hour=9,
            minute=(0 if session_phase.session_market == "MCX" else 15),
            second=0,
            microsecond=0,
        )
        if session_phase.session_market == "MCX":
            market_open = market_open.replace(minute=0)
            if now < market_open:
                market_open = market_open.replace(day=market_open.day - 1)

        session_elapsed_min = max(0.0, (now - market_open).total_seconds() / 60.0)
        market_data_ai: dict[str, object] = {
            "symbol": signal.symbol,
            "timestamp": signal.timestamp,
            "session": session_phase.session_name,
            "phase": session_phase.phase_int,
            "ltp": float(getattr(tick, "close", signal.entry)),
            "delta": float(getattr(tick, "delta", 0.0)),
            "volume": float(getattr(tick, "volume", 0.0)),
            "vah": float(getattr(amt_result, "value_area_high", 0.0)),
            "val": float(getattr(amt_result, "value_area_low", 0.0)),
            "poc": float(getattr(amt_result, "poc", 0.0)),
            "market_state": str(getattr(amt_result, "market_state", "")),
            "aggression": float(getattr(amt_result, "aggression", 0.0)),
            "cvd_slope": float(getattr(amt_result, "cvd_slope", 0.0)),
            "strategy_hint": self._build_strategy_hint(
                amt_result=amt_result,
                session_info=session_phase,
                symbol=signal.symbol,
            ),
            "session_elapsed_minutes": round(float(session_elapsed_min), 2),
            "session_market": session_phase.session_market,
            "session_phase": session_phase.phase_int,
            "signal": {
                "type": signal.type,
                "entry": signal.entry,
                "sl": signal.sl,
                "tp": signal.tp,
                "rr": signal.rr,
                "confidence": signal.confidence,
                "reason": signal.reason,
                "source": getattr(signal, "source", ""),
            },
            "amt": {
                "market_state": str(getattr(amt_result, "market_state", "")),
                "value_area_high": float(getattr(amt_result, "value_area_high", 0.0)),
                "value_area_low": float(getattr(amt_result, "value_area_low", 0.0)),
                "poc": float(getattr(amt_result, "poc", 0.0)),
                "aggression": float(getattr(amt_result, "aggression", 0.0)),
                "cvd_slope": float(getattr(amt_result, "cvd_slope", 0.0)),
                "session_vwap": float(getattr(amt_result, "session_vwap", 0.0)),
                "vwap_upper_2": float(getattr(amt_result, "vwap_upper_2", 0.0)),
                "shape": str(getattr(amt_result, "profile_shape", "")),
                "profile_type": str(getattr(amt_result, "profile_type", "Session")),
                "market_structure": str(getattr(amt_result, "market_structure", "")),
                "opening_bias": str(getattr(amt_result, "opening_bias", "")),
                "gap_type": str(getattr(amt_result, "gap_type", "")),
                "option_type": self._detect_option_type(signal.symbol or ""),
            },
            "profile_description": self._build_profile_description(amt_result),
            "volume_bubble_summary": self._build_volume_bubble_summary(amt_result, tick),
            "imbalance_summary": self._build_imbalance_summary(type("S", (), {"_last_fp_domain": None})()),
            "gate_context": self._build_gate_context(
                amt_result=amt_result,
                tick=tick,
                session=None,
                session_info=session_phase,
                agg_levels=[],
                fp_domain=None,
            ),
            "session_elapsed_min": round(float(session_elapsed_min), 2),
            "session_market": session_phase.session_market,
            "session_state": "BASIC",
            "session_info": str(session_phase),
            "amt_time_window": self._get_amt_time_window(now),
            "episodic_memory": self._load_episodic_memory(),
            "candles": [
                {
                    "time": str(getattr(candle, "time", "")),
                    "open": float(getattr(candle, "open", 0.0)),
                    "high": float(getattr(candle, "high", 0.0)),
                    "low": float(getattr(candle, "low", 0.0)),
                    "close": float(getattr(candle, "close", 0.0)),
                    "volume": float(getattr(candle, "volume", 0.0)),
                    "delta": float(getattr(candle, "delta", 0.0)),
                }
                for candle in (candles or [])
            ],
        }
        self._enrich_market_context(market_data_ai, amt_result)
        return market_data_ai

    @staticmethod
    def _derive_strategy_hint(
        signal: Signal,
        session_phase: _SessionPhaseInfo,
        amt_result: AMTResult,
    ) -> str:
        hint = ""
        if session_phase.session_market == "NSE":
            if session_phase.allow_trend:
                hint = "Trend continuation mode is preferred."
            else:
                hint = "Mean-reversion mode only."
        else:
            if session_phase.allow_trend:
                hint = "MCX trend continuation mode is active."
            else:
                hint = "MCX mean-reversion mode only."

        if str(getattr(amt_result, "profile_shape", "")).upper() == "P":
            hint += " P-shape profile detected."
        elif str(getattr(amt_result, "profile_shape", "")).upper() == "B":
            hint += " B-shape profile detected."
        elif str(getattr(amt_result, "profile_shape", "")).upper() in {"", "D"}:
            hint += " Balanced profile."

        if signal.type == "LONG":
            hint += " Existing signal is LONG."
        elif signal.type == "SHORT":
            hint += " Existing signal is SHORT."
        else:
            hint += " Existing signal is NO_TRADE."

        return hint.strip()

    def _save_llm_decision(
        self,
        symbol: str,
        decision: LLMDecision,
        amt_result: AMTResult,
        candles: list[OHLC],
    ) -> None:
        if self._storage is None:
            return
        last_candle = candles[-1] if candles else None
        ltp = float(last_candle.close) if last_candle is not None else 0.0
        self._last_direction[symbol] = decision.direction
        self._last_confidence[symbol] = decision.confidence
        try:
            self._storage.save_llm_decision({
                "symbol": symbol,
                "direction": decision.direction,
                "confidence": decision.confidence,
                "rationale": decision.rationale,
                "input_prompt": decision.input_prompt,
                "raw_output": decision.raw_output,
                "market_state": decision.market_state,
                "aggression": str(getattr(amt_result, "aggression", 0.0)),
                "tick_trace_id": decision.tick_trace_id,
                "price": ltp,
                "vah": float(getattr(amt_result, "value_area_high", 0.0)),
                "val": float(getattr(amt_result, "value_area_low", 0.0)),
                "poc": float(getattr(amt_result, "poc", 0.0)),
                "delta": float(getattr(last_candle, "delta", 0.0)) if last_candle is not None else 0.0,
                "volume": float(getattr(last_candle, "volume", 0.0)) if last_candle is not None else 0.0,
                "profile_shape": str(getattr(amt_result, "profile_shape", "")),
                "extra": {},
            })
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
