"""Parity: volume_profile moved module vs legacy shim."""

from quant.amt.profile.volume_profile import (
    compute_value_area as new_compute_value_area,
    create_profile as new_create_profile,
)
from quant.contracts.value_objects import OHLC, VolumeProfileLevel
from tests.quant.parity import assert_parity
from tests.quant.test_golden_file import _session_bars


def _candle(time: str, o: float, h: float, l: float, c: float, v: float) -> OHLC:
    return OHLC.create(time=time, open=o, high=h, low=l, close=c, volume=v)


# --- create_profile ----------------------------------------------------------


def test_parity_create_profile_empty():
    new_create_profile([])


def test_parity_create_profile_single_candle():
    data = [_candle("09:15", 100, 110, 90, 105, 1000)]
    new_create_profile(data, buckets=20)


def test_parity_create_profile_session_bars_auto_buckets():
    new_create_profile(_session_bars(), buckets=0)


def test_parity_create_profile_session_bars_explicit():
    new_create_profile(_session_bars(), buckets=120)


def test_parity_create_profile_concentrated_edge():
    data = [
        _candle("09:15", 100, 100, 100, 100, 100),
        _candle("09:16", 101, 102, 99, 101, 200),
        _candle("09:17", 101, 101, 101, 101, 300),
        _candle("09:18", 100, 100, 100, 100, 50),
    ]
    new_create_profile(data, buckets=25, concentrated=True)


def test_parity_create_profile_flat_range():
    data = [_candle("09:15", 100, 100, 100, 100, 500)]
    new_create_profile(data, buckets=20)


# --- compute_value_area ------------------------------------------------------


def test_parity_value_area_edge_poc_boundary_pair():
    """Boundary-pair regression: POC at index 1, single dense row below."""
    profile = [
        VolumeProfileLevel(price=90, volume=900),
        VolumeProfileLevel(price=91, volume=1000),
        VolumeProfileLevel(price=92, volume=460),
        VolumeProfileLevel(price=93, volume=450),
    ]
    new_compute_value_area(profile, poc_index=1, value_area_pct=0.70)


def test_parity_value_area_wide_profile():
    profile = [VolumeProfileLevel(price=float(i), volume=100) for i in range(20)]
    new_compute_value_area(profile, poc_index=10, value_area_pct=0.70)


def test_parity_value_area_default_pct():
    profile = [VolumeProfileLevel(price=float(i), volume=100) for i in range(10)]
    new_compute_value_area(profile, poc_index=5)


def test_parity_value_area_poc_at_top_edge():
    profile = [
        VolumeProfileLevel(price=100, volume=100),
        VolumeProfileLevel(price=101, volume=500),
        VolumeProfileLevel(price=102, volume=200),
    ]
    new_compute_value_area(profile, poc_index=2, value_area_pct=0.70)
