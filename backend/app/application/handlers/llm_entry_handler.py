"""LLM Entry Handler — Three-Align gate + Confirmation Bundle + LLM decision."""

from __future__ import annotations

import concurrent.futures
import logging
import time
import threading
from typing import TYPE_CHECKING, Callable

from app.domain.trading.models.enums import SignalType, Source, SetupType
from app.domain.trading.models.entities import Signal
from app.domain.fabio_ai.services.amt_analyzer import compute_aggression_sigma
from app.domain.fabio_ai.services.regime_detector import RegimeDetector
from app.domain.fabio_ai.services.trade_manager import TradeManager
from app.domain.trading.events import AIAnalysisCompleted, SignalGenerated
from app.domain.fabio_ai.services.session_context import get_session_info
from app.domain.fabio_ai.services.entry_gate import (
    three_align_check,
    check_confirmation_bundle,
    check_volatility_filter,
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
        """Check if LLM entry logic should run (regime-change triggered + gates)."""
        # Guard against degenerate AMT data (zero/negative levels)
        if amt_result.poc <= 0 or amt_result.value_area_high <= 0:
            return False

        if ai_running or has_position or has_managed_positions or in_cooldown:
            return False

        # Volatility / instrument health filter (pure quant)
        if check_volatility_filter(data, tick):
            return False

        # Block entries if daily loss limit reached
        if self._trade_manager and self._trade_manager.should_block_entry():
            logger.info("LLM entry blocked: daily loss limit reached")
            return False

        # CRITICAL: Don't consult regime detector until model is ready.
        if not self._gen_ai_service.is_ready():
            return False

        # Use regime detector instead of fixed 10s timer
        if not self._regime_detector.should_trigger_llm(tick, amt_result):
            return False

        # Three-Align gate (pure quant)
        aligned = three_align_check(data, amt_result, tick, order_book)
        if not aligned:
            logger.debug("Three-Align gate failed — skipping LLM call")
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
        session._last_ai_time = time.time()
        session._ai_running = True

        market_state_str = "Trending" if amt_result.market_state == "IMBALANCED" else "Balanced"

        # Session-aware setup bias (Fabio: London=MeanRev, NY=Trend)
        session_info = get_session_info(timestamp=tick.time)

        if amt_result.market_state == "IMBALANCED":
            setup_type = SetupType.TREND_MODEL
            strategy_hint = "Market is IMBALANCED (trending). Favor trend continuation setups. Look for breakouts beyond VA boundaries."
        else:
            setup_type = SetupType.MEAN_REVERSION
            strategy_hint = "Market is BALANCED (range-bound). Favor mean reversion setups. Look for fades at VA extremes back toward POC."

        # Session override: London forces mean reversion, NY forces trend
        if session_info.session == "LONDON" and setup_type == SetupType.TREND_MODEL:
            strategy_hint += " [London session — prefer mean reversion over trend.]"
        elif session_info.session in ("NEW_YORK", "OVERLAP") and setup_type == SetupType.MEAN_REVERSION:
            strategy_hint += " [NY session — watch for trend breakouts.]"
        elif session_info.session == "ASIA":
            strategy_hint += " [Asia session — reduced opportunity, be selective.]"

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
        volume_bubble_desc = ""
        if amt_result.aggressive_prints:
            recent_prints = amt_result.aggressive_prints[-3:]  # last 3 bubbles
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
        }

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

                    # Outside prime hours: downgrade one level
                    if session_info.session == "ASIA":
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
                session._ai_running = False

        self._executor.submit(_worker)

    # Gate and signal methods extracted to domain/fabio_ai/services/entry_gate.py
    # Delegated via: three_align_check, check_confirmation_bundle, build_entry_signal
