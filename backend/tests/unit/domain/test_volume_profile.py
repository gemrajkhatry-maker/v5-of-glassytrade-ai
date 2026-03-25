"""Tests for VolumeProfileComputer — independent, isolated tests."""

import pytest

from app.domain.services.volume_profile import (
    VolumeProfileSnapshot,
    build_snapshot,
    compute_bucket_index,
    compute_poc,
    compute_value_area,
    create_profile,
)
from app.domain.trading.models.value_objects import OHLC, VolumeProfileLevel


def _make_candle(time: str, o: float, h: float, l: float, c: float, v: float) -> OHLC:
    return OHLC.create(time=time, open=o, high=h, low=l, close=c, volume=v)


class TestBucketIndex:
    def test_basic(self):
        idx = compute_bucket_index(price=105.0, price_min=100.0, bucket_size=10.0)
        assert idx == 0  # (105 - 100) / 10 = 0.5 → floor = 0

    def test_second_bucket(self):
        idx = compute_bucket_index(price=115.0, price_min=100.0, bucket_size=10.0)
        assert idx == 1

    def test_exact_boundary(self):
        idx = compute_bucket_index(price=120.0, price_min=100.0, bucket_size=10.0)
        assert idx == 2


class TestCreateProfile:
    def test_empty_data(self):
        assert create_profile([]) == []

    def test_single_candle(self):
        data = [_make_candle("09:15", 100, 110, 90, 105, 1000)]
        profile = create_profile(data, buckets=20)
        total = sum(p.volume for p in profile)
        assert total == pytest.approx(1000, rel=0.01)

    def test_volume_distributed_across_range(self):
        data = [_make_candle("09:15", 100, 200, 100, 150, 1000)]
        profile = create_profile(data, buckets=10)
        total = sum(p.volume for p in profile)
        assert total == pytest.approx(1000, rel=0.01)
        # Volume should span multiple buckets (100 to 200 range)
        non_zero = sum(1 for p in profile if p.volume > 0)
        assert non_zero > 1

    def test_multiple_candles(self):
        data = [
            _make_candle("09:15", 100, 110, 95, 105, 500),
            _make_candle("09:20", 105, 115, 100, 110, 700),
        ]
        profile = create_profile(data, buckets=20)
        total = sum(p.volume for p in profile)
        assert total == pytest.approx(1200, rel=0.01)


class TestComputePOC:
    def test_single_bucket(self):
        profile = [
            VolumeProfileLevel(price=100, volume=100),
            VolumeProfileLevel(price=101, volume=500),  # POC
            VolumeProfileLevel(price=102, volume=200),
        ]
        poc_price, poc_idx = compute_poc(profile)
        assert poc_price == 101
        assert poc_idx == 1

    def test_tie_breaks_with_vwap(self):
        profile = [
            VolumeProfileLevel(price=100, volume=500),
            VolumeProfileLevel(price=101, volume=200),
            VolumeProfileLevel(price=102, volume=500),  # tie with bucket 0
        ]
        # VWAP closer to 102 → should pick bucket 2
        poc_price, poc_idx = compute_poc(profile, vwap_ref=102.0)
        assert poc_price == 102

    def test_empty_profile(self):
        poc_price, poc_idx = compute_poc([])
        assert poc_price == 0.0
        assert poc_idx == 0


class TestComputeValueArea:
    def test_full_area(self):
        # 10 buckets with equal volume → VA should span all
        profile = [VolumeProfileLevel(price=float(i), volume=100) for i in range(10)]
        vah, val = compute_value_area(profile, poc_index=5, value_area_pct=0.70)
        assert vah > val
        # 70% of volume from a 10-bucket equal profile should span most
        assert vah > 5.0  # POC at index 5

    def test_single_poc_dominates(self):
        profile = [
            VolumeProfileLevel(price=100, volume=10),
            VolumeProfileLevel(price=101, volume=1000),  # POC
            VolumeProfileLevel(price=102, volume=10),
        ]
        vah, val = compute_value_area(profile, poc_index=1, value_area_pct=0.70)
        # POC alone has ~98% of volume, so VAH/VAL should be very tight
        assert vah > val

    def test_empty_profile(self):
        vah, val = compute_value_area([], poc_index=0)
        assert vah == 0.0
        assert val == 0.0


class TestBuildSnapshot:
    def test_empty_profile(self):
        snap = build_snapshot([])
        assert snap.poc == 0.0
        assert snap.total_volume == 0.0

    def test_valid_profile(self):
        profile = [
            VolumeProfileLevel(price=100, volume=100),
            VolumeProfileLevel(price=101, volume=500),
            VolumeProfileLevel(price=102, volume=200),
        ]
        snap = build_snapshot(profile)
        assert snap.poc == 101
        assert snap.total_volume == pytest.approx(800)
        assert snap.vah > snap.val


class TestVolumeProfileIntegration:
    """End-to-end: OHLC → profile → POC/VAH/VAL snapshot."""

    def test_nifty_like_profile(self):
        data = []
        for i in range(20):
            base = 24000 + i * 5
            data.append(
                _make_candle(
                    f"09:{15 + i:02d}",
                    o=base,
                    h=base + 30,
                    l=base - 10,
                    c=base + 15,
                    v=1000 + i * 100,
                )
            )
        profile = create_profile(data, buckets=50)
        snap = build_snapshot(profile)

        assert snap.poc > 0
        assert snap.vah > snap.poc
        assert snap.val < snap.poc
        assert snap.total_volume > 0
