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
"""

from __future__ import annotations
from quant.contracts.enums import MarketState

import logging
import os
import random
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass

from quant.aggregator import BarAggregator
from quant.amt_engine import AMTEngine
from quant.amt.dto import empty_amt_dto
from quant.amt.session.context import get_session_info
from quant.bars import Bar
from quant.contracts.contracts import ContractRef
from quant.contracts.value_objects import OrderBook, OrderBookLevel
from quant.contracts.vocabulary import is_call_symbol, is_put_symbol
from quant.decision.context import DecisionContext
from quant.decision.decision_service import DecisionService
from quant.decision.signal_builder import clamp_quantity
from quant.decision.context_builder import DecisionContextBuilder
from quant.hotpath import get_hotpath_tracer
from quant.position_manager import PositionManager
from quant.session_gates import (
    bar_epoch_ms as _bar_epoch_ms,
    ist_dt as _ist_dt,
    parse_contract_expiry,
    session_allow_entry,
    session_force_exit,
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
    signal_matches_contract,
    validate_execution_model,
)
from quant.execution.exits import ExitDecision, ExitEngine
from quant.execution.oms import PaperOMS
from quant.execution.ports import IOMS
from quant.execution.risk import SessionRisk
from quant.contracts.timezones import IST
from quant.persistence import Journal
from quant.state import LiveQuoteCache, _decision_to_view, _epoch_to_iso
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

_DETERMINISTIC_CONVICTION = 0.7
# Minimum closed bars (live + seeded history) before the engine may decide.
# The analysis kernel needs enough bars for a meaningful POC/VA/VWAP profile;
# the AMT/decision design pins this at > 15 bars, which also keeps entries
# out of the opening-noise window (15 minutes at the default 1m timeframe).
_WARMUP_BARS = 15


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


def close_lingering_pyramids(pm, price: float, time_str: str, reason: str) -> int:
    """Close pyramid add-ons whose base position is already gone.

    Routes every add-on through ``PositionManager._execute_full_close`` — the
    ONLY full-close release path — so the exit-source stamp, the
    ``[POSITION CLOSED]`` log, the double-close guard and the portfolio-risk
    release all happen exactly as they do for the base position. A previous
    direct OMS close loop here skipped all four.

    Add-ons are closed with ``count_as_trade=False``: a pyramid-only flatten
    is bookkeeping on an already-realized round-trip, so it must not consume
    the session's trade budget (``trades_today``) nor move the win/loss
    streaks the consecutive-loss halt is built on — the same intent the old
    direct-OMS loop encoded. Each add-on is closed inside its own try/except
    so one failure cannot orphan the rest, and risk is released only for
    add-ons that actually produced a fill (the double-close guard returns
    ``None`` and must not be read as a close).

    Returns the number of add-ons actually closed.
    """
    from quant.execution.exits import ExitDecision

    # Detach the add-ons before closing them: _execute_full_close sweeps
    # ``pm.pyramid_positions`` as part of its own pyramid handling, so leaving
    # the list attached would close each add-on twice (once as the primary
    # close, once in that sweep). The sweep does not register add-on ids in
    # ``_closed_ids``, so the second close would slip past the double-close
    # guard and double-count P&L/risk. Detaching keeps exactly one close per
    # add-on, all through the single release path.
    #
    # Detached order is kept so a failed add-on can be restored to the book
    # (see the except branch) — dropping it would silently lose an open
    # position the broker still holds. ``pyramid_count`` is intentionally not
    # zeroed here: the authoritative value is re-derived from the surviving
    # book at the end of the loop, and _execute_full_close already zeroes it
    # per successful close.
    lingering = list(pm.pyramid_positions)
    pm.pyramid_positions = []
    closed = 0
    failed: list[object] = []
    for pyr_pos in lingering:
        # Same id accessor the release path uses (position_manager.py:260) so
        # the two agree on what "id-less" means; an id-less add-on would raise
        # ValueError out of _execute_full_close, which must not escape
        # force_close_position. Skip it loudly instead.
        pos_id = getattr(pyr_pos, "_id", None) or getattr(pyr_pos, "id", None)
        if pos_id is None:
            logger.error(
                "❌ [EOD PYRAMID CLOSE] %s: add-on without an id cannot be closed "
                "through the release path — skipped (type=%s)",
                pm.symbol, type(pyr_pos).__name__,
            )
            failed.append(pyr_pos)
            continue
        try:
            fill = pm._execute_full_close(
                pyr_pos, ExitDecision(True, reason, float(price)), time_str,
                count_as_trade=False,
            )
        except Exception:
            # One bad add-on must not orphan the rest: log and continue.
            logger.error(
                "❌ [EOD PYRAMID CLOSE] %s: add-on %s failed to close — continuing",
                pm.symbol, str(pos_id)[:8], exc_info=True,
            )
            failed.append(pyr_pos)
            continue
        if fill is None:
            # Double-close guard refused this add-on: nothing executed at the
            # broker, so we cannot prove it is flat. Treat it as a FAILED close
            # (D-15): keep it in the book so the next EOD/force-close pass
            # retries it instead of silently orphaning a possibly-live position.
            logger.error(
                "❌ [EOD PYRAMID CLOSE] %s: add-on %s refused by the close guard "
                "— it may still be open at the broker; retrying next pass",
                pm.symbol, str(pos_id)[:8],
            )
            failed.append(pyr_pos)
            continue
        closed += 1
        # Because we detached the add-on, _execute_full_close's own E11 sweep
        # did not see it — release its reserved aggregate risk here so the
        # portfolio ceiling is not leaked, exactly as the base close does.
        risk_i = pm._pyramid_open_risk.pop(pos_id, 0.0)
        portfolio_risk = getattr(pm, "_portfolio_risk", None)
        if portfolio_risk is not None:
            portfolio_risk.record_close(risk_i, float(fill.pnl))
    # Leave the bookkeeping consistent: only add-ons that genuinely closed are
    # gone. A failed one stays in the book so the next force-close/EOD pass
    # retries it rather than silently dropping a live position.
    pm.pyramid_positions = failed
    pm.pyramid_count = len(failed)
    return closed


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
    ) -> None:
        self._gateway = gateway
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
        self.symbol = symbol
        self._tick_size = tick_size
        self._max_lots = max_lots
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
        # ponytail: 60s micro aggregator drives 1-min entry triggers while 5-min aggregator retains macro AMT context
        MICRO_SEC = 60
        self._micro_aggregator = (
            BarAggregator(interval_seconds=MICRO_SEC)
            if interval_seconds > MICRO_SEC
            else None
        )
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
        self._exits = ExitEngine(time_stop_bars=time_stop_bars, cvd_kill_threshold=2.0)
        # Strategy — pluggable entry/exit logic. Defaults to the AMT scalping
        # playbook (Fabio Valentini) or TimesFM autonomous management.
        if strategy is not None:
            self._strategy = strategy
        else:
            use_timesfm_e2e = os.getenv("TIMESFM_END_TO_END", "").strip().lower() in ("1", "true", "yes")
            if use_timesfm_e2e:
                from quant.strategies.timesfm_strategy import TimesFMTradingStrategy
                logger.info("Initializing QuantEngine with TimesFMTradingStrategy (End-to-End Autonomous Management)")
                tfm_native = getattr(advisor, "_native_engine", None) if advisor else None
                self._strategy = TimesFMTradingStrategy(engine=tfm_native)
            else:
                from quant.strategies.amt_scalping import AmtScalpingStrategy
                self._strategy = AmtScalpingStrategy(
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

            def _journal_subscriber(event: Event) -> None:
                self._journal.append(
                    {"type": event.__class__.__name__, **asdict(event)}
                )

            for evt_type in (BarClosed, DecisionProduced,
                             SignalApproved, SignalBlocked,
                             PositionOpened, PositionClosed,
                             PositionReduced,
                             RiskUpdated, DepthUpdated, AmtUpdated,
                             OrderSubmitted, OrderFilled, StopMoved):
                self._bus.subscribe(evt_type, _journal_subscriber,
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

    def attach_journal(self, path: str | None = None) -> None:
        """Attach the fsync JSONL event journal and subscribe it to the bus.

        Called by the coordinator after construction so journals land in a
        per-day directory. Subscribes lazily so late attachment (post
        constructor, pre-run) still captures every event.
        """
        from quant.persistence import Journal

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

        def _journal_subscriber(event: Event) -> None:
            self._journal.append(
                {"type": event.__class__.__name__, **asdict(event)}
            )

        for evt_type in (BarClosed, DecisionProduced,
                        SignalApproved, SignalBlocked,
                        PositionOpened, PositionClosed,
                        PositionReduced,
                        RiskUpdated, DepthUpdated, AmtUpdated,
                        OrderSubmitted, OrderFilled, StopMoved):
            self._bus.subscribe(evt_type, _journal_subscriber, priority=-100)

    def attach_storage(self, storage) -> None:
        """Project PositionOpened/Closed onto IStorage (restart book)."""
        from quant.persistence_bridge import PositionStorageBridge
        PositionStorageBridge(storage, contract=self._contract).attach(self._bus)
        self._storage = storage
        try:
            from quant.amt.session.context import load_prior_profile
            prior = load_prior_profile(storage, self.symbol)
            if prior and prior.get("poc"):
                if hasattr(self, "_amt_engine") and hasattr(self._amt_engine, "set_prior_profile"):
                    self._amt_engine.set_prior_profile(
                        poc=prior["poc"], vah=prior.get("vah", 0.0), val=prior.get("val", 0.0)
                    )
        except Exception:
            logger.exception("Failed to load prior profile from storage for %s", self.symbol)

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

    def restore_position(self, position) -> None:
        """Rehydrate the in-memory book after a process restart."""
        pm = self._get_position_manager()
        pm.current_position = position
        self.state = self.state.with_position(_position_to_state(position))
        self._entry_bar_index = self._bar_index
        self._entry_time_epoch = 0.0
        # Seed EventStore with baseline PositionOpened so event sourcing
        # and subsequent fold()/PositionClosed remain consistent.
        from quant.events import PositionOpened
        ts = getattr(position, "open_time", None) or getattr(position, "entry_time", None) or "0"
        self.event_store.append(
            PositionOpened(symbol=self.symbol, time=str(ts), position=position)
        )
        if self._portfolio_risk is not None:
            self._portfolio_risk.register_open(0.0, symbol=self.symbol)

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
        except Exception:  # silent-except - certification record append must never break trading
            pass  # certification must never break trading

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

        initial_amt = self._option_amt_dto or self._amt_engine.last_amt_dto
        if initial_amt and hasattr(self, "_advisor") and self._advisor is not None:
            ctx = DecisionContextBuilder().build(
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
            )
            self._advisor.on_context(ctx)

        steps = 0
        while True:
            if max_steps is not None and steps >= max_steps:
                break
            tick = self._gateway.next_tick()
            if tick is None:
                break
            steps += 1
            self._last_tick_wall = time.time()
            if _HOTPATH.enabled:
                _HOTPATH.try_emit(
                    self.symbol, "tick",
                    time=str(tick.time), price=float(tick.price), source="option",
                )
            # 0. Tick-level fast SL/TP protection (Fabio: exit immediately on stop breach, never wait 5m)
            if self.state.position is not None:
                self._manage_tick_exit(float(tick.price), str(tick.time))

            # When an underlying feed is present, option ticks aggregate into option candles,
            # while underlying futures ticks feed the AMT auction structure engine.
            if self._underlying_gateway is not None:
                # 1. Micro-trigger: option's own ticks feed 1-min micro aggregator for fast entry decisions
                if self._micro_aggregator is not None:
                    micro_bar = self._micro_aggregator.add_tick(tick)
                    if micro_bar is not None and self.state.position is None:
                        if self._underlying_amt_dto and self._last_underlying_bar is not None:
                            self._decide(
                                self._underlying_amt_dto,
                                self._last_underlying_bar,
                                execution_bar=micro_bar,
                            )

                # Option's OWN ticks feed the option's 5m aggregator to form real option candles
                option_bar = self._aggregator.add_tick(tick)
                if self._option_amt_engine is not None:
                    self._option_amt_engine.on_tick(tick, self._aggregator.current_bar)
                if option_bar is not None:
                    self._bar_index += 1
                    self._emit(BarClosed(symbol=self.symbol, time=option_bar.time, bar=option_bar))
                    if self._option_amt_engine is not None:
                        self._option_amt_dto = self._option_amt_engine.analyze(option_bar)
                        self._emit_merged_amt(self._option_amt_dto, option_bar.time)
                        if self.state.position is not None:
                            self._manage_exit(self._option_amt_dto, option_bar)
                        elif self._micro_aggregator is None:
                            if self._underlying_amt_dto and self._last_underlying_bar is not None:
                                self._decide(
                                    self._underlying_amt_dto,
                                    self._last_underlying_bar,
                                    execution_bar=option_bar,
                                )

                # 2. Underlying futures ticks feed the underlying aggregator and AMT engine.
                if self._underlying_aggregator is not None:
                    utick = self._underlying_gateway.try_next_tick()
                    while utick is not None:
                        if _HOTPATH.enabled:
                            _HOTPATH.try_emit(
                                self.symbol, "tick",
                                time=str(utick.time), price=float(utick.price),
                                source="underlying",
                            )
                        if self._micro_underlying_aggregator is not None:
                            micro_ubar = self._micro_underlying_aggregator.add_tick(utick)
                            if micro_ubar is not None:
                                self._last_underlying_bar = micro_ubar
                        ubar = self._underlying_aggregator.add_tick(utick)
                        self._amt_engine.on_tick(utick, self._underlying_aggregator.current_bar)
                        if ubar is not None:
                            self._last_underlying_bar = ubar
                            self._underlying_amt_dto = self._amt_engine.analyze(ubar)
                            self._emit_merged_amt(self._underlying_amt_dto, ubar.time)
                        utick = self._underlying_gateway.try_next_tick()
            else:
                # Direct instrument / Futures: micro-trigger evaluation
                if self._micro_aggregator is not None:
                    micro_bar = self._micro_aggregator.add_tick(tick)
                    if micro_bar is not None and self.state.position is None:
                        amt_dto = self._amt_engine.last_amt_dto
                        if amt_dto:
                            self._decide(amt_dto, micro_bar)

                bar = self._aggregator.add_tick(tick)
                self._amt_engine.on_tick(tick, self._aggregator.current_bar)
                if bar is not None:
                    self._on_bar_closed(bar)

            # Per-tick live LTP/OI/depth and real-time forming live candle —
            # the option's own forming candle is self._aggregator.current_bar
            self._live.on_quote(
                self.symbol, tick, current_bar=self._aggregator.current_bar
            )
            if tick.depth is not None:
                self._last_depth = self._depth_to_book(tick.depth)
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
        """Fractional portfolio-risk reserve release after a tiered partial
        exit — shared by the bar (_manage_exit) and tick (_manage_tick_exit)
        paths so both book the same fraction of reserved open risk."""
        if self._portfolio_risk is None:
            return
        if pm.last_partial_fill is not None:
            closed_sz = abs(pm.last_partial_fill.position.size)
            remaining_sz = abs(remaining.size) if remaining is not None else 0.0
            total_sz = closed_sz + remaining_sz
            fraction = closed_sz / total_sz if total_sz > 0 else 0.0
            release = getattr(self, "_open_trade_risk", 0.0) * fraction
            self._portfolio_risk.record_close(release, float(pm.last_partial_fill.pnl))
            self._open_trade_risk = getattr(self, "_open_trade_risk", 0.0) - release
        # Pyramid add-on PnL is NOT booked here: _execute_full_close's E11
        # loop already pairs every add-on with its OWN fill pnl and risk_i —
        # re-releasing the aggregate last_pyramid_pnl would double-book it.

    def _manage_tick_exit(self, tick_price: float, tick_time: str) -> None:
        """Tick-level fast stop-loss and take-profit breach check (Fabio)."""
        with self._close_lock:
            pm = self._get_position_manager()
            if pm.current_position is None:
                return
            # manage_tick_exit does NOT reset these per call (unlike manage_exit);
            # clear them so stale values from an earlier tick/bar can't trigger
            # duplicate reserve releases below.
            pm.last_partial_fill = None
            pm.last_pyramid_pnl = 0.0
            # Adopt the survivor: a tick-path partial returns a NEW Position with
            # the reduced size — keeping the pre-partial object as the current
            # position would re-book the ORIGINAL size at the eventual full close.
            try:
                remaining = pm.manage_tick_exit(pm.current_position, tick_price, tick_time)
            except Exception:
                # C3: a broker/OMS failure while exiting must not kill the engine
                # thread. Keep the position open so the exit is retried on the
                # next tick/bar; the failure is loud so ops can intervene.
                logger.exception(
                    "❌ [EXIT FAILED] %s: tick-exit OMS call raised — position kept "
                    "open, will retry next tick (engine stays alive)",
                    self.symbol,
                )
                return
            pm.current_position = remaining
            self._release_partial_reserves(pm, remaining)
            if remaining is None:
                if self.state.position is not None:
                    self.state = self.state.with_position(None)
                self._book_full_close()

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
    # =========================================================================
    def _decide(self, amt_dto: dict, bar, execution_bar=None) -> None:
        blocked, cooldown_remaining_sec = self._entry_guards(bar)
        if blocked:
            return

        decision, ctx, amt_dto, risk_st = self._build_decision(
            amt_dto, bar, execution_bar, cooldown_remaining_sec,
)

        # S1: record the decision itself — gates with pass/fail and reasons.
        try:
            self.cert_records.append({
                "symbol": self.symbol, "time": bar.time,
                "stage": "decision",
                "approved": decision.approved, "reason": decision.reason,
                "block_reasons": list(decision.block_reasons or ()),
                "gate_results": [
                    {"gate": g.gate if hasattr(g, 'gate') else getattr(g, 'name', '?'),
                     "passed": bool(getattr(g, 'passed', False))}
                    for g in (decision.gate_results or ())
                ],
                "signal": {
                    "type": decision.signal.type,
                    "entry": float(decision.signal.entry),
                    "sl": float(decision.signal.sl),
                    "tp": float(decision.signal.tp),
                    "rr": float(decision.signal.rr),
                } if decision.signal else None,
                "position_size": None,
            })
        except Exception:  # silent-except - certification decision record must never break trading
            pass
        self._emit(DecisionProduced(symbol=self.symbol, time=bar.time, decision=decision))
        if hasattr(self, "_advisor") and self._advisor is not None:
            if self._option_amt_dto is not None and execution_bar is not None:
                advisor_ctx = DecisionContextBuilder().build(
                    bar=execution_bar,
                    symbol=self.symbol,
                    market=self._market,
                    contract_expiry=self._contract_expiry,
                    tick_size=self._tick_size,
                    bar_index=self._bar_index,
                    warm_bars=self._option_amt_engine.warm_bars if self._option_amt_engine else self._amt_engine.warm_bars,
                    cooldown_remaining_sec=cooldown_remaining_sec,
                    risk_state=risk_st,
                    amt_dto=self._option_amt_dto,
                    order_book=self._last_depth,
                    position=self.state.position,
                    entry_bar_index=self._entry_bar_index,
                    recent_decisions=list(self._recent_decisions),
                )
                self._advisor.on_context(advisor_ctx)
            else:
                self._advisor.on_context(ctx)

        if decision.approved and decision.signal is not None:
            self._translate_and_submit(decision, bar, amt_dto, risk_st)
        else:
            # Market state changed — all open blocking episodes are stale.
            self._latch.clear()
            if decision.reason == "OPPOSING_TYPE":
                logger.debug(
                    "⚪ [DECISION EVAL] %s: approved=False reason=OPPOSING_TYPE phase=%s",
                    self.symbol,
                    decision.phase,
                )
            else:
                logger.info(
                    "⚪ [DECISION EVAL] %s: approved=False reason=%s phase=%s blocked=%s",
                    self.symbol,
                    decision.reason,
                    decision.phase,
                    decision.block_reasons,
                )

    def _entry_guards(self, bar):
        """Debounce, risk-halt and post-trade cooldown gates.

        Returns ``(blocked, cooldown_remaining_sec)``; the halt and cooldown
        branches emit their DecisionProduced, the debounce branch emits nothing.
        """
        # Broker may hold partial exposure after a timeout/cancel race. Until
        # reconciled, this engine must stay flat and reject new entries.
        exposure = getattr(self, "exposure_state", None)
        if exposure is not None and not exposure.can_open_new_position:
            logger.error(
                "[BLOCKED] %s: broker exposure requires reconciliation (%s)",
                self.symbol, exposure.status,
            )
            return True, 0.0
        # ponytail: debounce repeated rejected entries to avoid 60-second log flood
        if (self._bar_index - getattr(self, "_last_rejected_bar_index", -999)) < 2:
            return True, 0.0
        # --- Guard 0: trade-count / risk halt check BEFORE building any context ---
        can_trade, no_trade_reason = self._risk.can_trade()
        if not can_trade:
            logger.info(
                "🚫 [BLOCKED] %s: %s (trades_today=%d)",
                self.symbol, no_trade_reason, self._risk.state().trades_today,
            )
            # Defect 2 fix: emit an explicit HALTED DecisionProduced so the
            # WS snapshot clears any stale approved/ENTER state that was
            # carried over from before the halt was triggered.
            from quant.decision.decision_service import QuantDecision
            halted_decision = QuantDecision(
                approved=False,
                signal=None,
                reason="HALTED",
                phase="",
                gate_results=(),
                block_reasons=(f"Risk: {no_trade_reason}",),
                model_label="",
            )
            self._emit(DecisionProduced(symbol=self.symbol, time=bar.time, decision=halted_decision))
            return True, 0.0
        # --- Guard 1: post-trade cooldown (bars since last close) ---
        bars_since_close = (
            self._bar_index - self._last_close_bar_index
            if self._last_close_bar_index >= 0
            else self._cooldown_bars  # no trade yet → no cooldown
        )
        cooldown_bars_remaining = max(0, self._cooldown_bars - bars_since_close)
        # Convert bars to seconds for the DecisionContext contract
        cooldown_remaining_sec = cooldown_bars_remaining * int(
            getattr(self._aggregator, "interval_seconds", DEFAULT_INTERVAL_SEC) or DEFAULT_INTERVAL_SEC
        )
        if cooldown_bars_remaining > 0:
            logger.debug(
                "⏳ [COOLDOWN] %s: %d bars remaining before next entry",
                self.symbol, cooldown_bars_remaining,
            )
            from quant.decision.decision_service import QuantDecision
            cooldown_decision = QuantDecision(
                approved=False,
                signal=None,
                reason="COOLDOWN",
                phase="",
                gate_results=(),
                block_reasons=(f"Cooldown: {cooldown_bars_remaining} bars remaining",),
                model_label="",
            )
            self._emit(DecisionProduced(symbol=self.symbol, time=bar.time, decision=cooldown_decision))
            return True, cooldown_remaining_sec
        return False, cooldown_remaining_sec

    def _build_decision(self, amt_dto, bar, execution_bar, cooldown_remaining_sec):
        """Build the DecisionContext, ask the strategy, translate to the option leg.

        Returns ``(decision, ctx, amt_dto, risk_st)``.
        """
        # Event purity (F5): the decision uses the DTO that arrived WITH this
        # bar — re-reading mutable last_amt_dto here could pick up evidence
        # from a LATER bar's analyze() on a multi-threaded consumer.
        amt_dto = amt_dto or self._amt_engine.last_amt_dto or {}
        risk_st = self._risk.state()
        self._cert_trace(
            bar=bar,
            stage="context",
            market_data={
                "open": float(bar.open), "high": float(bar.high),
                "low": float(bar.low), "close": float(bar.close),
                "volume": float(bar.volume),
            },
            profile_data={
                "poc": amt_dto.get("poc"), "vah": amt_dto.get("valueAreaHigh"),
                "val": amt_dto.get("valueAreaLow"),
                "lvns": amt_dto.get("lvns") or [],
                "hvns": amt_dto.get("hvns") or [],
                "leg_lvn": amt_dto.get("legLvn"),
            },
            context={
                "market_state": amt_dto.get("marketState"),
                "profile_shape": amt_dto.get("profileShape"),
                "session_phase": getattr(self, "_last_session_phase", ""),
                "balance_ratio": amt_dto.get("balanceRatio"),
            },
        )
        ctx = self._build_context(bar, amt_dto, cooldown_remaining_sec)
        decision = self._strategy.should_enter(ctx)
        # If running on an option contract with underlying futures feed, translate signal to option premium
        if decision.approved and decision.signal is not None and self._underlying_gateway is not None:
            from quant.amt.session.selector import OptionSelector
            from dataclasses import replace as _dc_replace
            exec_bar = execution_bar or self._aggregator.current_bar or bar
            opt_ltp = float(exec_bar.close) if exec_bar and exec_bar.close > 0 else 0.0
            if opt_ltp > 0:
                delta = getattr(ctx, "option_delta", None)
                selector = OptionSelector()
                opt_signal = selector.translate_underlying_signal_to_option(
                    signal=decision.signal,
                    option_symbol=self.symbol,
                    option_ltp=opt_ltp,
                    delta=delta,
                    tick_size=self._tick_size,
                )
                if opt_signal is None:
                    decision = _dc_replace(
                        decision,
                        approved=False,
                        signal=None,
                        reason="OPPOSING_TYPE",
                        block_reasons=("Signal direction opposes option contract type (Call vs Put)",),
                    )
                else:
                    decision = _dc_replace(decision, signal=opt_signal)
        return decision, ctx, amt_dto, risk_st

    def _apply_risk_ceilings(self, signal, bar, quantity) -> bool:
        """Cross-engine portfolio ceiling check + reservation.

        Returns True when the trade may proceed; on refusal it latches a
        SignalBlocked and returns False.
        """
        # Portfolio-level ceiling: aggregate open risk across ALL engines.
        # Per-engine SessionRisk stays authoritative for its own halts;
        # this is the cross-engine backstop (8 engines x 0.5% each would
        # otherwise risk 4% of capital simultaneously).
        if self._portfolio_risk is not None:
            trade_risk = abs(float(signal.entry) - float(signal.sl)) * max(1.0, quantity)
            ok, why = self._portfolio_risk.can_accept(trade_risk, symbol=self.symbol)
            if not ok:
                self._latch_or_signal_block(signal, why, bar.time)
                self._last_rejected_bar_index = self._bar_index
                return
            if not self._portfolio_risk.register_open(trade_risk, symbol=self.symbol):
                self._latch_or_signal_block(
                    signal, "portfolio cap breached between can_accept and register", bar.time,
                )
                self._last_rejected_bar_index = self._bar_index
                return
            self._open_trade_risk = trade_risk

        return True

    def _translate_and_submit(self, decision, bar, amt_dto, risk_st) -> None:
        """Size, ceiling-check and submit an approved signal, then emit fills."""
        signal = decision.signal
        if (
            self._execution_model is ExecutionModel.INDEPENDENT
            and self._contract is not None
            and not signal_matches_contract(getattr(signal, "symbol", None), self.symbol)
        ):
            logger.warning(
                "[INDEPENDENT_CONTRACT_GUARD] %s: rejected signal for %s",
                self.symbol,
                getattr(signal, "symbol", None),
            )
            self._latch_or_signal_block(
                signal,
                "independent execution requires signal and engine contract to match",
                bar.time,
            )
            return
        # ponytail: underlying observer engines stream charts/data but must not submit orders
        if not getattr(self, "_execution_enabled", True):
            logger.debug(
                "⏭️ [EXECUTION_DISABLED] %s: approved signal not submitted (underlying observer engine)",
                self.symbol,
            )
            return
        # Mirror position_manager's is_expiry source of truth (the traded
        # contract expires today) so entry sizing halves risk on expiry day.
        _ist = _ist_dt(bar.time)
        self._contract_is_expiry = bool(
            self._contract_expiry is not None
            and _ist is not None and _ist.date() == self._contract_expiry
        )
        # If strategy provides a TimesFM forecast, pass it for dynamic Kelly & VaR sizing
        tfm_fc = self._fresh_forecast()
        # Finding 1 (review of D-12): distinguish a model-sizing REFUSAL
        # from a genuine budget-zero so the operator-facing reason is
        # truthful. Snapshot the per-call count around the sizing call.
        # int(...) coercion matters: a stubbed risk object (MagicMock)
        # fabricates ANY attribute, so getattr's default never applies and
        # the counter would be a mock, not 0.
        _sizing_failures_before = _as_counter(
            getattr(self._risk, "model_sizing_failures", 0)
        )
        quantity = clamp_quantity(
            self._risk.position_size(
                signal.entry, signal.sl, lot_size=self._oms.lot_size,
                is_expiry=self._contract_is_expiry,
                max_lots=self._max_lots,
                forecast=tfm_fc,
                side=signal.type,
            )
        )
        # Risk-budget guard: when the per-trade budget can't afford even
        # ONE lot (budget < lot_size * risk distance), sizing correctly
        # returns 0 — opening a zero-size position would put a phantom
        # trade on the UI with frozen P&L. Skip the entry entirely.
        if quantity <= 0:
            # Episode-key stability: the reason must exclude per-evaluation
            # moving values (entry/sl drift with bar.close on a fresh Signal
            # each micro-bar) — a new reason string every evaluation would
            # re-open the blocking episode and spam SignalBlocked. The
            # payload carries the signal; the log line prints entry/sl.
            _model_sizing_failed = (
                _as_counter(getattr(self._risk, "model_sizing_failures", 0))
                > _sizing_failures_before
            )
            _zero_reason = (
                "model sizing unavailable (TimesFM failure) — refusing entry"
                if _model_sizing_failed
                else f"risk budget affords 0 lots (lot={self._oms.lot_size})"
            )
            self._latch_or_signal_block(signal, _zero_reason, bar.time)
            return
        if not self._apply_risk_ceilings(signal, bar, quantity):
            return
        try:
            position = self._oms.submit(signal, quantity)
        except Exception:
            # C3: a broker/OMS submission failure must not kill the engine
            # thread, and the portfolio risk reserved above must be unwound
            # — the entry never happened, so leaving the reservation in
            # place would leak aggregate headroom for the rest of the day.
            logger.exception(
                "❌ [ENTRY FAILED] %s: OMS submit raised — skipping entry and "
                "unwinding risk reservation (engine stays alive)",
                self.symbol,
            )
            self._latch_or_signal_block(signal, "OMS submit raised — broker/OMS failure", bar.time)
            if self._portfolio_risk is not None:
                reserved = getattr(self, "_open_trade_risk", 0.0)
                if reserved > 0:
                    self._portfolio_risk.release(reserved, symbol=self.symbol)
                self._open_trade_risk = 0.0
            return
        paper_fill = getattr(self._oms, "last_fill", None)
        try:
            _is_partial = (
                paper_fill is not None
                and float(paper_fill.filled_quantity) < float(paper_fill.requested_quantity)
            )
        except (TypeError, ValueError, AttributeError):
            _is_partial = False
        if _is_partial:
            from quant.execution.exposure import ExposureState
            self.exposure_state = self.exposure_state.partial_entry(
                symbol=self.symbol,
                order_id=paper_fill.order_id,
                requested_qty=paper_fill.requested_quantity,
                filled_qty=paper_fill.filled_quantity,
                fill_price=paper_fill.fill_price,
            )
            logger.error(
                "[RECONCILIATION REQUIRED] %s: paper order %s partially filled "
                "(%s/%s)",
                self.symbol,
                paper_fill.order_id,
                paper_fill.filled_quantity,
                paper_fill.requested_quantity,
            )
        logger.info(
            "⚡ [SIGNAL EXECUTED] %s: %s %s @ %.2f (SL=%.2f, TP=%.2f, RR=%.2f) — %s | trades_today=%d equity=₹%.0f",
            self.symbol,
            signal.type,
            signal.symbol,
            signal.entry,
            signal.sl,
            signal.tp,
            signal.rr,
            decision.reason,
            risk_st.trades_today,
            risk_st.equity,
        )
        # Contract (quant/execution/ports.py): every SignalApproved must
        # route through an IOMS — emit only after a successful submit.
        self._emit(SignalApproved(symbol=self.symbol, time=bar.time, signal=signal))
        self._entry_bar_index = self._bar_index
        self._latch.pop((getattr(signal, "symbol", "") or self.symbol, str(signal.type)), None)
        pm = self._get_position_manager()
        pm.current_position = position
        self._entry_time_epoch = _bar_epoch_ms(bar.time) / 1000.0
        self._emit(PositionOpened(symbol=self.symbol, time=bar.time, position=position))
        # Immediately notify advisor of new open position (switch role to Position Manager)
        if hasattr(self, "_advisor") and self._advisor is not None:
            try:
                pos_ctx = DecisionContextBuilder().build(
                    bar=bar,
                    symbol=self.symbol,
                    market=self._market,
                    contract_expiry=self._contract_expiry,
                    tick_size=self._tick_size,
                    bar_index=self._bar_index,
                    warm_bars=self._amt_engine.warm_bars,
                    cooldown_remaining_sec=0.0,
                    risk_state=self._risk.state(),
                    amt_dto=amt_dto or self._amt_engine.last_amt_dto or {},
                    order_book=self._last_depth,
                    position=position,
                    entry_bar_index=self._entry_bar_index,
                    recent_decisions=list(self._recent_decisions),
                )
                self._advisor.on_context(pos_ctx)
            except Exception:  # silent-except - advisor context notify is best-effort
                pass

    def _latch_or_signal_block(self, signal, block_reason: str, bar_time: str) -> None:
        """Record a blocked approval. First occurrence of an episode (same
        signal blocked for the same reason) warns + emits SignalBlocked;
        repeats debug-log only. Episodes live per (signal symbol, side) key in
        self._latch. Evaluation is never suppressed."""
        key = (getattr(signal, "symbol", "") or self.symbol, str(signal.type))
        if self._latch.get(key) == block_reason:
            logger.debug(
                "🛑 [SIGNAL BLOCKED] %s: %s %s @ %.2f — %s (repeat, latched)",
                self.symbol, signal.type, signal.symbol, signal.entry, block_reason,
            )
            return
        self._latch[key] = block_reason
        logger.warning(
            "🛑 [SIGNAL BLOCKED] %s: %s %s @ %.2f — %s",
            self.symbol, signal.type, signal.symbol, signal.entry, block_reason,
        )
        self._emit(SignalBlocked(
            symbol=self.symbol, time=bar_time, signal=signal, reason=block_reason,
        ))

    def _build_context(self, bar, amt_dto: dict, cooldown_remaining_sec: float):
        """Single DecisionContext source shared by the flat-path ``_decide()``
        and the positioned thesis-flip check — extracted, not duplicated."""
        eval_symbol = self._underlying() if self._underlying_gateway is not None else self.symbol
        pm = self._get_position_manager() if hasattr(self, "_get_position_manager") else None
        active_pos = (pm.current_position if pm is not None else None) or self.state.position
        return DecisionContextBuilder().build(
            bar=bar,
            symbol=eval_symbol,
            market=self._market,
            contract_expiry=self._contract_expiry,
            tick_size=self._tick_size,
            bar_index=self._bar_index,
            warm_bars=self._amt_engine.warm_bars,
            cooldown_remaining_sec=cooldown_remaining_sec,
            risk_state=self._risk.state(),
            amt_dto=amt_dto or self._amt_engine.last_amt_dto or {},
            order_book=self._last_depth,
            position=active_pos,
            entry_bar_index=self._entry_bar_index,
            recent_decisions=list(self._recent_decisions),
        )

    def _check_thesis_flip(self, amt_dto: dict, bar) -> None:
        """Opposing-signal exit (thesis invalidation).

        Runs ONLY after manage_exit declined to close (SL/spread/CVD/TP/
        trail/time priority preserved). Re-runs the unchanged decision
        pipeline with one bypass — gate 2's open-position blocker — through
        the existing DecisionService so SignalBuilder qualification holds.
        A fully-approved signal OPPOSITE the held side flattens now; a halt
        gates entries, not exits, so this still runs while risk-halted.
        """
        with self._close_lock:
            pm = self._get_position_manager()
            pos = pm.current_position
            if pos is None:
                return
            exec_bar = bar  # close settles on the caller bar (premium scale)
            # Basis parity: entries qualify on the UNDERLYING dto+bar whenever an
            # underlying feed drives decisions — evaluating the flip on the
            # option-side dto (what the positioned bar-exit path hands down)
            # could approve on noise the entry qualification never saw. The
            # executed close still settles on the caller bar (premium scale).
            if self._underlying_gateway is not None:
                amt_dto = self._underlying_amt_dto
                bar = self._last_underlying_bar
                if not amt_dto or bar is None:
                    logger.info(
                        "🔄 [THESIS FLIP] %s: skipped — underlying context "
                        "(entry basis) unavailable this bar",
                        self.symbol,
                    )
                    return
            bars_since_close = (
                self._bar_index - self._last_close_bar_index
                if self._last_close_bar_index >= 0
                else self._cooldown_bars  # no trade yet → no cooldown
            )
            cooldown_remaining_sec = max(0, self._cooldown_bars - bars_since_close) * int(
                getattr(self._aggregator, "interval_seconds", DEFAULT_INTERVAL_SEC) or DEFAULT_INTERVAL_SEC
            )
            ctx = self._build_context(bar, amt_dto, cooldown_remaining_sec)
            # One strategy seam: the positioned flip evaluation goes through the
            # same should_enter entry point entries use (allow_positioned=True
            # bypasses gate 2's open-position blocker and the halt entry gate),
            # so a swapped-in strategy governs both entries and flips.
            decision = self._strategy.should_enter(ctx, allow_positioned=True)
            self._emit(DecisionProduced(symbol=self.symbol, time=bar.time, decision=decision))
            if not (decision.approved and decision.signal is not None):
                return
            signal = decision.signal
            held_side = "LONG" if pos.size > 0 else "SHORT"
            is_put = is_put_symbol(self.symbol)
            is_call = is_call_symbol(self.symbol)
            if is_put:
                held_thesis = "SHORT" if pos.size > 0 else "LONG"
            elif is_call:
                held_thesis = "LONG" if pos.size > 0 else "SHORT"
            else:
                held_thesis = held_side

            # Same-direction approvals (and NO_EDGE) do nothing.
            if signal.type == held_thesis:
                return

            # Fabio Structural Holding: do NOT flip an active trade on minor drift / micro momentum.
            # A genuine thesis flip requires structural invalidation (BREAKOUT, TRIPLE_A, or confirmed VA_FADE).
            if str(signal.reason).upper() == "MODEL_MOMENTUM":
                logger.debug(
                    "🔄 [THESIS FLIP SKIPPED] %s: opposing %s is minor drift (MODEL_MOMENTUM) — holding %s position",
                    self.symbol, signal.type, held_thesis,
                )
                return

            logger.info(
                "🔄 [THESIS FLIP] %s: fresh %s approval (%s @ %.2f RR=%.2f) opposes "
                "held %s thesis (pos %s @ %.2f) — flattening (OPPOSING_SIGNAL)",
                self.symbol, signal.type, signal.model_label,
                float(signal.entry), float(signal.rr), held_thesis,
                held_side,
                float(pos.open_price) if getattr(pos, "open_price", None) else 0.0,
            )
            pm._execute_full_close(
                pos,
                ExitDecision(True, "OPPOSING_SIGNAL", float(exec_bar.close)),
                exec_bar.time,
            )
            self._book_full_close()

    # =========================================================================
    # 5. RISK — session risk, portfolio risk, halt logic
    # =========================================================================
    def _book_full_close(self) -> None:
        """Shared post-full-close bookkeeping — the ONLY full-close release path.

        Called exactly once per full close by every close site (bar exit, tick
        exit, thesis-flip, EOD force-close): marks the cooldown bar index and
        releases the aggregate portfolio-risk reservation for the trade. Prior
        to this extraction each site duplicated the block inline; a divergence
        (e.g. one path skipping the risk release) silently leaked aggregate
        headroom for the rest of the day.
        """
        pm = self._get_position_manager()
        self._last_close_bar_index = self._bar_index
        if self._portfolio_risk is not None:
            self._portfolio_risk.record_close(
                getattr(self, "_open_trade_risk", 0.0),
                float(getattr(pm.last_fill, "pnl", 0.0) or 0.0),
                symbol=self.symbol,
                is_full_close=True,
            )
            self._open_trade_risk = 0.0
        # Immediately notify advisor that position is closed (switch role back to Auction Scanner)
        if hasattr(self, "_advisor") and self._advisor is not None:
            try:
                cooldown_sec = float(self._cooldown_bars * int(getattr(self._aggregator, "interval_seconds", DEFAULT_INTERVAL_SEC) or DEFAULT_INTERVAL_SEC))
                curr_bar = self._aggregator.current_bar or getattr(self.state, "last_bar", None)
                if curr_bar is not None:
                    close_ctx = self._build_context(curr_bar, self._amt_engine.last_amt_dto or {}, cooldown_sec)
                    self._advisor.on_context(close_ctx)
            except Exception:  # silent-except - advisor context notify is best-effort
                pass

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
                portfolio_risk=self._portfolio_risk,  # E11: pyramid add-ons reserve aggregate risk
            )
        return self._pos_mgr

    def force_close_position(self, reason: str) -> bool:
        """Time-driven full close of the base position AND pyramid add-ons.

        EOD square-off backstop: the bar-driven SESSION_CLOSE (Phase 5) only
        fires when a bar closes. If bars stop flowing near the close (feed
        dead / engine starved), an open position would otherwise be carried
        overnight — unacceptable for an intraday book. The coordinator's EOD
        watchdog invokes this on the engine's behalf; it routes through
        PositionManager._execute_full_close so pyramid add-ons, risk release
        and PositionClosed events are handled exactly as the bar-driven path.
        Idempotent: returns False when nothing is open.
        """
        with self._close_lock:
            pm = self._get_position_manager()
            pos = pm.current_position
            if pos is None and not pm.pyramid_positions:
                return False
            bar = getattr(self._aggregator, "current_bar", None)
            if pos is not None:
                price = (
                    float(bar.close)
                    if bar is not None and bar.close
                    else float(pos.open_price)
                )
            else:
                price = float(bar.close) if bar is not None and bar.close else 0.0
            from quant.contracts.timezones import IST as _IST
            ts = datetime.now(tz=_IST).isoformat()
            if pos is not None:
                pm._execute_full_close(pos, ExitDecision(True, reason, price), ts)
                pyramid_closed = 0
            else:
                # Base already gone but pyramid add-ons linger — close them
                # through the single release path so the exit is stamped,
                # logged and risk-released exactly like the base close.
                # The count is surfaced below: a lingering-add-on EOD flatten
                # that closes nothing (all guarded/already gone) is otherwise
                # indistinguishable in the log from one that closed three.
                pyramid_closed = close_lingering_pyramids(pm, price, ts, reason)
            # Post-close bookkeeping — one shared release path.
            self._book_full_close()
            logger.warning(
                "🔒 [EOD FORCE CLOSE] %s reason=%s price=%.2f pyramids_closed=%d",
                self.symbol, reason, price, pyramid_closed,
            )
            return True

    def _fresh_forecast(self):
        """Return the cached TimesFM forecast unless it is stale (>1 bar old).

        Forecasts stamped with ``asof_bar < 0`` predate freshness tracking
        and pass through unchanged. Stale forecasts never reach exits or
        sizing — callers get None and fall back to deterministic behavior.
        """
        tfm_fc = getattr(self._strategy, "get_latest_forecast", lambda s: None)(self.symbol)
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
        with self._close_lock:
            pm = self._get_position_manager()
            # manage_exit returns the surviving position (unchanged, or reduced by
            # a tiered TP partial fill per spec §13.3), or None once fully closed.
            current_pos = pm.current_position
            was_open = current_pos is not None
            tfm_fc = self._fresh_forecast()
            try:
                remaining = pm.manage_exit(
                    amt_dto=amt_dto,
                    bar=bar,
                    position=current_pos,
                    bar_index=self._bar_index,
                    entry_bar_index=self._entry_bar_index,
                    entry_time_epoch=getattr(self, '_entry_time_epoch', 0.0),
                    timesfm_forecast=tfm_fc,
                )
            except Exception:
                # C3: a broker/OMS failure while exiting must not kill the engine
                # thread. Keep the position open so the exit is retried on the
                # next bar; the failure is loud so ops can intervene.
                logger.exception(
                    "❌ [EXIT FAILED] %s: bar-exit OMS call raised — position kept "
                    "open, will retry next bar (engine stays alive)",
                    self.symbol,
                )
                return
            pm.current_position = remaining
            self._release_partial_reserves(pm, remaining)
            if was_open and remaining is None:
                self._book_full_close()

        # Run advisor on position management state so model reasons about open trade
        if hasattr(self, "_advisor") and self._advisor is not None:
            try:
                risk_st = self._risk.state()
                active_pos = remaining or self.state.position
                if self._option_amt_dto is not None and self._last_underlying_bar is not None:
                    advisor_ctx = DecisionContextBuilder().build(
                        bar=bar,
                        symbol=self.symbol,
                        market=self._market,
                        contract_expiry=self._contract_expiry,
                        tick_size=self._tick_size,
                        bar_index=self._bar_index,
                        warm_bars=self._option_amt_engine.warm_bars if self._option_amt_engine else self._amt_engine.warm_bars,
                        cooldown_remaining_sec=0.0,
                        risk_state=risk_st,
                        amt_dto=self._option_amt_dto if self._option_amt_dto else amt_dto,
                        order_book=self._last_depth,
                        position=active_pos,
                        entry_bar_index=self._entry_bar_index,
                        recent_decisions=list(self._recent_decisions),
                    )
                    self._advisor.on_context(advisor_ctx)
                else:
                    advisor_ctx = DecisionContextBuilder().build(
                        bar=bar,
                        symbol=self.symbol,
                        market=self._market,
                        contract_expiry=self._contract_expiry,
                        tick_size=self._tick_size,
                        bar_index=self._bar_index,
                        warm_bars=self._amt_engine.warm_bars,
                        cooldown_remaining_sec=0.0,
                        risk_state=risk_st,
                        amt_dto=amt_dto,
                        order_book=self._last_depth,
                        position=active_pos,
                        entry_bar_index=self._entry_bar_index,
                        recent_decisions=list(self._recent_decisions),
                    )
                    self._advisor.on_context(advisor_ctx)
            except Exception:  # silent-except - advisor context notify is best-effort
                pass

        # Thesis invalidation: normal exits ran first and the position
        # survived — evaluate a fresh contrary approval against it.
        if remaining is not None:
            self._check_thesis_flip(amt_dto, bar)

    # =========================================================================
    # 6. EVENTS — emission, event store, reconciliation
    # =========================================================================
    def _emit(self, event: Event) -> None:
        """Publish to the bus, append to the trace, fold into the projector.

        Journal persistence is handled by a low-priority bus subscriber
        (set up in __init__) so JSON serialization stays off the hot path.

        Guarded by a lock so concurrent emitters (depth updates) never race
        the engine thread's own emits.

        Event sourcing: every emitted event is appended to the EventStore
        (the source of truth) and folded into the cached EngineState.

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
            # skew) must never kill the caller mid-bookkeeping — the journal
            # and storage bridge already received the event via the bus, and
            # the reconcile layer re-syncs event-sourced drift on startup.
            if self.event_appender.append(event) is None:
                exc = self.persistence_health.failure
                if exc is None:
                    exc = RuntimeError("event append failed without an error")
                if self._is_paper_runtime:
                    self.persistence_degraded = True
                    self.reconciliation_required = True
                    self.persistence_failure = exc
                if self._is_paper_runtime:
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
            self.state = apply_event(self.state, event)

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
        """Rebuild state from event store on startup.

        Replays all events in the event store to reconstruct the canonical
        EngineState. Called once before trading resumes after a restart.
        Verifies checksum chain integrity to detect tampering.
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
            # when the fold still yields no position (e.g., journal pruned,
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
                OrderBookLevel(float(l["price"]), float(l["quantity"]))
                for l in depth.get("bids", [])
            ),
            asks=tuple(
                OrderBookLevel(float(a["price"]), float(a["quantity"]))
                for a in depth.get("asks", [])
            ),
        )
