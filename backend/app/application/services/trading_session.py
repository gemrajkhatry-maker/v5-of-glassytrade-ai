"""TradingSession — application service coordinating the event-driven trading pipeline.

Manages per-symbol state, wires event subscriptions, and delegates:
  - AMT analysis        → AMTService
  - Session phase       → PhaseManager
  - Trade exits         → TradeLifecycleHandler
  - LLM entry decisions → LLMEntryHandler
  - RL status           → RLHandler
  - Session state       → SessionStateManager
  - Risk management     → SessionRiskCoordinator
  - Event logging       → SessionEventLogger
"""

# Re-export types from sub-modules for backward compatibility
from app.application.services.session_risk_coordinator import SystemRiskState
from app.application.services.session_state_manager import (
    SessionStateManager,
    SessionState,
)
from app.application.services.session_cache import SessionCache
from app.application.services.session_event_logger import SessionEventLogger

__all__ = [
    "TradingSessionService",
    "SystemRiskState",
    "SessionStateManager",
    "SessionState",
    "SessionCache",
    "SessionEventLogger",
]

import logging
import time
from datetime import datetime

from app.config import settings
from app.shared.config_features import Feature, feature_enabled
from app.shared.mode import is_live_mode
from app.domain.constants import (
    AGENT_DECISION_THRESHOLD,
    CANDLE_INTERVAL_MINUTES,
    IB_MINUTES,
)
from app.domain.trading.models.value_objects import OHLC, OrderBook
from app.domain.trading.models.aggregates import Portfolio
from app.domain.trading.models.enums import Source, MarketState
from app.domain.trading.events import (
    TickReceived,
    SignalGenerated,
    PositionOpened,
    PositionClosed,
)
from app.domain.trading.event_store import EventBus
from app.domain.ports.broker import IBroker
from app.domain.ports.storage import IStorage
from app.domain.ports.notification_adapter import INotificationAdapter
from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService
from app.domain.ports.probability_inference import (
    IProbabilityInference,
    NoOpProbabilityAdapter,
)
from app.domain.services.initial_balance_engine import InitialBalanceEngine
from app.domain.services.ib_breakout_scalp import IBBreakoutScalpEngine
from app.domain.services.one_min_bar_engine import OneMinBarEngine
from app.domain.services.mobile_alerts import MobileAlertSystem
from app.domain.services.self_healing import OrderRejectionHandler, DBFallbackBuffer
from app.application.handlers.post_trade_analyst import PostTradeAnalyst

from app.application.handlers.llm_entry_handler import LLMEntryHandler
from app.application.handlers.trade_lifecycle_handler import TradeLifecycleHandler
from app.application.handlers.rl_handler import RLHandler
from app.application.handlers.llm_overseer_handler import LLMOverseerHandler
from app.application.handlers.pre_candle_advisor import PreCandleAdvisor
from app.domain.fabio_ai.services.option_selector import OptionSelector
from app.application.services.entry_coordinator import EntryCoordinator
from app.application.services.exit_coordinator import ExitCoordinator
from app.domain.services.risk_sizing_engine import RiskSizingEngine

# Import delegated modules (SessionStateManager already imported at top)
from app.application.services.session_risk_coordinator import (
    SessionRiskCoordinator,
    SystemRiskState,
)
from app.application.services.session_event_logger import SessionEventLogger

# Import extracted modules
from app.application.services.state_snapshot_builder import build_state_snapshot
from app.application.services.session_cache import SessionCache
from app.application.services.session_event_router import SessionEventRouter
from app.application.services.amt_service import AMTService
from app.application.services.phase_manager import PhaseManager
from app.infrastructure.adapters.telegram_adapter import TelegramAdapter

# Import safe parsing utilities
from app.shared.parsing import extract_bar_minute
from app.shared.timezones import IST

log = logging.getLogger(__name__)

# Cap candle history per symbol to bound memory in long-running sessions.
MAX_CANDLES_PER_SYMBOL = 2000


class TradingSessionService:
    """Application service coordinating the event-driven trading pipeline."""

    def __init__(
        self,
        broker: IBroker,
        gen_ai_service: GenerativeAIService,
        storage: IStorage | None = None,
        probability_engine: IProbabilityInference | None = None,
        exchange_config=None,  # ExchangeConfig — injected from ServiceGraph
        allow_short: bool = False,
        gate_tracker=None,  # GateRejectionTracker — observability
        latency_tracker=None,  # LatencyTracker — observability
        signal_tracker=None,  # SignalTracker (from app.api) — gate rejection history
        event_bus: EventBus | None = None,  # Event bus for pub/sub pipeline
        notification_adapter: INotificationAdapter | None = None,
    ) -> None:
        live_mode = is_live_mode()

        if probability_engine is None and live_mode:
            raise ValueError(
                "Probability engine is required in live mode; NoOp fallback blocked."
            )

        self._broker = broker
        self._storage = storage
        self._probability_engine = probability_engine or NoOpProbabilityAdapter()
        if isinstance(self._probability_engine, NoOpProbabilityAdapter) and live_mode:
            raise ValueError(
                "NoOp probability adapter is not allowed in live mode."
            )
        self._gate_tracker = gate_tracker
        self._latency_tracker = latency_tracker
        self._signal_tracker = signal_tracker

        # Injected config — replaces inline Settings() calls
        self._exchange_config = exchange_config
        self._exchange = exchange_config.exchange if exchange_config else "MCX"
        self._allow_short = (
            allow_short  # Use injected allow_short (from settings.ALLOW_SHORT)
        )

        # --- Construct collaborators (override in tests) ---
        self._state_manager = self._create_state_manager(storage)
        self._event_logger = self._create_event_logger(storage)
        self._lifecycle_handler = self._create_lifecycle_handler(storage)
        self._risk_coordinator = self._create_risk_coordinator(
            storage, trade_manager=self._lifecycle_handler.trade_manager
        )
        self._llm_handler = self._create_llm_handler(gen_ai_service, storage)
        self._overseer_handler = self._create_overseer_handler(gen_ai_service, storage, probability_engine)
        self._rl_handler = RLHandler()
        self._option_selector = OptionSelector()
        self._post_trade_analyst = self._create_post_trade_analyst(gen_ai_service, storage)
        self._exit_coordinator = self._create_exit_coordinator(broker, storage)
        self._phase_manager = self._create_phase_manager(storage)
        self._amt_service = AMTService(exchange=self._exchange)
        self._entry_coordinator = self._create_entry_coordinator(broker, storage)
        self._pre_candle_advisor = self._create_pre_candle_advisor(gen_ai_service)
        self._scalp_enabled = feature_enabled(settings, Feature.SCALP_ENGINE)
        self._one_min_engines: dict = {}
        self._fifteen_sec_engines: dict = {}
        self._ib_scalp_engines: dict = {}
        self._alerts = MobileAlertSystem(
            bot_token=settings.TELEGRAM_BOT_TOKEN,
            chat_id=settings.TELEGRAM_CHAT_ID,
            adapter=notification_adapter
            or TelegramAdapter(
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                chat_id=settings.TELEGRAM_CHAT_ID,
            )
        )
        self._order_rejection = OrderRejectionHandler()
        self._db_fallback = DBFallbackBuffer()
        self._event_router = self._create_event_router(broker, storage, exchange_config, probability_engine)
        self._session_caches: dict[str, SessionCache] = {}
        self._fut_to_options: dict[str, list[str]] = {}
        self._recorded_trade_ids: set[str] = set()

        # Event bus integration — when provided, pipeline events flow through pub/sub
        self._event_bus = event_bus
        if event_bus is not None:
            event_bus.subscribe("TickReceived", self._on_tick)
            log.info("Event bus activated: TickReceived → _on_tick subscribed")

    def get_or_create_session(self, symbol: str) -> SessionState:
        """Get or create a session for the symbol."""
        session = self._state_manager.get_or_create_session(symbol)
        # Ensure cache exists for this session
        if symbol not in self._session_caches:
            self._session_caches[symbol] = SessionCache(session)
        return session

    def _get_cache(self, symbol: str) -> SessionCache:
        """Get the SessionCache for a symbol."""
        if symbol not in self._session_caches:
            session = self._state_manager.get_or_create_session(symbol)
            self._session_caches[symbol] = SessionCache(session)
        return self._session_caches[symbol]

    # ------------------------------------------------------------------
    # Factory methods for collaborators — override in tests to swap adapters
    # ------------------------------------------------------------------

    def _create_state_manager(self, storage):
        return SessionStateManager(storage=storage)

    def _create_risk_coordinator(self, storage, trade_manager=None):
        return SessionRiskCoordinator(
            storage=storage,
            capital=settings.CAPITAL,
            use_risk_tier_engine=feature_enabled(settings, Feature.RISK_TIER_ENGINE),
            trade_manager=trade_manager,
        )

    def _create_event_logger(self, storage):
        return SessionEventLogger(storage=storage)

    def _create_lifecycle_handler(self, storage):
        def _persist_fn(key: str, value: str | None = None) -> str | None:
            if not self._storage or not hasattr(self._storage, "kv_set"):
                return None
            if value is None:
                return self._storage.kv_get(key)
            self._storage.kv_set(key, value)
            return None

        return TradeLifecycleHandler(
            on_stop_out=self._on_stop_out,
            on_partial_exit=self._on_partial_exit,
            persist_fn=_persist_fn,
            event_logger=self._event_logger,
            on_trade_closed=lambda sym, pnl, pos_id=None: self._on_trade_closed(
                sym, pnl, pos_id
            ),
        )

    def _create_llm_handler(self, gen_ai_service, storage):
        return LLMEntryHandler(
            gen_ai_service,
            storage=storage,
            trade_manager=self._lifecycle_handler.trade_manager,
            journal=self._event_logger._journal,
            exchange=self._exchange,
            allow_short=self._allow_short,
            llm_timeout=settings.LLM_TIMEOUT_SECONDS,
        )

    def _create_overseer_handler(self, gen_ai_service, storage, probability_engine):
        return LLMOverseerHandler(
            gen_ai_service,
            trade_manager=self._lifecycle_handler.trade_manager,
            storage=storage,
            probability_engine=probability_engine,
        )

    def _create_post_trade_analyst(self, gen_ai_service, storage):
        return PostTradeAnalyst(
            gen_ai_service=gen_ai_service,
            storage=storage,
            enabled=feature_enabled(settings, Feature.LLM_POST_TRADE),
        )

    def _create_exit_coordinator(self, broker, storage):
        return ExitCoordinator(
            broker=broker,
            lifecycle_handler=self._lifecycle_handler,
            event_logger=self._event_logger,
            overseer_handler=self._overseer_handler,
            state_manager=self._state_manager,
            storage=storage,
            llm_handler=self._llm_handler,
            risk_coordinator=self._risk_coordinator,
            post_trade_analyst=self._post_trade_analyst,
        )

    def _create_phase_manager(self, storage):
        return PhaseManager(
            exchange=self._exchange,
            storage=storage,
            lifecycle_handler=self._lifecycle_handler,
            risk_coordinator=self._risk_coordinator,
            exit_coordinator=self._exit_coordinator,
        )

    def _create_entry_coordinator(self, broker, storage):
        broker_exchange_config = getattr(broker, "get_exchange_config", None)
        exchange_cfg = broker_exchange_config() if broker_exchange_config else None
        return EntryCoordinator(
            broker=broker,
            lifecycle_handler=self._lifecycle_handler,
            event_logger=self._event_logger,
            storage=storage,
            risk_coordinator=self._risk_coordinator,
            option_selector=self._option_selector,
            state_manager=self._state_manager,
            sizing_engine=RiskSizingEngine(exchange_config=exchange_cfg),
        )

    def _create_pre_candle_advisor(self, gen_ai_service):
        return PreCandleAdvisor(
            gen_ai_service=gen_ai_service,
            enabled=feature_enabled(settings, Feature.LLM_PRE_CANDLE_ADVISORY),
        )

    def _create_event_router(self, broker, storage, exchange_config, probability_engine):
        return SessionEventRouter(
            lifecycle_handler=self._lifecycle_handler,
            llm_handler=self._llm_handler,
            overseer_handler=self._overseer_handler,
            entry_coordinator=self._entry_coordinator,
            exit_coordinator=self._exit_coordinator,
            broker=broker,
            storage=storage,
            risk_coordinator=self._risk_coordinator,
            probability_engine=probability_engine,
            exchange_config=exchange_config,
            exchange=self._exchange,
            allow_short=self._allow_short,
            gate_tracker=self._gate_tracker,
            signal_tracker=self._signal_tracker,
            scalp_enabled=self._scalp_enabled,
        )

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def set_futures_option_map(self, fut_to_options: dict[str, list[str]]) -> None:
        """Which option legs share each subscribed futures root (for dual feed)."""
        self._fut_to_options = dict(fut_to_options)

    def set_symbol_trading_state(
        self, symbol: str, state: str, reason: str | None = None
    ) -> None:
        """Mark a symbol as tradable/untradable for runtime governance."""
        session = self.get_or_create_session(symbol)
        session.trading_state = state
        session.trading_state_reason = reason

    def get_symbol_trading_state(self, symbol: str) -> str:
        """Return the current symbol trading state."""
        return getattr(self.get_or_create_session(symbol), "trading_state", "TRADABLE")

    def on_underlying_futures_candle(self, futures_symbol: str, ohlc: OHLC) -> None:
        """Apply one futures OHLC update to every mapped option session."""
        for opt in self._fut_to_options.get(futures_symbol, ()):
            cache = self._get_cache(opt)
            cache.update_underlying_data(ohlc)

    def seed_underlying_from_history(self, futures_symbol: str, history: list) -> None:
        """Warm underlying buffers from historical futures when live feed is still ramping."""
        if not history:
            return
        from app.application.services.session_cache import MAX_CANDLES_PER_SYMBOL

        for opt in self._fut_to_options.get(futures_symbol, ()):
            self.get_or_create_session(opt)
            self._get_cache(opt).seed_underlying_if_sparse(history, MAX_CANDLES_PER_SYMBOL)

    def process_tick(
        self,
        symbol: str,
        tick: OHLC,
        order_book: OrderBook | None = None,
        oi_data: dict | None = None,
        underlying_tick: OHLC | None = None,
    ) -> dict:
        """Process a new tick and return the current state snapshot.

        Args:
            symbol: Option contract symbol (e.g., "CRUDEOIL 16 APR 8900 CALL")
            tick: Option contract OHLC candle (for execution price)
            order_book: Current order book snapshot
            oi_data: Open interest data
            underlying_tick: Underlying futures OHLC candle (for AMT analysis)
        """
        session = self.get_or_create_session(symbol)
        cache = self._get_cache(symbol)
        trading_enabled = session.trading_state == "TRADABLE"
        self._state_manager._maybe_reset_symbol_state(session, symbol, tick.time)

        # Drain pending signal from LLM worker thread + update tick time
        cache.update_tick_time()
        pending = cache.drain_pending_signal()
        if pending:
            pending_symbol, pending_signal = pending

            # Audit Fix: Signal TTL — ignore stale signals older than 10 minutes
            try:
                sig_time = datetime.fromisoformat(
                    pending_signal.timestamp.replace("Z", "+00:00")
                )
                curr_time = datetime.fromisoformat(tick.time.replace("Z", "+00:00"))
                signal_age = (curr_time - sig_time).total_seconds()
                if signal_age > 600:
                    log.warning(
                        "Discarding stale signal for %s (age=%.0fs)", symbol, signal_age
                    )
                    pending = None
            except (ValueError, KeyError) as e:
                log.debug("Signal age check error: %s", e, exc_info=True)
        if pending and trading_enabled:
            self._event_router.execute_signal(pending_symbol, pending_signal, session)
        elif pending:
            log.debug(
                "Dropping queued signal for %s because trading is disabled",
                symbol,
            )

        # Update data store via SessionCache
        cache.update_candle_buffer(tick, self._storage, symbol)
        cache.update_underlying_data(underlying_tick)
        cache.set_order_book(order_book)

        # Process tick in portfolio
        with session._lock:
            closed_positions = session.portfolio.process_tick(tick)
            if closed_positions:
                _snap_equity = session.portfolio.equity
                _snap_balance = session.portfolio.balance
                _snap_open_pnl = sum(
                    p.pnl for p in session.portfolio.positions if p.status == "OPEN"
                )
                _snap_open_count = len(
                    [p for p in session.portfolio.positions if p.status == "OPEN"]
                )

        for pos in closed_positions:
            if pos.id in self._recorded_trade_ids:
                continue
            self._recorded_trade_ids.add(pos.id)
            self._risk_coordinator.record_trade_result(
                symbol, float(pos.pnl), session.portfolio
            )
            # Direct call to exit coordinator (avoids PositionClosed serialization bug)
            try:
                self._exit_coordinator.on_position_closed(
                    symbol=symbol,
                    position=pos,
                )
            except (RuntimeError, ValueError) as e:
                log.error("Exit check failed for %s: %s", symbol, e, exc_info=True)
            if self._storage:
                try:
                    self._storage.save_trade(
                        {
                            "position_id": pos.id,
                            "symbol": symbol,
                            "side": pos.side.value
                            if hasattr(pos.side, "value")
                            else str(pos.side),
                            "entry_price": pos.entry_price,
                            "exit_price": pos.exit_price,
                            "size": pos.size,
                            "pnl": pos.pnl,
                            "source": pos.source.value
                            if hasattr(pos.source, "value")
                            else str(pos.source),
                            "reason": pos.close_reason or "",
                            "opened_at": pos.entry_time,
                            "closed_at": pos.exit_time,
                        }
                    )
                except (OSError, Exception) as e:
                    log.error(
                        "Trade persistence failed: %s", e, exc_info=True
                    )

        # No sync needed — ExitEngine is stateless, Position entity holds lifecycle state
        # Record losses for stop-outs (session-level risk tracking)
        if closed_positions:
            for pos in closed_positions:
                if pos.close_reason and "Stop" in pos.close_reason:
                    self._lifecycle_handler.exit_engine.record_loss(pos.symbol)
            if self._storage:
                try:
                    stats = session.portfolio.get_stats(Source.LLM)
                    self._storage.save_performance_snapshot(
                        {
                            "symbol": symbol,
                            "equity": _snap_equity,
                            "balance": _snap_balance,
                            "open_pnl": _snap_open_pnl,
                            "open_positions": _snap_open_count,
                            "total_trades": stats.total_trades,
                            "win_rate": stats.win_rate,
                        }
                    )
                except (ValueError, KeyError) as e:
                    log.debug("Performance snapshot error: %s", e, exc_info=True)

        # Event dispatch: publish TickReceived via event bus (when active)
        # or fall back to direct method call (backward compatibility)
        try:
            _agent_series: tuple = ()
            if cache.has_underlying_data(20):
                _ud = cache.get_underlying_data()
                if _ud:
                    _agent_series = tuple(_ud)
            tick_event = TickReceived(
                symbol=symbol,
                tick=tick,
                order_book=order_book,
                data=tuple(session.data),
                agent_series=_agent_series,
            )
            if self._event_bus is not None:
                self._event_bus.publish(tick_event)
            else:
                self._on_tick(tick_event)
        except (ValueError, RuntimeError) as e:
            log.warning("Tick processing error for %s: %s", symbol, e, exc_info=True)

        return self._build_state_snapshot(session)

    def create_portfolio(self) -> Portfolio:
        return Portfolio.create_default()

    # ----- event handlers -----

    def _resolve_entry_decision(
        self,
        agent_decision,
        cache: SessionCache,
        is_new_candle,
        has_position,
        _in_cooldown,
        trading_enabled: bool = True,
    ):
        """Resolve entry decision from agent or pending, return execution params."""
        _allow_short = self._allow_short
        _exec_decision = None
        _exec_amt = None
        _exec_tick = None

        if (
            agent_decision
            and agent_decision.direction != "FLAT"
            and agent_decision.probability >= AGENT_DECISION_THRESHOLD
        ):
            _exec_decision = agent_decision
            if is_new_candle:
                log.info(
                    "ENTRY: New candle with valid decision: %s P=%.3f",
                    agent_decision.direction,
                    agent_decision.probability,
                )

        pending_decision, pending_amt, pending_tick = cache.get_pending_decision()
        if _exec_decision is None and pending_decision:
            if (
                pending_decision.direction != "FLAT"
                and pending_decision.probability >= AGENT_DECISION_THRESHOLD
            ):
                _exec_decision = pending_decision
                _exec_amt = pending_amt
                _exec_tick = pending_tick
                if is_new_candle:
                    log.info(
                        "ENTRY: Using pending decision on new candle: %s P=%.3f",
                        pending_decision.direction,
                        pending_decision.probability,
                    )

        if not trading_enabled:
            _exec_decision = None
            _exec_amt = None
            _exec_tick = None
            _exec_prob = 0
            _exec_dir = "NONE"

        _exec_dir = (
            getattr(_exec_decision, "direction", "NONE") if _exec_decision else "NONE"
        )
        _exec_prob = getattr(_exec_decision, "probability", 0) if _exec_decision else 0
        run_entry = (
            not has_position
            and not _in_cooldown
            and _exec_decision is not None
            and _exec_dir in ("LONG", "SHORT")
            and (_exec_dir != "SHORT" or _allow_short)
            and _exec_prob >= AGENT_DECISION_THRESHOLD
        )
        return _exec_decision, _exec_amt, _exec_tick, _exec_dir, _exec_prob, run_entry

    def _on_tick(self, event: TickReceived) -> None:
        _tick_start = time.monotonic()
        session = self.get_or_create_session(event.symbol)
        cache = self._get_cache(event.symbol)
        trading_enabled = session.trading_state == "TRADABLE"

        # Initialize IB engine for this symbol if not exists
        if not hasattr(self, "_ib_engines"):
            self._ib_engines = {}
        if event.symbol not in self._ib_engines:
            self._ib_engines[event.symbol] = InitialBalanceEngine(
                ib_minutes=IB_MINUTES,
            )

        # 0. Session phase check + profile save
        self._phase_manager.check_and_handle_phase(
            event, session, cache
        )

        # 1. AMT Analysis + Footprint
        prior = getattr(session, "_prior_profile", None)
        amt_result = self._amt_service.run_analysis(
            event, session, cache, self._risk_coordinator, prior
        )
        if amt_result is None:
            # AMT failure — use a minimal sentinel so downstream exit/position
            # management still runs.  Entering new positions requires valid AMT,
            # but exits and overseer checks must not be disabled by an AMT error.
            log.warning(
                "AMT analysis failed for %s — continuing with exits/overseer only",
                event.symbol,
            )
            amt_result = self._amt_service.create_sentinel_result()

        # Update IB engine — use underlying futures when available (Phase 1B)
        ib_tick = event.tick
        if cache.has_underlying_data(20):
            ib_tick = cache.get_underlying_data()[-1]

        ib_engine = self._ib_engines.get(event.symbol)
        if ib_engine:
            ib_state = ib_engine.update(ib_tick)
            cache.set_ib_state(ib_state)

            # IB Breakout Scalp evaluation (Phase 4)
            if self._scalp_enabled and ib_state.is_complete:
                if event.symbol not in self._ib_scalp_engines:
                    self._ib_scalp_engines[event.symbol] = IBBreakoutScalpEngine()
                scalp_sig = self._ib_scalp_engines[event.symbol].evaluate_setup_a(
                    ib_state=ib_state,
                    current_price=float(event.tick.close),
                    current_high=float(event.tick.high),
                    current_low=float(event.tick.low),
                    current_volume=float(event.tick.volume),
                    avg_volume=float(
                        getattr(amt_result, "baseline_volume", event.tick.volume)
                    ),
                    cvd_slope_1m=float(getattr(amt_result, "cvd_slope", 0)),
                    bar_index=len(cache.get_data()),
                    tick_size=self._exchange_config.get_tick_size(event.symbol)
                    if self._exchange_config
                    else 0.05,
                )
                if scalp_sig.setup_valid:
                    log.info(
                        "IB SCALP [%s] %s: entry=%.1f sl=%.1f tp=%.1f rr=%.1f",
                        event.symbol,
                        scalp_sig.scalp_type.value,
                        scalp_sig.entry_price,
                        scalp_sig.stop_loss,
                        scalp_sig.take_profit,
                        scalp_sig.rr_ratio,
                    )

        # Update 1-min bar engine (Phase 4)
        if self._scalp_enabled:
            if event.symbol not in self._one_min_engines:
                self._one_min_engines[event.symbol] = OneMinBarEngine()
            self._one_min_engines[event.symbol].update(
                symbol=event.symbol,
                price=float(event.tick.close),
                volume=float(event.tick.volume),
                delta=float(getattr(amt_result, "delta_normalized", 0))
                * float(event.tick.volume),
                timestamp=event.tick.time,
            )

        # Pre-candle advisory: fire T-60s before 5-min bar close (bar minute 4)
        try:
            bar_minute = extract_bar_minute(str(event.tick.time), CANDLE_INTERVAL_MINUTES)
            if self._pre_candle_advisor.should_fire(event.symbol, bar_minute):
                self._pre_candle_advisor.fire_advisory(
                    event.symbol, event.tick, amt_result
                )
        except Exception:
            log.debug("Pre-candle advisory failed (non-critical)", exc_info=True)

        # 1b. Micro-agent pipeline
        agent_decision = self._event_router.run_micro_agent_pipeline(event, amt_result, self._exchange_config)
        cache.set_agent_decision(agent_decision)

        # Extract stacked imbalances from footprint
        _imbalances = None
        _fp_domain = cache.get_fp_domain()
        if _fp_domain:
            try:
                _latest_fp = list(_fp_domain.values())[-1] if _fp_domain else None
                if _latest_fp and hasattr(_latest_fp, "levels"):
                    _imbalances = [
                        lv for lv in _latest_fp.levels if getattr(lv, "stacked", False)
                    ]
            except Exception:
                log.debug("Stacked imbalance extraction failed", exc_info=True)

        # 2. Trade Lifecycle + Overseer + Entry decisions
        with session._lock:
            try:
                self._lifecycle_handler.check_exits(
                    session.portfolio,
                    symbol=event.symbol,
                    current_price=event.tick.close,
                    tick_low=float(event.tick.low),
                    tick_high=float(event.tick.high),
                    cvd_divergence=amt_result.cvd_divergence,
                    cvd_slope=float(getattr(amt_result, "cvd_slope", 0)),
                    order_book=event.order_book,
                    amt_result=amt_result,
                    imbalances=_imbalances,
                )
            except Exception:
                log.error(
                    "check_exits failed for %s — assuming no position",
                    event.symbol,
                    exc_info=True,
                )
            has_position = session.portfolio.has_open_positions()

            overseer_time = session._last_overseer_time
            overseer_running = session._overseer_running
            ai_running = session._ai_running
            ai_time = session._last_ai_time
            run_overseer = has_position and self._overseer_handler.should_run(
                last_overseer_time=overseer_time,
                overseer_running=overseer_running,
                ai_running=ai_running,
                has_position=has_position,
            )

            # Track candle boundaries for entry evaluation
            is_new_candle = event.tick.time != cache.get_last_entry_candle_time()
            _in_cooldown = self._lifecycle_handler.in_cooldown(event.symbol)

            # SAVE last good decision for execution on next candle
            if trading_enabled:
                if (
                    agent_decision
                    and agent_decision.direction != "FLAT"
                    and agent_decision.probability >= AGENT_DECISION_THRESHOLD
                ):
                    cache.set_pending_decision(agent_decision, amt_result, event.tick)
            else:
                cache.clear_pending_decision()

            # Priority score for UI display only
            _priority_score = 0.0
            if agent_decision and agent_decision.direction != "FLAT":
                _priority_score += agent_decision.probability * 10
            if (
                getattr(amt_result, "cvd_slope", 0) > 0.4
                or getattr(amt_result, "cvd_slope", 0) < -0.4
            ):
                _priority_score += 2.0
            _squeeze = self._llm_handler._get_regime_detector(
                event.symbol
            ).detect_squeeze(cache.get_data(), amt_result)
            if _squeeze:
                _priority_score += 3.0
            cache.set_llm_priority_score(_priority_score)

            # UNIFIED ENTRY PATH — delegated to focused helper methods
            _exec_decision, _exec_amt, _exec_tick, _exec_dir, _exec_prob, run_entry = (
                self._resolve_entry_decision(
                    agent_decision,
                    cache,
                    is_new_candle,
                    has_position,
                    _in_cooldown,
                    trading_enabled=trading_enabled,
                )
            )
            trigger_llm = (
                trading_enabled
                and self._event_router.should_trigger_llm(
                session,
                has_position,
                ai_running,
                _in_cooldown,
                amt_result,
                event,
                ai_time,
                )
            )

        self._event_router.run_overseer_if_needed(session, event, amt_result, self._exchange)

        # 4a. Execute entry using proper AMT pipeline
        self._event_router.execute_entry_path(
            event, session, amt_result, _exec_dir, _exec_prob, run_entry,
            self._exchange_config, self._allow_short, self._scalp_enabled,
        )
        
        # 4b. Trigger LLM descriptor for UI
        # Monitoring-mode LLM: fire every 5 min in active market states for context
        _monitoring_interval = 300
        monitoring_trigger = (
            amt_result.market_state in ("BALANCED", "IMBALANCED")
            and (time.time() - session._last_monitoring_llm) > _monitoring_interval
        )
        
        if trading_enabled and ((trigger_llm and is_new_candle) or monitoring_trigger):
            session._llm_status = "RUNNING"
            self._event_router.trigger_llm_entry(session, event.symbol, event.tick, amt_result)
            if monitoring_trigger:
                session._last_monitoring_llm = time.time()
                log.info(
                    "MONITORING LLM: Triggered context call for %s (state=%s)",
                    event.symbol,
                    amt_result.market_state,
                )

        elif not has_position and not ai_running and _in_cooldown:
            session._llm_status = "COOLDOWN"
            cooldown_status = cache.get_ai_analysis() or {}
            prev_dir = cooldown_status.get("direction", "FLAT")
            cooldown_status["direction"] = "FLAT"
            base_rationale = cooldown_status.get("rationale", "")
            base_rationale = base_rationale.split(" [Cooldown")[0]
            
            if prev_dir != "FLAT":
                new_rationale = f"FLAT (COOLDOWN) — Original decision was {prev_dir}. {base_rationale} [Cooldown active]"
            else:
                new_rationale = base_rationale + " [Cooldown — waiting before next entry]"
                
            cooldown_status["rationale"] = new_rationale
            cooldown_status["llm_status"] = "COOLDOWN"
            cache.set_ai_analysis(cooldown_status)

        # Record tick-to-signal latency
        if self._latency_tracker:
            elapsed_ms = (time.monotonic() - _tick_start) * 1000
            self._latency_tracker.record(event.symbol, elapsed_ms)

    def _execute_signal(self, symbol: str, sig, session: SessionState) -> None:
        """Execute a trade signal — delegates to EventRouter."""
        self._event_router.execute_signal(symbol, sig, session)

    def _on_partial_exit(
        self,
        pos_id: str,
        side: str,
        entry_price: float,
        exit_price: float,
        partial_pct: float,
        size_closed: float,
        size_remaining: float,
        realized_pnl: float,
    ) -> None:
        """Callback from TradeLifecycleHandler — delegates to EventRouter."""
        self._event_router.on_partial_exit(
            pos_id,
            side,
            entry_price,
            exit_price,
            partial_pct,
            size_closed,
            size_remaining,
            realized_pnl,
        )

    def _on_stop_out(self, level: float, direction: str, symbol: str = "") -> None:
        """Callback from TradeLifecycleHandler — delegates to EventRouter."""
        self._event_router.on_stop_out(level, direction, symbol, self._exchange)

    def _on_trade_closed(self, symbol: str, pnl: float, pos_id: str | None = None) -> None:
        """Callback from TradeLifecycleHandler — records PnL for session tracking."""
        if pos_id and pos_id in self._recorded_trade_ids:
            return
        if pos_id:
            self._recorded_trade_ids.add(pos_id)
        session = self._state_manager.get_or_create_session(symbol)
        self._event_router.on_trade_closed(symbol, pnl, pos_id, session)

    # ----- control-plane helpers -----

    def halt_trading(self) -> None:
        """Activate the global emergency kill switch."""
        self._risk_coordinator.halt_trading()

    def resume_trading(self) -> None:
        """Clear the global emergency kill switch."""
        self._risk_coordinator.resume_trading()

    def cleanup(self) -> None:
        """Shutdown handler thread pools during application teardown.

        Must be called during FastAPI lifespan shutdown to prevent
        thread pool leaks (LLMEntryHandler, LLMOverseerHandler each
        hold _executor + _predict_executor ThreadPoolExecutors).
        """
        self._llm_handler.cleanup()
        self._overseer_handler.cleanup()

    def get_system_risk_state(self) -> SystemRiskState:
        """Return an aggregated system-wide view of runtime risk state."""
        return self._risk_coordinator.get_system_risk_state()

    def reset_playbook_guard(self, symbol: str | None = None) -> dict:
        """Clear playbook-guard rejections for one symbol or all active sessions."""
        return self._state_manager.reset_playbook_guard(symbol)

    # ----- state snapshot -----

    def _build_state_snapshot(self, session: SessionState) -> dict:
        return build_state_snapshot(
            session,
            self._risk_coordinator,
            self._rl_handler,
            self._lifecycle_handler,
        )

    # State snapshot helpers delegated to state_snapshot_builder module
