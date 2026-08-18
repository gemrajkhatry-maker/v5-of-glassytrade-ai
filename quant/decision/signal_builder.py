from dataclasses import dataclass

from quant.decision.context import DecisionContext
from quant.decision.result import GateResult

MIN_STOP_DISTANCE_PCT = 0.1
MAX_POSITION_QUANTITY = 1000
# ponytail: NSE options tick size; promote to config when we trade a second instrument class
TICK_SIZE_NSE_OPTIONS = 0.05


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

    def build(
        self,
        ctx: DecisionContext,
        pipeline_results: list[GateResult],
        model_label: str = "Triple-A",
    ) -> Signal | None:
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

        # Canonical value area — the AMT analyzer's session-scoped, clamped VA
        # the UI renders, matching gate 4 exactly (DecisionContext.poc/vah/val).
        # Falls back to the state's bar-based profile only when no AMT VA.
        amt_val = ctx.val if ctx.val and ctx.val > 0 else None
        amt_vah = ctx.vah if ctx.vah and ctx.vah > 0 else None

        if direction == "LONG":
            val = amt_val if amt_val is not None else float(state.volume_profile.val)
            step = float(state.volume_profile.step)
            anchor = val if entry > val else nearest_level
            # Fabio: SL sits 1-2 ticks INSIDE the value-area edge, not a full
            # profile bucket outside it.
            sl = anchor - 2 * TICK_SIZE_NSE_OPTIONS
            if sl >= anchor:  # degenerate profile safety net
                sl = anchor - step if step > 0 else anchor
            if sl >= entry:
                sl = entry - 2 * TICK_SIZE_NSE_OPTIONS
            # Fabio: target structural levels (prior POC / naked POC) when available.
            # Fall back to fixed R:R multiplier when no structure qualifies.
            fixed_tp = entry + (entry - sl) * self.tp_multiplier
            tp = self._structural_tp(ctx, entry, sl, "LONG", fixed_tp)
        else:
            vah = amt_vah if amt_vah is not None else float(state.volume_profile.vah)
            step = float(state.volume_profile.step)
            anchor = vah if entry < vah else nearest_level
            # Fabio: SL sits 1-2 ticks INSIDE the value-area edge, not a full
            # profile bucket outside it.
            sl = anchor + 2 * TICK_SIZE_NSE_OPTIONS
            if sl <= anchor:  # degenerate profile safety net
                sl = anchor + step if step > 0 else anchor
            if sl <= entry:
                sl = entry + 2 * TICK_SIZE_NSE_OPTIONS
            fixed_tp = entry - (sl - entry) * self.tp_multiplier
            tp = self._structural_tp(ctx, entry, sl, "SHORT", fixed_tp)

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

        return Signal(
            type=direction,
            reason="All 4 gates passed",
            entry=entry,
            sl=sl,
            tp=tp,
            rr=rr,
            model_label=model_label,
            symbol=ctx.symbol,
            timestamp=state.time,
        )

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
        unfilled naked POC. Fall back to the fixed R:R multiplier when no
        structural target qualifies.

        Priority: nearest NPOC > prior POC > fixed R:R.
        """
        risk = abs(entry - sl)
        if risk <= 0:
            return fallback_tp

        candidates: list[float] = []

        # Collect structural targets in the right direction
        if direction == "LONG":
            if ctx.npoc_above and ctx.npoc_above > entry:
                candidates.append(ctx.npoc_above)
            if ctx.prior_poc and ctx.prior_poc > entry:
                candidates.append(ctx.prior_poc)
        else:
            if ctx.npoc_below and ctx.npoc_below < entry and ctx.npoc_below > 0:
                candidates.append(ctx.npoc_below)
            if ctx.prior_poc and ctx.prior_poc < entry and ctx.prior_poc > 0:
                candidates.append(ctx.prior_poc)

        # Filter: must give R:R >= min_rr
        valid = []
        for target in candidates:
            reward = abs(target - entry)
            rr = reward / risk
            if rr >= min_rr:
                valid.append((abs(target - entry), target))  # (distance, price)

        if valid:
            # Pick nearest qualifying structural target
            valid.sort()
            return valid[0][1]

        return fallback_tp

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
