"""Tests for mlx_compute — MLX GPU-accelerated compute primitives."""

import math
import pytest
from quant.amt import compute as mc


class TestGaussianWeights:
    def test_sums_to_one(self):
        centers = [float(i) for i in range(100)]
        w = mc.gaussian_weights(centers, 50.0, 10.0)
        assert abs(sum(w) - 1.0) < 1e-5

    def test_peak_at_center(self):
        centers = [10.0, 20.0, 30.0, 40.0, 50.0]
        w = mc.gaussian_weights(centers, 30.0, 5.0)
        assert w[2] == max(w)  # center bucket has highest weight

    def test_empty_returns_uniform(self):
        assert mc.gaussian_weights([], 0.0, 1.0) == [1.0]

    def test_zero_sigma(self):
        w = mc.gaussian_weights([1.0, 2.0, 3.0], 2.0, 0.0)
        assert len(w) == 3
        assert abs(sum(w) - 1.0) < 1e-5


class TestLinregSlope:
    def test_perfect_line(self):
        # y = 2x + 1 → slope = 2
        ys = [1.0, 3.0, 5.0, 7.0, 9.0]
        assert abs(mc.linreg_slope(ys) - 2.0) < 1e-4

    def test_flat(self):
        assert mc.linreg_slope([5.0, 5.0, 5.0, 5.0]) == 0.0

    def test_single_value(self):
        assert mc.linreg_slope([42.0]) == 0.0


class TestATR:
    def test_simple(self):
        # 3 candles: ranges 10, 10 → ATR = 10
        highs = [110.0, 120.0, 130.0]
        lows = [100.0, 110.0, 120.0]
        closes = [105.0, 115.0, 125.0]
        result = mc.atr(highs, lows, closes, period=14)
        assert result > 0

    def test_single_candle(self):
        assert mc.atr([110.0], [100.0], [105.0]) == 10.0


class TestEMA:
    def test_constant(self):
        assert mc.ema([5.0, 5.0, 5.0], 3) == 5.0

    def test_trending(self):
        result = mc.ema([1.0, 2.0, 3.0, 4.0, 5.0], 3)
        assert result > 3.0  # should be above midpoint for uptrend

    def test_empty(self):
        assert mc.ema([], 5) == 0.0


class TestCandleOverlapPct:
    def test_full_overlap(self):
        # Same candle repeated → 100% overlap
        highs = [110.0] * 5
        lows = [100.0] * 5
        assert mc.candle_overlap_pct(highs, lows, 5) == pytest.approx(100.0)

    def test_no_overlap(self):
        # Non-overlapping candles
        highs = [10.0, 20.0, 30.0]
        lows = [0.0, 15.0, 25.0]
        result = mc.candle_overlap_pct(highs, lows, 3)
        assert result < 100.0


class TestWeightedMoments:
    def test_symmetric(self):
        prices = [1.0, 2.0, 3.0, 4.0, 5.0]
        volumes = [1.0, 2.0, 4.0, 2.0, 1.0]  # symmetric around 3
        skew, kurt, std = mc.weighted_moments(prices, volumes)
        assert abs(skew) < 0.1  # nearly zero skew
        assert std > 0

    def test_zero_volume(self):
        assert mc.weighted_moments([1.0], [0.0]) == (0.0, 0.0, 0.0)


class TestCountPeaks:
    def test_two_peaks(self):
        vols = [0, 0, 10, 0, 0, 0, 10, 0, 0]
        assert mc.count_peaks([float(v) for v in vols], 0.5) == 2

    def test_single_peak(self):
        vols = [1, 2, 5, 2, 1]
        assert mc.count_peaks([float(v) for v in vols], 0.5) == 1

    def test_short_list(self):
        assert mc.count_peaks([1.0, 2.0], 0.5) == 1  # < 5 elements


class TestAggressionSigma:
    def test_normal_volume(self):
        volumes = [100.0] * 20
        # Same as history → sigma ~0
        assert abs(mc.aggression_sigma(100.0, volumes, 20)) < 0.5

    def test_spike(self):
        volumes = [100.0] * 20
        # 10x spike → high sigma
        assert mc.aggression_sigma(1000.0, volumes, 20) > 2.0

    def test_insufficient_data(self):
        assert mc.aggression_sigma(100.0, [50.0] * 5, 20) == 0.0


class TestDivergenceDetect:
    def test_no_divergence(self):
        prices = list(range(20))  # monotonic up
        cvds = list(range(20))    # monotonic up
        dtype, z = mc.divergence_detect([float(p) for p in prices], [float(c) for c in cvds])
        assert dtype == "NONE"

    def test_bearish_divergence(self):
        # Price HH, CVD LH
        prices = [10, 11, 12, 13, 14, 15, 14, 13, 12, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]
        cvds =   [10, 11, 12, 13, 14, 15, 14, 13, 12, 11, 10,  9,  8,  7,  6,  5,  4,  3,  2,  1]
        dtype, z = mc.divergence_detect([float(p) for p in prices], [float(c) for c in cvds])
        assert dtype == "BEARISH_DIV"


class TestStd:
    def test_zero_variance(self):
        assert mc.std([5.0, 5.0, 5.0]) == 0.0

    def test_known_values(self):
        # std of [1,2,3,4,5] = sqrt(2) ≈ 1.414
        result = mc.std([1.0, 2.0, 3.0, 4.0, 5.0])
        assert abs(result - math.sqrt(2.0)) < 0.01
