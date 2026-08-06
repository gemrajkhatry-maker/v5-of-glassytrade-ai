"""WS adapter — maps StateProjector output to the frontend WS snapshot shape.

Pure mapper: StateProjector.ViewState -> the existing WS snapshot dict the
frontend already consumes (``_symbol, portfolio, amt, auction, quantDecision,
genAIAnalysis, overseerAction, overseerReason, agentDecision, riskState, tick,
ltp, oi, depth``). No I/O, no backend imports.
"""

from __future__ import annotations


def view_state_to_ws(vs) -> dict:
    """Map StateProjector.ViewState -> the existing WS snapshot shape."""
    return {
        "_symbol": vs.symbol,
        "portfolio": vs.portfolio or {},
        "amt": vs.amt,
        "auction": vs.auction,
        "quantDecision": vs.quant_decision,
        "genAIAnalysis": vs.gen_ai,
        "overseerAction": vs.overseer_action,
        "overseerReason": vs.overseer_reason,
        "agentDecision": vs.agent_decision,
        "riskState": vs.risk_state,
        "tick": vs.tick,
        "ltp": vs.ltp,
        "oi": vs.oi,
        "depth": vs.depth or {},
    }
