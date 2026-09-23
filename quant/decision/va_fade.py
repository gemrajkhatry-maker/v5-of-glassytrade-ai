"""Value-Area fade signal (tier-2 hierarchy): VAL reclaim LONG / VAH rejection SHORT.

Fabio Model 2 (failed auction -> reclaim -> POC): price that probes beyond the
value area but fails to hold (closes back INSIDE the VA) is a failed auction;
the trade fades back toward the POC. Price still outside the VA is a trend, not
a fade, so no signal is returned until the reclaim close is in hand.
"""

from __future__ import annotations

from dataclasses import dataclass

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
