"""WS adapter — maps StateProjector output to the frontend WS snapshot shape.

Pure mapper: StateProjector.ViewState -> the existing WS snapshot dict the
frontend already consumes (``_symbol, portfolio, amt, quantDecision,
agentDecision, riskState, tick, ltp, oi, depth``). No I/O, no backend imports.

``agentDecision`` is the LLMAdvisor / AMT_RULE narrative only. It is NOT
projected from ``quantDecision`` — that mixed gate reasons into the AI thesis
card on fast bars before the advisor fired.
"""

from __future__ import annotations

from quant.contracts.aggregates import INITIAL_CAPITAL


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
    # ponytail: explicit float conversion at WS edge for JSON serialization
    return {
        "_symbol": vs.symbol,
        "portfolio": {
            "balance": float(portfolio.get("balance", INITIAL_CAPITAL)),
            "equity": float(portfolio.get("equity", INITIAL_CAPITAL)),
            "leverage": portfolio.get("leverage", 10),
            "positions": portfolio.get("positions", []),
            "closedTrades": portfolio.get("closedTrades", []),
        },
        "amt": vs.amt,
        "quantDecision": vs.quant_decision,
        "agentDecision": vs.agent_decision,
        "riskState": vs.risk_state,
        "tick": vs.tick,
        "ltp": vs.ltp,
        "oi": vs.oi,
        "depth": vs.depth or {},
    }
