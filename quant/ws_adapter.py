"""WS adapter — maps StateProjector output to the frontend WS snapshot shape.

Pure mapper: StateProjector.ViewState -> the existing WS snapshot dict the
frontend already consumes (``_symbol, portfolio, amt, auction, quantDecision,
genAIAnalysis, overseerAction, overseerReason, agentDecision, riskState, tick,
ltp, oi, depth``). No I/O, no backend imports.
"""

from __future__ import annotations


def view_state_to_ws(vs) -> dict:
    """Map StateProjector.ViewState -> the existing WS snapshot shape.

    Portfolio is ALWAYS the full contract shape (balance/equity/leverage +
    positions/closedTrades arrays) — the frontend reduces over these fields
    unconditionally and treats a partial/empty object as a full replacement.
    """
    portfolio = vs.portfolio or {}
    # Defaults MUST mirror quant/state.py StateProjector._portfolio and the
    # frontend createInstrumentState (hooks/useServerTradingSystem.ts).
    # Paper account capital: ₹10 lakh (1M) — mirrors quant/state.py
    # StateProjector._portfolio and the frontend createInstrumentState.
    return {
        "_symbol": vs.symbol,
        "portfolio": {
            "balance": portfolio.get("balance", 1_000_000.0),
            "equity": portfolio.get("equity", 1_000_000.0),
            "leverage": portfolio.get("leverage", 10),
            "positions": portfolio.get("positions", []),
            "closedTrades": portfolio.get("closedTrades", []),
        },
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
