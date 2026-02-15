"""TradingSession — application service managing per-symbol state.

This is the central coordinator that owns the data store, portfolio,
model weights, and wires up the event flow for each trading symbol.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import logging
import time
import threading

from app.domain.trading.models.value_objects import OHLC, OrderBook
from app.domain.fabio_ai.models.predictions import ModelWeights
from app.domain.trading.models.aggregates import Portfolio
from app.domain.trading.models.entities import Signal
from app.domain.trading.models.enums import SignalType, Source, SetupType
from app.domain.trading.events import (
    TickReceived, AnalysisCompleted, PredictionCompleted,
    SignalGenerated, PositionOpened, PositionClosed, AIAnalysisCompleted,
)
from app.domain.ports.event_bus import EventBusPort
from app.domain.fabio_ai.services.amt_analyzer import AMTAnalyzer, compute_aggression_sigma
from app.domain.fabio_ai.services.prediction_engine import PredictionEngine
from app.domain.trading.services.signal_generator import SignalGenerator
from app.domain.trading.services.risk_manager import RiskManager
from app.domain.fabio_ai.services.learning_engine import LearningEngine
from app.domain.fabio_ai.services.footprint_analyzer import FootprintAnalyzer
from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService
from app.domain.fabio_ai.services.trade_manager import TradeManager
from app.domain.ports.broker import BrokerPort

log = logging.getLogger(__name__)

# RL imports are optional — they require numpy + gymnasium + sb3_contrib
try:
    import numpy as np
    from app.domain.fabio_ai.rl.trainer import ValentiniTrainer
    from app.domain.fabio_ai.rl.valentini_env import (
        ACTION_HOLD, ACTION_TREND_BUY, ACTION_TREND_SELL,
        ACTION_REVERT_BUY, ACTION_REVERT_SELL, ACTION_NAMES,
        ValentiniAMTEnv,
    )
    _RL_AVAILABLE = True
except ImportError:
    _RL_AVAILABLE = False
    log.info("RL dependencies not installed — RL signals disabled")

from app.infrastructure.serialization.schemas import (
    portfolio_to_dto, amt_result_to_dto, ohlc_to_dto,
    signal_to_dto, stats_to_dto, footprint_to_dto,
)


@dataclass
class SessionState:
    """Mutable per-symbol state."""
    symbol: str = ""
    data: list[OHLC] = field(default_factory=list)
    order_book: OrderBook | None = None
    portfolio: Portfolio = field(default_factory=Portfolio.create_default)
    learning: LearningEngine = field(default_factory=LearningEngine)

    # Cached latest results for query access
    last_amt: dict | None = None
    last_prediction: dict | None = None
    last_footprint: dict | None = None
    last_ai_analysis: dict | None = None


class TradingSessionService:
    """Application service coordinating the event-driven trading pipeline.

    Wires domain services together through the event bus and manages
    per-symbol session state.
    """

    def __init__(
        self,
        event_bus: EventBusPort,
        broker: BrokerPort,
        gen_ai_service: GenerativeAIService | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._broker = broker
        self._gen_ai_service = gen_ai_service or GenerativeAIService()

        # Domain services
        self._amt_analyzer = AMTAnalyzer()
        self._prediction_engine = PredictionEngine()
        self._signal_generator = SignalGenerator()
        self._risk_manager = RiskManager()
        self._footprint_analyzer = FootprintAnalyzer()
        self._trade_manager = TradeManager()
        self._entry_lock = threading.Lock()  # prevents duplicate entries

        # RL signal source (optional — active only when a model is loaded)
        self._rl_trainer = ValentiniTrainer() if _RL_AVAILABLE else None

        # Session state per symbol
        self._sessions: dict[str, SessionState] = {}

        # Wire event subscriptions
        self._event_bus.subscribe(TickReceived, self._on_tick)
        self._event_bus.subscribe(AnalysisCompleted, self._on_analysis_completed)
        self._event_bus.subscribe(PredictionCompleted, self._on_prediction_completed)
        self._event_bus.subscribe(SignalGenerated, self._on_signal_generated)
        self._event_bus.subscribe(PositionClosed, self._on_position_closed)

    def get_or_create_session(self, symbol: str) -> SessionState:
        if symbol not in self._sessions:
            new_session = SessionState(symbol=symbol)
            new_session.last_ai_analysis = {
                "direction": "FLAT",
                "rationale": "Initializing AI Model... Trigger: **Wait**",
                "confidence": "Low",
                "input_prompt": "System Startup",
            }
            self._sessions[symbol] = new_session
        return self._sessions[symbol]

    def process_tick(self, symbol: str, tick: OHLC, order_book: OrderBook | None = None) -> dict:
        """Process a new tick: publish TickReceived, let event chain run,
        return the current full state snapshot."""
        session = self.get_or_create_session(symbol)

        # Update data store
        session.data.append(tick)
        if len(session.data) > 1000:
            session.data = session.data[-1000:]
        session.order_book = order_book

        # Process tick in portfolio (SL/TP exits)
        closed_positions = session.portfolio.process_tick(tick)

        # Emit PositionClosed events for learning
        for pos in closed_positions:
            self._event_bus.publish(PositionClosed(symbol=symbol, position=pos))

        # Publish the main tick event (triggers analysis chain)
        self._event_bus.publish(TickReceived(
            symbol=symbol, tick=tick,
            order_book=order_book,
            data=tuple(session.data),
        ))

        # Return current state snapshot
        return self._build_state_snapshot(session)

    def create_portfolio(self) -> Portfolio:
        """Create a fresh default portfolio (for REST endpoint)."""
        return Portfolio.create_default()

    # ----- event handlers -----

    def _on_tick(self, event: TickReceived) -> None:
        """Handle TickReceived.

        Every tick:
          1. AMT analysis  → compute VAH/POC/VAL (context)
          2. TradeManager   → check SL/TP/Trail/TimeStop for open positions

        Throttled (10s):
          3. If no position AND not in cooldown → LLM entry decision
        """
        session = self.get_or_create_session(event.symbol)

        # ── 1. AMT Analysis (context, no signals) ──
        amt_result = self._amt_analyzer.analyze(list(event.data), event.order_book)
        session.last_amt = amt_result_to_dto(amt_result)

        # Footprint (latest 50 candles) — chart visualization
        fp_data = list(event.data)[-50:]
        fp_result = self._footprint_analyzer.generate(fp_data)
        session.last_footprint = {
            k: footprint_to_dto(v) for k, v in fp_result.items()
        }

        # ── 2. Deterministic Trade Management (every tick) ──
        open_positions = [p for p in session.portfolio.positions if p.status == 'OPEN']
        has_position = len(open_positions) > 0

        if has_position:
            pos = open_positions[0]
            exit_sig = self._trade_manager.check_position(pos.id, event.tick.close)
            if exit_sig:
                session.portfolio.close_position(
                    pos.id, exit_sig.exit_price, exit_sig.reason,
                )
                self._trade_manager.unregister_position(pos.id)
                log.info(
                    f"Position {pos.id} closed: {exit_sig.reason} "
                    f"at {exit_sig.exit_price:.2f}"
                )
                has_position = False  # allow LLM to look for next entry

        # ── 3. LLM Entry Decision (throttled, entry-only) ──
        now = time.time()
        last_ai_time = getattr(session, '_last_ai_time', 0)
        ai_running = getattr(session, '_ai_running', False)

        should_run_llm = (
            (now - last_ai_time) >= 10
            and not ai_running
            and not has_position
            and not self._trade_manager.has_managed_positions
            and not self._trade_manager.in_cooldown()
            and self._three_align_check(session, amt_result, event.tick)
        )

        if should_run_llm:
            session._last_ai_time = now
            session._ai_running = True

            # Build market context with AMT-computed VA levels
            market_state_str = "Balanced"
            if amt_result.market_state == "IMBALANCED":
                market_state_str = "Trending"

            market_data_ai = {
                "ltp": event.tick.close,
                "delta": event.tick.delta,
                "volume": event.tick.volume,
                "vah": amt_result.value_area_high,
                "val": amt_result.value_area_low,
                "poc": amt_result.poc,
                "market_state": market_state_str,
                "aggression": f"Aggression Score: {amt_result.aggression:.2f}",
            }

            def _run_ai_entry(sess, data, symbol, tick, amt_res):
                try:
                    ai_result = self._gen_ai_service.analyze_market(data)
                    direction = ai_result["direction"]

                    sess.last_ai_analysis = {
                        "direction": direction,
                        "rationale": ai_result["rationale"],
                        "confidence": "High" if direction != "FLAT" else "Medium",
                        "input_prompt": ai_result.get("input_prompt", ""),
                        "raw_output": ai_result.get("raw_output", ""),
                        "market_state": ai_result.get("market_state", "Unknown"),
                        "aggression": ai_result.get("aggression", "0.00"),
                    }

                    # === ENTRY ONLY (thread-safe) ===
                    if direction in ("LONG", "SHORT"):
                        with self._entry_lock:
                            # Double-check: no position was opened while LLM was thinking
                            live_positions = [p for p in sess.portfolio.positions if p.status == 'OPEN']
                            if live_positions or self._trade_manager.has_managed_positions:
                                log.info("LLM wanted to enter but position already exists — skipping")
                            else:
                                is_buy = direction == "LONG"
                                sig_type = SignalType.BUY if is_buy else SignalType.SELL
                                
                                # Dynamic SL/TP from Fabio Playbook
                                # Target = POC
                                # SL = VAL (Long) / VAH (Short) + buffer
                                # Trail = Only if Imbalanced
                                
                                buffer = tick.close * 0.001  # 0.1% buffer
                                tp_price = amt_res.poc
                                
                                if is_buy:
                                    stop_price = amt_res.value_area_low - buffer
                                    # Safety: if POC is below entry or SL above entry (weird profile), fallback to fixed %
                                    if tp_price <= tick.close or stop_price >= tick.close:
                                         tp_price = tick.close * 1.015
                                         stop_price = tick.close * 0.995
                                else:
                                    stop_price = amt_res.value_area_high + buffer
                                    if tp_price >= tick.close or stop_price <= tick.close:
                                         tp_price = tick.close * 0.985
                                         stop_price = tick.close * 1.005

                                allow_trail = (amt_res.market_state == "IMBALANCED")

                                entry_signal = Signal(
                                    type=sig_type,
                                    price=tick.close,
                                    reason=f"LLM Entry: {ai_result['rationale'][:80]}",
                                    setup=SetupType.TREND_MODEL,
                                    source=Source.LLM,
                                    stop_loss=stop_price,
                                    take_profit=tp_price,
                                    timestamp=tick.time,
                                    metadata={"llm_entry": True, "allow_trail": allow_trail},
                                )
                                self._event_bus.publish(SignalGenerated(
                                    symbol=symbol, signal=entry_signal,
                                ))

                    self._event_bus.publish(AIAnalysisCompleted(
                        symbol=symbol,
                        direction=direction,
                        rationale=ai_result["rationale"],
                        confidence="High" if direction != "FLAT" else "Medium",
                    ))
                except Exception as e:
                    log.error(f"AI Analysis failed: {e}")
                finally:
                    sess._ai_running = False

            t = threading.Thread(
                target=_run_ai_entry,
                args=(session, market_data_ai, event.symbol, event.tick, amt_result),
                daemon=True,
            )
            t.start()
        elif not has_position and not ai_running:
            # No position, but LLM hasn't run yet — update UI status
            if self._trade_manager.in_cooldown():
                cooldown_status = session.last_ai_analysis or {}
                cooldown_status["direction"] = "FLAT"
                cooldown_status["rationale"] = (
                    cooldown_status.get("rationale", "") +
                    " [Cooldown — waiting before next entry]"
                )
                session.last_ai_analysis = cooldown_status

        # NOTE: AMT/Prediction/RL signal generation DISABLED
        # LLM handles entries; TradeManager handles exits

    def _three_align_check(self, session, amt_result, tick) -> bool:
        """Fabio Playbook 'Three-Align' Gate.
        
        Only trade when ALL 3 align:
        1) Market State (Balance vs Imbalance) - check displacement/acceptance
        2) Location (Near VAH/VAL/POC/LVN)
        3) Aggression (Confirmation Bundle)
        """
        # 1. Market State
        # AMT analysis now correctly identifies Imbalanced/Balanced
        state_ok = amt_result.market_state in ("BALANCED", "IMBALANCED")
        
        # 2. Location
        # Check if price is near key levels (within 0.2%)
        near_level = False
        threshold = tick.close * 0.002
        
        for level in [amt_result.value_area_high, amt_result.value_area_low, amt_result.poc]:
            if abs(tick.close - level) < threshold:
                near_level = True
                break
                
        if not near_level:
            # Check LVNs
            for lvn in amt_result.lvns:
                if abs(tick.close - lvn) < threshold:
                    near_level = True
                    break
        
        # 3. Aggression (Confirmation Bundle)
        agg_ok = self._check_confirmation_bundle(session, tick)
        
        # Log failure reason for debugging/UI
        if not near_level:
            # Update rationale only if we haven't run AI recently
            pass 
            
        return state_ok and near_level and agg_ok

    def _check_confirmation_bundle(self, session, tick) -> bool:
        """Fabio Confirmation Bundle (Require 2/3).
        
        1. Volume Impulse: Tick volume > 1.5x rolling avg
        2. Delta Pressure: |Delta| / Volume > 15%
        3. Aggression Sigma: > 2.5 sigma spike
        """
        if not session.data or len(session.data) < 20:
            return False
            
        # 1. Volume Impulse
        recent_vols = [d.volume for d in session.data[-20:]]
        avg_vol = sum(recent_vols) / len(recent_vols) if recent_vols else 1.0
        vol_impulse = tick.volume > (avg_vol * 1.5)
        
        # 2. Delta Pressure
        delta_ratio = abs(tick.delta) / tick.volume if tick.volume > 0 else 0
        delta_pressure = delta_ratio > 0.15
        
        # 3. Aggression Sigma
        sigma = compute_aggression_sigma(tick, session.data[-50:])
        agg_sigma = sigma >= 2.5
        
        # Count matches
        count = sum([vol_impulse, delta_pressure, agg_sigma])
        return count >= 2

    def _on_analysis_completed(self, event: AnalysisCompleted) -> None:
        """Extract signal from AMT analysis."""
        signal = self._signal_generator.evaluate_amt(event.result)
        if signal:
            self._event_bus.publish(SignalGenerated(
                symbol=event.symbol, signal=signal,
            ))

    def _on_prediction_completed(self, event: PredictionCompleted) -> None:
        """Extract signal from prediction analysis."""
        if not event.analysis:
            return
        session = self.get_or_create_session(event.symbol)
        if not session.data:
            return

        signal = self._signal_generator.evaluate_prediction(
            event.analysis, session.data[-1], event.generation,
        )
        if signal:
            self._event_bus.publish(SignalGenerated(
                symbol=event.symbol, signal=signal,
            ))

    def _on_signal_generated(self, event: SignalGenerated) -> None:
        """Validate signal via risk manager and execute via broker."""
        if not event.signal:
            return

        session = self.get_or_create_session(event.symbol)

        if not self._risk_manager.validate(event.signal, session.portfolio):
            return

        position = self._broker.execute_order(
            event.signal, session.portfolio, event.symbol,
        )

        if position:
            self._event_bus.publish(PositionOpened(
                symbol=event.symbol, position=position,
            ))

            # Register LLM-sourced positions with TradeManager
            if event.signal.source == Source.LLM:
                allow_trail = event.signal.metadata.get("allow_trail", False)
                self._trade_manager.register_position(
                    position_id=position.id,
                    side="LONG" if event.signal.type == SignalType.BUY else "SHORT",
                    entry_price=position.entry_price,
                    stop_loss=event.signal.stop_loss,
                    take_profit=event.signal.take_profit,
                    allow_trail=allow_trail,
                )

    def _on_position_closed(self, event: PositionClosed) -> None:
        """Feed closed positions to the learning engine."""
        if not event.position:
            return
        session = self.get_or_create_session(event.symbol)
        session.learning.learn(event.position)

    # ----- state snapshot -----

    def _build_state_snapshot(self, session: SessionState) -> dict:
        """Build the full state snapshot for the WebSocket response."""
        portfolio = session.portfolio
        weights = session.learning.weights

        # RL training status
        if _RL_AVAILABLE and self._rl_trainer:
            rl_st = self._rl_trainer.status
            rl_status = {
                "state": rl_st.state,
                "modelLoaded": bool(rl_st.model_path),
                "timestepsDone": rl_st.timesteps_done,
                "totalTimesteps": rl_st.total_timesteps,
                "episodeCount": rl_st.episode_count,
                "meanReward": rl_st.mean_reward,
                "meanSharpe": rl_st.mean_sharpe,
                "totalTrades": rl_st.total_trades,
                "elapsedSeconds": rl_st.elapsed_seconds,
            }
        else:
            rl_status = {
                "state": "unavailable", "modelLoaded": False,
                "timestepsDone": 0, "totalTimesteps": 0,
                "episodeCount": 0, "meanReward": 0.0,
                "meanSharpe": 0.0, "totalTrades": 0,
                "elapsedSeconds": 0.0,
            }

        return {
            "_symbol": session.symbol,
            "portfolio": portfolio_to_dto(portfolio),
            "amt": session.last_amt,
            "prediction": session.last_prediction,
            "footprint": session.last_footprint,
            "genAIAnalysis": session.last_ai_analysis,
            "modelWeights": {
                "trend": weights.trend,
                "momentum": weights.momentum,
                "delta": weights.delta,
                "orderBook": weights.order_book,
                "volatility": weights.volatility,
            },
            "generation": session.learning.generation,
            "stats": {
                "amt": stats_to_dto(portfolio.get_stats(Source.AMT)),
                "prediction": stats_to_dto(portfolio.get_stats(Source.PREDICTION)),
                "rl": stats_to_dto(portfolio.get_stats(Source.RL)),
            },
            "rlStatus": rl_status,
        }
