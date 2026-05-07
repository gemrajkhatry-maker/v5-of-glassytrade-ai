"""Tests for MLX compute pure functions."""
import math
import pytest
from app.domain.amt.service.mlx_compute import (
    gaussian_weights, smooth_array, ema, linreg_slope,
    atr, candle_overlap_pct, weighted_moments, count_peaks,
    aggression_sigma, divergence_detect, std
)


class TestGaussianWeights:
    """Tests for gaussian_weights()."""

    def test_basic_gaussian(self):
        """Gaussian weights peak at center."""
        centers = [98.0, 99.0, 100.0, 101.0, 102.0]
        weights = gaussian_weights(centers, center=100.0, sigma=1.0)
        assert len(weights) == 5
        assert weights[2] == max(weights)  # Center is highest

    def test_symmetric(self):
        """Gaussian is symmetric around center."""
        centers = [98.0, 99.0, 100.0, 101.0, 102.0]
        weights = gaussian_weights(centers, center=100.0, sigma=1.0)
        assert weights[0] == pytest.approx(weights[4], rel=0.01)
        assert weights[1] == pytest.approx(weights[3], rel=0.01)

    def test_empty_centers_returns_uniform(self):
        """Empty centers returns [1.0] as fallback."""
        assert gaussian_weights([], center=100.0, sigma=1.0) == [1.0]

    def test_sums_to_one(self):
        """Weights sum to approximately 1."""
        centers = [95.0, 96.0, 97.0, 98.0, 99.0, 100.0, 101.0, 102.0, 103.0, 104.0]
        weights = gaussian_weights(centers, center=100.0, sigma=2.0)
        assert sum(weights) == pytest.approx(1.0, rel=0.01)

    def test_zero_sigma_fallback(self):
        """Zero sigma returns uniform weights."""
        weights = gaussian_weights([1.0, 2.0, 3.0], center=2.0, sigma=0)
        assert all(w == pytest.approx(1/3, rel=0.01) for w in weights)


class TestSmoothArray:
    """Tests for smooth_array()."""

    def test_smoothing_reduces_variance(self):
        """Smoothing reduces variance."""
        data = [1.0, 10.0, 1.0, 10.0, 1.0]
        smoothed = smooth_array(data, window=3)
        assert len(smoothed) == len(data)

    def test_preserves_length(self):
        """Output length equals input length."""
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        smoothed = smooth_array(data, window=3)
        assert len(smoothed) == 5

    def test_empty_array(self):
        """Empty array returns empty."""
        assert smooth_array([], window=3) == []

    def test_window_one_no_change(self):
        """Window=1 returns original data."""
        data = [1.0, 2.0, 3.0]
        assert smooth_array(data, window=1) == data


class TestEMA:
    """Tests for ema()."""

    def test_ema_follows_trend(self):
        """EMA follows upward trend."""
        data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        result = ema(data, period=5)
        assert result > 5.0  # Should be above midpoint

    def test_ema_short_period(self):
        """Short period EMA reacts faster."""
        data = [1.0, 10.0, 10.0, 10.0, 10.0]
        short = ema(data, period=2)
        long = ema(data, period=10)
        assert short > long  # Short EMA catches up faster

    def test_ema_empty(self):
        """Empty data returns 0."""
        assert ema([], period=5) == 0.0

    def test_ema_single_value(self):
        """Single value returns itself."""
        assert ema([5.0], period=5) == 5.0


class TestLinregSlope:
    """Tests for linreg_slope()."""

    def test_upward_slope(self):
        """Upward trend has positive slope."""
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        slope = linreg_slope(data)
        assert slope > 0

    def test_downward_slope(self):
        """Downward trend has negative slope."""
        data = [5.0, 4.0, 3.0, 2.0, 1.0]
        slope = linreg_slope(data)
        assert slope < 0

    def test_flat_slope(self):
        """Flat data has zero slope."""
        data = [5.0, 5.0, 5.0, 5.0, 5.0]
        slope = linreg_slope(data)
        assert slope == pytest.approx(0.0, abs=0.01)

    def test_insufficient_data(self):
        """Less than 2 points returns 0."""
        assert linreg_slope([1.0]) == 0.0
        assert linreg_slope([]) == 0.0


class TestATR:
    """Tests for atr()."""

    def test_atr_basic(self):
        """ATR computes average true range."""
        highs = [105.0, 108.0, 110.0, 112.0, 115.0]
        lows = [95.0, 98.0, 100.0, 102.0, 105.0]
        closes = [100.0, 103.0, 105.0, 108.0, 110.0]
        result = atr(highs, lows, closes, period=3)
        assert result > 0

    def test_atr_zero_range(self):
        """Zero range candles have zero ATR (single candle)."""
        result = atr([100.0], [100.0], [100.0])
        assert result == 0.0

    def test_atr_insufficient_data(self):
        """Single candle returns high-low range."""
        result = atr([100.0], [90.0], [95.0])
        assert result == 10.0


class TestCandleOverlapPct:
    """Tests for candle_overlap_pct()."""

    def test_overlapping_candles(self):
        """Overlapping candles have high overlap percentage."""
        highs = [105.0, 103.0]
        lows = [95.0, 97.0]
        pct = candle_overlap_pct(highs, lows)
        assert pct > 0

    def test_non_overlapping(self):
        """Non-overlapping candles have zero overlap."""
        highs = [105.0, 115.0]
        lows = [95.0, 110.0]
        pct = candle_overlap_pct(highs, lows)
        assert pct == 0.0

    def test_single_candle(self):
        """Single candle returns 100%."""
        assert candle_overlap_pct([100.0], [90.0]) == 100.0


class TestWeightedMoments:
    """Tests for weighted_moments()."""

    def test_moments_computed(self):
        """Weighted moments returns skewness, kurtosis, std."""
        prices = [1.0, 2.0, 3.0, 4.0, 5.0]
        volumes = [10.0, 20.0, 30.0, 20.0, 10.0]
        skew, kurt, std_val = weighted_moments(prices, volumes)
        assert isinstance(skew, float)
        assert isinstance(kurt, float)
        assert std_val > 0

    def test_zero_volume(self):
        """Zero volume returns zeros."""
        skew, kurt, std_val = weighted_moments([1.0, 2.0], [0.0, 0.0])
        assert skew == 0.0
        assert kurt == 0.0
        assert std_val == 0.0

    def test_constant_prices(self):
        """Constant prices returns zero std."""
        skew, kurt, std_val = weighted_moments([5.0, 5.0, 5.0], [1.0, 2.0, 1.0])
        assert std_val == pytest.approx(0.0, abs=0.01)


class TestCountPeaks:
    """Tests for count_peaks()."""

    def test_few_values_returns_one(self):
        """Less than 5 values returns 1."""
        assert count_peaks([1.0, 2.0, 3.0]) == 1

    def test_single_peak(self):
        """Data with one peak detected."""
        data = [1.0, 2.0, 5.0, 2.0, 1.0, 1.0, 1.0]
        assert count_peaks(data) >= 1

    def test_multiple_peaks(self):
        """Data with multiple peaks detected."""
        data = [1.0, 3.0, 1.0, 3.0, 1.0, 3.0, 1.0]
        assert count_peaks(data) >= 2

    def test_zero_max(self):
        """All zeros returns 0 peaks."""
        assert count_peaks([0.0, 0.0, 0.0, 0.0, 0.0]) == 0


class TestAggressionSigma:
    """Tests for aggression_sigma()."""

    def test_zero_volume_no_aggression(self):
        """Zero volume returns 0."""
        volumes = [100.0] * 20
        result = aggression_sigma(candle_volume=0, volumes=volumes)
        assert result == 0.0

    def test_high_volume_aggression(self):
        """High volume relative to average shows aggression."""
        volumes = [100.0] * 20
        result = aggression_sigma(candle_volume=500, volumes=volumes)
        assert result > 0

    def test_insufficient_volumes(self):
        """Less than 10 volumes returns 0."""
        result = aggression_sigma(candle_volume=100, volumes=[10.0] * 5)
        assert result == 0.0

    def test_variance_floor(self):
        """Variance floor prevents division by zero."""
        volumes = [100.0] * 20
        result = aggression_sigma(candle_volume=100, volumes=volumes)
        assert not math.isnan(result)
        assert not math.isinf(result)


class TestDivergenceDetect:
    """Tests for divergence_detect()."""

    def test_bullish_divergence(self):
        """Price lower low in second half + CVD higher low = bullish divergence."""
        # First half: prices min=95, cvds min=3
        # Second half: prices min=85 (lower), cvds min=6 (higher)
        prices = [100.0, 95.0, 90.0, 98.0, 85.0, 92.0, 96.0, 94.0]
        cvds = [10.0, 8.0, 5.0, 6.0, 8.0, 7.0, 9.0, 10.0]
        result_type, z_score = divergence_detect(prices, cvds)
        assert result_type == "BULLISH_DIV"

    def test_bearish_divergence(self):
        """Price higher high + CVD lower high = bearish divergence."""
        prices = [100.0, 105.0, 110.0, 115.0, 108.0, 112.0, 118.0, 120.0]
        cvds = [10.0, 12.0, 15.0, 18.0, 14.0, 13.0, 11.0, 10.0]
        result_type, z_score = divergence_detect(prices, cvds)
        assert result_type == "BEARISH_DIV"

    def test_no_divergence(self):
        """Aligned price and CVD = no divergence."""
        prices = [100.0, 105.0, 110.0, 115.0]
        cvds = [10.0, 15.0, 20.0, 25.0]
        result_type, z_score = divergence_detect(prices, cvds)
        assert result_type == "NONE"

    def test_insufficient_data(self):
        """Less than 4 points returns NONE."""
        assert divergence_detect([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == ("NONE", 0.0)


class TestStd:
    """Tests for std()."""

    def test_std_positive(self):
        """Non-constant data has positive std."""
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert std(data) > 0

    def test_std_zero(self):
        """Constant data has zero std."""
        data = [5.0, 5.0, 5.0, 5.0]
        assert std(data) == pytest.approx(0.0)

    def test_std_single_value(self):
        """Single value has zero std."""
        assert std([5.0]) == pytest.approx(0.0)

    def test_std_empty(self):
        """Empty data returns 0."""
        assert std([]) == 0.0
