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
from dataclasses import asdict

from quant.aggregator import BarAggregator
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
from quant.state import StateProjector

logger = logging.getLogger(__name__)


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
    ) -> None:
        self._gateway = gateway
        self.symbol = symbol
        self._tick_size = tick_size
        self._aggregator = BarAggregator(interval_seconds=interval_seconds)
        from quant.coordinator import AuctionCoordinator

        self._coordinator = AuctionCoordinator()
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
        steps = 0
        while True:
            if max_steps is not None and steps >= max_steps:
                break
            tick = self._gateway.next_tick()
            if tick is None:
                break
            steps += 1
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
        state = self._coordinator.on_bar_close(bar)
        self._bar_index += 1
        self._emit(BarClosed(symbol=self.symbol, time=bar.time, bar=bar))
        self._emit(AuctionUpdated(symbol=self.symbol, time=bar.time, auction=state))
        self._emit(AmtUpdated(symbol=self.symbol, time=bar.time,
                              amt=self._amt_from_state(state)))

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

    @staticmethod
    def _amt_from_state(state) -> dict:
        """Small ``amt`` DTO derived from the auction state so the field is
        always populated even without an LLM."""
        vp = state.volume_profile
        of = state.order_flow
        return {
            "poc": vp.poc,
            "vah": vp.vah,
            "val": vp.val,
            "delta": of.delta,
        }

    def _schedule_llm(self, state, bar) -> None:
        """Run on the llm-fold thread: predict, parse JSON, fold events back.

        The emitted LLM/Overseer/AgentDecision events are posted through the
        lock-guarded ``_emit``, so the deterministic bar/decision trace on the
        engine thread is untouched and async results only append afterwards.
        """
        try:
            raw = self._inference.predict(
                instruction=self._llm_instruction(state, bar),
                input_text=self._llm_input(state, bar),
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
