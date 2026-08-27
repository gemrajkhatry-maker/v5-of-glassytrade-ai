# tests/quant/runtime/test_tick_level_exits.py
import pytest
from quant.brokers.gateway import Tick
from quant.events import PositionClosed
from quant.decision.signal_builder import Signal
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway


def _make_signal(symbol="TEST", side="LONG", entry=100.0, sl=90.0, tp=120.0):
    return Signal(
        type=side,
        reason="Triple-A setup",
        entry=entry,
        sl=sl,
        tp=tp,
        rr=2.0,
        model_label="Triple-A",
        symbol=symbol,
        timestamp="1700000000",
    )


def test_tick_level_sl_breach_closes_position_immediately():
    """When a tick price crosses the stop loss level, position is closed immediately on tick."""
    ticks = [
        Tick(time="1700000000", price=100.0, volume=10, buy_volume=5, sell_volume=5),
        Tick(time="1700000010", price=89.0, volume=10, buy_volume=0, sell_volume=10),
    ]
    gw = SyntheticGateway(ticks)
    eng = QuantEngine(gw, "TEST", interval_seconds=300)
    
    sig = _make_signal(symbol="TEST", side="LONG", entry=100.0, sl=90.0, tp=120.0)
    eng._position = eng._oms.submit(sig, 1.0)
    eng._entry_bar_index = 0
    
    events = eng.run()
    
    closed_events = [e for e in events if isinstance(e, PositionClosed)]
    assert len(closed_events) == 1
    assert closed_events[0].time == "1700000010"
    assert closed_events[0].fill.reason == "SL"
    assert closed_events[0].fill.close_price == 89.0
    assert eng._position is None


def test_tick_level_tp_hit_closes_position_immediately():
    """When a tick price crosses the take profit level, position is closed immediately on tick."""
    ticks = [
        Tick(time="1700000000", price=100.0, volume=10, buy_volume=5, sell_volume=5),
        Tick(time="1700000010", price=121.0, volume=10, buy_volume=10, sell_volume=0),
    ]
    gw = SyntheticGateway(ticks)
    eng = QuantEngine(gw, "TEST", interval_seconds=300)
    
    sig = _make_signal(symbol="TEST", side="LONG", entry=100.0, sl=90.0, tp=120.0)
    eng._position = eng._oms.submit(sig, 1.0)
    eng._entry_bar_index = 0
    
    events = eng.run()
    
    closed_events = [e for e in events if isinstance(e, PositionClosed)]
    assert len(closed_events) == 1
    assert closed_events[0].time == "1700000010"
    assert closed_events[0].fill.reason == "TP"
    assert closed_events[0].fill.close_price == 121.0
    assert eng._position is None
