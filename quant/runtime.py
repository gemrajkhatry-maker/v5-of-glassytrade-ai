"""QuantEngine — the deterministic single-threaded event loop.

Architecture Overview
=====================
QuantEngine is the per-symbol runtime that consumes ticks, aggregates bars,
makes trading decisions, manages positions, and emits events. It is the
central orchestrator of the quant trading pipeline.

Pipeline Flow:
  Tick → BarAggregator → AMTEngine → DecisionService → PaperOMS → ExitEngine → SessionRisk
                         ↓
                    EventBus (events emitted)

Internal Structure
==================
The engine is organized into these functional areas:

1. LIFECYCLE — construction, run loop, startup/shutdown
2. TICK PROCESSING — tick ingestion, bar aggregation, AMT updates
3. DECISIONS — entry gating, signal translation, submission
4. POSITION MANAGEMENT — entries, exits, pyramids, partials
5. RISK — session risk, portfolio risk, halt logic
6. EVENTS — emission, event store, reconciliation
7. UTILITIES — depth conversion, quote caching, advisors

Each area has well-separated internal methods. The class is large (1,595 lines)
but internally cohesive — every method directly supports the per-symbol runtime.

Only imports ``quant.*`` and stdlib — zero backend/ imports.

Threading and Locking
=====================
This engine runs in a single thread (one thread per symbol, managed by
QuantCoordinator's ThreadPoolExecutor). The single-threaded design eliminates
most concurrency risks, but cross-engine coordination requires care.

Lock Ordering Invariant
-----------------------
When acquiring multiple locks, always acquire in this order:

1. ``_close_lock`` (per-engine, serializes position close operations)
2. ``PortfolioRiskAuthority._lock`` (global, guards aggregate risk tracking)
3. ``SessionRisk._lock`` (per-symbol, guards risk state)

Never acquire locks in reverse order. The single-threaded-per-engine design
prevents deadlock in practice (submit and close cannot interleave on the same
engine), but this invariant must be preserved if the engine is ever refactored
to multi-threaded tick processing.

Cross-Engine Coordination
-------------------------
Engines coordinate only through ``PortfolioRiskAuthority`` (shared across all
engines). All access is guarded by ``PortfolioRiskAuthority._lock``.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from datetime import datetime
from dataclasses import asdict
from typing import Any

from quant.aggregator import BarAggregator
from quant.contracts.constants import CVD_KILL_THRESHOLD
from quant.amt_engine import AMTEngine
from quant.engine.tick_handler import TickHandler
from quant.engine.decision_loop import DecisionLoop
from quant.engine.exit_manager import ExitManager
from quant.amt.dto import empty_amt_dto
from quant.contracts.contracts import ContractRef
from quant.contracts.value_objects import OrderBook, OrderBookLevel
from quant.decision.decision_service import DecisionService
from quant.decision.context_builder import (
    DecisionContextBuilder,
    build_engine_context,
)
from quant.hotpath import get_hotpath_tracer
from quant.position_manager import PositionManager
from quant.session_gates import (
    parse_contract_expiry,
)
from quant.session_levels import SessionLevelStore
from quant.strategy import TradingStrategy
from quant.events import (
    AgentDecisionProduced,
    AmtUpdated,
    BarClosed,
    DecisionProduced,
    DepthUpdated,
    Event,
    EventBus,
    OrderFilled,
    OrderSubmitted,
    PositionClosed,
    PositionReduced,
    PositionOpened,
    RiskUpdated,
    SignalApproved,
    SignalBlocked,
    StopMoved,
)
from quant.execution.execution_model import (
    ExecutionModel,
    validate_execution_model,
)
from quant.execution.exits import ExitEngine
from quant.execution.oms import PaperOMS
from quant.execution.ports import IOMS
from quant.execution.risk import SessionRisk
from quant.contracts.timezones import IST
from quant.persistence import Journal
from quant.state import LiveQuoteCache, _decision_to_view
from quant.bars import DEFAULT_INTERVAL_SEC
from quant.event_store import EventStore
from quant.persistence_boundary import EventAppender, PersistenceHealth
from quant.state_machine import EngineState
from quant.reconciliation_service import PeriodicReconciliationResult
from quant.transitions import apply_event, _position_to_state

logger = logging.getLogger(__name__)

# Opt-in hot-path trace (GLASSYTRADE_HOTPATH_TRACE=1). Zero cost when
# disabled: every call site checks ``_HOTPATH.is_enabled()`` first.
_HOTPATH = get_hotpath_tracer()

# Deterministic conviction used for gate 4's probability check when the engine
# decides from the auction state alone (at the 0.65 data-quality conviction
# threshold). The decision-critical path is 100% deterministic by design — no
# model inference is involved, so _decide never waits on external calls.
# Price-scaled WS ``amt`` keys that must stay on the OPTION contract's scale
# when an option engine merges underlying-futures context into its payload.
# GEX strike levels are deliberately absent: strikes are underlying-scale by
# nature (the option chain's own levels), so they ride through unchanged.
_OPTION_SCALE_KEYS = (
    "poc", "valueAreaHigh", "valueAreaLow", "lvns", "hvns", "profile",
    "aggressivePrints", "sessionVwap", "vwapUpper1", "vwapUpper2",
    "vwapLower1", "vwapLower2", "ibHigh", "ibLow", "ibPoc", "ibVah", "ibVal",
    "priorPoc", "priorVah", "priorVal", "npocAbove", "npocBelow",
    "legProfile", "legLvns", "legPoc", "legVah", "legVal",
    "absorptionClusterHigh", "absorptionClusterLow", "breakLevel",
    "contestedZone", "acceptanceAbove", "acceptanceBelow",
    "rejectionAtHigh", "rejectionAtLow", "squeezeTrappedLevel",
    "dailyVah", "dailyVal", "dailyPoc", "hourlyPoc", "valueMigration",
    "footprints", "halfTrend",
)

# Safe empty shape for the option-scale keys above (built once at import).
_EMPTY_AMT_DTO = empty_amt_dto()


class _LateBound:
    """Proxy that forwards attribute access to a dynamically-resolved object.

    Tests (and the coordinator) sometimes replace engine attributes like
    ``_risk``, ``_strategy``, or ``_oms`` after construction. The DecisionLoop
    captures deps at creation time, so a direct reference would go stale.
    This proxy resolves the target on every attribute access, keeping the
    loop wired to whatever the engine currently holds.
    """
    __slots__ = ("_resolver",)

    def __init__(self, resolver):
        object.__setattr__(self, "_resolver", resolver)

    def __getattr__(self, name):
        return getattr(self._resolver(), name)

    def __repr__(self):
        return f"_LateBound({self._resolver()!r})"



def _as_counter(value) -> int:
    """Coerce a diagnostic counter to int, defaulting to 0 when unusable.

    A stubbed risk object (``MagicMock``) fabricates ANY attribute, so
    ``getattr(obj, "model_sizing_failures", 0)`` returns a mock rather than the
    ``0`` default and comparing two of them raises TypeError. A diagnostic
    counter must never be able to break the sizing guard, so a non-numeric
    value reads as "no failure recorded".
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _resolve_range_bars_flag(explicit: bool | None) -> bool:
    """Plan T8 range flag: explicit kwarg wins, else env, else False.

    Env accepts 1/true/yes/on (and 0/false/no/off) per base.yaml docs.
    Single env-sniff site for GLASSYTRADE_USE_RANGE_BARS.
    """
    if explicit is not None:
        return bool(explicit)
    raw = os.environ.get("GLASSYTRADE_USE_RANGE_BARS", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _tick_epoch_seconds(tick) -> float | None:
    """Best-effort unix seconds from a tick (timestamp_ms, numeric time, ISO)."""
    ts_ms = getattr(tick, "timestamp_ms", None)
    if ts_ms is not None:
        try:
            return int(ts_ms) / 1000.0
        except (TypeError, ValueError):  # silent-except - non-numeric timestamp_ms falls through
            pass
    text = str(getattr(tick, "time", "") or "").strip()
    try:
        val = float(text)
        if val > 100_000_000_000:
            val /= 1000.0
        if val > 1e9:
            return val
    except (TypeError, ValueError):  # silent-except - unparseable time falls through to ISO
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=IST)
        return parsed.timestamp()
    except (TypeError, ValueError):  # silent-except - non-ISO time → no wall-clock anchor
        return None


class QuantEngine:
    # =========================================================================
    # 1. LIFECYCLE — construction, run loop, startup/shutdown
    # =========================================================================
    def __init__(
        self,
        gateway,
        symbol: str,
        interval_seconds: int = DEFAULT_INTERVAL_SEC,
        journal_path: str | None = None,
        min_rr: float = 1.5,
        tick_size: float = 0.05,
        time_stop_bars: int | None = None,
        time_stop_minutes: int = 60,
        cooldown_bars: int | None = None,
        cooldown_minutes: int = 5,
        history_source=None,
        lot_size: float = 1.0,
        market: str = "NSE",
        session_levels: SessionLevelStore | None = None,
        underlying_gateway=None,
        execution_model: str | ExecutionModel | None = None,
        contract: ContractRef | None = None,
        strategy: TradingStrategy | None = None,
        portfolio_risk=None,
        oms=None,
        max_trades_per_session: int = 6,
        advisor=None,
        risk_per_trade_pct: float | None = None,
        capital_deployment_pct: float | None = None,
        max_daily_loss_pct: float = 0.02,
        max_consecutive_losses: int = 3,
        execution_enabled: bool = True,
        seed_scheduler=None,
        max_lots: int | None = None,
        trades_executed=None,
        telemetry=None,
        range_bars_enabled: bool | None = None,
    ) -> None:
        self._gateway = gateway
        # Plan T8: range micro behind GLASSYTRADE_USE_RANGE_BARS (default off).
        # Explicit kwarg wins (live wiring may pass YAML); else read env once
        # here — the single env-sniff site for this flag (F4 noted; the plan
        # explicitly requires the env var).
        self.range_bars_enabled = _resolve_range_bars_flag(range_bars_enabled)
        # Live range warmup: counters advance only on live-tick range closes.
        self._live_range_bars = 0
        self._range_mode_started_at: float | None = None
        self._last_range_tick_epoch: float | None = None
        self._seed_range_bars: list = []
        # Independent mode is the production default. Legacy dual-feed
        # construction remains identifiable and is never implicit in the
        # coordinator path.
        self._execution_model = (
            ExecutionModel.LEGACY_TRANSLATED
            if execution_model is None and underlying_gateway is not None
            else validate_execution_model(execution_model)
        )
        if self._execution_model is ExecutionModel.INDEPENDENT and underlying_gateway is not None:
            raise ValueError(
                "independent execution cannot attach an underlying_gateway; "
                "construct separate engines for futures and options"
            )
        self._underlying_gateway = underlying_gateway
        if contract is not None:
            if not isinstance(contract, ContractRef):
                raise ValueError("QuantEngine contract must be a validated ContractRef")
            if contract.symbol != str(symbol).strip():
                raise ValueError(
                    "QuantEngine contract symbol must match engine symbol: "
                    f"{contract.symbol!r} != {symbol!r}"
                )
        self._contract = contract
        self._portfolio_risk = portfolio_risk  # shared PortfolioRiskAuthority | None
        self._execution_enabled = execution_enabled  # ponytail: False for underlying observer feeds in options mode
        self.telemetry = telemetry
        self.symbol = symbol
        self._tick_size = tick_size
        self._max_lots = max_lots
        from quant.contracts.ports.greeks import DictGreeks
        self._greeks = DictGreeks()
        # Session market for the Fabio phase gates: NSE closes 15:30, MCX
        # trades until 23:30 — a hardcoded NSE table would block every MCX
        # entry after 15:15 ("Session closed").
        m = str(market or "NSE").upper()
        if m in ("NSE", "NFO", "NSE_FNO", "NSE_INDEX", "NSE_OPTIONS"):
            self._market = "NSE"
        elif m in ("MCX", "MCX_COMM", "MCX_COMMODITY", "MCX_OPTIONS"):
            self._market = "MCX"
        else:
            self._market = m
        # Per-contract option expiry (e.g. "CRUDEOIL 17 AUG 7450 CALL" -> 17 Aug):
        # on the contract's own expiry day, MCX gates entries after 21:00 IST
        # (option buying stops at 22:00) and forces a square-off from 21:30 so
        # an ITM option never devolves into a futures position at expiry.
        self._contract_expiry = parse_contract_expiry(symbol)
        self._aggregator = BarAggregator(interval_seconds=interval_seconds)
        # ponytail: 60s micro aggregator drives 1-min entry triggers while 5-minute aggregator retains macro AMT context
        MICRO_SEC = 60
        if interval_seconds > MICRO_SEC and self.range_bars_enabled:
            # Range mode: micro is range-built (interval 0 → bar time = tick
            # time; add_tick bypasses windowing when range_size is set).
            # Provisional H = tick until seed refreshes via ATR(14).
            self._micro_aggregator = BarAggregator(
                interval_seconds=0,
                range_size=max(float(self._tick_size), 1e-12),
            )
        elif interval_seconds > MICRO_SEC:
            self._micro_aggregator = BarAggregator(interval_seconds=MICRO_SEC)
        else:
            self._micro_aggregator = None
        self._underlying_aggregator = (
            BarAggregator(interval_seconds=interval_seconds)
            if self._underlying_gateway is not None
            else None
        )
        self._micro_underlying_aggregator = (
            BarAggregator(interval_seconds=MICRO_SEC)
            if (self._underlying_gateway is not None and interval_seconds > MICRO_SEC)
            else None
        )
        self._history_source = history_source
        # Phase 1 — prior-session levels + naked-POC tracking: the store
        # persists per-symbol {poc, vah, val} across sessions (shared by the
        # coordinator across engines) so the AMT analyzer and the Triple-A
        # take-profit can target the previous balance area (Fabio's rule). A
        # memory-only store is used when none is injected (tests/replay).
        self._session_levels = session_levels or SessionLevelStore()
        self._last_depth: OrderBook | None = None
        self._crashed: bool = False
        self._last_tick_wall: float = time.time()
        self._underlying_warned: bool = False  # Per-engine (no global state)
        # S1 certification records (bounded; drained by cert harness)
        from collections import deque as _dq
        self.cert_records = _dq(maxlen=5_000)
        # AMT analysis engine — owns the candle ring, incremental profile,
        # analyzer, and seed logic. Receives callbacks for depth and risk PnL.
        self._option_amt_engine = None
        self._option_amt_dto: dict | None = None
        self._underlying_amt_dto: dict | None = None
        self._last_underlying_bar = None
        # Last seen option-premium close — the ONLY valid price scale for
        # signals/positions on this (option) engine. Futures-scale prices on
        # an option instrument produce crore-scale phantom P&L.
        self._last_option_close: float = 0.0
        
        # Event sourcing: EventStore is the source of truth
        self.event_store = EventStore()
        self.persistence_health = PersistenceHealth()
        self.event_appender = EventAppender(self.event_store, self.persistence_health)
        # Paper execution must stop pretending persistence is healthy after a
        # side effect has escaped the event store. These markers are deliberately
        # runtime-local and do not alter broker-facing behavior.
        self.persistence_degraded = False
        self.reconciliation_required = False
        self.persistence_failure: Exception | None = None
        self._is_paper_runtime = os.environ.get("GLASSYTRADE_ENV", "paper").strip().lower() == "paper"
        # State is derived from events (cached for performance)
        self.state = EngineState(symbol=symbol)
        from quant.execution.exposure import ExposureState
        self.exposure_state = ExposureState.none()

        if self._underlying_gateway is not None:
            underlying_symbol = (
                getattr(self._underlying_gateway, "_symbol", None)
                or self._underlying()
            )
            # 1. Underlying futures AMT engine (decision brain)
            self._amt_engine = AMTEngine(
                symbol=underlying_symbol,
                market=self._market,
                session_levels=self._session_levels,
                history_source=history_source,
                underlying_fn=self._underlying,
                get_depth=lambda: self._last_depth,
                get_risk_pnl=lambda: self._risk.state().daily_pnl if hasattr(self, '_risk') else 0.0,
                interval_seconds=interval_seconds,
                seed_scheduler=seed_scheduler,
                range_bars_enabled=self.range_bars_enabled,
                tick_size=self._tick_size,
            )
            # 2. Option contract AMT engine (option volume profile, POC, VAH, VAL)
            self._option_amt_engine = AMTEngine(
                symbol=self.symbol,
                market=self._market,
                session_levels=self._session_levels,
                history_source=history_source,
                underlying_fn=self._underlying,
                get_depth=lambda: self._last_depth,
                get_risk_pnl=lambda: self._risk.state().daily_pnl if hasattr(self, '_risk') else 0.0,
                interval_seconds=interval_seconds,
                seed_scheduler=seed_scheduler,
                range_bars_enabled=self.range_bars_enabled,
                tick_size=self._tick_size,
            )
        else:
            self._amt_engine = AMTEngine(
                symbol=symbol,
                market=self._market,
                session_levels=self._session_levels,
                history_source=history_source,
                underlying_fn=self._underlying,
                get_depth=lambda: self._last_depth,
                get_risk_pnl=lambda: self._risk.state().daily_pnl if hasattr(self, '_risk') else 0.0,
                interval_seconds=interval_seconds,
                seed_scheduler=seed_scheduler,
                range_bars_enabled=self.range_bars_enabled,
                tick_size=self._tick_size,
            )
        self._decision_service = DecisionService(min_rr=min_rr)
        # IOMS port: the engine never constructs its own OMS — the coordinator
        # injects PaperOMS (paper/replay/backtest) or LiveOMS (live). Paper
        # remains the safe default for direct replay/test construction.
        self._oms: IOMS = oms if oms is not None else PaperOMS(lot_size=lot_size)
        # Bar-count knobs are wall-clock MINUTES by default; bar counts are
        # derived from the ACTUAL bar interval so moving 1m -> 5m bars cannot
        # silently multiply durations x5 (a literal 60-bar stop meant 1h on
        # 1m bars but 5h on 5m bars). An explicit ``time_stop_bars`` (legacy
        # callers/tests) overrides the minute-based derivation unchanged.
        _interval_sec = max(1, int(interval_seconds))
        if time_stop_bars is None:
            time_stop_bars = max(1, int(time_stop_minutes) * 60 // _interval_sec)
        # ponytail: mirror BE constant; tune from journal replay later
        _cvd_be = 1.0 if str(self._market).upper() == "MCX" else 2.0
        self._exits = ExitEngine(
            time_stop_bars=time_stop_bars,
            cvd_kill_threshold=CVD_KILL_THRESHOLD,
            cvd_be_threshold=_cvd_be,
        )
        # Strategy — single entry authority (decision 2026-09-17): the
        # deterministic Fabio AMT gate pipeline. An explicitly injected strategy
        # (tests/replay) still wins; nothing else may swap the entry authority.
        if strategy is not None:
            self._strategy = strategy
        else:
            from quant.strategies.selection import build_strategy
            self._strategy = build_strategy(
                decision_service=self._decision_service,
                exit_engine=self._exits,
            )
        # SessionLevelStore now exposes kv_get/kv_set (its JSON file), so the
        # daily-loss budget survives restart through the same port that already
        # persists prior-session POC/VAH/VAL.
        # SessionRisk must be initialized with today's date so the storage key
        # is "daily_risk:SYMBOL:2026-08-17" — NOT "daily_risk:SYMBOL:None".
        # _session_date is always None at __init__ time (set on first bar), so
        # we pass None here and SessionRisk._today() fills it correctly.
        base_risk = risk_per_trade_pct if risk_per_trade_pct is not None else 0.005
        from quant.contracts.aggregates import INITIAL_CAPITAL
        _equity = float(
            getattr(self._portfolio_risk, "_starting_equity", None) or INITIAL_CAPITAL
        )
        self._risk = SessionRisk(
            storage=self._session_levels,
            symbol=self.symbol,
            portfolio_risk=self._portfolio_risk,
            max_trades_per_session=max_trades_per_session,
            capital_deployment_pct=capital_deployment_pct,
            max_daily_loss_pct=max_daily_loss_pct,
            max_consecutive_losses=max_consecutive_losses,
            base_risk_pct=base_risk,
            day_of_week=datetime.now(tz=IST).weekday(),
            starting_equity=_equity,
        )
        self._bus = EventBus()
        # Passive hot-path trace (B7): bar/decision/fill phases are mapped by
        # a bus subscriber owned by quant.hotpath — the engine publishes
        # events and holds no trace field-extraction logic. The subscriber is
        # a no-op while the tracer is disabled.
        from quant.hotpath import HotPathSubscriber
        HotPathSubscriber.subscribe(self._bus)
        self._live = LiveQuoteCache(interval_sec=interval_seconds)
        # Latest event-derived values for the WS snapshot (amt, decisions).
        # These are updated inline by _emit() so the coordinator can read
        # them without replaying the event trace.
        self._latest_amt: dict | None = None
        self._latest_quant_decision: dict | None = None
        self._latest_agent_decision: dict | None = None
        self._latest_depth: dict | None = None
        self._journal_subscribed = False
        self._journal = None
        if journal_path:
            # Constructor-provided journal: attach immediately so the bus
            # subscription exists before run() starts capturing events.
            from quant.persistence import Journal

            self._journal = Journal(path=journal_path)
            self._journal_subscribed = True

            journal_subscriber = self._create_journal_subscriber()
            for evt_type in self._get_journal_event_types():
                self._bus.subscribe(evt_type, journal_subscriber,
                                    priority=-100)
        else:
            self._pending_journal_path = None
            self._journal_subscribed = False
        # ponytail: bounded ring for the whole-session trace. 10k bars @ ~10 events
        # per bar covers a 6.5-hour NSE session; older events fall out of memory.
        # Full history still lands in the tick journal (quant/persistence.Journal).
        self._trace: deque[Event] = deque(maxlen=10_000)
        # Setup latch: approved-but-blocked episodes, keyed by (signal symbol,
        # side) → block reason. Emits SignalBlocked once per blocking episode
        # instead of once per micro-bar. The dict is wiped on any non-approved
        # decision (market changed → episodes stale) and per-key on successful
        # entry. Never suppresses evaluation.
        self._latch: dict[tuple[str, str], str] = {}
        self._bar_index = 0
        # History bars seeded into the AMT engine count toward the warmup
        # requirement (accessed via self._amt_engine.warm_bars).
        self._entry_bar_index = 0
        self._subscribed = False
        self._emit_lock = threading.Lock()
        # Serializes time-driven force-close (EOD watchdog / SIGTERM) against
        # concurrent close attempts so the full position (base + pyramids) is
        # flattened exactly once.
        self._close_lock = threading.Lock()
        # Post-trade cooldown: after a fill, the engine waits this many bars
        # before evaluating a new entry. Prevents chasing consecutive signals.
        # Derived from wall-clock minutes so the wait stays ~5 minutes on ANY
        # bar interval (5 bars @ 1m, 1 bar @ 5m) instead of silently scaling
        # with the timeframe. An explicit ``cooldown_bars`` (legacy
        # callers/tests) overrides the minute-based derivation unchanged.
        if cooldown_bars is None:
            cooldown_bars = max(
                1, int(cooldown_minutes) * 60 // max(1, int(interval_seconds))
            )
        self._cooldown_bars: int = cooldown_bars
        self._last_close_bar_index: int = -1  # bar index of most recent fill
        self._recent_decisions: deque[dict[str, Any]] = deque(maxlen=5)
        # F4: NO environment sniffing inside the deterministic engine. The
        # advisor is injected explicitly (default None -> no advisor, no
        # threads). Only the live wiring path reads MLX_* env vars — see
        # quant.wiring_advisor.build_live_advisor — so backtest/replay
        # constructions stay thread-free and reproducible.
        self._advisor = advisor
        self._trades_executed = trades_executed
        # DecisionLoop: encapsulates the entry decision pipeline (entry guards,
        # context build, strategy evaluation, signal translation, submission).
        # Created after all dependencies are initialized so it can bind to them.
        self._decision_loop = self._create_decision_loop()
        # ExitManager: encapsulates all exit evaluation and execution logic
        # (bar exits, tick exits, thesis flip, full close, bookkeeping).
        self._exit_manager = self._create_exit_manager()

    # =========================================================================
    # 2. TICK PROCESSING — tick ingestion, bar aggregation, AMT updates
    # =========================================================================
    def run(self, max_steps: int | None = None) -> list[Event]:
        """Consume ticks from the gateway, drive the full pipeline, and return
        the event trace. Deterministic: same ticks -> same trace.

        Crash containment: the coordinator runs this on a bare thread with no
        supervision — an unguarded exception here (e.g. OMS failure, journal
        disk-full) silently killed the thread and the symbol stopped trading
        with no signal anywhere (proven empirically). The guard converts a
        thread death into a loud, logged failure; the engine stays dead by
        design (fail-stop for trading state) but the coordinator's liveness
        check now sees it."""
        try:
            return self._run_inner(max_steps)
        except Exception:
            import logging

            logging.getLogger(__name__).critical(
                "ENGINE THREAD DIED — symbol %s stopped trading. "
                "positions_open=%s last_bar_index=%s",
                self.symbol, self.state.position is not None, self._bar_index,
                exc_info=True,
            )
            self._crashed = True
            raise

    def _create_journal_subscriber(self) -> callable:
        """Create a journal subscriber closure that writes events to the journal.
        
        This is a single source of truth for the journal subscriber logic,
        used by both __init__() and attach_journal() to avoid duplication.
        
        Returns:
            A callable that accepts an Event and writes it to the journal.
        """
        def _journal_subscriber(event: Event) -> None:
            self._journal.append(
                {"type": event.__class__.__name__, **asdict(event)}
            )
        return _journal_subscriber

    def _get_journal_event_types(self) -> tuple:
        """Return the event types that should be journaled.
        
        Single source of truth for the list of event types that get written
        to the journal. Used by both __init__() and attach_journal().
        """
        return (BarClosed, DecisionProduced,
                SignalApproved, SignalBlocked,
                PositionOpened, PositionClosed,
                PositionReduced,
                RiskUpdated, DepthUpdated, AmtUpdated,
                OrderSubmitted, OrderFilled, StopMoved)

    def attach_journal(self, path: str | None = None) -> None:
        """Attach the fsync JSONL event journal and subscribe it to the bus.

        Called by the coordinator after construction so journals land in a
        per-day directory. Subscribes lazily so late attachment (post
        constructor, pre-run) still captures every event.
        """

        path = (
            path
            or getattr(self, "journal_path", None)
            or self._pending_journal_path
        )
        if not path or self._journal is not None:
            return
        self._journal = Journal(path=path)
        self._pending_journal_path = None
        if self._journal_subscribed:
            return
        self._journal_subscribed = True

        journal_subscriber = self._create_journal_subscriber()
        for evt_type in self._get_journal_event_types():
            self._bus.subscribe(evt_type, journal_subscriber, priority=-100)

    def attach_storage(self, storage) -> None:
        """Project PositionOpened/Closed onto IStorage (restart book)."""
        from quant.persistence_bridge import PositionStorageBridge
        PositionStorageBridge(storage, contract=self._contract).attach(self._bus)
        self._storage = storage
        # Dated SessionLevelStore is the sole prior-levels authority.
        # Do NOT overwrite with undated prior_profile kv (audit §5.3).
        try:
            if hasattr(self, "_amt_engine") and hasattr(self._amt_engine, "_prior"):
                dated = self._session_levels.load_levels(self.symbol) if self._session_levels else {}
                if dated and dated.get("poc"):
                    self._amt_engine.set_prior_profile(
                        poc=float(dated["poc"]),
                        vah=float(dated.get("vah") or 0.0),
                        val=float(dated.get("val") or 0.0),
                        close=float(dated.get("close") or 0.0),
                    )
        except Exception:
            logger.exception("Failed to load dated prior levels for %s", self.symbol)
        self.restore_kernel_state()

    def set_option_delta(self, delta: float, *, symbol: str | None = None) -> None:
        """Stamp the execution contract's Greek delta for option translation."""
        self._greeks.set_delta(symbol or self.symbol, delta)

    def persist_prior_profile(self) -> None:
        """Persist current session POC/VAH/VAL to storage as prior profile."""
        storage = getattr(self, "_storage", None)
        if storage is None:
            return
        amt = getattr(self._amt_engine, "last_amt_dto", None) or {}
        poc = float(amt.get("poc") or 0.0)
        if poc > 0:
            try:
                from quant.amt.session.context import persist_prior_profile
                persist_prior_profile(
                    storage,
                    self.symbol,
                    poc=poc,
                    vah=float(amt.get("valueAreaHigh") or 0.0),
                    val=float(amt.get("valueAreaLow") or 0.0),
                )
            except Exception:
                logger.exception("Failed to persist prior profile for %s", self.symbol)
        self.persist_kernel_state()

    def persist_kernel_state(self) -> None:
        """Persist SessionKernel CVD/VWAP/IB/warmth for mid-session restart."""
        storage = getattr(self, "_storage", None)
        amt = getattr(self, "_amt_engine", None)
        if storage is None or amt is None or not hasattr(amt, "export_kernel_state"):
            return
        try:
            from quant.amt.session.context import persist_kernel_state
            persist_kernel_state(storage, self.symbol, amt.export_kernel_state())
        except Exception:
            logger.exception("Failed to persist kernel state for %s", self.symbol)

    def restore_kernel_state(self) -> None:
        """Rehydrate SessionKernel trackers from the durable kv snapshot."""
        storage = getattr(self, "_storage", None)
        amt = getattr(self, "_amt_engine", None)
        if storage is None or amt is None or not hasattr(amt, "import_kernel_state"):
            return
        try:
            from quant.amt.session.context import load_kernel_state
            snap = load_kernel_state(storage, self.symbol)
            if snap:
                amt.import_kernel_state(snap)
        except Exception:
            logger.exception("Failed to restore kernel state for %s", self.symbol)

    def restore_position(self, position, *, stop_meta: dict | None = None) -> None:
        """Rehydrate the in-memory book after a process restart."""
        pm = self._get_position_manager()
        pm.current_position = position
        self.state = self.state.with_position(_position_to_state(position))
        self._entry_bar_index = self._bar_index
        meta = stop_meta or {}
        epoch = float(meta.get("entry_time_epoch") or 0.0)
        if epoch <= 0:
            # Prefer a parseable open_time over leaving the time-stop dead (0.0).
            try:
                from quant.contracts.timezones import parse_bar_time
                parsed = parse_bar_time(getattr(position, "open_time", "") or "")
                epoch = float(parsed.timestamp()) if parsed is not None else 0.0
            except Exception:
                epoch = 0.0
        self._entry_time_epoch = epoch
        be = meta.get("breakeven")
        trail = meta.get("trail_stop")
        tier = int(meta.get("tp_tier") or 0)
        if be or trail or tier:
            pm._exits.restore_stop_state(
                position,
                breakeven=float(be) if be else None,
                trail_stop=float(trail) if trail else None,
                tp_tier=tier,
            )
        # Seed EventStore with baseline PositionOpened so event sourcing
        # and subsequent fold()/PositionClosed remain consistent.
        from quant.events import PositionOpened
        ts = getattr(position, "open_time", None) or getattr(position, "entry_time", None) or "0"
        self.event_store.append(
            PositionOpened(symbol=self.symbol, time=str(ts), position=position)
        )
        if self._portfolio_risk is not None:
            order = getattr(position, "order", None)
            sig = getattr(order, "signal", None)
            entry = float(
                getattr(sig, "entry", 0.0)
                or getattr(position, "entry", 0.0)
                or getattr(position, "entry_price", 0.0)
                or getattr(position, "open_price", 0.0)
                or 0.0
            )
            sl = float(
                getattr(sig, "sl", 0.0)
                or getattr(position, "sl", 0.0)
                or getattr(position, "stop_loss", 0.0)
                or 0.0
            )
            size = float(getattr(position, "size", 0.0) or 0.0)
            qty = abs(size) or float(
                getattr(order, "quantity", 0.0)
                or getattr(position, "qty", 0.0)
                or getattr(position, "quantity", 0.0)
                or 0.0
            )
            risk = abs(entry - sl) * qty if (entry and sl and qty) else 0.0
            self._portfolio_risk.register_open(risk, symbol=self.symbol)

    def close(self) -> None:
        """Cleanly release attached resources (advisor, journal)."""
        advisor = getattr(self, "_advisor", None)
        if advisor is not None and callable(getattr(advisor, "shutdown", None)):
            try:
                advisor.shutdown()
            except Exception:
                logger.warning("advisor shutdown failed; continuing runtime close", exc_info=True)
        journal = getattr(self, "_journal", None)
        if journal is not None and callable(getattr(journal, "close", None)):
            try:
                journal.close()
            except Exception:
                logger.warning("journal close failed; continuing runtime close", exc_info=True)

    def _cert_trace(self, bar=None, stage: str = "", **fields) -> None:
        """S1 decision traceability: append a certification record for this
        bar. Bounded buffer; consumed by tests/nightly certification runs
        via engine.cert_records. Nothing here can raise into the run loop."""
        try:
            rec = {"symbol": self.symbol,
                   "time": getattr(bar, "time", "") if bar else "",
                   "stage": stage}
            rec.update(fields)
            if bar is not None:
                rec["bar_index"] = self._bar_index
                rec["position_open"] = self.state.position is not None
            self.cert_records.append(rec)
        except Exception as e:  # certification record append must never break trading
            logger.debug(f"Certification record append failed: {e}")

    def _create_tick_handler(self) -> TickHandler:
        """Build a TickHandler wired to this engine's callbacks and state.

        Called once by ``_run_inner()`` before the tick loop starts. All
        callbacks are bound methods or thin closures so the handler can drive
        the full pipeline without knowing about QuantEngine internals.
        """
        def _depth_update(depth) -> None:
            self._last_depth = self._depth_to_book(depth)

        def _hotpath_emit(symbol: str, phase: str, time_str: str, price: float, source: str) -> None:
            if _HOTPATH.enabled:
                _HOTPATH.try_emit(symbol, phase, time=time_str, price=price, source=source)

        return TickHandler(
            symbol=self.symbol,
            macro_aggregator=self._aggregator,
            micro_aggregator=self._micro_aggregator,
            amt_engine=self._amt_engine,
            state_getter=lambda: self.state,
            # Core callbacks
            manage_tick_exit_callback=self._manage_tick_exit,
            decide_callback=self._decide,
            on_bar_closed_callback=self._on_bar_closed,
            manage_exit_callback=self._manage_exit,
            # Option-specific (None for futures-only engines)
            underlying_gateway=self._underlying_gateway,
            underlying_aggregator=self._underlying_aggregator,
            micro_underlying_aggregator=self._micro_underlying_aggregator,
            option_amt_engine=self._option_amt_engine,
            # Live quote and depth
            live_quote_callback=self._live.on_quote,
            depth_callback=_depth_update,
            # Hotpath tracing
            hotpath_callback=_hotpath_emit if _HOTPATH.enabled else None,
            # State tracking setters (keep QuantEngine state in sync)
            underlying_bar_setter=lambda bar: setattr(self, "_last_underlying_bar", bar),
            underlying_amt_dto_setter=lambda dto: setattr(self, "_underlying_amt_dto", dto),
            option_amt_dto_setter=lambda dto: setattr(self, "_option_amt_dto", dto),
            bar_index_increaser=lambda: setattr(self, "_bar_index", self._bar_index + 1),
            bar_closed_emitter=lambda sym, t, bar: self._emit(BarClosed(symbol=sym, time=t, bar=bar)),
            merged_amt_emitter=self._emit_merged_amt,
            range_tick_callback=self._on_range_live_tick,
            range_bar_closed_callback=self._on_range_bar_closed,
            telemetry=self.telemetry,
        )

    # --- Range-mode live warmup (plan T8) ---------------------------------
    @property
    def live_range_bars(self) -> int:
        """Closed range micro bars from live ticks — seed/synth never count."""
        return self._live_range_bars

    @property
    def range_start_epoch(self) -> float | None:
        """Epoch of the first live tick in range mode (wall-clock anchor)."""
        return self._range_mode_started_at

    def live_range_minutes(self) -> float:
        """Minutes elapsed since the first live range-mode tick."""
        if self._range_mode_started_at is None:
            return 0.0
        now = (
            self._last_range_tick_epoch
            if self._last_range_tick_epoch is not None
            else time.time()
        )
        return max(0.0, (now - self._range_mode_started_at) / 60.0)

    # Private alias — tests/contract readers use the underscore form.
    _live_range_minutes = live_range_minutes

    def _get_range_warmup(self) -> tuple[bool, int, float]:
        """Range-mode warmup triple — one expression for build_engine_context
        and the DecisionLoop/ExitManager ``get_range_warmup`` state wiring."""
        return (
            bool(self.range_bars_enabled),
            int(self._live_range_bars),
            float(self.live_range_minutes()),
        )

    def _on_range_live_tick(self, tick) -> None:
        epoch = _tick_epoch_seconds(tick)
        if self._range_mode_started_at is None and epoch is not None:
            self._range_mode_started_at = epoch
        if epoch is not None:
            self._last_range_tick_epoch = epoch
        elif self._range_mode_started_at is None:
            self._range_mode_started_at = time.time()

    def _on_range_bar_closed(self) -> None:
        self._live_range_bars += 1

    def _refresh_range_h_after_seed(self) -> None:
        """Recompute H_range from seed candles + build non-live synth seed bars."""
        if not self.range_bars_enabled or self._micro_aggregator is None:
            return
        from quant.amt.range_seed import h_range_from_ohlcs, synth_range_bars

        # Prefer the H the AMT engine derived during its range-mode seed.
        h = float(getattr(self._amt_engine, "last_range_h", 0.0) or 0.0)
        candles = list(getattr(self._amt_engine, "session_candles", ()) or ())
        if h <= 0 and candles:
            h = h_range_from_ohlcs(candles, self._tick_size)
        if h > 0:
            self._micro_aggregator.range_size = h
        # Synth range bars from seed OHLCV — stored, never counted live.
        if candles and h > 0:
            try:
                self._seed_range_bars = synth_range_bars(candles, h)
            except ValueError:
                self._seed_range_bars = []

    def _create_decision_loop(self) -> DecisionLoop:
        """Build a DecisionLoop wired to this engine's state and dependencies.

        Called once at the end of ``__init__``. All mutable state is accessed
        through callbacks so the loop is fully testable in isolation.
        """
        config = {
            "symbol": self.symbol,
            "market": self._market,
            "contract_expiry": self._contract_expiry,
            "tick_size": self._tick_size,
            "cooldown_bars": self._cooldown_bars,
            "max_lots": self._max_lots,
        }
        deps = {
            "risk": _LateBound(lambda: self._risk),
            "get_portfolio_risk": lambda: self._portfolio_risk,
            "get_opportunity_auction": lambda: getattr(self, "_opportunity_auction", None),
            "oms": _LateBound(lambda: self._oms),
            "strategy": _LateBound(lambda: self._strategy),
            "amt_engine": _LateBound(lambda: self._amt_engine),
            "get_position_manager": self._get_position_manager,
            "execution_model": self._execution_model,
            "contract": self._contract,
            "underlying_gateway": self._underlying_gateway,
            "execution_enabled": self._execution_enabled,
            "live_mode": lambda: bool(getattr(self._oms, "is_live", False)),
            "get_underlying_symbol": self._underlying if self._underlying_gateway is not None else None,
            "trades_executed": self._trades_executed,
            "greeks": getattr(self, "_greeks", None),
        }
        state = {
            "get_bar_index": lambda: self._bar_index,
            "get_entry_bar_index": lambda: self._entry_bar_index,
            "set_entry_bar_index": lambda v: setattr(self, "_entry_bar_index", v),
            "get_last_close_bar_index": lambda: self._last_close_bar_index,
            "get_latch": lambda: self._latch,
            "set_latch": lambda k, v: self._latch.__setitem__(k, v),
            "clear_latch": lambda: self._latch.clear(),
            "pop_latch": lambda key: self._latch.pop(key, None),
            "get_cert_records": lambda: self.cert_records,
            "get_last_depth": lambda: self._last_depth,
            "get_recent_decisions": lambda: self._recent_decisions,
            "get_open_trade_risk": lambda: getattr(self, "_open_trade_risk", 0.0),
            "set_open_trade_risk": lambda v: setattr(self, "_open_trade_risk", v),
            "get_exposure_state": lambda: getattr(self, "exposure_state", None),
            "get_startup_block": lambda: bool(
                self.persistence_degraded
                or self.reconciliation_required
                or getattr(self, "_startup_issue_fn", lambda: False)()
            ),
            "set_exposure_state": lambda v: setattr(self, "exposure_state", v),
            "set_entry_time_epoch": lambda v: setattr(self, "_entry_time_epoch", v),
            "get_state": lambda: self.state,
            "get_range_warmup": self._get_range_warmup,
        }
        return DecisionLoop(
            config=config,
            deps=deps,
            state=state,
            emit=self._emit,
            forecast_fn=self._fresh_forecast,
            advisor=getattr(self, "_advisor", None),
            telemetry=getattr(self, "telemetry", None),
        )

    def _create_exit_manager(self) -> ExitManager:
        """Build an ExitManager wired to this engine's state and dependencies.

        Called once at the end of ``__init__``. All mutable state is accessed
        through callbacks so the manager is fully testable in isolation.
        """
        config = {
            "symbol": self.symbol,
            "market": self._market,
            "contract_expiry": self._contract_expiry,
            "tick_size": self._tick_size,
            "cooldown_bars": self._cooldown_bars,
        }
        deps = {
            "get_position_manager": self._get_position_manager,
            "get_portfolio_risk": lambda: self._portfolio_risk,
            "strategy": _LateBound(lambda: self._strategy),
            "amt_engine": _LateBound(lambda: self._amt_engine),
            "aggregator": self._aggregator,
            "get_underlying_symbol": self._underlying if self._underlying_gateway is not None else None,
            "close_lock": self._close_lock,
            "underlying_gateway": self._underlying_gateway,
            "risk": _LateBound(lambda: self._risk),
            "greeks": getattr(self, "_greeks", None),
        }
        state = {
            "get_bar_index": lambda: self._bar_index,
            "get_entry_bar_index": lambda: self._entry_bar_index,
            "get_entry_time_epoch": lambda: getattr(self, "_entry_time_epoch", 0.0),
            "get_last_close_bar_index": lambda: self._last_close_bar_index,
            "set_last_close_bar_index": lambda v: setattr(self, "_last_close_bar_index", v),
            "get_open_trade_risk": lambda: getattr(self, "_open_trade_risk", 0.0),
            "set_open_trade_risk": lambda v: setattr(self, "_open_trade_risk", v),
            "get_state": lambda: self.state,
            "set_state": lambda s: setattr(self, "state", s),
            "get_last_depth": lambda: self._last_depth,
            "get_recent_decisions": lambda: self._recent_decisions,
            "get_underlying_amt_dto": lambda: self._underlying_amt_dto,
            "get_last_underlying_bar": lambda: self._last_underlying_bar,
            "get_option_amt_dto": lambda: self._option_amt_dto,
            "get_range_warmup": self._get_range_warmup,
        }
        return ExitManager(
            config=config,
            deps=deps,
            state=state,
            emit=self._emit,
            forecast_fn=self._fresh_forecast,
            advisor=getattr(self, "_advisor", None),
        )

    def _run_inner(self, max_steps: int | None = None) -> list[Event]:
        if not self._subscribed:
            self._gateway.subscribe(self.symbol)
            self._subscribed = True
        if self._underlying_gateway is not None:
            # Fabio Task 8: auction structure belongs on the underlying futures.
            # Subscribe the second feed; its ticks feed AMT via the aggregator.
            self._underlying_gateway.subscribe(self._underlying())
        elif not self._underlying_warned and self._contract_expiry is not None:
            # Option contract with no underlying feed — running AMT on the
            # option's own premium is a fallback, not the faithful setup.
            # Warning state is per-engine (self._underlying_warned) so one
            # engine's startup path never mutates a module global.
            self._underlying_warned = True
            logger.info(
                "Independent scalping active for %s — running AMT directly on option premium.",
                self.symbol,
            )
        self._amt_engine.seed()
        if self._option_amt_engine is not None:
            self._option_amt_engine.seed()
            if self._option_amt_engine.last_amt_dto:
                self._option_amt_dto = self._option_amt_engine.last_amt_dto
                if self._amt_engine.last_amt_dto:
                    self._underlying_amt_dto = self._amt_engine.last_amt_dto
                self._emit_merged_amt(self._option_amt_dto, self._option_amt_dto.get("time", ""))
        elif self._amt_engine.last_amt_dto:
            self._underlying_amt_dto = self._amt_engine.last_amt_dto
            self._emit(AmtUpdated(symbol=self.symbol, time=self._amt_engine.last_amt_dto.get("time", ""), amt=self._amt_engine.last_amt_dto))
        self._refresh_range_h_after_seed()

        initial_amt = self._option_amt_dto or self._amt_engine.last_amt_dto
        if initial_amt and hasattr(self, "_advisor") and self._advisor is not None:
            contract_symbol = (
                self.symbol if self._underlying_gateway is not None else None
            )
            ctx = DecisionContextBuilder(greeks=self._greeks).build(
                bar=self._amt_engine.last_bar,
                symbol=self.symbol,
                market=self._market,
                contract_expiry=self._contract_expiry,
                tick_size=self._tick_size,
                bar_index=0,
                warm_bars=self._amt_engine.warm_bars,
                cooldown_remaining_sec=0,
                risk_state=self._risk.state(),
                amt_dto=initial_amt,
                order_book=self._last_depth,
                recent_decisions=list(self._recent_decisions),
                contract_symbol=contract_symbol,
            )
            self._advisor.on_context(ctx)

        tick_handler = self._create_tick_handler()
        steps = 0
        while True:
            if max_steps is not None and steps >= max_steps:
                break
            tick = self._gateway.next_tick()
            if tick is None:
                break
            steps += 1
            # Freshness: prefer local arrival over exchange LTT. An illiquid
            # contract's last_trade_time can lag by minutes while quote/depth
            # packets still arrive — using LTT alone falsely marked those
            # engines stale. Arrival still catches true backlog (a tick that
            # sat in the queue for hours carries an old arrived_at).
            try:
                tick_epoch = float(getattr(tick, "time", 0) or 0)
            except (TypeError, ValueError):
                tick_epoch = 0.0
            try:
                arrived = float(getattr(tick, "arrived_at", 0) or 0)
            except (TypeError, ValueError):
                arrived = 0.0
            if arrived > 1e9:
                self._last_tick_wall = arrived
            elif tick_epoch > 1e9:
                self._last_tick_wall = tick_epoch
            else:
                self._last_tick_wall = time.time()
            tick_handler.process_tick(tick)
        return list(self._trace)

    @property
    def events(self) -> tuple[Event, ...]:
        return tuple(self._trace)

    @property
    def live_cache(self) -> LiveQuoteCache:
        return self._live

    # =========================================================================
    # 3. POSITION MANAGEMENT — entries, exits, pyramids, partials
    # =========================================================================

    @property
    def latest_amt(self) -> dict | None:
        return self._latest_amt

    @property
    def latest_quant_decision(self) -> dict | None:
        return self._latest_quant_decision

    @property
    def latest_agent_decision(self) -> dict | None:
        return self._latest_agent_decision

    @property
    def latest_depth(self) -> dict | None:
        return self._latest_depth

    def _release_partial_reserves(self, pm: PositionManager, remaining) -> None:
        """Fractional portfolio-risk reserve release after a tiered partial exit.

        Delegates to the ExitManager. Retained as a thin wrapper so that
        direct callers continue to work.
        """
        self._exit_manager._release_partial_reserves(pm, remaining)

    def _manage_tick_exit(self, tick_price: float, tick_time: str) -> None:
        """Tick-level fast stop-loss and take-profit breach check (Fabio).

        Delegates to the ExitManager. Retained as a thin wrapper so that
        direct callers (TickHandler) continue to work.
        """
        self._exit_manager.manage_tick_exit(tick_price, tick_time)

    def _emit_merged_amt(self, base_dto: dict, time_str: str) -> None:
        merged = dict(self._underlying_amt_dto or base_dto)
        opt_dto = self._option_amt_dto or (self._option_amt_engine.last_amt_dto if self._option_amt_engine else None)
        # Option-scale price fields. The WS ``amt`` payload renders ON the
        # option contract's chart (candles at premium scale ~50-200), so every
        # price-scaled display field must come from the OPTION engine — never
        # from the underlying futures (~24,000). A futures-scale overlay on an
        # option chart is drawn tens of thousands of points off-scale: the
        # HalfTrend line, VWAP/IB/prior levels, absorption clusters and volume
        # profile (architectural review finding 4 — the pre-fix merge only
        # overrode profile/poc/VAH/VAL/hvns/lvns/leg*, leaking futures-scale
        # halfTrend and VWAP/IB levels onto the option chart).
        if self._option_amt_engine is not None:
            if opt_dto is not None:
                for key in _OPTION_SCALE_KEYS:
                    if key in opt_dto and opt_dto[key] is not None:
                        merged[key] = opt_dto[key]
            else:
                # Option engine exists but has no analysis yet — replace every
                # price-scaled key with the safe empty shape so a futures-scale
                # value can never ride through to the option chart.
                for key in _OPTION_SCALE_KEYS:
                    merged[key] = _EMPTY_AMT_DTO.get(key)
        merged["barInterval"] = getattr(self._aggregator, "interval_seconds", DEFAULT_INTERVAL_SEC)
        merged["microBarInterval"] = getattr(self._micro_aggregator, "interval_seconds", 60) if self._micro_aggregator is not None else None
        self._emit(AmtUpdated(symbol=self.symbol, time=time_str, amt=merged))

    def _on_bar_closed(self, bar) -> None:
        self._bar_index += 1
        self._emit(BarClosed(symbol=self.symbol, time=bar.time, bar=bar))
        # Snapshot the AMT DTO for this bar so the banner/UI sees the same
        # auction evidence the decision path used.
        amt_dto = self._amt_engine.analyze(bar)
        amt_dto["barInterval"] = getattr(self._aggregator, "interval_seconds", DEFAULT_INTERVAL_SEC)
        amt_dto["microBarInterval"] = getattr(self._micro_aggregator, "interval_seconds", 60) if self._micro_aggregator is not None else None
        self._emit(AmtUpdated(symbol=self.symbol, time=bar.time, amt=amt_dto))

        if self.state.position is not None:
            self._manage_exit(amt_dto, bar)
            if hasattr(self, "_advisor") and self._advisor is not None and self.state.position is not None:
                ctx = self._build_context(bar, amt_dto, 0.0)
                self._advisor.on_context(ctx)
        elif self._micro_aggregator is None:
            self._decide(amt_dto, bar)

    # =========================================================================
    # 4. DECISIONS — entry gating, signal translation, submission
    #    Delegated to DecisionLoop (quant/engine/decision_loop.py)
    # =========================================================================
    def _decide(self, amt_dto: dict, bar, execution_bar=None) -> None:
        """Delegate entry evaluation to the DecisionLoop.

        The DecisionLoop encapsulates the full pipeline: entry guards, context
        build, strategy evaluation, signal translation, risk ceilings, sizing,
        OMS submission, and event emission.
        """
        self._decision_loop.evaluate(amt_dto, bar, execution_bar)

    def _entry_guards(self, bar):
        """Debounce, risk-halt and post-trade cooldown gates.

        Delegates to the DecisionLoop. Retained as a thin wrapper so that
        direct callers (tests, exposure-state checks) continue to work.

        Returns ``(blocked, cooldown_remaining_sec)``.
        """
        return self._decision_loop._entry_guards(bar)

    def _build_context(self, bar, amt_dto: dict, cooldown_remaining_sec: float):
        """Thin delegate to the single construction owner
        (``build_engine_context``) shared with DecisionLoop and ExitManager."""
        return build_engine_context(self, bar, amt_dto, cooldown_remaining_sec)

    def _check_thesis_flip(self, amt_dto: dict, bar) -> None:
        """Opposing-signal exit (thesis invalidation).

        Delegates to the ExitManager. Retained as a thin wrapper so that
        direct callers continue to work.
        """
        self._exit_manager.check_thesis_flip(amt_dto, bar)

    # =========================================================================
    # 5. RISK — session risk, portfolio risk, halt logic
    # =========================================================================
    def _book_full_close(self) -> None:
        """Shared post-full-close bookkeeping — the ONLY full-close release path.

        Delegates to the ExitManager. Retained as a thin wrapper so that
        direct callers continue to work.
        """
        self._exit_manager._book_full_close()

    def _get_position_manager(self) -> PositionManager:
        """Lazily create the PositionManager with the correct emit function."""
        if not hasattr(self, '_pos_mgr') or self._pos_mgr is None:
            self._pos_mgr = PositionManager(
                oms=self._oms,
                exits=self._exits,
                risk=self._risk,
                emit_fn=self._emit,
                symbol=self.symbol,
                market=self._market,
                contract_expiry=self._contract_expiry,
                tick_size=self._tick_size,
                get_depth=lambda: self._last_depth,
                get_amt_dto=lambda: self._amt_engine.last_amt_dto,
                get_snapshot=lambda: self._amt_engine.last_snapshot,
                portfolio_risk=self._portfolio_risk,  # E11: pyramid add-ons reserve aggregate risk
            )
        return self._pos_mgr

    def force_close_position(self, reason: str) -> bool:
        """Time-driven full close of the base position AND pyramid add-ons.

        Delegates to the ExitManager. Retained as a thin wrapper so that
        direct callers (coordinator EOD watchdog) continue to work.
        """
        return self._exit_manager.execute_full_close(reason)

    def _fresh_forecast(self):
        """Return the cached TimesFM forecast unless it is stale (>1 bar old).

        Forecasts stamped with ``asof_bar < 0`` predate freshness tracking
        and pass through unchanged. Stale forecasts never reach exits or
        sizing — callers get None and fall back to deterministic behavior.
        """
        from quant.decision.timesfm_forecast_factory import fresh_forecast
        tfm_fc = fresh_forecast(
            getattr(self, "_advisor", None),
            getattr(self, "_strategy", None),
            symbol=self.symbol,
            bar_index=self._bar_index,
        )
        asof = getattr(tfm_fc, "asof_bar", -1)
        try:
            asof = int(asof)
        except (TypeError, ValueError):
            asof = -1
        if tfm_fc is not None and asof >= 0:
            age = self._bar_index - asof
            if age > 1:
                logger.warning(
                    "⚠️ [STALE FORECAST] %s: cached forecast %d bars old — deterministic exits",
                    self.symbol, age,
                )
                return None
        return tfm_fc

    def _manage_exit(self, amt_dto: dict, bar) -> None:
        """Bar-driven exit evaluation.

        Delegates to the ExitManager. Retained as a thin wrapper so that
        direct callers (TickHandler) continue to work.
        """
        self._exit_manager.manage_exit(amt_dto, bar)

    # =========================================================================
    # 6. EVENTS — emission, event store, reconciliation
    # =========================================================================
    def _emit(self, event: Event) -> None:
        """Publish to the bus, append to the trace, fold into the projector.

        Journal (JSONL) persistence is handled by a low-priority bus
        subscriber (set up in __init__) so JSON serialization stays off the
        hot path; the journal is write-only durability audit.

        Guarded by a lock so concurrent emitters (depth updates) never race
        the engine thread's own emits.

        Event sourcing: every emitted event is appended to the EventStore
        (the source of truth) and folded into the cached EngineState.
        Lifecycle events (PositionOpened/Reduced/Closed) and StopMoved are
        append-before-publish: bus/journal subscribers only see them after a
        durable append. Other telemetry/market events publish first.

        Timestamp contract: the EventStore rejects empty event times (audit
        integrity), so an event constructed without a time inherits the last
        bar's time, falling back to the current IST wall-clock for a flat
        store. This catches synthetic DTOs (e.g. the seeded AmtUpdated whose
        payload has no "time" key) without crashing the engine thread.
        """
        if not event.time:
            from dataclasses import replace as _dc_replace
            from datetime import datetime as _dt
            from quant.contracts.timezones import IST as _IST

            fallback = getattr(self.state, "last_bar", None)
            fallback_time = getattr(fallback, "time", None) or ""
            if not fallback_time:
                fallback_time = _dt.now(tz=_IST).isoformat()
            event = _dc_replace(event, time=fallback_time)
        with self._emit_lock:
            if isinstance(event, AgentDecisionProduced) and isinstance(event.decision, dict):
                dec = event.decision
                entry = {
                    "time": event.time,
                    "action": dec.get("action", "FLAT"),
                    "direction": dec.get("direction", "FLAT"),
                    "setup": dec.get("setup", "NO_EDGE"),
                    "confidence": dec.get("confidence", "Medium"),
                    "rationale": dec.get("rationale", ""),
                }
                if not self._recent_decisions or self._recent_decisions[-1].get("time") != event.time:
                    self._recent_decisions.append(entry)
                else:
                    self._recent_decisions[-1] = entry
            lifecycle_event = isinstance(event, (PositionOpened, PositionReduced, PositionClosed))
            # StopMoved is durable-gated like lifecycle events: append first,
            # publish only after a durable append (stop-move audit must not
            # precede the store). Other telemetry/market events stay
            # publish-before-append for low-latency observability.
            durable_gated = lifecycle_event or isinstance(event, StopMoved)
            if not durable_gated:
                self._bus.publish(event)
                self._trace.append(event)
            # Track latest event-derived values for the WS snapshot
            if isinstance(event, AmtUpdated):
                self._latest_amt = event.amt
            elif isinstance(event, DecisionProduced):
                self._latest_quant_decision = _decision_to_view(event.decision)
            elif isinstance(event, AgentDecisionProduced):
                self._latest_agent_decision = event.decision
            elif isinstance(event, DepthUpdated):
                self._latest_depth = event.depth
            # Event sourcing: append to EventStore and fold into state.
            # Contained: a sourcing failure (disk I/O, corrupt payload, clock
            # skew) must never kill the caller mid-bookkeeping. Eager-publish
            # events already reached the bus/journal; durable-gated events
            # (lifecycle, StopMoved) are held back until append succeeds.
            append_sequence = self.event_appender.append(event)
            append_failed = append_sequence is None
            if append_failed:
                exc = self.persistence_health.failure
                if exc is None:
                    exc = RuntimeError("event append failed without an error")
                if lifecycle_event or self._is_paper_runtime:
                    self.persistence_degraded = True
                    self.reconciliation_required = True
                    self.persistence_failure = exc
                if lifecycle_event and self._is_paper_runtime:
                    from quant.execution.exposure import ExposureStatus, ExposureState
                    if self.exposure_state.status is ExposureStatus.NONE:
                        self.exposure_state = ExposureState(
                            status=ExposureStatus.RECONCILIATION_REQUIRED,
                            symbol=self.symbol,
                            order_id=f"event-store:{type(event).__name__}",
                        )
                logger.critical(
                    "⚠️ [EVENT SOURCING] %s: append failed for %s — event NOT "
                    "recorded in the store; state may drift (reconciliation "
                    "re-syncs on startup)",
                    self.symbol, type(event).__name__,
                )
            if not append_failed or not durable_gated:
                # Lifecycle/StopMoved state is canonical only after durable
                # append. Other telemetry/market events may still update the
                # operational cache.
                self.state = apply_event(self.state, event)
            if lifecycle_event:
                # Always adopt the execution-book cache from the lifecycle
                # event. On a durable append this is the post-append book
                # adopt; on append failure the OMS fill still happened and
                # must not be orphaned (reconciliation_required is already
                # latched above).
                self._adopt_position_cache_from_journal(event)
            if durable_gated and not append_failed:
                self._bus.publish(event)
                self._trace.append(event)
            if lifecycle_event and not append_failed:
                self.persist_kernel_state()

    def _adopt_position_cache_from_journal(self, event: Event) -> None:
        """Rebuild ``pm.current_position`` from the lifecycle store event.

        OMS fill paths emit PositionOpened/Reduced/Closed; this is the only
        writer that adopts the execution-book cache from those events so the
        fold and the book stay aligned after every durable append.
        """
        pm = self._get_position_manager()
        if isinstance(event, PositionOpened):
            pos = event.position
            # Pyramid add-ons live on pm.pyramid_positions; do not clobber base.
            if int(getattr(pos, "pyramid_level", 0) or 0) > 0:
                return
            pm.current_position = pos
        elif isinstance(event, PositionReduced):
            pm.current_position = event.remaining
        elif isinstance(event, PositionClosed):
            closed = getattr(event.fill, "position", None)
            if closed is not None and int(getattr(closed, "pyramid_level", 0) or 0) > 0:
                return
            pm.current_position = None

    def _underlying(self) -> str:
        from quant.contracts.exchange_config import ExchangeConfig
        underlying = ExchangeConfig.for_exchange(self._market).extract_underlying(self.symbol)
        if not underlying:
            raise ValueError(
                f"Cannot resolve underlying for instrument {self.symbol!r} "
                f"on market {self._market!r}"
            )
        return underlying

    def startup_reconcile(self) -> None:
        """Rebuild state from the EventStore after a process restart.

        Cross-restart position rebuild is SQLite-row first: the coordinator
        loads open-position rows and calls ``restore_position()`` (baseline
        ``PositionOpened`` seed). This method then verifies the checksum
        chain and folds the EventStore; if the fold is empty but the
        execution book holds a restored position, the book wins. The JSONL
        journal is write-only durability audit and is NOT replayed here.
        """
        # Verify checksum chain integrity (tamper detection)
        if not self.event_store.verify_chain():
            logger.critical(
                "STARTUP RECONCILE %s: event store checksum chain broken — "
                "possible tampering or corruption",
                self.symbol,
            )
        rebuilt = self.event_store.fold()
        position = rebuilt.position
        pm = self._get_position_manager()
        if position is None and pm.current_position is not None:
            # Restored-book baseline (process restart): restore_position()
            # seeds the EventStore with a baseline PositionOpened event, so
            # the fold normally yields a position. This branch fires only
            # when the fold still yields no position (e.g., EventStore pruned,
            # seed event absent, or the store is genuinely empty). Adopting
            # the PositionManager's book keeps the run-loop position gates
            # (tick/bar exits, entry blocking) consistent with execution.
            position = _position_to_state(pm.current_position)
            logger.info(
                "startup_reconcile %s: event store fold yielded no position "
                "— adopting restored position %s from execution book",
                self.symbol, position.id,
            )
        elif position is not None and pm.current_position is None:
            logger.warning(
                "startup_reconcile %s: event store holds position %s but the "
                "execution book is flat — store wins for state; investigate",
                self.symbol, position.id,
            )
        self.state = EngineState(
            symbol=self.symbol,
            sequence=rebuilt.sequence,
            last_bar=rebuilt.last_bar,
            position=position,
            pyramids=rebuilt.pyramids,
            risk=rebuilt.risk,
            last_close_bar=rebuilt.last_close_bar,
        )

    def reconcile_paper_fills(self, simulator) -> None:
        """Restore unresolved paper fills into the entry safety state."""
        unresolved = simulator.unresolved_fills
        if not unresolved:
            return
        fill = unresolved[0]
        if self.exposure_state.status.name != "NONE":
            return
        from quant.execution.exposure import ExposureState
        self.exposure_state = ExposureState.none().partial_entry(
            symbol=self.symbol,
            order_id=fill.order_id,
            requested_qty=fill.requested_quantity,
            filled_qty=fill.filled_quantity,
            fill_price=fill.fill_price,
        )

    def restore_unresolved_order(self, row: dict) -> None:
        """Restore an inflight broker order before the decision loop runs."""
        from quant.execution.exposure import ExposureState

        if self.exposure_state.status.name != "NONE":
            return
        self.exposure_state = ExposureState.none().unknown_entry(
            symbol=str(row.get("symbol") or self.symbol),
            order_id=str(row.get("broker_order_id") or row.get("order_id") or "unknown-order"),
            requested_qty=float(row.get("quantity") or 0.0),
            filled_qty=float(row.get("filled_quantity") or 0.0),
            fill_price=float(row.get("avg_fill_price") or 0.0),
        )

    def reconcile_unresolved_order(self, snapshot) -> None:
        """Apply one broker snapshot without clearing an unavailable outcome."""
        self.exposure_state = self.exposure_state.reconcile(snapshot)

    def periodic_reconcile(self) -> PeriodicReconciliationResult:
        """Periodic reconciliation between cached state and event store.

        Compares the in-memory EngineState against a fresh fold of the
        EventStore. Detects drift (e.g., state desync, risk halt mismatch)
        and emits a RiskUpdated event when a discrepancy is found.

        Returns:
            PeriodicReconciliationResult with drift details.
        """
        canonical = self.event_store.fold()
        discrepancies: list[str] = []
        risk_event_emitted = False

        # Position drift vs the event store (cached-state desync)
        if canonical.position != self.state.position:
            discrepancies.append(
                f"position drift: state={self.state.position} vs store={canonical.position}"
            )

        # Execution-truth drift: the PositionManager book is the execution
        # authority (it owns partial-fill adoption and pyramid state). The
        # cached state must agree with it — a divergence means an entry/exit
        # mutated the book without an event, or an event desynced from the
        # book (the pre-fold PositionReduced staleness lived exactly here:
        # fold AND cached state both kept the full size while the book held
        # the reduced runner, so neither side of the old check saw it).
        pm = self._get_position_manager()
        pm_pos = pm.current_position
        st_pos = self.state.position
        pm_size = float(getattr(pm_pos, "size", 0.0) or 0.0) if pm_pos is not None else 0.0
        st_size = float(st_pos.size) if st_pos is not None else 0.0
        if (pm_pos is None) != (st_pos is None) or abs(pm_size - st_size) > 1e-9:
            discrepancies.append(
                f"position drift: position_manager_size={pm_size} "
                f"vs state_size={st_size}"
            )
        pm_pyramid_ids = {
            str(getattr(p, "_id", None) or getattr(p, "id", ""))
            for p in (pm.pyramid_positions or [])
        }
        st_pyramid_ids = {str(p.id) for p in self.state.pyramids}
        if pm_pyramid_ids != st_pyramid_ids:
            discrepancies.append(
                f"pyramid drift: position_manager={sorted(pm_pyramid_ids)} "
                f"vs state={sorted(st_pyramid_ids)}"
            )

        # Risk drift (e.g., halt state mismatch)
        if canonical.risk != self.state.risk:
            discrepancies.append(
                f"risk drift: state_halted={self.state.risk.halted} "
                f"vs store_halted={canonical.risk.halted}"
            )
            # Emit RiskUpdated so downstream consumers see the correction.
            # Convert state_machine.RiskState -> execution.risk.RiskState
            # (the projector expects consecutive_losses/equity/cushion_tier).
            from quant.execution import risk as _risk_mod
            exec_risk = _risk_mod.RiskState(
                daily_pnl=canonical.risk.daily_pnl,
                trades_today=canonical.risk.trades_today,
                halted=canonical.risk.halted,
                halt_reason=canonical.risk.halt_reason,
                consecutive_losses=0,
                risk_per_trade_pct=0.005,
                equity=0.0,
                cushion_tier="CONSERVATIVE",
            )
            # Timestamp the drift-correction event: an empty time would be
            # rejected by the EventStore timestamp validation (audit trail
            # integrity). Prefer the canonical fold's last bar time (market
            # time); fall back to the current IST wall-clock for a flat store.
            from quant.contracts.timezones import IST as _IST
            from datetime import datetime as _dt

            drift_time = (
                getattr(canonical.last_bar, "time", None)
                if canonical.last_bar is not None
                else None
            ) or _dt.now(tz=_IST).isoformat()
            self._emit(RiskUpdated(symbol=self.symbol, time=drift_time, risk=exec_risk))
            risk_event_emitted = True

        return PeriodicReconciliationResult(
            has_drift=bool(discrepancies),
            risk_event_emitted=risk_event_emitted,
            discrepancies=tuple(discrepancies),
        )

    # =========================================================================
    # 7. UTILITIES — depth conversion, quote caching, advisors
    # =========================================================================
    @staticmethod
    def _depth_to_book(depth: dict) -> OrderBook | None:
        if not depth:
            return None
        return OrderBook(
            bids=tuple(
                OrderBookLevel(float(lv["price"]), float(lv["quantity"]))
                for lv in depth.get("bids", [])
            ),
            asks=tuple(
                OrderBookLevel(float(a["price"]), float(a["quantity"]))
                for a in depth.get("asks", [])
            ),
        )
