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
import time

from app.config import Settings
from app.domain.trading.models.value_objects import OHLC, OrderBook
from app.domain.trading.models.aggregates import Portfolio
from app.domain.trading.models.enums import Source
from app.domain.trading.events import (
    TickReceived,
    SignalGenerated, PositionOpened, PositionClosed,
)
from app.domain.ports.event_bus import EventBusPort
from app.domain.ports.broker import BrokerPort
from app.domain.ports.storage import StoragePort
from app.domain.trading.services.risk_manager import RiskManager
from app.domain.fabio_ai.services.learning_engine import LearningEngine
from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService
from app.domain.ports.probability_inference import ProbabilityInferencePort, NoOpProbabilityAdapter

from app.application.handlers.amt_handler import AMTHandler
from app.application.handlers.llm_entry_handler import LLMEntryHandler
from app.application.handlers.trade_lifecycle_handler import TradeLifecycleHandler
from app.application.handlers.rl_handler import RLHandler
from app.application.handlers.llm_overseer_handler import LLMOverseerHandler
from app.domain.fabio_ai.services.option_selector import OptionSelector

from app.application.services.trade_journal import TradeJournal
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

    # Thread safety lock for portfolio reads/writes AND throttle flags
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # LLM throttling state — MUST be accessed under _lock
    _last_ai_time: float = 0
    _ai_running: bool = False

    # Overseer throttling state — MUST be accessed under _lock
    _last_overseer_time: float = 0
    _overseer_running: bool = False

    # Last entry time — for minimum gap between entries
    _last_entry_time: float = 0

    # Pending signal from LLM worker thread — drained on next process_tick
    # This ensures portfolio mutations always happen on the main thread.
    _pending_signal: tuple | None = None  # (symbol, Signal) or None

    # Track last candle time — LLM only fires on new candle boundaries
    _last_candle_time: str = ""


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
    ) -> None:
        self._event_bus = event_bus
        self._broker = broker
        self._storage = storage
        self._probability_engine = probability_engine or NoOpProbabilityAdapter()

        # Domain services
        self._risk_manager = RiskManager()

        # Focused handlers
        self._amt_handler = amt_handler or AMTHandler()
        # Trading journal — comprehensive JSONL trade logging
        self._journal = TradeJournal()
        self._forward_logger: ForwardTestLogger | None = None
        try:
            from app.application.services.forward_test_logger import ForwardTestLogger
            self._forward_logger = ForwardTestLogger()
        except Exception:
            pass

        self._lifecycle_handler = TradeLifecycleHandler(
            on_stop_out=self._on_stop_out,
            on_partial_exit=self._on_partial_exit,
        )

        self._llm_handler = LLMEntryHandler(
            gen_ai_service, event_bus, storage=storage,
            trade_manager=self._lifecycle_handler.trade_manager,
            journal=self._journal,
        )
        self._rl_handler = RLHandler()
        self._overseer_handler = LLMOverseerHandler(
            gen_ai_service, event_bus,
            trade_manager=self._lifecycle_handler.trade_manager,
            storage=storage,
            probability_engine=self._probability_engine,
        )

        # Option selector for NSE options signal enrichment
        self._option_selector = OptionSelector()

        # Session state per symbol
        self._sessions: dict[str, SessionState] = {}

        # Wire event subscriptions
        self._event_bus.subscribe(TickReceived, self._on_tick)
        self._event_bus.subscribe(SignalGenerated, self._on_signal_generated)
        self._event_bus.subscribe(PositionClosed, self._on_position_closed)

    def get_or_create_session(self, symbol: str) -> SessionState:
        if symbol not in self._sessions:
            new_session = SessionState(symbol=symbol)
            new_session.last_ai_analysis = {
                "direction": "FLAT",
                "rationale": "Waiting for first LLM call.",
                "confidence": "Low",
                "input_prompt": "",
                "raw_output": "",
            }
            # Load prior session profile for gap analysis
            if self._storage:
                try:
                    prior = self._storage.get_previous_session_profile(symbol, "NSE")
                    if prior:
                        new_session._prior_profile = prior
                        log.info(
                            "Loaded prior session profile for %s: POC=%.1f VAH=%.1f VAL=%.1f",
                            symbol, prior.get("poc", 0), prior.get("vah", 0), prior.get("val", 0),
                        )
                except Exception:
                    log.debug("Failed to load prior session profile", exc_info=True)

            # Recover open positions from storage (crash recovery)
            if self._storage:
                try:
                    saved_positions = self._storage.load_open_positions()
                    for pos_data in saved_positions:
                        if pos_data.get("symbol") != symbol:
                            continue
                        from app.domain.trading.models.entities import Position
                        from app.domain.trading.models.enums import Side, PositionStatus
                        pos = Position(
                            id=pos_data["id"],
                            symbol=pos_data["symbol"],
                            side=Side(pos_data["side"]),
                            source=Source.LLM,
                            entry_price=pos_data["entry_price"],
                            size=pos_data["size"],
                            stop_loss=pos_data["stop_loss"],
                            take_profit=pos_data["take_profit"],
                            entry_time=pos_data.get("opened_at", ""),
                            status=PositionStatus.OPEN,
                        )
                        new_session.portfolio.positions.append(pos)
                        # Re-register with TradeManager for exit monitoring
                        self._lifecycle_handler._trade_manager.register_position(
                            position_id=pos.id,
                            side=pos_data["side"],
                            entry_price=pos.entry_price,
                            stop_loss=pos.stop_loss,
                            take_profit=pos.take_profit,
                        )
                        log.info(
                            "Recovered position %s: %s %s @ %.2f (SL=%.2f, TP=%.2f)",
                            pos.id, pos_data["side"], symbol,
                            pos.entry_price, pos.stop_loss, pos.take_profit,
                        )
                except Exception:
                    log.error("Failed to recover open positions", exc_info=True)

            # Clear failed entry records from previous session
            self._llm_handler.clear_failed_entries()

            self._sessions[symbol] = new_session
        return self._sessions[symbol]

    def process_tick(
        self, symbol: str, tick: OHLC, order_book: OrderBook | None = None,
    ) -> dict:
        """Process a new tick and return the current state snapshot."""
        session = self.get_or_create_session(symbol)

        # Drain pending signal from LLM worker thread.
        # This ensures portfolio mutations always happen on the main thread,
        # eliminating the race condition where the worker thread would mutate
        # portfolio.positions concurrently via the synchronous event bus.
        with session._lock:
            pending = session._pending_signal
            session._pending_signal = None
        if pending:
            pending_symbol, pending_signal = pending
            self._execute_signal(pending_symbol, pending_signal, session)

        # Update data store — deduplicate sub-candle updates.
        # Live feed sends ~150 updates per 5m candle.  Each update
        # carries the same open-time but progressively updated OHLCV.
        # We must replace the current candle in-place (not append) so that
        # session.data contains exactly one entry per candle interval.
        new_candle = not (session.data and session.data[-1].time == tick.time)
        if not new_candle:
            session.data[-1] = tick          # update current candle
        else:
            session.data.append(tick)        # new candle
            session._last_candle_time = tick.time
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
            # Capture snapshot while locked (before overseer can mutate)
            if closed_positions:
                _snap_equity = session.portfolio.equity
                _snap_balance = session.portfolio.balance
                _snap_open_pnl = sum(p.pnl for p in session.portfolio.positions if p.status == "OPEN")
                _snap_open_count = len([p for p in session.portfolio.positions if p.status == "OPEN"])
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
                        "opened_at": pos.entry_time, "closed_at": pos.exit_time,
                    })
                except Exception:
                    log.debug("Failed to persist trade", exc_info=True)

        # Sync portfolio-closed positions to TradeManager to prevent double-close
        if closed_positions:
            for pos in closed_positions:
                # Track daily losses in TradeManager (SL exits via Portfolio safety net)
                if pos.close_reason and "Stop" in pos.close_reason:
                    self._lifecycle_handler.trade_manager.record_loss()
            self._lifecycle_handler.sync_closed(closed_positions)
            # Snapshot equity after trade closes (for performance tracking)
            if self._storage:
                try:
                    stats = session.portfolio.get_stats(Source.LLM)
                    self._storage.save_performance_snapshot({
                        "symbol": symbol,
                        "equity": _snap_equity,
                        "balance": _snap_balance,
                        "open_pnl": _snap_open_pnl,
                        "open_positions": _snap_open_count,
                        "total_trades": stats.total_trades,
                        "win_rate": stats.win_rate,
                    })
                except Exception:
                    log.debug("Failed to persist performance snapshot", exc_info=True)

        # Publish the main tick event (triggers analysis chain)
        # Pass data as-is; handlers must not mutate (use list() where needed).
        # Avoids copying 1000 candles on every tick.
        self._event_bus.publish(TickReceived(
            symbol=symbol, tick=tick,
            order_book=order_book,
            data=session.data,
        ))

        return self._build_state_snapshot(session)

    def create_portfolio(self) -> Portfolio:
        return Portfolio.create_default()

    # ----- event handlers -----

    def _on_tick(self, event: TickReceived) -> None:
        session = self.get_or_create_session(event.symbol)

        # 0. Session phase check — force exit all positions in Phase 5 (15:15-15:30 IST)
        from app.domain.fabio_ai.services.session_context import get_session_info as _get_si
        from app.config import Settings
        _market = Settings().DEFAULT_EXCHANGE
        if _market in ("NFO", "BSE"):
            _market = "NSE"
        session_phase = _get_si(timestamp=event.tick.time, market=_market)
        if session_phase.force_exit:
            with session._lock:
                open_positions = [p for p in session.portfolio.positions if p.status == "OPEN"]
                for pos in open_positions:
                    session.portfolio.close_position(
                        pos.id, event.tick.close, "SESSION_CLOSE (Phase 5: 15:15 IST)"
                    )
                    self._lifecycle_handler.trade_manager.unregister_position(pos.id)
                    if self._storage:
                        try:
                            self._storage.delete_open_position(pos.id)
                        except Exception:
                            pass
                    log.info("Session Phase 5: force-closed position %s at %.2f", pos.id, event.tick.close)

            # Save end-of-session profile for next-day gap analysis
            if self._storage and session.last_amt and not getattr(session, '_profile_saved', False):
                try:
                    from datetime import datetime, timezone, timedelta
                    ist = timezone(timedelta(hours=5, minutes=30))
                    session_date = datetime.now(ist).strftime("%Y-%m-%d")
                    profile_data = {
                        "symbol": event.symbol,
                        "market": "NSE",
                        "session_date": session_date,
                        "poc": session.last_amt.get("poc", 0),
                        "vah": session.last_amt.get("vah", 0),
                        "val": session.last_amt.get("val", 0),
                        "profile_shape": session.last_amt.get("profileShape", ""),
                        "total_volume": sum(d.volume for d in session.data[-100:]),
                    }
                    self._storage.save_session_profile(profile_data)
                    session._profile_saved = True  # Set AFTER successful save
                    log.info("Saved session profile for %s on %s", event.symbol, session_date)
                except Exception:
                    log.debug("Failed to save session profile", exc_info=True)

        # 1. AMT Analysis + Footprint
        # Pass prior session data for gap/bias computation
        prior = getattr(session, '_prior_profile', None)
        amt_result, amt_dto, fp_dto = self._amt_handler.analyze(
            list(event.data), event.order_book,
            prior_poc=prior.get("poc", 0.0) if prior else 0.0,
            prior_vah=prior.get("vah", 0.0) if prior else 0.0,
            prior_val=prior.get("val", 0.0) if prior else 0.0,
        )
        session.last_amt = amt_dto
        session.last_footprint = fp_dto

        # 1b. Micro-agent pipeline (LightGBM probability, <1ms)
        agent_decision = None
        if self._probability_engine.is_ready() and len(list(event.data)) >= 20:
            try:
                from app.domain.probability.features import extract_features
                from app.domain.probability.agent_pipeline import run_agent_pipeline
                features = extract_features(list(event.data), amt_result, event.tick, event.order_book)
                agent_decision = run_agent_pipeline(
                    data=list(event.data),
                    amt_result=amt_result,
                    tick=event.tick,
                    probability_engine=self._probability_engine,
                    features=features,
                    order_book=event.order_book,
                )
                log.info("Agent pipeline: dir=%s P=%.3f regime=%s timing=%s kelly=%.1f%% (%dus) — %s",
                         agent_decision.direction, agent_decision.probability,
                         agent_decision.regime, agent_decision.timing,
                         agent_decision.size_fraction * 100, agent_decision.latency_us,
                         agent_decision.rationale)
            except Exception:
                log.debug("Agent pipeline failed (non-critical)", exc_info=True)

        # Store agent decision on session for LLM enrichment
        session._agent_decision = agent_decision

        # 2. Trade Lifecycle (exits via TradeManager)
        with session._lock:
            position_closed = self._lifecycle_handler.check_exits(
                session.portfolio, event.tick.close,
                cvd_divergence=amt_result.cvd_divergence,
            )
            has_position = any(p.status == "OPEN" for p in session.portfolio.positions)

        # 3. LLM Overseer (runs while position IS open)
        # Read throttle flags under lock AND make dispatch decision atomically
        with session._lock:
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
            # Agent pipeline advises LLM but does NOT block it.
            # LLM is the Fabio-trained reasoning engine — it should always get
            # a chance to evaluate regime changes and market structure, even when
            # the quant agent sees no statistical edge. The agent fast-enters
            # independently when it has high conviction (ENTER_NOW path below).
            agent_blocks = False  # LLM runs independently of agent
            # Only evaluate entry on new candle boundaries — prevents signal spam
            # on mid-candle updates (150 updates per 5m candle from live feed).
            # Overseer still runs every ~10s for active position management.
            is_new_candle = (event.tick.time != getattr(session, '_last_entry_candle_time', ''))
            run_entry = (not run_overseer) and (not agent_blocks) and is_new_candle and self._llm_handler.should_run(
                last_ai_time=ai_time,
                ai_running=ai_running,
                has_position=has_position,
                has_managed_positions=self._lifecycle_handler.has_managed_positions,
                in_cooldown=self._lifecycle_handler.in_cooldown(),
                last_entry_time=session._last_entry_time,
                data=session.data,
                amt_result=amt_result,
                tick=event.tick,
                order_book=event.order_book,
            )

        if run_overseer:
            self._overseer_handler.run_overseer(session, event.symbol, event.tick, amt_result)

        # 4a. Agent-driven fast entry (LightGBM probability — bypasses slow LLM)
        # When agent pipeline says ENTER_NOW with high probability, create entry directly.
        # This is the fast path (<1ms). LLM remains as slow-path meta-agent for regime changes.
        agent_entered = False
        _last_entry = getattr(session, '_last_entry_time', 0)
        _agent_cooldown_ok = (time.time() - _last_entry) >= 30 if _last_entry else True
        if (not has_position and not ai_running and _agent_cooldown_ok
                and not getattr(session, '_pending_signal', None)
                and agent_decision and agent_decision.direction != "FLAT"
                and (Settings().ALLOW_SHORT or agent_decision.direction != "SHORT")
                and agent_decision.timing == "ENTER_NOW"
                and agent_decision.probability >= 0.55
                and agent_decision.size_fraction > 0
                and not self._lifecycle_handler.in_cooldown()
                and not self._lifecycle_handler.has_managed_positions):
            try:
                from app.domain.trading.models.enums import SignalType, SetupType
                from app.domain.trading.models.entities import Signal
                from app.domain.fabio_ai.services.entry_gate import build_entry_signal
                # Level-based SL/TP from Fabio playbook (VP levels, aggressive prints, ATR floor)
                setup = SetupType.TREND_MODEL if agent_decision.regime == "TRENDING" else SetupType.MEAN_REVERSION
                is_buy = agent_decision.direction == "LONG"
                sig = build_entry_signal(
                    direction=agent_decision.direction,
                    tick=event.tick,
                    amt_result=amt_result,
                    ai_result={"rationale": f"[Agent] {agent_decision.rationale[:80]}",
                               "confidence": "High" if agent_decision.probability >= 0.60 else "Medium"},
                    setup_type=setup,
                    data=session.data,
                )
                # Override source + metadata for agent path
                sig = Signal(
                    type=sig.type, price=sig.price, reason=sig.reason,
                    setup=sig.setup, source=Source.AGENT,
                    stop_loss=sig.stop_loss, take_profit=sig.take_profit,
                    timestamp=sig.timestamp,
                    metadata={"agent_entry": True, "probability": agent_decision.probability,
                              "kelly": agent_decision.size_fraction,
                              "confidence": "High" if agent_decision.probability >= 0.60 else "Medium"},
                )

                from app.domain.fabio_ai.services.trade_manager import TradeManager
                if TradeManager.is_valid_rr(sig.price, sig.stop_loss, sig.take_profit):
                    log.info("AGENT FAST ENTRY: %s P=%.3f kelly=%.1f%% — %s",
                             agent_decision.direction, agent_decision.probability,
                             agent_decision.size_fraction * 100, agent_decision.rationale)
                    session._pending_signal = (event.symbol, sig)
                    session._last_entry_candle_time = event.tick.time
                    session._last_entry_time = time.time()
                    agent_entered = True
                    # Update AI analysis display for frontend
                    session.last_ai_analysis = {
                        "direction": agent_decision.direction,
                        "rationale": f"[Agent] {agent_decision.rationale}",
                        "confidence": "High" if agent_decision.probability >= 0.60 else "Medium",
                    }
                    if self._journal:
                        self._journal.log_signal(
                            symbol=event.symbol, amt=session.last_amt,
                            llm_direction=agent_decision.direction,
                            llm_confidence="High" if agent_decision.probability >= 0.60 else "Medium",
                            llm_rationale=f"[Agent] {agent_decision.rationale}",
                            agent_direction=agent_decision.direction,
                            agent_regime=agent_decision.regime,
                            probability_long=agent_decision.probability if agent_decision.direction == "LONG" else 0,
                            probability_short=agent_decision.probability if agent_decision.direction == "SHORT" else 0,
                        )
                else:
                    log.info("Agent signal rejected by RR filter (P=%.3f %s)", agent_decision.probability, agent_decision.direction)
            except Exception:
                log.debug("Agent fast entry failed", exc_info=True)

        # 4b. LLM Entry Decision — slow path (fires once per new candle when agent didn't enter)
        if run_entry and not agent_entered:
            session._last_entry_candle_time = event.tick.time
            self._llm_handler.run_entry(session, event.symbol, event.tick, amt_result)
        elif not has_position and not ai_running:
            if self._lifecycle_handler.in_cooldown():
                cooldown_status = session.last_ai_analysis or {}
                cooldown_status["direction"] = "FLAT"
                base_rationale = cooldown_status.get("rationale", "")
                # Strip any existing cooldown suffix before adding fresh one
                base_rationale = base_rationale.split(" [Cooldown")[0]
                cooldown_status["rationale"] = base_rationale + " [Cooldown — waiting before next entry]"
                session.last_ai_analysis = cooldown_status

    def _on_signal_generated(self, event: SignalGenerated) -> None:
        """Event bus handler — may be called from any thread.

        Wraps _execute_signal with lock for thread safety.
        In the preferred path, LLM worker enqueues to _pending_signal instead
        and this is drained on the main thread in process_tick().
        """
        if not event.signal:
            return
        session = self.get_or_create_session(event.symbol)
        self._execute_signal(event.symbol, event.signal, session)

    def _execute_signal(self, symbol: str, sig, session: SessionState) -> None:
        """Execute a trade signal — MUST run on main thread or under lock.

        All portfolio mutations are protected by session._lock.
        """
        import time as _time

        log.info("Signal received: %s @ %.2f (SL=%.2f, TP=%.2f, source=%s)",
                 sig.type, sig.price, sig.stop_loss, sig.take_profit, sig.source)

        with session._lock:
            if not self._risk_manager.validate(sig, session.portfolio):
                log.info("Signal rejected by risk manager")
                _ad = getattr(session, '_agent_decision', None)
                self._journal.log_rejection(
                    symbol=symbol, reason="risk_manager",
                    amt=session.last_amt,
                    llm_direction="BUY" if sig.is_buy else "SELL",
                    agent_direction=_ad.direction if _ad else "",
                    agent_regime=_ad.regime if _ad else "",
                )
                return

        # Enrich signal with option selection (strike, expiry, lot sizing)
        try:
            # Extract underlying: "CRUDEOIL 17 MAR 6100 CALL" → "CRUDEOIL"
            # Also handles "NSE:NIFTY..." format
            _clean = symbol.replace("NSE:", "").replace("MCX:", "").strip()
            underlying = _clean.split("-")[0].split(" ")[0]
            direction = "LONG" if sig.is_buy else "SHORT"
            selected_strike = self._option_selector.select_strike(
                spot_price=sig.price, direction=direction, underlying=underlying,
            )
            if sig.metadata is None:
                sig.metadata = {}
            sig.metadata["option_strike"] = selected_strike
            # Derive option type from the active symbol (scanner already picked CE/PE)
            _sym_upper = symbol.upper()
            if "CALL" in _sym_upper or "CE" in _sym_upper:
                sig.metadata["option_type"] = "CE"
            elif "PUT" in _sym_upper or "PE" in _sym_upper:
                sig.metadata["option_type"] = "PE"
            else:
                sig.metadata["option_type"] = "CE"  # fallback
            sig.metadata["option_underlying"] = underlying
            sig.metadata["option_lot_size"] = self._option_selector._lot_size_for(underlying)
            log.info("Option selection: %s %s %d", underlying,
                     sig.metadata["option_type"], selected_strike)
        except Exception:
            log.debug("Option selection skipped", exc_info=True)

        # Portfolio mutation under lock — critical section
        with session._lock:
            session._last_entry_time = _time.time()
            position = self._broker.execute_order(sig, session.portfolio, symbol)

        if position:
            self._lifecycle_handler.register_position(position, sig)
            self._event_bus.publish(PositionOpened(symbol=symbol, position=position))
            _meta = sig.metadata or {}
            _is_agent = _meta.get("agent_entry", False)
            _ad = getattr(session, '_agent_decision', None)
            self._journal.log_entry(
                symbol=symbol,
                position_id=position.id,
                side=position.side.value if hasattr(position.side, 'value') else str(position.side),
                entry_price=position.entry_price,
                stop_loss=sig.stop_loss,
                take_profit=sig.take_profit,
                amt=session.last_amt,
                agent_direction=_ad.direction if _ad else "",
                agent_regime=_ad.regime if _ad else "",
                probability_long=_meta.get("probability", 0.0) if _is_agent and sig.is_buy else (_ad.probability if _ad and _ad.direction == "LONG" else 0.0),
                probability_short=_meta.get("probability", 0.0) if _is_agent and not sig.is_buy else (_ad.probability if _ad and _ad.direction == "SHORT" else 0.0),
                llm_direction="" if _is_agent else ("BUY" if sig.is_buy else "SELL"),
                llm_rationale=sig.reason[:200] if sig.reason else "",
            )
            # Persist for crash recovery
            if self._storage:
                try:
                    self._storage.save_open_position({
                        "id": position.id,
                        "symbol": symbol,
                        "side": position.side.value if hasattr(position.side, 'value') else str(position.side),
                        "entry_price": position.entry_price,
                        "size": position.size,
                        "stop_loss": position.stop_loss,
                        "take_profit": position.take_profit,
                        "source": position.source.value if hasattr(position.source, 'value') else str(position.source),
                        "opened_at": position.entry_time,
                    })
                except Exception:
                    log.debug("Failed to persist open position", exc_info=True)

    def _on_partial_exit(
        self, pos_id: str, side: str, entry_price: float, exit_price: float,
        partial_pct: float, size_closed: float, size_remaining: float, realized_pnl: float,
    ) -> None:
        """Callback from TradeLifecycleHandler when a partial exit fires."""
        # Find the symbol from any active session
        symbol = ""
        for sym, sess in self._sessions.items():
            if any(p.id == pos_id for p in sess.portfolio.positions):
                symbol = sym
                break

        self._journal.log_partial_exit(
            symbol=symbol, position_id=pos_id, side=side,
            entry_price=entry_price, exit_price=exit_price,
            partial_pct=partial_pct, size_closed=size_closed,
            size_remaining=size_remaining, realized_pnl=realized_pnl,
        )
        if self._forward_logger:
            self._forward_logger.log_partial_exit(
                symbol=symbol, position_id=pos_id,
                partial_pct=partial_pct, size_closed=size_closed,
                size_remaining=size_remaining, exit_price=exit_price,
                realized_pnl=realized_pnl, exit_reason="PARTIAL_TAKE_PROFIT",
            )
        log.info(
            "Journal: PARTIAL_EXIT pos=%s side=%s %d→%d @ %.2f pnl=%.2f",
            pos_id, side, size_closed, size_remaining, exit_price, realized_pnl,
        )

    def _on_stop_out(self, level: float, direction: str) -> None:
        """Callback from TradeLifecycleHandler when a position is stopped out (Rule 11)."""
        from app.domain.fabio_ai.services.session_context import get_session_info as _get_si
        from app.config import Settings
        from datetime import datetime, timezone, timedelta
        ist = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(ist).strftime("%H:%M:%S")
        _market = Settings().DEFAULT_EXCHANGE
        if _market in ("NFO", "BSE"):
            _market = "NSE"
        si = _get_si(timestamp=now_ist, market=_market)
        self._llm_handler.record_stop_out(level, direction, si.phase)

    def _on_position_closed(self, event: PositionClosed) -> None:
        if not event.position:
            return
        pos = event.position
        session = self.get_or_create_session(event.symbol)
        session.learning.learn(pos)
        self._overseer_handler.reset_position_state()
        # Journal exit
        mp = self._lifecycle_handler.trade_manager._positions.get(pos.id)
        # Calculate time in trade (entry_time and exit_time are ISO strings)
        time_in_trade = 0.0
        if pos.exit_time and pos.entry_time:
            try:
                from datetime import datetime as _dt
                _exit = _dt.fromisoformat(pos.exit_time.replace("Z", "+00:00"))
                _entry = _dt.fromisoformat(pos.entry_time.replace("Z", "+00:00"))
                time_in_trade = (_exit - _entry).total_seconds()
            except Exception:
                time_in_trade = mp.tick_count * 0.5 if mp else 0.0  # fallback

        self._journal.log_exit(
            symbol=event.symbol,
            position_id=pos.id,
            side=pos.side.value if hasattr(pos.side, 'value') else str(pos.side),
            entry_price=pos.entry_price,
            exit_price=pos.exit_price or pos.entry_price,
            exit_reason=pos.close_reason or "UNKNOWN",
            pnl=pos.pnl,
            time_in_trade_s=time_in_trade,
            mfe=mp.mfe if mp else 0,
            mae=mp.mae if mp else 0,
            tick_count=mp.tick_count if mp else 0,
            amt=session.last_amt,
        )
        if self._forward_logger:
            self._forward_logger.log_exit(
                symbol=event.symbol, position_id=pos.id,
                pnl=pos.pnl, mfe=mp.mfe if mp else 0,
                mae=mp.mae if mp else 0,
                time_in_trade_s=time_in_trade,
                exit_reason=pos.close_reason or "UNKNOWN",
            )
        # Remove persisted open position (crash recovery cleanup)
        if self._storage:
            try:
                self._storage.delete_open_position(event.position.id)
            except Exception:
                log.debug("Failed to delete persisted position", exc_info=True)

    # ----- state snapshot -----

    def _build_state_snapshot(self, session: SessionState) -> dict:
        weights = session.learning.weights

        # All portfolio reads under lock to prevent concurrent mutation from
        # overseer worker thread (which holds lock for partial/full exits).
        with session._lock:
            ai_analysis = session.last_ai_analysis
            portfolio_dto = portfolio_to_dto(session.portfolio)
            llm_stats = stats_to_dto(session.portfolio.get_stats(Source.LLM))
            agent_stats = stats_to_dto(session.portfolio.get_stats(Source.AGENT))
            stats_by_source = {
                "amt": stats_to_dto(session.portfolio.get_stats(Source.AMT)),
                "prediction": stats_to_dto(session.portfolio.get_stats(Source.PREDICTION)),
                "rl": stats_to_dto(session.portfolio.get_stats(Source.RL)),
                "llm": llm_stats,
                "agent": agent_stats,
            }

        return {
            "_symbol": session.symbol,
            "portfolio": portfolio_dto,
            "amt": session.last_amt,
            "prediction": session.last_prediction,
            "footprint": session.last_footprint,
            "genAIAnalysis": self._camel_case_ai(ai_analysis),
            "overseerAction": (ai_analysis or {}).get("overseer_action", ""),
            "overseerReason": (ai_analysis or {}).get("overseer_reason", ""),
            "modelWeights": {
                "trend": weights.trend,
                "momentum": weights.momentum,
                "delta": weights.delta,
                "orderBook": weights.order_book,
                "volatility": weights.volatility,
            },
            "generation": session.learning.generation,
            "stats": llm_stats,
            "statsBySource": stats_by_source,
            "agentDecision": self._agent_decision_dto(session),
            "rlStatus": self._rl_handler.get_status(),
            "riskState": {
                "halted": self._risk_manager.is_halted,
                "haltReason": self._risk_manager.halt_reason,
                "consecutiveLosses": self._risk_manager.daily_state.consecutive_losses,
                "dailyPnl": self._risk_manager.daily_state.realized_pnl,
                "driftAlert": self._risk_manager._drift_alert,
                "driftMessage": self._risk_manager._drift_message,
            },
        }

    @staticmethod
    def _agent_decision_dto(session) -> dict | None:
        ad = getattr(session, '_agent_decision', None)
        if ad is None:
            return None
        return {
            "direction": ad.direction,
            "probability": round(ad.probability, 3),
            "regime": ad.regime,
            "timing": ad.timing,
            "sizeFraction": round(ad.size_fraction, 3),
            "slAdjust": round(ad.sl_adjust, 2),
            "tpAdjust": round(ad.tp_adjust, 2),
            "latencyUs": ad.latency_us,
            "rationale": ad.rationale,
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
