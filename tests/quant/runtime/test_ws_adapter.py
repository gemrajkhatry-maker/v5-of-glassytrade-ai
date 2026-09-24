import asyncio
import threading

from quant.bars import Bar
from quant.brokers.multiplexed_feed import MultiplexedMarketFeed
from quant.decision.decision_service import QuantDecision
from quant.decision.signal_builder import Signal
from quant.event_store import EventStore
from quant.events import (
    AmtUpdated,
    BarClosed,
    DecisionProduced,
    RiskUpdated,
)
from quant.execution.risk import RiskState
from quant.state import project_state
from quant.state_machine import EngineState
from quant.ws_adapter import view_state_to_ws

WS_KEYS = {
    "_symbol", "portfolio", "amt", "quantDecision",
    "agentDecision", "riskState", "tick", "ltp", "oi", "depth",
}


def _sig():
    return Signal(type="LONG", reason="All 5 gates passed", entry=100.0,
                  sl=99.0, tp=102.0, rr=2.0, model_label="Triple-A", symbol="S",
                  timestamp="t1")


def _view_state_with_everything():
    """Build a ViewState with all fields populated via fold + overrides."""
    store = EventStore()
    store.append(BarClosed(symbol="S", time="t1",
                           bar=Bar(time="t1", open=100, high=101, low=99,
                                   close=100, volume=100)))
    store.append(AmtUpdated(symbol="S", time="t1", amt={"poc": 100.0, "marketState": "IMBALANCED"}))
    store.append(DecisionProduced(symbol="S", time="t1",
                                  decision=QuantDecision(True, _sig(), "Triple-A",
                                                         "AGGRESSION", ())))
    store.append(RiskUpdated(symbol="S", time="t1",
                             risk=RiskState(daily_pnl=-50.0,
                                            consecutive_losses=2, halted=True,
                                            halt_reason="daily loss limit reached",
                                            risk_per_trade_pct=0.01,
                                            base_risk_pct=0.0031,
                                            effective_base_risk_pct=0.0025,
                                            max_daily_loss_pct=0.017,
                                            max_consecutive_losses=4,
                                            effective_hmp_tier="MOMENTUM")))
    from quant.state import _decision_to_view
    vs = project_state(store.fold())
    # Extract latest values from the event trace (engine does this inline)
    amt = None
    qd = None
    for e in store.get_all():
        if isinstance(e, AmtUpdated):
            amt = e.amt
        elif isinstance(e, DecisionProduced):
            qd = _decision_to_view(e.decision)
    from dataclasses import replace
    return replace(vs, amt=amt, quant_decision=qd)


def test_feed_close_cancels_pending_stream():
    started = threading.Event()
    closed = threading.Event()

    class _FailingStream:
        def stream_full(self, symbols):
            async def _generator():
                started.set()
                try:
                    await asyncio.sleep(60)
                finally:
                    closed.set()
                yield {}

            return _generator()

    feed = MultiplexedMarketFeed(_FailingStream())
    try:
        feed.set_symbols(["NIFTY"])
        assert started.wait(timeout=2.0)
        feed.close()
        assert feed._thread is None
        assert closed.is_set()
    finally:
        feed.close()


def test_ws_snapshot_has_all_frontend_keys():
    ws = view_state_to_ws(_view_state_with_everything())
    assert set(ws) == WS_KEYS
    assert len(ws) == 10


def test_agent_decision_passthrough_only():
    """agentDecision comes from AgentDecisionProduced only — never invented
    from quantDecision gate reasons (that lied on the AI thesis card)."""
    ws = view_state_to_ws(_view_state_with_everything())
    assert ws["agentDecision"] is None


def test_agent_decision_from_advisor_event():
    vs = _view_state_with_everything()
    from dataclasses import replace
    vs = replace(vs, agent_decision={
        "direction": "FLAT", "action": "FLAT", "setup": "NO_EDGE",
        "confidence": "Medium", "rationale": "mid-value near POC",
        "source": "AMT_RULE",
    })
    ws = view_state_to_ws(vs)
    ad = ws["agentDecision"]
    assert ad["direction"] == "FLAT"
    assert ad["source"] == "AMT_RULE"
    assert "POC" in ad["rationale"]


def test_ws_snapshot_fields():
    ws = view_state_to_ws(_view_state_with_everything())
    assert ws["_symbol"] == "S"
    assert ws["amt"] is not None and "marketState" in ws["amt"]
    assert ws["quantDecision"] is not None and "approved" in ws["quantDecision"]
    assert ws["quantDecision"]["approved"] is True
    assert ws["riskState"] is not None and "halted" in ws["riskState"]
    assert ws["riskState"]["effectiveBaseRiskPct"] == 0.0025
    assert ws["riskState"]["riskPerTradePct"] == 0.01
    assert ws["riskState"]["maxDailyLossPct"] == 0.017
    assert ws["riskState"]["maxConsecutiveLosses"] == 4
    assert ws["riskState"]["effectiveHmpTier"] == "MOMENTUM"


def test_ws_snapshot_passthrough_values():
    ws = view_state_to_ws(_view_state_with_everything())
    assert ws["amt"]["marketState"] == "IMBALANCED"
    assert ws["quantDecision"]["signal"]["type"] == "LONG"
    assert ws["riskState"]["consecutiveLosses"] == 2
    assert ws["ltp"] == 100.0


def test_ws_snapshot_empty_state_does_not_crash():
    vs = project_state(EngineState(symbol="S"))
    ws = view_state_to_ws(vs)
    assert set(ws) == WS_KEYS
    assert ws["_symbol"] == "S"
    assert ws["quantDecision"] is None
    # Empty fold still yields the default risk dict (EngineState carries a
    # default RiskState) — None was the old StateProjector cache default.
    assert ws["riskState"] == {
        "halted": False,
        "haltReason": "",
        "consecutiveLosses": 0,
        "dailyPnl": 0.0,
        "tradesToday": 0,
        "equity": 1_000_000.0,
        "driftAlert": False,
        "driftMessage": "",
        "baseRiskPct": 0.0025,
        "effectiveBaseRiskPct": 0.0025,
        "riskPerTradePct": 0.0025,
        "maxDailyLossPct": 0.02,
        "maxConsecutiveLosses": 3,
        "effectiveHmpTier": "CONSERVATIVE",
    }
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
