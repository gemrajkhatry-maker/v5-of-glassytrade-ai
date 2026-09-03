from dataclasses import dataclass

from quant.decision.context import DecisionContext
from quant.decision.result import GateResult
from quant.decision.stops import DEFAULT_TICK, structural_anchor, structural_stop

MIN_STOP_DISTANCE_PCT = 0.1
MAX_POSITION_QUANTITY = 1000
# ponytail: NSE options tick size; promote to config when we trade a second instrument class
TICK_SIZE_NSE_OPTIONS = DEFAULT_TICK


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
        return max(0.0, quantity)
    return max(0.0, min(quantity, max_quantity))


@dataclass(frozen=True)
class Signal:
    type: str            # "LONG" | "SHORT"
    reason: str
    entry: float
    sl: float
    tp: float
    rr: float
    model_label: str     # "Triple-A" | "LVN_Sniper" | "VA_Fade" — which playbook triggered
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

    def build_or_reason(
        self,
        ctx: DecisionContext,
        pipeline_results: list[GateResult],
        model_label: str = "Triple-A",
    ) -> tuple[Signal | None, str]:
        if any(not r.passed for r in pipeline_results):
            return None, "gates failed"

        direction = ctx.agent_direction
        if direction not in ("LONG", "SHORT"):
            return None, "no direction"

        if ctx.bar is None:
            return None, "no bar"

        entry = float(ctx.bar.close)
        tick = ctx.tick_size if ctx.tick_size and ctx.tick_size > 0 else TICK_SIZE_NSE_OPTIONS
        anchor = structural_anchor(ctx, direction)
        sl = structural_stop(direction, entry, anchor, tick)
        if direction == "LONG":
            if sl >= entry:
                sl = entry - max(tick * 2, abs(entry) * (self.min_stop_distance_pct / 100.0))
            fixed_tp = entry + (entry - sl) * self.tp_multiplier
            tp = self._structural_tp(ctx, entry, sl, "LONG", fixed_tp)
        else:
            if sl <= entry:
                sl = entry + max(tick * 2, abs(entry) * (self.min_stop_distance_pct / 100.0))
            fixed_tp = entry - (sl - entry) * self.tp_multiplier
            tp = self._structural_tp(ctx, entry, sl, "SHORT", fixed_tp)

        if direction == "LONG":
            monotonic = sl < entry < tp
        else:
            monotonic = sl > entry > tp  # SL above entry, TP below
        try:
            assert monotonic, f"inverted signal: direction={direction} entry={entry} sl={sl} tp={tp}"
        except AssertionError:
            import logging as _log
            _log.getLogger(__name__).warning(
                "SignalBuilder: inverted signal dropped — %s entry=%.2f sl=%.2f tp=%.2f",
                direction, entry, sl, tp,
            )
            return None, f"inverted signal: direction={direction} entry={entry} sl={sl} tp={tp}"

        risk = abs(entry - sl)
        if is_stop_too_thin(entry, sl, self.min_stop_distance_pct):
            return None, "thin stop"

        rr = abs(tp - entry) / risk if risk > 0 else 0.0

        return Signal(
            type=direction,
            reason="All 4 gates passed",
            entry=entry,
            sl=sl,
            tp=tp,
            rr=rr,
            model_label=model_label,
            symbol=ctx.symbol,
            timestamp=ctx.time_str,
        ), ""

    def build(
        self,
        ctx: DecisionContext,
        pipeline_results: list[GateResult],
        model_label: str = "Triple-A",
    ) -> Signal | None:
        """Back-compat wrapper — prefer build_or_reason for auditability."""
        sig, _why = self.build_or_reason(ctx, pipeline_results, model_label)
        return sig

    @staticmethod
    def _structural_tp(
        ctx: DecisionContext,
        entry: float,
        sl: float,
        direction: str,
        fallback_tp: float,
        min_rr: float = 1.5,
    ) -> float:
        """Pick the nearest structural TP target that meets minimum R:R.

        Fabio's rule: target the previous balance area / prior POC / nearest
        unfilled naked POC / opposite Value Area boundary. Fall back to the fixed
        R:R multiplier when no structural target qualifies.

        Priority: nearest NPOC > prior POC > opposite VA edge > fixed R:R.
        """
        risk = abs(entry - sl)
        if risk <= 0:
            return fallback_tp

        candidates: list[float] = []

        # Collect structural targets in the right direction
        is_va_fade = getattr(ctx, "setup_evidence", None) and getattr(ctx.setup_evidence, "setup_type", "") == "VA_FADE"
        if direction == "LONG":
            if is_va_fade and ctx.poc and ctx.poc > entry:
                candidates.append(ctx.poc)
            if ctx.npoc_above and ctx.npoc_above > entry:
                candidates.append(ctx.npoc_above)
            if ctx.prior_poc and ctx.prior_poc > entry:
                candidates.append(ctx.prior_poc)
            if ctx.vah and ctx.vah > entry:
                candidates.append(ctx.vah)
        else:
            if is_va_fade and ctx.poc and ctx.poc < entry and ctx.poc > 0:
                candidates.append(ctx.poc)
            if ctx.npoc_below and ctx.npoc_below < entry and ctx.npoc_below > 0:
                candidates.append(ctx.npoc_below)
            if ctx.prior_poc and ctx.prior_poc < entry and ctx.prior_poc > 0:
                candidates.append(ctx.prior_poc)
            if ctx.val and ctx.val < entry and ctx.val > 0:
                candidates.append(ctx.val)

        # Filter: must give R:R >= min_rr and stay within reasonable price scale (prevent option-scale level leakage into futures)
        valid = []
        for target in candidates:
            if not (0.70 * entry <= target <= 1.30 * entry):
                continue
            reward = abs(target - entry)
            rr = reward / risk
            if min_rr <= rr <= 10.0:
                valid.append((abs(target - entry), target))  # (distance, price)

        if valid:
            # Pick nearest qualifying structural target
            valid.sort()
            return valid[0][1]

        return fallback_tp

    # NOTE: no ``size`` method here — position sizing lives in
    # ``quant.execution.risk.SessionRisk.position_size`` (the single sizing
    # authority); the module-level ``clamp_quantity`` applies the ceiling at
    # the engine's order-submission step. A second fixed-fractional formula
    # in this class was removed because it duplicated that authority with a
    # different clamp and risk source (architectural review finding).
