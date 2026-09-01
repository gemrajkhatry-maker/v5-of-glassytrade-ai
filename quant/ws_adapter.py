"""WS adapter — maps EngineState (via EventStore.fold()) to the frontend WS snapshot shape.

Pure mapper: EngineState -> ViewState -> the existing WS snapshot dict the
frontend already consumes (``_symbol, portfolio, amt, quantDecision,
agentDecision, riskState, tick, ltp, oi, depth``). No I/O, no backend imports.

``agentDecision`` is the LLMAdvisor / AMT_RULE narrative only. It is NOT
projected from ``quantDecision`` — that mixed gate reasons into the AI thesis
card on fast bars before the advisor fired.
"""

from __future__ import annotations

from quant.contracts.aggregates import INITIAL_CAPITAL
from quant.state import ViewState, project_state
from quant.state_machine import EngineState


def view_state_to_ws(vs: ViewState | EngineState) -> dict:
    """Map ViewState (or EngineState) -> the existing WS snapshot shape.

    Accepts either a ViewState (legacy) or an EngineState (new path from
    EventStore.fold()). Portfolio is ALWAYS the full contract shape
    (balance/equity/leverage + positions/closedTrades arrays).
    """
    if isinstance(vs, EngineState):
        vs = project_state(vs)
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
