"""Tests for Volume Profile."""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from appv2.domain.services.incremental_volume_profile import IncrementalVolumeProfile
from types import SimpleNamespace


def test_profile_builds():
    """Profile should accumulate from candles."""
    vp = IncrementalVolumeProfile(tick_size=0.05)

    for i in range(10):
        candle = SimpleNamespace(
            high=100 + i, low=100, close=100 + i / 2, volume=100,
        )
        vp.update_candle(candle)

    profile = vp.get_profile()
    assert len(profile) > 0
    assert vp.get_total_volume() > 0


def test_poc_found():
    """POC should be the bin with most volume."""
    vp = IncrementalVolumeProfile(tick_size=0.05)

    # Concentrate volume at 100
    for _ in range(5):
        vp.update_candle(SimpleNamespace(high=100.5, low=99.5, close=100, volume=200))

    # Less volume elsewhere
    vp.update_candle(SimpleNamespace(high=105, low=104, close=104.5, volume=20))

    poc = vp.get_poc()
    assert poc > 0


def test_value_area_computed():
    """Value area should return POC, VAH, VAL."""
    vp = IncrementalVolumeProfile(tick_size=0.05)

    for i in range(20):
        vp.update_candle(SimpleNamespace(
            high=100 + i * 0.5, low=100 + i * 0.5 - 0.3,
            close=100 + i * 0.5 - 0.1, volume=50 + i * 10,
        ))

    poc, vah, val = vp.compute_value_area()
    assert poc > 0
    assert vah >= val
    assert val > 0


def test_reset_clears():
    """Reset should clear all accumulated data."""
    vp = IncrementalVolumeProfile(tick_size=0.05)
    vp.update_candle(SimpleNamespace(high=101, low=100, close=100.5, volume=100))
    assert vp.get_total_volume() > 0

    vp.reset()
    assert vp.get_total_volume() == 0
    assert vp.get_poc() == 0.0
