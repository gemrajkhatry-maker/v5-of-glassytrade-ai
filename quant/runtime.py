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
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass

from quant.aggregator import BarAggregator
from quant.amt.analyzer import AMTAnalyzer
from quant.amt.dto import amt_result_to_dto, empty_amt_dto
from quant.amt.profile.volume_profile import IncrementalVolumeProfile
from quant.bars import Bar
from quant.contracts.value_objects import OrderBook, OrderBookLevel
from quant.decision.context import DecisionContext
from quant.decision.decision_service import DecisionService
from quant.decision.signal_builder import clamp_quantity
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
from quant.execution.exits import ExitEngine
from quant.execution.oms import PaperOMS
from quant.execution.risk import SessionRisk
from quant.persistence import Journal
from quant.state import StateProjector, _epoch_to_iso

logger = logging.getLogger(__name__)


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
    ) -> None:
        self._gateway = gateway
        self.symbol = symbol
        self._tick_size = tick_size
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
        self._last_depth: OrderBook | None = None
        self._last_amt_dto: dict | None = None
        self._amt_fail_logged = False
        self._decision_service = DecisionService(min_rr=min_rr)
        self._oms = PaperOMS()
        self._exits = ExitEngine(time_stop_bars=time_stop_bars)
        self._risk = SessionRisk()
        self._bus = EventBus()
        self._projector = StateProjector()
        self._journal = Journal(path=journal_path) if journal_path else None
        self._trace: list[Event] = []
        self._position = None
        self._bar_index = 0
        self._entry_bar_index = 0
        self._subscribed = False
        self._inference = inference
        self._llm_history = llm_history
        self._llm_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="llm-fold"
        )
        self._emit_lock = threading.Lock()

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
        self._emit(AmtUpdated(symbol=self.symbol, time=bar.time,
                              amt=self._amt_analyze(bar)))

        if self._inference is not None and self._inference.is_ready():
            self._llm_executor.submit(self._schedule_llm, state, bar)

        if self._position is None:
            self._decide(state, bar)
        else:
            self._manage_exit(state, bar)

    def _decide(self, state, bar) -> None:
        ctx = DecisionContext(
            state=state,
            bar=bar,
            symbol=self.symbol,
            session_open=True,
            warmup_complete=True,
            position_open=False,
            cooldown_remaining_sec=0,
            risk_halted=False,
            agent_direction="LONG",
            agent_probability=0.7,
            tick_size=self._tick_size,
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

    def _manage_exit(self, state, bar) -> None:
        held_bars = self._bar_index - self._entry_bar_index
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
            try:
                import asyncio

                candles = asyncio.run(
                    self._history_source.fetch_history(self.symbol, "5m", 500)
                )
            except Exception:
                logger.warning(
                    "AMT history seed failed for %s", self.symbol, exc_info=True
                )
                return
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
        try:
            ohlc = FloatOHLC(
                time=_epoch_to_iso(bar.time),
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

    def _schedule_llm(self, state, bar) -> None:
        """Run on the llm-fold thread: predict, parse JSON, fold events back.

        The emitted LLM/Overseer/AgentDecision events are posted through the
        lock-guarded ``_emit``, so the deterministic bar/decision trace on the
        engine thread is untouched and async results only append afterwards.
        """
        try:
            instruction = self._llm_instruction(state, bar)
            input_text = self._llm_input(state, bar)
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
            self._llm_history.append(analysis)
            if len(self._llm_history) >= 50:
                del self._llm_history[0]

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
    def _agent_decision(analysis: dict) -> dict:
        return {
            "direction": str(analysis.get("direction", "FLAT")),
            "probability": analysis.get(
                "probability", analysis.get("confidence", "Medium")
            ),
            "regime": str(analysis.get("regime", analysis.get("market_state", ""))),
            "timing": str(analysis.get("timing", "")),
            "sizeFraction": analysis.get(
                "sizeFraction", analysis.get("size_fraction")
            ),
            "latencyUs": analysis.get("latencyUs"),
            "rationale": str(analysis.get("rationale", "")),
        }

    def _llm_instruction(self, state, bar) -> str:
        """System instruction — the canonical entry prompt when the pure builder
        is importable, else a minimal inline instruction."""
        try:
            from quant.inference.prompt_builder import build_entry_prompt

            vp = state.volume_profile
            vw = state.vwap
            of = state.order_flow
            return build_entry_prompt({
                "symbol": self.symbol,
                "time": state.time,
                "ltp": state.close,
                "poc": vp.poc,
                "vah": vp.vah,
                "val": vp.val,
                "market_state": state.triple_a_signal or state.triple_a_phase,
                "cvd": of.cvd,
                "cvd_slope": of.cvd_slope,
                "cvd_divergence": of.cvd_divergence,
                "delta": of.delta,
                "vwap": vw.value,
                "vwap_upper_2": vw.upper_2,
                "vwap_lower_2": vw.lower_2,
            })
        except Exception as exc:
            logger.warning("prompt_builder unavailable, using inline prompt: %s", exc)
            return (
                "You are an orderflow analyst. Analyze the auction and return a "
                "JSON object with keys direction, confidence, rationale."
            )

    @staticmethod
    def _llm_input(state, bar) -> str:
        vp = state.volume_profile
        return (
            f"Bar {bar.time}: O={bar.open} H={bar.high} L={bar.low} "
            f"C={bar.close} V={bar.volume} delta={bar.delta}. "
            f"Auction: POC={vp.poc} VAH={vp.vah} VAL={vp.val}."
        )
