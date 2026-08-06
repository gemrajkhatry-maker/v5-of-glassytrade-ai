from dataclasses import dataclass

from quant.decision.context import DecisionContext
from quant.decision.result import GateResult


@dataclass(frozen=True)
class Signal:
    type: str            # "LONG" | "SHORT"
    reason: str
    entry: float
    sl: float
    tp: float
    rr: float
    confidence: float
    symbol: str
    timestamp: str


class SignalBuilder:
    def __init__(self, tp_multiplier: float = 2.0) -> None:
        self.tp_multiplier = tp_multiplier

    def build(self, ctx: DecisionContext, pipeline_results: list[GateResult]) -> Signal | None:
        if any(not r.passed for r in pipeline_results):
            return None

        direction = ctx.agent_direction
        if direction not in ("LONG", "SHORT"):
            return None

        state = ctx.state
        if state is None:
            return None

        entry = float(state.close)
        nearest_level = float(state.location.nearest_level)

        if direction == "LONG":
            val = float(state.volume_profile.val)
            step = float(state.volume_profile.step)
            anchor = val if entry > val else nearest_level
            sl = anchor - step if step > 0 else anchor
            tp = entry + (entry - sl) * self.tp_multiplier
        else:
            vah = float(state.volume_profile.vah)
            step = float(state.volume_profile.step)
            anchor = vah if entry < vah else nearest_level
            sl = anchor + step if step > 0 else anchor
            tp = entry - (sl - entry) * self.tp_multiplier

        if direction == "LONG":
            monotonic = sl < entry < tp
        else:
            monotonic = entry > sl > tp
        try:
            assert monotonic, f"inverted signal: direction={direction} entry={entry} sl={sl} tp={tp}"
        except AssertionError:
            return None

        risk = abs(entry - sl)
        rr = abs(tp - entry) / risk if risk > 0 else 0.0

        confidence = (
            float(state.absorption.strength)
            if state.absorption is not None
            else ctx.agent_probability
        )

        return Signal(
            type=direction,
            reason="All 5 gates passed",
            entry=entry,
            sl=sl,
            tp=tp,
            rr=rr,
            confidence=confidence,
            symbol=ctx.symbol,
            timestamp=state.time,
        )
