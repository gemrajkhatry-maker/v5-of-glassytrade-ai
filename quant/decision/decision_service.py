"""DecisionService — the quant decision engine of record.

Runs GatePipeline (gates 1-7) then SignalBuilder; when the gates pass but no
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
from quant.decision.signal_builder import Signal, SignalBuilder, is_min_stop_met
from quant.decision.va_fade import detect_va_fade


@dataclass(frozen=True)
class QuantDecision:
    approved: bool
    signal: Signal | None
    reason: str          # "Triple-A" | "VA_FADE" | "NO_EDGE" | "GATE_REJECTED"
    phase: str           # AuctionState.triple_a_phase
    gate_results: tuple[GateResult, ...]
    # Every failed gate as "NAME: reason" (GateResult.name) so UI/logs can
    # show the full rejection detail, not just one gate's reason.
    block_reasons: tuple[str, ...] = ()


def _block_reasons(results) -> tuple[str, ...]:
    return tuple(f"{r.name}: {r.reason}" for r in results if not r.passed)


class DecisionService:
    def __init__(self, min_rr: float = 1.5) -> None:
        self.min_rr = min_rr

    def evaluate(self, ctx: DecisionContext) -> QuantDecision:
        if ctx.state is None:
            return QuantDecision(False, None, "NO_EDGE", "", ())
        results = tuple(GatePipeline().evaluate(ctx))
        blocked = _block_reasons(results)
        if all(r.passed for r in results):
            sig = SignalBuilder().build(ctx, results)
            if sig is not None:
                return QuantDecision(True, sig, "Triple-A", ctx.state.triple_a_phase, results)
            return QuantDecision(False, None, "GATE_REJECTED", ctx.state.triple_a_phase, results, blocked)
        # VA-fade fallback — the balance-returning reversion trade. It targets
        # the POC and requires price OUTSIDE the value area, so it never fires
        # in balanced rotation; a dead market refuses even the reversion.
        if str(ctx.market_state or "").upper() == "DEAD":
            return QuantDecision(False, None, "NO_EDGE", ctx.state.triple_a_phase, tuple(results), blocked)
        fade = detect_va_fade(ctx.state, ctx)
        if fade and ctx.agent_direction == fade.direction and fade.rr >= self.min_rr:
            if not is_min_stop_met(fade.entry, fade.sl):
                return QuantDecision(False, None, "NO_EDGE", ctx.state.triple_a_phase, tuple(results), blocked)
            sig = Signal(type=fade.direction, reason="Value-Area fade", entry=fade.entry,
                         sl=fade.sl, tp=fade.tp, rr=fade.rr, confidence=0.5,
                         symbol=ctx.symbol, timestamp=ctx.state.time)
            return QuantDecision(True, sig, "VA_FADE", ctx.state.triple_a_phase, tuple(results))
        return QuantDecision(False, None, "NO_EDGE", ctx.state.triple_a_phase, tuple(results), blocked)
