"""LLM Entry Handler — Three-Align gate + Confirmation Bundle + LLM decision."""

from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
import queue
from typing import TYPE_CHECKING, Callable, Optional

from app.domain.trading.models.enums import MarketStateCodec, SignalType, Source, SetupType
from app.domain.trading.models.entities import Signal
from app.config import settings
from app.domain.fabio_ai.services.regime_detector import RegimeDetector
from app.domain.fabio_ai.services.trade_manager import TradeManager
from app.domain.trading.events import AIAnalysisCompleted, SignalGenerated
from app.domain.fabio_ai.services.session_context import get_session_info
from app.domain.fabio_ai.services.entry_gate import (
    build_entry_signal,
    check_momentum_fade,
    check_vwap_bias,
    check_imbalance_alignment,
    three_align_check,
    cluster_aggressive_prints,
)
from app.domain.fabio_ai.services.footprint_analyzer import (
    detect_absorption,
    detect_contested_zone,
)

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, AMTResult
    from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService
    from app.domain.ports.event_bus import EventBusPort
    from app.domain.ports.storage import StoragePort

logger = logging.getLogger(__name__)


class LLMEntryHandler:
    """Handles LLM-based entry decisions with Fabio Playbook gates."""

    def __init__(
        self,
        gen_ai_service: GenerativeAIService,
        event_bus: EventBusPort,
        storage: StoragePort | None = None,
        trade_manager: TradeManager | None = None,
        journal=None,
    ) -> None:
        self._gen_ai_service = gen_ai_service
        self._event_bus = event_bus
        self._storage = storage
        self._trade_manager = trade_manager
        self._journal = journal
        self._regime_detectors: dict[str, RegimeDetector] = {}
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self._predict_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        # Per-symbol workers for parallel LLM inference across symbols
        # Bounded queue (10) per symbol prevents regime-change storms
        self._llm_queues: dict[str, queue.Queue] = {}
        self._worker_threads: dict[str, threading.Thread] = {}
        self._workers_lock = threading.Lock()

    def _get_regime_detector(self, symbol: str) -> RegimeDetector:
        """Return per-symbol RegimeDetector, creating one if needed.

        Uses double-checked locking: dict reads are atomic in CPython,
        so the fast path (detector already exists) needs no lock.
        """
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
        """Check if LLM entry logic should run — no gates, model decides freely."""
        import time as _time

        # Guard against degenerate AMT data (zero/negative levels)
        if amt_result.poc <= 0 or amt_result.value_area_high <= 0:
            logger.debug(
                "LLM blocked: degenerate AMT (poc=%.1f vah=%.1f)",
                amt_result.poc,
                amt_result.value_area_high,
            )
            return False

        if ai_running:
            return False  # already running, silent skip

        # Only block the LLM if THIS specific symbol already has an open position.
        # Global locks (has_managed_positions, in_cooldown, daily loss limits)
        # should only stop the EXECUTION layer, not the LLM analysis itself,
        # so the frontend UI can continue displaying real-time rationale.
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

        # logger.info("LLM entry ALLOWED — calling model (elapsed=%.1fs)", elapsed)
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
            "Trending" if MarketStateCodec.is_imbalanced(amt_result.market_state) else "Balanced"
        )

        # Session-aware setup bias (Fabio 5-phase IST structure for NSE)
        # Use prior session's VA for opening relation / gap analysis
        prior = getattr(session, "_prior_profile", None)
        prior_vah = prior.get("vah", 0) if prior else 0
        prior_val = prior.get("val", 0) if prior else 0
        open_price = session.data[0].open if session.data else 0
        from app.config import Settings

        _market = Settings().DEFAULT_EXCHANGE
        # Map NFO/BSE to NSE for session context (same trading hours)
        if _market in ("NFO", "BSE"):
            _market = "NSE"
        session_info = get_session_info(
            timestamp=tick.time,
            market=_market,
            open_price=open_price,
            prior_vah=prior_vah,
            prior_val=prior_val,
        )

        # Fabio Gap #1: Move gates INTO prompt as context, NOT hard blocks
        # The LLM sees all context and decides with conviction
        # Hard guardrails (circuit breaker, daily loss) run AFTER

        # Session phase context for LLM (instead of blocking)
        session_context_for_llm = ""
        if not session_info.allow_entry:
            session_context_for_llm += f"[WARNING] Current session phase: {session_info.session} — entries discouraged. "
        if session_info.allow_trend:
            session_context_for_llm += "Trend setups allowed. "
        else:
            session_context_for_llm += "Mean-reversion only. "

        # Three-Align context for LLM (instead of hard blocking)
        agg_levels = cluster_aggressive_prints(amt_result.aggressive_prints)
        prior_prints = getattr(session, "_prior_print_levels", [])
        all_structural_levels = agg_levels + prior_prints
        fp_domain = getattr(session, "_last_fp_domain", None)
        gate_passed, confirmation_strong, is_second_drive = three_align_check(
            session.data,
            amt_result,
            tick,
            aggressive_levels=all_structural_levels,
            footprint_domain=fp_domain,
            return_is_second_drive=True,
        )

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

        if MarketStateCodec.is_imbalanced(amt_result.market_state) and session_info.allow_trend:
            setup_type = SetupType.TREND_MODEL
            strategy_hint = "Market is IMBALANCED (trending). Favor trend continuation setups. Look for breakouts beyond VA boundaries."
        elif MarketStateCodec.is_imbalanced(amt_result.market_state) and not session_info.allow_trend:
            # Midday consolidation: force reversion even if imbalanced
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

        # Contraction advisory — inform model, let it decide
        if session.data and self._get_regime_detector(symbol).is_contracting(
            session.data
        ):
            strategy_hint += " [CAUTION: Market is contracting after expansion — prefer Stay Flat or mean reversion only.]"

        # Profile shape — read from AMTResult (already computed once in analyzer)
        profile_shape_str = ""
        if amt_result.profile_shape:
            shape_descriptions = {
                "D": "D-shape (balanced, rotational)",
                "P": "P-shape (top-heavy, sellers may be trapped)",
                "b": "b-shape (bottom-heavy, buying absorption)",
                "B": "B-shape (bimodal, two value areas — potential breakout)",
            }
            profile_shape_str = shape_descriptions.get(amt_result.profile_shape, "")

        # Volume bubble summary (aggressive prints = 2.5σ volume spikes)
        # Only include recent bubbles (last 10 candles) — stale prints mislead the model
        volume_bubble_desc = ""
        if amt_result.aggressive_prints:
            try:
                if (
                    tick.time.replace(".", "", 1)
                    .replace("-", "")
                    .replace("+", "")
                    .isdigit()
                ):
                    # Epoch timestamp (e.g. "1771832400.0")
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

        # Stacked imbalances from footprint (Gap #2)
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
                pass

        # Episodic memory — feed last 5 trade outcomes to the LLM prompt
        episodic_memory = ""
        if self._storage:
            try:
                _ist = timezone(timedelta(hours=5, minutes=30))
                _today = datetime.now(_ist).strftime("%Y-%m-%d")
                recent_trades = self._storage.get_recent_trades(limit=10)
                if recent_trades:
                    # Filter to today's session only
                    today_trades = [
                        t for t in recent_trades if _today in str(t.get("time", ""))
                    ]
                    if not today_trades:
                        today_trades = recent_trades[:5]  # fallback to last 5
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
            "vwap": (
                amt_result.session_vwap if amt_result.session_vwap > 0 else tick.vwap
            ),
            "leg_poc": amt_result.leg_poc,
            "leg_lvns": amt_result.leg_lvns[:3] if amt_result.leg_lvns else (),
            "opening_relation": session_info.opening_relation,
            "market_structure": amt_result.market_structure,
            "structure_confidence": amt_result.structure_confidence,
            "balance_ratio": amt_result.balance_ratio,
            "episodic_memory": episodic_memory,
            # Fabio Gap #1: Gate context as information, not hard blocks
            "gate_context": gate_context,
            # Phase 1: Session structure
            "ib_high": amt_result.ib_high,
            "ib_low": amt_result.ib_low,
            "ib_complete": amt_result.ib_complete,
            "prior_poc": amt_result.prior_poc,
            "prior_vah": amt_result.prior_vah,
            "prior_val": amt_result.prior_val,
            "gap_type": amt_result.gap_type,
            "opening_bias": amt_result.opening_bias,
            # Phase 2: Acceptance/Rejection
            "acceptance_above": amt_result.acceptance_above,
            "acceptance_below": amt_result.acceptance_below,
            "rejection_at_high": amt_result.rejection_at_high,
            "rejection_at_low": amt_result.rejection_at_low,
            "price_velocity": amt_result.price_velocity,
            # Phase 3: Break detection
            "break_direction": amt_result.break_direction,
            "break_type": amt_result.break_type,
            "break_level": amt_result.break_level,
            # Phase 4: POC migration + LVN play + Second drive
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
        # 30-second staleness timeout (if it sits in queue longer, it's dropped)
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
            "confirmation_strong": confirmation_strong,
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
        from app.config import settings as _settings

        with self._workers_lock:
            worker_queue = self._llm_queues.get(queue_symbol)

        if not worker_queue:
            logger.error(f"Worker for {queue_symbol} started but no queue found!")
            return

        while True:
            try:
                item = worker_queue.get()
                if item is None:
                    break  # shutdown signal

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

                # Staleness check: Drop if sitting in queue > 30 seconds
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

                logger.info(
                    "LLM inference starting for %s (price=%.2f, state=%s, setup=%s)",
                    symbol,
                    tick.close,
                    market_state_str,
                    setup_type.value,
                )

                try:
                    # 1. Volatility Fast-Track Check (Bypass LLM completely)
                    is_extreme_volatility = (
                        amt_result.market_structure == "EXPANSION"
                        or amt_result.price_velocity > 5.0
                    )

                    fallback_direction = "FLAT"
                    _ml_dir = getattr(session, "_agent_decision", None)
                    if _ml_dir and _ml_dir.direction != "FLAT":
                        fallback_direction = _ml_dir.direction
                    elif amt_result.signal:
                        from app.domain.trading.models.enums import SignalType

                        fallback_direction = (
                            "LONG"
                            if amt_result.signal.type == SignalType.BUY
                            else "SHORT"
                        )

                    if is_extreme_volatility and fallback_direction != "FLAT":
                        logger.warning(
                            f"Extreme volatility detected. Bypassing LLM execution. Using deterministic signal: {fallback_direction}"
                        )
                        ai_result = {
                            "direction": fallback_direction,
                            "rationale": "Deterministic Fallback due to Extreme Volatility (EXPANSION regime or high price velocity).",
                            "confidence": "High",
                            "input_prompt": "",
                            "raw_output": "QUANT_FALLBACK",
                            "market_state": market_state_str,
                            "aggression": f"{amt_result.aggression:.2f}",
                        }
                    else:
                        predict_future = self._predict_executor.submit(
                            self._gen_ai_service.analyze_market,
                            market_data_ai,
                        )
                        ai_result = predict_future.result(
                            timeout=_settings.LLM_TIMEOUT_SECONDS
                        )
                except concurrent.futures.TimeoutError:
                    predict_future.cancel()
                    logger.warning(
                        "Entry LLM timed out after %.0fs — attempting deterministic fallback",
                        _settings.LLM_TIMEOUT_SECONDS,
                    )
                    if fallback_direction != "FLAT":
                        logger.info(
                            f"Using deterministic fallback direction: {fallback_direction} due to LLM timeout."
                        )
                        ai_result = {
                            "direction": fallback_direction,
                            "rationale": "Deterministic Fallback due to LLM Timeout. Quant gates approved entry.",
                            "confidence": "Medium",
                            "input_prompt": "",
                            "raw_output": "QUANT_FALLBACK_TIMEOUT",
                            "market_state": market_state_str,
                            "aggression": f"{amt_result.aggression:.2f}",
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
                # BUY-only gate: block SHORT when ALLOW_SHORT=false
                if direction == "SHORT" and not _settings.ALLOW_SHORT:
                    logger.info("BUY-ONLY mode: SHORT blocked → FLAT")
                    direction = "FLAT"
                    ai_result["direction"] = "FLAT"
                # VWAP overextension gate — block entries at/beyond ±2σ bands
                if (
                    direction == "LONG"
                    and amt_result.vwap_upper_2 > 0
                    and tick.close >= amt_result.vwap_upper_2
                ):
                    logger.info(
                        "VWAP overextension gate: LONG blocked at/above +2σ (price=%.2f, band=%.2f)",
                        tick.close,
                        amt_result.vwap_upper_2,
                    )
                    direction = "FLAT"
                elif (
                    direction == "SHORT"
                    and amt_result.vwap_lower_2 > 0
                    and tick.close <= amt_result.vwap_lower_2
                ):
                    logger.info(
                        "VWAP overextension gate: SHORT blocked at/below -2σ (price=%.2f, band=%.2f)",
                        tick.close,
                        amt_result.vwap_lower_2,
                    )
                    direction = "FLAT"

                confidence = ai_result.get(
                    "confidence", "High" if direction != "FLAT" else "Medium"
                )
                logger.info(
                    "LLM result: direction=%s confidence=%s", direction, confidence
                )

                # Journal: log every LLM signal (before gates filter it)
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
                            agent_feature_drivers=(
                                getattr(_agent, "feature_drivers", ()) if _agent else ()
                            ),
                            probability_long=(
                                _agent.probability
                                if _agent and _agent.direction == "LONG"
                                else 0
                            ),
                            probability_short=(
                                _agent.probability
                                if _agent and _agent.direction == "SHORT"
                                else 0
                            ),
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

                # Meta-filter: if ML signal exists, LLM must confirm it
                # Exception: if ML probability is weak (<0.55), trust LLM's conviction
                agent = getattr(session, "_agent_decision", None)
                if (
                    agent
                    and agent.direction != "FLAT"
                    and direction not in ("FLAT", agent.direction)
                ):
                    ml_prob = max(
                        getattr(agent, "p_long", 0.5), getattr(agent, "p_short", 0.5)
                    )
                    if ml_prob >= 0.55:
                        logger.info(
                            "Meta-filter: LLM %s disagrees with ML %s (P=%.2f) → staying FLAT",
                            direction,
                            agent.direction,
                            ml_prob,
                        )
                        direction = "FLAT"
                    else:
                        logger.info(
                            "Meta-filter: LLM %s disagrees with weak ML %s (P=%.2f) → trusting LLM",
                            direction,
                            agent.direction,
                            ml_prob,
                        )

                # Momentum Fade Gate (Fabio Rule: Don't short a freight train)
                if direction in ("LONG", "SHORT") and check_momentum_fade(
                    session.data, tick, direction
                ):
                    logger.info(
                        "Momentum Fade Gate blocked entry: Attempting to %s into massive unrejected momentum",
                        direction,
                    )
                    if self._journal:
                        self._journal.log_rejection(
                            symbol=symbol,
                            reason="MOMENTUM_FADE",
                            amt=session.last_amt,
                            llm_direction=direction,
                        )
                    direction = "FLAT"

                # CVD Hard Gate: Block entries when CVD strongly opposes direction
                # A 3B model can miss this — this is the safety net
                # Thresholds are market-aware: NSE volume is much higher than MCX
                cvd_thresh = 5000 if settings.SCANNER_MODE in ("nse", "nse_options") else 50
                
                if direction == "LONG" and amt_result.cvd_slope < -cvd_thresh:
                    logger.info(
                        "CVD hard gate: LONG blocked — CVD slope %.1f (extreme selling, thresh=%d)",
                        amt_result.cvd_slope,
                        cvd_thresh,
                    )
                    if self._journal:
                        self._journal.log_rejection(
                            symbol=symbol,
                            reason="CVD_OPPOSING",
                            amt=session.last_amt,
                            llm_direction=direction,
                        )
                    direction = "FLAT"
                elif direction == "SHORT" and amt_result.cvd_slope > cvd_thresh:
                    logger.info(
                        "CVD hard gate: SHORT blocked — CVD slope %.1f (extreme buying, thresh=%d)",
                        amt_result.cvd_slope,
                        cvd_thresh,
                    )
                    if self._journal:
                        self._journal.log_rejection(
                            symbol=symbol,
                            reason="CVD_OPPOSING",
                            amt=session.last_amt,
                            llm_direction=direction,
                        )
                    direction = "FLAT"

                # Profile Shape Hard Gate: Block entries opposing dominant distribution
                _shape_code = profile_shape_str[0] if profile_shape_str else ""
                if direction == "LONG" and _shape_code == "P":
                    logger.info(
                        "Profile shape gate: LONG blocked — P-shape (top-heavy distribution)"
                    )
                    if self._journal:
                        self._journal.log_rejection(
                            symbol=symbol,
                            reason="PROFILE_SHAPE_P",
                            amt=session.last_amt,
                            llm_direction=direction,
                        )
                    direction = "FLAT"
                elif direction == "SHORT" and _shape_code == "b":
                    logger.info(
                        "Profile shape gate: SHORT blocked — b-shape (bottom accumulation)"
                    )
                    if self._journal:
                        self._journal.log_rejection(
                            symbol=symbol,
                            reason="PROFILE_SHAPE_B",
                            amt=session.last_amt,
                            llm_direction=direction,
                        )
                    direction = "FLAT"

                # A/B/C Setup Grading (Fabio methodology)
                if direction in ("LONG", "SHORT"):
                    grade_score = 0
                    # Fabio: Proportional conviction - weight bubbles by contract size
                    # 100-contract bubble ≠ 30-contract bubble
                    if item.get("volume_bubbles"):
                        import re

                        # Extract volumes from bubble string: "BUY bubble at 24750 (500 vol, delta +250)"
                        volumes = re.findall(r"\((\d+) vol", item["volume_bubbles"])
                        total_vol = sum(int(v) for v in volumes) if volumes else 0
                        max_vol = max(int(v) for v in volumes) if volumes else 0

                        # Proportional bonus: +1 for direction match, +1 more if big bubble (>200)
                        if (
                            direction == "LONG"
                            and "BUY" in item["volume_bubbles"].upper()
                        ) or (
                            direction == "SHORT"
                            and "SELL" in item["volume_bubbles"].upper()
                        ):
                            grade_score += 1
                            # Big bubble bonus (proportional conviction)
                            if max_vol > 200:
                                grade_score += 1
                    if (direction == "LONG" and amt_result.cvd_slope > 0.3) or (
                        direction == "SHORT" and amt_result.cvd_slope < -0.3
                    ):
                        grade_score += 1
                    # CVD opposing direction: penalize heavily
                    if (direction == "LONG" and amt_result.cvd_slope < -0.3) or (
                        direction == "SHORT" and amt_result.cvd_slope > 0.3
                    ):
                        grade_score -= 2
                    if not amt_result.cvd_divergence:
                        grade_score += 1
                    elif (
                        direction == "LONG"
                        and amt_result.cvd_divergence == "BEARISH_DIV"
                    ) or (
                        direction == "SHORT"
                        and amt_result.cvd_divergence == "BULLISH_DIV"
                    ):
                        grade_score -= 2

                    if (
                        session_info.favor_strategy == "MEAN_REVERSION"
                        and setup_type == SetupType.MEAN_REVERSION
                    ) or (
                        session_info.favor_strategy == "TREND_CONTINUATION"
                        and setup_type == SetupType.TREND_MODEL
                    ):
                        grade_score += 1

                    shape_code = profile_shape_str[0] if profile_shape_str else ""
                    if (shape_code == "b" and direction == "LONG") or (
                        shape_code == "P" and direction == "SHORT"
                    ):
                        grade_score += 1
                    elif (shape_code == "b" and direction == "SHORT") or (
                        shape_code == "P" and direction == "LONG"
                    ):
                        grade_score -= 1

                    vwap_bias = check_vwap_bias(
                        direction,
                        tick.close,
                        (
                            amt_result.session_vwap
                            if amt_result.session_vwap > 0
                            else tick.vwap
                        ),
                        getattr(amt_result, "vwap_upper_2", 0),
                        getattr(amt_result, "vwap_lower_2", 0),
                    )
                    # Fabio: VWAP bias filter - hard block against VWAP direction
                    # Price below VWAP = don't go LONG, above VWAP = don't go SHORT
                    if vwap_bias.get("overextended"):
                        logger.info(
                            "VWAP overextension: %s blocked at ±2σ band (price=%.2f)",
                            direction,
                            tick.close,
                        )
                        if self._journal:
                            self._journal.log_rejection(
                                symbol=symbol,
                                reason="VWAP_OVEREXTENDED",
                                amt=session.last_amt,
                                llm_direction=direction,
                            )
                        direction = "FLAT"
                        block_trade = True
                    elif vwap_bias.get("warning"):
                        # Against VWAP bias - warn but don't block (LLM can override with conviction)
                        grade_score -= 1

                    fp_domain = getattr(session, "_last_fp_domain", None)
                    if fp_domain:
                        try:
                            latest_fp = (
                                list(fp_domain.values())[-1] if fp_domain else None
                            )
                            if latest_fp and hasattr(latest_fp, "levels"):
                                stacked = [
                                    lv
                                    for lv in latest_fp.levels
                                    if getattr(lv, "stacked", False)
                                ]
                                if stacked:
                                    imb_adj = check_imbalance_alignment(
                                        direction, stacked
                                    )
                                    grade_score += imb_adj
                        except Exception:
                            pass

                    if fp_domain:
                        try:
                            _fp_vals = (
                                list(fp_domain.values())
                                if isinstance(fp_domain, dict)
                                else []
                            )
                            if _fp_vals:
                                _latest_fp = _fp_vals[-1]
                                _price_chg = (
                                    ((tick.close - tick.open) / tick.open * 100)
                                    if tick.open > 0
                                    else 0
                                )
                                _absorption = detect_absorption(_latest_fp, _price_chg)
                                if _absorption:
                                    market_data_ai["absorption"] = (
                                        f"ABSORPTION: {_absorption['absorbed_by']} absorbing {_absorption['aggressive_side']} aggression"
                                    )
                        except Exception:
                            pass

                    # Second drive bonus
                    key_levels = [
                        amt_result.poc,
                        amt_result.value_area_high,
                        amt_result.value_area_low,
                    ]
                    key_levels.extend(amt_result.lvns[:3] if amt_result.lvns else [])
                    if self._get_regime_detector(symbol).is_second_drive(
                        tick.close, key_levels
                    ):
                        grade_score += 2

                    # Squeeze bonus
                    squeeze = self._get_regime_detector(symbol).detect_squeeze(
                        session.data, amt_result
                    )
                    if squeeze and squeeze.direction == direction:
                        grade_score += 2

                    if fp_domain:
                        try:
                            _fp_vals = (
                                list(fp_domain.values())
                                if isinstance(fp_domain, dict)
                                else []
                            )
                            # Fabio: Contested zone = hard block (both BUY and SELL bubbles = FLAT)
                            if _fp_vals and detect_contested_zone(_fp_vals):
                                logger.info(
                                    "Contested zone detected: both BUY and SELL bubbles present — blocking entry"
                                )
                                if self._journal:
                                    self._journal.log_rejection(
                                        symbol=symbol,
                                        reason="CONTESTED_ZONE",
                                        amt=session.last_amt,
                                        llm_direction=direction,
                                    )
                                direction = "FLAT"
                                block_trade = True
                        except Exception:
                            pass

                    # Confirmation bundle: weak vol/delta/spread penalizes grade
                    if not item.get("confirmation_strong", True):
                        grade_score -= 1

                    if grade_score >= 3:
                        confidence = "High"
                    elif grade_score >= 0:
                        confidence = "Medium"
                    else:
                        confidence = "Low"

                    # Fabio Gap #1: Trust LLM conviction - only block on extreme cases
                    # Grade filter is now advisory (informs confidence level)
                    # Guardrails AFTER LLM decision: only circuit breaker, daily loss, R:R
                    block_trade = False
                    # Only block if grade is severely negative (less than -3)
                    # This is an extreme guardrail, not a routine filter
                    if grade_score < -3:
                        logger.info(
                            "Grade guardrail: %s blocked — grade_score=%d (extreme negative)",
                            direction,
                            grade_score,
                        )
                        block_trade = True
                        if self._journal:
                            self._journal.log_rejection(
                                symbol=symbol,
                                reason="GRADE_FILTER",
                                amt=session.last_amt,
                                llm_direction=direction,
                            )
                        direction = "FLAT"

                with session._lock:
                    session.last_ai_analysis = {
                        "direction": direction,
                        "rationale": ai_result["rationale"],
                        "confidence": confidence,
                        "input_prompt": ai_result.get("input_prompt", ""),
                        "raw_output": ai_result.get("raw_output", ""),
                        "market_state": ai_result.get("market_state", "Unknown"),
                        "aggression": ai_result.get("aggression", "0.00"),
                    }

                # Persist full LLM decision
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
                        pass

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
                            # Circuit breaker: pause all entries after consecutive stops
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
                                # Compute ATR for wider re-entry buffer
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
                                    # Fabio: Max trades per session cap
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
                                        # Pass confidence for position sizing
                                        entry_signal = build_entry_signal(
                                            direction,
                                            tick,
                                            amt_result,
                                            ai_result,
                                            setup_type,
                                            data=session.data,
                                            risk_sl_pct=_cushion_sl,
                                            session_context=session_info.session,
                                            confidence=confidence,
                                        )
                                    if not TradeManager.is_valid_rr(
                                        entry_signal.price,
                                        entry_signal.stop_loss,
                                        entry_signal.take_profit,
                                    ):
                                        if self._journal:
                                            self._journal.log_rejection(
                                                symbol=symbol,
                                                reason="RR_FILTER",
                                                amt=session.last_amt,
                                                llm_direction=direction,
                                            )
                                    else:
                                        # LLM is now purely advisory for the UI.
                                        # Entry signals are generated and managed by the Unified Quant path.
                                        logger.info(
                                            "LLM inference complete — advisory-only signal for %s",
                                            symbol,
                                        )
                                        if self._journal:
                                            # Create a placeholder signal just for the journal entry
                                            _cushion_sl = session._session_risk_manager.stop_loss_pct if hasattr(session, "_session_risk_manager") else None
                                            entry_signal = build_entry_signal(
                                                direction, tick, amt_result, ai_result, setup_type,
                                                data=session.data, risk_sl_pct=_cushion_sl,
                                                session_context=session_info.session, confidence=confidence
                                            )
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

    # ------------------------------------------------------------------
    # Fabio Rule 11 — Failed entry recording (call on stop-out)
    # ------------------------------------------------------------------

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
        """Clear failed entry records — call on new session start.

        If symbol is empty, clears for all symbols.
        """
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
                    q.put_nowait(None)  # shutdown signal
                except queue.Full:
                    pass

    # Gate and signal methods extracted to domain/fabio_ai/services/entry_gate.py
    # Delegated via: three_align_check, check_confirmation_bundle, build_entry_signal
