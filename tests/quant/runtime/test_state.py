from quant.bars import Bar
from quant.decision.decision_service import QuantDecision
from quant.decision.signal_builder import Signal
from quant.events import (
    AmtUpdated,
    BarClosed,
    DecisionProduced,
    PositionClosed,
    PositionOpened,
    RiskUpdated,
)
from quant.execution.order import Fill, Order, Position
from quant.execution.risk import RiskState
from quant.state import StateProjector


def _position(symbol="S", time="t1", size=10.0, entry=100.0):
    sig = Signal(type="LONG", reason="All 5 gates passed", entry=entry, sl=entry - 1,
                 tp=entry + 2, rr=2.0, model_label="Triple-A", symbol=symbol, timestamp=time)
    return Position(order=Order(signal=sig, quantity=size),
                    open_price=entry, open_time=time, size=size)


def test_projector_folds_bar_and_amt():
    p = StateProjector()
    p.on_event(BarClosed(symbol="S", time="t1",
                         bar=Bar(time="t1", open=100, high=101, low=99, close=100, volume=100)))
    p.on_event(AmtUpdated(symbol="S", time="t1", amt={"poc": 100.0, "marketState": "BALANCED"}))
    v = p.snapshot("S")
    assert v.ltp == 100.0
    assert v.amt is not None and v.amt.get("marketState") == "BALANCED"


def test_projector_per_symbol_isolation():
    p = StateProjector()
    p.on_event(BarClosed(symbol="S1", time="t",
                         bar=Bar(time="t", open=1, high=2, low=0.5, close=1.5, volume=10)))
    p.on_event(BarClosed(symbol="S2", time="t",
                         bar=Bar(time="t", open=5, high=6, low=4, close=5.5, volume=10)))
    assert p.snapshot("S1").ltp == 1.5
    assert p.snapshot("S2").ltp == 5.5


def test_snapshot_defaults_empty_state():
    v = StateProjector().snapshot("S")
    assert v.symbol == "S"
    assert v.tick is None
    assert v.ltp is None
    assert v.oi is None
    assert v.quant_decision is None
    assert v.risk_state is None
    assert v.depth is None
    # Portfolio is always materialized as the full contract shape — the WS
    # layer and React reduce over balance/equity/positions unconditionally.
    assert v.portfolio == {
        "balance": 1_000_000.0,
        "equity": 1_000_000.0,
        "leverage": 10,
        "positions": [],
        "closedTrades": [],
    }
    assert v.amt is None


def test_bar_fold_sets_ohlc_tick():
    p = StateProjector()
    p.on_event(BarClosed(symbol="S", time="t1",
                         bar=Bar(time="t1", open=100, high=101, low=99, close=100.5,
                                 volume=100, buy_volume=60, sell_volume=40, delta=20)))
    v = p.snapshot("S")
    assert v.ltp == 100.5
    # Non-epoch bar times (test fixtures) pass through unchanged.
    assert v.tick == {
        "time": "t1",
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 100.0,
        "vwap": 0.0,
        "takerBuyVolume": 60.0,
        "delta": 20.0,
    }


def test_bar_tick_time_normalized_to_iso_for_epoch():
    """Live gateway emits unix-epoch strings; the WS contract requires ISO.

    ``new Date("1786095001")`` is NaN in the frontend, which silently drops
    live ticks from the chart. The serializer must emit the same ISO +05:30
    format the REST history endpoint uses so the chart can merge both.
    """
    p = StateProjector()
    p.on_event(BarClosed(symbol="S", time="1786095001",
                         bar=Bar(time="1786095001", open=100, high=101, low=99,
                                 close=100.5, volume=100)))
    tick = p.snapshot("S").tick
    assert tick["time"] == "2026-08-07T15:00:01+05:30"
    # Must be parseable by JS Date (round-trips to the same epoch).
    from datetime import datetime
    assert int(datetime.fromisoformat(tick["time"]).timestamp()) == 1786095001


def test_amt_fold():
    p = StateProjector()
    p.on_event(AmtUpdated(symbol="S", time="t1", amt={"poc": 100.0, "marketState": "IMBALANCED"}))
    assert p.snapshot("S").amt["marketState"] == "IMBALANCED"


def test_decision_fold():
    sig = Signal(type="LONG", reason="All 5 gates passed", entry=100.0, sl=99.0,
                 tp=102.0, rr=2.0, model_label="Triple-A", symbol="S", timestamp="t1")
    p = StateProjector()
    p.on_event(DecisionProduced(symbol="S", time="t1",
                                decision=QuantDecision(True, sig, "Triple-A", "AGGRESSION", (),
                                                       model_label="Triple-A")))
    qd = p.snapshot("S").quant_decision
    assert qd == {
        "approved": True,
        "reason": "Triple-A",
        "phase": "AGGRESSION",
        "blockReasons": [],
        "gateResults": [],
        "modelLabel": "Triple-A",
        "signal": {"type": "LONG", "entry": 100.0, "sl": 99.0, "tp": 102.0,
                   "rr": 2.0, "modelLabel": "Triple-A"},
    }


def test_decision_fold_no_signal():
    p = StateProjector()
    p.on_event(DecisionProduced(symbol="S", time="t1",
                                decision=QuantDecision(False, None, "NO_EDGE", "", ())))
    qd = p.snapshot("S").quant_decision
    assert qd["approved"] is False
    assert qd["reason"] == "NO_EDGE"
    assert qd["signal"] is None


def test_decision_fold_gate_results():
    from quant.decision.result import GateResult

    p = StateProjector()
    p.on_event(DecisionProduced(
        symbol="S", time="t1",
        decision=QuantDecision(
            False, None, "GATE_REJECTED", "ABSORBING",
             (GateResult(1, True, "session phase ok"),
              GateResult(2, True),
              GateResult(3, False, "No Triple-A edge")),
             block_reasons=("TRIPLE_A_EDGE: No Triple-A edge",),
        ),
    ))
    qd = p.snapshot("S").quant_decision
    assert qd["gateResults"] == [
        {"gate": 1, "name": "SESSION_PHASE", "passed": True, "reason": "session phase ok"},
        {"gate": 2, "name": "POSITION_COOLDOWN", "passed": True, "reason": ""},
        {"gate": 3, "name": "TRIPLE_A_EDGE", "passed": False, "reason": "No Triple-A edge"},
    ]
    assert qd["blockReasons"] == ["TRIPLE_A_EDGE: No Triple-A edge"]


def test_risk_fold():
    p = StateProjector()
    p.on_event(RiskUpdated(symbol="S", time="t1",
                           risk=RiskState(daily_pnl=-50.0, consecutive_losses=2,
                                          halted=True, halt_reason="daily loss limit reached",
                                          risk_per_trade_pct=0.01,
                                          trades_today=3, equity=950000.0)))
    assert p.snapshot("S").risk_state == {
        "halted": True,
        "haltReason": "daily loss limit reached",
        "consecutiveLosses": 2,
        "dailyPnl": -50.0,
        "tradesToday": 3,
        "equity": 950000.0,
        "driftAlert": False,
        "driftMessage": "",
    }


def test_quote_updates_ltp_oi_depth_per_tick():
    """Per-tick LTP/OI/depth refresh between bar closes (Phase E)."""
    from quant.brokers.gateway import Tick

    p = StateProjector()
    p.on_quote("S", Tick(time="1", price=105.0, volume=0, oi=42.0,
                         depth={"bids": [{"price": 104.5, "quantity": 10}],
                                "asks": [{"price": 105.5, "quantity": 8}]}))
    v = p.snapshot("S")
    assert v.ltp == 105.0
    assert v.oi == 42.0
    assert v.depth == {"bids": [{"price": 104.5, "quantity": 10}],
                       "asks": [{"price": 105.5, "quantity": 8}]}
    # Depth is sticky across ticks without depth; ltp/oi keep updating.
    p.on_quote("S", Tick(time="2", price=106.0, volume=0, oi=43.0))
    v2 = p.snapshot("S")
    assert v2.ltp == 106.0
    assert v2.oi == 43.0
    assert v2.depth == v.depth


def test_portfolio_open_then_close():
    p = StateProjector()
    pos = _position()
    p.on_event(PositionOpened(symbol="S", time="t1", position=pos))
    port = p.snapshot("S").portfolio
    assert port == {
        "balance": 1_000_000.0,
        "equity": 1_000_000.0,
        "leverage": 10,
        "positions": [{
            "id": pos._id, "symbol": "S", "side": "LONG", "source": "AMT",
            "entryPrice": 100.0, "size": 10.0, "stopLoss": 99.0, "takeProfit": 102.0,
            "pnl": 0.0, "entryTime": "t1", "status": "OPEN",
        }],
        "closedTrades": [],
    }
    p.on_event(PositionClosed(symbol="S", time="t2",
                              fill=Fill(position=pos, close_price=102.0,
                                        close_time="t2", reason="TP", pnl=20.0)))
    port = p.snapshot("S").portfolio
    assert port["positions"] == []
    assert port["closedTrades"] == [{
        "id": pos._id, "symbol": "S", "side": "LONG", "source": "AMT",
        "entryPrice": 100.0, "size": 10.0, "stopLoss": 99.0, "takeProfit": 102.0,
        "pnl": 20.0, "entryTime": "t1", "status": "CLOSED",
        "exitPrice": 102.0, "exitTime": "t2", "closeReason": "TP",
    }]
