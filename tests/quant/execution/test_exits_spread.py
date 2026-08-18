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


def test_spread_blowout_exits_long():
    # 4-wide spread on a 100 close = 4% >= 3% default threshold.
    d = ExitEngine().evaluate(
        _position(), _state(close=100.5), bar_index=5, best_bid=98.5, best_ask=102.5
    )
    assert d.should_exit and d.reason == "SPREAD_BLOWOUT"
    assert d.close_price == 100.5  # mid of the book


def test_no_blowout_without_depth():
    d = ExitEngine().evaluate(
        _position(), _state(close=100.5), bar_index=5, best_bid=None, best_ask=None
    )
    assert not d.should_exit
    # One-sided depth also cannot blow out.
    d = ExitEngine().evaluate(
        _position(), _state(close=100.5), bar_index=5, best_bid=98.5, best_ask=None
    )
    assert not d.should_exit


def test_no_blowout_below_threshold():
    # 1-wide spread on a 100 close = 1% < 3% default threshold.
    d = ExitEngine().evaluate(
        _position(), _state(close=100.5), bar_index=5, best_bid=100.0, best_ask=101.0
    )
    assert not d.should_exit
