# tests/quant/runtime/test_tick_level_exits.py
import pytest
from quant.brokers.gateway import Tick
from quant.events import PositionClosed
from quant.decision.signal_builder import Signal
from quant.execution.exits import ExitEngine
from quant.execution.oms import PaperOMS
from quant.execution.risk import SessionRisk
from quant.position_manager import PositionManager
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


def _make_pm():
    oms = PaperOMS(lot_size=1.0)
    exits = ExitEngine()
    pm = PositionManager(
        oms=oms,
        exits=exits,
        risk=SessionRisk(starting_equity=1_000_000),
        emit_fn=lambda e: None,
        symbol="TEST",
        market="NSE",
        contract_expiry=None,
        tick_size=0.05,
    )
    return pm, oms


def test_tick_tp_touch_books_first_partial_not_full_close():
    """An intrabar touch of signal.tp on the tick path books half + arms BE
    (bar-path parity), instead of silently full-closing the plan."""
    pm, oms = _make_pm()
    sig = _make_signal(symbol="TEST", side="LONG", entry=100.0, sl=90.0, tp=120.0)
    open_position = oms.submit(sig, 4.0)
    assert open_position.size == 4

    out = pm.manage_tick_exit(open_position, tick_price=120.0, tick_time="12:00:00")

    assert out is not None                      # still alive
    assert out.size == 2                        # half booked
    assert pm._exits._tp_tier[open_position._id] == 1    # tier armed
    assert pm._exits._breakeven[open_position._id] == pytest.approx(100.0)


def test_tick_tp_second_touch_closes_remaining_runner():
    """After TP1 books the half, a second TP tag closes the runner (size→0)."""
    pm, oms = _make_pm()
    sig = _make_signal(symbol="TEST", side="LONG", entry=100.0, sl=90.0, tp=120.0)
    open_position = oms.submit(sig, 4.0)

    remaining = pm.manage_tick_exit(open_position, tick_price=120.0, tick_time="12:00:00")
    assert remaining is not None and remaining.size == 2

    out = pm.manage_tick_exit(remaining, tick_price=120.0, tick_time="12:00:01")
    assert out is None                           # runner closed
    assert pm._exits._tp_tier.get(open_position._id) is None  # state released
