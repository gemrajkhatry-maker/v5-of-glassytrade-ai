"""Tests for VolumeProfileComputer — independent, isolated tests."""

import pytest

from quant.amt.profile.volume_profile import (
    build_snapshot,
    compute_bucket_index,
    compute_poc,
    compute_value_area,
    create_profile,
)
from quant.contracts.value_objects import OHLC, VolumeProfileLevel


def _make_candle(time: str, o: float, h: float, lo: float, c: float, v: float) -> OHLC:
    return OHLC.create(time=time, open=o, high=h, low=lo, close=c, volume=v)


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

    def test_partial_pair_not_underweighted(self):
        # POC at index 1 (near the bottom edge). Below it only ONE row exists
        # (index 0, dense vol 900); above there are TWO rows (indices 2,3,
        # ~455 each). Old sum-comparison: up_sum(910) >= down_sum(900) -> drift
        # UP first. Average-weighted must favor the single dense down row
        # (down_avg 900 >> up_avg 455), keeping VAH tighter.
        profile = [
            VolumeProfileLevel(price=90, volume=900),   # dense single below row
            VolumeProfileLevel(price=91, volume=1000),  # POC
            VolumeProfileLevel(price=92, volume=460),
            VolumeProfileLevel(price=93, volume=450),
        ]
        vah, val = compute_value_area(profile, poc_index=1, value_area_pct=0.70)
        # 70% of 2810 = 1967; POC(1000)+down(900)=1900 < 1967.
        # Down first (avg 900 > avg 455), then up adds the remaining pair -> VAH=93.5.
        assert vah >= 93.0
        assert val == 89.5

    def test_default_pct_from_config(self):
        # value_area_pct omitted -> falls back to constants.VALUE_AREA_PCT (0.682, spec §5.1)
        profile = [VolumeProfileLevel(price=float(i), volume=100) for i in range(10)]
        vah, val = compute_value_area(profile, poc_index=5)
        assert vah > val

    def test_sparse_far_tail_does_not_inflate_vah(self):
        """A sparse far-out tail (stale morning regime) must not drag VAH away
        from the dense cluster. Reproduces the live CRUDEOIL 7950 CALL case:
        premium collapsed from ~195 to ~102, so the profile has a dense cluster
        at 95-105 (POC) separated from a thin tail at 160+ by a zero-volume
        gap (the old premium band was never traded back through). The CME
        two-row method must stop at the gap, not ride across it to collect 70%."""
        profile = []
        # Dense current auction: buckets at integer prices 95..105
        for p in range(95, 106):
            vol = 100 if p in (101, 102, 103, 104, 105) else 30
            profile.append(VolumeProfileLevel(price=float(p), volume=vol))
        # Zero-volume gap 106..159 (nothing traded there — the collapse skipped it)
        for p in range(106, 160):
            profile.append(VolumeProfileLevel(price=float(p), volume=0))
        # Stale tail 160..199 with real but thin volume
        for p in range(160, 200):
            profile.append(VolumeProfileLevel(price=float(p), volume=10))

        # POC is 101..105 in the dense cluster
        poc_price, poc_idx = compute_poc(profile)
        assert 101 <= poc_price <= 105

        vah, val = compute_value_area(profile, poc_index=poc_idx, value_area_pct=0.70)
        # The VA must stay in the current auction cluster, NOT leap the gap to
        # the stale tail. Total volume 30*6 + 100*5 + 40*10 = 1080; 70% = 756
        # is fully satisfied by the 95-105 cluster alone.
        assert vah < 106.0
        assert vah > 105.0  # upper edge of the top cluster bin
        assert val < 96.0

    def test_soft_shell_reaches_value_area_pct(self):
        """Quiet-but-nonzero shell around a fat POC must still expand to 70%.

        Audit §1.7: a 1%-of-POC desert threshold froze coverage at ~45% when
        adjacent bins carried volume 4 (pair=8 < 0.01*POC).
        """
        profile = []
        for i in range(40):
            if i == 20:
                v = 1000.0
            elif abs(i - 20) <= 8:
                v = 4.0
            else:
                v = 50.0
            profile.append(VolumeProfileLevel(price=float(i), volume=v))
        total = sum(p.volume for p in profile)
        vah, val = compute_value_area(profile, poc_index=20, value_area_pct=0.70)
        cov = sum(p.volume for p in profile if val <= p.price <= vah) / total
        assert cov >= 0.70 - 1e-9
        assert vah > 20.5  # expanded beyond the POC bin


class TestIncrementalFlatPrice:
    def test_identical_ltp_conserves_volume_in_one_bucket(self):
        from quant.amt.profile.volume_profile import IncrementalVolumeProfile

        inc = IncrementalVolumeProfile(buckets=10, concentrated=False, tick_size=0.05)
        for i in range(5):
            c = OHLC.create(
                time=str(i), open=100.0, high=100.0, low=100.0, close=100.0,
                volume=100.0, vwap=100.0, taker_buy_volume=60.0, delta=20.0,
            )
            inc.update(c)
        levels = inc.get_profile()
        nonzero = [lv for lv in levels if lv.volume > 0]
        assert len(nonzero) == 1
        assert nonzero[0].volume == pytest.approx(500.0)
        assert nonzero[0].buy_volume == pytest.approx(300.0)
        assert nonzero[0].sell_volume == pytest.approx(200.0)


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
                    lo=base - 10,
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
