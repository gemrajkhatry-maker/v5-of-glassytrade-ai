"""Value-Area fade signal (tier-2 hierarchy): VAL bounce LONG / VAH rejection SHORT.

Per amt_docs: when price trades outside the value area against the mean-reversion
pull of VWAP and order flow, fade back toward the POC.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from quant.auction_state import AuctionState
from quant.decision.context import DecisionContext


@dataclass(frozen=True)
class VAFadeSignal:
    direction: str           # "LONG" | "SHORT"
    entry: float
    sl: float
    tp: float                # target = POC
    rr: float
    reason: str


def detect_va_fade(state: AuctionState, ctx: Optional[DecisionContext] = None) -> VAFadeSignal | None:
    """LONG: zone==BELOW_VA, CVD > 0, close < poc, target POC.
       SHORT: zone==ABOVE_VA, CVD < 0, close > poc, target POC."""
    vp = state.volume_profile
    poc = (ctx.poc if ctx and ctx.poc and ctx.poc > 0 else None) or vp.poc
    val = (ctx.val if ctx and ctx.val and ctx.val > 0 else None) or vp.val
    vah = (ctx.vah if ctx and ctx.vah and ctx.vah > 0 else None) or vp.vah
    step = vp.step if (vp and vp.step and vp.step > 0) else 0.0

    if not poc or not val or not vah or not step:
        return None

    close = float(state.close)
    cvd = float(state.order_flow.cvd)

    # LONG: price probed below VAL and buyers are in control (positive CVD)
    # Fabio: only fade back toward POC when order flow confirms the rejection
    if state.location.zone == "BELOW_VA" and cvd > 0 and close < poc:
        entry = close
        sl = entry - step
        tp = poc
        risk = entry - sl
        rr = (tp - entry) / risk if risk > 0 else 0.0
        return VAFadeSignal("LONG", entry, sl, tp, rr,
                            "VAL bounce: below VA, buyer order flow")

    # SHORT: price probed above VAH and sellers are in control (negative CVD)
    if state.location.zone == "ABOVE_VA" and cvd < 0 and close > poc:
        entry = close
        sl = entry + step
        tp = poc
        risk = sl - entry
        rr = (entry - tp) / risk if risk > 0 else 0.0
        return VAFadeSignal("SHORT", entry, sl, tp, rr,
                            "VAH rejection: above VA, seller order flow")
    return None
