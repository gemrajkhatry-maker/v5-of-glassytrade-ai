"""TradingSession — thin coordinator delegating to focused handlers.

Manages per-symbol state, wires event subscriptions, and delegates:
  - AMT analysis        → AMTHandler
  - Trade exits         → TradeLifecycleHandler
  - LLM entry decisions → LLMEntryHandler
  - RL status           → RLHandler
  - Session state       → SessionStateManager
  - Risk management     → SessionRiskCoordinator
  - Event logging       → SessionEventLogger
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal
import logging
import threading
import time
from typing import TYPE_CHECKING

from app.config import settings
from app.domain.constants import (
    AGENT_DECISION_THRESHOLD,
    CONFIDENCE_HIGH_THRESHOLD,
    RECENT_DATA_WINDOW,
    CANDLE_INTERVAL_MINUTES,
)
from app.domain.trading.models.value_objects import OHLC, OrderBook
from app.domain.trading.models.aggregates import Portfolio
from app.domain.trading.models.enums import MarketStateCodec, Source
from app.domain.trading.events import (
    TickReceived,
    SignalGenerated,
    PositionOpened,
    PositionClosed,
)
from app.domain.ports.broker import BrokerPort
from app.domain.ports.storage import StoragePort
from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService
from app.domain.ports.probability_inference import (
    ProbabilityInferencePort,
    NoOpProbabilityAdapter,
)

from app.application.handlers.amt_handler import AMTHandler
from app.application.handlers.llm_entry_handler import LLMEntryHandler
from app.application.handlers.trade_lifecycle_handler import TradeLifecycleHandler
from app.application.handlers.rl_handler import RLHandler
from app.application.handlers.llm_overseer_handler import LLMOverseerHandler
from app.application.handlers.pre_candle_advisor import PreCandleAdvisor
from app.domain.fabio_ai.services.option_selector import OptionSelector
from app.domain.fabio_ai.services.trade_thesis import validate_trade_thesis
from app.domain.fabio_ai.services.entry_gate import build_entry_signal
from app.application.services.entry_coordinator import EntryCoordinator
from app.application.services.exit_coordinator import ExitCoordinator

# Import delegated modules
from app.application.services.session_state_manager import (
    SessionStateManager,
    SessionState,
)
from app.application.services.session_risk_coordinator import (
    SessionRiskCoordinator,
    SystemRiskState,
)
from app.application.services.session_event_logger import SessionEventLogger

# Import extracted modules
from app.application.services.state_snapshot_builder import build_state_snapshot
from app.application.services.session_cache import SessionCache
from app.application.services.session_event_router import SessionEventRouter

# Import error handling utilities
from shared.error_handling import (
    handle_errors,
    safe_execute,
    ErrorContext,
    log_and_continue,
    TradingError,
    StorageError,
)

# Import safe parsing utilities
from app.shared.parsing import is_mcx_symbol, extract_bar_minute

from app.infrastructure.serialization.schemas import portfolio_to_dto, stats_to_dto

log = logging.getLogger(__name__)

# Cap candle history per symbol to bound memory in long-running sessions.
MAX_CANDLES_PER_SYMBOL = 2000


class TradingSessionService:
    """Application service coordinating the event-driven trading pipeline."""

    def __init__(
        self,
        broker: BrokerPort,
        gen_ai_service: GenerativeAIService,
        storage: StoragePort | None = None,
        amt_handler: AMTHandler | None = None,
        probability_engine: ProbabilityInferencePort | None = None,
        exchange_config=None,  # ExchangeConfig — injected from ServiceGraph
        allow_short: bool = False,
        gate_tracker=None,  # GateRejectionTracker — observability
        latency_tracker=None,  # LatencyTracker — observability
        signal_tracker=None,  # SignalTracker (from app.api) — gate rejection history
    ) -> None:
        self._broker = broker
        self._storage = storage
        self._probability_engine = probability_engine or NoOpProbabilityAdapter()
        self._gate_tracker = gate_tracker
        self._latency_tracker = latency_tracker
        self._signal_tracker = signal_tracker

        # Injected config — replaces inline Settings() calls
        self._exchange_config = exchange_config
        self._exchange = exchange_config.exchange if exchange_config else "MCX"
        self._allow_short = (
            allow_short  # Use injected allow_short (from settings.ALLOW_SHORT)
        )

        # Delegated modules
        self._state_manager = SessionStateManager(storage=storage)
        self._risk_coordinator = SessionRiskCoordinator(
            storage=storage,
            capital=float(getattr(settings, "CAPITAL", 5000000)),
            use_risk_tier_engine=getattr(settings, "RISK_TIER_ENGINE", False),
        )
        self._event_logger = SessionEventLogger(storage=storage)

        # Focused handlers — per-symbol AMT handlers (VP state is per-instrument)
        self._amt_handlers: dict[str, AMTHandler] = {}
        self._default_amt_handler = amt_handler  # used as template for config

        # Crash-safe state persistence via storage kv_set/kv_get
        def _persist_fn(key: str, value: str | None = None) -> str | None:
            if not self._storage or not hasattr(self._storage, "kv_set"):
                return None
            if value is None:
                return self._storage.kv_get(key)
            self._storage.kv_set(key, value)
            return None

        self._lifecycle_handler = TradeLifecycleHandler(
            on_stop_out=self._on_stop_out,
            on_partial_exit=self._on_partial_exit,
            persist_fn=_persist_fn,
            on_trade_closed=lambda sym, pnl, pos_id=None: self._on_trade_closed(
                sym, pnl, pos_id
            ),
        )

        self._llm_handler = LLMEntryHandler(
            gen_ai_service,
            storage=storage,
            trade_manager=self._lifecycle_handler.trade_manager,
            journal=self._event_logger._journal,
            exchange=self._exchange,
            allow_short=self._allow_short,
            llm_timeout=float(getattr(settings, "LLM_TIMEOUT_SECONDS", 15)),
        )
        self._rl_handler = RLHandler()

        self._overseer_handler = LLMOverseerHandler(
            gen_ai_service,
            trade_manager=self._lifecycle_handler.trade_manager,
            storage=storage,
            probability_engine=self._probability_engine,
        )

        # Option selector for NSE options signal enrichment
        self._option_selector = OptionSelector()

        # Post-Trade Analyst (Phase 3) — must be created before ExitCoordinator
        from app.application.handlers.post_trade_analyst import PostTradeAnalyst

        self._post_trade_analyst = PostTradeAnalyst(
            gen_ai_service=gen_ai_service,
            storage=storage,
            enabled=getattr(settings, "LLM_POST_TRADE", True),
        )

        # Exit Coordinator — extracted exit callback logic
        self._exit_coordinator = ExitCoordinator(
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

        # Entry Coordinator — extracted signal execution logic
        self._entry_coordinator = EntryCoordinator(
            broker=broker,
            lifecycle_handler=self._lifecycle_handler,
            event_logger=self._event_logger,
            storage=storage,
            risk_coordinator=self._risk_coordinator,
            option_selector=self._option_selector,
            state_manager=self._state_manager,
        )

        # Pre-Candle Advisor — non-blocking advisory for dashboard (T-60s before bar close)
        self._pre_candle_advisor = PreCandleAdvisor(
            gen_ai_service=gen_ai_service,
            enabled=getattr(settings, "LLM_PRE_CANDLE_ADVISORY", True),
        )

        # Scalping components (Phase 4)
        self._scalp_enabled = getattr(settings, "SCALP_ENGINE_ENABLED", False)
        self._one_min_engines: dict = {}
        self._fifteen_sec_engines: dict = {}
        self._ib_scalp_engines: dict = {}

        # Mobile alerts (Phase 5)
        from app.domain.services.mobile_alerts import MobileAlertSystem

        self._alerts = MobileAlertSystem(
            bot_token=getattr(settings, "TELEGRAM_BOT_TOKEN", ""),
            chat_id=getattr(settings, "TELEGRAM_CHAT_ID", ""),
        )

        # Self-healing (Phase 5)
        from app.domain.services.self_healing import (
            OrderRejectionHandler,
            DBFallbackBuffer,
        )

        self._order_rejection = OrderRejectionHandler()
        self._db_fallback = DBFallbackBuffer()

        # Event Router — delegates all handler calls
        self._event_router = SessionEventRouter(
            lifecycle_handler=self._lifecycle_handler,
            llm_handler=self._llm_handler,
            overseer_handler=self._overseer_handler,
            entry_coordinator=self._entry_coordinator,
            exit_coordinator=self._exit_coordinator,
            broker=broker,
            storage=storage,
            risk_coordinator=self._risk_coordinator,
            probability_engine=self._probability_engine,
            exchange_config=exchange_config,
            exchange=self._exchange,
            allow_short=self._allow_short,
            gate_tracker=gate_tracker,
            signal_tracker=signal_tracker,
            scalp_enabled=self._scalp_enabled,
        )

        # Per-session caches (created on demand)
        self._session_caches: dict[str, SessionCache] = {}

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
        self._state_manager._maybe_reset_symbol_state(session, symbol, tick.time)

        # Drain pending signal from LLM worker thread + update tick time
        cache.update_tick_time()
        pending = cache.drain_pending_signal()
        if pending:
            pending_symbol, pending_signal = pending

            # Audit Fix: Signal TTL — ignore stale signals older than 10 minutes
            from datetime import datetime

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
        if pending:
            self._event_router.execute_signal(pending_symbol, pending_signal, session)

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

        # Call entry logic directly (avoids event bus overhead)
        try:
            tick_event = TickReceived(
                symbol=symbol,
                tick=tick,
                order_book=order_book,
                data=tuple(session.data),
            )
            self._on_tick(tick_event)
        except (ValueError, RuntimeError) as e:
            log.warning("Entry logic error for %s: %s", symbol, e, exc_info=True)

        return self._build_state_snapshot(session)

    def create_portfolio(self) -> Portfolio:
        return Portfolio.create_default()

    # ----- event handlers -----

    def _session_phase_check(self, event: TickReceived, session, cache: SessionCache) -> None:
        """Check session phase and force-exit positions if Phase 5 (15:15-15:30 IST)."""
        from datetime import datetime
        from app.domain.fabio_ai.services.session_context import (
            get_session_info as _get_si,
        )
        from app.shared.timezones import IST
        from app.domain.fabio_ai.services.entry_gate import cluster_aggressive_prints

        try:
            _market = self._exchange
            if _market in ("NFO", "BSE"):
                _market = "NSE"
            session_phase = _get_si(timestamp=event.tick.time, market=_market)
            cache.set_last_session_info(session_phase)
            if session_phase.force_exit:
                with session._lock:
                    open_positions = [
                        p for p in session.portfolio.positions if p.status == "OPEN"
                    ]
                    for pos in open_positions:
                        # Calculate realized PnL before closing
                        _close_price = event.tick.close
                        realized_pnl = (
                            (_close_price - pos.entry_price) * pos.size
                            if pos.side.value == "LONG"
                            else (pos.entry_price - _close_price) * pos.size
                        )

                        session.portfolio.close_position(
                            pos.id,
                            _close_price,
                            "SESSION_CLOSE (Phase 5: 15:15 IST)",
                        )

                        # Record PnL for session tracking — MUST happen AFTER close_position
                        # to ensure closed_trades list is updated
                        if session and session.portfolio:
                            self._risk_coordinator.record_trade_result(
                                event.symbol, float(realized_pnl), session.portfolio
                            )
                        self._exit_coordinator.on_position_closed(event.symbol, None)

                        # Clear partition state for the closed position
                        self._lifecycle_handler.clear_partition_state(pos.id)
                        if self._storage:
                            try:
                                self._storage.delete_open_position(pos.id)
                            except Exception as e:
                                log.error(
                                    "Failed to delete open position %s: %s", pos.id, e
                                )
                        log.info(
                            "Session Phase 5: force-closed position %s at %.2f (pnl=%.2f)",
                            pos.id,
                            _close_price,
                            realized_pnl,
                        )

                if (
                    self._storage
                    and cache.get_latest_amt()
                    and not getattr(session, "_profile_saved", False)
                ):
                    try:
                        session_date = datetime.now(IST).strftime("%Y-%m-%d")
                        _agg_prints = cache.get_aggressive_prints()
                        _print_clusters = (
                            cluster_aggressive_prints(tuple(_agg_prints))
                            if _agg_prints
                            else []
                        )
                        last_amt = cache.get_latest_amt()
                        profile_data = {
                            "symbol": event.symbol,
                            "market": _market,
                            "session_date": session_date,
                            "poc": last_amt.get("poc", 0),
                            "vah": last_amt.get("vah", 0),
                            "val": last_amt.get("val", 0),
                            "profile_shape": last_amt.get("profileShape", ""),
                            "total_volume": sum(d.volume for d in cache.get_data()[-RECENT_DATA_WINDOW:]),
                            "print_levels": [
                                {"price": p, "side": "MIXED"}
                                for p in _print_clusters[:5]
                            ],
                            "is_underlying": cache.has_underlying_data(),
                        }
                        self._storage.save_session_profile(profile_data)
                        cache.set_profile_saved(True)
                        log.info(
                            "Saved session profile for %s on %s",
                            event.symbol,
                            session_date,
                        )
                    except Exception as e:
                        log.error(
                            "Failed to save session profile: %s", e, exc_info=True
                        )
        except Exception as e:
            log.critical(
                "Session phase check CRITICAL failure for %s — FORCING EXIT ALL POSITIONS",
                event.symbol,
                exc_info=True,
            )
            exit_price = getattr(event.tick, "close", None)
            with session._lock:
                for pos in list(session.portfolio.positions):
                    try:
                        # Calculate realized PnL before closing
                        _ep = exit_price if exit_price is not None else 0
                        _er_pnl = (
                            (_ep - pos.entry_price) * pos.size
                            if pos.side.value == "LONG"
                            else (pos.entry_price - _ep) * pos.size
                        )

                        session.portfolio.close_position(
                            pos.id,
                            exit_price if exit_price is not None else Decimal("0"),
                            "EMERGENCY_SESSION_PHASE",
                        )

                        # Record PnL for session tracking
                        if session and session.portfolio:
                            self._risk_coordinator.record_trade_result(
                                event.symbol, float(_er_pnl), session.portfolio
                            )
                        self._exit_coordinator.on_position_closed(event.symbol, None)
                    except Exception as close_err:
                        log.error(
                            "Failed to emergency close position %s: %s",
                            pos.id,
                            close_err,
                        )

    def _run_amt_analysis(self, event: TickReceived, session, prior, cache: SessionCache) -> object:
        """Run AMT analysis with data source selection and prior profile injection."""
        # Dual feed: use underlying futures data for AMT analysis (only if we have enough data)
        amt_data = list(event.data)
        if cache.has_underlying_data(20):
            amt_data = cache.get_underlying_data()
        elif amt_data:
            log.debug(
                "AMT: using option premium data for %s (no underlying futures available) — VAH/VAL will be in premium units",
                event.symbol,
            )

        srm = self._risk_coordinator.get_session_risk_manager(event.symbol)
        try:
            amt_result, amt_dto, fp_dto = self._amt_handlers[event.symbol].analyze(
                amt_data,
                event.order_book,
                prior_poc=prior.get("poc", 0.0) if prior else 0.0,
                prior_vah=prior.get("vah", 0.0) if prior else 0.0,
                prior_val=prior.get("val", 0.0) if prior else 0.0,
                cushion_tier=srm.risk_tier.name if srm else "NORMAL",
                session_pnl=srm.session_pnl if srm else 0.0,
                option_tick=event.tick,
            )
        except Exception:
            log.error(
                "AMT analysis failed for %s — skipping tick",
                event.symbol,
                exc_info=True,
            )
            return None

        # Update cache with AMT results
        cache.update_amt(amt_result, amt_dto, fp_dto)

        log.info(
            "AMT analysis done for %s: poc=%.2f vah=%.2f val=%.2f agg=%.2f ofi=%.3f cvd=%.1f state=%s ibH=%.2f ibL=%.2f",
            event.symbol,
            amt_dto.get("poc", 0),
            amt_dto.get("valueAreaHigh", 0),
            amt_dto.get("valueAreaLow", 0),
            amt_dto.get("aggression", 0),
            amt_dto.get("ofi", 0),
            amt_dto.get("cvdSlope", 0),
            amt_dto.get("marketState", "N/A"),
            amt_dto.get("ibHigh", 0),
            amt_dto.get("ibLow", 0),
        )

        return amt_result

    def _resolve_entry_decision(
        self, agent_decision, cache: SessionCache, is_new_candle, has_position, _in_cooldown
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
        import time as _tick_time

        _tick_start = _tick_time.monotonic()
        session = self.get_or_create_session(event.symbol)
        cache = self._get_cache(event.symbol)

        # Initialize IB engine for this symbol if not exists
        if not hasattr(self, "_ib_engines"):
            self._ib_engines = {}
        if event.symbol not in self._ib_engines:
            from app.domain.services.initial_balance_engine import InitialBalanceEngine

            self._ib_engines[event.symbol] = InitialBalanceEngine(
                ib_minutes=30 if self._exchange == "NSE" else 30,
            )

        # 0. Session phase check + profile save
        self._session_phase_check(event, session, cache)

        # 1. AMT Analysis + Footprint
        prior = getattr(session, "_prior_profile", None)
        if event.symbol not in self._amt_handlers:
            self._amt_handlers[event.symbol] = AMTHandler()

        amt_result = self._run_amt_analysis(event, session, prior, cache)
        if amt_result is None:
            # AMT failure — use a minimal sentinel so downstream exit/position
            # management still runs.  Entering new positions requires valid AMT,
            # but exits and overseer checks must not be disabled by an AMT error.
            log.warning(
                "AMT analysis failed for %s — continuing with exits/overseer only",
                event.symbol,
            )
            from app.domain.trading.models.value_objects import AMTResult
            from app.domain.trading.models.enums import MarketState

            amt_result = AMTResult(
                market_state=MarketState.BALANCED.value,
                poc=0.0,
                value_area_high=0.0,
                value_area_low=0.0,
            )

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
                    from app.domain.services.ib_breakout_scalp import (
                        IBBreakoutScalpEngine,
                    )

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
                from app.domain.services.one_min_bar_engine import OneMinBarEngine

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
            pass  # Advisory is non-critical

        # Record level approaches for second drive tracking
        if hasattr(self._llm_handler, "_regime_detector"):
            key_levels = [
                amt_result.poc,
                amt_result.value_area_high,
                amt_result.value_area_low,
            ]
            if amt_result.lvns:
                key_levels.extend(amt_result.lvns[:3])
            self._llm_handler._regime_detector.record_level_approach(
                event.tick.close,
                key_levels,
                time.time(),
            )

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
                log.debug("Silent exception handled", exc_info=True)

        # 2. Trade Lifecycle + Overseer + Entry decisions
        with session._lock:
            try:
                self._lifecycle_handler.check_exits(
                    session.portfolio,
                    symbol=event.symbol,
                    current_price=event.tick.close,
                    cvd_divergence=amt_result.cvd_divergence,
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
            if (
                agent_decision
                and agent_decision.direction != "FLAT"
                and agent_decision.probability >= AGENT_DECISION_THRESHOLD
            ):
                cache.set_pending_decision(agent_decision, amt_result, event.tick)

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
                    agent_decision, cache, is_new_candle, has_position, _in_cooldown
                )
            )
            trigger_llm = self._event_router.should_trigger_llm(
                session,
                has_position,
                ai_running,
                _in_cooldown,
                amt_result,
                event,
                ai_time,
            )

        self._event_router.run_overseer_if_needed(session, event, amt_result, self._exchange)

        # 4a. Execute entry using proper AMT pipeline
        self._event_router.execute_entry_path(
            event, session, amt_result, _exec_dir, _exec_prob, run_entry,
            self._exchange_config, self._allow_short, self._risk_coordinator,
            self._scalp_enabled,
        )
        
        # 4b. Trigger LLM descriptor for UI
        # Monitoring-mode LLM: fire every 5 min in BALANCED/NO_TRADE for context
        import time as _time
        monitoring_trigger = (
            amt_result.market_state in ("BALANCED", "NO_TRADE")
            and (_time.time() - session._last_monitoring_llm) > 300
        )
        
        if (trigger_llm and is_new_candle) or monitoring_trigger:
            self._event_router.trigger_llm_entry(session, event.symbol, event.tick, amt_result)
            if monitoring_trigger:
                session._last_monitoring_llm = _time.time()
                logger.info(
                    "MONITORING LLM: Triggered context call for %s (state=%s)",
                    event.symbol,
                    amt_result.market_state,
                )

        elif not has_position and not ai_running and _in_cooldown:
            cooldown_status = cache.get_ai_analysis() or {}
            cooldown_status["direction"] = "FLAT"
            base_rationale = cooldown_status.get("rationale", "")
            base_rationale = base_rationale.split(" [Cooldown")[0]
            cooldown_status["rationale"] = (
                base_rationale + " [Cooldown — waiting before next entry]"
            )
            cache.set_ai_analysis(cooldown_status)

        # Record tick-to-signal latency
        if self._latency_tracker:
            elapsed_ms = (_tick_time.monotonic() - _tick_start) * 1000
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
        session = self._state_manager.get_or_create_session(symbol)
        self._event_router.on_trade_closed(symbol, pnl, pos_id, session)

    # ----- control-plane helpers -----

    def halt_trading(self) -> None:
        """Activate the global emergency kill switch."""
        self._risk_coordinator.halt_trading()

    def resume_trading(self) -> None:
        """Clear the global emergency kill switch."""
        self._risk_coordinator.resume_trading()

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
