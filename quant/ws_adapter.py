"""WS adapter — maps StateProjector output to the frontend WS snapshot shape.

Pure mapper: StateProjector.ViewState -> the existing WS snapshot dict the
frontend already consumes (``_symbol, portfolio, amt, quantDecision,
agentDecision, riskState, tick, ltp, oi, depth``). No I/O, no backend imports.

The LLM layer is gone, so the LLM-derived keys (``genAIAnalysis``,
``overseerAction``, ``overseerReason``) are not emitted; ``agentDecision`` is
projected from the deterministic ``quantDecision`` so the frontend's
sidebar sorting/filtering keeps working on engine output alone.
"""

from __future__ import annotations

from quant.contracts.aggregates import INITIAL_CAPITAL


def _agent_decision_from_quant(qd: dict | None) -> dict | None:
    """Project the deterministic decision into the frontend ``AgentDecision``
    contract (direction/modelLabel/regime/timing/rationale)."""
    if not qd:
        return None
    sig = qd.get("signal") or {}
    direction = str(sig.get("type") or "FLAT").upper()
    if direction not in ("LONG", "SHORT", "FLAT"):
        direction = "FLAT"
    return {
        "direction": direction,
        "modelLabel": str(sig.get("modelLabel") or qd.get("modelLabel") or ""),
        "regime": str(qd.get("phase") or ""),
        "timing": "",
        "sizeFraction": 0.0,
        "latencyUs": 0,
        "rationale": str(qd.get("reason") or ""),
    }


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
            "balance": portfolio.get("balance", float(INITIAL_CAPITAL)),
            "equity": portfolio.get("equity", float(INITIAL_CAPITAL)),
            "leverage": portfolio.get("leverage", 10),
            "positions": portfolio.get("positions", []),
            "closedTrades": portfolio.get("closedTrades", []),
        },
        "amt": vs.amt,
        "quantDecision": vs.quant_decision,
        "agentDecision": vs.agent_decision or _agent_decision_from_quant(vs.quant_decision),
        "riskState": vs.risk_state,
        "tick": vs.tick,
        "ltp": vs.ltp,
        "oi": vs.oi,
        "depth": vs.depth or {},
    }
