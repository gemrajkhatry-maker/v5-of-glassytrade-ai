from quant.decision.signal_builder import Signal
from quant.execution.order import Order, Position
from quant.execution.exits import ExitEngine
from quant.auction_state import AuctionState
from quant.vwap import VWAPState
from quant.volume_profile import VolumeProfile
from quant.order_flow import OrderFlowState
from quant.location import LocationState

def _position(size=10, sl=99.0, tp=102.0, entry=100.0):
    sig = Signal(type="LONG", reason="r", entry=entry, sl=sl, tp=tp, rr=2.0,
                 confidence=0.8, symbol="SYM", timestamp="t0")
    return Position(order=Order(sig, abs(size)), open_price=entry, open_time="t0", size=size)

def _short_position(size=-10, sl=101.0, tp=98.0, entry=100.0):
    sig = Signal(type="SHORT", reason="r", entry=entry, sl=sl, tp=tp, rr=2.0,
                 confidence=0.8, symbol="SYM", timestamp="t0")
    return Position(order=Order(sig, abs(size)), open_price=entry, open_time="t0", size=size)

def _state(close, cvd_slope=0.0):
    return AuctionState(
        time="t", close=close,
        volume_profile=VolumeProfile(levels=(), poc=100, vah=102, val=98, step=1, total_volume=100),
        vwap=VWAPState(value=100, upper_1=101, lower_1=99, upper_2=102, lower_2=98, std=1, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=0, cvd_slope=cvd_slope, cvd_divergence="NONE", aggressive_prints=()),
        absorption=None,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True, zone="INSIDE_VA", nearest_level=100, distance_to_level=0),
        triple_a_phase="", triple_a_signal=None,
    )

def test_sl_hit():
    d = ExitEngine().evaluate(_position(), _state(close=99.0), bar_index=5)
    assert d.should_exit and d.reason == "SL" and d.close_price == 99.0

def test_tp_hit():
    d = ExitEngine().evaluate(_position(), _state(close=102.0), bar_index=5)
    assert d.should_exit and d.reason == "TP"

def test_time_stop():
    d = ExitEngine(time_stop_bars=10).evaluate(_position(), _state(close=100.5), bar_index=12)
    assert d.should_exit and d.reason == "TIME"

def test_cvd_kill_long():
    d = ExitEngine(cvd_kill_threshold=0.0).evaluate(_position(), _state(close=100.5, cvd_slope=-8.0), bar_index=5)
    assert d.should_exit and d.reason == "CVD_KILL"

def test_no_exit_in_range():
    d = ExitEngine(time_stop_bars=30).evaluate(_position(), _state(close=100.5), bar_index=5)
    assert not d.should_exit

def test_cvd_kill_requires_adverse_threshold():
    long_pos = _position(size=10)
    short_pos = _short_position()
    engine = ExitEngine(cvd_kill_threshold=1.0)
    d = engine.evaluate(long_pos, _state(close=100.5, cvd_slope=-0.001), bar_index=5)
    assert not d.should_exit
    d = engine.evaluate(long_pos, _state(close=100.5, cvd_slope=-2.0), bar_index=5)
    assert d.should_exit and d.reason == "CVD_KILL"
    d = engine.evaluate(long_pos, _state(close=100.5, cvd_slope=+2.0), bar_index=5)
    assert not d.should_exit
    d = engine.evaluate(short_pos, _state(close=100.5, cvd_slope=+0.001), bar_index=5)
    assert not d.should_exit
    d = engine.evaluate(short_pos, _state(close=100.5, cvd_slope=+2.0), bar_index=5)
    assert d.should_exit and d.reason == "CVD_KILL"
    d = engine.evaluate(short_pos, _state(close=100.5, cvd_slope=-2.0), bar_index=5)
    assert not d.should_exit

def test_cvd_kill_disabled_by_default():
    d = ExitEngine().evaluate(_position(), _state(close=100.5, cvd_slope=-8.0), bar_index=5)
    assert not d.should_exit

def test_intrabar_sl_hit_wins_over_tp():
    d = ExitEngine().evaluate(_position(), _state(close=101.0), bar_index=5, bar_low=98.0, bar_high=103.0)
    assert d.should_exit and d.reason == "SL" and d.close_price == 101.0

def test_intrabar_tp_when_no_sl_pierce():
    d = ExitEngine().evaluate(_position(), _state(close=101.0), bar_index=5, bar_low=99.5, bar_high=103.0)
    assert d.should_exit and d.reason == "TP"
