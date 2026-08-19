from quant.bars import Bar
from quant.decision.decision_service import QuantDecision
from quant.decision.signal_builder import Signal
from quant.events import (
    AmtUpdated,
    BarClosed,
    DecisionProduced,
    RiskUpdated,
)
from quant.execution.risk import RiskState
from quant.state import StateProjector
from quant.ws_adapter import view_state_to_ws

WS_KEYS = {
    "_symbol", "portfolio", "amt", "auction", "quantDecision",
    "agentDecision", "riskState", "tick", "ltp", "oi", "depth",
}


def _sig():
    return Signal(type="LONG", reason="All 5 gates passed", entry=100.0,
                  sl=99.0, tp=102.0, rr=2.0, model_label="Triple-A", symbol="S",
                  timestamp="t1")


def _projector():
    p = StateProjector()
    p.on_event(BarClosed(symbol="S", time="t1",
                         bar=Bar(time="t1", open=100, high=101, low=99,
                                 close=100, volume=100)))
    p.on_event(AmtUpdated(symbol="S", time="t1", amt={"poc": 100.0, "marketState": "IMBALANCED"}))
    p.on_event(DecisionProduced(symbol="S", time="t1",
                                decision=QuantDecision(True, _sig(), "Triple-A",
                                                       "AGGRESSION", ())))
    p.on_event(RiskUpdated(symbol="S", time="t1",
                           risk=RiskState(daily_pnl=-50.0,
                                          consecutive_losses=2, halted=True,
                                          halt_reason="daily loss limit reached",
                                          risk_per_trade_pct=0.01)))
    return p


def test_ws_snapshot_has_all_frontend_keys():
    ws = view_state_to_ws(_projector().snapshot("S"))
    assert set(ws) == WS_KEYS
    assert len(ws) == 11


def test_agent_decision_projected_from_quant_decision():
    """agentDecision is now derived from the deterministic quantDecision —
    direction/modelLabel/rationale mirror the signal, no LLM involved."""
    ws = view_state_to_ws(_projector().snapshot("S"))
    ad = ws["agentDecision"]
    assert ad["direction"] == "LONG"
    assert ad["modelLabel"] == "Triple-A"  # replaces the removed confidence/probability field
    assert ad["rationale"] == "Triple-A"


def test_ws_snapshot_fields():
    ws = view_state_to_ws(_projector().snapshot("S"))
    assert ws["_symbol"] == "S"
    assert ws["amt"] is not None and "marketState" in ws["amt"]
    assert ws["quantDecision"] is not None and "approved" in ws["quantDecision"]
    assert ws["quantDecision"]["approved"] is True
    assert ws["riskState"] is not None and "halted" in ws["riskState"]


def test_ws_snapshot_passthrough_values():
    ws = view_state_to_ws(_projector().snapshot("S"))
    assert ws["amt"]["marketState"] == "IMBALANCED"
    assert ws["quantDecision"]["signal"]["type"] == "LONG"
    assert ws["riskState"]["consecutiveLosses"] == 2
    assert ws["ltp"] == 100.0


def test_ws_snapshot_empty_state_does_not_crash():
    ws = view_state_to_ws(StateProjector().snapshot("S"))
    assert set(ws) == WS_KEYS
    assert ws["_symbol"] == "S"
    assert ws["auction"] is None
    assert ws["quantDecision"] is None
    assert ws["riskState"] is None
    # Portfolio is ALWAYS the full frontend contract shape (never `{}`) so
    # the React layer never reduces over undefined positions/closedTrades.
    assert ws["portfolio"] == {
        "balance": 1_000_000.0,
        "equity": 1_000_000.0,
        "leverage": 10,
        "positions": [],
        "closedTrades": [],
    }
    assert ws["depth"] == {}
