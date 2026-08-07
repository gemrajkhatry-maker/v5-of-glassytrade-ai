from dataclasses import dataclass

from quant.decision.context import DecisionContext
from quant.decision.result import GateResult

MIN_STOP_DISTANCE_PCT = 0.1
MAX_POSITION_QUANTITY = 1000


def is_stop_too_thin(
    entry: float, sl: float, min_stop_distance_pct: float = MIN_STOP_DISTANCE_PCT
) -> bool:
    """True when the stop distance is below ``min_stop_distance_pct``% of price.

    A sub-0.1% stop (e.g. VA-fade razor-thin SL at VAL-step) is noise, not a
    structural stop, so it must not be emitted as a tradeable Signal.
    """
    return abs(entry - sl) < abs(entry) * (min_stop_distance_pct / 100.0)


def is_min_stop_met(
    entry: float, sl: float, min_stop_distance_pct: float = MIN_STOP_DISTANCE_PCT
) -> bool:
    """True when the stop distance meets ``min_stop_distance_pct``% of price.

    Positive form of ``is_stop_too_thin`` for callers that express the guard as
    "require a structural stop" (e.g. the VA-fade fallback).
    """
    return not is_stop_too_thin(entry, sl, min_stop_distance_pct)


def clamp_quantity(
    quantity: float, max_quantity: float = MAX_POSITION_QUANTITY
) -> float:
    """Clamp a computed position quantity to ``max_quantity`` (sizing step).

    Passing ``max_quantity <= 0`` disables the clamp for callers that explicitly
    override the ceiling.
    """
    if max_quantity is None or max_quantity <= 0:
        return quantity
    return min(quantity, max_quantity)


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
    def __init__(
        self,
        tp_multiplier: float = 2.0,
        min_stop_distance_pct: float = MIN_STOP_DISTANCE_PCT,
        max_position_quantity: float = MAX_POSITION_QUANTITY,
    ) -> None:
        self.tp_multiplier = tp_multiplier
        self.min_stop_distance_pct = min_stop_distance_pct
        self.max_position_quantity = max_position_quantity

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
            monotonic = sl > entry > tp  # SL above entry, TP below
        try:
            assert monotonic, f"inverted signal: direction={direction} entry={entry} sl={sl} tp={tp}"
        except AssertionError:
            return None

        risk = abs(entry - sl)
        if is_stop_too_thin(entry, sl, self.min_stop_distance_pct):
            return None

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

    def size(
        self,
        equity: float,
        entry: float,
        sl: float,
        risk_per_trade_pct: float,
    ) -> float:
        """Compute fixed-fractional quantity and clamp to the max ceiling.

        The clamp is applied in the sizing step (never silently in fills):
        ``equity * risk_pct / |entry - sl|`` may explode on razor-thin stops,
        so the result is capped at ``max_position_quantity``.
        """
        risk = abs(entry - sl)
        if equity <= 0 or risk <= 0:
            return 0.0
        quantity = equity * risk_per_trade_pct / risk
        return clamp_quantity(quantity, self.max_position_quantity)
