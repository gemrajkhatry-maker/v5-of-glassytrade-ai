"""DecisionService — the quant decision engine of record.

Runs GatePipeline (gates 1-4, the Fabio AMT playbook) then SignalBuilder;
when the gates pass but no Triple-A signal materializes, falls back to a
Value-Area fade (tier-2); returns NO_EDGE when nothing qualifies. The returned
QuantDecision is consumed by the backend wiring (quant signal → domain Signal
→ execution).
"""

from __future__ import annotations
from quant.contracts.enums import MarketState

from dataclasses import dataclass, field
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
    reason: str          # "Triple-A" | "LVN_Sniper" | "VA_FADE" | "NO_EDGE" | "GATE_REJECTED" | "HALTED"
    phase: str           # "" (deprecated)
    gate_results: tuple[GateResult, ...]
    # Every failed gate as "NAME: reason" (GateResult.name) so UI/logs can
    # show the full rejection detail, not just one gate's reason.
    block_reasons: tuple[str, ...] = ()
    # Which Fabio playbook produced the approval — matches Signal.model_label.
    # "Triple-A" | "LVN_Sniper" | "VA_Fade" | "" (not approved)
    model_label: str = ""


def _block_reasons(results) -> tuple[str, ...]:
    return tuple(f"{r.name}: {r.reason}" for r in results if not r.passed)


def _label_from_gate_results(results) -> str:
    """Identify which Gate 3 path fired to select the model_label."""
    for r in results:
        if r.gate == 3 and r.passed:
            reason = (r.reason or "").lower()
            if "lvn sniper" in reason or "lvn_sniper" in reason:
                return "LVN_Sniper"
    return "Triple-A"


class DecisionService:
    def __init__(self, min_rr: float = 0.0) -> None:
        self.min_rr = min_rr

    def evaluate(self, ctx: DecisionContext) -> QuantDecision:
        if ctx.bar is None:
            return QuantDecision(False, None, "NO_EDGE", "", ())

        # Hard safety: if risk is halted, emit an explicit HALTED decision so
        # the StateProjector clears any stale approved state from scanner rows.
        # (Defect 2 fix: previously runtime._decide() returned early without
        # emitting any DecisionProduced, leaving stale ENTER signals visible.)
        if ctx.risk_halted:
            return QuantDecision(
                approved=False,
                signal=None,
                reason="HALTED",
                phase="",
                gate_results=(),
                block_reasons=("Risk: session halted",),
                model_label="",
            )

        results = tuple(GatePipeline().evaluate(ctx))
        blocked = _block_reasons(results)
        if all(r.passed for r in results):
            label = _label_from_gate_results(results)
            sig = SignalBuilder().build(ctx, results, model_label=label)
            if sig is not None:
                return QuantDecision(
                    True, sig, label, "", results,
                    model_label=label,
                )
            return QuantDecision(
                False, None, "GATE_REJECTED", "", results, blocked,
            )
        # VA-fade fallback — the balance-returning reversion trade. It targets
        # the POC and requires price OUTSIDE the value area, so it never fires
        # in balanced rotation; a dead market refuses even the reversion.
        if str(getattr(ctx.market_state, "value", ctx.market_state) or "").upper() == "DEAD":
            return QuantDecision(False, None, "NO_EDGE", "", tuple(results), blocked)
        fade = detect_va_fade(ctx)
        if fade:
            import logging
            log = logging.getLogger(__name__)
            log.info(f"FADE EVAL {ctx.symbol}: fade={fade} agent_dir={ctx.agent_direction} rr={fade.rr} min_rr={self.min_rr}")
        if fade and (ctx.agent_direction in (fade.direction, None)) and fade.rr >= self.min_rr:
            if not is_min_stop_met(fade.entry, fade.sl):
                return QuantDecision(False, None, "NO_EDGE", "", tuple(results), blocked)
            sig = Signal(
                type=fade.direction, reason="Value-Area fade", entry=fade.entry,
                sl=fade.sl, tp=fade.tp, rr=fade.rr, model_label="VA_Fade",
                symbol=ctx.symbol, timestamp=ctx.time_str,
            )
            return QuantDecision(
                True, sig, "VA_FADE", "", tuple(results),
                model_label="VA_Fade",
            )
        return QuantDecision(False, None, "NO_EDGE", "", tuple(results), blocked)
