from quant.decision.signal_builder import Signal
from quant.execution.order import Order, Position
from quant.execution.exits import ExitEngine
from quant.auction_state import AuctionState
from quant.vwap import VWAPState
from quant.volume_profile import VolumeProfile
from quant.order_flow import OrderFlowState
from quant.location import LocationState


def _position(size=10, sl=99.0, tp=1000.0, entry=100.0):
    # tp far away so TP never fires in these tests; risk = 1.0 (1R at 101).
    sig = Signal(type="LONG", reason="r", entry=entry, sl=sl, tp=tp, rr=2.0,
                 model_label="Triple-A", symbol="SYM", timestamp="t0")
    return Position(order=Order(sig, abs(size)), open_price=entry, open_time="t0", size=size)


def _short_position(size=-10, sl=101.0, tp=0.0, entry=100.0):
    sig = Signal(type="SHORT", reason="r", entry=entry, sl=sl, tp=tp, rr=2.0,
                 model_label="Triple-A", symbol="SYM", timestamp="t0")
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


def test_trailing_activates_at_1r_long():
    # close=102 -> profit=2 >= risk=1. candidate = 102 - 0.20*2 = 101.60.
    # BE floor = entry = 100.0, candidate 101.60 > 100.0 -> no BE override.
    # Bar dips to 101.2 intrabar -> trail stop hit.
    eng = ExitEngine()
    d = eng.evaluate(
        _position(), _state(close=102.0), bar_index=5, bar_high=102.0, bar_low=101.2
    )
    assert d.should_exit and d.reason == "TRAIL"
    assert d.trail_stop == 102.0 - 0.20 * 2.0


def test_trailing_never_widens_long():
    eng = ExitEngine()
    pos = _position()
    # Bar 1: close=102 -> profit=2 -> stop = 102 - 0.20*2 = 101.60.
    d = eng.evaluate(pos, _state(close=102.0), bar_index=5, bar_high=102.0, bar_low=101.7)
    assert not d.should_exit
    assert eng._trail[id(pos)].stop == 101.60
    # Bar 2: price falls to 101.8 -> profit=1.8 -> candidate 101.44 < 101.60 ->
    # stop must NOT widen down; intrabar low of 101.59 hits the old stop.
    d = eng.evaluate(pos, _state(close=101.8), bar_index=6, bar_high=102.0, bar_low=101.59)
    assert d.should_exit and d.reason == "TRAIL"
    assert d.trail_stop == 101.60


def test_trailing_activates_at_1r_short():
    # short entry=100, sl=101, risk=1. close=98 -> profit=2.
    # candidate = 98 + 0.20*2 = 98.40 -> clamped min(98.40, sl=101) = 98.40.
    # BE floor = entry = 100.0, min(98.40, 100.0) = 98.40.
    # Bar rallies to 98.5 intrabar -> trail stop hit.
    eng = ExitEngine()
    d = eng.evaluate(
        _short_position(), _state(close=98.0), bar_index=5, bar_high=98.5, bar_low=98.0
    )
    assert d.should_exit and d.reason == "TRAIL"
    assert d.trail_stop == 98.0 + 0.20 * 2.0


def test_trailing_does_not_fire_before_1r():
    # close=100.5 -> profit=0.5 < risk=1.0 -> trailing inactive, no trail dict entry.
    eng = ExitEngine()
    pos = _position()
    d = eng.evaluate(pos, _state(close=100.5), bar_index=5, bar_high=100.5, bar_low=99.9)
    assert not d.should_exit
    assert id(pos) not in eng._trail
