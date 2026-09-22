import logging
from dataclasses import dataclass, field

from quant.contracts.constants import TICK_SIZE_NSE_OPTIONS
from quant.contracts.instrument_registry import is_option_contract
from quant.contracts.entities import derive_signal_id
from quant.decision.context import DecisionContext
from quant.decision.result import GateResult
from quant.decision.stops import structural_anchor, structural_stop

logger = logging.getLogger(__name__)

MIN_STOP_DISTANCE_PCT = 0.1
MAX_POSITION_QUANTITY = 1000
# TICK_SIZE_NSE_OPTIONS is imported from quant.contracts.constants.


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
    # Stable logical identity for retries and broker idempotency. Derived from
    # the decision content (RESTART-STABLE): replaying the same approved bar
    # after a crash re-derives the SAME id, so broker-side correlation dedup
    # still blocks a duplicate order. compare=False: identity, not behavior —
    # keeps replay traces equal. An explicit signal_id wins.
    signal_id: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if not self.signal_id:
            object.__setattr__(
                self,
                "signal_id",
                derive_signal_id(
                    symbol=self.symbol,
                    timestamp=self.timestamp,
                    reason=self.reason,
                    entry=self.entry,
                    stop_loss=self.sl,
                    take_profit=self.tp,
                    kind=self.type,
                    setup=self.model_label,
                ),
            )


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
        model_label: str = "",
    ) -> tuple[Signal | None, str]:
        if any(not r.passed for r in pipeline_results):
            return None, "gates failed"
        if not model_label:
            return None, "unlabeled setup"

        direction = ctx.agent_direction
        if direction not in ("LONG", "SHORT"):
            return None, "no direction"

        if is_option_contract(ctx.symbol) and direction == "SHORT":
            return None, "option scalping is buy-only (cannot short options)"

        if ctx.bar is None:
            return None, "no bar"

        entry = float(ctx.bar.close)
        tick = ctx.tick_size if ctx.tick_size and ctx.tick_size > 0 else TICK_SIZE_NSE_OPTIONS
        anchor = structural_anchor(ctx, direction)
        if anchor is None:
            return None, "no structural anchor"
        sl = structural_stop(direction, entry, anchor, tick)
        if sl <= 0:
            return None, f"stop at/below zero ({sl})"
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
        if not monotonic:
            logger.warning(
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
        model_label: str = "",
    ) -> Signal | None:
        """Back-compat wrapper — prefer build_or_reason for auditability."""
        sig, _why = self.build_or_reason(ctx, pipeline_results, model_label)
        return sig

    @staticmethod
    def _shield_tp(
        tp: float,
        entry: float,
        direction: str,
        tick: float,
        shield_ticks: int = 2,
    ) -> float:
        """Spec §11 tick-inside profit target shield.

        When the take-profit sits at a major structural level (NPOC, prior POC,
        VAH/VAL), place it 1-2 ticks **inside** the level (toward entry) so the
        limit fill executes BEFORE the liquidity cascade at the exact structural
        level triggers slippage. Returns the unmodified ``tp`` if doing so would
        invert the signal or if ``tp`` is not at a structural extreme.
        """
        if tick <= 0 or tp <= 0 or entry <= 0:
            return tp
        offset = tick * shield_ticks
        if direction == "LONG":
            shielded = tp - offset
            # Never shield above entry (would invert the signal)
            if shielded <= entry:
                return tp
            return shielded
        else:  # SHORT
            shielded = tp + offset
            if shielded >= entry:
                return tp
            return shielded

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

        Per spec §11, structural TP levels are shielded 1-2 ticks inside (toward
        entry) to fill before slippage cascades at the exact structural level.
        """
        risk = abs(entry - sl)
        if risk <= 0:
            return fallback_tp

        tick = ctx.tick_size if ctx.tick_size and ctx.tick_size > 0 else TICK_SIZE_NSE_OPTIONS

        # MEAN_REVERSION exits at balance (Fabio Model 2): a VA_FADE always
        # targets the POC. The generic filter below would drop the POC when its
        # reward is under min_rr and fall through to the opposite VA edge, which
        # is the wrong exit for a balance-return trade.
        is_va_fade = getattr(ctx, "setup_evidence", None) and getattr(ctx.setup_evidence, "setup_type", "") == "VA_FADE"
        if is_va_fade and ctx.poc and ctx.poc > 0:
            raw_tp = ctx.poc
            if direction == "LONG" and raw_tp > entry:
                # VA-fade mean-reversion targets exact POC — do NOT shield
                # away from balance or the exit fires before price rotates
                return raw_tp
            if direction == "SHORT" and raw_tp < entry:
                return raw_tp

        candidates: list[float] = []

        # Collect structural targets in the right direction
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
            raw_tp = valid[0][1]
            # Spec §11 shield applies to trend structural targets (NPOC, prior
            # POC, VAH/VAL) but NOT to VA-fade mean-reversion POC exits —
            # those target the exact balance level, and shielding would cause
            # a premature exit before price rotates to POC.
            if is_va_fade and ctx.poc and abs(raw_tp - ctx.poc) < tick:
                return raw_tp
            return SignalBuilder._shield_tp(raw_tp, entry, direction, tick)

        return fallback_tp

    # NOTE: no ``size`` method here — position sizing lives in
    # ``quant.execution.risk.SessionRisk.position_size`` (the single sizing
    # authority); the module-level ``clamp_quantity`` applies the ceiling at
    # the engine's order-submission step. A second fixed-fractional formula
    # in this class was removed because it duplicated that authority with a
    # different clamp and risk source (architectural review finding).
