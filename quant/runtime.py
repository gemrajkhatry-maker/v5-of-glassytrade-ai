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
from quant.decision_context_builder import DecisionContextBuilder
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
    AmtUpdated,
    AuctionUpdated,
    BarClosed,
    DecisionProduced,
    DepthUpdated,
    Event,
    EventBus,
    PositionClosed,
    PositionOpened,
    RiskUpdated,
    SignalApproved,
)
from quant.execution.exits import ExitDecision, ExitEngine
from quant.execution.oms import PaperOMS
from quant.execution.risk import SessionRisk
from quant.persistence import Journal
from quant.state import StateProjector, _epoch_to_iso

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
        interval_seconds: int = 60,
        journal_path: str | None = None,
        min_rr: float = 1.5,
        tick_size: float = 0.05,
        time_stop_bars: int = 60,
        history_source=None,
        lot_size: float = 1.0,
        market: str = "NSE",
        session_levels: SessionLevelStore | None = None,
        underlying_gateway=None,
        strategy: TradingStrategy | None = None,
    ) -> None:
        self._gateway = gateway
        self._underlying_gateway = underlying_gateway
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
        self._underlying_aggregator = (
            BarAggregator(interval_seconds=interval_seconds)
            if self._underlying_gateway is not None
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
        # AMT analysis engine — owns the candle ring, incremental profile,
        # analyzer, and seed logic. Receives callbacks for depth and risk PnL.
        self._option_amt_engine = None
        self._option_amt_dto: dict | None = None
        self._underlying_amt_dto: dict | None = None

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
        # Lot-aware paper OMS: the position size is snapped to lot multiples
        # (units per lot from the broker) so paper rupee P&L matches live
        # fills exactly — see PaperOMS docstring.
        self._oms = PaperOMS(lot_size=lot_size)
        self._exits = ExitEngine(time_stop_bars=time_stop_bars)
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
        self._risk = SessionRisk(storage=self._session_levels, symbol=self.symbol)
        self._bus = EventBus()
        self._projector = StateProjector()
        self._journal = Journal(path=journal_path) if journal_path else None
        # Journal persistence via low-priority bus subscriber — keeps JSON
        # serialization off the hot path in _emit(). Subscribe to all event
        # types since the bus uses exact-type matching.
        if self._journal is not None:
            def _journal_subscriber(event: Event) -> None:
                self._journal.append(
                    {"type": event.__class__.__name__, **asdict(event)}
                )
            for evt_type in (BarClosed, AuctionUpdated, DecisionProduced,
                            SignalApproved, PositionOpened, PositionClosed,
                            RiskUpdated, DepthUpdated, AmtUpdated):
                self._bus.subscribe(evt_type, _journal_subscriber, priority=-100)
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
        # Default 5 bars = 5 minutes on a 1m timeframe (configurable).
        self._cooldown_bars: int = 5
        self._last_close_bar_index: int = -1  # bar index of most recent fill

    def run(self, max_steps: int | None = None) -> list[Event]:
        """Consume ticks from the gateway, drive the full pipeline, and return
        the event trace. Deterministic: same ticks -> same trace."""
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
        steps = 0
        while True:
            if max_steps is not None and steps >= max_steps:
                break
            tick = self._gateway.next_tick()
            if tick is None:
                break
            steps += 1
            # When an underlying feed is present, option ticks aggregate into option candles,
            # while underlying futures ticks feed the AMT auction structure engine.
            if self._underlying_gateway is not None:
                # 1. Option's OWN ticks feed the option's aggregator to form real option candles
                option_bar = self._aggregator.add_tick(tick)
                if self._option_amt_engine is not None:
                    self._option_amt_engine.on_tick(tick, self._aggregator.current_bar)
                if option_bar is not None:
                    self._bar_index += 1
                    self._emit(BarClosed(symbol=self.symbol, time=option_bar.time, bar=option_bar))
                    if self._option_amt_engine is not None:
                        self._option_amt_dto = self._option_amt_engine.analyze(option_bar)
                        self._emit_merged_amt(self._option_amt_dto, option_bar.time)

                # 2. Underlying futures ticks feed the underlying aggregator and AMT engine
                if self._underlying_aggregator is not None:
                    utick = self._underlying_gateway.next_tick()
                    while utick is not None:
                        ubar = self._underlying_aggregator.add_tick(utick)
                        self._amt_engine.on_tick(utick, self._underlying_aggregator.current_bar)
                        if ubar is not None:
                            self._underlying_amt_dto = self._amt_engine.analyze(ubar)
                            self._emit_merged_amt(self._underlying_amt_dto, ubar.time)
                            if self._position is None:
                                self._decide(self._underlying_amt_dto, ubar)
                            else:
                                self._manage_exit(self._underlying_amt_dto, ubar)
                        utick = self._underlying_gateway.next_tick()
            else:
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
        self._emit(AmtUpdated(symbol=self.symbol, time=time_str, amt=merged))

    def _on_bar_closed(self, bar) -> None:
        self._bar_index += 1
        self._emit(BarClosed(symbol=self.symbol, time=bar.time, bar=bar))
        # Snapshot the AMT DTO for this bar so the banner/UI sees the same
        # auction evidence the decision path used.
        amt_dto = self._amt_engine.analyze(bar)
        self._emit(AmtUpdated(symbol=self.symbol, time=bar.time, amt=amt_dto))

        if self._position is None:
            self._decide(amt_dto, bar)
        else:
            self._manage_exit(amt_dto, bar)

    def _decide(self, amt_dto: dict, bar) -> None:
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
            getattr(self._aggregator, "interval_seconds", 60) or 60
        )
        if cooldown_bars_remaining > 0:
            logger.debug(
                "⏳ [COOLDOWN] %s: %d bars remaining before next entry",
                self.symbol, cooldown_bars_remaining,
            )
            return  # Skip decision entirely during cooldown

        amt_dto = self._amt_engine.last_amt_dto or {}
        risk_st = self._risk.state()
        ctx = DecisionContextBuilder().build(
            bar=bar,
            symbol=self.symbol,
            market=self._market,
            contract_expiry=self._contract_expiry,
            tick_size=self._tick_size,
            bar_index=self._bar_index,
            warm_bars=self._amt_engine.warm_bars,
            cooldown_remaining_sec=cooldown_remaining_sec,
            risk_state=risk_st,
            amt_dto=amt_dto,
        )
        decision = self._strategy.should_enter(ctx)
        self._emit(DecisionProduced(symbol=self.symbol, time=bar.time, decision=decision))

        if decision.approved and decision.signal is not None:
            signal = decision.signal

            # If running on an option contract with underlying futures feed, translate signal to option premium
            if self._underlying_gateway is not None:
                from quant.amt.session.selector import OptionSelector
                cur_bar = self._aggregator.current_bar
                opt_ltp = float(cur_bar.close) if (cur_bar and cur_bar.close > 0) else (float(bar.close) if bar else 0.0)
                if opt_ltp > 0 and abs(opt_ltp - signal.entry) > 1.0:
                    delta = float(getattr(ctx, "option_delta", 0.50) or 0.50)
                    selector = OptionSelector()
                    signal = selector.translate_underlying_signal_to_option(
                        signal=signal,
                        option_symbol=self.symbol,
                        option_ltp=opt_ltp,
                        delta=delta,
                        tick_size=self._tick_size,
                    )

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
            quantity = clamp_quantity(
                self._risk.position_size(signal.entry, signal.sl, lot_size=self._oms.lot_size)
            )
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
            )
        return self._pos_mgr

    def _manage_exit(self, amt_dto: dict, bar) -> None:
        pm = self._get_position_manager()
        # Sync pyramid state from the position manager
        closed = pm.manage_exit(
            amt_dto=amt_dto,
            bar=bar,
            position=self._position,
            bar_index=self._bar_index,
            entry_bar_index=self._entry_bar_index,
            entry_time_epoch=getattr(self, '_entry_time_epoch', 0.0),
        )
        if closed:
            self._position = None
            self._pyramid_positions = pm.pyramid_positions
            self._pyramid_count = pm.pyramid_count
            self._last_close_bar_index = self._bar_index

    def _check_pyramid(self, amt_dto: dict, bar) -> None:
        pm = self._get_position_manager()
        pm.check_pyramid(amt_dto, bar, self._position, self._bar_index)
        # Sync pyramid state back
        self._pyramid_positions = pm.pyramid_positions
        self._pyramid_count = pm.pyramid_count

    def _emit(self, event: Event) -> None:
        """Publish to the bus, append to the trace, fold into the projector.

        Journal persistence is handled by a low-priority bus subscriber
        (set up in __init__) so JSON serialization stays off the hot path.

        Guarded by a lock so concurrent emitters (depth updates) never race
        the engine thread's own emits.
        """
        with self._emit_lock:
            self._bus.publish(event)
            self._trace.append(event)
            self._projector.on_event(event)


    def _underlying(self) -> str:
        from quant.contracts.exchange_config import ExchangeConfig
        return ExchangeConfig.for_exchange(self._market).extract_underlying(self.symbol) or "NIFTY"

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

