import pytest

from quant.bars import Bar
from quant.order_flow import OrderFlowBuilder


def _bar(i, delta, vol=100):
    bv = max(0, (vol + delta) / 2)
    sv = vol - bv
    return Bar(time=f"t{i}", open=100, high=101, low=99, close=100,
               volume=vol, buy_volume=bv, sell_volume=sv, delta=delta)


def test_cvd_is_cumulative():
    of = OrderFlowBuilder()
    of.update(_bar(0, 10)); of.update(_bar(1, -4)); of.update(_bar(2, 7))
    assert of.snapshot().cvd == pytest.approx(13)


def test_delta_matches_bar():
    of = OrderFlowBuilder()
    of.update(_bar(0, 25))
    assert of.snapshot().delta == pytest.approx(25)


def test_slope_positive_for_rising_deltas():
    of = OrderFlowBuilder()
    for i, d in enumerate([1, 2, 3, 4, 5, 6]):
        of.update(_bar(i, d))
    assert of.snapshot().cvd_slope > 0


def test_bullish_divergence_when_cvd_up_price_down():
    of = OrderFlowBuilder()
    # cvd rising while closes fall -> bullish divergence
    for i in range(20):
        of.update(Bar(time=f"t{i}", open=100-i, high=101-i, low=99-i, close=100-i,
                      volume=100, buy_volume=60, sell_volume=40, delta=20))
    assert of.snapshot().cvd_divergence == "BULLISH"
