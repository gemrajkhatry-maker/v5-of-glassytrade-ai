"""QuantEngine — the deterministic single-threaded event loop.

Consumes ticks from a ``BrokerGateway``, aggregates them into bars, drives the
pipeline AuctionCoordinator -> DecisionService -> PaperOMS -> ExitEngine ->
SessionRisk, and emits typed events. Purely deterministic: replaying the same
tick sequence always yields the same event trace.

Only imports ``quant.*`` and stdlib — zero backend/ imports.
"""

from __future__ import annotations

import json
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
    AgentDecisionProduced,
    AmtUpdated,
    AuctionUpdated,
    BarClosed,
    DecisionProduced,
    Event,
    EventBus,
    LLMAnalysisProduced,
    OverseerProduced,
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

# Deterministic conviction used for gate 3's probability check when the engine
# decides from the auction state alone (above the 0.55 min_probability
# threshold). The decision-critical path is 100% deterministic by design — the
# LLM is an advisory overlay (narrative + exit tuning) and never gates a trade
# (AMT_ARCHITECTURE_PROPOSAL.md), so _decide must not depend on the async
# fold-back.
_DETERMINISTIC_CONVICTION = 0.7

# Minimum closed bars (live + seeded history) before the engine may decide.
# The analysis kernel needs enough bars for a meaningful POC/VA/VWAP profile;
# the AMT/decision design pins this at > 15 bars (75 minutes of 5m candles),
# which also keeps entries out of the opening-noise window.
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
        inference=None,
        llm_history=None,
        history_source=None,
        lot_size: float = 1.0,
        market: str = "NSE",
        llm_consensus_gate: bool | None = None,
        session_levels: SessionLevelStore | None = None,
    ) -> None:
        self._gateway = gateway
        self.symbol = symbol
        self._tick_size = tick_size
        # Session market for the Fabio phase gates: NSE closes 15:30, MCX
        # trades until 23:30 — a hardcoded NSE table would block every MCX
        # entry after 15:15 ("Session closed").
        self._market = str(market or "NSE").upper()
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
        risk_storage = getattr(self._session_levels, "_storage", None)  # ponytail: session_levels already owns the storage port
        self._risk = SessionRisk(storage=risk_storage, symbol=self.symbol, date=self._session_date)
        self._bus = EventBus()
        self._projector = StateProjector()
        self._journal = Journal(path=journal_path) if journal_path else None
        # ponytail: bounded ring for the whole-session trace. 10k bars @ ~10 events
        # per bar covers a 6.5-hour NSE session; older events fall out of memory.
        # Full history still lands in the tick journal (quant/persistence.Journal).
        self._trace: deque[Event] = deque(maxlen=10_000)
        self._position = None
        self._bar_index = 0
        # History bars seeded into the decision coordinator (see
        # _start_amt_seed) count toward the warmup requirement.
        self._warm_bars = 0
        self._entry_bar_index = 0
        self._subscribed = False
        self._inference = inference
        self._llm_history = llm_history
        self._llm_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="llm-fold"
        )
        self._emit_lock = threading.Lock()
        # LLM-consensus gate (Track D): when enabled, an entry needs the LLM
        # advisory to agree with the deterministic Triple-A direction at High
        # confidence. Opt-in via LLM_CONSENSUS_GATE=1 (or the constructor
        # param) — default OFF so the advisory stays advisory-only until the
        # model is validated (paper-first rollout).
        if llm_consensus_gate is not None:
            self._llm_execution_enabled = bool(llm_consensus_gate)
        else:
            self._llm_execution_enabled = (
                os.getenv("LLM_CONSENSUS_GATE", "0").lower()
                in ("1", "true", "yes")
            )
        self._llm_state_lock = threading.Lock()  # guards _llm_history + _last_llm_bar_index
        self._last_llm_bar_index = -1

    def run(self, max_steps: int | None = None) -> list[Event]:
        """Consume ticks from the gateway, drive the full pipeline, and return
        the event trace. Deterministic: same ticks -> same trace."""
        if not self._subscribed:
            self._gateway.subscribe(self.symbol)
            self._subscribed = True
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
        # Snapshot the AMT DTO for this bar and hand it to the fold-back so
        # the LLM advisory is grounded in the SAME evidence the banner shows
        # (IB break, absorption side, aggression) instead of a stale/last DTO.
        amt_dto = self._amt_analyze(bar)
        self._emit(AmtUpdated(symbol=self.symbol, time=bar.time, amt=amt_dto))

        if self._inference is not None and (
            self._inference.is_ready() or self._inference_loading()
        ):
            # Pass the bar index at submit time so the fold-back thread stamps
            # WHICH bar its advisory analyzed — the async task reads
            # self._bar_index later and could see a newer index.
            self._llm_executor.submit(
                self._schedule_llm, state, bar, amt_dto, self._bar_index
            )

        if self._position is None:
            self._decide(state, bar)
        else:
            self._manage_exit(state, bar)

    def _decide(self, state, bar) -> None:
        # Direction input to the gates is the deterministic Triple-A auction-
        # state signal, NOT the async LLM advisory. It was hard-coded to
        # "LONG", which made a SHORT edge structurally unreachable: gate 4
        # requires ``state.triple_a_signal == agent_direction`` and gate 3 runs
        # the LONG CVD-conflict check, so the kernel's SELL-absorption edge
        # (close < vwap.lower_1 -> AGGRESSION/SHORT) could never execute.
        signal = state.triple_a_signal if state is not None else None
        agent_direction = signal if signal in ("LONG", "SHORT") else None
        # Gate 1 (session-phase) and warmup were hard-coded to pass; the engine
        # now enforces the Fabio NSE session phases (no entries in the
        # 09:15-09:30 opening-noise window, none after 15:15 close protection)
        # and the >15-bar warmup — see quant/amt/session/context.py.
        llm_direction, llm_confidence, llm_fresh = self._llm_consensus_state()
        # Market state + balance ratio from the AMT analyzer (this bar's DTO,
        # snapshotted in _on_bar_closed before _decide). Gate 4 refuses any
        # initiative entry unless the market is IMBALANCED (Fabio: the edge
        # exists only out of balance); the VA-fade tier refuses dead markets.
        amt_dto = self._last_amt_dto or {}
        amt_market_state = str(amt_dto.get("marketState") or "BALANCED").upper()
        if amt_market_state not in ("BALANCED", "IMBALANCED", "DEAD"):
            amt_market_state = "BALANCED"
        ctx = DecisionContext(
            state=state,
            bar=bar,
            symbol=self.symbol,
            session_open=self._session_allow_entry(
                bar.time, market=self._market, contract_expiry=self._contract_expiry
            ),
            warmup_complete=(self._bar_index + self._warm_bars) >= _WARMUP_BARS,
            position_open=False,
            cooldown_remaining_sec=0,
            risk_halted=False,
            agent_direction=agent_direction,
            agent_probability=_DETERMINISTIC_CONVICTION,
            market_state=amt_market_state,
            balance_ratio=float(amt_dto.get("balanceRatio") or 0.0),
            prior_poc=float(amt_dto.get("priorPoc") or 0.0),
            npoc_above=float(amt_dto.get("npocAbove") or 0.0),
            npoc_below=float(amt_dto.get("npocBelow") or 0.0),
            tick_size=self._tick_size,
            llm_direction=llm_direction,
            llm_confidence=llm_confidence,
            llm_fresh=llm_fresh,
            llm_execution_enabled=self._llm_execution_enabled,
        )
        decision = self._decision_service.evaluate(ctx)
        self._emit(DecisionProduced(symbol=self.symbol, time=bar.time, decision=decision))

        if decision.approved and decision.signal is not None:
            signal = decision.signal
            self._emit(SignalApproved(symbol=self.symbol, time=bar.time, signal=signal))
            quantity = clamp_quantity(self._risk.position_size(signal.entry, signal.sl))
            position = self._oms.submit(signal, quantity)
            self._entry_bar_index = self._bar_index
            self._position = position
            self._emit(PositionOpened(symbol=self.symbol, time=bar.time, position=position))

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
            logger.warning("session phase lookup failed for %r", bar_time, exc_info=True)
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
            exit_dec = self._exits.evaluate(self._position, state, bar_index=held_bars)
        if exit_dec.should_exit:
            fill = self._oms.close(self._position, exit_dec.close_price, bar.time,
                                   exit_dec.reason)
            self._position = None
            self._emit(PositionClosed(symbol=self.symbol, time=bar.time, fill=fill))
            risk = self._risk.record_trade(fill.pnl)
            self._emit(RiskUpdated(symbol=self.symbol, time=bar.time, risk=risk))

    def _emit(self, event: Event) -> None:
        """Publish to the bus, append to the trace, fold into the projector,
        and persist a JSON-serializable record to the journal.

        Guarded by a lock so the LLM fold-back thread (``_schedule_llm``) can
        post results without racing the engine thread's own emits.
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
            for attempt in range(1, _SEED_FETCH_RETRIES + 1):
                try:
                    candles = asyncio.run(
                        self._history_source.fetch_history(self.symbol, "5m", 500)
                    )
                except Exception:
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
            logger.warning("AMT bar->OHLC mapping failed: %r", bar, exc_info=True)
            ohlc = None
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
            return self._last_amt_dto if self._last_amt_dto is not None else empty_amt_dto()
        # NB: llmThinking stays empty — the amt DTO must be deterministic and
        # independent of the async LLM fold-back (see test_llm_hook).
        dto = amt_result_to_dto(result)
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
        head = (self.symbol or "").split()
        return head[0] if head else "NIFTY"

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

    def _inference_loading(self) -> bool:
        """True when the inference backend is mid-load and will be ready soon.

        The MLX adapter lazily loads its shared singleton model on the first
        ``predict()`` after a restart. If a bar close lands in that window,
        ``is_ready()`` is False but the fold-back must still be scheduled —
        ``predict()`` waits for the in-flight load rather than raising. Other
        backends (GGUF sync-load, cloud) are never mid-load at call time.
        """
        loader = getattr(self._inference, "is_loading", None)
        return bool(loader and loader())

    def _schedule_llm(self, state, bar, amt_dto=None, bar_index=None) -> None:
        """Run on the llm-fold thread: predict, parse JSON, fold events back.

        The emitted LLM/Overseer/AgentDecision events are posted through the
        lock-guarded ``_emit``, so the deterministic bar/decision trace on the
        engine thread is untouched and async results only append afterwards.

        ``bar_index`` is the engine bar index this analysis belongs to; it is
        stamped so the LLM-consensus gate can judge freshness (an advisory for
        the current or immediately-previous bar only).
        """
        try:
            instruction = self._llm_instruction(state, bar, amt_dto)
            input_text = self._llm_input(state, bar, amt_dto, self.symbol)
            raw = self._inference.predict(
                instruction=instruction,
                input_text=input_text,
                temperature=0.3,
                max_tokens=256,
                prefill="{",
            )
            analysis = json.loads(raw)
            if not isinstance(analysis, dict):
                analysis = {"raw_output": raw}
        except Exception as exc:
            logger.warning("LLM fold-back failed for %s: %s", self.symbol, exc)
            return

        # Stamp the analysis with its own bar time so the UI decision history
        # shows real per-entry timestamps instead of a shared client-side
        # Date.now() value, and so persisted rows keep the actual decision time.
        ts_ms = self._bar_epoch_ms(bar.time)
        analysis.setdefault("timestamp", ts_ms)
        analysis.setdefault("created_at", self._ist_created_at(bar.time, ts_ms))
        analysis.setdefault("input_prompt", input_text)
        analysis.setdefault("raw_output", raw)
        # Audit trail: persist the full system instruction too (the DB sink
        # stores unknown keys in the ``extra`` JSON), so every decision can be
        # verified against exactly what the model was asked.
        analysis.setdefault("instruction", instruction)

        # Contradiction guard: the LLM advisory must never independently
        # claim LONG/SHORT when the deterministic engine found no edge.
        # When the kernel's Triple-A signal is absent, coerce to FLAT.
        engine_edge = str(state.triple_a_signal or "").upper() if state else ""
        llm_dir = str(analysis.get("direction") or "").upper()
        if llm_dir in ("LONG", "SHORT") and engine_edge not in ("LONG", "SHORT"):
            analysis["_original_direction"] = llm_dir
            analysis["direction"] = "FLAT"
            analysis["guard_overridden"] = True
            analysis["guard_reason"] = (
                f"No deterministic edge (triple_a_signal={engine_edge or 'NONE'})"
                " -- advisory overridden to FLAT"
            )

        self._emit(LLMAnalysisProduced(symbol=self.symbol, time=bar.time,
                                       analysis=analysis))
        self._emit(OverseerProduced(
            symbol=self.symbol,
            time=bar.time,
            action=str(analysis.get("action", "")),
            reason=str(analysis.get("reason", analysis.get("rationale", ""))),
        ))
        self._emit(AgentDecisionProduced(symbol=self.symbol, time=bar.time,
                                         decision=self._agent_decision(analysis)))

        if self._llm_history is not None:
            with self._llm_state_lock:
                self._llm_history.append(analysis)
                if len(self._llm_history) >= 50:
                    del self._llm_history[0]
                # Freshness stamp: this analysis is for ``bar_index`` (the bar
                # index captured at submit time). A failed fold-back returns
                # before here, so a failed bar never refreshes the stamp and
                # the consensus gate sees the advisory as stale.
                self._last_llm_bar_index = bar_index

    def _llm_consensus_state(self) -> tuple:
        """Latest LLM advisory (direction, confidence) + freshness flag.

        Fresh = the advisory analyzed the current or immediately-previous bar
        (the fold-back for bar N lands ~seconds after its close, well before
        bar N+1's decision 5m later). Guarded by ``_llm_state_lock`` so the
        engine thread never races the fold-back thread's append.
        """
        if self._llm_history is None:
            return None, None, False
        with self._llm_state_lock:
            entry = self._llm_history[-1] if self._llm_history else None
            fresh = self._last_llm_bar_index >= self._bar_index - 1
            if entry is None:
                return None, None, fresh
            return (
                str(entry.get("direction", "") or "").upper(),
                str(entry.get("confidence", "") or "").capitalize(),
                fresh,
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
            from datetime import datetime as _dt
            return int(
                _dt.fromisoformat(bar_time.replace("Z", "+00:00")).timestamp() * 1000
            )
        except (TypeError, ValueError):
            pass
        try:
            return int(float(bar_time) * 1000)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _ist_created_at(bar_time: str, ts_ms: int) -> str:
        """Format a bar time as the DB's ``YYYY-MM-DD HH:MM:SS`` IST string."""
        from datetime import datetime as _dt
        from quant.contracts.timezones import IST
        if ts_ms:
            return _dt.fromtimestamp(ts_ms / 1000, tz=IST).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        return bar_time

    @staticmethod
    def _normalize_probability(value) -> float:
        """Map the LLM advisory's confidence/probability to a float in [0, 1].

        The LLM contract emits ``confidence: "High" | "Medium" | "Low"``, but
        the frontend contract (types.ts ``probability: number``) and gate 3's
        ``ctx.agent_probability < min_probability`` comparison both require a
        number. Accepts floats, numeric strings, and percentage form (75 -> 0.75).
        """
        if value is None:
            return 0.0
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if not isinstance(value, (int, float)):
            text = str(value).strip().lower()
            words = {"high": 0.8, "medium": 0.6, "low": 0.4}
            if text in words:
                return words[text]
            try:
                value = float(text)
            except (TypeError, ValueError):
                return 0.0
        p = float(value)
        if p > 1.0:
            p = p / 100.0  # tolerate "75" as 75%
        return max(0.0, min(1.0, p))

    @staticmethod
    def _agent_decision(analysis: dict) -> dict:
        return {
            "direction": str(analysis.get("direction", "FLAT")),
            "probability": QuantEngine._normalize_probability(
                analysis.get("probability", analysis.get("confidence", "Medium"))
            ),
            "regime": str(analysis.get("regime", analysis.get("market_state", ""))),
            "timing": str(analysis.get("timing", "")),
            "sizeFraction": analysis.get(
                "sizeFraction", analysis.get("size_fraction")
            ),
            "latencyUs": analysis.get("latencyUs"),
            "rationale": str(analysis.get("rationale", "")),
        }

    def _llm_instruction(self, state, bar, amt_dto=None) -> str:
        """System instruction — the short canonical contract, matching the
        training shape produced by scripts/dataset_render.py (``_DEFAULT_INSTRUCTION``
        + the entry JSON schema). The AMT narrative lives in the USER message
        (``_llm_input``), exactly as the datasets render it — previously the
        narrative was in the system role while training put it in the user
        role, so adapters saw a different role split at runtime than at
        training time.

        The schema allows SHORT: the engine is SHORT-capable, and a LONG/FLAT-only
        schema made the advisory structurally unable to agree with a bearish
        setup (IB BREAK DOWN / SELL ABSORPTION banner vs always-LONG advisory).
        """
        try:
            from quant.inference.generative_ai import _DEFAULT_INSTRUCTION
            from quant.inference.llm_contract import (
                entry_response_schema_instruction,
            )

            return (
                _DEFAULT_INSTRUCTION
                + "\n"
                + entry_response_schema_instruction(allow_short=True)
            )
        except Exception as exc:
            logger.warning("prompt_builder unavailable, using inline prompt: %s", exc)
            return (
                "You are an orderflow analyst. Analyze the auction and return a "
                "JSON object with keys direction (LONG, SHORT or FLAT), "
                "confidence, rationale."
            )

    @staticmethod
    def _entry_prompt_data(state, bar, amt_dto=None, symbol: str = "") -> dict:
        """Build the field dict for the live AMT narrative.

        Single source of truth: the AMT DTO's POC/VA/CVD are what the dashboard
        banner shows — the model must see the same numbers the user sees, not
        the decision-path profile (which drifts by a fraction of a point from
        a different bucketing).
        """
        vp = state.volume_profile
        vw = state.vwap
        of = state.order_flow
        amt = amt_dto or {}
        absr = state.absorption
        return {
            "symbol": symbol,
            "time": state.time,
            "ltp": state.close,
            "poc": amt.get("poc") or vp.poc,
            "vah": amt.get("valueAreaHigh") or vp.vah,
            "val": amt.get("valueAreaLow") or vp.val,
            "market_state": (
                amt.get("marketState") or state.triple_a_signal
                or state.triple_a_phase
            ),
            "aggression": amt.get("aggression", 0.0),
            "cvd": of.cvd,
            "cvd_slope": (
                amt.get("cvdSlope")
                if amt.get("cvdSlope") is not None
                else of.cvd_slope
            ),
            "cvd_divergence": of.cvd_divergence,
            "delta": of.delta,
            "vwap": vw.value,
            "session_vwap": amt.get("sessionVwap") or vw.value,
            "vwap_upper_2": amt.get("vwapUpper2") or vw.upper_2,
            "vwap_lower_2": amt.get("vwapLower2") or vw.lower_2,
            "ib_high": amt.get("ibHigh", 0.0),
            "ib_low": amt.get("ibLow", 0.0),
            "ib_complete": bool(amt.get("ibComplete")),
            "break_direction": amt.get("breakDirection", ""),
            "break_type": amt.get("breakType", ""),
            "break_level": amt.get("breakLevel", 0.0),
            "absorption_side": absr.side if absr is not None else None,
            "market_structure": amt.get("marketStructure", ""),
            "profile_shape": amt.get("profileShape", ""),
            "acceptance_above": bool(amt.get("acceptanceAbove")),
            "acceptance_below": bool(amt.get("acceptanceBelow")),
            "rejection_at_high": bool(amt.get("rejectionAtHigh")),
            "rejection_at_low": bool(amt.get("rejectionAtLow")),
            "is_second_drive": bool(amt.get("isSecondDrive")),
            "lvn_play": amt.get("lvnPlay"),
            "lvns": amt.get("lvns", []),
            "prior_poc": amt.get("priorPoc", 0.0),
            "prior_vah": amt.get("priorVah", 0.0),
            "prior_val": amt.get("priorVal", 0.0),
            "gap_type": amt.get("gapType", ""),
            "opening_bias": amt.get("openingBias", ""),
            "option_type": AMTAnalyzer._detect_option_type(symbol),
        }

    @staticmethod
    def _llm_input(state, bar, amt_dto=None, symbol: str = "") -> str:
        """USER message for the LLM — the live AMT narrative, exactly the
        training shape (scripts/dataset_render.py renders the same narrative
        via render_entry_prompt), plus a compact bar footer with the closed
        bar's OHLC/volume/delta.

        Every numeric goes through quant.inference.formatting: prices at 2dp
        (option tick size is 0.05), volume/delta as integers. Raw floats (e.g.
        a weighted POC of 72.1598272138229) leak into the model output verbatim
        and confuse the rationale — the helper also coerces NaN/None safely.

        The delta is the closed bar's body-ratio delta — the SAME
        ``estimate_tick_delta`` the REST history API serves — so the model sees
        the number the chart shows. Dhan's WS carries no traded buy/sell split:
        the live per-tick attribution (used by the AMT/CVD pipeline) would give
        the model a different, noisier figure than the chart the user is
        looking at (measured: live −17 vs the API's +68.7 on the same bar).
        """
        from quant.contracts.market_data_utils import estimate_tick_delta
        from quant.inference.formatting import fmt_int, fmt_price
        from quant.inference.prompt_builder import build_entry_prompt

        data = QuantEngine._entry_prompt_data(state, bar, amt_dto, symbol)
        delta = estimate_tick_delta(
            bar.open, bar.high, bar.low, bar.close, bar.volume
        )
        narrative = build_entry_prompt(
            data, allow_short=True, include_schema=False
        )
        footer = (
            f"\nBar {bar.time}: O={fmt_price(bar.open)} H={fmt_price(bar.high)} "
            f"L={fmt_price(bar.low)} C={fmt_price(bar.close)} V={fmt_int(bar.volume)} "
            f"delta={fmt_int(delta)}. "
            f"Auction: POC={fmt_price(data['poc'])} VAH={fmt_price(data['vah'])} "
            f"VAL={fmt_price(data['val'])}."
        )
        return narrative + footer
