"""LLM Entry Handler — LLM inference coordination with delegated gate/signal logic.

This module coordinates LLM inference and delegates to specialized modules:
- EntryGateCoordinator: Gate checking orchestration
- SignalConstructor: Signal building logic
- PositionSizer: Position sizing logic
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from dataclasses import replace as _replace
from datetime import datetime, timedelta, timezone
import queue
from typing import TYPE_CHECKING, Callable, Optional

from app.domain.trading.models.enums import (
    MarketStateCodec,
    SignalType,
    Source,
    SetupType,
)
from app.domain.trading.models.entities import Signal
from app.config import settings
from app.domain.fabio_ai.services.regime_detector import RegimeDetector
from app.domain.fabio_ai.services.trade_manager import TradeManager
from app.domain.trading.events import AIAnalysisCompleted, SignalGenerated
from app.domain.fabio_ai.services.session_context import get_session_info
from app.domain.fabio_ai.services.entry_gate import (
    build_entry_signal,
    cluster_aggressive_prints,
)

# Import delegated modules
from app.application.handlers.entry_gate_coordinator import EntryGateCoordinator
from app.application.handlers.signal_constructor import SignalConstructor
from app.application.handlers.position_sizer import PositionSizer

# Import error handling utilities
from shared.error_handling import (
    handle_errors,
    safe_execute,
    ErrorContext,
    LLMError,
    SignalError,
)

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, AMTResult
    from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService
    from app.domain.ports.event_bus import EventBusPort
    from app.domain.ports.storage import StoragePort

logger = logging.getLogger(__name__)


class LLMEntryHandler:
    """Handles LLM-based entry decisions with delegated gate/signal logic."""

    def __init__(
        self,
        gen_ai_service: GenerativeAIService,
        event_bus: EventBusPort,
        storage: StoragePort | None = None,
        trade_manager: TradeManager | None = None,
        journal=None,
        exchange: str = "MCX",
        allow_short: bool = False,
        llm_timeout: float = 15.0,
    ) -> None:
        self._gen_ai_service = gen_ai_service
        self._event_bus = event_bus
        self._storage = storage
        self._trade_manager = trade_manager
        self._journal = journal
        self._exchange = exchange
        self._allow_short = allow_short  # Use injected allow_short
        self._llm_timeout = llm_timeout
        self._regime_detectors: dict[str, RegimeDetector] = {}
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self._predict_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        # Per-symbol workers for parallel LLM inference across symbols
        # Bounded queue (10) per symbol prevents regime-change storms
        self._llm_queues: dict[str, queue.Queue] = {}
        self._worker_threads: dict[str, threading.Thread] = {}
        self._workers_lock = threading.Lock()

        # Delegated modules
        self._gate_coordinator = EntryGateCoordinator()
        self._signal_constructor = SignalConstructor()
        self._position_sizer = PositionSizer()

    def _get_regime_detector(self, symbol: str) -> RegimeDetector:
        """Return per-symbol RegimeDetector, creating one if needed."""
        det = self._regime_detectors.get(symbol)
        if det is not None:
            return det
        with self._workers_lock:
            if symbol not in self._regime_detectors:
                self._regime_detectors[symbol] = RegimeDetector()
            return self._regime_detectors[symbol]

    def should_run(
        self,
        last_ai_time: float,
        ai_running: bool,
        has_position: bool,
        has_managed_positions: bool,
        in_cooldown: bool,
        last_entry_time: float = 0,
        data: list | None = None,
        amt_result: AMTResult | None = None,
        tick: OHLC | None = None,
        order_book=None,
    ) -> bool:
        """Check if LLM entry logic should run."""
        import time as _time

        # Guard against degenerate AMT data
        if amt_result.poc <= 0 or amt_result.value_area_high <= 0:
            logger.debug(
                "LLM blocked: degenerate AMT (poc=%.1f vah=%.1f)",
                amt_result.poc,
                amt_result.value_area_high,
            )
            return False

        if ai_running:
            return False

        # Only block if THIS specific symbol already has an open position
        if has_position:
            logger.debug("LLM blocked: symbol already has an open position")
            return False

        # Don't call until model is loaded
        if not self._gen_ai_service.is_ready():
            logger.info(
                "LLM blocked: model not ready (is_loading=%s)",
                not self._gen_ai_service.is_ready(),
            )
            return False

        # Simple 10s cooldown between LLM calls
        elapsed = _time.time() - last_ai_time
        if elapsed < 10:
            return False

        return True

    def run_entry(
        self,
        session,
        symbol: str,
        tick: OHLC,
        amt_result: AMTResult,
    ) -> None:
        """Run LLM entry analysis in background thread."""
        with session._lock:
            session._last_ai_time = time.time()
            session._ai_running = True

        market_state_str = (
            "Trending"
            if MarketStateCodec.is_imbalanced(amt_result.market_state)
            else "Balanced"
        )

        # Session-aware setup bias
        prior = getattr(session, "_prior_profile", None)
        prior_vah = prior.get("vah", 0) if prior else 0
        prior_val = prior.get("val", 0) if prior else 0
        open_price = session.data[0].open if session.data else 0
        _market = self._exchange
        if _market in ("NFO", "BSE"):
            _market = "NSE"
        session_info = get_session_info(
            timestamp=tick.time,
            market=_market,
            open_price=open_price,
            prior_vah=prior_vah,
            prior_val=prior_val,
        )

        # Build session context for LLM
        session_context_for_llm = ""
        if not session_info.allow_entry:
            logger.info("SESSION GATE: Phase %s blocks entries — skipping LLM for %s", session_info.session, symbol)
            
            ai_result = {
                "direction": "FLAT",
                "rationale": f"Market in {session_info.session} phase. Entries are blocked by Session Gate.",
                "confidence": "High",
                "input_prompt": "",
                "raw_output": "QUANT_PHASE_BLOCKED",
                "market_state": market_state_str,
            }
            
            with session._lock:
                session.last_ai_analysis = ai_result
                session._ai_running = False
                
            if self._storage:
                try:
                    self._storage.save_llm_decision({
                        "symbol": symbol,
                        "direction": "FLAT",
                        "confidence": "High",
                        "rationale": ai_result["rationale"],
                        "input_prompt": "",
                        "raw_output": "QUANT_PHASE_BLOCKED",
                        "market_state": market_state_str,
                        "aggression": f"{amt_result.aggression:.4f}",
                        "price": tick.close,
                        "vah": amt_result.value_area_high,
                        "val": amt_result.value_area_low,
                        "poc": amt_result.poc,
                        "delta": tick.delta,
                        "volume": tick.volume,
                        "profile_shape": getattr(amt_result, "profile_shape", ""),
                        "setup_type": "SESSION_BLOCK",
                        "strategy_hint": "",
                    })
                except Exception:
                    pass
            return

        if session_info.allow_trend:
            session_context_for_llm += "Trend setups allowed. "
        else:
            session_context_for_llm += "Mean-reversion only. "

        # Delegate gate checking to EntryGateCoordinator
        agg_levels = cluster_aggressive_prints(amt_result.aggressive_prints)
        prior_prints = getattr(session, "_prior_print_levels", [])
        all_structural_levels = agg_levels + prior_prints
        fp_domain = getattr(session, "_last_fp_domain", None)

        # Check gates using delegated coordinator
        gate_passed, gate_reason, is_second_drive = (
            self._gate_coordinator.check_entry_eligibility(
                data=session.data,
                amt_result=amt_result,
                tick=tick,
                order_book=session.order_book,
                direction="LONG",  # Default, will be overridden by LLM
                aggressive_levels=all_structural_levels,
                footprint_domain=fp_domain,
                session_info=session_info,
            )
        )

        # Build gate context for LLM
        three_align_context = ""
        if not gate_passed:
            three_align_context = (
                f"[GATE WARNING] Three-Align NOT MET: "
                f"Market state: {amt_result.market_state}, "
                f"Price: {tick.close:.1f}, POC: {amt_result.poc:.1f}, "
                f"VAH: {amt_result.value_area_high:.1f}, VAL: {amt_result.value_area_low:.1f}. "
                f"You must have STRONG conviction to override. "
            )

        gate_context = session_context_for_llm + three_align_context

        # Determine setup type
        if (
            MarketStateCodec.is_imbalanced(amt_result.market_state)
            and session_info.allow_trend
        ):
            setup_type = SetupType.TREND_MODEL
            strategy_hint = "Market is IMBALANCED (trending). Favor trend continuation setups. Look for breakouts beyond VA boundaries."
        elif (
            MarketStateCodec.is_imbalanced(amt_result.market_state)
            and not session_info.allow_trend
        ):
            setup_type = SetupType.MEAN_REVERSION
            strategy_hint = "Market is IMBALANCED but session phase favors mean reversion only. Look for fades at VA extremes back toward POC."
        else:
            setup_type = SetupType.MEAN_REVERSION
            strategy_hint = "Market is BALANCED (range-bound). Favor mean reversion setups. Look for fades at VA extremes back toward POC."

        # Add session context to strategy hint
        session_hints = {
            "NSE_PRIMARY": "[Primary Setup Window 09:30-11:30 — best window for AAA setups.]",
            "NSE_MIDDAY": "[Midday Consolidation 11:30-14:00 — mean reversion only, no new trend trades.]",
            "NSE_POWER_HOUR": "[Power Hour 14:00-15:15 — second-best window for AAA setups.]",
        }
        hint = session_hints.get(session_info.session, "")
        if hint:
            strategy_hint += f" {hint}"

        # Contraction advisory
        if session.data and self._get_regime_detector(symbol).is_contracting(
            session.data
        ):
            strategy_hint += " [CAUTION: Market is contracting after expansion — prefer Stay Flat or mean reversion only.]"

        # Profile shape
        profile_shape_str = ""
        if amt_result.profile_shape:
            shape_descriptions = {
                "D": "D-shape (balanced, rotational)",
                "P": "P-shape (top-heavy, sellers may be trapped)",
                "b": "b-shape (bottom-heavy, buying absorption)",
                "B": "B-shape (bimodal, two value areas — potential breakout)",
            }
            profile_shape_str = shape_descriptions.get(amt_result.profile_shape, "")

        # Volume bubble summary
        volume_bubble_desc = ""
        if amt_result.aggressive_prints:
            try:
                if (
                    tick.time.replace(".", "", 1)
                    .replace("-", "")
                    .replace("+", "")
                    .isdigit()
                ):
                    cutoff_dt = datetime.fromtimestamp(float(tick.time)) - timedelta(
                        seconds=3000
                    )
                else:
                    cutoff_dt = datetime.fromisoformat(
                        tick.time.replace("Z", "+00:00")
                    ) - timedelta(seconds=3000)
            except (ValueError, OSError):
                cutoff_dt = datetime.now() - timedelta(seconds=3000)
            cutoff_time = cutoff_dt.isoformat()
            recent_prints = [
                ap for ap in amt_result.aggressive_prints if ap.time >= cutoff_time
            ][-3:]
            bubble_parts = []
            for ap in recent_prints:
                bubble_parts.append(
                    f"{ap.side} bubble at {ap.price:.0f} ({ap.volume:.0f} vol, delta {ap.delta:+.0f})"
                )
            volume_bubble_desc = "; ".join(bubble_parts)

        # Stacked imbalances from footprint
        imbalance_desc = ""
        fp_domain = getattr(session, "_last_fp_domain", None)
        if fp_domain:
            try:
                fp_vals = (
                    list(fp_domain.values()) if isinstance(fp_domain, dict) else None
                )
                latest_fp = fp_vals[-1] if fp_vals else None
                if latest_fp and hasattr(latest_fp, "levels"):
                    stacked = [
                        lv for lv in latest_fp.levels if getattr(lv, "stacked", False)
                    ]
                    if stacked:
                        parts = []
                        for lv in stacked[:3]:
                            side = getattr(
                                lv, "direction", getattr(lv, "side", "UNKNOWN")
                            )
                            price = getattr(lv, "price", 0)
                            parts.append(f"{side} imbalance at {price:.0f}")
                        imbalance_desc = "STACKED IMBALANCES: " + ", ".join(parts)
            except Exception:
                logger.debug("Exception handled silently", exc_info=True)

        # Episodic memory
        episodic_memory = ""
        if self._storage:
            try:
                _ist = timezone(timedelta(hours=5, minutes=30))
                _today = datetime.now(_ist).strftime("%Y-%m-%d")
                recent_trades = self._storage.get_recent_trades(limit=10)
                if recent_trades:
                    today_trades = [
                        t for t in recent_trades if _today in str(t.get("time", ""))
                    ]
                    if not today_trades:
                        today_trades = recent_trades[:5]
                    parts = []
                    session_pnl = 0.0
                    for i, t in enumerate(today_trades, 1):
                        side = t.get("side", "?")
                        pnl = t.get("pnl", 0)
                        reason = t.get("reason", "")
                        session_pnl += pnl
                        sign = "+" if pnl >= 0 else ""
                        parts.append(f"{i}) {side} {sign}Rs{pnl:.0f} ({reason})")
                    pnl_sign = "+" if session_pnl >= 0 else ""
                    episodic_memory = (
                        f"Session P&L: {pnl_sign}Rs{session_pnl:.0f} ({len(today_trades)} trades). "
                        + ", ".join(parts)
                        + "."
                    )
            except Exception:
                logger.debug("Failed to load episodic memory", exc_info=True)

        # QUANT ENGINE GATE
        agent_decision = getattr(session, "_agent_decision", None)

        if agent_decision:
            agent_regime = getattr(agent_decision, "regime", "")
            if agent_regime == "DEAD":
                logger.info(
                    "QUANT GATE: Market regime=DEAD (no volume) — skipping LLM for %s",
                    symbol,
                )
                # Override timing to SKIP — dead market cannot have entries
                agent_decision = _replace(agent_decision, timing="SKIP")
                ai_result = {
                    "direction": "FLAT",
                    "rationale": "DEAD market: volume < 5% of average. No trade.",
                    "confidence": "High",
                    "input_prompt": "",
                    "raw_output": "QUANT_DEAD_MARKET",
                    "market_state": market_state_str,
                }
                direction = "FLAT"
                confidence = "High"
                with session._lock:
                    session.last_ai_analysis = ai_result
                return

            if agent_decision.direction == "FLAT":
                agent_prob = getattr(agent_decision, "probability", 0.5)
                if abs(agent_prob - 0.5) < 0.10:
                    logger.info(
                        "QUANT GATE: Engine says FLAT (P=%.3f, no edge) — skipping LLM for %s",
                        agent_prob,
                        symbol,
                    )
                    # Override timing to SKIP — FLAT with no edge cannot have ENTER_NOW
                    agent_decision = _replace(agent_decision, timing="SKIP")
                    ai_result = {
                        "direction": "FLAT",
                        "rationale": f"No quant edge: P={agent_prob:.3f} near 50/50. Wait for clearer setup.",
                        "confidence": "High",
                        "input_prompt": "",
                        "raw_output": "QUANT_FLAT_NO_EDGE",
                        "market_state": market_state_str,
                    }
                    direction = "FLAT"
                    confidence = "High"
                    with session._lock:
                        session.last_ai_analysis = ai_result
                    return

        # Build market data for LLM
        market_data_ai = {
            "ltp": tick.close,
            "delta": tick.delta,
            "volume": tick.volume,
            "vah": amt_result.value_area_high,
            "val": amt_result.value_area_low,
            "poc": amt_result.poc,
            "market_state": market_state_str,
            "aggression": f"Aggression Score: {amt_result.aggression:.2f}",
            "profile_shape": profile_shape_str,
            "strategy_hint": strategy_hint,
            "volume_bubbles": volume_bubble_desc,
            "stacked_imbalances": imbalance_desc,
            "hvns": amt_result.hvns[:3] if amt_result.hvns else (),
            "lvns": amt_result.lvns[:3] if amt_result.lvns else (),
            "cvd_slope": amt_result.cvd_slope,
            "cvd_divergence": amt_result.cvd_divergence,
            "vwap": amt_result.session_vwap
            if amt_result.session_vwap > 0
            else tick.vwap,
            "leg_poc": amt_result.leg_poc,
            "leg_lvns": amt_result.leg_lvns[:3] if amt_result.leg_lvns else (),
            "opening_relation": session_info.opening_relation,
            "market_structure": amt_result.market_structure,
            "structure_confidence": amt_result.structure_confidence,
            "balance_ratio": amt_result.balance_ratio,
            "episodic_memory": episodic_memory,
            "gate_context": gate_context,
            "ib_high": amt_result.ib_high,
            "ib_low": amt_result.ib_low,
            "ib_complete": amt_result.ib_complete,
            "prior_poc": amt_result.prior_poc,
            "prior_vah": amt_result.prior_vah,
            "prior_val": amt_result.prior_val,
            "gap_type": amt_result.gap_type,
            "opening_bias": amt_result.opening_bias,
            "acceptance_above": amt_result.acceptance_above,
            "acceptance_below": amt_result.acceptance_below,
            "rejection_at_high": amt_result.rejection_at_high,
            "rejection_at_low": amt_result.rejection_at_low,
            "price_velocity": amt_result.price_velocity,
            "break_direction": amt_result.break_direction,
            "break_type": amt_result.break_type,
            "break_level": amt_result.break_level,
            "poc_signal": amt_result.poc_signal,
            "poc_vs_price": amt_result.poc_vs_price,
            "lvn_play": amt_result.lvn_play,
            "is_second_drive": is_second_drive,
        }

        # ML signal for LLM meta-filter
        agent = getattr(session, "_agent_decision", None)
        if agent and agent.direction != "FLAT":
            market_data_ai["ml_signal"] = {
                "direction": agent.direction,
                "probability": agent.probability,
                "regime": agent.regime,
            }

        # Ensure per-symbol queue and worker exist
        with self._workers_lock:
            if symbol not in self._llm_queues:
                self._llm_queues[symbol] = queue.Queue(maxsize=10)
                wt = threading.Thread(
                    target=self._llm_worker_loop,
                    args=(symbol,),
                    daemon=True,
                    name=f"LLM-Worker-{symbol}",
                )
                self._worker_threads[symbol] = wt
                wt.start()

        # Enqueue the job for the dedicated LLM worker thread
        item = {
            "session": session,
            "symbol": symbol,
            "tick": tick,
            "amt_result": amt_result,
            "market_data_ai": market_data_ai,
            "setup_type": setup_type,
            "session_info": session_info,
            "strategy_hint": strategy_hint,
            "profile_shape_str": profile_shape_str,
            "market_state_str": market_state_str,
            "enqueue_time": time.time(),
        }
        try:
            self._llm_queues[symbol].put_nowait(item)
            logger.debug(
                f"Queued LLM analysis for {symbol} (Queue size: {self._llm_queues[symbol].qsize()})"
            )
        except queue.Full:
            logger.warning(f"LLM Queue full, dropping analysis for {symbol}")
            with session._lock:
                session._ai_running = False

    def _llm_worker_loop(self, queue_symbol: str) -> None:
        """Dedicated background thread that processes LLM requests sequentially for a specific symbol."""

        with self._workers_lock:
            worker_queue = self._llm_queues.get(queue_symbol)

        if not worker_queue:
            logger.error(f"Worker for {queue_symbol} started but no queue found!")
            return

        while True:
            try:
                item = worker_queue.get()
                if item is None:
                    break

                enqueue_time = item["enqueue_time"]
                session = item["session"]
                symbol = item["symbol"]
                tick = item["tick"]
                amt_result = item["amt_result"]
                market_data_ai = item["market_data_ai"]
                setup_type = item["setup_type"]
                session_info = item["session_info"]
                strategy_hint = item["strategy_hint"]
                profile_shape_str = item["profile_shape_str"]
                market_state_str = item["market_state_str"]

                # Staleness check
                if time.time() - enqueue_time > 30.0:
                    logger.warning(
                        f"Dropping stale LLM request for {symbol} (queued {time.time() - enqueue_time:.1f}s ago)"
                    )
                    with session._lock:
                        session._ai_running = False
                    worker_queue.task_done()
                    continue

                if not self._gen_ai_service.is_ready():
                    with session._lock:
                        session.last_ai_analysis = {
                            "direction": "FLAT",
                            "rationale": "Model loading...",
                            "confidence": "Low",
                        }
                        session._ai_running = False
                    worker_queue.task_done()
                    continue

                # Add context flags to market_data_ai
                if amt_result.aggression < 1.0:
                    market_data_ai["aggression_warning"] = (
                        "Weak aggression — higher risk"
                    )
                if amt_result.market_state == "IMBALANCED":
                    market_data_ai["drive_warning"] = (
                        "First drive — wait for second if possible"
                    )
                if abs(amt_result.cvd_slope) > 50:
                    market_data_ai["cvd_warning"] = (
                        f"Extreme CVD ({amt_result.cvd_slope:.0f}) — respect institutional pressure"
                    )

                # Update LTP to use the absolute latest tick to avoid stale context during inference delay
                try:
                    if session.data:
                        market_data_ai["ltp"] = session.data[-1].close
                except Exception:
                    pass

                # Call LLM
                try:
                    is_extreme_volatility = (
                        amt_result.market_structure == "EXPANSION"
                        or amt_result.price_velocity > 5.0
                    )

                    fallback_direction = "FLAT"
                    _ml_dir = getattr(session, "_agent_decision", None)
                    if _ml_dir and _ml_dir.direction != "FLAT":
                        fallback_direction = _ml_dir.direction
                    elif amt_result.signal:
                        fallback_direction = (
                            "LONG"
                            if amt_result.signal.type == SignalType.BUY
                            else "SHORT"
                        )

                    if is_extreme_volatility and fallback_direction != "FLAT":
                        logger.warning(
                            f"Extreme volatility detected. Bypassing LLM. Using: {fallback_direction}"
                        )
                        ai_result = {
                            "direction": fallback_direction,
                            "rationale": "Volatility bypass — quant signal",
                            "confidence": "High",
                            "input_prompt": "",
                            "raw_output": "QUANT_FALLBACK",
                            "market_state": market_state_str,
                        }
                    else:
                        predict_future = self._predict_executor.submit(
                            self._gen_ai_service.analyze_market,
                            market_data_ai,
                        )
                        ai_result = predict_future.result(timeout=self._llm_timeout)
                except concurrent.futures.TimeoutError:
                    predict_future.cancel()
                    logger.warning(
                        "LLM timed out after %.0fs — using fallback",
                        self._llm_timeout,
                    )
                    if fallback_direction != "FLAT":
                        ai_result = {
                            "direction": fallback_direction,
                            "rationale": "Timeout fallback — quant signal",
                            "confidence": "Medium",
                            "input_prompt": "",
                            "raw_output": "TIMEOUT_FALLBACK",
                            "market_state": market_state_str,
                        }
                    else:
                        with session._lock:
                            session._ai_running = False
                        worker_queue.task_done()
                        continue
                except Exception as e:
                    logger.error(f"LLM inference exception: {e}", exc_info=True)
                    with session._lock:
                        session._ai_running = False
                    worker_queue.task_done()
                    continue

                direction = ai_result["direction"]
                confidence = ai_result.get("confidence", "Medium")
                rationale = ai_result.get("rationale", "")

                # SAFETY NETS ONLY
                if direction == "SHORT" and not self._allow_short:
                    logger.info("BUY-ONLY mode: SHORT blocked → FLAT")
                    direction = "FLAT"
                    rationale = "System in BUY-ONLY mode"

                # VWAP EXTREME check
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
                    confidence = "Low"
                    rationale += " [VWAP extreme: >+2σ]"

                confidence = ai_result.get(
                    "confidence", "High" if direction != "FLAT" else "Medium"
                )
                logger.info(
                    "LLM result: direction=%s confidence=%s", direction, confidence
                )

                # Journal logging
                if self._journal:
                    try:
                        _agent = getattr(session, "_agent_decision", None)
                        self._journal.log_signal(
                            symbol=symbol,
                            amt=session.last_amt,
                            llm_direction=direction,
                            llm_confidence=confidence,
                            llm_rationale=ai_result.get("rationale", ""),
                            agent_direction=_agent.direction if _agent else "",
                            agent_regime=_agent.regime if _agent else "",
                            agent_feature_drivers=getattr(_agent, "feature_drivers", ())
                            if _agent
                            else (),
                            probability_long=_agent.probability
                            if _agent and _agent.direction == "LONG"
                            else 0,
                            probability_short=_agent.probability
                            if _agent and _agent.direction == "SHORT"
                            else 0,
                            decision_source="llm",
                            attribution=(
                                "llm_plus_quant_agree"
                                if _agent
                                and _agent.direction == direction
                                and direction != "FLAT"
                                else (
                                    "llm_override_quant"
                                    if _agent
                                    and _agent.direction not in ("", "FLAT", direction)
                                    else "llm_only"
                                )
                            ),
                        )
                    except Exception:
                        logger.debug("Journal log_signal failed", exc_info=True)

                # Use delegated modules for gate checking and signal construction
                if direction in ("LONG", "SHORT"):
                    # Delegate gate checking
                    gate_passed, gate_reason, is_second_drive = (
                        self._gate_coordinator.check_entry_eligibility(
                            data=session.data,
                            amt_result=amt_result,
                            tick=tick,
                            order_book=session.order_book,
                            direction=direction,
                            session_info=session_info,
                        )
                    )

                    if not gate_passed:
                        logger.info(
                            "Gate check failed for %s: %s", direction, gate_reason
                        )
                        if self._journal:
                            self._journal.log_rejection(
                                symbol=symbol,
                                reason=gate_reason,
                                amt=session.last_amt,
                                llm_direction=direction,
                            )
                        direction = "FLAT"

                # Save LLM decision
                with session._lock:
                    # Include quant engine probability for Monitor panel consistency
                    _agent = getattr(session, "_agent_decision", None)
                    _quant_p = _agent.probability if _agent else 0.0
                    _quant_dir = _agent.direction if _agent else ""
                    session.last_ai_analysis = {
                        "direction": direction,
                        "rationale": ai_result["rationale"],
                        "confidence": confidence,
                        "input_prompt": ai_result.get("input_prompt", ""),
                        "raw_output": ai_result.get("raw_output", ""),
                        "market_state": ai_result.get("market_state", "Unknown"),
                        "aggression": ai_result.get("aggression", "0.00"),
                        "quant_probability": round(_quant_p, 3),
                        "quant_direction": _quant_dir,
                    }

                # Persist LLM decision
                if self._storage:
                    try:
                        self._storage.save_llm_decision(
                            {
                                "symbol": symbol,
                                "direction": direction,
                                "confidence": confidence,
                                "rationale": ai_result["rationale"],
                                "input_prompt": ai_result.get("input_prompt", ""),
                                "raw_output": ai_result.get("raw_output", ""),
                                "market_state": market_state_str,
                                "aggression": f"{amt_result.aggression:.4f}",
                                "price": tick.close,
                                "vah": amt_result.value_area_high,
                                "val": amt_result.value_area_low,
                                "poc": amt_result.poc,
                                "delta": tick.delta,
                                "volume": tick.volume,
                                "profile_shape": profile_shape_str,
                                "setup_type": setup_type.value,
                                "strategy_hint": strategy_hint,
                            }
                        )
                    except Exception:
                        logger.debug("Exception handled silently", exc_info=True)

                # Build signal using delegated SignalConstructor
                if direction in ("LONG", "SHORT"):
                    _ad = getattr(session, "_agent_decision", None)
                    if (
                        _ad
                        and _ad.direction in ("LONG", "SHORT")
                        and _ad.direction != direction
                    ):
                        if self._journal:
                            self._journal.log_rejection(
                                symbol=symbol,
                                reason="AGENT_DIRECTION_MISMATCH",
                                amt=session.last_amt,
                                llm_direction=direction,
                            )
                        with session._lock:
                            session._ai_running = False
                        worker_queue.task_done()
                        continue

                    with session._lock:
                        live_positions = [
                            p for p in session.portfolio.positions if p.status == "OPEN"
                        ]
                        if not live_positions:
                            _det = self._get_regime_detector(symbol)
                            if _det.is_circuit_breaker_active():
                                logger.info(
                                    "Circuit breaker blocked %s entry for %s",
                                    direction,
                                    symbol,
                                )
                                if self._journal:
                                    self._journal.log_rejection(
                                        symbol=symbol,
                                        reason="CIRCUIT_BREAKER",
                                        amt=session.last_amt,
                                        llm_direction=direction,
                                    )
                            else:
                                _squeeze = _det.detect_squeeze(session.data, amt_result)
                                from app.domain.fabio_ai.services.entry_gate import (
                                    compute_atr,
                                )

                                _atr = compute_atr(session.data, 14)
                                if _det.is_re_entry_blocked(
                                    tick.close,
                                    direction,
                                    session_info.phase,
                                    squeeze_active=bool(
                                        _squeeze and _squeeze.direction == direction
                                    ),
                                    atr=_atr,
                                ):
                                    if self._journal:
                                        self._journal.log_rejection(
                                            symbol=symbol,
                                            reason="RE_ENTRY_BLOCKED",
                                            amt=session.last_amt,
                                            llm_direction=direction,
                                        )
                                else:
                                    _risk_mgr = getattr(
                                        session, "_session_risk_manager", None
                                    )
                                    if _risk_mgr and not _risk_mgr.can_trade:
                                        logger.info(
                                            "Max trades per session cap reached (%d trades) — blocking entry",
                                            _risk_mgr.trade_count,
                                        )
                                        if self._journal:
                                            self._journal.log_rejection(
                                                symbol=symbol,
                                                reason="MAX_TRADES_CAP",
                                                amt=session.last_amt,
                                                llm_direction=direction,
                                            )
                                    else:
                                        _cushion_sl = (
                                            _risk_mgr.stop_loss_pct
                                            if _risk_mgr
                                            else None
                                        )

                                        # Delegate signal construction to SignalConstructor
                                        entry_signal = (
                                            self._signal_constructor.construct_signal(
                                                direction=direction,
                                                tick=tick,
                                                amt_result=amt_result,
                                                ai_result=ai_result,
                                                setup_type=setup_type,
                                                data=session.data,
                                                risk_sl_pct=_cushion_sl,
                                                session_context=session_info.session,
                                                confidence=confidence,
                                                inside_extreme=settings.SL_INSIDE_EXTREME,
                                            )
                                        )

                                        if (
                                            not entry_signal
                                            or not TradeManager.is_valid_rr(
                                                entry_signal.price,
                                                entry_signal.stop_loss,
                                                entry_signal.take_profit,
                                            )
                                        ):
                                            if self._journal:
                                                self._journal.log_rejection(
                                                    symbol=symbol,
                                                    reason="RR_FILTER",
                                                    amt=session.last_amt,
                                                    llm_direction=direction,
                                                )
                                        else:
                                            logger.info(
                                                "LLM inference complete — advisory-only signal for %s",
                                                symbol,
                                            )
                                            if self._journal:
                                                self._journal.log_rejection(
                                                    symbol=symbol,
                                                    reason="LLM_ADVISORY_ONLY",
                                                    amt=session.last_amt,
                                                    llm_direction=direction,
                                                    decision_source="llm",
                                                    attribution=(
                                                        "llm_plus_quant_agree"
                                                        if _ad
                                                        and _ad.direction == direction
                                                        and direction != "FLAT"
                                                        else (
                                                            "llm_override_quant"
                                                            if _ad
                                                            and _ad.direction
                                                            not in (
                                                                "",
                                                                "FLAT",
                                                                direction,
                                                            )
                                                            else "llm_only"
                                                        )
                                                    ),
                                                    trade_thesis=(
                                                        entry_signal.metadata or {}
                                                    ).get("trade_thesis"),
                                                )

                self._event_bus.publish(
                    AIAnalysisCompleted(
                        symbol=symbol,
                        direction=direction,
                        rationale=ai_result["rationale"],
                        confidence=confidence,
                    )
                )

                with session._lock:
                    session._ai_running = False

                worker_queue.task_done()

            except Exception as e:
                logger.error(f"Worker loop fatal error: {e}", exc_info=True)
                try:
                    if "session" in locals() and session:
                        with session._lock:
                            session._ai_running = False
                except Exception:
                    pass
                try:
                    worker_queue.task_done()
                except Exception:
                    pass

    def record_stop_out(
        self, level: float, direction: str, session_phase: int, symbol: str = ""
    ) -> None:
        """Record a stopped-out position so re-entry at the same level is blocked."""
        self._get_regime_detector(symbol).record_failed_entry(
            level, direction, session_phase
        )

    def record_successful_exit(self, symbol: str = "") -> None:
        """Reset consecutive stop counter on a profitable exit."""
        self._get_regime_detector(symbol).record_successful_exit()

    def clear_failed_entries(self, symbol: str = "") -> None:
        """Clear failed entry records — call on new session start."""
        if symbol:
            self._get_regime_detector(symbol).clear_failed_entries()
        else:
            with self._workers_lock:
                for det in self._regime_detectors.values():
                    det.clear_failed_entries()

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
