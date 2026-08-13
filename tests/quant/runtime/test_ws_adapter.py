from quant.absorption import Absorption
from quant.auction_state import AuctionState
from quant.bars import Bar
from quant.decision.decision_service import QuantDecision
from quant.decision.signal_builder import Signal
from quant.events import (
    AuctionUpdated,
    BarClosed,
    DecisionProduced,
    RiskUpdated,
)
from quant.execution.risk import RiskState
from quant.location import LocationState
from quant.order_flow import OrderFlowState
from quant.state import StateProjector
from quant.volume_profile import VolumeProfile
from quant.vwap import VWAPState
from quant.ws_adapter import view_state_to_ws

WS_KEYS = {
    "_symbol", "portfolio", "amt", "auction", "quantDecision",
    "agentDecision", "riskState", "tick", "ltp", "oi", "depth",
}


def _auction():
    return AuctionState(
        time="t", close=100.0,
        volume_profile=VolumeProfile(levels=(), poc=100, vah=102, val=98,
                                     step=1, total_volume=100),
        vwap=VWAPState(value=100, upper_1=101, lower_1=99, upper_2=102,
                       lower_2=98, std=1, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=0, cvd_slope=0.0,
                                  cvd_divergence="NONE", aggressive_prints=()),
        absorption=Absorption(0, 100.5, 500, "BUY", 0.6, 0),
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True,
                               zone="INSIDE_VA", nearest_level=100,
                               distance_to_level=0),
        triple_a_phase="AGGRESSION", triple_a_signal="LONG",
    )


def _sig():
    return Signal(type="LONG", reason="All 5 gates passed", entry=100.0,
                  sl=99.0, tp=102.0, rr=2.0, confidence=0.8, symbol="S",
                  timestamp="t1")


def _projector():
    p = StateProjector()
    p.on_event(BarClosed(symbol="S", time="t1",
                         bar=Bar(time="t1", open=100, high=101, low=99,
                                 close=100, volume=100)))
    p.on_event(AuctionUpdated(symbol="S", time="t1", auction=_auction()))
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
    direction/probability/rationale mirror the signal, no LLM involved."""
    ws = view_state_to_ws(_projector().snapshot("S"))
    ad = ws["agentDecision"]
    assert ad["direction"] == "LONG"
    assert ad["probability"] == 0.8
    assert ad["rationale"] == "Triple-A"


def test_ws_snapshot_fields():
    ws = view_state_to_ws(_projector().snapshot("S"))
    assert ws["_symbol"] == "S"
    assert ws["auction"] is not None and "tripleAPhase" in ws["auction"]
    assert ws["quantDecision"] is not None and "approved" in ws["quantDecision"]
    assert ws["quantDecision"]["approved"] is True
    assert ws["riskState"] is not None and "halted" in ws["riskState"]


def test_ws_snapshot_passthrough_values():
    ws = view_state_to_ws(_projector().snapshot("S"))
    assert ws["auction"]["tripleAPhase"] == "AGGRESSION"
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
