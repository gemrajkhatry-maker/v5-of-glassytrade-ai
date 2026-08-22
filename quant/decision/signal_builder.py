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

        if ctx.bar is None:
            return None

        entry = float(ctx.bar.close)

        # Canonical value area — the AMT analyzer's session-scoped, clamped VA
        # the UI renders, matching gate 4 exactly (DecisionContext.poc/vah/val).
        amt_val = ctx.val if ctx.val and ctx.val > 0 else None
        amt_vah = ctx.vah if ctx.vah and ctx.vah > 0 else None

        if direction == "LONG":
            val = amt_val
            vah = amt_vah
            step = ctx.tick_size
            if val is not None and vah is not None and val > vah:
                # Corrupt / inverted profile -> triggers inverted SL rejection
                anchor = val
            elif (getattr(ctx, "nearest_buy_print_below", 0.0) or 0.0) > 0 \
                    and entry > ctx.nearest_buy_print_below:
                # A big BUY print below = institutional support. Anchor there
                # (Fabio Gap #10): prints create structural levels.
                anchor = ctx.nearest_buy_print_below
            elif ctx.leg_lvn and ctx.leg_lvn > 0 and entry > ctx.leg_lvn:
                anchor = ctx.leg_lvn
            elif val is not None and entry > val:
                anchor = val
            elif hasattr(ctx.bar, "low") and float(ctx.bar.low) < entry:
                anchor = float(ctx.bar.low)
            else:
                anchor = val or ctx.poc or (entry - 5 * (ctx.tick_size or TICK_SIZE_NSE_OPTIONS))
            # Fabio: SL sits 1-2 ticks INSIDE the value-area/LVN edge, not a full
            # profile bucket outside it.
            sl = anchor - 2 * (ctx.tick_size or TICK_SIZE_NSE_OPTIONS)
            if sl >= anchor:  # degenerate profile safety net
                sl = anchor - step if step > 0 else anchor
            if (val is None or vah is None or val <= vah) and sl >= entry:
                sl = entry - max(step * 2, abs(entry) * (self.min_stop_distance_pct / 100.0))
            # Fabio: target structural levels (prior POC / naked POC / opposite VA) when available.
            # Fall back to fixed R:R multiplier when no structure qualifies.
            fixed_tp = entry + (entry - sl) * self.tp_multiplier
            tp = self._structural_tp(ctx, entry, sl, "LONG", fixed_tp)
        else:
            val = amt_val
            vah = amt_vah
            step = ctx.tick_size
            if val is not None and vah is not None and val > vah:
                # Corrupt / inverted profile -> triggers inverted SL rejection
                anchor = vah
            elif (getattr(ctx, "nearest_sell_print_above", 0.0) or 0.0) > 0 \
                    and entry < ctx.nearest_sell_print_above:
                anchor = ctx.nearest_sell_print_above
            elif ctx.leg_lvn and ctx.leg_lvn > 0 and entry < ctx.leg_lvn:
                anchor = ctx.leg_lvn
            elif vah is not None and entry < vah:
                anchor = vah
            elif hasattr(ctx.bar, "high") and float(ctx.bar.high) > entry:
                anchor = float(ctx.bar.high)
            else:
                anchor = vah or ctx.poc or (entry + 5 * (ctx.tick_size or TICK_SIZE_NSE_OPTIONS))
            # Fabio: SL sits 1-2 ticks INSIDE the value-area/LVN edge, not a full
            # profile bucket outside it.
            sl = anchor + 2 * (ctx.tick_size or TICK_SIZE_NSE_OPTIONS)
            if sl <= anchor:  # degenerate profile safety net
                sl = anchor + step if step > 0 else anchor
            if (val is None or vah is None or val <= vah) and sl <= entry:
                sl = entry + max(step * 2, abs(entry) * (self.min_stop_distance_pct / 100.0))
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
            timestamp=ctx.time_str,
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
