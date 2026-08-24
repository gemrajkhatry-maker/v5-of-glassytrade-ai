# tests/quant/test_location.py
import pytest

from quant.bars import Bar
from quant.location import LocationBuilder

def _bars():
    return [Bar(time=f"t{i}", open=100, high=105, low=95, close=100, volume=100)
            for i in range(8)]

def test_ib_from_first_n_bars():
    lb = LocationBuilder(ib_bars=2)
    for b in _bars():
        lb.update(b)
    # first 2 bars high=105 low=95
    st = lb.snapshot(None, 100)
    assert st.ib_high == 105 and st.ib_low == 95 and st.ib_complete is True

def test_zone_relative_to_va():
    from quant.volume_profile import VolumeProfile
    from quant.volume_profile import VolumeProfileLevel
    vp = VolumeProfile(
        levels=(VolumeProfileLevel(price=100, volume=100),
                VolumeProfileLevel(price=101, volume=100),
                VolumeProfileLevel(price=102, volume=100)),
        poc=101, vah=102, val=100, step=1, total_volume=300)
    lb = LocationBuilder()
    for b in _bars():
        lb.update(b)
    assert lb.snapshot(vp, 103.0).zone == "ABOVE_VA"
    assert lb.snapshot(vp, 99.0).zone == "BELOW_VA"
    assert lb.snapshot(vp, 101.0).zone == "INSIDE_VA"

def test_nearest_level():
    from quant.volume_profile import VolumeProfile
    from quant.volume_profile import VolumeProfileLevel
    vp = VolumeProfile(
        levels=(VolumeProfileLevel(price=100, volume=100),
                VolumeProfileLevel(price=101, volume=100),
                VolumeProfileLevel(price=102, volume=100)),
        poc=101, vah=102, val=100, step=1, total_volume=300)
    lb = LocationBuilder()
    for b in _bars():
        lb.update(b)
    st = lb.snapshot(vp, 102.5)
    assert st.nearest_level == 102  # vah
    assert st.distance_to_level == pytest.approx(0.5)
