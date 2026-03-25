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
from app.domain.trading.models.value_objects import OHLC, OrderBook
from app.domain.trading.models.aggregates import Portfolio
from app.domain.trading.models.enums import MarketStateCodec, Source
from app.domain.trading.events import (
    TickReceived,
    SignalGenerated,
    PositionOpened,
    PositionClosed,
)
from app.domain.ports.event_bus import EventBusPort
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

from app.infrastructure.serialization.schemas import portfolio_to_dto, stats_to_dto

log = logging.getLogger(__name__)

# Cap candle history per symbol to bound memory in long-running sessions.
MAX_CANDLES_PER_SYMBOL = 2000


class TradingSessionService:
    """Application service coordinating the event-driven trading pipeline."""

    def __init__(
        self,
        event_bus: EventBusPort,
        broker: BrokerPort,
        gen_ai_service: GenerativeAIService,
        storage: StoragePort | None = None,
        amt_handler: AMTHandler | None = None,
        probability_engine: ProbabilityInferencePort | None = None,
        exchange_config=None,  # ExchangeConfig — injected from ServiceGraph
        allow_short: bool = False,
        gate_tracker=None,  # GateRejectionTracker — observability
        latency_tracker=None,  # LatencyTracker — observability
    ) -> None:
        self._event_bus = event_bus
        self._broker = broker
        self._storage = storage
        self._probability_engine = probability_engine or NoOpProbabilityAdapter()
        self._gate_tracker = gate_tracker
        self._latency_tracker = latency_tracker

        # Injected config — replaces inline Settings() calls
        self._exchange_config = exchange_config
        self._exchange = exchange_config.exchange if exchange_config else "MCX"
        self._allow_short = False  # BUY-only mode — SHORT entries disabled

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
        )

        self._llm_handler = LLMEntryHandler(
            gen_ai_service,
            event_bus,
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
            event_bus,
            trade_manager=self._lifecycle_handler.trade_manager,
            storage=storage,
            probability_engine=self._probability_engine,
        )

        # Option selector for NSE options signal enrichment
        self._option_selector = OptionSelector()

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
        )

        # Entry Coordinator — extracted signal execution logic
        self._entry_coordinator = EntryCoordinator(
            broker=broker,
            event_bus=event_bus,
            lifecycle_handler=self._lifecycle_handler,
            event_logger=self._event_logger,
            storage=storage,
            risk_coordinator=self._risk_coordinator,
            option_selector=self._option_selector,
            state_manager=self._state_manager,
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
        )

        # Pre-Candle Advisor — non-blocking advisory for dashboard (T-60s before bar close)
        self._pre_candle_advisor = PreCandleAdvisor(
            gen_ai_service=gen_ai_service,
            enabled=getattr(settings, "LLM_PRE_CANDLE_ADVISORY", True),
        )

        self._event_bus.subscribe(TickReceived, self._on_tick)
        self._event_bus.subscribe(SignalGenerated, self._on_signal_generated)
        self._event_bus.subscribe(PositionClosed, self._on_position_closed)

    def get_or_create_session(self, symbol: str) -> SessionState:
        """Get or create a session for the symbol."""
        return self._state_manager.get_or_create_session(symbol)

    def process_tick(
        self,
        symbol: str,
        tick: OHLC,
        order_book: OrderBook | None = None,
        oi_data: dict | None = None,
    ) -> dict:
        """Process a new tick and return the current state snapshot."""
        session = self.get_or_create_session(symbol)
        session._last_tick_time = time.time()
        self._state_manager._maybe_reset_symbol_state(session, symbol, tick.time)

        # Drain pending signal from LLM worker thread
        with session._lock:
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
            except Exception:
                log.debug("Silent exception handled", exc_info=True)
        if pending:
            self._execute_signal(pending_symbol, pending_signal, session)

        # Update data store
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
                except Exception:
                    log.debug("Silent exception handled", exc_info=True)
            session.data.append(tick)
            session._last_candle_time = tick.time
            if len(session.data) > MAX_CANDLES_PER_SYMBOL:
                del session.data[: len(session.data) - MAX_CANDLES_PER_SYMBOL]
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
                symbol, pos.pnl, session.portfolio
            )
            # Direct call to exit coordinator (avoids PositionClosed serialization bug)
            try:
                self._exit_coordinator.on_position_closed(
                    symbol=symbol,
                    position=pos,
                )
            except Exception:
                log.debug("Exit coordinator error", exc_info=True)
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
                except Exception as e:
                    log.error(
                        "Failed to persist trade for %s: %s", symbol, e, exc_info=True
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
                except Exception:
                    log.debug("Failed to persist performance snapshot", exc_info=True)

        # Publish tick event
        self._event_bus.publish(
            TickReceived(
                symbol=symbol,
                tick=tick,
                order_book=order_book,
                data=tuple(session.data),
            )
        )

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

        # 0. Session phase check — force exit all positions in Phase 5 (15:15-15:30 IST)
        try:
            from app.domain.fabio_ai.services.session_context import (
                get_session_info as _get_si,
            )

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
                        session.portfolio.close_position(
                            pos.id,
                            event.tick.close,
                            "SESSION_CLOSE (Phase 5: 15:15 IST)",
                        )
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
                            "Session Phase 5: force-closed position %s at %.2f",
                            pos.id,
                            event.tick.close,
                        )

                if (
                    self._storage
                    and session.last_amt
                    and not getattr(session, "_profile_saved", False)
                ):
                    try:
                        from datetime import datetime, timezone, timedelta

                        _market = self._exchange
                        ist = timezone(timedelta(hours=5, minutes=30))
                        session_date = datetime.now(ist).strftime("%Y-%m-%d")
                        from app.domain.fabio_ai.services.entry_gate import (
                            cluster_aggressive_prints,
                        )

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
                            "total_volume": sum(d.volume for d in session.data[-100:]),
                            "print_levels": [
                                {"price": p, "side": "MIXED"}
                                for p in _print_clusters[:5]
                            ],
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
                        session.portfolio.close_position(
                            pos.id,
                            exit_price if exit_price is not None else Decimal("0"),
                            "EMERGENCY_SESSION_PHASE",
                        )
                    except Exception as close_err:
                        log.error(
                            "Failed to emergency close position %s: %s",
                            pos.id,
                            close_err,
                        )

        # 1. AMT Analysis + Footprint
        prior = getattr(session, "_prior_profile", None)
        if event.symbol not in self._amt_handlers:
            self._amt_handlers[event.symbol] = AMTHandler()

        srm = self._risk_coordinator.get_session_risk_manager(event.symbol)
        try:
            amt_result, amt_dto, fp_dto = self._amt_handlers[event.symbol].analyze(
                list(event.data),
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
            return

        with session._lock:
            session.last_amt = amt_dto
            session.last_footprint = fp_dto
            session._last_fp_domain = fp_dto
            session._last_aggressive_prints = amt_result.aggressive_prints

        # Update IB engine
        ib_engine = self._ib_engines.get(event.symbol)
        if ib_engine:
            ib_state = ib_engine.update(event.tick)
            session._ib_state = ib_state

        # Pre-candle advisory: fire T-60s before 5-min bar close (bar minute 4)
        try:
            bar_minute = (
                int(event.tick.time.split("T")[1].split(":")[1]) % 5
                if "T" in str(event.tick.time)
                else -1
            )
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
        agent_decision = None
        if self._probability_engine.is_ready() and len(list(event.data)) >= 20:
            try:
                from app.domain.probability.features import extract_features
                from app.domain.probability.agent_pipeline import run_agent_pipeline

                is_mcx = event.symbol.split()[0] in [
                    "CRUDEOIL",
                    "GOLD",
                    "SILVER",
                    "NATURALGAS",
                    "COPPER",
                ]
                features = extract_features(
                    list(event.data),
                    amt_result,
                    event.tick,
                    event.order_book,
                    is_mcx=is_mcx,
                )
                agent_decision = run_agent_pipeline(
                    data=list(event.data),
                    amt_result=amt_result,
                    tick=event.tick,
                    probability_engine=self._probability_engine,
                    features=features,
                    order_book=event.order_book,
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
            except Exception:
                log.warning(
                    "Agent pipeline failed for %s (non-critical)",
                    event.symbol,
                    exc_info=True,
                )

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
                    event.tick.close,
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
                and agent_decision.probability >= 0.55
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

            # UNIFIED ENTRY PATH
            _allow_short = self._allow_short

            # USE BEST AVAILABLE DECISION
            _exec_decision = None
            _exec_amt = amt_result
            _exec_tick = event.tick

            if (
                agent_decision
                and agent_decision.direction != "FLAT"
                and agent_decision.probability >= 0.55
            ):
                _exec_decision = agent_decision
                if is_new_candle:
                    log.info(
                        "ENTRY: New candle with valid decision: %s P=%.3f",
                        agent_decision.direction,
                        agent_decision.probability,
                    )

            if _exec_decision is None and hasattr(session, "_pending_decision"):
                pending = session._pending_decision
                if (
                    pending
                    and pending.direction != "FLAT"
                    and pending.probability >= 0.55
                ):
                    _exec_decision = pending
                    _exec_amt = getattr(session, "_pending_amt", amt_result)
                    _exec_tick = getattr(session, "_pending_tick", event.tick)
                    if is_new_candle:
                        log.info(
                            "ENTRY: Using pending decision on new candle: %s P=%.3f",
                            pending.direction,
                            pending.probability,
                        )

            _exec_dir = (
                getattr(_exec_decision, "direction", "NONE")
                if _exec_decision
                else "NONE"
            )
            _exec_prob = (
                getattr(_exec_decision, "probability", 0) if _exec_decision else 0
            )

            run_entry = (
                not has_position
                and not _in_cooldown
                and _exec_decision is not None
                and _exec_dir in ("LONG", "SHORT")
                and (_exec_dir != "SHORT" or _allow_short)
                and _exec_prob >= 0.55
            )

            # Independent LLM trigger for UI display
            trigger_llm = self._llm_handler.should_run(
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

        if run_overseer:
            _mkt = self._exchange
            if _mkt in ("NFO", "BSE"):
                _mkt = "NSE"
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

        # 4a. Execute entry using proper AMT pipeline
        import time as _time_mod

        _last_exec_mono = getattr(session, "_last_exec_mono", 0)
        _now_mono = _time_mod.monotonic()
        _time_since_last = _now_mono - _last_exec_mono
        _can_execute = _time_since_last > 60

        if run_entry and _can_execute:
            srm = self._risk_coordinator.get_session_risk_manager(event.symbol)
            if srm and not srm.can_trade:
                log.info(
                    "ENTRY BLOCKED: %s — session risk: %s",
                    event.symbol,
                    srm.halt_reason,
                )
                run_entry = False

            if run_entry:
                from app.domain.fabio_ai.services.entry_gate import run_gate_pipeline

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
                    max_distance_to_level_ticks=self._exchange_config.max_distance_to_level_ticks,
                    probing_aggression_threshold=0.0,
                    min_aggression_score=0.0,
                    max_cushion_ticks=500.0,
                    min_rr_ratio=0.1,
                )

                if gate_passed:
                    # Record gate pass
                    if self._gate_tracker:
                        self._gate_tracker.record(event.symbol, "gate_pipeline", True)
                    # SHORT gate check (S1-S5) — only for SHORT signals
                    if _exec_dir == "SHORT":
                        from app.domain.services.short_signal_gates import (
                            evaluate_short_gates,
                        )

                        short_ok, short_results = evaluate_short_gates(
                            short_enabled=getattr(
                                settings, "SHORT_SIGNALS_ENABLED", False
                            ),
                            market_state=amt_result.market_state,
                            displacement_direction=getattr(
                                amt_result, "displacement_direction", ""
                            ),
                            failed_breakout=getattr(
                                amt_result, "failed_breakout", False
                            ),
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

                    _ts = (
                        self._exchange_config.get_tick_size(event.symbol)
                        if self._exchange_config
                        else 0.05
                    )
                    signal = build_entry_signal(
                        direction=_exec_dir,
                        tick=event.tick,
                        amt_result=amt_result,
                        ai_result={
                            "rationale": f"AMT pipeline: {amt_result.market_state} {amt_result.aggression:.1f} aggression",
                            "confidence": "High" if _exec_prob >= 0.65 else "Medium",
                            "market_state": amt_result.market_state,
                        },
                        setup_type=amt_result.setup or "MEAN_REVERSION",
                        data=list(event.data),
                        session_context=getattr(
                            session._last_session_info, "session", ""
                        ),
                        confidence="High" if _exec_prob >= 0.65 else "Medium",
                        tick_size=_ts,
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
                        session._pending_decision = None
                        session._pending_amt = None
                        session._pending_tick = None
                    else:
                        log.info(
                            "ENTRY BLOCKED: %s — signal construction failed",
                            event.symbol,
                        )
                else:
                    log.info(
                        "ENTRY BLOCKED: %s — gate %d (%s): %s",
                        event.symbol,
                        gate_passed,
                        gate_reason,
                        gate_detail,
                    )
                    # Record gate rejection for observability
                    if self._gate_tracker:
                        self._gate_tracker.record(
                            event.symbol, f"gate_{gate_passed}", False
                        )

                # Persist gate decision for decision history
                try:
                    from app.api.dependencies import get_service_graph

                    sg = get_service_graph()
                    if hasattr(sg, "signal_tracker") and sg.signal_tracker:
                        if gate_passed:
                            sg.signal_tracker.track_signal_generated(
                                symbol=event.symbol,
                                direction=_exec_dir,
                                confidence="High" if _exec_prob >= 0.65 else "Medium",
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
                            sg.signal_tracker.track_gate_block(
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
        elif run_entry and not _can_execute:
            log.debug(
                "COOLDOWN: %s waiting %.0fs before next trade",
                event.symbol,
                60 - _time_since_last,
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

    def _on_signal_generated(self, event: SignalGenerated) -> None:
        """Event bus handler — may be called from any thread."""
        if not event.signal:
            return
        session = self.get_or_create_session(event.symbol)
        self._execute_signal(event.symbol, event.signal, session)

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

    def _on_stop_out(self, level: float, direction: str) -> None:
        """Callback from TradeLifecycleHandler — delegates to ExitCoordinator."""
        self._exit_coordinator.on_stop_out(level, direction, self._exchange)

    def _on_position_closed(self, event: PositionClosed) -> None:
        """Handle position closed — delegates to ExitCoordinator."""
        self._exit_coordinator.on_position_closed(event)

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
