"""QuantEngine — the deterministic single-threaded event loop.

Consumes ticks from a ``BrokerGateway``, aggregates them into bars, drives the
pipeline AuctionCoordinator -> DecisionService -> PaperOMS -> ExitEngine ->
SessionRisk, and emits typed events. Purely deterministic: replaying the same
tick sequence always yields the same event trace.

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
from quant.contracts.value_objects import OrderBook, OrderBookLevel
from quant.decision.context import DecisionContext
from quant.decision.decision_service import DecisionService
from quant.decision.signal_builder import clamp_quantity
from quant.decision.context_builder import DecisionContextBuilder
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
    StopMoved,
)
from quant.execution.exits import ExitDecision, ExitEngine
from quant.execution.oms import PaperOMS
from quant.execution.ports import IOMS
from quant.execution.risk import SessionRisk
from quant.persistence import Journal
from quant.state import StateProjector, _epoch_to_iso
from quant.bars import DEFAULT_INTERVAL_SEC

logger = logging.getLogger(__name__)

# Deterministic conviction used for gate 4's probability check when the engine
# decides from the auction state alone (above the 0.55 min_probability
# threshold). The decision-critical path is 100% deterministic by design — no
# model inference is involved, so _decide never waits on external calls.
_DETERMINISTIC_CONVICTION = 0.7
# One-shot startup warning when an option contract runs with no underlying
# feed — Fabio's auction structure belongs on the most liquid futures; running
# AMT on option premium is a deliberate fallback (Task 8).
_UNDERLYING_WARNED = False
# Minimum closed bars (live + seeded history) before the engine may decide.
# The analysis kernel needs enough bars for a meaningful POC/VA/VWAP profile;
# the AMT/decision design pins this at > 15 bars, which also keeps entries
# out of the opening-noise window (15 minutes at the default 1m timeframe).
_WARMUP_BARS = 15



class QuantEngine:
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
        strategy: TradingStrategy | None = None,
        portfolio_risk=None,
        oms=None,
        max_trades_per_session: int = 6,
        advisor=None,
    ) -> None:
        self._gateway = gateway
        self._underlying_gateway = underlying_gateway
        self._portfolio_risk = portfolio_risk  # shared PortfolioRiskAuthority | None
        self.symbol = symbol
        self._tick_size = tick_size
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
        # playbook (Fabio Valentini). Swap for momentum, mean-reversion, etc.
        if strategy is not None:
            self._strategy = strategy
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
        self._risk = SessionRisk(storage=self._session_levels, symbol=self.symbol,
                                 portfolio_risk=self._portfolio_risk,
                                 max_trades_per_session=max_trades_per_session)
        self._bus = EventBus()
        self._projector = StateProjector(interval_sec=interval_seconds)
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
                            SignalApproved, PositionOpened, PositionClosed,
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
        self._position = None
        self._bar_index = 0
        # Pyramiding state (spec §13.2): tracks add-on positions for the base trade.
        # _pyramid_count: number of pyramid add-ons opened (max 2: P1 + P2).
        # _pyramid_positions: list of open pyramid Position objects.
        self._pyramid_count: int = 0
        self._pyramid_positions: list = []
        self._bar_index = 0
        # History bars seeded into the AMT engine count toward the warmup
        # requirement (accessed via self._amt_engine.warm_bars).
        self._entry_bar_index = 0
        self._subscribed = False
        self._emit_lock = threading.Lock()
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
        global _UNDERLYING_WARNED
        try:
            return self._run_inner(max_steps)
        except Exception:
            import logging

            logging.getLogger(__name__).critical(
                "ENGINE THREAD DIED — symbol %s stopped trading. "
                "positions_open=%s last_bar_index=%s",
                self.symbol, self._position is not None, self._bar_index,
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
                        SignalApproved, PositionOpened, PositionClosed,
                        PositionReduced,
                        RiskUpdated, DepthUpdated, AmtUpdated,
                        OrderSubmitted, OrderFilled, StopMoved):
            self._bus.subscribe(evt_type, _journal_subscriber, priority=-100)

    def attach_storage(self, storage) -> None:
        """Project PositionOpened/Closed onto IStorage (restart book)."""
        from quant.persistence_bridge import PositionStorageBridge
        PositionStorageBridge(storage).attach(self._bus)

    def restore_position(self, position) -> None:
        """Rehydrate the in-memory book after a process restart."""
        self._position = position
        self._entry_bar_index = self._bar_index
        self._entry_time_epoch = 0.0

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
                rec["position_open"] = self._position is not None
            self.cert_records.append(rec)
        except Exception:
            pass  # certification must never break trading

    def _run_inner(self, max_steps: int | None = None) -> list[Event]:
        global _UNDERLYING_WARNED
        if not self._subscribed:
            self._gateway.subscribe(self.symbol)
            self._subscribed = True
        if self._underlying_gateway is not None:
            # Fabio Task 8: auction structure belongs on the underlying futures.
            # Subscribe the second feed; its ticks feed AMT via the aggregator.
            self._underlying_gateway.subscribe(self._underlying())
        elif not _UNDERLYING_WARNED and self._contract_expiry is not None:
            # Option contract with no underlying feed — running AMT on the
            # option's own premium is a fallback, not the faithful setup.
            _UNDERLYING_WARNED = True
            logger.warning(
                "No underlying feed for %s — running AMT on the option premium. "
                "Pass underlying_gateway to compute auction structure on the futures.",
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
            # 0. Tick-level fast SL/TP protection (Fabio: exit immediately on stop breach, never wait 5m)
            if self._position is not None:
                self._manage_tick_exit(float(tick.price), str(tick.time))

            # When an underlying feed is present, option ticks aggregate into option candles,
            # while underlying futures ticks feed the AMT auction structure engine.
            if self._underlying_gateway is not None:
                # 1. Micro-trigger: option's own ticks feed 1-min micro aggregator for fast entry decisions
                if self._micro_aggregator is not None:
                    micro_bar = self._micro_aggregator.add_tick(tick)
                    if micro_bar is not None and self._position is None:
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
                        if self._position is not None:
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
                    if micro_bar is not None and self._position is None:
                        amt_dto = self._amt_engine.last_amt_dto
                        if amt_dto:
                            self._decide(amt_dto, micro_bar)

                bar = self._aggregator.add_tick(tick)
                self._amt_engine.on_tick(tick, self._aggregator.current_bar)
                if bar is not None:
                    self._on_bar_closed(bar)

            # Per-tick live LTP/OI/depth and real-time forming live candle —
            # the option's own forming candle is self._aggregator.current_bar
            self._projector.on_quote(
                self.symbol, tick, current_bar=self._aggregator.current_bar
            )
            if tick.depth is not None:
                self._last_depth = self._depth_to_book(tick.depth)
        return list(self._trace)

    @property
    def events(self) -> tuple[Event, ...]:
        return tuple(self._trace)

    @property
    def projector(self) -> StateProjector:
        return self._projector

    def _manage_tick_exit(self, tick_price: float, tick_time: str) -> None:
        """Tick-level fast stop-loss and take-profit breach check (Fabio)."""
        if self._position is None:
            return
        pm = self._get_position_manager()
        was_open = True
        remaining = pm.manage_tick_exit(self._position, tick_price, tick_time)
        if was_open and remaining is None:
            self._position = None
            self._pyramid_positions = pm.pyramid_positions
            self._pyramid_count = pm.pyramid_count
            self._last_close_bar_index = self._bar_index
            if self._portfolio_risk is not None:
                self._portfolio_risk.record_close(
                    getattr(self, "_open_trade_risk", 0.0),
                    float(getattr(pm.last_fill, "pnl", 0.0) or 0.0),
                )
                self._open_trade_risk = 0.0

    def _emit_merged_amt(self, base_dto: dict, time_str: str) -> None:
        merged = dict(self._underlying_amt_dto or base_dto)
        if self._option_amt_dto and self._option_amt_dto.get("profile"):
            merged["profile"] = self._option_amt_dto["profile"]
            if self._option_amt_dto.get("poc"):
                merged["poc"] = self._option_amt_dto["poc"]
            if self._option_amt_dto.get("valueAreaHigh"):
                merged["valueAreaHigh"] = self._option_amt_dto["valueAreaHigh"]
            if self._option_amt_dto.get("valueAreaLow"):
                merged["valueAreaLow"] = self._option_amt_dto["valueAreaLow"]
            merged["hvns"] = self._option_amt_dto.get("hvns", [])
            merged["lvns"] = self._option_amt_dto.get("lvns", [])
            if self._option_amt_dto.get("legProfile"):
                merged["legProfile"] = self._option_amt_dto["legProfile"]
                merged["legPoc"] = self._option_amt_dto.get("legPoc")
                merged["legVah"] = self._option_amt_dto.get("legVah")
                merged["legVal"] = self._option_amt_dto.get("legVal")
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

        if self._position is not None:
            self._manage_exit(amt_dto, bar)
        elif self._micro_aggregator is None:
            self._decide(amt_dto, bar)

    def _decide(self, amt_dto: dict, bar, execution_bar=None) -> None:
        # --- Guard 0: trade-count / risk halt check BEFORE building any context ---
        can_trade, no_trade_reason = self._risk.can_trade()
        if not can_trade:
            logger.info(
                "🚫 [BLOCKED] %s: %s (trades_today=%d)",
                self.symbol, no_trade_reason, self._risk.state().trades_today,
            )
            # Defect 2 fix: emit an explicit HALTED DecisionProduced so the
            # StateProjector clears any stale approved/ENTER state that was
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
            return

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
            return

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
        except Exception:
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
                    position=self._position,
                    entry_bar_index=self._entry_bar_index,
                    recent_decisions=list(self._recent_decisions),
                )
                self._advisor.on_context(advisor_ctx)
            else:
                self._advisor.on_context(ctx)


        if decision.approved and decision.signal is not None:
            signal = decision.signal

            # If running on an option contract with underlying futures feed, translate signal to option premium
            if self._underlying_gateway is not None:
                from quant.amt.session.selector import OptionSelector
                exec_bar = execution_bar or self._aggregator.current_bar or bar
                opt_ltp = float(exec_bar.close) if exec_bar and exec_bar.close > 0 else 0.0
                if opt_ltp > 0:
                    delta = float(getattr(ctx, "option_delta", 0.50) or 0.50)
                    selector = OptionSelector()
                    signal = selector.translate_underlying_signal_to_option(
                        signal=signal,
                        option_symbol=self.symbol,
                        option_ltp=opt_ltp,
                        delta=delta,
                        tick_size=self._tick_size,
                    )
                    if signal is None:
                        return

            logger.info(
                "⚡ [APPROVED SIGNAL] %s: %s @ %.2f (SL=%.2f, TP=%.2f, RR=%.2f) — %s | trades_today=%d equity=₹%.0f",
                self.symbol,
                signal.type,
                signal.entry,
                signal.sl,
                signal.tp,
                signal.rr,
                decision.reason,
                risk_st.trades_today,
                risk_st.equity,
            )
            self._emit(SignalApproved(symbol=self.symbol, time=bar.time, signal=signal))
            # Mirror position_manager's is_expiry source of truth (the traded
            # contract expires today) so entry sizing halves risk on expiry day.
            _ist = _ist_dt(bar.time)
            self._contract_is_expiry = bool(
                self._contract_expiry is not None
                and _ist is not None and _ist.date() == self._contract_expiry
            )
            quantity = clamp_quantity(
                self._risk.position_size(
                    signal.entry, signal.sl, lot_size=self._oms.lot_size,
                    is_expiry=self._contract_is_expiry,
                )
            )
            # Risk-budget guard: when the per-trade budget can't afford even
            # ONE lot (budget < lot_size * risk distance), sizing correctly
            # returns 0 — opening a zero-size position would put a phantom
            # trade on the UI with frozen P&L. Skip the entry entirely.
            if quantity <= 0:
                logger.info(
                    "⏭️ [SIZING] %s: skipping entry — risk budget affords 0 lots "
                    "(entry=%.2f sl=%.2f lot=%d)",
                    self.symbol, signal.entry, signal.sl, self._oms.lot_size,
                )
                return
            # Portfolio-level ceiling: aggregate open risk across ALL engines.
            # Per-engine SessionRisk stays authoritative for its own halts;
            # this is the cross-engine backstop (8 engines x 0.5% each would
            # otherwise risk 4% of capital simultaneously).
            if self._portfolio_risk is not None:
                trade_risk = abs(float(signal.entry) - float(signal.sl)) * max(1.0, quantity)
                ok, why = self._portfolio_risk.can_accept(trade_risk)
                if not ok:
                    logger.warning(
                        "🛑 [PORTFOLIO RISK] %s: entry rejected — %s",
                        self.symbol, why,
                    )
                    return
                if not self._portfolio_risk.register_open(trade_risk):
                    logger.warning(
                        "🛑 [PORTFOLIO RISK] %s: entry rejected at register — "
                        "cap breached between can_accept and register",
                        self.symbol,
                    )
                    return
                self._open_trade_risk = trade_risk
            position = self._oms.submit(signal, quantity)
            self._entry_bar_index = self._bar_index
            self._position = position
            self._entry_time_epoch = _bar_epoch_ms(bar.time) / 1000.0
            self._emit(PositionOpened(symbol=self.symbol, time=bar.time, position=position))
        else:
            logger.info(
                "⚪ [DECISION EVAL] %s: approved=False reason=%s phase=%s blocked=%s",
                self.symbol,
                decision.reason,
                decision.phase,
                decision.block_reasons,
            )

    def _build_context(self, bar, amt_dto: dict, cooldown_remaining_sec: float):
        """Single DecisionContext source shared by the flat-path ``_decide()``
        and the positioned thesis-flip check — extracted, not duplicated."""
        return DecisionContextBuilder().build(
            bar=bar,
            symbol=self.symbol,
            market=self._market,
            contract_expiry=self._contract_expiry,
            tick_size=self._tick_size,
            bar_index=self._bar_index,
            warm_bars=self._amt_engine.warm_bars,
            cooldown_remaining_sec=cooldown_remaining_sec,
            risk_state=self._risk.state(),
            amt_dto=amt_dto or self._amt_engine.last_amt_dto or {},
            order_book=self._last_depth,
            position=self._position,
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
        pos = self._position
        if pos is None:
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
        decision = self._decision_service.evaluate(ctx, allow_positioned=True)
        self._emit(DecisionProduced(symbol=self.symbol, time=bar.time, decision=decision))
        if not (decision.approved and decision.signal is not None):
            return
        signal = decision.signal
        held_side = "LONG" if pos.size > 0 else "SHORT"
        # Same-direction approvals (and NO_EDGE) do nothing.
        if signal.type == held_side:
            return
        logger.info(
            "🔄 [THESIS FLIP] %s: fresh %s approval (%s @ %.2f RR=%.2f) opposes "
            "open %s @ %.2f — flattening (OPPOSING_SIGNAL)",
            self.symbol, signal.type, signal.model_label,
            float(signal.entry), float(signal.rr), held_side,
            float(pos.open_price) if getattr(pos, "open_price", None) else 0.0,
        )
        pm = self._get_position_manager()
        pm._execute_full_close(
            pos,
            ExitDecision(True, "OPPOSING_SIGNAL", float(bar.close)),
            bar.time,
        )
        self._position = None
        self._pyramid_positions = pm.pyramid_positions
        self._pyramid_count = pm.pyramid_count
        self._last_close_bar_index = self._bar_index
        if self._portfolio_risk is not None:
            self._portfolio_risk.record_close(
                getattr(self, "_open_trade_risk", 0.0),
                float(getattr(pm.last_fill, "pnl", 0.0) or 0.0),
            )
            self._open_trade_risk = 0.0

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

    def _manage_exit(self, amt_dto: dict, bar) -> None:
        pm = self._get_position_manager()
        # manage_exit returns the surviving position (unchanged, or reduced by
        # a tiered TP partial fill per spec §13.3), or None once fully closed.
        was_open = self._position is not None
        remaining = pm.manage_exit(
            amt_dto=amt_dto,
            bar=bar,
            position=self._position,
            bar_index=self._bar_index,
            entry_bar_index=self._entry_bar_index,
            entry_time_epoch=getattr(self, '_entry_time_epoch', 0.0),
        )
        self._position = remaining
        self._pyramid_positions = pm.pyramid_positions
        self._pyramid_count = pm.pyramid_count
        if self._portfolio_risk is not None:
            if pm.last_partial_fill is not None:
                closed_sz = abs(pm.last_partial_fill.position.size)
                remaining_sz = abs(remaining.size) if remaining is not None else 0.0
                total_sz = closed_sz + remaining_sz
                fraction = closed_sz / total_sz if total_sz > 0 else 0.0
                release = getattr(self, "_open_trade_risk", 0.0) * fraction
                self._portfolio_risk.record_close(release, float(pm.last_partial_fill.pnl))
                self._open_trade_risk = getattr(self, "_open_trade_risk", 0.0) - release
            if pm.last_pyramid_pnl:
                # ponytail: pyramid add-ons never register open risk (they only
                # fire on a risk-free base); book their pnl, release nothing.
                self._portfolio_risk.record_close(0.0, float(pm.last_pyramid_pnl))
        if was_open and remaining is None:
            self._last_close_bar_index = self._bar_index
            if self._portfolio_risk is not None:
                self._portfolio_risk.record_close(
                    getattr(self, "_open_trade_risk", 0.0),
                    float(getattr(pm.last_fill, "pnl", 0.0) or 0.0),
                )
                self._open_trade_risk = 0.0

        # Run advisor on position management state so model reasons about open trade
        if hasattr(self, "_advisor") and self._advisor is not None:
            try:
                risk_st = self._risk.state()
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
                        position=self._position,
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
                        position=self._position,
                        entry_bar_index=self._entry_bar_index,
                        recent_decisions=list(self._recent_decisions),
                    )
                    self._advisor.on_context(advisor_ctx)
            except Exception:
                pass

        # Thesis invalidation: normal exits ran first and the position
        # survived — evaluate a fresh contrary approval against it.
        if remaining is not None:
            self._check_thesis_flip(amt_dto, bar)

    def _check_pyramid(self, amt_dto: dict, bar) -> None:
        pm = self._get_position_manager()
        pm.check_pyramid(amt_dto, bar, self._position, self._bar_index)
        # Sync pyramid state back
        self._pyramid_positions = pm.pyramid_positions
        self._pyramid_count = pm.pyramid_count
        # Consume the ratcheted base produced by check_pyramid (E10 / Task 8).
        if pm.base_override is not None:
            self._position = pm.base_override
            pm.base_override = None

    def _emit(self, event: Event) -> None:
        """Publish to the bus, append to the trace, fold into the projector.

        Journal persistence is handled by a low-priority bus subscriber
        (set up in __init__) so JSON serialization stays off the hot path.

        Guarded by a lock so concurrent emitters (depth updates) never race
        the engine thread's own emits.
        """
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
            self._projector.on_event(event)


    def _underlying(self) -> str:
        from quant.contracts.exchange_config import ExchangeConfig
        underlying = ExchangeConfig.for_exchange(self._market).extract_underlying(self.symbol)
        if not underlying:
            raise ValueError(
                f"Cannot resolve underlying for instrument {self.symbol!r} "
                f"on market {self._market!r}"
            )
        return underlying

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

