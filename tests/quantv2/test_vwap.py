import math

from quantv2.types import Bar
from quantv2.vwap import AnchoredVWAP

BARS = tuple(
    Bar(time="t", open=c, high=c + 1, low=c - 1, close=c, volume=100.0)
    for c in (100.0, 102.0, 104.0)
)


def test_vwap_bands_and_climax():
    v = AnchoredVWAP()
    for bar in BARS:
        v.on_bar(bar)
    assert abs(v.vwap - 102.0) < 1e-9
    assert v.sigma1_up > v.vwap and v.sigma2_up > v.sigma1_up
    assert v.anti_climax(120.0) is True and v.anti_climax(102.0) is False


def test_sigma_and_bands_hand_computed():
    v = AnchoredVWAP()
    for bar in BARS:
        v.on_bar(bar)
    sigma = math.sqrt(8.0 / 3.0)
    assert abs(v.sigma - sigma) < 1e-9
    expected = (
        ("sigma1_up", 102.0 + sigma),
        ("sigma1_dn", 102.0 - sigma),
        ("sigma2_up", 102.0 + 2.0 * sigma),
        ("sigma2_dn", 102.0 - 2.0 * sigma),
    )
    for attr, band in expected:
        assert abs(getattr(v, attr) - band) < 1e-9


def test_reset_zero_volume_and_typical_override():
    v = AnchoredVWAP()
    v.on_bar(Bar(time="a", open=10.0, high=11.0, low=9.0, close=10.0, volume=0.0))
    assert v.vwap == 0.0 and v.anti_climax(1e9) is False
    v.on_bar(Bar(time="b", open=10.0, high=11.0, low=9.0, close=10.0, volume=3.0), typical_price=9.0)
    assert abs(v.vwap - 9.0) < 1e-12
    v.reset()
    assert v.vwap == 0.0 and v.sigma == 0.0
