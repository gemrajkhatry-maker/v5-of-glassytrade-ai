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
    """LONG: zone==BELOW_VA and close > vwap.value and cvd > 0, target POC.
       SHORT: zone==ABOVE_VA and close < vwap.value and cvd < 0, target POC."""
    vp = state.volume_profile
    if not vp.poc or not vp.val or not vp.vah or not vp.step:
        return None

    close = state.close
    if state.location.zone == "BELOW_VA" and close > state.vwap.value and state.order_flow.cvd > 0:
        entry = close
        sl = vp.val - vp.step
        tp = vp.poc
        rr = (tp - entry) / (entry - sl) if entry != sl else 0.0
        return VAFadeSignal("LONG", entry, sl, tp, rr,
                            "VAL bounce: below VA, above VWAP, buyer CVD")
    if state.location.zone == "ABOVE_VA" and close < state.vwap.value and state.order_flow.cvd < 0:
        entry = close
        sl = vp.vah + vp.step
        tp = vp.poc
        rr = (entry - tp) / (sl - entry) if sl != entry else 0.0
        return VAFadeSignal("SHORT", entry, sl, tp, rr,
                            "VAH rejection: above VA, below VWAP, seller CVD")
    return None
