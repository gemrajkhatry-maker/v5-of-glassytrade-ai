"""DecisionService — the quant decision engine of record.

Runs GatePipeline (gates 1-5) then SignalBuilder; when the gates pass but no
Triple-A signal materializes, falls back to a Value-Area fade (tier-2); returns
NO_EDGE when nothing qualifies. The returned QuantDecision is consumed by the
backend wiring (quant signal -> domain Signal -> execution).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from quant.decision.context import DecisionContext
from quant.decision.pipeline import GatePipeline
from quant.decision.result import GateResult
from quant.contracts.enums import SignalType, SetupType, Source
from quant.decision.signal_builder import Signal, SignalBuilder, is_min_stop_met
from quant.decision.va_fade import detect_va_fade


@dataclass(frozen=True)
class QuantDecision:
    approved: bool
    signal: Signal | None
    reason: str          # "Triple-A" | "VA_FADE" | "NO_EDGE" | "GATE_REJECTED"
    phase: str           # AuctionState.triple_a_phase
    gate_results: tuple[GateResult, ...]


class DecisionService:
    """The default AMT strategy (implements ``quant.strategy.Strategy``).

    Stateless: construct it anywhere the engine needs a decision policy. The
    concrete entry rules live here; the engine never knows about them — it only
    calls ``evaluate(ctx)``.
    """

    name = "amt"

    def __init__(self, min_rr: float = 1.5) -> None:
        self.min_rr = min_rr

    def evaluate(self, ctx: DecisionContext) -> QuantDecision:
        if ctx.state is None:
            return QuantDecision(False, None, "NO_EDGE", "", ())
        results = GatePipeline().evaluate(ctx)
        if all(r.passed for r in results):
            sig = SignalBuilder().build(ctx, results)
            if sig is not None:
                return QuantDecision(True, sig, "Triple-A", ctx.state.triple_a_phase, tuple(results))
            return QuantDecision(False, None, "GATE_REJECTED", ctx.state.triple_a_phase, tuple(results))
        # VA-fade fallback
        fade = detect_va_fade(ctx.state, ctx)
        if fade and ctx.agent_direction == fade.direction and fade.rr >= self.min_rr:
            if not is_min_stop_met(fade.entry, fade.sl):
                return QuantDecision(False, None, "NO_EDGE", ctx.state.triple_a_phase, tuple(results))
            sig = Signal.create(
                type=SignalType.BUY if fade.direction == "LONG" else SignalType.SELL,
                price=fade.entry,
                reason="Value-Area fade",
                stop_loss=fade.sl,
                take_profit=fade.tp,
                timestamp=ctx.state.time,
                setup=SetupType.RESPONSIVE_FADE,
                source=Source.LLM,
                metadata={"quant_rr": fade.rr, "confidence": 0.5},
            )
            return QuantDecision(True, sig, "VA_FADE", ctx.state.triple_a_phase, tuple(results))
        return QuantDecision(False, None, "NO_EDGE", ctx.state.triple_a_phase, tuple(results))
