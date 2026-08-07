from quant.absorption import Absorption
from quant.auction_state import AuctionState
from quant.bars import Bar
from quant.decision.decision_service import QuantDecision
from quant.decision.signal_builder import Signal
from quant.events import (
    AuctionUpdated,
    BarClosed,
    DecisionProduced,
    PositionClosed,
    PositionOpened,
    RiskUpdated,
)
from quant.execution.order import Fill, Order, Position
from quant.execution.risk import RiskState
from quant.location import LocationState
from quant.order_flow import OrderFlowState
from quant.state import StateProjector
from quant.volume_profile import VolumeProfile
from quant.vwap import VWAPState


def _state(triple_a_phase="", triple_a_signal=None, close=100.0,
           cvd_slope=0.0, absorption=None, upper_1=101.0, lower_1=99.0):
    return AuctionState(
        time="t", close=close,
        volume_profile=VolumeProfile(levels=(), poc=100, vah=102, val=98, step=1, total_volume=100),
        vwap=VWAPState(value=100, upper_1=upper_1, lower_1=lower_1,
                       upper_2=102, lower_2=98, std=1, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=0, cvd_slope=cvd_slope,
                                  cvd_divergence="NONE", aggressive_prints=()),
        absorption=absorption,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True,
                               zone="INSIDE_VA", nearest_level=100, distance_to_level=0),
        triple_a_phase=triple_a_phase, triple_a_signal=triple_a_signal,
    )


def _position(symbol="S", time="t1", size=10.0, entry=100.0):
    sig = Signal(type="LONG", reason="All 5 gates passed", entry=entry, sl=entry - 1,
                 tp=entry + 2, rr=2.0, confidence=0.8, symbol=symbol, timestamp=time)
    return Position(order=Order(signal=sig, quantity=size),
                    open_price=entry, open_time=time, size=size)


def test_projector_folds_bar_and_auction():
    p = StateProjector()
    p.on_event(BarClosed(symbol="S", time="t1",
                         bar=Bar(time="t1", open=100, high=101, low=99, close=100, volume=100)))
    p.on_event(AuctionUpdated(symbol="S", time="t1", auction=_state()))
    v = p.snapshot("S")
    assert v.ltp == 100.0
    assert v.auction is not None and "tripleAPhase" in v.auction


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
    assert v.auction is None
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
    assert v.gen_ai is None
    assert v.overseer_action == ""
    assert v.overseer_reason == ""
    assert v.agent_decision is None


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


def test_auction_keys_match_backend_serializer():
    p = StateProjector()
    p.on_event(AuctionUpdated(symbol="S", time="t1",
                              auction=_state(triple_a_phase="AGGRESSION",
                                             triple_a_signal="LONG",
                                             absorption=Absorption(0, 100.5, 500, "BUY", 0.6, 0))))
    a = p.snapshot("S").auction
    assert set(a) == {"time", "close", "volumeProfile", "vwap", "orderFlow",
                      "absorption", "location", "tripleAPhase", "tripleASignal"}
    assert set(a["volumeProfile"]) == {"poc", "vah", "val", "step", "totalVolume"}
    assert set(a["vwap"]) == {"value", "upper1", "lower1", "upper2", "lower2",
                              "std", "deviationSigmas"}
    assert set(a["orderFlow"]) == {"delta", "cvd", "cvdSlope", "cvdDivergence"}
    assert set(a["location"]) == {"ibHigh", "ibLow", "ibComplete", "zone",
                                  "nearestLevel", "distanceToLevel"}
    assert a["absorption"] == {"side": "BUY", "price": 100.5, "volume": 500.0,
                               "strength": 0.6, "barAge": 0}
    assert a["tripleAPhase"] == "AGGRESSION"
    assert a["tripleASignal"] == "LONG"


def test_auction_absorption_null_when_none():
    p = StateProjector()
    p.on_event(AuctionUpdated(symbol="S", time="t1", auction=_state()))
    assert p.snapshot("S").auction["absorption"] is None


def test_decision_fold():
    sig = Signal(type="LONG", reason="All 5 gates passed", entry=100.0, sl=99.0,
                 tp=102.0, rr=2.0, confidence=0.8, symbol="S", timestamp="t1")
    p = StateProjector()
    p.on_event(DecisionProduced(symbol="S", time="t1",
                                decision=QuantDecision(True, sig, "Triple-A", "AGGRESSION", ())))
    qd = p.snapshot("S").quant_decision
    assert qd == {
        "approved": True,
        "reason": "Triple-A",
        "phase": "AGGRESSION",
        "gateResults": [],
        "signal": {"type": "LONG", "entry": 100.0, "sl": 99.0, "tp": 102.0,
                   "rr": 2.0, "confidence": 0.8},
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
             GateResult(3, False, "probability below threshold", "0.42")),
        ),
    ))
    qd = p.snapshot("S").quant_decision
    assert qd["gateResults"] == [
        {"gate": 1, "passed": True, "reason": "session phase ok"},
        {"gate": 2, "passed": True, "reason": ""},
        {"gate": 3, "passed": False, "reason": "probability below threshold"},
    ]


def test_risk_fold():
    p = StateProjector()
    p.on_event(RiskUpdated(symbol="S", time="t1",
                           risk=RiskState(daily_pnl=-50.0, consecutive_losses=2,
                                          halted=True, halt_reason="daily loss limit reached",
                                          risk_per_trade_pct=0.01)))
    assert p.snapshot("S").risk_state == {
        "halted": True,
        "haltReason": "daily loss limit reached",
        "consecutiveLosses": 2,
        "dailyPnl": -50.0,
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
            "id": "t1", "symbol": "S", "side": "LONG", "source": "AMT",
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
        "id": "t1", "symbol": "S", "side": "LONG", "source": "AMT",
        "entryPrice": 100.0, "size": 10.0, "stopLoss": 99.0, "takeProfit": 102.0,
        "pnl": 20.0, "entryTime": "t1", "status": "CLOSED",
        "exitPrice": 102.0, "exitTime": "t2", "closeReason": "TP",
    }]
