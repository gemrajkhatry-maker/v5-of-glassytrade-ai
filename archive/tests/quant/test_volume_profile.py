# tests/quant/test_volume_profile.py
import pytest
from quant.bars import Bar
from quant.volume_profile import VALUE_AREA_PCT, VolumeProfileBuilder

def _bars():
    # 10 bars spanning 100..109, equal volume 100 each, close=mid
    return [Bar(time=f"t{i}", open=100+i, high=100+i+0.5, low=100+i-0.5,
                close=100+i, volume=100) for i in range(10)]

def test_volume_is_preserved():
    vb = VolumeProfileBuilder()
    for b in _bars():
        vb.update(b)
    vp = vb.snapshot()
    assert vp.total_volume == pytest.approx(1000)

def test_poc_is_max_volume_bucket():
    bars = _bars()
    bars[5] = Bar(time="t5", open=105, high=105.5, low=104.5, close=105, volume=1000)
    vb = VolumeProfileBuilder()
    for b in bars:
        vb.update(b)
    vp = vb.snapshot()
    assert vp.poc == max(vp.levels, key=lambda l: l.volume).price
    assert 104.5 <= vp.poc <= 105.5  # within the heavy bar's range

def test_value_area_captures_68_percent():
    assert VALUE_AREA_PCT == 0.68
    vb = VolumeProfileBuilder()
    for b in _bars():
        vb.update(b)
    vp = vb.snapshot()
    va_vol = sum(l.volume for l in vp.levels
                 if vp.val <= l.price <= vp.vah)
    assert va_vol >= 0.68 * vp.total_volume
    assert vp.vah > vp.val
