from quantv2.absorption import AbsorptionTracker
from quantv2.types import Bar


def _baseline(n=20):
    return [Bar(time=f"a{i}", open=100.0, high=100.6, low=99.4, close=100.0, volume=10.0, delta=2.0) for i in range(n)]


def test_absorption_gate_and_cluster():
    t = AbsorptionTracker()
    bars = [Bar(time=f"a{i}", open=100.0, high=100.6, low=99.4, close=100.0, volume=10.0, delta=2.0) for i in range(20)]
    for b in bars:
        assert t.on_bar(b) is None
    # 1.5× volume (15+), range 1.2 ≤ 0.5×avg-range? avg range = 1.2 → need ≤0.6 → compressed high/low
    big = Bar(time="x", open=99.8, high=100.1, low=99.7, close=100.0, volume=20.0, delta=-14.0)  # 70% sellers at one side
    a = t.on_bar(big, book_one_sided=0.7)
    assert a is not None and a.vol_ratio >= 1.5 and a.range_ratio <= 0.5 and a.one_sided >= 0.60
    c = t.cluster()
    assert c is not None and c["count"] >= 1 and c["low"] <= c["high"]


def test_delta_proxy_without_book():
    t = AbsorptionTracker()
    for b in _baseline():
        assert t.on_bar(b) is None
    big = Bar(time="x", open=99.8, high=100.1, low=99.7, close=100.0, volume=20.0, delta=-14.0)
    a = t.on_bar(big)
    assert a is not None and abs(a.one_sided - 0.7) < 1e-9 and a.side == "SELL_ABSORBED"


def test_buy_side_absorbed():
    t = AbsorptionTracker()
    for b in _baseline():
        assert t.on_bar(b) is None
    big = Bar(time="x", open=99.8, high=100.1, low=99.7, close=100.0, volume=20.0, delta=14.0)
    a = t.on_bar(big, book_one_sided=0.7)
    assert a is not None and a.side == "BUY_ABSORBED"


def test_two_sided_flow_is_not_absorption():
    t = AbsorptionTracker()
    for b in _baseline():
        assert t.on_bar(b) is None
    two_sided = Bar(time="x", open=99.8, high=100.1, low=99.7, close=100.0, volume=20.0, delta=-3.0)
    assert t.on_bar(two_sided) is None
    assert t.on_bar(two_sided, book_one_sided=0.5) is None


def test_cluster_grows_within_three_ticks_and_resets_beyond():
    t = AbsorptionTracker()
    for b in _baseline():
        t.on_bar(b)
    a1 = t.on_bar(Bar(time="c1", open=99.8, high=100.1, low=99.7, close=100.0, volume=20.0, delta=-14.0), book_one_sided=0.7)
    assert t.cluster() == {"high": 100.1, "low": 99.7, "count": 1}
    a2 = t.on_bar(Bar(time="c2", open=100.0, high=100.3, low=99.9, close=100.1, volume=30.0, delta=-21.0), book_one_sided=0.7)
    c = t.cluster()
    assert c is not None and c["count"] == 2 and c["high"] == 100.3 and c["low"] == 99.7
    a3 = t.on_bar(Bar(time="c3", open=104.8, high=105.0, low=104.6, close=104.9, volume=45.0, delta=-31.5), book_one_sided=0.7)
    assert all(x is not None for x in (a1, a2, a3))
    c = t.cluster()
    assert c is not None and c["count"] == 1 and c["high"] == 105.0 and c["low"] == 104.6


def test_cluster_is_none_before_any_absorption():
    t = AbsorptionTracker()
    assert t.cluster() is None
