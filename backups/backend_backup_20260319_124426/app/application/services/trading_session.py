"""TradingSession — thin coordinator delegating to focused handlers.

Manages per-symbol state, wires event subscriptions, and delegates:
  - AMT analysis        → AMTHandler
  - Trade exits         → TradeLifecycleHandler
  - LLM entry decisions → LLMEntryHandler
  - RL status           → RLHandler
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import logging
import threading
import time
import math
import queue
import json
from uuid import uuid4

from app.config import Settings
from app.domain.trading.models.value_objects import OHLC, OrderBook
from app.domain.trading.models.aggregates import Portfolio
from app.domain.trading.models.enums import MarketStateCodec, Source
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
from app.domain.fabio_ai.services.trade_thesis import (
    build_trade_thesis,
    validate_trade_thesis,
)
from app.domain.fabio_ai.services.entry_gate import (
    build_entry_signal,
    three_align_check,
    check_momentum_fade,
)

from app.application.services.trade_journal import TradeJournal
from app.application.services.experiment_context import build_experiment_context
from app.domain.fabio_ai.services.session_risk_manager import SessionRiskManager
from app.infrastructure.serialization.schemas import portfolio_to_dto, stats_to_dto

log = logging.getLogger(__name__)

# Cap candle history per symbol to bound memory in long-running sessions.
MAX_CANDLES_PER_SYMBOL = 2000


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

    # Idempotency: track executed signal IDs to prevent duplicate position openings
    _executed_signal_ids: set = field(default_factory=set)

    # Track last candle time — LLM only fires on new candle boundaries
    _last_candle_time: str = ""

    # Live structural guard telemetry for frontend/runtime QA
    _playbook_guard_rejections: dict[str, int] = field(default_factory=dict)
    _last_playbook_guard_reason: str = ""
    _playbook_guard_day: str = ""
    _explainability_entries: int = 0
    _explained_entries: int = 0
    _aggression_explained_entries: int = 0
    _last_explainability_alert: str = ""
    _explainability_day: str = ""



@dataclass(frozen=True)
class SystemRiskState:
    """Aggregated system-wide risk and halt state for control-plane endpoints."""

    halted: bool
    halt_reason: str
    daily_drawdown_pct: float
    consecutive_losses: int
    peak_equity: float
    current_equity: float
    drift_alert: bool
    drift_message: str


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
        self._risk_managers: dict[str, RiskManager] = {}

        # Focused handlers — per-symbol AMT handlers (VP state is per-instrument)
        self._amt_handlers: dict[str, AMTHandler] = {}
        self._default_amt_handler = amt_handler  # used as template for config
        self._experiment = build_experiment_context()
        # Trading journal — comprehensive JSONL trade logging
        self._journal = TradeJournal(experiment=self._experiment)
        self._forward_logger: ForwardTestLogger | None = None
        try:
            from app.application.services.forward_test_logger import ForwardTestLogger
            self._forward_logger = ForwardTestLogger(experiment=self._experiment)
        except Exception:
                    logger.debug("Silent exception handled", exc_info=True)
        # Crash-safe state persistence via storage kv_set/kv_get
        def _persist_fn(key: str, value: str | None = None) -> str | None:
            if not self._storage or not hasattr(self._storage, 'kv_set'):
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
            gen_ai_service, event_bus, storage=storage,
            trade_manager=self._lifecycle_handler.trade_manager,
            journal=self._journal,
        )
        self._rl_handler = RLHandler()

        # Session risk managers — Fabio cushion system (Gap #4)
        # These are per-symbol, lazily initialized in get_or_create_session.
        self._session_risk_managers: dict[str, SessionRiskManager] = {}

        self._overseer_handler = LLMOverseerHandler(
            gen_ai_service, event_bus,
            trade_manager=self._lifecycle_handler.trade_manager,
            storage=storage,
            probability_engine=self._probability_engine,
            # (Warning: OverseerHandler now requires session._session_risk_manager dynamically)
        )

        # Option selector for NSE options signal enrichment
        self._option_selector = OptionSelector()

        # Session state per symbol
        self._sessions: dict[str, SessionState] = {}
        self._session_creation_lock = threading.Lock()

        # Session eviction — prevent unbounded memory growth
        self._session_eviction_interval = 3600  # check every hour
        self._last_eviction_check = time.time()
        self._session_idle_timeout = 86400  # 24 hours

        self._event_bus.subscribe(TickReceived, self._on_tick)
        self._event_bus.subscribe(SignalGenerated, self._on_signal_generated)
        self._event_bus.subscribe(PositionClosed, self._on_position_closed)


    def _evict_idle_sessions(self) -> None:
        """Remove sessions idle for > 24 hours with no open positions."""
        now = time.time()
        if now - self._last_eviction_check < self._session_eviction_interval:
            return
        self._last_eviction_check = now
        to_evict = []
        for symbol, session in self._sessions.items():
            last_tick = getattr(session, '_last_tick_time', 0)
            has_positions = any(
                p.status == "OPEN" for p in session.portfolio.positions
            ) if hasattr(session, 'portfolio') else False
            if not has_positions and (now - last_tick) > self._session_idle_timeout:
                to_evict.append(symbol)
        for symbol in to_evict:
            del self._sessions[symbol]
            log.info("Evicted idle session: %s", symbol)

    def _get_risk_manager(self, symbol: str) -> RiskManager:
        """Return per-symbol RiskManager, creating one if needed."""
        with self._session_creation_lock:
            if symbol not in self._risk_managers:
                self._risk_managers[symbol] = RiskManager()
            return self._risk_managers[symbol]

    def get_or_create_session(self, symbol: str) -> SessionState:
        self._evict_idle_sessions()
        if symbol not in self._sessions:
            with self._session_creation_lock:
                if symbol not in self._sessions:  # double-check after acquiring lock
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
                            _market = Settings().DEFAULT_EXCHANGE
                            prior = self._storage.get_previous_session_profile(symbol, _market)
                            if prior:
                                new_session._prior_profile = prior
                                # Extract prior session print levels for cross-session
                                # structural level persistence (Gap #10)
                                new_session._prior_print_levels = [
                                    p["price"]
                                    for p in prior.get("print_levels", [])
                                ]
                                log.info(
                                    "Loaded prior session profile for %s: POC=%.1f VAH=%.1f VAL=%.1f print_levels=%d",
                                    symbol, prior.get("poc", 0), prior.get("vah", 0), prior.get("val", 0),
                                    len(new_session._prior_print_levels),
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
                                    symbol=symbol,
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
                                self._log_position_event(
                                    position_id=pos.id,
                                    symbol=symbol,
                                    event_type="RECOVERED",
                                    event_time=pos.entry_time,
                                    side=pos_data["side"],
                                    entry_price=pos.entry_price,
                                    stop_loss=pos.stop_loss,
                                    take_profit=pos.take_profit,
                                )
                        except Exception:
                            log.critical(
                                "POSITION RECOVERY FAILED for %s — manual check required",
                                symbol, exc_info=True,
                            )

                    # Clear failed entry records from previous session
                    self._llm_handler.clear_failed_entries()

                    # Create and potentially restore SessionRiskManager for this symbol
                    srm = SessionRiskManager()
                    if self._storage and hasattr(self._storage, 'kv_get'):
                        try:
                            import json
                            from datetime import date
                            saved = self._storage.kv_get(f"risk_state_{symbol}_{date.today().isoformat()}")
                            if saved:
                                srm.load_from_dict(json.loads(saved))
                                log.info("Restored risk state for %s: tier=%s, pnl=%.2f",
                                         symbol, srm.risk_tier.name, srm.session_pnl)
                        except Exception:
                            log.debug("Could not load risk state for %s", symbol, exc_info=True)
                    self._session_risk_managers[symbol] = srm
                    new_session._session_risk_manager = srm

                    self._sessions[symbol] = new_session
        return self._sessions[symbol]

    def process_tick(
        self, symbol: str, tick: OHLC, order_book: OrderBook | None = None,
        oi_data: dict | None = None,
    ) -> dict:
        """Process a new tick and return the current state snapshot."""
        session = self.get_or_create_session(symbol)
        session._last_tick_time = time.time()
        self._maybe_reset_symbol_state(session, symbol, tick.time)

        # Drain pending signal from LLM worker thread.
        # This ensures portfolio mutations always happen on the main thread,
        # eliminating the race condition where the worker thread would mutate
        # portfolio.positions concurrently via the synchronous event bus.
        with session._lock:
            pending = session._pending_signal
            session._pending_signal = None
        if pending:
            pending_symbol, pending_signal = pending
            
            # Audit Fix: Signal TTL — ignore stale signals older than 10 minutes
            from datetime import datetime
            try:
                sig_time = datetime.fromisoformat(pending_signal.timestamp.replace("Z", "+00:00"))
                curr_time = datetime.fromisoformat(tick.time.replace("Z", "+00:00"))
                signal_age = (curr_time - sig_time).total_seconds()
                if signal_age > 600:
                    log.warning("Discarding stale signal for %s (age=%.0fs)", symbol, signal_age)
                    pending = None
            except Exception:
                    logger.debug("Silent exception handled", exc_info=True)
        if pending:
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
            # A new candle started — persist the just-completed candle to DB
            if self._storage and session.data:
                closed = session.data[-1]
                try:
                    self._storage.save_tick(symbol, {
                        "time": closed.time, "open": closed.open, "high": closed.high,
                        "low": closed.low, "close": closed.close,
                        "volume": closed.volume, "delta": closed.delta,
                    })
                except Exception:
                    logger.debug("Silent exception handled", exc_info=True)
            session.data.append(tick)        # new candle
            session._last_candle_time = tick.time
            if len(session.data) > MAX_CANDLES_PER_SYMBOL:
                del session.data[:len(session.data) - MAX_CANDLES_PER_SYMBOL]
        session.order_book = order_book

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
            self._get_risk_manager(symbol).record_trade_result(pos.pnl, session.portfolio)
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
                except (OSError, IOError) as e:
                    log.warning("Failed to persist trade for %s — audit trail gap: %s", symbol, e)
                except Exception as e:
                    log.error("Unexpected error persisting trade for %s: %s", symbol, e, exc_info=True)

        # Sync portfolio-closed positions to TradeManager to prevent double-close
        if closed_positions:
            for pos in closed_positions:
                # Track daily losses in TradeManager (SL exits via Portfolio safety net)
                if pos.close_reason and "Stop" in pos.close_reason:
                    self._lifecycle_handler.trade_manager.record_loss(pos.symbol)
            self._lifecycle_handler.sync_closed(closed_positions)
            self._record_position_consistency(session, symbol, context="post_portfolio_close")
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
            data=tuple(session.data),  # defensive copy — preserve event immutability
        ))

        return self._build_state_snapshot(session)

    def create_portfolio(self) -> Portfolio:
        return Portfolio.create_default()

    @staticmethod
    def _expected_playbook_for(session_info, market_state: str) -> str:
        if not session_info:
            return ""
        if MarketStateCodec.is_imbalanced(market_state) and getattr(session_info, "allow_trend", False):
            return "imbalance_continuation"
        if MarketStateCodec.is_balanced(market_state) and getattr(session_info, "allow_reversion", False):
            return "return_to_value"
        return ""

    @staticmethod
    def _record_playbook_guard_rejection(session: SessionState, reason: str) -> None:
        session._playbook_guard_rejections[reason] = session._playbook_guard_rejections.get(reason, 0) + 1
        session._last_playbook_guard_reason = reason

    @staticmethod
    def _playbook_guard_total(session: SessionState) -> int:
        return sum(getattr(session, "_playbook_guard_rejections", {}).values())

    @staticmethod
    def _playbook_guard_tripped(session: SessionState) -> bool:
        return TradingSessionService._playbook_guard_total(session) >= Settings().PLAYBOOK_GUARD_MAX_REJECTIONS

    @staticmethod
    def _session_day_from_timestamp(timestamp: str) -> str:
        ist = timezone(timedelta(hours=5, minutes=30))
        try:
            stripped = str(timestamp).strip()
            if stripped.replace(".", "", 1).lstrip("-").isdigit() and "T" not in stripped and len(stripped) >= 9:
                dt = datetime.fromtimestamp(float(stripped), tz=timezone.utc)
            else:
                dt = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
        except Exception:
            return datetime.now(ist).date().isoformat()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ist).date().isoformat()

    def _reset_playbook_guard_state(self, session: SessionState, symbol: str) -> None:
        session._playbook_guard_rejections.clear()
        session._last_playbook_guard_reason = ""
        self._llm_handler.clear_failed_entries(symbol=symbol)

    @staticmethod
    def _reset_explainability_state(session: SessionState) -> None:
        session._explainability_entries = 0
        session._explained_entries = 0
        session._aggression_explained_entries = 0
        session._last_explainability_alert = ""

    @staticmethod
    def _has_aggression_feature_driver(feature_drivers: tuple[str, ...] | list[str] | None) -> bool:
        if not feature_drivers:
            return False
        return any(
            str(driver or "").startswith(("orderflow:", "aggression:", "liquidity:"))
            for driver in feature_drivers
        )

    def _record_explainability_entry(self, session: SessionState, feature_drivers: tuple[str, ...] | list[str] | None) -> None:
        session._explainability_entries += 1
        if feature_drivers:
            session._explained_entries += 1
        if self._has_aggression_feature_driver(feature_drivers):
            session._aggression_explained_entries += 1

        min_trades = Settings().EXPLAINABILITY_ALERT_MIN_TRADES
        if session._explainability_entries < min_trades:
            session._last_explainability_alert = ""
            return

        coverage = (session._explained_entries / session._explainability_entries * 100.0) if session._explainability_entries else 0.0
        aggression = (session._aggression_explained_entries / session._explainability_entries * 100.0) if session._explainability_entries else 0.0
        if coverage < Settings().EXPLAINABILITY_MIN_DRIVER_COVERAGE_PCT:
            session._last_explainability_alert = "LOW_FEATURE_DRIVER_COVERAGE"
            return
        if aggression < Settings().EXPLAINABILITY_MIN_AGGRESSION_DRIVER_PCT:
            session._last_explainability_alert = "LOW_AGGRESSION_DRIVER_RATE"
            return
        session._last_explainability_alert = ""

    def _maybe_reset_symbol_state(self, session: SessionState, symbol: str, tick_time: str) -> None:
        day_key = self._session_day_from_timestamp(tick_time)
        if not session._playbook_guard_day:
            session._playbook_guard_day = day_key
        if not session._explainability_day:
            session._explainability_day = day_key
        if session._playbook_guard_day == day_key and session._explainability_day == day_key:
            return
        session._playbook_guard_day = day_key
        session._explainability_day = day_key
        self._reset_playbook_guard_state(session, symbol)
        self._reset_explainability_state(session)
        log.info("Reset runtime QA state for %s on new session day %s", symbol, day_key)

    def reset_playbook_guard(self, symbol: str | None = None) -> dict:
        """Clear playbook-guard rejections for one symbol or all active sessions."""
        reset_symbols: list[str] = []
        targets = [symbol] if symbol else list(self._sessions.keys())
        for target in targets:
            session = self._sessions.get(target)
            if session is None:
                continue
            self._reset_playbook_guard_state(session, target)
            session._playbook_guard_day = datetime.now(timezone(timedelta(hours=5, minutes=30))).date().isoformat()
            self._reset_explainability_state(session)
            session._explainability_day = session._playbook_guard_day
            reset_symbols.append(target)
        return {
            "resetSymbols": reset_symbols,
            "count": len(reset_symbols),
        }

    @staticmethod
    def _decision_attribution(signal, agent_decision) -> tuple[str, str]:
        """Classify the decision source for experiment reporting."""
        meta = getattr(signal, "metadata", None) or {}
        if meta.get("agent_entry"):
            direction = "LONG" if getattr(signal, "is_buy", False) else "SHORT"
            if agent_decision and getattr(agent_decision, "direction", "") == direction:
                return "quant", "quant_only"
            return "quant", "quant_only"
        if agent_decision and getattr(agent_decision, "direction", "FLAT") != "FLAT":
            signal_direction = "LONG" if getattr(signal, "is_buy", False) else "SHORT"
            if agent_decision.direction == signal_direction:
                return "llm", "llm_plus_quant_agree"
            return "llm", "llm_override_quant"
        return "llm", "llm_only"

    # ----- control-plane helpers -----

    def halt_trading(self) -> None:
        """Activate the global emergency kill switch."""
        RiskManager.halt_trading()

    def resume_trading(self) -> None:
        """Clear the global emergency kill switch."""
        RiskManager.resume_trading()

    def get_system_risk_state(self) -> SystemRiskState:
        """Return an aggregated system-wide view of runtime risk state.

        The trading session uses per-symbol RiskManager instances, so the
        control plane must aggregate their current state rather than assuming
        a single `_risk_manager` exists on the service.
        """
        with self._session_creation_lock:
            managers = list(self._risk_managers.values())

        if not managers:
            return SystemRiskState(
                halted=RiskManager._global_halt,
                halt_reason="Emergency kill switch active" if RiskManager._global_halt else "",
                daily_drawdown_pct=0.0,
                consecutive_losses=0,
                peak_equity=0.0,
                current_equity=0.0,
                drift_alert=False,
                drift_message="",
            )

        peak_equity = max((rm.daily_state.peak_equity for rm in managers), default=0.0)
        current_equity = sum(rm.daily_state.current_equity for rm in managers)
        consecutive_losses = max((rm.daily_state.consecutive_losses for rm in managers), default=0)
        drift_alert = any(getattr(rm, "_drift_alert", False) for rm in managers)
        drift_messages = [
            getattr(rm, "_drift_message", "")
            for rm in managers
            if getattr(rm, "_drift_message", "")
        ]
        halted_manager = next((rm for rm in managers if rm.is_halted), None)

        if RiskManager._global_halt:
            halted = True
            halt_reason = "Emergency kill switch active"
        elif halted_manager is not None:
            halted = True
            halt_reason = halted_manager.halt_reason
        else:
            halted = False
            halt_reason = ""

        if peak_equity > 0 and math.isfinite(current_equity):
            daily_drawdown_pct = max(0.0, (peak_equity - current_equity) / peak_equity)
        else:
            daily_drawdown_pct = 0.0

        return SystemRiskState(
            halted=halted,
            halt_reason=halt_reason,
            daily_drawdown_pct=daily_drawdown_pct,
            consecutive_losses=consecutive_losses,
            peak_equity=peak_equity,
            current_equity=current_equity,
            drift_alert=drift_alert,
            drift_message=" | ".join(drift_messages[:3]),
        )

    def _log_position_event(
        self,
        *,
        position_id: str,
        symbol: str,
        event_type: str,
        event_time: str = "",
        **extra,
    ) -> None:
        """Persist append-only lifecycle events for replay and audit."""
        if not self._storage or not hasattr(self._storage, "save_position_event"):
            return
        try:
            payload = {
                "event_id": extra.pop("event_id", str(uuid4())),
                "position_id": position_id,
                "symbol": symbol,
                "event_type": event_type,
                "event_time": event_time,
            }
            payload.update(extra)
            self._storage.save_position_event(payload)
        except Exception:
            log.debug("Failed to persist position event %s for %s", event_type, position_id, exc_info=True)

    def _record_position_consistency(self, session: SessionState, symbol: str, *, context: str) -> None:
        """Audit and reconcile portfolio/lifecycle consistency for one symbol."""
        before = self._lifecycle_handler.get_position_consistency(session.portfolio, symbol=symbol)
        for stale_id in before.stale_managed_ids:
            self._log_position_event(
                position_id=stale_id,
                symbol=symbol,
                event_type="RECONCILED_STALE",
                context=context,
            )
        if before.stale_managed_ids:
            self._lifecycle_handler.reconcile_portfolio(session.portfolio, symbol=symbol)

        after = self._lifecycle_handler.get_position_consistency(session.portfolio, symbol=symbol)
        if after.unmanaged_open_ids:
            log.error(
                "Position state mismatch after %s for %s: unmanaged_open_ids=%s",
                context,
                symbol,
                ",".join(after.unmanaged_open_ids),
            )
            for position_id in after.unmanaged_open_ids:
                self._log_position_event(
                    position_id=position_id,
                    symbol=symbol,
                    event_type="STATE_MISMATCH_UNMANAGED_OPEN",
                    context=context,
                )

    # ----- event handlers -----

    def _on_tick(self, event: TickReceived) -> None:
        session = self.get_or_create_session(event.symbol)

        # 0. Session phase check — force exit all positions in Phase 5 (15:15-15:30 IST)
        try:
            from app.domain.fabio_ai.services.session_context import get_session_info as _get_si
            from app.config import Settings
            _market = Settings().DEFAULT_EXCHANGE
            if _market in ("NFO", "BSE"):
                _market = "NSE"
            session_phase = _get_si(timestamp=event.tick.time, market=_market)
            session._last_session_info = session_phase
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
                            except (OSError, IOError) as e:
                                log.warning("Failed to delete open position %s: %s", pos.id, e)
                            except Exception as e:
                                log.error("Unexpected error deleting position %s: %s", pos.id, e)
                        log.info("Session Phase 5: force-closed position %s at %.2f", pos.id, event.tick.close)

                # Save end-of-session profile for next-day gap analysis
                if self._storage and session.last_amt and not getattr(session, '_profile_saved', False):
                    try:
                        from datetime import datetime, timezone, timedelta
                        from app.config import Settings
                        _market = Settings().DEFAULT_EXCHANGE
                        ist = timezone(timedelta(hours=5, minutes=30))
                        session_date = datetime.now(ist).strftime("%Y-%m-%d")
                        from app.domain.fabio_ai.services.entry_gate import cluster_aggressive_prints
                        _agg_prints = getattr(session, '_last_aggressive_prints', None)
                        _print_clusters = cluster_aggressive_prints(
                            tuple(_agg_prints)
                        ) if _agg_prints else []
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
                        log.info("Saved session profile for %s on %s", event.symbol, session_date)
                    except (OSError, IOError) as e:
                        log.warning("Failed to save session profile (IO error): %s", e)
                    except Exception as e:
                        log.error("Failed to save session profile: %s", e, exc_info=True)
        except ImportError as e:
            # Missing dependency - log but continue trading
            log.error("Session phase check failed for %s: missing dependency %s", event.symbol, e)
        except Exception as e:
            # Unexpected error in session phase logic - MUST NOT stop trading
            log.critical("Session phase check CRITICAL failure for %s — FORCING EXIT ALL POSITIONS", event.symbol, exc_info=True)
            # Force exit all positions as safety measure
            # Use getattr as fallback in case tick is malformed
            exit_price = getattr(event.tick, 'close', None)
            with session._lock:
                for pos in list(session.portfolio.positions):
                    try:
                        session.portfolio.close_position(
                            pos.id,
                            exit_price if exit_price is not None else Decimal("0"),
                            "EMERGENCY_SESSION_PHASE"
                        )
                    except Exception as close_err:
                        log.error("Failed to emergency close position %s: %s", pos.id, close_err)

        # 1. AMT Analysis + Footprint
        # Pass prior session data for gap/bias computation
        prior = getattr(session, '_prior_profile', None)
        # Per-symbol AMT handler (each symbol needs its own VP state)
        if event.symbol not in self._amt_handlers:
            self._amt_handlers[event.symbol] = AMTHandler()

        srm = session._session_risk_manager
        try:
            amt_result, amt_dto, fp_dto = self._amt_handlers[event.symbol].analyze(
                list(event.data), event.order_book,
                prior_poc=prior.get("poc", 0.0) if prior else 0.0,
                prior_vah=prior.get("vah", 0.0) if prior else 0.0,
                prior_val=prior.get("val", 0.0) if prior else 0.0,
                cushion_tier=srm.risk_tier.name if srm else "NORMAL",
                session_pnl=srm.session_pnl if srm else 0.0,
            )
        except Exception:
            log.error("AMT analysis failed for %s — skipping tick", event.symbol, exc_info=True)
            return
        with session._lock:
            session.last_amt = amt_dto
            session.last_footprint = fp_dto
            # Store domain footprint for overseer and exit management
            session._last_fp_domain = fp_dto  # will be None if no footprint available
            # Store aggressive prints from domain AMTResult for cross-session persistence (Gap #10)
            session._last_aggressive_prints = amt_result.aggressive_prints


        # Record level approaches for second drive tracking (Gap #6)
        if hasattr(self._llm_handler, '_regime_detector'):
            key_levels = [amt_result.poc, amt_result.value_area_high, amt_result.value_area_low]
            if amt_result.lvns:
                key_levels.extend(amt_result.lvns[:3])
            self._llm_handler._regime_detector.record_level_approach(
                event.tick.close, key_levels, time.time(),
            )

        # 1b. Micro-agent pipeline (LightGBM probability, <1ms)
        agent_decision = None
        if self._probability_engine.is_ready() and len(list(event.data)) >= 20:
            try:
                from app.domain.probability.features import extract_features
                from app.domain.probability.agent_pipeline import run_agent_pipeline
                
                is_mcx = event.symbol.split()[0] in ["CRUDEOIL", "GOLD", "SILVER", "NATURALGAS", "COPPER"]
                features = extract_features(list(event.data), amt_result, event.tick, event.order_book, is_mcx=is_mcx)
                agent_decision = run_agent_pipeline(
                    data=list(event.data),
                    amt_result=amt_result,
                    tick=event.tick,
                    probability_engine=self._probability_engine,
                    features=features,
                    order_book=event.order_book,
                )
                log.info("Agent pipeline [%s]: dir=%s P=%.3f regime=%s timing=%s kelly=%.1f%% (%dus) — %s",
                         event.symbol, agent_decision.direction, agent_decision.probability,
                         agent_decision.regime, agent_decision.timing,
                         agent_decision.size_fraction * 100, agent_decision.latency_us,
                         agent_decision.rationale)
            except Exception:
                log.warning("Agent pipeline failed for %s (non-critical)", event.symbol, exc_info=True)

        # Store agent decision on session for LLM enrichment
        session._agent_decision = agent_decision

        # Extract stacked imbalances from footprint for exit management
        _imbalances = None
        _fp_domain = getattr(session, '_last_fp_domain', None)
        if _fp_domain:
            try:
                _latest_fp = list(_fp_domain.values())[-1] if _fp_domain else None
                if _latest_fp and hasattr(_latest_fp, 'levels'):
                    _imbalances = [lv for lv in _latest_fp.levels if getattr(lv, 'stacked', False)]
            except Exception:
                    logger.debug("Silent exception handled", exc_info=True)
        # 2. Trade Lifecycle (exits via TradeManager)
        # 3. Overseer + Entry decisions
        # Single lock block: check_exits, has_position, and dispatch decisions
        # are computed atomically to prevent TOCTOU race on position state.
        with session._lock:
            try:
                self._lifecycle_handler.check_exits(
                    session.portfolio, event.tick.close,
                    cvd_divergence=amt_result.cvd_divergence,
                    order_book=event.order_book,
                    amt_result=amt_result,
                    imbalances=_imbalances,
                )
            except Exception:
                log.error("check_exits failed for %s — assuming no position", event.symbol, exc_info=True)
            has_position = any(p.status == "OPEN" for p in session.portfolio.positions)

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
            # ---------------------------------------------------------------
            # UNIFIED QUANT ENTRY ARCHITECTURE
            # ---------------------------------------------------------------
            # Every symbol is fully independent.
            # Decision Layer: LightGBM probability + timing + regime.
            # Structural Layer: Three-Align, CVD, and Momentum gates.
            # Explainer Layer: LLM analysis (advisory-only for UI).
            # ---------------------------------------------------------------

            # Track candle boundaries for entry evaluation
            is_new_candle = (event.tick.time != getattr(session, '_last_entry_candle_time', ''))
            _in_cooldown = self._lifecycle_handler.in_cooldown(event.symbol)
            
            # SAVE last good decision for execution on next candle
            # This solves the timing mismatch between agent and candle
            if agent_decision and agent_decision.direction != "FLAT" and agent_decision.probability >= 0.55:
                session._pending_decision = agent_decision
                session._pending_amt = amt_result
                session._pending_tick = event.tick

            # Priority score for UI display only (does NOT gate analysis)
            _priority_score = 0.0
            if agent_decision and agent_decision.direction != "FLAT":
                _priority_score += agent_decision.probability * 10
            if getattr(amt_result, 'cvd_slope', 0) > 0.4 or getattr(amt_result, 'cvd_slope', 0) < -0.4:
                _priority_score += 2.0
            _squeeze = self._llm_handler._get_regime_detector(event.symbol).detect_squeeze(session.data, amt_result)
            if _squeeze:
                _priority_score += 3.0
            session._llm_priority_score = _priority_score

            # UNIFIED ENTRY PATH
            # Executes based on ML probability + timing and structural confluence.
            # LLM is triggered independently as an "Explainer" but has no veto power.
            from app.config import Settings as _QSettings
            _allow_short = _QSettings().ALLOW_SHORT
            
            # Log why entry is/isn't triggered
            _entry_checks = {
                "has_position": has_position,
                "in_cooldown": _in_cooldown,
                "is_new_candle": is_new_candle,
                "agent_exists": agent_decision is not None,
                "agent_direction": getattr(agent_decision, 'direction', 'NONE') if agent_decision else 'NONE',
                "agent_timing": getattr(agent_decision, 'timing', 'NONE') if agent_decision else 'NONE',
                "agent_prob": getattr(agent_decision, 'probability', 0) if agent_decision else 0,
                "ai_running": ai_running,
            }
            
            # USE BEST AVAILABLE DECISION
            # Priority: 1) Current tick if valid, 2) Pending decision
            _exec_decision = None
            _exec_amt = amt_result
            _exec_tick = event.tick
            
            # Check current tick's decision first
            if agent_decision and agent_decision.direction != "FLAT" and agent_decision.probability >= 0.55:
                _exec_decision = agent_decision
                if is_new_candle:
                    log.info("ENTRY: New candle with valid decision: %s P=%.3f",
                             agent_decision.direction, agent_decision.probability)
            
            # If no valid current decision, use pending decision
            if _exec_decision is None and hasattr(session, '_pending_decision'):
                pending = session._pending_decision
                if pending and pending.direction != "FLAT" and pending.probability >= 0.55:
                    _exec_decision = pending
                    _exec_amt = getattr(session, '_pending_amt', amt_result)
                    _exec_tick = getattr(session, '_pending_tick', event.tick)
                    if is_new_candle:
                        log.info("ENTRY: Using pending decision on new candle: %s P=%.3f",
                                 pending.direction, pending.probability)
            
            # Entry execution — execute when signal is valid
            # Removed is_new_candle check — entries should fire when conditions align,
            # not wait for arbitrary candle boundaries
            # Entry execution — when agent has valid edge
            _exec_dir = getattr(_exec_decision, 'direction', 'NONE') if _exec_decision else 'NONE'
            _exec_prob = getattr(_exec_decision, 'probability', 0) if _exec_decision else 0
            
            run_entry = (
                not has_position
                and not _in_cooldown
                and _exec_decision is not None
                and _exec_dir in ("LONG", "SHORT")
                and (_exec_dir != "SHORT" or _allow_short)
                and _exec_prob >= 0.55
            )
            
            if _exec_decision:
                _exec_type = type(_exec_decision).__name__
                _exec_id = id(_exec_decision)
                log.info("ENTRY CHECK: %s dir=%s P=%.3f timing=%s type=%s id=%s run_entry=%s",
                         event.symbol, _exec_dir, _exec_prob, 
                         getattr(_exec_decision, 'timing', 'NONE'),
                         _exec_type, _exec_id, run_entry)

            # Independent LLM trigger for UI display
            # Per-symbol 10s cooldown (enforced in should_run)
            trigger_llm = self._llm_handler.should_run(
                last_ai_time=ai_time,
                ai_running=ai_running,
                has_position=has_position,
                has_managed_positions=self._lifecycle_handler.has_managed_positions(event.symbol),
                in_cooldown=_in_cooldown,
                last_entry_time=session._last_entry_time,
                data=session.data,
                amt_result=amt_result,
                tick=event.tick,
                order_book=event.order_book,
            )

        if run_overseer:
            # Compute session info for overseer context
            from app.config import Settings as _Settings
            _mkt = _Settings().DEFAULT_EXCHANGE
            if _mkt in ("NFO", "BSE"):
                _mkt = "NSE"
            _si = _get_si(timestamp=event.tick.time, market=_mkt)
            _fp_candle = None
            _fp_domain = getattr(session, '_last_fp_domain', None)
            if _fp_domain:
                try:
                    _fp_vals = list(_fp_domain.values()) if isinstance(_fp_domain, dict) else None
                    _fp_candle = _fp_vals[-1] if _fp_vals else None
                except Exception:
                    logger.debug("Silent exception handled", exc_info=True)
            self._overseer_handler.run_overseer(
                session, event.symbol, event.tick, amt_result,
                session_info=_si, footprint_candle=_fp_candle,
            )

        # 4a. Execute unified entry (structural gates inside)
        # Execute with cooldown between trades (prevent overtrading)
        import time as _time_mod
        _last_exec_mono = getattr(session, '_last_exec_mono', 0)
        _now_mono = _time_mod.monotonic()
        _time_since_last = _now_mono - _last_exec_mono
        _can_execute = _time_since_last > 60  # 60 second cooldown between same-symbol trades
        
        if run_entry and _can_execute:
            session._last_entry_candle_time = event.tick.time
            import time as _time_mod
            session._last_exec_mono = _time_mod.monotonic()
            _exec_id = id(_exec_decision) if _exec_decision else 'None'
            _exec_prob = getattr(_exec_decision, 'probability', 'N/A') if _exec_decision else 'N/A'
            log.info("EXECUTING: %s dir=%s P=%s id=%s",
                     event.symbol, _exec_dir, _exec_prob, _exec_id)
            self._execute_unified_entry(session, event.symbol, _exec_decision, _exec_amt, _exec_tick)
            # Clear pending decision after use
            session._pending_decision = None
            session._pending_amt = None
            session._pending_tick = None
        elif run_entry and not _can_execute:
            log.debug("COOLDOWN: %s waiting %.0fs before next trade", event.symbol, 30 - _time_since_last)

        # 4b. Trigger LLM descriptor for UI
        if trigger_llm:
            self._llm_handler.run_entry(session, event.symbol, event.tick, amt_result)

        # Cooldown status message
        elif not has_position and not ai_running and _in_cooldown:
            cooldown_status = session.last_ai_analysis or {}
            cooldown_status["direction"] = "FLAT"
            base_rationale = cooldown_status.get("rationale", "")
            base_rationale = base_rationale.split(" [Cooldown")[0]
            cooldown_status["rationale"] = base_rationale + " [Cooldown — waiting before next entry]"
            session.last_ai_analysis = cooldown_status

    def _execute_unified_entry(self, session, symbol, agent_decision, amt_result, tick):
        """Execute position entry using SignalCoordinator + unified gates."""
        from app.domain.trading.models.enums import Source, SetupType
        from app.domain.fabio_ai.services.signal_coordinator import SignalCoordinator
        
        # Debug: log what we received
        _dir = getattr(agent_decision, 'direction', 'NONE')
        _prob = getattr(agent_decision, 'probability', 0)
        _id = id(agent_decision) if agent_decision else 'None'
        log.info("UNIFIED ENTRY: %s received decision dir=%s P=%.3f id=%s",
                 symbol, _dir, _prob, _id)
        
        # Use SignalCoordinator for clean entry evaluation
        coordinator = SignalCoordinator()
        
        # Get structural confirmation from AMT gate
        _fp_domain = getattr(session, '_last_fp_domain', None)
        _ib_high = getattr(session, '_ib_high', 0.0)
        _ib_low = getattr(session, '_ib_low', 0.0)
        
        from app.domain.fabio_ai.services.entry_gate import (
            three_align_check, check_momentum_fade
        )
        
        gate_passed, confirmation_strong, is_second_drive = three_align_check(
            data=session.data,
            amt_result=amt_result,
            tick=tick,
            order_book=session.order_book,
            ib_high=_ib_high,
            ib_low=_ib_low,
            footprint_domain=_fp_domain,
            return_is_second_drive=True
        )
        
        # Use SignalCoordinator for unified decision
        session_info = getattr(session, "_last_session_info", None)
        _has_position = self._lifecycle_handler.has_managed_positions(symbol) if hasattr(self, '_lifecycle_handler') else False
        _is_new_candle = (tick.time != getattr(session, '_last_entry_candle_time', ''))
        
        # Debug: log what decision we received
        _decision_prob = getattr(agent_decision, 'probability', None) if agent_decision else None
        _decision_dir = getattr(agent_decision, 'direction', 'NONE') if agent_decision else 'NONE'
        log.info("COORDINATOR INPUT: %s decision=%s P=%s",
                 symbol, _decision_dir, f'{_decision_prob:.3f}' if _decision_prob else 'None')
        
        # Use the decision passed in (already resolved from pending or current)
        evaluation = coordinator.evaluate_entry(
            agent_decision=agent_decision,
            amt_result=amt_result,
            tick=tick,
            session_info=session_info,
            confirmation_strong=confirmation_strong,
            is_new_candle=_is_new_candle,
            is_overseer_running=False,  # Overseer runs separately
            has_position=_has_position,
        )
        
        # Log coordinator decision
        log.info("SIGNAL COORDINATOR: %s — %s (P=%.3f conviction=%s)",
                 symbol, evaluation.reason, evaluation.probability, evaluation.conviction)
        
        if not evaluation.should_enter:
            log.info("SIGNAL COORDINATOR: %s — %s (P=%.3f conviction=%s)",
                     symbol, evaluation.reason, evaluation.probability, evaluation.conviction)
            return
        
        log.info("SIGNAL COORDINATOR: %s — ENTER %s (P=%.3f conviction=%s setup=%s)",
                 symbol, evaluation.direction, evaluation.probability,
                 evaluation.conviction, evaluation.setup_type)
        
        # Map setup type
        if evaluation.setup_type == "MEAN_REVERSION":
            setup_type = SetupType.MEAN_REVERSION
        else:
            setup_type = SetupType.TREND_MODEL
        
        # Build and execute signal
        log.info("SIGNAL BUILDING: %s — constructing %s signal",
                 symbol, evaluation.direction)
        
        # Build signal using entry_gate
        from app.domain.trading.models.enums import SignalType
        
        is_buy = evaluation.direction == "LONG"
        sig_type = SignalType.BUY if is_buy else SignalType.SELL
        
        # Simple signal construction
        buffer = tick.close * 0.001
        if is_buy:
            stop_price = tick.close - (tick.close * 0.02)  # 2% stop
            tp_price = tick.close + (tick.close * 0.04)    # 4% target
        else:
            stop_price = tick.close + (tick.close * 0.02)
            tp_price = tick.close - (tick.close * 0.04)
        
        # Create signal
        from app.domain.trading.models.entities import Signal
        from app.domain.trading.models.enums import Source
        
        signal = Signal(
            type=sig_type,
            price=tick.close,
            reason=f"LLM {evaluation.setup_type}: {evaluation.direction} (P={evaluation.probability:.3f})",
            setup=SetupType.MEAN_REVERSION if evaluation.setup_type == "MEAN_REVERSION" else SetupType.TREND_MODEL,
            source=Source.LLM,
            stop_loss=stop_price,
            take_profit=tp_price,
            timestamp=tick.time,
            metadata={
                "conviction": evaluation.conviction,
                "probability": evaluation.probability,
                "setup_type": evaluation.setup_type,
            }
        )
        
        log.info("SIGNAL CREATED: %s %s SL=%.2f TP=%.2f conviction=%s",
                 symbol, evaluation.direction, stop_price, tp_price, evaluation.conviction)
        
        # Create signal object with complete trade thesis
        from app.domain.trading.models.entities import Signal
        from app.domain.trading.models.enums import SignalType, Source, SetupType
        
        is_buy = evaluation.direction == "LONG"
        sig_type = SignalType.BUY if is_buy else SignalType.SELL
        
        # Build trade thesis for validation
        setup_type_enum = SetupType.MEAN_REVERSION if evaluation.setup_type == "MEAN_REVERSION" else SetupType.TREND_MODEL
        trade_thesis = {
            "market_state": amt_result.market_state if amt_result else "BALANCED",
            "location_type": "LVN" if amt_result and amt_result.lvns else "POC",
            "location_level": tick.close,
            "aggression_trigger": "LLM_AGGRESSION",
            "session_context": evaluation.setup_type,
            "invalidation_level": stop_price,
            "setup_family": "return_to_value" if evaluation.setup_type == "MEAN_REVERSION" else "imbalance_continuation",
        }
        
        signal = Signal(
            type=sig_type,
            price=tick.close,
            reason=f"LLM {evaluation.setup_type}: {evaluation.direction} (P={evaluation.probability:.3f})",
            setup=setup_type_enum,
            source=Source.LLM,
            stop_loss=stop_price,
            take_profit=tp_price,
            timestamp=tick.time,
            metadata={
                "conviction": evaluation.conviction,
                "probability": evaluation.probability,
                "setup_type": evaluation.setup_type,
                "trade_thesis": trade_thesis,  # Required for thesis validation
            }
        )
        
        # Execute the signal
        try:
            self._execute_signal(symbol, signal, session)
            log.info("SIGNAL EXECUTED: %s %s", symbol, evaluation.direction)
        except Exception as e:
            log.error("Signal execution failed: %s", e, exc_info=True)
        
        # Log to journal
        try:
            self._journal.log_signal(
                symbol=symbol,
                amt=amt_result,
                llm_direction=evaluation.direction,
                llm_confidence=evaluation.conviction,
                llm_rationale=evaluation.reason,
                decision_source="llm",
                attribution="llm_plus_quant",
            )
        except:
            pass
        
        return
        
        # Dead code below - keeping for reference
        if False:
            self._journal.log_rejection(
                symbol=symbol,
                reason="PLAYBOOK_GUARD_TRIPPED",
                amt=session.last_amt,
                agent_direction=agent_decision.direction,
                agent_regime=agent_decision.regime,
                agent_feature_drivers=getattr(agent_decision, "feature_drivers", ()),
                decision_source="unified",
                attribution="quant",
            )
            return

        session_info = getattr(session, "_last_session_info", None)
        if not getattr(session_info, "allow_entry", False):
            self._record_playbook_guard_rejection(session, "PLAYBOOK_SESSION_BLOCK")
            self._journal.log_rejection(
                symbol=symbol,
                reason="PLAYBOOK_SESSION_BLOCK",
                amt=session.last_amt,
                agent_direction=agent_decision.direction,
                agent_regime=agent_decision.regime,
                agent_feature_drivers=getattr(agent_decision, "feature_drivers", ()),
                decision_source="unified",
                attribution="quant",
            )
            return

        market_state = str(getattr(amt_result, "market_state", ""))
        if MarketStateCodec.is_imbalanced(market_state) and getattr(session_info, "allow_trend", False):
            setup_type = SetupType.TREND_MODEL
        elif MarketStateCodec.is_balanced(market_state) and getattr(session_info, "allow_reversion", False):
            setup_type = SetupType.MEAN_REVERSION
        else:
            self._record_playbook_guard_rejection(session, "PLAYBOOK_STATE_SESSION_MISMATCH")
            self._journal.log_rejection(
                symbol=symbol,
                reason="PLAYBOOK_STATE_SESSION_MISMATCH",
                amt=session.last_amt,
                agent_direction=agent_decision.direction,
                agent_regime=agent_decision.regime,
                agent_feature_drivers=getattr(agent_decision, "feature_drivers", ()),
                decision_source="unified",
                attribution="quant",
            )
            return

        # 2. Structural Layer — Fabio Location & Confluence
        # Gate: Three-Align (Market State + Price Location)
        _fp_domain = getattr(session, '_last_fp_domain', None)
        gate_passed, confirmation_strong, is_second_drive = three_align_check(
            data=session.data,
            amt_result=amt_result,
            tick=tick,
            order_book=session.order_book,
            ib_high=getattr(session, '_ib_high', 0.0),
            ib_low=getattr(session, '_ib_low', 0.0),
            footprint_domain=_fp_domain,
            return_is_second_drive=True
        )

        if not gate_passed:
            log.info("UNIFIED ENTRY: %s BLOCKED by AMT gate (state=%s, location=%s, confirm=%s)",
                     symbol, amt_result.market_state, "near_level" if abs(tick.close - amt_result.poc) < (amt_result.value_area_high - amt_result.value_area_low) * 0.5 else "mid_range",
                     confirmation_strong)
            return
        
        log.info("UNIFIED ENTRY: %s AMT gate PASSED (confirm_strong=%s, second_drive=%s)",
                 symbol, confirmation_strong, is_second_drive)

        # Gate: Momentum Fade (Don't fade a freight train)
        if check_momentum_fade(session.data, tick, agent_decision.direction):
            log.warning("UNIFIED ENTRY: %s blocked by Momentum Fade gate", symbol)
            return

        # 3. Decision Refinement
        # High confidence (0.65+) triggers immediately.
        # Medium confidence (0.55+) requires strong structural confirmation.
        is_high_conviction = agent_decision.probability >= 0.65
        is_medium_conviction = agent_decision.probability >= 0.55 and confirmation_strong
        
        if not (is_high_conviction or is_medium_conviction):
            log.info("UNIFIED ENTRY: %s probability (%.3f) insufficient — need P>=0.65 OR (P>=0.55 + strong confirmation=%s)", 
                      symbol, agent_decision.probability, confirmation_strong)
            return
        
        # Log successful passage of all gates
        log.info("UNIFIED ENTRY: %s ALL GATES PASSED — executing %s signal (P=%.3f conviction=%s)",
                 symbol, agent_decision.direction, agent_decision.probability,
                 "HIGH" if is_high_conviction else "MEDIUM+STRONG")

        # 4. VWAP Overextension Guard
        if amt_result and amt_result.vwap_upper_2 > 0 and agent_decision.direction == "LONG" and tick.close >= amt_result.vwap_upper_2:
            log.info("UNIFIED ENTRY: LONG blocked at +2σ VWAP (price=%.2f, band=%.2f)", tick.close, amt_result.vwap_upper_2)
            return
        if amt_result and amt_result.vwap_lower_2 > 0 and agent_decision.direction == "SHORT" and tick.close <= amt_result.vwap_lower_2:
            log.info("UNIFIED ENTRY: SHORT blocked at -2σ VWAP (price=%.2f, band=%.2f)", tick.close, amt_result.vwap_lower_2)
            return

        # 5. Build and Execute Signal
        # COMPOUNDING: Get dynamic session risk for position sizing
        srm = session._session_risk_manager
        session_risk_pct = None
        if srm:
            # Use TradeManager's compounding logic if available
            try:
                session_risk_pct, risk_tier = self._trade_manager.compute_dynamic_risk(
                    base_capital=float(session.portfolio.equity)
                )
                log.info("COMPOUNDING: risk_pct=%.4f tier=%s session_pnl=%.2f",
                        session_risk_pct, risk_tier, srm.session_pnl)
            except Exception:
                session_risk_pct = None
        
        signal = build_entry_signal(
            agent_decision.direction,
            tick,
            amt_result,
            {
                "rationale": f"Unified P={agent_decision.probability:.3f} confluence={'Strong' if confirmation_strong else 'Normal'}",
                "confidence": "High" if is_high_conviction else "Medium",
                "market_state": market_state,
            },
            setup_type=setup_type,
            data=session.data,
            session_context=getattr(session_info, "session", ""),
            session_risk_pct=session_risk_pct,  # COMPOUNDING
        )
        signal.source = Source.AGENT
        signal.reason = f"Unified {setup_type.value} P={agent_decision.probability:.3f} kelly={agent_decision.size_fraction:.1%}"
        signal.metadata = {
            **(signal.metadata or {}),
            "agent": "unified",
            "agent_entry": True,
            "probability": agent_decision.probability,
            "size_fraction": agent_decision.size_fraction,
            "playbook": (signal.metadata or {}).get("trade_thesis", {}).get("setup_family", ""),
            "structural_confluence": confirmation_strong,
            "is_second_drive": is_second_drive,
        }

        # Mark candle as consumed so we don't re-fire until the next candle
        session._last_quant_candle_time = tick.time # Maintain legacy flag just in case
        
        log.info("UNIFIED ENTRY: %s %s playbook=%s P=%.3f confluence=%s",
                 agent_decision.direction, symbol, setup_type.value, agent_decision.probability,
                 "STRONG" if confirmation_strong else "NORMAL")
        self._execute_signal(symbol, signal, session)

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

        thesis = (getattr(sig, "metadata", None) or {}).get("trade_thesis")
        thesis_valid, thesis_reason = validate_trade_thesis(thesis)
        if not thesis_valid:
            log.info("Signal rejected by trade thesis gate: %s", thesis_reason)
            _ad = getattr(session, "_agent_decision", None)
            decision_source, attribution = self._decision_attribution(sig, _ad)
            self._journal.log_rejection(
                symbol=symbol,
                reason=f"THESIS_{thesis_reason.upper()}",
                amt=session.last_amt,
                llm_direction="BUY" if sig.is_buy else "SELL",
                agent_direction=_ad.direction if _ad else "",
                agent_regime=_ad.regime if _ad else "",
                agent_feature_drivers=getattr(_ad, "feature_drivers", ()) if _ad else (),
                decision_source=decision_source,
                attribution=attribution,
                trade_thesis=thesis,
            )
            return

        # Idempotency guard: prevent duplicate position openings on crash/retry.
        # Each Signal carries a unique signal_id (UUID). If the same signal_id
        # is seen twice (e.g. network glitch, LLM fires twice), skip execution.
        sig_id = getattr(sig, 'signal_id', None)
        if sig_id:
            with session._lock:
                if sig_id in session._executed_signal_ids:
                    log.warning("Duplicate signal %s — skipping execution", sig_id)
                    return
                session._executed_signal_ids.add(sig_id)
                # Cap set size to prevent unbounded memory growth
                if len(session._executed_signal_ids) > 1000:
                    session._executed_signal_ids = set(
                        list(session._executed_signal_ids)[-500:]
                    )

        log.info("Signal received: %s @ %.2f (SL=%.2f, TP=%.2f, source=%s, id=%s)",
                 sig.type, sig.price, sig.stop_loss, sig.take_profit, sig.source, sig_id)

        with session._lock:
            if not self._get_risk_manager(symbol).validate(sig, session.portfolio):
                log.info("Signal rejected by risk manager")
                _ad = getattr(session, '_agent_decision', None)
                self._journal.log_rejection(
                    symbol=symbol, reason="risk_manager",
                    amt=session.last_amt,
                    llm_direction="BUY" if sig.is_buy else "SELL",
                    agent_direction=_ad.direction if _ad else "",
                    agent_regime=_ad.regime if _ad else "",
                    agent_feature_drivers=getattr(_ad, "feature_drivers", ()) if _ad else (),
                    decision_source="quant" if (getattr(sig, "metadata", None) or {}).get("agent_entry") else "llm",
                    attribution=self._decision_attribution(sig, _ad)[1],
                    trade_thesis=(getattr(sig, "metadata", None) or {}).get("trade_thesis"),
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
            if (sig.metadata or {}).get("agent_entry"):
                self._record_explainability_entry(
                    session,
                    getattr(getattr(session, "_agent_decision", None), "feature_drivers", ()),
                )
            self._lifecycle_handler.register_position(symbol, position, sig)
            self._log_position_event(
                position_id=position.id,
                symbol=symbol,
                event_type="OPENED",
                event_time=position.entry_time,
                side=position.side.value if hasattr(position.side, "value") else str(position.side),
                entry_price=position.entry_price,
                stop_loss=position.stop_loss,
                take_profit=position.take_profit,
                source=position.source.value if hasattr(position.source, "value") else str(position.source),
            )
            # Create proper PositionOpened event with required fields
            self._event_bus.publish(PositionOpened(
                symbol=symbol,
                trade_id=getattr(position, 'id', ''),
                side=getattr(position, 'side', ''),
                entry_price=float(getattr(position, 'entry_price', 0)),
                quantity=float(getattr(position, 'size', 0)),
            ))
            _meta = sig.metadata or {}
            _is_agent = _meta.get("agent_entry", False)
            _ad = getattr(session, '_agent_decision', None)
            decision_source, attribution = self._decision_attribution(sig, _ad)
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
                agent_feature_drivers=getattr(_ad, "feature_drivers", ()) if _ad else (),
                probability_long=_meta.get("probability", 0.0) if _is_agent and sig.is_buy else (_ad.probability if _ad and _ad.direction == "LONG" else 0.0),
                probability_short=_meta.get("probability", 0.0) if _is_agent and not sig.is_buy else (_ad.probability if _ad and _ad.direction == "SHORT" else 0.0),
                llm_direction="" if _is_agent else ("BUY" if sig.is_buy else "SELL"),
                llm_rationale=sig.reason[:200] if sig.reason else "",
                decision_source=decision_source,
                attribution=attribution,
                trade_thesis=(sig.metadata or {}).get("trade_thesis"),
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
            self._record_position_consistency(session, symbol, context="post_open")

    def _on_partial_exit(
        self, pos_id: str, side: str, entry_price: float, exit_price: float,
        partial_pct: float, size_closed: float, size_remaining: float, realized_pnl: float,
    ) -> None:
        """Callback from TradeLifecycleHandler when a partial exit fires."""
        # Find the symbol from any active session
        symbol = ""
        position = None
        for sym, sess in self._sessions.items():
            for p in sess.portfolio.positions:
                if p.id == pos_id:
                    symbol = sym
                    position = p
                    break
            if symbol:
                break

        # Scrub working Broker SL limit since size has been reduced.
        # Natively, one would need to replace the SL with the new size, but since TradeLifecycleHandler 
        # instantly converts partials into trailing Breakeven SLs, it's safer to cancel the broker SL 
        # and rely purely on software SL for the runner.
        if position:
            dhan_sl_id = (position.metadata or {}).get("dhan_sl_order_id")
            if dhan_sl_id:
                try:
                    self._broker.cancel_order(dhan_sl_id)
                    position.metadata.pop("dhan_sl_order_id", None)
                    log.info("Scrubbed broker hardware SL %s for partially closed pos %s - software trailing now handles runner.", dhan_sl_id, pos_id)
                except Exception as e:
                    log.error("Failed to scrub broker hardware SL %s: %s", dhan_sl_id, e)

        self._journal.log_partial_exit(
            symbol=symbol, position_id=pos_id, side=side,
            entry_price=entry_price, exit_price=exit_price,
            partial_pct=partial_pct, size_closed=size_closed,
            size_remaining=size_remaining, realized_pnl=realized_pnl,
            decision_source="lifecycle",
            attribution="managed_exit",
        )
        self._log_position_event(
            position_id=pos_id,
            symbol=symbol,
            event_type="PARTIAL_EXIT",
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            partial_pct=partial_pct,
            size_closed=size_closed,
            size_remaining=size_remaining,
            realized_pnl=realized_pnl,
        )
        if self._forward_logger:
            self._forward_logger.log_partial_exit(
                symbol=symbol, position_id=pos_id,
                partial_pct=partial_pct, size_closed=size_closed,
                size_remaining=size_remaining, exit_price=exit_price,
                realized_pnl=realized_pnl, exit_reason="PARTIAL_TAKE_PROFIT",
                attribution="managed_exit",
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
        
        # Scrub working Broker SL limits since position is now logically closed
        dhan_sl_id = (pos.metadata or {}).get("dhan_sl_order_id")
        if dhan_sl_id:
            try:
                self._broker.cancel_order(dhan_sl_id)
                log.info("Scrubbed broker hardware SL %s for fully closed pos %s", dhan_sl_id, pos.id)
            except Exception as e:
                log.error("Failed to scrub broker hardware SL %s: %s", dhan_sl_id, e)
                
        session = self.get_or_create_session(event.symbol)
        self._record_position_consistency(session, event.symbol, context="post_close")
        session.learning.learn(pos)
        self._overseer_handler.reset_position_state()
        # Journal exit
        mp_metrics = self._lifecycle_handler.trade_manager.get_position_metrics(pos.id)
        # Calculate time in trade (entry_time and exit_time are ISO strings)
        time_in_trade = 0.0
        if pos.exit_time and pos.entry_time:
            try:
                from datetime import datetime as _dt
                _exit = _dt.fromisoformat(pos.exit_time.replace("Z", "+00:00"))
                _entry = _dt.fromisoformat(pos.entry_time.replace("Z", "+00:00"))
                time_in_trade = (_exit - _entry).total_seconds()
            except Exception:
                time_in_trade = (
                    float(mp_metrics["tick_count"]) * 0.5 if mp_metrics else 0.0
                )  # fallback

        self._journal.log_exit(
            symbol=event.symbol,
            position_id=pos.id,
            side=pos.side.value if hasattr(pos.side, 'value') else str(pos.side),
            entry_price=pos.entry_price,
            exit_price=pos.exit_price or pos.entry_price,
            exit_reason=pos.close_reason or "UNKNOWN",
            pnl=pos.pnl,
            time_in_trade_s=time_in_trade,
            mfe=float(mp_metrics["mfe"]) if mp_metrics else 0,
            mae=float(mp_metrics["mae"]) if mp_metrics else 0,
            tick_count=int(mp_metrics["tick_count"]) if mp_metrics else 0,
            amt=session.last_amt,
            decision_source="lifecycle",
            attribution="managed_exit",
        )
        self._log_position_event(
            position_id=pos.id,
            symbol=event.symbol,
            event_type="CLOSED",
            event_time=pos.exit_time or "",
            side=pos.side.value if hasattr(pos.side, "value") else str(pos.side),
            entry_price=pos.entry_price,
            exit_price=pos.exit_price or pos.entry_price,
            pnl=pos.pnl,
            exit_reason=pos.close_reason or "UNKNOWN",
            time_in_trade_s=time_in_trade,
        )
        if self._forward_logger:
            self._forward_logger.log_exit(
                symbol=event.symbol, position_id=pos.id,
                pnl=pos.pnl, mfe=float(mp_metrics["mfe"]) if mp_metrics else 0,
                mae=float(mp_metrics["mae"]) if mp_metrics else 0,
                time_in_trade_s=time_in_trade,
                exit_reason=pos.close_reason or "UNKNOWN",
                attribution="managed_exit",
            )
        # Reset circuit breaker on profitable exit
        if pos.pnl and pos.pnl > 0:
            self._llm_handler.record_successful_exit(symbol=event.symbol)

        # Update session risk manager (Gap #4 — cushion system)
        srm = session._session_risk_manager
        srm.record_trade(pos.pnl)
        
        # COMPOUNDING: Feed TradeManager for dynamic risk calculation
        if hasattr(self._trade_manager, 'add_realized_pnl'):
            self._trade_manager.add_realized_pnl(pos.pnl)
        
        log.info("SessionRisk: tier=%s sl_pct=%.4f pnl=%.2f wins=%d losses=%d",
                 srm.risk_tier.value,
                 srm.stop_loss_pct,
                 srm.session_pnl,
                 srm.consecutive_wins,
                 srm.consecutive_losses)
        # Persist updated risk state (crash-safe)
        if self._storage and hasattr(self._storage, 'kv_set'):
            try:
                import json
                from datetime import date
                self._storage.kv_set(
                    f"risk_state_{event.symbol}_{date.today().isoformat()}",
                    json.dumps(srm.to_dict()),
                )
            except Exception:
                log.debug("Could not persist risk state", exc_info=True)

        # Remove persisted open position (crash recovery cleanup)
        if self._storage:
            try:
                self._storage.delete_open_position(event.position.id)
            except Exception:
                log.debug("Failed to delete persisted position", exc_info=True)

    def _playbook_guard_status(self, session: SessionState) -> dict:
        session_info = getattr(session, "_last_session_info", None)
        agent = getattr(session, "_agent_decision", None)
        amt = session.last_amt or {}
        market_state = str(amt.get("marketState", ""))
        expected = self._expected_playbook_for(session_info, market_state)
        candidate = getattr(agent, "playbook", "") if agent is not None else ""
        session_name = getattr(session_info, "session", "")
        session_compatible = expected != "" or not session_name
        return {
            "session": session_name,
            "marketState": market_state,
            "expectedPlaybook": expected,
            "candidatePlaybook": candidate,
            "guardTripped": self._playbook_guard_tripped(session),
            "maxRejections": Settings().PLAYBOOK_GUARD_MAX_REJECTIONS,
            "totalRejections": self._playbook_guard_total(session),
            "sessionCompatible": session_compatible,
            "agentAligned": (candidate == expected) if candidate and expected else False,
            "lastRejectionReason": getattr(session, "_last_playbook_guard_reason", ""),
            "rejections": dict(getattr(session, "_playbook_guard_rejections", {})),
        }

    def _explainability_status(self, session: SessionState) -> dict:
        total = getattr(session, "_explainability_entries", 0)
        explained = getattr(session, "_explained_entries", 0)
        aggression = getattr(session, "_aggression_explained_entries", 0)
        coverage_rate = round((explained / total * 100.0), 1) if total else 0.0
        aggression_rate = round((aggression / total * 100.0), 1) if total else 0.0
        min_trades = Settings().EXPLAINABILITY_ALERT_MIN_TRADES
        alert = getattr(session, "_last_explainability_alert", "")
        return {
            "entries": total,
            "explainedEntries": explained,
            "aggressionExplainedEntries": aggression,
            "coverageRate": coverage_rate,
            "aggressionDriverRate": aggression_rate,
            "minTrades": min_trades,
            "minCoverageRate": Settings().EXPLAINABILITY_MIN_DRIVER_COVERAGE_PCT,
            "minAggressionRate": Settings().EXPLAINABILITY_MIN_AGGRESSION_DRIVER_PCT,
            "alertActive": bool(alert) and total >= min_trades,
            "alertReason": alert,
        }

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

        rm = self._get_risk_manager(session.symbol)
        
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
            "playbookGuard": self._playbook_guard_status(session),
            "explainabilityMonitor": self._explainability_status(session),
            "rlStatus": self._rl_handler.get_status(),
            "riskState": {
                "halted": rm.is_halted,
                "haltReason": rm.halt_reason,
                "consecutiveLosses": rm.daily_state.consecutive_losses,
                "dailyPnl": rm.daily_state.realized_pnl,
                "driftAlert": rm._drift_alert,
                "driftMessage": rm._drift_message,
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
            "playbook": getattr(ad, "playbook", ""),
            "featureDrivers": list(getattr(ad, "feature_drivers", ())),
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
