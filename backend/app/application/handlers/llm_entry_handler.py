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
from app.domain.trading.events import AIAnalysisCompleted, SignalGenerated

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
    ) -> None:
        self._gen_ai_service = gen_ai_service
        self._event_bus = event_bus
        self._storage = storage
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
    ) -> bool:
        """Check if LLM entry logic should run (regime-change triggered + gates)."""
        # Guard against degenerate AMT data (zero/negative levels)
        if amt_result.poc <= 0 or amt_result.value_area_high <= 0:
            return False

        if ai_running or has_position or has_managed_positions or in_cooldown:
            return False

        # CRITICAL: Don't consult regime detector until model is ready.
        # Otherwise the first-observation trigger gets consumed while the
        # model is still loading, and the LLM never gets called in stable markets.
        if not self._gen_ai_service.is_ready():
            return False

        # Use regime detector instead of fixed 10s timer
        if not self._regime_detector.should_trigger_llm(tick, amt_result):
            return False

        # Three-Align gate — if it fails, still run LLM in monitoring mode
        # (returns FLAT) so the UI gets updated with market context
        aligned = self._three_align_check(data, amt_result, tick)
        if not aligned:
            logger.debug("Three-Align gate failed — running LLM in monitoring mode")
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

        # Determine setup type based on market regime
        if amt_result.market_state == "IMBALANCED":
            setup_type = SetupType.TREND_MODEL
            strategy_hint = "Market is IMBALANCED (trending). Favor trend continuation setups. Look for breakouts beyond VA boundaries."
        else:
            setup_type = SetupType.MEAN_REVERSION
            strategy_hint = "Market is BALANCED (range-bound). Favor mean reversion setups. Look for fades at VA extremes back toward POC."

        # Profile shape — read from AMTResult (already computed once in analyzer)
        profile_shape_str = ""
        if amt_result.profile_shape:
            shape_descriptions = {
                "D": "D-shape (balanced, rotational)",
                "P": "P-shape (top-heavy, sellers may be trapped)",
                "b": "b-shape (bottom-heavy, buying absorption)",
            }
            profile_shape_str = shape_descriptions.get(amt_result.profile_shape, "")

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

                # Shape-aware confidence adjustment
                if profile_shape_str and direction in ("LONG", "SHORT"):
                    shape_code = profile_shape_str[0] if profile_shape_str else ""
                    if (shape_code == "b" and direction == "LONG") or (shape_code == "P" and direction == "SHORT"):
                        confidence = "High"  # shape aligns with direction
                    elif (shape_code == "b" and direction == "SHORT") or (shape_code == "P" and direction == "LONG"):
                        confidence = "Low"   # shape contradicts direction

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
                            entry_signal = self._build_signal(direction, tick, amt_result, ai_result, setup_type)
                            self._event_bus.publish(
                                SignalGenerated(symbol=symbol, signal=entry_signal)
                            )

                self._event_bus.publish(AIAnalysisCompleted(
                    symbol=symbol,
                    direction=direction,
                    rationale=ai_result["rationale"],
                    confidence="High" if direction != "FLAT" else "Medium",
                ))
            except Exception as e:
                logger.error(f"AI Analysis failed: {e}")
            finally:
                session._ai_running = False

        self._executor.submit(_worker)

    # ------------------------------------------------------------------
    # Fabio Playbook gates
    # ------------------------------------------------------------------

    def _three_align_check(self, data: list, amt_result: AMTResult, tick: OHLC) -> bool:
        """Three-Align Gate: Market State + Location + Aggression."""
        # Reject if AMT has zero levels (degenerate result)
        if amt_result.poc <= 0 or amt_result.value_area_high <= 0 or amt_result.value_area_low <= 0:
            return False

        state_ok = amt_result.market_state in ("BALANCED", "IMBALANCED")

        near_level = False
        threshold = tick.close * 0.002
        for level in [amt_result.value_area_high, amt_result.value_area_low, amt_result.poc]:
            if abs(tick.close - level) < threshold:
                near_level = True
                break
        if not near_level:
            for lvn in amt_result.lvns:
                if abs(tick.close - lvn) < threshold:
                    near_level = True
                    break

        agg_ok = self._check_confirmation_bundle(data, tick)
        return state_ok and near_level and agg_ok

    def _check_confirmation_bundle(self, data: list, tick: OHLC) -> bool:
        """Confirmation Bundle (2/3): Volume Impulse + Delta Pressure + Aggression Sigma.

        Volume Impulse uses EMA(20) of volume (Valentini dynamic threshold).
        Aggression Sigma uses EMA-based z-score (same as Volume Bubbles).
        """
        if not data or len(data) < 20:
            return False

        # 1. Volume Impulse — EMA-based (Valentini dynamic threshold)
        alpha = 2.0 / 21  # EMA(20)
        ema_vol = data[-20].volume
        for d in data[-19:]:
            ema_vol = alpha * d.volume + (1.0 - alpha) * ema_vol
        vol_impulse = tick.volume > (ema_vol * 1.5)

        # 2. Delta Pressure — directional filter
        delta_ratio = abs(tick.delta) / tick.volume if tick.volume > 0 else 0
        delta_pressure = delta_ratio > 0.15

        # 3. Aggression Sigma — EMA-based z-score (2.5σ = top ~1%)
        sigma = compute_aggression_sigma(tick, data[-50:])
        agg_sigma = sigma >= 2.5

        return sum([vol_impulse, delta_pressure, agg_sigma]) >= 2

    # ------------------------------------------------------------------
    # Signal construction
    # ------------------------------------------------------------------

    def _build_signal(
        self, direction: str, tick: OHLC, amt_result: AMTResult, ai_result: dict,
        setup_type: SetupType = SetupType.TREND_MODEL,
    ) -> Signal:
        """Build Signal from LLM decision using Fabio Playbook SL/TP.

        Mean Reversion: TP at POC, tight SL beyond VA boundary.
        Trend Model:    TP extended beyond VA, wider SL, trailing allowed.
        """
        is_buy = direction == "LONG"
        sig_type = SignalType.BUY if is_buy else SignalType.SELL
        buffer = tick.close * 0.001

        if setup_type == SetupType.MEAN_REVERSION:
            # Mean reversion: target POC, stop beyond VA edge
            tp_price = amt_result.poc
            if is_buy:
                stop_price = amt_result.value_area_low - buffer
                if tp_price <= tick.close or stop_price >= tick.close:
                    tp_price = tick.close * 1.010
                    stop_price = tick.close * 0.995
            else:
                stop_price = amt_result.value_area_high + buffer
                if tp_price >= tick.close or stop_price <= tick.close:
                    tp_price = tick.close * 0.990
                    stop_price = tick.close * 1.005
            allow_trail = False
        else:
            # Trend model: target extended beyond VA, trailing stop enabled
            if is_buy:
                tp_price = amt_result.value_area_high + (amt_result.value_area_high - amt_result.poc)
                stop_price = amt_result.poc - buffer
                if tp_price <= tick.close or stop_price >= tick.close:
                    tp_price = tick.close * 1.020
                    stop_price = tick.close * 0.990
            else:
                tp_price = amt_result.value_area_low - (amt_result.poc - amt_result.value_area_low)
                stop_price = amt_result.poc + buffer
                if tp_price >= tick.close or stop_price <= tick.close:
                    tp_price = tick.close * 0.980
                    stop_price = tick.close * 1.010
            allow_trail = True

        setup_label = "MeanRev" if setup_type == SetupType.MEAN_REVERSION else "Trend"

        return Signal(
            type=sig_type,
            price=tick.close,
            reason=f"LLM {setup_label}: {ai_result['rationale'][:80]}",
            setup=setup_type,
            source=Source.LLM,
            stop_loss=stop_price,
            take_profit=tp_price,
            timestamp=tick.time,
            metadata={
                "llm_entry": True,
                "allow_trail": allow_trail,
                "confidence": ai_result.get("confidence", "Medium"),
                "market_state_model": ai_result.get("market_state", "Unknown"),
                "raw_output": ai_result.get("raw_output", "")[:200],
            },
        )
