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

    def get_or_create_session(self, symbol: str) -> SessionState:
        """Get or create a session for the symbol."""
        return self._state_manager.get_or_create_session(symbol)

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
        self._state_manager._maybe_reset_symbol_state(session, symbol, tick.time)

        # Drain pending signal from LLM worker thread + update tick time
        with session._lock:
            session._last_tick_time = time.time()
            pending = session._pending_signal
            session._pending_signal = None
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
            self._execute_signal(pending_symbol, pending_signal, session)

        # Update data store (under lock — session.data is shared with LLM handler)
        with session._lock:
            new_candle = not (session.data and session.data[-1].time == tick.time)
            if not new_candle:
                session.data[-1] = tick
            else:
                if self._storage and session.data:
                    closed = session.data[-1]
                    try:
                        self._storage.save_tick(
                            symbol,
                            {
                                "time": closed.time,
                                "open": closed.open,
                                "high": closed.high,
                                "low": closed.low,
                                "close": closed.close,
                                "volume": closed.volume,
                                "delta": closed.delta,
                            },
                        )
                    except (OSError, Exception) as e:
                        log.warning("Failed to save tick for %s: %s", symbol, e, exc_info=True)
                session.data.append(tick)
                session._last_candle_time = tick.time
                if len(session.data) > MAX_CANDLES_PER_SYMBOL:
                    del session.data[: len(session.data) - MAX_CANDLES_PER_SYMBOL]

            # Store underlying futures data for AMT analysis (dual feed)
            if underlying_tick is not None:
                if not hasattr(session, "_underlying_data"):
                    session._underlying_data = []
                ut = underlying_tick
                ut_new = not (
                    session._underlying_data
                    and session._underlying_data[-1].time == ut.time
                )
                if not ut_new:
                    session._underlying_data[-1] = ut
                else:
                    session._underlying_data.append(ut)
                    if len(session._underlying_data) > MAX_CANDLES_PER_SYMBOL:
                        del session._underlying_data[
                            : len(session._underlying_data) - MAX_CANDLES_PER_SYMBOL
                        ]

            session.order_book = order_book

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

        # Sync portfolio-closed positions to TradeManager
        if closed_positions:
            for pos in closed_positions:
                if pos.close_reason and "Stop" in pos.close_reason:
                    self._lifecycle_handler.trade_manager.record_loss(pos.symbol)
            self._lifecycle_handler.sync_closed(closed_positions)
            self._record_position_consistency(
                session, symbol, context="post_portfolio_close"
            )
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

    def _record_position_consistency(
        self, session: SessionState, symbol: str, *, context: str
    ) -> None:
        """Audit and reconcile portfolio/lifecycle consistency for one symbol."""
        before = self._lifecycle_handler.get_position_consistency(
            session.portfolio, symbol=symbol
        )
        for stale_id in before.stale_managed_ids:
            self._event_logger.log_position_event(
                position_id=stale_id,
                symbol=symbol,
                event_type="RECONCILED_STALE",
                context=context,
            )
        if before.stale_managed_ids:
            self._lifecycle_handler.reconcile_portfolio(
                session.portfolio, symbol=symbol
            )

        after = self._lifecycle_handler.get_position_consistency(
            session.portfolio, symbol=symbol
        )
        if after.unmanaged_open_ids:
            log.error(
                "Position state mismatch after %s for %s: unmanaged_open_ids=%s",
                context,
                symbol,
                ",".join(after.unmanaged_open_ids),
            )
            for position_id in after.unmanaged_open_ids:
                self._event_logger.log_position_event(
                    position_id=position_id,
                    symbol=symbol,
                    event_type="STATE_MISMATCH_UNMANAGED_OPEN",
                    context=context,
                )

    # ----- event handlers -----

    def _run_micro_agent_pipeline(self, event: TickReceived, amt_result):
        """Run the micro-agent (LightGBM) pipeline for agent decision."""
        if not self._probability_engine.is_ready() or len(list(event.data)) < 20:
            return None
        try:
            from app.domain.probability.features import extract_features
            from app.domain.probability.agent_pipeline import run_agent_pipeline

            is_mcx = is_mcx_symbol(event.symbol)
            features = extract_features(
                list(event.data),
                amt_result,
                event.tick,
                event.order_book,
                is_mcx=is_mcx,
            )
            tick_size = (
                self._exchange_config.get_tick_size(event.symbol)
                if self._exchange_config
                else 0.05
            )
            agent_decision = run_agent_pipeline(
                data=list(event.data),
                amt_result=amt_result,
                tick=event.tick,
                probability_engine=self._probability_engine,
                features=features,
                order_book=event.order_book,
                tick_size=tick_size,
                symbol=event.symbol,
                tick_age_seconds=1.0,
            )
            log.info(
                "Agent pipeline [%s]: dir=%s P=%.3f regime=%s timing=%s kelly=%.1f%% (%dus) — %s",
                event.symbol,
                agent_decision.direction,
                agent_decision.probability,
                agent_decision.regime,
                agent_decision.timing,
                agent_decision.size_fraction * 100,
                agent_decision.latency_us,
                agent_decision.rationale,
            )
            return agent_decision
        except (ValueError, RuntimeError) as e:
            log.warning(
                "Agent pipeline error for %s: %s",
                event.symbol,
                e,
                exc_info=True,
            )
            return None

    def _session_phase_check(self, event: TickReceived, session) -> None:
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
            session._last_session_info = session_phase
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

                        self._lifecycle_handler.trade_manager.unregister_position(
                            pos.id
                        )
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
                    and session.last_amt
                    and not getattr(session, "_profile_saved", False)
                ):
                    try:
                        session_date = datetime.now(IST).strftime("%Y-%m-%d")
                        _agg_prints = getattr(session, "_last_aggressive_prints", None)
                        _print_clusters = (
                            cluster_aggressive_prints(tuple(_agg_prints))
                            if _agg_prints
                            else []
                        )
                        profile_data = {
                            "symbol": event.symbol,
                            "market": _market,
                            "session_date": session_date,
                            "poc": session.last_amt.get("poc", 0),
                            "vah": session.last_amt.get("vah", 0),
                            "val": session.last_amt.get("val", 0),
                            "profile_shape": session.last_amt.get("profileShape", ""),
                            "total_volume": sum(d.volume for d in session.data[-RECENT_DATA_WINDOW:]),
                            "print_levels": [
                                {"price": p, "side": "MIXED"}
                                for p in _print_clusters[:5]
                            ],
                            "is_underlying": hasattr(session, "_underlying_data")
                            and bool(session._underlying_data),
                        }
                        self._storage.save_session_profile(profile_data)
                        session._profile_saved = True
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

    def _run_amt_analysis(self, event: TickReceived, session, prior) -> object:
        """Run AMT analysis with data source selection and prior profile injection."""
        # Dual feed: use underlying futures data for AMT analysis (only if we have enough data)
        amt_data = list(event.data)
        if hasattr(session, "_underlying_data") and session._underlying_data and len(session._underlying_data) >= 20:
            amt_data = list(session._underlying_data)
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
            )
        except Exception:
            log.error(
                "AMT analysis failed for %s — skipping tick",
                event.symbol,
                exc_info=True,
            )
            return None

        with session._lock:
            session.last_amt = amt_dto
            session.last_footprint = fp_dto
            session._last_fp_domain = fp_dto
            session._last_aggressive_prints = amt_result.aggressive_prints

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
        self, agent_decision, session, is_new_candle, has_position, _in_cooldown
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

        if _exec_decision is None and getattr(session, "_pending_decision", None):
            pending = session._pending_decision
            if (
                pending.direction != "FLAT"
                and pending.probability >= AGENT_DECISION_THRESHOLD
            ):
                _exec_decision = pending
                _exec_amt = getattr(session, "_pending_amt", None)
                _exec_tick = getattr(session, "_pending_tick", None)
                if is_new_candle:
                    log.info(
                        "ENTRY: Using pending decision on new candle: %s P=%.3f",
                        pending.direction,
                        pending.probability,
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

    def _should_trigger_llm(
        self,
        session,
        has_position,
        ai_running,
        _in_cooldown,
        amt_result,
        event,
        ai_time,
    ):
        """Determine if LLM entry trigger should run."""
        return self._llm_handler.should_run(
            last_ai_time=ai_time,
            ai_running=ai_running,
            has_position=has_position,
            has_managed_positions=self._lifecycle_handler.has_managed_positions(
                event.symbol
            ),
            in_cooldown=_in_cooldown,
            last_entry_time=session._last_entry_time,
            data=session.data,
            amt_result=amt_result,
            tick=event.tick,
            order_book=event.order_book,
        )

    def _run_overseer_if_needed(self, session, event, amt_result):
        """Run overseer handler if positions exist."""
        if self._lifecycle_handler.has_managed_positions(event.symbol):
            _mkt = self._exchange
            if _mkt in ("NFO", "BSE"):
                _mkt = "NSE"
            from app.domain.fabio_ai.services.session_context import (
                get_session_info as _get_si,
            )

            _si = _get_si(timestamp=event.tick.time, market=_mkt)
            _fp_candle = None
            _fp_domain = getattr(session, "_last_fp_domain", None)
            if _fp_domain:
                try:
                    _fp_vals = (
                        list(_fp_domain.values())
                        if isinstance(_fp_domain, dict)
                        else None
                    )
                    _fp_candle = _fp_vals[-1] if _fp_vals else None
                except Exception:
                    log.debug("Silent exception handled", exc_info=True)
            self._overseer_handler.run_overseer(
                session,
                event.symbol,
                event.tick,
                amt_result,
                session_info=_si,
                footprint_candle=_fp_candle,
            )

    def _execute_entry_path(
        self, event, session, amt_result, _exec_dir, _exec_prob, run_entry
    ):
        """Execute entry path: gate pipeline, SHORT gates, signal build, persist."""
        import time as _time_mod

        _last_exec_mono = getattr(session, "_last_exec_mono", 0)
        _time_since_last = _time_mod.monotonic() - _last_exec_mono
        _can_execute = _time_since_last > 60

        if run_entry and _can_execute:
            srm = self._risk_coordinator.get_session_risk_manager(event.symbol)
            if srm and not srm.can_trade:
                log.info(
                    "ENTRY BLOCKED: %s — session risk: %s",
                    event.symbol,
                    srm.halt_reason,
                )
                return

            from app.domain.fabio_ai.services.entry_gate import run_gate_pipeline

            tick_size = (
                self._exchange_config.get_tick_size(event.symbol)
                if self._exchange_config
                else 0.05
            )

            gate_passed, gate_reason, gate_detail = run_gate_pipeline(
                data=list(event.data),
                amt_result=amt_result,
                tick=event.tick,
                market_state=amt_result.market_state,
                drive_number=getattr(amt_result, "drive_number", 0),
                drive_entry_valid=getattr(amt_result, "drive_entry_valid", False),
                aggression_score=amt_result.aggression,
                is_risk_halted=False,
                halt_reason="",
                tick_age_seconds=1.0,
                symbol=event.symbol,
                max_distance_to_level_ticks=self._exchange_config.max_distance_to_level_ticks
                if self._exchange_config
                else 3.0,
                probing_aggression_threshold=0.0,
                min_aggression_score=0.0,
                max_cushion_ticks=500.0,
                min_rr_ratio=0.1,
                tick_size=tick_size,
            )

            if gate_passed:
                if self._gate_tracker:
                    self._gate_tracker.record(event.symbol, "gate_pipeline", True)

                if _exec_dir == "SHORT":
                    from app.domain.services.short_signal_gates import (
                        evaluate_short_gates,
                    )

                    short_ok, short_results = evaluate_short_gates(
                        short_enabled=getattr(settings, "SHORT_SIGNALS_ENABLED", False),
                        market_state=amt_result.market_state,
                        displacement_direction=getattr(
                            amt_result, "displacement_direction", ""
                        ),
                        failed_breakout=getattr(amt_result, "failed_breakout", False),
                        playbook=str(amt_result.setup or "return_to_value"),
                        ml_probability=_exec_prob,
                        bid_volume=float(getattr(amt_result, "bid_volume", 0)),
                        ask_volume=float(getattr(amt_result, "ask_volume", 0)),
                        cvd_slope=float(getattr(amt_result, "cvd_slope", 0)),
                        delta_normalized=float(
                            getattr(amt_result, "delta_normalized", 0)
                        ),
                        contract_type="PE",
                    )
                    if not short_ok:
                        failed_gate = next(r for r in short_results if not r.passed)
                        log.info(
                            "SHORT BLOCKED: %s — %s (%s)",
                            event.symbol,
                            failed_gate.gate_name,
                            failed_gate.reason,
                        )
                        gate_passed = False
                        if self._gate_tracker:
                            self._gate_tracker.record(
                                event.symbol, failed_gate.gate_name, False
                            )

            if gate_passed:
                signal = build_entry_signal(
                    direction=_exec_dir,
                    tick=event.tick,
                    amt_result=amt_result,
                    ai_result={
                        "rationale": f"AMT pipeline: {amt_result.market_state} {amt_result.aggression:.1f} aggression",
                        "confidence": "High"
                        if _exec_prob >= CONFIDENCE_HIGH_THRESHOLD
                        else "Medium",
                        "market_state": amt_result.market_state,
                    },
                    setup_type=amt_result.setup or "MEAN_REVERSION",
                    data=list(event.data),
                    session_context=getattr(session._last_session_info, "session", ""),
                    confidence="High"
                    if _exec_prob >= CONFIDENCE_HIGH_THRESHOLD
                    else "Medium",
                    tick_size=tick_size,
                    inside_extreme=self._scalp_enabled,
                    risk_sl_pct=srm.stop_loss_pct if srm else None,
                )
                if signal:
                    session._last_entry_candle_time = event.tick.time
                    session._last_exec_mono = _time_mod.monotonic()
                    log.info(
                        "EXECUTING: %s dir=%s P=%.3f via AMT pipeline",
                        event.symbol,
                        _exec_dir,
                        _exec_prob,
                    )
                    self._execute_signal(event.symbol, signal, session)
                    with session._lock:
                        session._pending_decision = None
                        session._pending_amt = None
                        session._pending_tick = None
                else:
                    log.info(
                        "ENTRY BLOCKED: %s — signal construction failed", event.symbol
                    )
            else:
                log.info(
                    "ENTRY BLOCKED: %s — gate %s (%s): %s",
                    event.symbol,
                    gate_passed,
                    gate_reason,
                    gate_detail,
                )
                if self._gate_tracker:
                    self._gate_tracker.record(
                        event.symbol, f"gate_{gate_passed}", False
                    )

            self._persist_gate_decision(
                event,
                amt_result,
                _exec_dir,
                _exec_prob,
                gate_passed,
                gate_reason,
                gate_detail,
            )
        elif run_entry and not _can_execute:
            log.debug(
                "COOLDOWN: %s waiting %.0fs before next trade",
                event.symbol,
                60 - _time_since_last,
            )

    def _persist_gate_decision(
        self,
        event,
        amt_result,
        _exec_dir,
        _exec_prob,
        gate_passed,
        gate_reason,
        gate_detail,
    ):
        """Persist gate decision via injected signal tracker."""
        if not self._signal_tracker:
            return
        try:
            if gate_passed:
                self._signal_tracker.track_signal_generated(
                    symbol=event.symbol,
                    direction=_exec_dir,
                    confidence="High"
                    if _exec_prob >= CONFIDENCE_HIGH_THRESHOLD
                    else "Medium",
                    aggression_score=float(amt_result.aggression),
                    drive_number=getattr(amt_result, "drive_number", 0),
                    market_state=amt_result.market_state,
                    price=float(event.tick.close),
                    poc=float(amt_result.poc),
                    vah=float(amt_result.value_area_high),
                    val=float(amt_result.value_area_low),
                    cvd_slope=float(amt_result.cvd_slope),
                )
            else:
                self._signal_tracker.track_gate_block(
                    symbol=event.symbol,
                    gate_name=f"GATE_{gate_passed}",
                    gate_reason=gate_reason or "FLAT",
                    gate_detail=gate_detail or "",
                    market_state=amt_result.market_state,
                    price=float(event.tick.close),
                    poc=float(amt_result.poc),
                    vah=float(amt_result.value_area_high),
                    val=float(amt_result.value_area_low),
                    cvd_slope=float(amt_result.cvd_slope),
                    aggression_score=float(amt_result.aggression),
                )
        except Exception:
            pass  # Non-critical — tracking failure should not break pipeline

    def _on_tick(self, event: TickReceived) -> None:
        import time as _tick_time

        _tick_start = _tick_time.monotonic()
        session = self.get_or_create_session(event.symbol)

        # Initialize IB engine for this symbol if not exists
        if not hasattr(self, "_ib_engines"):
            self._ib_engines = {}
        if event.symbol not in self._ib_engines:
            from app.domain.services.initial_balance_engine import InitialBalanceEngine

            self._ib_engines[event.symbol] = InitialBalanceEngine(
                ib_minutes=30 if self._exchange == "NSE" else 30,
            )

        # 0. Session phase check + profile save
        self._session_phase_check(event, session)

        # 1. AMT Analysis + Footprint
        prior = getattr(session, "_prior_profile", None)
        if event.symbol not in self._amt_handlers:
            self._amt_handlers[event.symbol] = AMTHandler()

        amt_result = self._run_amt_analysis(event, session, prior)
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
        if hasattr(session, "_underlying_data") and session._underlying_data and len(session._underlying_data) >= 20:
            ib_tick = session._underlying_data[-1]

        ib_engine = self._ib_engines.get(event.symbol)
        if ib_engine:
            ib_state = ib_engine.update(ib_tick)
            session._ib_state = ib_state

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
                    bar_index=len(session.data),
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
        agent_decision = self._run_micro_agent_pipeline(event, amt_result)
        session._agent_decision = agent_decision

        # Extract stacked imbalances from footprint
        _imbalances = None
        _fp_domain = getattr(session, "_last_fp_domain", None)
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
            is_new_candle = event.tick.time != getattr(
                session, "_last_entry_candle_time", ""
            )
            _in_cooldown = self._lifecycle_handler.in_cooldown(event.symbol)

            # SAVE last good decision for execution on next candle
            if (
                agent_decision
                and agent_decision.direction != "FLAT"
                and agent_decision.probability >= AGENT_DECISION_THRESHOLD
            ):
                session._pending_decision = agent_decision
                session._pending_amt = amt_result
                session._pending_tick = event.tick

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
            ).detect_squeeze(session.data, amt_result)
            if _squeeze:
                _priority_score += 3.0
            session._llm_priority_score = _priority_score

            # UNIFIED ENTRY PATH — delegated to focused helper methods
            _exec_decision, _exec_amt, _exec_tick, _exec_dir, _exec_prob, run_entry = (
                self._resolve_entry_decision(
                    agent_decision, session, is_new_candle, has_position, _in_cooldown
                )
            )
            trigger_llm = self._should_trigger_llm(
                session,
                has_position,
                ai_running,
                _in_cooldown,
                amt_result,
                event,
                ai_time,
            )

        self._run_overseer_if_needed(session, event, amt_result)

        # 4a. Execute entry using proper AMT pipeline
        self._execute_entry_path(
            event, session, amt_result, _exec_dir, _exec_prob, run_entry
        )
        # 4b. Trigger LLM descriptor for UI
        if trigger_llm and is_new_candle:
            self._llm_handler.run_entry(session, event.symbol, event.tick, amt_result)

        elif not has_position and not ai_running and _in_cooldown:
            cooldown_status = session.last_ai_analysis or {}
            cooldown_status["direction"] = "FLAT"
            base_rationale = cooldown_status.get("rationale", "")
            base_rationale = base_rationale.split(" [Cooldown")[0]
            cooldown_status["rationale"] = (
                base_rationale + " [Cooldown — waiting before next entry]"
            )
            session.last_ai_analysis = cooldown_status

        # Record tick-to-signal latency
        if self._latency_tracker:
            elapsed_ms = (_tick_time.monotonic() - _tick_start) * 1000
            self._latency_tracker.record(event.symbol, elapsed_ms)

    def _execute_signal(self, symbol: str, sig, session: SessionState) -> None:
        """Execute a trade signal — delegates to EntryCoordinator."""
        self._entry_coordinator.execute_signal(symbol, sig, session)
        self._record_position_consistency(session, symbol, context="post_open")

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
        """Callback from TradeLifecycleHandler — delegates to ExitCoordinator."""
        self._exit_coordinator.on_partial_exit(
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
        """Callback from TradeLifecycleHandler — delegates to ExitCoordinator."""
        self._exit_coordinator.on_stop_out(level, direction, symbol, self._exchange)

    def _on_trade_closed(self, symbol: str, pnl: float, pos_id: str | None = None) -> None:
        """Callback from TradeLifecycleHandler — records PnL for session tracking."""
        session = self._state_manager.get_or_create_session(symbol)
        if session and session.portfolio:
            self._risk_coordinator.record_trade_result(
                symbol, pnl, session.portfolio
            )
        # Also record in ExitCoordinator for full lifecycle tracking
        self._exit_coordinator.on_position_closed(symbol, pos_id)

        # Delete from persistent storage so recovery doesn't re-create it
        if self._storage:
            try:
                delete_id = pos_id or symbol
                self._storage.delete_open_position(delete_id)
            except Exception as e:
                log.error("Failed to delete closed position %s: %e", pos_id or symbol, e)

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
        return build_state_snapshot(session, self._risk_coordinator, self._rl_handler)

    # State snapshot helpers delegated to state_snapshot_builder module
