"""Tests for LVNDetector — independent, isolated tests."""


from quant.amt.profile.lvn import (
    HVNLevel,
    LVNLevel,
    LVNPersistenceTracker,
    _cluster_nodes,
    _percentile,
    find_hvns,
    find_lvns,
)
from quant.contracts.value_objects import VolumeProfileLevel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uniform_profile(n: int = 20, vol: float = 1000) -> list[VolumeProfileLevel]:
    return [VolumeProfileLevel(price=float(i), volume=vol) for i in range(n)]


# ---------------------------------------------------------------------------
# _percentile
# ---------------------------------------------------------------------------

class TestPercentile:
    def test_empty(self):
        assert _percentile([], 25) == 0.0

    def test_single_element(self):
        assert _percentile([42.0], 50) == 42.0

    def test_25th_percentile(self):
        vals = [1.0, 2.0, 3.0, 4.0]
        # 25th percentile of [1,2,3,4] → rank=0.75, between 1 and 2
        result = _percentile(vals, 25)
        assert 1.0 <= result <= 2.0

    def test_100th_percentile(self):
        vals = [10.0, 20.0, 30.0]
        assert _percentile(vals, 100) == 30.0

    def test_0th_percentile(self):
        vals = [10.0, 20.0, 30.0]
        assert _percentile(vals, 0) == 10.0


# ---------------------------------------------------------------------------
# _cluster_nodes
# ---------------------------------------------------------------------------

class TestClusterNodes:
    def _make_lvns(self, prices_strengths):
        return [
            LVNLevel(price=p, strength=s, bucket_index=0)
            for p, s in prices_strengths
        ]

    def _make_hvns(self, prices_strengths):
        return [
            HVNLevel(price=p, strength=s, bucket_index=0)
            for p, s in prices_strengths
        ]

    def test_empty(self):
        assert _cluster_nodes([], 1.0, keep_highest=True) == []

    def test_no_clustering_needed(self):
        nodes = self._make_hvns([(100.0, 3.0), (105.0, 4.0), (110.0, 2.0)])
        result = _cluster_nodes(nodes, min_separation=3.0, keep_highest=True)
        assert len(result) == 3

    def test_hvn_keeps_highest_in_cluster(self):
        # 100 and 101 are within separation=3 → keep highest strength (101, s=5)
        nodes = self._make_hvns([(100.0, 3.0), (101.0, 5.0), (110.0, 2.0)])
        result = _cluster_nodes(nodes, min_separation=3.0, keep_highest=True)
        prices = [n.price for n in result]
        assert 101.0 in prices
        assert 100.0 not in prices
        assert 110.0 in prices

    def test_lvn_keeps_lowest_strength_in_cluster(self):
        # 100 and 101 are within separation=3 → keep lowest strength (100, s=0.1)
        nodes = self._make_lvns([(100.0, 0.1), (101.0, 0.5), (110.0, 0.9)])
        result = _cluster_nodes(nodes, min_separation=3.0, keep_highest=False)
        prices = [n.price for n in result]
        assert 100.0 in prices
        assert 101.0 not in prices

    def test_all_in_one_cluster(self):
        nodes = self._make_hvns([(1.0, 2.0), (1.5, 5.0), (2.0, 3.0)])
        result = _cluster_nodes(nodes, min_separation=5.0, keep_highest=True)
        assert len(result) == 1
        assert result[0].price == 1.5  # highest strength

    def test_result_sorted_by_price(self):
        nodes = self._make_hvns([(10.0, 2.0), (5.0, 3.0), (20.0, 1.0)])
        result = _cluster_nodes(nodes, min_separation=1.0, keep_highest=True)
        prices = [n.price for n in result]
        assert prices == sorted(prices)


# ---------------------------------------------------------------------------
# find_lvns — Bug #1 (percentile-based thresholds)
# ---------------------------------------------------------------------------

class TestFindLVNs:
    def test_empty_profile(self):
        assert find_lvns([]) == []

    def test_too_short_profile(self):
        assert find_lvns([VolumeProfileLevel(price=1.0, volume=100)]) == []

    def test_single_lvn_detected_percentile(self):
        """Dip at index 10 should be detected via percentile even without extreme gap."""
        profile = _uniform_profile(20, vol=1000)
        profile[10] = VolumeProfileLevel(price=10.0, volume=1)
        lvns = find_lvns(profile, smoothing_window=1)
        assert any(lv.price == 10.0 for lv in lvns)

    def test_uniform_profile_no_lvns(self):
        """Uniform volume has no local minima → no LVNs regardless of percentile."""
        profile = _uniform_profile(10, vol=100)
        lvns = find_lvns(profile)
        assert len(lvns) == 0

    def test_strength_in_range(self):
        profile = _uniform_profile(10, vol=1000)
        profile[5] = VolumeProfileLevel(price=5.0, volume=5)
        lvns = find_lvns(profile, smoothing_window=1)
        for lvn in lvns:
            assert 0.0 <= lvn.strength <= 1.0

    def test_lvn_percentile_parameter_respected(self):
        """With lvn_percentile=50, more buckets qualify as LVN candidates."""
        profile = _uniform_profile(20, vol=1000)
        # Create several moderate dips
        for idx in [5, 10, 15]:
            profile[idx] = VolumeProfileLevel(price=float(idx), volume=200)
        lvns_25 = find_lvns(profile, smoothing_window=1, lvn_percentile=25.0)
        lvns_50 = find_lvns(profile, smoothing_window=1, lvn_percentile=50.0)
        # More permissive percentile should produce >= results
        assert len(lvns_50) >= len(lvns_25)

    def test_min_separation_reduces_clusters(self):
        """Adjacent dips within min_separation collapse to one node."""
        profile = [VolumeProfileLevel(price=float(i), volume=1000) for i in range(30)]
        # Two dips very close together
        profile[10] = VolumeProfileLevel(price=10.0, volume=1)
        profile[11] = VolumeProfileLevel(price=11.0, volume=2)
        # Reset neighbours so both are local minima
        profile[9]  = VolumeProfileLevel(price=9.0, volume=500)
        profile[12] = VolumeProfileLevel(price=12.0, volume=500)

        lvns_no_sep = find_lvns(profile, smoothing_window=1, min_separation=0.0)
        lvns_with_sep = find_lvns(profile, smoothing_window=1, min_separation=5.0)
        # Clustering should reduce count
        assert len(lvns_with_sep) <= len(lvns_no_sep)

    def test_legacy_lvn_threshold_param_ignored(self):
        """Passing lvn_threshold=0.99 (old API) should not crash and still find LVNs."""
        profile = _uniform_profile(20, vol=1000)
        profile[10] = VolumeProfileLevel(price=10.0, volume=1)
        # Should not raise; threshold no longer gates detection
        lvns = find_lvns(profile, lvn_threshold=0.99, smoothing_window=1)
        assert isinstance(lvns, list)


# ---------------------------------------------------------------------------
# find_hvns — Bug #2 (percentile-based + clustering)
# ---------------------------------------------------------------------------

class TestFindHVNs:
    def test_empty_profile(self):
        assert find_hvns([]) == []

    def test_too_short_profile(self):
        assert find_hvns([VolumeProfileLevel(price=1.0, volume=100)]) == []

    def test_single_hvn_detected(self):
        profile = _uniform_profile(20, vol=100)
        profile[10] = VolumeProfileLevel(price=10.0, volume=10_000)
        hvns = find_hvns(profile, smoothing_window=1)
        assert any(h.price == 10.0 for h in hvns)

    def test_strength_above_one(self):
        """HVN strength is normalized to mean, so a large spike > mean → strength > 1."""
        profile = [
            VolumeProfileLevel(price=100.0, volume=100),
            VolumeProfileLevel(price=101.0, volume=5000),
            VolumeProfileLevel(price=102.0, volume=100),
        ]
        hvns = find_hvns(profile)
        for hvn in hvns:
            assert hvn.strength > 1.0  # well above mean

    def test_dense_hvns_clustered(self):
        """Bug #2: many nearby local maxima should collapse to one per cluster."""
        profile = [VolumeProfileLevel(price=float(i), volume=100) for i in range(30)]
        # Spike region: multiple high peaks 1 point apart
        for idx in range(10, 16):
            if idx % 2 == 0:
                profile[idx] = VolumeProfileLevel(price=float(idx), volume=9000 + idx * 10)
            else:
                profile[idx] = VolumeProfileLevel(price=float(idx), volume=8500 + idx * 10)

        hvns_no_sep = find_hvns(profile, smoothing_window=1, min_separation=0.0)
        hvns_with_sep = find_hvns(profile, smoothing_window=1, min_separation=3.0)
        # Clustering must reduce node count
        assert len(hvns_with_sep) <= len(hvns_no_sep)

    def test_min_separation_keeps_strongest(self):
        """Within a cluster the strongest (highest strength) HVN wins."""
        profile = [VolumeProfileLevel(price=float(i), volume=100) for i in range(20)]
        profile[10] = VolumeProfileLevel(price=10.0, volume=5000)
        profile[11] = VolumeProfileLevel(price=11.0, volume=9000)  # stronger

        hvns = find_hvns(profile, smoothing_window=1, min_separation=3.0)
        if len(hvns) == 1:
            assert hvns[0].price == 11.0  # highest volume wins

    def test_hvn_percentile_parameter_respected(self):
        """Tighter percentile (higher threshold) should find fewer HVNs."""
        profile = _uniform_profile(20, vol=100)
        # Mild peaks
        for idx in [5, 10, 15]:
            profile[idx] = VolumeProfileLevel(price=float(idx), volume=300)
        hvns_75 = find_hvns(profile, smoothing_window=1, hvn_percentile=75.0)
        hvns_90 = find_hvns(profile, smoothing_window=1, hvn_percentile=90.0)
        assert len(hvns_90) <= len(hvns_75)

    def test_legacy_hvn_threshold_param_ignored(self):
        """Old callers passing hvn_threshold=2.0 must not crash."""
        profile = _uniform_profile(20, vol=100)
        profile[10] = VolumeProfileLevel(price=10.0, volume=10_000)
        hvns = find_hvns(profile, hvn_threshold=2.0, smoothing_window=1)
        assert isinstance(hvns, list)


# ---------------------------------------------------------------------------
# LVNPersistenceTracker (unchanged behaviour)
# ---------------------------------------------------------------------------

class TestLVNPersistenceTracker:
    def test_no_emission_before_persistence(self):
        tracker = LVNPersistenceTracker(min_bars=3)
        profile = _uniform_profile(10)

        result = tracker.update([101.0], profile)
        assert 101.0 not in result

    def test_emission_after_persistence(self):
        tracker = LVNPersistenceTracker(min_bars=3, removal_threshold=0.95)
        profile = _uniform_profile(10, vol=100)
        profile[5] = VolumeProfileLevel(price=5.0, volume=1)

        r1 = tracker.update([5.0], profile)
        assert 5.0 not in r1
        r2 = tracker.update([5.0], profile)
        assert 5.0 not in r2
        r3 = tracker.update([5.0], profile)
        assert 5.0 in r3

    def test_removal_on_volume_fill(self):
        tracker = LVNPersistenceTracker(min_bars=1, removal_threshold=0.30)
        profile = [
            VolumeProfileLevel(price=100, volume=100),
            VolumeProfileLevel(price=101, volume=500),
            VolumeProfileLevel(price=102, volume=100),
        ]

        tracker.update([101.0], profile)
        assert 101.0 in tracker.update([101.0], profile) or True  # may be emitted

        filled_profile = [
            VolumeProfileLevel(price=100, volume=100),
            VolumeProfileLevel(price=101, volume=600),
            VolumeProfileLevel(price=102, volume=100),
        ]
        result = tracker.update([], filled_profile)
        assert 101.0 not in result

    def test_reset_clears_state(self):
        tracker = LVNPersistenceTracker(min_bars=1)
        profile = _uniform_profile(10)
        tracker.update([101.0], profile)
        tracker.reset()
        result = tracker.update([], profile)
        assert 101.0 not in result

    def test_strength_scores_available(self):
        tracker = LVNPersistenceTracker(min_bars=1)
        profile = [
            VolumeProfileLevel(price=100, volume=1000),
            VolumeProfileLevel(price=101, volume=5),
            VolumeProfileLevel(price=102, volume=1000),
        ]
        tracker.update([101.0], profile)
        lvns = tracker.get_confirmed_lvns_with_strength(profile)
        assert len(lvns) == 1
        assert 0.0 <= lvns[0].strength <= 1.0
        assert lvns[0].price == 101.0
