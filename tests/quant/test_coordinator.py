from quant.bars import Bar
from quant.coordinator import AuctionCoordinator


def _session_bars():
    out = []
    for i in range(30):
        close = 100 + i * 0.5
        out.append(Bar(time=f"t{i}", open=close - 0.5, high=close + 1, low=close - 1,
                       close=close, volume=100 + (i % 5) * 50,
                       buy_volume=60, sell_volume=40, delta=20))
    return out


def test_on_bar_close_returns_complete_state():
    c = AuctionCoordinator()
    trace = [c.on_bar_close(b) for b in _session_bars()]
    last = trace[-1]
    assert len(trace) == 30
    assert last.time == "t29"
    assert last.close > 0
    assert last.volume_profile.poc > 0
    assert last.vwap.value > 0
    assert isinstance(last.order_flow.cvd, float)
    assert last.location.ib_high > 0
    assert last.location.ib_low > 0
    assert last.location.ib_complete is True
    assert last.triple_a_phase in {"WAITING", "ABSORBING", "ACCUMULATING", "AGGRESSION"}
    for s in trace:
        assert s.vwap.value > 0


def test_determinism_same_input_same_output():
    c1 = AuctionCoordinator()
    trace1 = [c1.on_bar_close(b) for b in _session_bars()]
    c2 = AuctionCoordinator()
    trace2 = [c2.on_bar_close(b) for b in _session_bars()]
    assert trace1 == trace2


def _long_sequence():
    out = [Bar(time=f"t{i}", open=100, high=101, low=99, close=100, volume=100)
           for i in range(25)]
    out.append(Bar(time="t25", open=100, high=100.2, low=99.8, close=100,
                   volume=500, buy_volume=450, sell_volume=50))
    for i in range(26, 31):
        close = 100 + (i - 25) * 4
        out.append(Bar(time=f"t{i}", open=close - 0.5, high=close + 1, low=close - 1,
                       close=close, volume=100))
    return out


def test_triple_a_signal_flows_through():
    c = AuctionCoordinator()
    last = None
    for b in _long_sequence():
        last = c.on_bar_close(b)
    assert last.triple_a_phase == "ABSORBING"
    assert last.triple_a_signal is None
