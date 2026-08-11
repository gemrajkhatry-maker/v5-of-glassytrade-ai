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
        min_rr: float = 1.5,
    ) -> None:
        self.tp_multiplier = tp_multiplier
        self.min_stop_distance_pct = min_stop_distance_pct
        self.max_position_quantity = max_position_quantity
        self.min_rr = min_rr

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

        # CONTINUATION-TP: Fabio's target for an initiative trade is the
        # previous balance area / prior POC ("the market seeks a new balance").
        # The structural target is the nearest level ahead of the entry from
        # {naked-POC above, prior-session POC, session VAH} (LONG) or
        # {naked-POC below, prior-session POC, session VAL} (SHORT), capped at
        # the fixed R-multiple when it is nearer, and applied only when the
        # capped R:R still meets ``min_rr``. With no structure ahead (zeros),
        # the build-guide fixed R-multiple remains the explicit placeholder.
        # The reversion (VA-fade) path targets the POC — see
        # quant/decision/va_fade.py.
        if direction == "LONG":
            val = float(state.volume_profile.val)
            step = float(state.volume_profile.step)
            anchor = val if entry > val else nearest_level
            # Fabio: SL sits 1-2 ticks INSIDE the value-area edge, not a full
            # profile bucket outside it.
            sl = anchor - 2 * TICK_SIZE_NSE_OPTIONS
            if sl >= anchor:  # degenerate profile safety net
                sl = anchor - step if step > 0 else anchor
            tp = entry + (entry - sl) * self.tp_multiplier
            structural = self._cap_at_nearest_acceptable(
                entry, sl,
                float(getattr(ctx, "npoc_above", 0.0) or 0.0),
                float(getattr(ctx, "prior_poc", 0.0) or 0.0),
                float(state.volume_profile.vah or 0.0),
                direction="LONG",
                min_rr=self.min_rr,
            )
            if structural is not None:
                tp = min(tp, structural)
        else:
            vah = float(state.volume_profile.vah)
            step = float(state.volume_profile.step)
            anchor = vah if entry < vah else nearest_level
            # Fabio: SL sits 1-2 ticks INSIDE the value-area edge, not a full
            # profile bucket outside it.
            sl = anchor + 2 * TICK_SIZE_NSE_OPTIONS
            if sl <= anchor:  # degenerate profile safety net
                sl = anchor + step if step > 0 else anchor
            tp = entry - (sl - entry) * self.tp_multiplier
            structural = self._cap_at_nearest_acceptable(
                entry, sl,
                float(getattr(ctx, "npoc_below", 0.0) or 0.0),
                float(getattr(ctx, "prior_poc", 0.0) or 0.0),
                float(state.volume_profile.val or 0.0),
                direction="SHORT",
                min_rr=self.min_rr,
            )
            if structural is not None:
                tp = max(tp, structural)

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

    def _cap_at_nearest_acceptable(
        self,
        entry: float,
        sl: float,
        *candidates: float,
        direction: str,
        min_rr: float = 1.5,
    ) -> float | None:
        """Nearest structural level ahead of ``entry`` whose capped R:R >= min_rr.

        Candidates are scanned nearest-first; the first one that still pays
        ``min_rr`` against the actual stop is the cap. Levels too close to pay
        (e.g. session VAH 2 ticks away on a 3-tick stop) are skipped — the
        caller keeps the fixed R-multiple target when nothing qualifies.
        """
        risk = abs(entry - sl)
        if risk <= 0:
            return None
        if direction == "LONG":
            above = sorted(c for c in candidates if c and c > entry)
            for cand in above:
                if (cand - entry) / risk >= min_rr:
                    return cand
        else:
            below = sorted((c for c in candidates if c and 0 < c < entry), reverse=True)
            for cand in below:
                if (entry - cand) / risk >= min_rr:
                    return cand
        return None

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
