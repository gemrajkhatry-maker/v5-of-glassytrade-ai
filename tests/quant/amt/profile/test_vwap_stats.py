"""SessionVWAP recent_stats must publish raw statistical σ."""

import pytest

from quant.amt.profile.vwap import SessionVWAP
from quant.contracts.value_objects import FloatOHLC


def test_recent_stats_does_not_floor_tiny_std():
    """Audit §1.7: proportional clamp (max(1.0, 0.1%×vwap)) inflated tiny
    true σ into a fake statistical band."""
    # Nearly identical prices → true std ≪ 1.0
    data = [
        FloatOHLC(
            time=str(i), open=100.0, high=100.01, low=99.99, close=100.0,
            volume=100.0, vwap=100.0, taker_buy_volume=50.0, delta=0.0,
        )
        for i in range(20)
    ]
    _vwap, std = SessionVWAP.recent_stats(data)
    assert std < 1.0
    assert std < 100.0 * 0.001  # below the old 0.1% floor


def test_recent_stats_does_not_cap_wide_std():
    data = [
        FloatOHLC(
            time="0", open=100, high=100, low=100, close=100,
            volume=100, vwap=100, taker_buy_volume=50, delta=0,
        ),
        FloatOHLC(
            time="1", open=200, high=200, low=200, close=200,
            volume=100, vwap=200, taker_buy_volume=50, delta=0,
        ),
    ]
    vwap, std = SessionVWAP.recent_stats(data)
    # Two equal-weight points at 100 and 200 → std = 50; old cap was 3%×vwap≈4.5
    assert std == pytest.approx(50.0, rel=1e-3)
    assert std > vwap * 0.03
