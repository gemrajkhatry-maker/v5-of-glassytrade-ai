"""Parity: lvn moved module vs legacy shim."""

from quant.amt.profile.lvn import find_hvns as new_find_hvns
from quant.amt.profile.lvn import find_lvns as new_find_lvns
from quant.contracts.value_objects import VolumeProfileLevel
from tests.quant.parity import assert_parity


def _uniform(n: int, vol: float = 1000) -> list[VolumeProfileLevel]:
    return [VolumeProfileLevel(price=float(i), volume=vol) for i in range(n)]


def _bimodal() -> list[VolumeProfileLevel]:
    """Two dense clusters separated by a V-shaped valley (the classic LVN gap)."""
    profile = _uniform(24, vol=800)
    for i, v in {
        0: 2000, 1: 2400, 2: 2500, 3: 2400, 4: 2000, 5: 1800, 6: 1600, 7: 1400,
    }.items():
        profile[i] = VolumeProfileLevel(price=float(i), volume=v)
    for i, v in {8: 400, 9: 200, 10: 80, 11: 40, 12: 80, 13: 200, 14: 400, 15: 2500}.items():
        profile[i] = VolumeProfileLevel(price=float(i), volume=v)
    for i, v in {
        16: 2000, 17: 2400, 18: 2500, 19: 2400, 20: 2000, 21: 1800, 22: 1600, 23: 1400,
    }.items():
        profile[i] = VolumeProfileLevel(price=float(i), volume=v)
    return profile


def test_parity_find_lvns_uniform():
    new_find_lvns(_uniform(20, vol=1000))


def test_parity_find_lvns_single_dip():
    profile = _uniform(20, vol=1000)
    profile[10] = VolumeProfileLevel(price=10.0, volume=1)
    new_find_lvns(profile, smoothing_window=1)


def test_parity_find_lvns_bimodal():
    profile = _bimodal()
    new_find_lvns(profile)
    new_find_lvns(profile, smoothing_window=1, min_separation=3.0)


def test_parity_find_hvns_uniform():
    new_find_hvns(_uniform(20, vol=100))


def test_parity_find_hvns_spike():
    profile = _uniform(20, vol=100)
    profile[10] = VolumeProfileLevel(price=10.0, volume=10_000)
    new_find_hvns(profile, smoothing_window=1)


def test_parity_find_hvns_bimodal():
    profile = _bimodal()
    new_find_hvns(profile)
    new_find_hvns(profile, smoothing_window=1, min_separation=5.0)


def test_parity_bimodal_valley_found():
    lvns = new_find_lvns(_bimodal())
    prices = [l.price for l in lvns]
    assert any(8.0 <= p <= 15.0 for p in prices)
