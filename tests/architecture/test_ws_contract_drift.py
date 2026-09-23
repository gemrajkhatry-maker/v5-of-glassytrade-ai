"""Architecture test: WebSocket snapshot schema drift guardian.

Ensures that view_state_to_ws produces the exact keys expected by the frontend
WebSocket receiver without drift.
"""

from quant.contracts.aggregates import INITIAL_CAPITAL
from quant.state import ViewState
from quant.ws_adapter import view_state_to_ws


def test_ws_snapshot_schema_keys():
    """Verify all expected top-level WS snapshot keys are present."""
    vs = ViewState(
        symbol="CRUDEOIL",
        tick=None,
        ltp=6200.0,
        oi=12000,
        amt={"poc": 6200.0, "valueAreaHigh": 6250.0, "valueAreaLow": 6150.0},
        quant_decision=None,
        agent_decision=None,
        risk_state={"halted": False, "haltReason": "", "dailyPnl": 0.0, "consecutiveLosses": 0},
        portfolio={
            "balance": float(INITIAL_CAPITAL),
            "equity": float(INITIAL_CAPITAL),
            "leverage": 10,
            "positions": [],
            "closedTrades": [],
        },
        depth={"bids": [], "asks": []},
    )

    snap = view_state_to_ws(vs)

    expected_top_keys = {
        "_symbol",
        "portfolio",
        "amt",
        "quantDecision",
        "agentDecision",
        "riskState",
        "tick",
        "ltp",
        "oi",
        "depth",
    }
    assert set(snap.keys()) == expected_top_keys, f"WS snapshot keys drift: {set(snap.keys())} != {expected_top_keys}"

    expected_portfolio_keys = {
        "balance",
        "equity",
        "leverage",
        "positions",
        "closedTrades",
    }
    assert set(snap["portfolio"].keys()) == expected_portfolio_keys, (
        f"Portfolio keys drift: {set(snap['portfolio'].keys())} != {expected_portfolio_keys}"
    )
