"""LLM Entry Handler — Three-Align gate + Confirmation Bundle + LLM decision."""

from __future__ import annotations

import concurrent.futures
import logging
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable

from app.domain.trading.models.enums import SignalType, Source, SetupType
from app.domain.trading.models.entities import Signal
from app.domain.fabio_ai.services.regime_detector import RegimeDetector
from app.domain.fabio_ai.services.trade_manager import TradeManager
from app.domain.trading.events import AIAnalysisCompleted, SignalGenerated
from app.domain.fabio_ai.services.session_context import get_session_info
from app.domain.fabio_ai.services.entry_gate import (
    build_entry_signal,
    check_iv_gate,
    check_delta_filter,
    classify_oi_action,
    check_momentum_fade,
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
        self._regime_detector = RegimeDetector()
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self._predict_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

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
            logger.debug("LLM blocked: degenerate AMT (poc=%.1f vah=%.1f)", amt_result.poc, amt_result.value_area_high)
            return False

        if ai_running:
            return False  # already running, silent skip

        if has_position or has_managed_positions:
            logger.debug("LLM blocked: has_position=%s has_managed=%s", has_position, has_managed_positions)
            return False

        if in_cooldown:
            logger.debug("LLM blocked: in cooldown")
            return False

        # Minimum 60s between entries to prevent rapid re-entries
        if last_entry_time and (_time.time() - last_entry_time) < 60:
            logger.debug("LLM blocked: entry cooldown (%.0fs since last entry)", _time.time() - last_entry_time)
            return False

        # Block entries if daily loss limit reached
        if self._trade_manager and self._trade_manager.should_block_entry():
            logger.info("LLM blocked: daily loss limit reached")
            return False

        # Don't call until model is loaded
        if not self._gen_ai_service.is_ready():
            logger.info("LLM blocked: model not ready (is_loading=%s)", not self._gen_ai_service.is_ready())
            return False

        # Simple 10s cooldown between LLM calls
        elapsed = _time.time() - last_ai_time
        if elapsed < 10:
            return False

        logger.info("LLM entry ALLOWED — calling model (elapsed=%.1fs)", elapsed)
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

        market_state_str = "Trending" if amt_result.market_state == "IMBALANCED" else "Balanced"

        # Session-aware setup bias (Fabio 5-phase IST structure for NSE)
        # Use prior session's VA for opening relation / gap analysis
        prior = getattr(session, '_prior_profile', None)
        prior_vah = prior.get("vah", 0) if prior else 0
        prior_val = prior.get("val", 0) if prior else 0
        open_price = session.data[0].open if session.data else 0
        from app.config import Settings
        _market = Settings().DEFAULT_EXCHANGE
        # Map NFO/BSE to NSE for session context (same trading hours)
        if _market in ("NFO", "BSE"):
            _market = "NSE"
        session_info = get_session_info(
            timestamp=tick.time, market=_market,
            open_price=open_price, prior_vah=prior_vah, prior_val=prior_val,
        )

        # Block entries if session doesn't allow them
        if not session_info.allow_entry:
            with session._lock:
                session.last_ai_analysis = {
                    "direction": "FLAT",
                    "rationale": f"Session phase: {session_info.session} — entries not allowed.",
                    "confidence": "Low",
                }
                session._ai_running = False
            return

        if amt_result.market_state == "IMBALANCED" and session_info.allow_trend:
            setup_type = SetupType.TREND_MODEL
            strategy_hint = "Market is IMBALANCED (trending). Favor trend continuation setups. Look for breakouts beyond VA boundaries."
        elif amt_result.market_state == "IMBALANCED" and not session_info.allow_trend:
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
        if session.data and self._regime_detector.is_contracting(session.data):
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
                if tick.time.replace(".", "", 1).replace("-", "").replace("+", "").isdigit():
                    # Epoch timestamp (e.g. "1771832400.0")
                    cutoff_dt = datetime.fromtimestamp(float(tick.time)) - timedelta(seconds=3000)
                else:
                    cutoff_dt = datetime.fromisoformat(tick.time.replace("Z", "+00:00")) - timedelta(seconds=3000)
            except (ValueError, OSError):
                cutoff_dt = datetime.now() - timedelta(seconds=3000)
            cutoff_time = cutoff_dt.isoformat()
            recent_prints = [ap for ap in amt_result.aggressive_prints if ap.time >= cutoff_time][-3:]
            bubble_parts = []
            for ap in recent_prints:
                bubble_parts.append(f"{ap.side} bubble at {ap.price:.0f} ({ap.volume:.0f} vol, delta {ap.delta:+.0f})")
            volume_bubble_desc = "; ".join(bubble_parts)

        # Episodic memory — feed last 5 trade outcomes to the LLM prompt
        episodic_memory = ""
        if self._storage:
            try:
                recent_trades = self._storage.get_recent_trades(limit=5)
                if recent_trades:
                    parts = []
                    for i, t in enumerate(recent_trades, 1):
                        side = t.get("side", "?")
                        pnl = t.get("pnl", 0)
                        reason = t.get("reason", "")
                        sign = "+" if pnl >= 0 else ""
                        parts.append(f"{i}) {side} {sign}Rs{pnl:.0f} ({reason})")
                    episodic_memory = "Recent trades: " + ", ".join(parts) + "."
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
            "hvns": amt_result.hvns[:3] if amt_result.hvns else (),
            "lvns": amt_result.lvns[:3] if amt_result.lvns else (),
            "cvd_slope": amt_result.cvd_slope,
            "cvd_divergence": amt_result.cvd_divergence,
            "vwap": amt_result.session_vwap if amt_result.session_vwap > 0 else tick.vwap,
            "leg_poc": amt_result.leg_poc,
            "leg_lvns": amt_result.leg_lvns[:3] if amt_result.leg_lvns else (),
            "opening_relation": session_info.opening_relation,
            "market_structure": amt_result.market_structure,
            "structure_confidence": amt_result.structure_confidence,
            "balance_ratio": amt_result.balance_ratio,
            "episodic_memory": episodic_memory,
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
            # Phase 4: POC migration + LVN play
            "poc_signal": amt_result.poc_signal,
            "poc_vs_price": amt_result.poc_vs_price,
            "lvn_play": amt_result.lvn_play,
        }

        # ML signal for LLM meta-filter
        agent = getattr(session, '_agent_decision', None)
        if agent and agent.direction != "FLAT":
            market_data_ai["ml_signal"] = {
                "direction": agent.direction,
                "probability": agent.probability,
                "regime": agent.regime,
            }

        # Options Greeks — theta/gamma/IV context for options scalping
        if hasattr(session, '_greeks') and session._greeks:
            market_data_ai["greeks"] = session._greeks

        # Inject OI analysis if available (stored on session by external feed)
        oi_analysis = getattr(session, '_oi_analysis', None)
        if oi_analysis:
            market_data_ai["oi_pcr"] = oi_analysis.get("pcr", 0)
            market_data_ai["oi_sentiment"] = oi_analysis.get("sentiment", "")
            market_data_ai["oi_nearest_support"] = oi_analysis.get("nearest_support", 0)
            market_data_ai["oi_nearest_resistance"] = oi_analysis.get("nearest_resistance", 0)

        def _worker():
            try:
                # Check if the LLM adapter is ready before calling
                if not self._gen_ai_service.is_ready():
                    with session._lock:
                        session.last_ai_analysis = {
                            "direction": "FLAT",
                            "rationale": "Model loading...",
                            "confidence": "Low",
                        }
                    return

                logger.info("LLM inference starting for %s (price=%.2f, state=%s, setup=%s)",
                            symbol, tick.close, market_state_str, setup_type.value)
                from app.config import settings as _settings
                predict_future = self._predict_executor.submit(
                    self._gen_ai_service.analyze_market, market_data_ai,
                )
                try:
                    ai_result = predict_future.result(timeout=_settings.LLM_TIMEOUT_SECONDS)
                except concurrent.futures.TimeoutError:
                    logger.warning(
                        "Entry LLM timed out after %.0fs — skipping",
                        _settings.LLM_TIMEOUT_SECONDS,
                    )
                    return
                direction = ai_result["direction"]
                # BUY-only gate: block SHORT when ALLOW_SHORT=false
                if direction == "SHORT" and not _settings.ALLOW_SHORT:
                    logger.info("BUY-ONLY mode: SHORT blocked → FLAT")
                    direction = "FLAT"
                    ai_result["direction"] = "FLAT"
                confidence = ai_result.get("confidence", "High" if direction != "FLAT" else "Medium")
                logger.info("LLM result: direction=%s confidence=%s", direction, confidence)

                # Journal: log every LLM signal (before gates filter it)
                if self._journal:
                    try:
                        _agent = getattr(session, '_agent_decision', None)
                        self._journal.log_signal(
                            symbol=symbol,
                            amt=session.last_amt,
                            llm_direction=direction,
                            llm_confidence=confidence,
                            llm_rationale=ai_result.get("rationale", ""),
                            agent_direction=_agent.direction if _agent else "",
                            agent_regime=_agent.regime if _agent else "",
                            probability_long=_agent.probability if _agent and _agent.direction == "LONG" else 0,
                            probability_short=_agent.probability if _agent and _agent.direction == "SHORT" else 0,
                        )
                    except Exception:
                        logger.debug("Journal log_signal failed", exc_info=True)

                # Meta-filter: if ML signal exists, LLM must confirm it
                agent = getattr(session, '_agent_decision', None)
                if agent and agent.direction != "FLAT" and direction not in ("FLAT", agent.direction):
                    logger.info("Meta-filter: LLM %s disagrees with ML %s → staying FLAT", direction, agent.direction)
                    direction = "FLAT"

                # Option gates: IV + Delta filter
                if hasattr(session, '_greeks') and session._greeks:
                    greeks = session._greeks
                    if check_iv_gate(greeks.get("iv", 0), greeks.get("iv_baseline", 0)):
                        logger.info("IV gate blocked entry: IV=%.1f%% (%.1fx baseline)",
                                     greeks.get("iv", 0),
                                     greeks.get("iv", 0) / greeks.get("iv_baseline", 1))
                        if self._journal:
                            self._journal.log_rejection(symbol=symbol, reason="IV_GATE", amt=session.last_amt, llm_direction=direction)
                        direction = "FLAT"
                    elif not check_delta_filter(greeks.get("delta", 0)):
                        logger.info("Delta filter blocked: delta=%.3f (outside 0.35-0.65)",
                                     greeks.get("delta", 0))
                        if self._journal:
                            self._journal.log_rejection(symbol=symbol, reason="DELTA_FILTER", amt=session.last_amt, llm_direction=direction)
                        direction = "FLAT"

                # Momentum Fade Gate (Fabio Rule: Don't short a freight train)
                if direction in ("LONG", "SHORT") and check_momentum_fade(session.data, tick, direction):
                    logger.info("Momentum Fade Gate blocked entry: Attempting to %s into massive unrejected momentum", direction)
                    if self._journal:
                        self._journal.log_rejection(symbol=symbol, reason="MOMENTUM_FADE", amt=session.last_amt, llm_direction=direction)
                    direction = "FLAT"

                # A/B/C Setup Grading (Fabio methodology)
                # A: full confluence (gate + volume bubble + CVD + session aligns)
                # B: partial confluence (gate + 1 confirmation)
                # C: gate only
                if direction in ("LONG", "SHORT"):
                    grade_score = 0
                    # Volume bubble confirms direction
                    if volume_bubble_desc:
                        if (direction == "LONG" and "BUY" in volume_bubble_desc.upper()) or \
                           (direction == "SHORT" and "SELL" in volume_bubble_desc.upper()):
                            grade_score += 1
                    # CVD confirms direction
                    if (direction == "LONG" and amt_result.cvd_slope > 0.3) or \
                       (direction == "SHORT" and amt_result.cvd_slope < -0.3):
                        grade_score += 1
                    # No CVD divergence against direction
                    if not amt_result.cvd_divergence:
                        grade_score += 1
                    elif (direction == "LONG" and amt_result.cvd_divergence == "BEARISH_DIV") or \
                         (direction == "SHORT" and amt_result.cvd_divergence == "BULLISH_DIV"):
                        grade_score -= 2  # strong contra-signal

                    # Session alignment
                    if (session_info.favor_strategy == "MEAN_REVERSION" and setup_type == SetupType.MEAN_REVERSION) or \
                       (session_info.favor_strategy == "TREND_CONTINUATION" and setup_type == SetupType.TREND_MODEL):
                        grade_score += 1

                    # Profile shape alignment
                    shape_code = profile_shape_str[0] if profile_shape_str else ""
                    if (shape_code == "b" and direction == "LONG") or (shape_code == "P" and direction == "SHORT"):
                        grade_score += 1
                    elif (shape_code == "b" and direction == "SHORT") or (shape_code == "P" and direction == "LONG"):
                        grade_score -= 1

                    # Map score to grade
                    if grade_score >= 3:
                        confidence = "High"  # A-grade setup
                    elif grade_score >= 1:
                        confidence = "Medium"  # B-grade setup
                    else:
                        confidence = "Low"  # C-grade setup

                    # Midday consolidation: downgrade one level (less favorable conditions)
                    if session_info.session == "NSE_MIDDAY":
                        confidence = "Low" if confidence in ("Medium", "Low") else "Medium"

                    logger.info("Setup grade: score=%d confidence=%s (session=%s)",
                                grade_score, confidence, session_info.session)

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

                # Persist full LLM decision for fine-tuning dataset
                if self._storage:
                    try:
                        self._storage.save_llm_decision({
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
                        })
                    except Exception:
                        logger.debug("Failed to persist LLM decision", exc_info=True)

                if direction in ("LONG", "SHORT"):
                    # Agent direction agreement check: if agent has a directional
                    # opinion, LLM must agree. Prevents contradictory entries.
                    _ad = getattr(session, '_agent_decision', None)
                    if _ad and _ad.direction in ("LONG", "SHORT") and _ad.direction != direction:
                        logger.info("LLM %s contradicts agent %s — skipping entry", direction, _ad.direction)
                        if self._journal:
                            self._journal.log_rejection(symbol=symbol, reason="AGENT_DIRECTION_MISMATCH", amt=session.last_amt, llm_direction=direction)
                        with session._lock:
                            session._ai_running = False
                        return

                    with session._lock:
                        live_positions = [
                            p for p in session.portfolio.positions if p.status == "OPEN"
                        ]
                        if live_positions:
                            logger.info("LLM wanted to enter but position already exists — skipping")
                        else:
                            # Fabio Rule 11: block re-entry at same failed level
                            if self._regime_detector.is_re_entry_blocked(
                                tick.close, direction, session_info.phase,
                            ):
                                logger.info("Re-entry blocked at %.2f %s (Rule 11)", tick.close, direction)
                                if self._journal:
                                    self._journal.log_rejection(symbol=symbol, reason="RE_ENTRY_BLOCKED", amt=session.last_amt, llm_direction=direction)
                            else:
                                entry_signal = build_entry_signal(direction, tick, amt_result, ai_result, setup_type, data=session.data)
                                # RR filter: reject signals with risk:reward < 1:2
                                if not TradeManager.is_valid_rr(
                                    entry_signal.price, entry_signal.stop_loss, entry_signal.take_profit
                                ):
                                    logger.info("RR filter rejected signal (< 1:2)")
                                    if self._journal:
                                        self._journal.log_rejection(symbol=symbol, reason="RR_FILTER", amt=session.last_amt, llm_direction=direction)
                                else:
                                    # Enqueue signal for main thread to execute.
                                    # DO NOT publish SignalGenerated from worker thread —
                                    # the synchronous event bus would run the handler here,
                                    # mutating portfolio without the main thread's lock.
                                    session._pending_signal = (symbol, entry_signal)
                                    session._last_entry_time = time.time()

                self._event_bus.publish(AIAnalysisCompleted(
                    symbol=symbol,
                    direction=direction,
                    rationale=ai_result["rationale"],
                    confidence=confidence,
                ))
            except Exception as e:
                logger.error(f"AI Analysis failed: {e}")
            finally:
                with session._lock:
                    session._ai_running = False

        self._executor.submit(_worker)

    # ------------------------------------------------------------------
    # Fabio Rule 11 — Failed entry recording (call on stop-out)
    # ------------------------------------------------------------------

    def record_stop_out(self, level: float, direction: str, session_phase: int) -> None:
        """Record a stopped-out position so re-entry at the same level is blocked."""
        self._regime_detector.record_failed_entry(level, direction, session_phase)

    def clear_failed_entries(self) -> None:
        """Clear failed entry records — call on new session start."""
        self._regime_detector.clear_failed_entries()

    # Gate and signal methods extracted to domain/fabio_ai/services/entry_gate.py
    # Delegated via: three_align_check, check_confirmation_bundle, build_entry_signal
