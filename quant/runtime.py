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
from quant.amt.analyzer import AMTAnalyzer
from quant.amt.dto import amt_result_to_dto, empty_amt_dto
from quant.amt.profile.volume_profile import IncrementalVolumeProfile
from quant.amt.session.context import get_session_info
from quant.amt.session.npoc import NPOCTracker
from quant.bars import Bar
from quant.contracts.value_objects import OrderBook, OrderBookLevel
from quant.decision.context import DecisionContext
from quant.decision.decision_service import DecisionService
from quant.decision.signal_builder import clamp_quantity
from quant.session_levels import SessionLevelStore
from quant.events import (
    AmtUpdated,
    AuctionUpdated,
    BarClosed,
    DecisionProduced,
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

# ---------------------------------------------------------------------------
# History-seed startup backoff
# ---------------------------------------------------------------------------
# Startup spawns one AMT history-seed thread per engine almost simultaneously
# (QuantCoordinator._spawn_engine starts every engine in a tight loop). Dhan's
# REST history endpoint rate-limits bursts ([DH-3001]); a burst of concurrent
# get_historical calls trips the broker circuit breaker before the first seed
# succeeds. Fix: stagger first-fetch starts across engines (fixed interval +
# jitter) and retry failures with jittered exponential backoff, so the seed
# is absorbed without ever opening the breaker.
_SEED_STAGGER_SEC = 2.0      # spacing between per-engine first-fetch starts
_SEED_STAGGER_JITTER = 0.5   # random noise so repeated restarts don't re-collide
_SEED_FETCH_RETRIES = 3      # max attempts per symbol (1 + 2 backoff retries)
_SEED_FETCH_BASE_DELAY = 1.5  # exponential backoff base between attempts (s)
_SEED_GATE_LOCK = threading.Lock()
_SEED_NEXT_START = 0.0


def _reserve_seed_slot() -> None:
    """Serialise and stagger history-seed starts across engines.

    Each seed thread reserves the next slot (``stagger`` after the previous
    reservation, plus up to ``jitter`` of random noise) and sleeps until its
    turn, so N engines never hit Dhan's REST history endpoint at the same
    instant. Thread-safe; the sleep happens outside the lock so one engine's
    delay never blocks another's reservation.
    """
    global _SEED_NEXT_START
    with _SEED_GATE_LOCK:
        now = time.monotonic()
        target = max(now, _SEED_NEXT_START)
        _SEED_NEXT_START = target + _SEED_STAGGER_SEC
    delay = max(0.0, target - now) + random.uniform(0.0, _SEED_STAGGER_JITTER)
    if delay > 0:
        logger.info("AMT history seed: staggering start by %.2fs", delay)
        time.sleep(delay)


@dataclass(frozen=True)
class FloatOHLC:
    """Float-based candle for AMTAnalyzer input.

    The legacy AMTHandler converted Decimal-based OHLC to float before
    analyzing (``FloatOHLC``); the analyzer does float arithmetic against
    float profile levels, so Decimal inputs crash on mixed-type ops.
    """

    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float = 0.0
    taker_buy_volume: float = 0.0
    delta: float = 0.0


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
        self._contract_expiry = QuantEngine._parse_contract_expiry(symbol)
        self._aggregator = BarAggregator(interval_seconds=interval_seconds)
        from quant.coordinator import AuctionCoordinator

        self._coordinator = AuctionCoordinator()
        # Full AMT analysis (the legacy AMTHandler pipeline) — one analyzer per
        # engine keeps session-continuous state (rolling VWAP, LVN tracker,
        # acceptance/rejection, displacement legs, ...). ``history_source`` is
        # the coordinator's IMarketData adapter, used once to seed the candle
        # ring so the profile/levels are meaningful from session start.
        self._amt_analyzer = AMTAnalyzer()
        self._amt_candles: list[OHLC] = []
        self._amt_lock = threading.Lock()
        # Incremental volume profile kept in lock-step with ``_amt_candles``
        # (seeded from the same session-scoped history, then updated per live
        # bar close) — passed to the analyzer so it does not rebuild the full
        # histogram from scratch on every bar.
        self._amt_incremental: IncrementalVolumeProfile | None = None
        self._coord_lock = threading.Lock()  # guards AuctionCoordinator builders
        self._history_source = history_source
        # Phase 1 — prior-session levels + naked-POC tracking: the store
        # persists per-symbol {poc, vah, val} across sessions (shared by the
        # coordinator across engines) so the AMT analyzer and the Triple-A
        # take-profit can target the previous balance area (Fabio's rule). A
        # memory-only store is used when none is injected (tests/replay).
        self._session_levels = session_levels or SessionLevelStore()
        self._npoc = NPOCTracker(storage_port=self._session_levels)
        self._npoc.load_from_storage(self._underlying())
        self._session_date: str | None = None
        self._prior = self._session_levels.load_levels(self.symbol)
        self._last_depth: OrderBook | None = None
        self._last_amt_dto: dict | None = None
        self._amt_fail_logged = False
        self._decision_service = DecisionService(min_rr=min_rr)
        # Lot-aware paper OMS: the position size is snapped to lot multiples
        # (units per lot from the broker) so paper rupee P&L matches live
        # fills exactly — see PaperOMS docstring.
        self._oms = PaperOMS(lot_size=lot_size)
        self._exits = ExitEngine(time_stop_bars=time_stop_bars)
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
        # History bars seeded into the decision coordinator (see
        # _start_amt_seed) count toward the warmup requirement.
        self._warm_bars = 0
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
        self._start_amt_seed()
        steps = 0
        while True:
            if max_steps is not None and steps >= max_steps:
                break
            tick = self._gateway.next_tick()
            if tick is None:
                break
            steps += 1
            # Per-tick live LTP/OI/depth — the gameloop polls snapshots at
            # 0.5s, so the sidebar/order-flow stay live between bar closes.
            self._projector.on_quote(self.symbol, tick)
            if tick.depth is not None:
                self._last_depth = self._depth_to_book(tick.depth)
            # When an underlying feed is present, the option tick only drives
            # quotes/depth/fills — auction bars come from the futures stream.
            if self._underlying_gateway is not None:
                utick = self._underlying_gateway.next_tick()
                while utick is not None:
                    bar = self._aggregator.add_tick(utick)
                    if bar is not None:
                        self._on_bar_closed(bar)
                    utick = self._underlying_gateway.next_tick()
            else:
                bar = self._aggregator.add_tick(tick)
                if bar is not None:
                    self._on_bar_closed(bar)
        return list(self._trace)

    @property
    def events(self) -> tuple[Event, ...]:
        return tuple(self._trace)

    @property
    def projector(self) -> StateProjector:
        return self._projector

    def _on_bar_closed(self, bar) -> None:
        with self._coord_lock:
            state = self._coordinator.on_bar_close(bar)
        self._bar_index += 1
        self._emit(BarClosed(symbol=self.symbol, time=bar.time, bar=bar))
        self._emit(AuctionUpdated(symbol=self.symbol, time=bar.time, auction=state))
        # Snapshot the AMT DTO for this bar so the banner/UI sees the same
        # auction evidence the decision path used.
        amt_dto = self._amt_analyze(bar)
        self._emit(AmtUpdated(symbol=self.symbol, time=bar.time, amt=amt_dto))

        if self._position is None:
            self._decide(state, bar)
        else:
            self._manage_exit(state, bar)

    def _decide(self, state, bar) -> None:
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
                phase=getattr(state, "triple_a_phase", "") if state else "",
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

        amt_dto = self._last_amt_dto or {}
        obi = float(amt_dto.get("obi") or 0.0)

        # Direction input to the gates is the deterministic auction-state edge:
        # the AGGRESSION Triple-A signal when the machine has one, else the
        # fresh absorption side (BUY -> LONG, SELL -> SHORT), depth OBI imbalance,
        # or Value-Area location for reversion setups.
        signal = state.triple_a_signal if state is not None else None
        agent_direction = signal if signal in ("LONG", "SHORT") else None
        if (
            agent_direction is None
            and state is not None
            and state.absorption is not None
            and state.absorption.bar_age <= 5
        ):
            agent_direction = {"BUY": "LONG", "SELL": "SHORT"}.get(
                state.absorption.side
            )
        if agent_direction is None and state is not None:
            if obi >= 0.20 and state.close > state.vwap.upper_1:
                agent_direction = "LONG"
            elif obi <= -0.20 and state.close < state.vwap.lower_1:
                agent_direction = "SHORT"
            elif state.location and state.location.zone == "BELOW_VA":
                agent_direction = "LONG"
            elif state.location and state.location.zone == "ABOVE_VA":
                agent_direction = "SHORT"

        # Fabio Gap #9: VWAP directional bias filter.
        # Price below session VWAP → don't go long (mean-reversion pull).
        # Price above session VWAP → don't go short.
        # Exception: IMBALANCED markets override (displacement can carry through VWAP).
        if agent_direction is not None and state is not None:
            session_vwap = float(amt_dto.get("vwap") or 0.0)
            if session_vwap > 0:
                raw_ms_check = str(amt_dto.get("marketState") or "BALANCED").upper()
                if raw_ms_check != "IMBALANCED":
                    if agent_direction == "LONG" and float(state.close) < session_vwap:
                        logger.debug(
                            "🔇 [VWAP BIAS] %s: LONG rejected — close %.2f below VWAP %.2f",
                            self.symbol, float(state.close), session_vwap,
                        )
                        agent_direction = None
                    elif agent_direction == "SHORT" and float(state.close) > session_vwap:
                        logger.debug(
                            "🔇 [VWAP BIAS] %s: SHORT rejected — close %.2f above VWAP %.2f",
                            self.symbol, float(state.close), session_vwap,
                        )
                        agent_direction = None

        # Gate 1 (session-phase) and warmup were hard-coded to pass; the engine
        # now enforces the Fabio NSE session phases (no entries in the
        # 09:15-09:30 opening-noise window, none after 15:15 close protection)
        # and the >15-bar warmup — see quant/amt/session/context.py.
        # Market state + balance ratio from the AMT analyzer (this bar's DTO,
        # snapshotted in _on_bar_closed before _decide). The DEAD market state
        # refuses any initiative entry; the VA-fade tier refuses dead markets.
        raw_ms = str(amt_dto.get("marketState") or "BALANCED").upper()
        if raw_ms == "DEAD":
            amt_market_state = "DEAD"
        elif raw_ms == "IMBALANCED":
            amt_market_state = MarketState.IMBALANCED
        else:
            amt_market_state = MarketState.BALANCED
        risk_st = self._risk.state()
        ctx = DecisionContext(
            state=state,
            bar=bar,
            symbol=self.symbol,
            session_open=self._session_allow_entry(
                bar.time, market=self._market, contract_expiry=self._contract_expiry
            ),
            warmup_complete=(self._bar_index + self._warm_bars) >= _WARMUP_BARS,
            position_open=False,
            cooldown_remaining_sec=cooldown_remaining_sec,
            risk_halted=risk_st.halted,
            consecutive_losses=risk_st.consecutive_losses,
            agent_direction=agent_direction,
            agent_probability=_DETERMINISTIC_CONVICTION,
            market_state=amt_market_state,
            balance_ratio=float(amt_dto.get("balanceRatio") or 0.0),
            # Drive tracker flows only the "second drive" boolean today; the
            # raw drive count is not exported on the WS DTO, so gate 3's
            # rejection reason falls back to drive=0. Thread driveNumber
            # through amt_result_to_dto when the banner needs it.
            drive_entry_valid=bool(amt_dto.get("isSecondDrive") or False),
            # Depth reaches gate 3: the AMT DTO carries the live order-book
            # imbalance (computed from the Dhan 5-level depth snapshot), and
            # gate 3's order-flow aggression leg consumes it as the A3 trigger.
            obi=obi,
            # Canonical session VA (session-scoped, clamped) — gate 4 and
            # SignalBuilder anchor stops on THIS profile so the LOCATION gate
            # compares price against the same POC/VA the UI renders, not the
            # coordinator's differently-bucketed bar-based snapshot.
            poc=float(amt_dto.get("poc") or 0.0),
            vah=float(amt_dto.get("valueAreaHigh") or 0.0),
            val=float(amt_dto.get("valueAreaLow") or 0.0),
            prior_poc=float(amt_dto.get("priorPoc") or 0.0),
            npoc_above=float(amt_dto.get("npocAbove") or 0.0),
            npoc_below=float(amt_dto.get("npocBelow") or 0.0),
            tick_size=self._tick_size,
            equity=risk_st.equity,
            risk_per_trade_pct=risk_st.risk_per_trade_pct,
            # Impulse Leg LVN (Layer 3 profile) — the primary void in the most
            # recent directional impulse leg. Gate 3 Path C (Playbook C sniper)
            # fires when price retests this level with fresh absorption.
            # The key "legLvn" is populated by analyzer.detect_displacement_leg()
            # → amt_result_to_dto(). Zero means no leg profile available yet.
            leg_lvn=float(amt_dto.get("legLvn") or 0.0),
        )
        decision = self._decision_service.evaluate(ctx)
        self._emit(DecisionProduced(symbol=self.symbol, time=bar.time, decision=decision))

        if decision.approved and decision.signal is not None:
            signal = decision.signal
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
            quantity = clamp_quantity(self._risk.position_size(signal.entry, signal.sl))
            position = self._oms.submit(signal, quantity)
            self._entry_bar_index = self._bar_index
            self._position = position
            self._entry_time_epoch = self._bar_epoch_ms(bar.time) / 1000.0
            self._emit(PositionOpened(symbol=self.symbol, time=bar.time, position=position))
        else:
            logger.info(
                "⚪ [DECISION EVAL] %s: approved=False reason=%s phase=%s blocked=%s",
                self.symbol,
                decision.reason,
                decision.phase,
                decision.block_reasons,
            )


    @staticmethod
    def _parse_contract_expiry(symbol: str):
        """Parse the option contract's expiry date from its symbol.

        MCX/NSE option symbols embed the expiry day+month, e.g.
        "CRUDEOIL 17 AUG 7450 CALL" -> 17 Aug, "GOLDM 28 AUG 150500 CALL" ->
        28 Aug. The year is inferred from the current IST date (a parsed date
        already past is next year's). Returns None when the symbol has no
        month token (synthetic test symbols, futures, etc.).
        """
        months = {
            "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
            "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
        }
        tokens = str(symbol or "").split()
        if len(tokens) < 3:
            return None
        day_tok, month_tok = tokens[1], tokens[2]
        if not day_tok.isdigit():
            return None
        month = months.get(month_tok.upper())
        if month is None:
            return None
        day = int(day_tok)
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        try:
            parsed = date(today.year, month, day)
        except ValueError:
            return None
        # A parsed date before today can only be next year's contract.
        if parsed < today:
            parsed = date(today.year + 1, month, day)
        return parsed

    @staticmethod
    def _ist_dt(bar_time):
        """Parse bar_time to an IST datetime, or None when unparseable.

        Accepts epoch-seconds strings (live gateway) and ISO timestamps
        (history bars); synthetic/replay times ("t300") return None so the
        deterministic traces never depend on wall-clock gating.
        """
        ts_ms = QuantEngine._bar_epoch_ms(bar_time)
        if not ts_ms:
            return None
        return datetime.fromtimestamp(
            ts_ms / 1000.0, tz=timezone(timedelta(hours=5, minutes=30))
        )

    @staticmethod
    def _session_allow_entry(bar_time, market: str = "NSE", contract_expiry=None) -> bool:
        """Fabio session gate: new entries only in phases 2-4.

        Exchange-aware (NSE/MCX/GLOBAL): blocks the opening-noise window
        (Phase 1), the close-protection window (Phase 5) and pre/post market.
        MCX trades until 23:30, so 16:45 IST is an open MCX afternoon but a
        closed NSE post-market.

        ``contract_expiry``: on the contract's own expiry day, new entries
        close early — MCX at 21:00 IST (option buying stops at 22:00, and a
        fresh option in the last hour risks the devolvement window) and NSE at
        14:00 IST (Tuesday NIFTY expiry — the final hour's gamma/theta
        distortion corrupts orderflow signals). The NSE square-off at 15:15 is
        already enforced by the phase table (Phase 5 close-protection).
        Unparseable (synthetic/replay) timestamps default to open so the
        deterministic unit/replay traces never depend on wall-clock time;
        live bars always carry parseable epoch-seconds or ISO timestamps.
        """
        if not bar_time:
            return True
        text = str(bar_time).strip()
        is_epoch = (
            text.replace(".", "", 1).lstrip("-").isdigit()
            and len(text) >= 9
            and "T" not in text
        )
        is_iso = "T" in text or "+" in text or ":" in text
        if not (is_epoch or is_iso):
            return True
        try:
            allowed = bool(get_session_info(bar_time, market=market).allow_entry)
        except Exception:
            logger.warning("session phase lookup failed for %r — defaulting to open", bar_time, exc_info=True)
            return True
        if not allowed:
            return False
        if contract_expiry is not None:
            ist = QuantEngine._ist_dt(bar_time)
            if ist is not None and ist.date() == contract_expiry:
                if str(market).upper() == "MCX" and ist.hour >= 21:
                    # MCX expiry day: option buying stops 22:00 IST.
                    return False
                if str(market).upper() == "NSE" and ist.hour >= 14:
                    # NSE expiry day (Tuesday for NIFTY): the final hour's
                    # gamma/theta distortion corrupts orderflow signals — no
                    # fresh entries after 14:00 IST.
                    return False
        return True

    @staticmethod
    def _session_force_exit(bar_time, market: str = "NSE", contract_expiry=None) -> bool:
        """True once entries are blocked (Phase 5 close-protection, post-market).

        Exchange-aware like ``_session_allow_entry``. The NSE phase table marks
        POST_MARKET with ``force_exit=False``, but a position still open after
        15:30 must be squared off — so any window in which new entries are
        disallowed triggers the exit (pre-market and the opening-noise window
        are unreachable with an open position anyway).

        ``contract_expiry`` (MCX only): on the contract's own expiry day, an
        open position is force-squared from 21:30 IST — an ITM option left
        open at expiry devolves into a futures position with margin (MCX
        physical settlement via futures), so it must never ride into the
        devolvement window.
        """
        if not bar_time:
            return False
        text = str(bar_time).strip()
        is_epoch = (
            text.replace(".", "", 1).lstrip("-").isdigit()
            and len(text) >= 9
            and "T" not in text
        )
        is_iso = "T" in text or "+" in text or ":" in text
        if not (is_epoch or is_iso):
            return False
        try:
            info = get_session_info(bar_time, market=market)
        except Exception:
            logger.warning("session force-exit lookup failed for %r — defaulting to hold", bar_time, exc_info=True)
            return False
        force = bool(info.force_exit or not info.allow_entry)
        if not force and str(market).upper() == "MCX" and contract_expiry is not None:
            ist = QuantEngine._ist_dt(bar_time)
            if (
                ist is not None
                and ist.date() == contract_expiry
                and (ist.hour, ist.minute) >= (21, 30)
            ):
                force = True
        return force

    def _manage_exit(self, state, bar) -> None:
        held_bars = self._bar_index - self._entry_bar_index
        if self._session_force_exit(
            bar.time, market=self._market, contract_expiry=self._contract_expiry
        ):
            # Fabio Phase 5 / post-market: EXIT ONLY — square off every open
            # position so nothing rides overnight.
            exit_dec = ExitDecision(True, "SESSION_CLOSE", float(state.close))
        else:
            book = self._last_depth
            best_bid = float(book.bids[0].price) if book and book.bids else None
            best_ask = float(book.asks[0].price) if book and book.asks else None
            # Session context for the session-aware time stop. SessionInfo has
            # no is_expiry/time_to_close fields, so derive both here: the
            # session name is the phase label; expiry + seconds-to-close come
            # from the session helpers.
            from quant.amt.session.context import is_expiry_day, seconds_to_close
            ist_dt = QuantEngine._ist_dt(bar.time)
            amt_dto = self._last_amt_dto or {}
            raw_ms = str(amt_dto.get("marketState") or "BALANCED").upper()
            if raw_ms == "IMBALANCED":
                market_state = MarketState.IMBALANCED
            else:
                market_state = MarketState.BALANCED
            if ist_dt is not None:
                info = get_session_info(bar.time, market=self._market)
                session_phase = str(info.session)
                is_expiry = (
                    self._market == "NSE" and is_expiry_day(ist_dt.date())
                ) or (
                    self._contract_expiry is not None
                    and ist_dt.date() == self._contract_expiry
                )
                time_to_close = seconds_to_close(bar.time, exchange=self._market)
                now_epoch = ist_dt.timestamp()
            else:
                session_phase, is_expiry, time_to_close, now_epoch = "", False, 0.0, 0.0
            exit_dec = self._exits.evaluate(
                self._position, state, bar_index=held_bars,
                bar_high=bar.high, bar_low=bar.low,
                best_bid=best_bid, best_ask=best_ask,
                market_state=market_state, session_phase=session_phase,
                is_expiry=is_expiry, time_to_close=time_to_close,
                entry_time_epoch=getattr(self, "_entry_time_epoch", 0.0),
                now_epoch=now_epoch,
            )
        if exit_dec.should_exit:
            closing = self._position
            fill = self._oms.close(closing, exit_dec.close_price, bar.time,
                                   exit_dec.reason)
            self._exits.pop_trail(closing)
            self._position = None
            # Reset pyramid state: close all pyramid add-ons at the same price
            for pyr_pos in self._pyramid_positions:
                pyr_fill = self._oms.close(pyr_pos, exit_dec.close_price, bar.time,
                                           exit_dec.reason + "_PYRAMID")
                self._exits.pop_trail(pyr_pos)
                self._risk.record_trade(pyr_fill.pnl)
                logger.info(
                    "🔒 [PYRAMID CLOSED] %s level=%d reason=%s pnl=₹%.2f",
                    self.symbol, pyr_pos.pyramid_level, exit_dec.reason, pyr_fill.pnl,
                )
            self._pyramid_positions = []
            self._pyramid_count = 0
            # Track close time so cooldown gate correctly blocks re-entry
            self._last_close_bar_index = self._bar_index
            self._emit(PositionClosed(symbol=self.symbol, time=bar.time, fill=fill))
            risk = self._risk.record_trade(fill.pnl)
            logger.info(
                "🔒 [POSITION CLOSED] %s reason=%s pnl=₹%.2f daily_pnl=₹%.2f "
                "trades=%d/%d equity=₹%.0f halted=%s",
                self.symbol, exit_dec.reason, fill.pnl,
                risk.daily_pnl, risk.trades_today,
                6,  # max_trades_per_session
                risk.equity, risk.halted,
            )
            self._emit(RiskUpdated(symbol=self.symbol, time=bar.time, risk=risk))
        else:
            # Position survived this bar. Check if we can add a pyramid.
            # Pyramid is only authorized when the base trade is risk-free (0.8R hit).
            if self._position is not None and self._exits.is_risk_free(self._position):
                self._check_pyramid(state, bar)

    def _check_pyramid(self, state, bar) -> None:
        """Spec §13.2 pyramid engine: add-on positions at Impulse Leg LVN retest.

        Authorization gates (all must pass):
          1. Base trade is risk-free (SL at breakeven or better)
          2. Maximum 2 pyramid add-ons not yet reached
          3. Session allows entry (no force-exit window)
          4. Risk engine not halted

        Entry conditions (per bar):
          - Price is within 2 ticks of the Impulse Leg LVN (Layer 3 profile)
          - Fresh absorption (bar_age == 0) at the LVN in the trade direction
          - 1m candle closes in the trade direction (close confirms level)

        Sizing:
          Pyramid 1: 50% of base position size (absolute units)
          Pyramid 2: 25% of base position size (absolute units)

        SL ratchet: combined SL moves to LVN - 2*tick (LONG) / LVN + 2*tick
        (SHORT) so the entire bundle (base + pyramids) is always net positive.
        """
        if self._pyramid_count >= 2:
            return  # Max 2 add-ons reached

        # Guard: session must allow new entries
        if not self._session_allow_entry(
            bar.time, market=self._market, contract_expiry=self._contract_expiry
        ):
            return

        # Guard: risk engine must be healthy
        can_trade, _ = self._risk.can_trade()
        if not can_trade:
            return

        # Need the Impulse Leg LVN from the AMT DTO
        amt_dto = self._last_amt_dto or {}
        leg_lvn = float(amt_dto.get("legLvn") or 0.0)
        if leg_lvn <= 0:
            return  # No Layer 3 LVN available yet

        price = float(state.close)
        tick = self._tick_size
        if abs(price - leg_lvn) > 2.0 * tick:
            return  # Price not at LVN zone

        # Need fresh absorption at the LVN
        absorption = state.absorption
        if absorption is None or absorption.bar_age != 0:
            return  # No fresh absorption this bar

        pos = self._position
        long = pos.size > 0

        # Absorption direction must agree with the open position
        if long and absorption.side != "BUY":
            return
        if not long and absorption.side != "SELL":
            return

        # Candle close must confirm the direction
        if long and float(bar.close) < float(bar.open):
            return  # Bearish candle at LVN for a long — skip
        if not long and float(bar.close) > float(bar.open):
            return  # Bullish candle at LVN for a short — skip

        # Size: 50% of base for P1, 25% for P2
        base_size = abs(pos.size)
        fraction = 0.50 if self._pyramid_count == 0 else 0.25
        pyramid_size = base_size * fraction

        # New SL behind the LVN shelf
        new_sl = (leg_lvn - 2.0 * tick) if long else (leg_lvn + 2.0 * tick)

        try:
            pyramid_pos = self._oms.add_pyramid(
                base=pos,
                entry_price=price,
                new_sl=new_sl,
                size=pyramid_size,
                time=bar.time,
                pyramid_level=self._pyramid_count + 1,
            )
        except ValueError as exc:
            logger.debug("⏩ [PYRAMID SKIP] %s: %s", self.symbol, exc)
            return

        self._pyramid_count += 1
        self._pyramid_positions.append(pyramid_pos)

        logger.info(
            "⚡ [PYRAMID ADD] %s P%d @ %.2f size=%.0f SL=%.2f LVN=%.2f",
            self.symbol, self._pyramid_count, price, pyramid_size, new_sl, leg_lvn,
        )
        self._emit(PositionOpened(symbol=self.symbol, time=bar.time, position=pyramid_pos))

    def _emit(self, event: Event) -> None:
        """Publish to the bus, append to the trace, fold into the projector,
        and persist a JSON-serializable record to the journal.

        Guarded by a lock so concurrent emitters (depth updates) never race
        the engine thread's own emits.
        """
        with self._emit_lock:
            self._bus.publish(event)
            self._trace.append(event)
            self._projector.on_event(event)
            if self._journal is not None:
                self._journal.append(
                    {"type": event.__class__.__name__, **asdict(event)}
                )

    # ------------------------------------------------------------------
    # Full AMT analysis (legacy AMTHandler pipeline restored)
    # ------------------------------------------------------------------

    @staticmethod
    def _session_scope(candles) -> list:
        """Keep only candles from the most recent session (the calendar date
        of the newest candle) so POC/VA/VWAP reflect today's auction instead
        of multi-day history.

        Today's candles are kept even when thin (< 5): the AMT analyzer's
        ``len(data) >= 5`` guard then returns an empty result early, which is
        the correct behaviour for a session that has barely started — never
        mix prior-day levels into the session profile.
        """
        if not candles:
            return candles
        newest = candles[-1]
        date = str(newest.time)[:10]
        return [c for c in candles if str(c.time)[:10] == date]

    def _start_amt_seed(self) -> None:
        """Best-effort: seed the AMT candle ring AND the decision profile from
        REST history so POC/VA/VWAP/IB are meaningful from the first bar close.

        The fetched history is session-scoped (today's candles only) so the
        "session" profile is genuinely today's auction. Runs on its own daemon
        thread; ``fetch_history`` is internally sync-safe to run under
        ``asyncio.run`` on a worker thread (the Dhan adapter calls the sync
        ``broker.get_historical``)."""
        if self._history_source is None:
            return

        def run() -> None:
            # Stagger this engine's first fetch behind the other engines'
            # (startup burst protection) before touching the REST endpoint.
            _reserve_seed_slot()
            import asyncio

            candles: list = []
            seed_interval = self._seed_interval_str()
            for attempt in range(1, _SEED_FETCH_RETRIES + 1):
                try:
                    candles = asyncio.run(
                        self._history_source.fetch_history(
                            self.symbol, seed_interval, 500
                        )
                    )
                except Exception as e:
                    import asyncio
                    if not isinstance(e, (TimeoutError, ConnectionError, OSError, asyncio.CancelledError)):
                        logger.critical("Unexpected error", exc_info=True)
                    logger.warning(
                        "AMT history seed failed for %s (attempt %d/%d)",
                        self.symbol, attempt, _SEED_FETCH_RETRIES, exc_info=True,
                    )
                    candles = []
                if candles:
                    break
                if attempt < _SEED_FETCH_RETRIES:
                    # Dhan rate-limit backoff ([DH-3001]). The adapter
                    # swallows transient API failures as [], so retry empties
                    # with jittered exponential backoff — spaced retries let
                    # the rate-limit window pass without tripping the circuit
                    # breaker (a single success resets its failure count).
                    delay = _SEED_FETCH_BASE_DELAY * (
                        2 ** (attempt - 1)
                    ) + random.uniform(0.0, 1.0)
                    logger.info(
                        "AMT history seed retry %d/%d for %s in %.1fs",
                        attempt + 1, _SEED_FETCH_RETRIES, self.symbol, delay,
                    )
                    time.sleep(delay)
            if not candles:
                return
            scoped = self._session_scope(candles)
            with self._coord_lock:
                with self._amt_lock:
                    if self._amt_candles:
                        return  # live bars already flowing — keep them
                    ohlcs = [self._to_float_ohlc(c) for c in scoped]
                    self._amt_candles = ohlcs
                    inc = IncrementalVolumeProfile()
                    for c in ohlcs:
                        inc.update(c)
                    self._amt_incremental = inc
                    self._coordinator.seed_history(
                        [self._to_bar(c) for c in scoped]
                    )
                    self._warm_bars = len(scoped)
            logger.info(
                "AMT seeded %d session candles for %s", len(scoped), self.symbol
            )

        threading.Thread(
            target=run, daemon=True, name=f"amt-seed-{self.symbol}"
        ).start()

    def _seed_interval_str(self) -> str:
        """Dhan history interval string matching the engine's bar aggregation.

        The aggregator floors live ticks to ``interval_seconds`` windows; the
        REST history seed must use the same interval so seeded candles align
        with live bars (1m -> "1m", 5m -> "5m", 60s/300s -> same)."""
        seconds = int(getattr(self._aggregator, "interval_seconds", 60) or 60)
        if seconds % 3600 == 0:
            return f"{seconds // 3600}h"
        if seconds % 60 == 0:
            return f"{seconds // 60}m"
        return f"{seconds}s"

    def _amt_analyze(self, bar) -> dict:
        """Append the closed bar to the AMT ring and run the full AMTAnalyzer.

        Emits the complete 60-field ``amt`` DTO (profile histogram, market
        state, VWAP bands, LVNs/HVNs, absorption, ...) that the frontend
        ``AMTAnalysis`` contract expects. Called once per bar close on the
        engine thread — the analyzer's rolling session state accumulates
        exactly one candle per call.
        """
        # Phase 1 — session rollover: when the bar's date changes, the
        # previous session is complete. Persist its levels (from the last DTO)
        # and reload the prior levels so this session's analyzer and TP can
        # target the previous balance area. Only real ``YYYY-MM-DD`` dates
        # roll (synthetic test times like "t0" never match).
        iso_now = _epoch_to_iso(bar.time)
        iso_date = iso_now[:10] if len(iso_now) >= 10 and iso_now[4] == "-" else ""
        if iso_date and self._session_date and iso_date != self._session_date:
            prev = self._last_amt_dto or {}
            prev_poc = float(prev.get("poc") or 0.0)
            if prev_poc > 0:
                self._session_levels.save_levels(
                    self.symbol,
                    self._session_date,
                    prev_poc,
                    float(prev.get("valueAreaHigh") or 0.0),
                    float(prev.get("valueAreaLow") or 0.0),
                )
                self._npoc.add_session_poc(
                    self._underlying(), self._session_date, prev_poc
                )
            self._prior = self._session_levels.load_levels(self.symbol)
        if iso_date:
            self._session_date = iso_date
        try:
            ohlc = FloatOHLC(
                time=iso_now,
                open=float(bar.open), high=float(bar.high),
                low=float(bar.low), close=float(bar.close),
                volume=float(bar.volume), vwap=float(bar.vwap or 0.0),
                taker_buy_volume=float(bar.buy_volume), delta=float(bar.delta),
            )
        except Exception:
            logger.warning("AMT bar->OHLC mapping failed: %r — keeping last DTO", bar, exc_info=True)
            return self._last_amt_dto or {}
        if ohlc is not None:
            with self._amt_lock:
                self._amt_candles.append(ohlc)
                oldest: FloatOHLC | None = None
                if len(self._amt_candles) > 1000:
                    oldest = self._amt_candles[0]
                    self._amt_candles = self._amt_candles[-1000:]
                if self._amt_incremental is not None:
                    self._amt_incremental.update(ohlc, oldest)
        try:
            with self._amt_lock:
                candles = list(self._amt_candles)
                incremental = self._amt_incremental
            result = self._amt_analyzer.analyze(
                candles,
                order_book=self._last_depth,
                incremental_profile=incremental,
                cushion_tier="Conservative",
                session_pnl=self._risk.state().daily_pnl,
                underlying=self._underlying(),
                symbol=self.symbol,
                prior_poc=self._prior["poc"],
                prior_vah=self._prior["vah"],
                prior_val=self._prior["val"],
                npoc_tracker=self._npoc,
            )
        except Exception:
            if not self._amt_fail_logged:
                logger.warning(
                    "AMT analyze failed for %s — keeping last good DTO",
                    self.symbol, exc_info=True,
                )
                self._amt_fail_logged = True
            return self._last_amt_dto or {}
        # The amt DTO is fully deterministic — no model inference involved.
        dto = amt_result_to_dto(result)
        # Guard against concurrent read in _decide() during startup seed phase.
        with self._amt_lock:
            self._last_amt_dto = dto
        return dto

    @staticmethod
    def _to_float_ohlc(c) -> FloatOHLC:
        return FloatOHLC(
            time=str(c.time),
            open=float(c.open), high=float(c.high), low=float(c.low),
            close=float(c.close), volume=float(c.volume),
            vwap=float(getattr(c, "vwap", 0.0) or 0.0),
            taker_buy_volume=float(getattr(c, "taker_buy_volume", 0.0) or 0.0),
            delta=float(getattr(c, "delta", 0.0) or 0.0),
        )

    @staticmethod
    def _to_bar(c) -> Bar:
        """History OHLC -> decision-path Bar (buy_volume from taker_buy_volume)."""
        vol = float(getattr(c, "volume", 0.0) or 0.0)
        buy = float(getattr(c, "taker_buy_volume", 0.0) or 0.0)
        return Bar(
            time=str(c.time),
            open=float(c.open), high=float(c.high), low=float(c.low),
            close=float(c.close), volume=vol,
            buy_volume=buy, sell_volume=max(0.0, vol - buy),
            delta=float(getattr(c, "delta", 0.0) or 0.0),
            vwap=float(getattr(c, "vwap", 0.0) or 0.0),
        )

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


    @staticmethod
    def _bar_epoch_ms(bar_time: str) -> int:
        """Parse bar.time into epoch milliseconds.

        History bars carry IST ISO strings (``2026-08-07T22:46:12+05:30``);
        live gateway bars carry epoch seconds as strings. Returns 0 when the
        value cannot be parsed.
        """
        if not bar_time:
            return 0
        try:
            from datetime import datetime as _dt, timezone as _tz, timedelta as _td
            _ist = _tz(_td(hours=5, minutes=30))
            dt = _dt.fromisoformat(bar_time.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_ist)
            return int(dt.timestamp() * 1000)
        except (TypeError, ValueError):
            pass
        try:
            return int(float(bar_time) * 1000)
        except (TypeError, ValueError):
            return 0

