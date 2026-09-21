"""Value-Area fade signal (tier-2 hierarchy): VAL reclaim LONG / VAH rejection SHORT.

Fabio Model 2 (failed auction -> reclaim -> POC): price that probes beyond the
value area but fails to hold (closes back INSIDE the VA) is a failed auction;
the trade fades back toward the POC. Price still outside the VA is a trend, not
a fade, so no signal is returned until the reclaim close is in hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from quant.decision.context import DecisionContext


@dataclass(frozen=True)
class VAFadeSignal:
    direction: str           # "LONG" | "SHORT"
    entry: float
    sl: float
    tp: float                # target = POC
    rr: float
    reason: str


def detect_va_fade(ctx: DecisionContext) -> VAFadeSignal | None:
    """LONG: probe below VAL rejected, price CLOSES back inside VA with buyers.
       SHORT: probe above VAH rejected, price CLOSES back inside VA with sellers.
       Target is always the POC. Returns None while price is still outside VA."""
    if not ctx or not ctx.bar:
        return None

    poc = ctx.poc
    val = ctx.val
    vah = ctx.vah
    step = ctx.tick_size

    if not poc or not val or not vah or not step:
        return None

    close = float(ctx.bar.close)
    cvd = float(ctx.cvd_slope)
    inside_va = val <= close <= vah

    # A complete VA_FADE evidence packet from the analyzer certifies the failed
    # auction even if the session-extreme tracker has not recorded the probe.
    ev = getattr(ctx, "setup_evidence", None)
    ev_ok_long = bool(
        ev is not None
        and getattr(ev, "setup_type", "") == "VA_FADE"
        and getattr(ev, "direction", "") == "LONG"
        and getattr(ev, "is_complete", lambda: False)()
    )
    ev_ok_short = bool(
        ev is not None
        and getattr(ev, "setup_type", "") == "VA_FADE"
        and getattr(ev, "direction", "") == "SHORT"
        and getattr(ev, "is_complete", lambda: False)()
    )

    # Probe beyond the VA edge: prefer the tracked session extreme, fall back to
    # the current bar's wick (a single-bar failed auction).
    session_low = getattr(ctx, "session_extreme_low", 0.0) or 0.0
    session_high = getattr(ctx, "session_extreme_high", 0.0) or 0.0
    bar_low = float(ctx.bar.low) if hasattr(ctx.bar, "low") else 0.0
    bar_high = float(ctx.bar.high) if hasattr(ctx.bar, "high") else 0.0
    probe_low = session_low if session_low > 0 else (bar_low if bar_low < val else 0.0)
    probe_high = session_high if session_high > 0 else (bar_high if bar_high > vah else 0.0)
    failed_below = (probe_low > 0 and probe_low < val) or ev_ok_long
    failed_above = (probe_high > 0 and probe_high > vah) or ev_ok_short

    # LuxAlgo Value Area Reversion Signals (VARS) — an independent reclaim
    # confirmation that substitutes for CVD agreement.
    vars_res = ctx.vars_result or {}
    vars_bull = (
        isinstance(vars_res, dict) and vars_res.get("bullishReclaim")
    ) or getattr(vars_res, "bullish_reclaim", False)
    vars_bear = (
        isinstance(vars_res, dict) and vars_res.get("bearishReclaim")
    ) or getattr(vars_res, "bearish_reclaim", False)

    # LONG: probe below VAL was rejected, price closed back inside, buyers in control
    if inside_va and close < poc and failed_below and (cvd > 0 or vars_bull):
        entry = close
        # Fabio failed-breakout rule: stop beyond the full probe extreme, not just current bar wick
        stop_ref = probe_low if probe_low > 0 else bar_low
        sl = min(entry - step, stop_ref - step) if stop_ref < entry else entry - step
        if sl >= entry:
            sl = entry - step
        tp = poc
        risk = entry - sl
        rr = (tp - entry) / risk if risk > 0 else 0.0
        reason = "VARS Bullish Reclaim" if vars_bull else "VAL reclaim: failed probe below VA, buyer order flow"
        return VAFadeSignal("LONG", entry, sl, tp, rr, reason)

    # SHORT: probe above VAH was rejected, price closed back inside, sellers in control
    if inside_va and close > poc and failed_above and (cvd < 0 or vars_bear):
        entry = close
        # Fabio failed-breakout rule: stop beyond the full probe extreme, not just current bar wick
        stop_ref = probe_high if probe_high > 0 else bar_high
        sl = max(entry + step, stop_ref + step) if stop_ref > entry else entry + step
        if sl <= entry:
            sl = entry + step
        tp = poc
        risk = sl - entry
        rr = (entry - tp) / risk if risk > 0 else 0.0
        reason = "VARS Bearish Reclaim" if vars_bear else "VAH rejection: failed probe above VA, seller order flow"
        return VAFadeSignal("SHORT", entry, sl, tp, rr, reason)
    return None


def detect_gap_fill_fade(ctx: DecisionContext) -> VAFadeSignal | None:
    """Gap-fill mean-reversion: price fills an overnight/session-opening gap and
    re-accepts inside the prior value area.

    Parallel to detect_va_fade (failed auction → reclaim → POC) but for the
    overnight gap: the gap itself is the "probe", and price filling it back
    is the "failed auction". The trade fades toward the gap-POC, which acts
    as a magnet for the fill.

    Conditions:
    1. A gap was detected (gap_profile_poc > 0).
    2. Price has moved to fill the gap (gap is no longer open — current price
       has crossed back through the gap zone).
    3. Price is inside the prior value area (re-acceptance).
    4. Direction: gap was UP (open above prior close) → now filling down →
       LONG targeting gap-POC. Gap was DOWN → now filling up → SHORT.
    """
    if not ctx or not ctx.bar:
        return None

    gap_poc = getattr(ctx, "gap_profile_poc", 0.0) or 0.0
    gap_vah = getattr(ctx, "gap_profile_vah", 0.0) or 0.0
    gap_val = getattr(ctx, "gap_profile_val", 0.0) or 0.0

    # Condition 1: a gap must have been detected
    if gap_poc <= 0 or gap_vah <= 0 or gap_val <= 0:
        return None

    poc = ctx.poc
    val = ctx.val
    vah = ctx.vah
    step = ctx.tick_size

    if not poc or not val or not vah or not step:
        return None

    close = float(ctx.bar.close)
    cvd = float(ctx.cvd_slope)

    # Condition 3: price must be inside the prior value area (re-acceptance)
    inside_va = val <= close <= vah
    if not inside_va:
        return None

    # Condition 2: gap is being filled. The gap zone is [gap_val, gap_vah].
    # For an UP gap (gap_vah > gap_val, open was above prior close):
    #   - Gap fills when price drops back below gap_vah (into the gap zone)
    #   - Strong fill: price drops below gap_poc or even gap_val
    # For a DOWN gap:
    #   - Gap fills when price rises back above gap_val
    #   - Strong fill: price rises above gap_poc or even gap_vah
    gap_range = gap_vah - gap_val
    if gap_range <= 0:
        return None

    # Determine gap direction from the gap zone position relative to current VA
    gap_above_va = gap_val >= vah  # UP gap: gap zone is above the VA
    gap_below_va = gap_vah <= val  # DOWN gap: gap zone is below the VA

    # LuxAlgo VARS reclaim confirmation (substitutes for CVD agreement)
    vars_res = ctx.vars_result or {}
    vars_bull = (
        isinstance(vars_res, dict) and vars_res.get("bullishReclaim")
    ) or getattr(vars_res, "bullish_reclaim", False)
    vars_bear = (
        isinstance(vars_res, dict) and vars_res.get("bearishReclaim")
    ) or getattr(vars_res, "bearish_reclaim", False)

    entry = close

    # UP gap filling down → LONG (buy the fill, target gap-POC)
    # Price must have dropped back into/below the gap zone
    if gap_above_va and close <= gap_vah and close < poc:
        filled = (gap_vah - close) / gap_range  # how much of gap is filled
        if filled >= 0.3 and (cvd > 0 or vars_bull):  # meaningful fill + flow confirm
            sl = gap_val - step  # stop below the gap zone floor
            if sl >= entry:
                sl = entry - step
            tp = gap_poc  # target the gap magnet
            risk = entry - sl
            rr = (tp - entry) / risk if risk > 0 else 0.0
            return VAFadeSignal(
                "LONG", entry, sl, tp, rr,
                f"Gap-fill LONG: UP gap {filled:.0%} filled, target gap-POC {gap_poc:.2f}",
            )

    # DOWN gap filling up → SHORT (sell the fill, target gap-POC)
    # Price must have risen back into/above the gap zone
    if gap_below_va and close >= gap_val and close > poc:
        filled = (close - gap_val) / gap_range  # how much of gap is filled
        if filled >= 0.3 and (cvd < 0 or vars_bear):  # meaningful fill + flow confirm
            sl = gap_vah + step  # stop above the gap zone ceiling
            if sl <= entry:
                sl = entry + step
            tp = gap_poc  # target the gap magnet
            risk = sl - entry
            rr = (entry - tp) / risk if risk > 0 else 0.0
            return VAFadeSignal(
                "SHORT", entry, sl, tp, rr,
                f"Gap-fill SHORT: DOWN gap {filled:.0%} filled, target gap-POC {gap_poc:.2f}",
            )

    return None
