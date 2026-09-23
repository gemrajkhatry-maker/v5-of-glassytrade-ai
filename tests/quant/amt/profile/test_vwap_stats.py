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


def test_decision_bands_floor_width_for_anti_climax():
    """Bands (used by Anti-Climax) must floor at 1.0 so quiet auctions do not
    veto every displacement; recent_stats keeps raw σ (audit §1.7)."""
    from quant.amt.profile.vwap import SessionVWAP
    data = [
        FloatOHLC(
            time=str(i), open=100.0, high=100.05, low=99.95, close=100.0,
            volume=100.0, vwap=100.0, taker_buy_volume=50.0, delta=0.0,
        )
        for i in range(40)
    ]
    _v, raw = SessionVWAP.recent_stats(data)
    assert raw < 1.0  # raw stays tiny
    sw = SessionVWAP()
    current = FloatOHLC(
        time="40", open=100.0, high=100.6, low=99.9, close=100.6,
        volume=100.0, vwap=100.0, taker_buy_volume=90.0, delta=80.0,
    )
    u1, _l1, u2, _l2, std_out, _dev = sw.bands(100.0, current, recent_data=data)
    # Decision bands use floored σ (≥1.0) so first displacement is inside ±2σ
    assert u2 >= 100.0 + 2.0 - 1e-9, f"upper_2={u2} not floored"
    # Reported σ remains raw
    assert std_out == pytest.approx(raw, rel=1e-6)
    # 100.6 must not be above a floored +2σ band
    assert 100.6 <= u2 + 1e-9
