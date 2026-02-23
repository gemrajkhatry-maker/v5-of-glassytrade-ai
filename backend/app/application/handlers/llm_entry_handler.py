"""LLM Entry Handler — Three-Align gate + Confirmation Bundle + LLM decision."""

from __future__ import annotations

import concurrent.futures
import logging
import time
import threading
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
    ) -> None:
        self._gen_ai_service = gen_ai_service
        self._event_bus = event_bus
        self._storage = storage
        self._trade_manager = trade_manager
        self._entry_lock = threading.Lock()
        self._regime_detector = RegimeDetector()
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def should_run(
        self,
        last_ai_time: float,
        ai_running: bool,
        has_position: bool,
        has_managed_positions: bool,
        in_cooldown: bool,
        data: list,
        amt_result: AMTResult,
        tick: OHLC,
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

        # Block entries if daily loss limit reached
        if self._trade_manager and self._trade_manager.should_block_entry():
            logger.info("LLM blocked: daily loss limit reached")
            return False

        # Don't call until model is loaded
        if not self._gen_ai_service.is_ready():
            logger.info("LLM blocked: model not ready (is_loading=%s)", not self._gen_ai_service.is_ready())
            return False

        # Fabio Rule 8: block trend trades during contraction
        if data and self._regime_detector.is_contracting(data):
            # Determine prospective setup type from AMT state
            if amt_result.market_state == "IMBALANCED":
                logger.info("LLM blocked: market contracting — trend trade suppressed (Rule 8)")
                return False
            # Mean-reversion setups are still allowed during contraction

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
        session_info = get_session_info(
            timestamp=tick.time, market="NSE",
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

        # Profile shape — read from AMTResult (already computed once in analyzer)
        profile_shape_str = ""
        if amt_result.profile_shape:
            shape_descriptions = {
                "D": "D-shape (balanced, rotational)",
                "P": "P-shape (top-heavy, sellers may be trapped)",
                "b": "b-shape (bottom-heavy, buying absorption)",
            }
            profile_shape_str = shape_descriptions.get(amt_result.profile_shape, "")

        # Volume bubble summary (aggressive prints = 2.5σ volume spikes)
        # Only include recent bubbles (last 10 candles) — stale prints mislead the model
        volume_bubble_desc = ""
        if amt_result.aggressive_prints:
            cutoff_dt = datetime.fromisoformat(tick.time.replace("Z", "+00:00")) - timedelta(seconds=3000)
            cutoff_time = cutoff_dt.isoformat()
            recent_prints = [ap for ap in amt_result.aggressive_prints if ap.time >= cutoff_time][-3:]
            bubble_parts = []
            for ap in recent_prints:
                bubble_parts.append(f"{ap.side} bubble at {ap.price:.0f} ({ap.volume:.0f} vol, delta {ap.delta:+.0f})")
            volume_bubble_desc = "; ".join(bubble_parts)

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
        }

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
                ai_result = self._gen_ai_service.analyze_market(market_data_ai)
                direction = ai_result["direction"]
                confidence = ai_result.get("confidence", "High" if direction != "FLAT" else "Medium")
                logger.info("LLM result: direction=%s confidence=%s", direction, confidence)

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
                    with self._entry_lock:
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
                            else:
                                entry_signal = build_entry_signal(direction, tick, amt_result, ai_result, setup_type)
                                # RR filter: reject signals with risk:reward < 1:2
                                if not TradeManager.is_valid_rr(
                                    entry_signal.price, entry_signal.stop_loss, entry_signal.take_profit
                                ):
                                    logger.info("RR filter rejected signal (< 1:2)")
                                else:
                                    self._event_bus.publish(
                                        SignalGenerated(symbol=symbol, signal=entry_signal)
                                    )

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
