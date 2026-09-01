"""Value-Area fade signal (tier-2 hierarchy): VAL bounce LONG / VAH rejection SHORT.

Per docs/amt: when price trades outside the value area against the mean-reversion
pull of VWAP and order flow, fade back toward the POC.
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
    """LONG: close < val, CVD > 0, close < poc, target POC.
       SHORT: close > vah, CVD < 0, close > poc, target POC."""
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

    zone = "INSIDE_VA"
    if close < val:
        zone = "BELOW_VA"
    elif close > vah:
        zone = "ABOVE_VA"

    # Check VARS reclaim signals (LuxAlgo Value Area Reversion Signals)
    vars_res = ctx.vars_result or {}
    vars_bull = (
        isinstance(vars_res, dict) and vars_res.get("bullishReclaim")
    ) or getattr(vars_res, "bullish_reclaim", False)
    vars_bear = (
        isinstance(vars_res, dict) and vars_res.get("bearishReclaim")
    ) or getattr(vars_res, "bearish_reclaim", False)

    # LONG: price probed below VAL and buyers are in control (positive CVD or VARS Bullish Reclaim)
    if (zone == "BELOW_VA" and cvd > 0 and close < poc) or (vars_bull and close < poc):
        entry = close
        probe_low = float(ctx.bar.low) if hasattr(ctx.bar, "low") else entry
        sl = min(entry - step, probe_low - step) if probe_low < entry else entry - step
        if sl >= entry:
            sl = entry - step
        tp = poc
        risk = entry - sl
        rr = (tp - entry) / risk if risk > 0 else 0.0
        reason = "VARS Bullish Reclaim" if vars_bull else "VAL bounce: below VA, buyer order flow"
        return VAFadeSignal("LONG", entry, sl, tp, rr, reason)

    # SHORT: price probed above VAH and sellers are in control (negative CVD or VARS Bearish Reclaim)
    if (zone == "ABOVE_VA" and cvd < 0 and close > poc) or (vars_bear and close > poc):
        entry = close
        probe_high = float(ctx.bar.high) if hasattr(ctx.bar, "high") else entry
        sl = max(entry + step, probe_high + step) if probe_high > entry else entry + step
        if sl <= entry:
            sl = entry + step
        tp = poc
        risk = sl - entry
        rr = (entry - tp) / risk if risk > 0 else 0.0
        reason = "VARS Bearish Reclaim" if vars_bear else "VAH rejection: above VA, seller order flow"
        return VAFadeSignal("SHORT", entry, sl, tp, rr, reason)
    return None
