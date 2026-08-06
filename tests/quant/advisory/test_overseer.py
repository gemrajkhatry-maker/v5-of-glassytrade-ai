import time
from quant.advisory.chat import ChatClient
from quant.advisory.overseer import Overseer, OverseerAction
from quant.auction_state import AuctionState
from quant.vwap import VWAPState
from quant.volume_profile import VolumeProfile
from quant.order_flow import OrderFlowState
from quant.location import LocationState
from quant.decision.signal_builder import Signal
from quant.execution.order import Order, Position

class FakeClient:
    def __init__(self, response='{"action":"HOLD","rationale":"ok"}'):
        self.response = response; self.calls = 0
    def complete(self, messages, max_tokens=200):
        self.calls += 1
        return self.response

def _state():
    return AuctionState(time="t", close=100.0,
        volume_profile=VolumeProfile(levels=(), poc=100, vah=102, val=98, step=1, total_volume=100),
        vwap=VWAPState(value=100, upper_1=101, lower_1=99, upper_2=102, lower_2=98, std=1, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=0, cvd_slope=0, cvd_divergence="NONE", aggressive_prints=()),
        absorption=None,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True, zone="INSIDE_VA", nearest_level=100, distance_to_level=0),
        triple_a_phase="", triple_a_signal=None)

def _pos():
    sig = Signal(type="LONG", reason="r", entry=100, sl=99, tp=102, rr=2, confidence=.8, symbol="SYM", timestamp="t0")
    return Position(order=Order(sig, 10), open_price=100, open_time="t0", size=10)

def test_cooldown_blocks():
    o = Overseer(FakeClient(), cooldown_seconds=15.0)
    assert o.should_run(time.time(), running=False) is True
    assert o.should_run(time.time(), running=False) is False   # too soon
    assert o.should_run(time.time() - 16, running=False) is True

def test_evaluate_returns_action():
    fc = FakeClient()
    o = Overseer(fc, cooldown_seconds=0.0)
    a = o.evaluate(_state(), _pos())
    assert a is not None and a.action == "HOLD"
    assert fc.calls == 1

def test_bounded_queue_drops_busy():
    # emulate: running=True means busy; evaluate must return None without calling the client
    fc = FakeClient()
    o = Overseer(fc, cooldown_seconds=0.0, queue_size=2)
    a1 = o.evaluate(_state(), _pos())
    a2 = o.evaluate(_state(), _pos())
    a3 = o.evaluate(_state(), _pos())   # third is dropped
    assert fc.calls <= 2

def test_overseer_recovers_after_cooldown():
    fc = FakeClient()
    o = Overseer(fc, cooldown_seconds=0.05, queue_size=2)
    o.evaluate(_state(), _pos())
    time.sleep(0.06)
    o.evaluate(_state(), _pos())
    time.sleep(0.06)
    o.evaluate(_state(), _pos())
    assert fc.calls == 3
