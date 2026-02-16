"""TradingSession — thin coordinator delegating to focused handlers.

Manages per-symbol state, wires event subscriptions, and delegates:
  - AMT analysis        → AMTHandler
  - Trade exits         → TradeLifecycleHandler
  - LLM entry decisions → LLMEntryHandler
  - RL status           → RLHandler
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import threading

from app.domain.trading.models.value_objects import OHLC, OrderBook
from app.domain.trading.models.aggregates import Portfolio
from app.domain.trading.models.enums import Source
from app.domain.trading.events import (
    TickReceived, AnalysisCompleted, PredictionCompleted,
    SignalGenerated, PositionOpened, PositionClosed,
)
from app.domain.ports.event_bus import EventBusPort
from app.domain.ports.broker import BrokerPort
from app.domain.ports.storage import StoragePort
from app.domain.trading.services.signal_generator import SignalGenerator
from app.domain.trading.services.risk_manager import RiskManager
from app.domain.fabio_ai.services.learning_engine import LearningEngine
from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService

from app.application.handlers.amt_handler import AMTHandler
from app.application.handlers.llm_entry_handler import LLMEntryHandler
from app.application.handlers.trade_lifecycle_handler import TradeLifecycleHandler
from app.application.handlers.rl_handler import RLHandler

from app.infrastructure.serialization.schemas import portfolio_to_dto, stats_to_dto

log = logging.getLogger(__name__)


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

    # LLM throttling state
    _last_ai_time: float = 0
    _ai_running: bool = False

    # Thread safety lock for portfolio reads/writes
    _lock: threading.Lock = field(default_factory=threading.Lock)


class TradingSessionService:
    """Application service coordinating the event-driven trading pipeline."""

    def __init__(
        self,
        event_bus: EventBusPort,
        broker: BrokerPort,
        gen_ai_service: GenerativeAIService,
        storage: StoragePort | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._broker = broker
        self._storage = storage

        # Domain services
        self._signal_generator = SignalGenerator()
        self._risk_manager = RiskManager()

        # Focused handlers
        self._amt_handler = AMTHandler()
        self._llm_handler = LLMEntryHandler(gen_ai_service, event_bus, storage=storage)
        self._lifecycle_handler = TradeLifecycleHandler()
        self._rl_handler = RLHandler()

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

    def process_tick(
        self, symbol: str, tick: OHLC, order_book: OrderBook | None = None,
    ) -> dict:
        """Process a new tick and return the current state snapshot."""
        session = self.get_or_create_session(symbol)

        # Update data store
        session.data.append(tick)
        if len(session.data) > 1000:
            del session.data[:len(session.data) - 1000]
        session.order_book = order_book

        # Persist tick
        if self._storage:
            try:
                self._storage.save_tick(symbol, {
                    "time": tick.time, "open": tick.open, "high": tick.high,
                    "low": tick.low, "close": tick.close, "volume": tick.volume,
                    "delta": tick.delta,
                })
            except Exception:
                log.debug("Failed to persist tick", exc_info=True)

        # Process tick in portfolio (SL/TP exits from Portfolio itself)
        with session._lock:
            closed_positions = session.portfolio.process_tick(tick)
        for pos in closed_positions:
            self._risk_manager.record_trade_result(pos.pnl, session.portfolio)
            self._event_bus.publish(PositionClosed(symbol=symbol, position=pos))
            if self._storage:
                try:
                    self._storage.save_trade({
                        "position_id": pos.id, "symbol": symbol,
                        "side": pos.side.value if hasattr(pos.side, 'value') else str(pos.side),
                        "entry_price": pos.entry_price, "exit_price": pos.exit_price,
                        "size": pos.size, "pnl": pos.pnl,
                        "source": pos.source.value if hasattr(pos.source, 'value') else str(pos.source),
                        "reason": pos.close_reason or "",
                        "opened_at": pos.opened_at, "closed_at": pos.closed_at,
                    })
                except Exception:
                    log.debug("Failed to persist trade", exc_info=True)

        # Sync portfolio-closed positions to TradeManager to prevent double-close
        if closed_positions:
            self._lifecycle_handler.sync_closed(closed_positions)
            # Snapshot equity after trade closes (for performance tracking)
            if self._storage:
                try:
                    stats = session.portfolio.get_stats(Source.LLM)
                    self._storage.save_performance_snapshot({
                        "symbol": symbol,
                        "equity": session.portfolio.equity,
                        "balance": session.portfolio.balance,
                        "open_pnl": sum(p.pnl for p in session.portfolio.positions if p.status == "OPEN"),
                        "open_positions": len([p for p in session.portfolio.positions if p.status == "OPEN"]),
                        "total_trades": stats.total_trades,
                        "win_rate": stats.win_rate,
                    })
                except Exception:
                    log.debug("Failed to persist performance snapshot", exc_info=True)

        # Publish the main tick event (triggers analysis chain)
        self._event_bus.publish(TickReceived(
            symbol=symbol, tick=tick,
            order_book=order_book,
            data=tuple(session.data),
        ))

        return self._build_state_snapshot(session)

    def create_portfolio(self) -> Portfolio:
        return Portfolio.create_default()

    # ----- event handlers -----

    def _on_tick(self, event: TickReceived) -> None:
        session = self.get_or_create_session(event.symbol)

        # 1. AMT Analysis + Footprint
        amt_result, amt_dto, fp_dto = self._amt_handler.analyze(
            list(event.data), event.order_book,
        )
        session.last_amt = amt_dto
        session.last_footprint = fp_dto

        # 2. Trade Lifecycle (exits via TradeManager)
        with session._lock:
            position_closed = self._lifecycle_handler.check_exits(
                session.portfolio, event.tick.close,
            )
            has_position = any(p.status == "OPEN" for p in session.portfolio.positions)

        # 3. LLM Entry Decision (throttled)
        if self._llm_handler.should_run(
            last_ai_time=session._last_ai_time,
            ai_running=session._ai_running,
            has_position=has_position,
            has_managed_positions=self._lifecycle_handler.has_managed_positions,
            in_cooldown=self._lifecycle_handler.in_cooldown(),
            data=session.data,
            amt_result=amt_result,
            tick=event.tick,
        ):
            self._llm_handler.run_entry(session, event.symbol, event.tick, amt_result)
        elif not has_position and not session._ai_running:
            if self._lifecycle_handler.in_cooldown():
                cooldown_status = session.last_ai_analysis or {}
                cooldown_status["direction"] = "FLAT"
                cooldown_status["rationale"] = (
                    cooldown_status.get("rationale", "")
                    + " [Cooldown — waiting before next entry]"
                )
                session.last_ai_analysis = cooldown_status

    def _on_analysis_completed(self, event: AnalysisCompleted) -> None:
        signal = self._signal_generator.evaluate_amt(event.result)
        if signal:
            self._event_bus.publish(SignalGenerated(symbol=event.symbol, signal=signal))

    def _on_prediction_completed(self, event: PredictionCompleted) -> None:
        if not event.analysis:
            return
        session = self.get_or_create_session(event.symbol)
        if not session.data:
            return
        signal = self._signal_generator.evaluate_prediction(
            event.analysis, session.data[-1], event.generation,
        )
        if signal:
            self._event_bus.publish(SignalGenerated(symbol=event.symbol, signal=signal))

    def _on_signal_generated(self, event: SignalGenerated) -> None:
        if not event.signal:
            return
        session = self.get_or_create_session(event.symbol)
        if not self._risk_manager.validate(event.signal, session.portfolio):
            return
        position = self._broker.execute_order(event.signal, session.portfolio, event.symbol)
        if position:
            self._event_bus.publish(PositionOpened(symbol=event.symbol, position=position))
            self._lifecycle_handler.register_position(position, event.signal)

    def _on_position_closed(self, event: PositionClosed) -> None:
        if not event.position:
            return
        session = self.get_or_create_session(event.symbol)
        session.learning.learn(event.position)

    # ----- state snapshot -----

    def _build_state_snapshot(self, session: SessionState) -> dict:
        portfolio = session.portfolio
        weights = session.learning.weights

        with session._lock:
            ai_analysis = session.last_ai_analysis

        return {
            "_symbol": session.symbol,
            "portfolio": portfolio_to_dto(portfolio),
            "amt": session.last_amt,
            "prediction": session.last_prediction,
            "footprint": session.last_footprint,
            "genAIAnalysis": self._camel_case_ai(ai_analysis),
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
            "rlStatus": self._rl_handler.get_status(),
            "riskState": {
                "halted": self._risk_manager.is_halted,
                "haltReason": self._risk_manager.halt_reason,
                "consecutiveLosses": self._risk_manager.daily_state.consecutive_losses,
                "dailyPnl": self._risk_manager.daily_state.realized_pnl,
            },
        }

    @staticmethod
    def _camel_case_ai(data: dict | None) -> dict | None:
        if not data:
            return data
        return {
            "direction": data.get("direction", "FLAT"),
            "rationale": data.get("rationale", ""),
            "confidence": data.get("confidence", "Medium"),
            "inputPrompt": data.get("input_prompt", ""),
            "rawOutput": data.get("raw_output", ""),
            "marketState": data.get("market_state", "Unknown"),
            "aggression": data.get("aggression", ""),
        }
