"""Tests for spread normalization."""
import pytest
from app.domain.amt.service.spread_normalizer import (
    SpreadNormalizer, SpreadNormalizationResult
)


class TestSpreadNormalizerUpdate:
    """Tests for update() method."""

    def test_initializes_on_first_valid_spread(self):
        """First positive spread initializes EMA."""
        sn = SpreadNormalizer()
        sn.update(5.0)
        assert sn._ema_spread == 5.0
        assert sn._initialized is True

    def test_ignores_negative_spread(self):
        """Negative spread is ignored."""
        sn = SpreadNormalizer()
        sn.update(-1.0)
        assert sn._initialized is False

    def test_ignores_zero_spread(self):
        """Zero spread is ignored."""
        sn = SpreadNormalizer()
        sn.update(0.0)
        assert sn._initialized is False

    def test_ema_updates_on_subsequent_spreads(self):
        """EMA updates with alpha weighting."""
        sn = SpreadNormalizer(ema_period=10)
        alpha = 2.0 / 11
        sn.update(10.0)
        sn.update(20.0)
        expected = alpha * 20.0 + (1.0 - alpha) * 10.0
        assert sn._ema_spread == pytest.approx(expected)

    def test_multiple_updates_converge(self):
        """EMA converges towards recent values."""
        sn = SpreadNormalizer(ema_period=5)
        sn.update(10.0)
        for _ in range(20):
            sn.update(20.0)
        assert sn._ema_spread > 15.0  # Should be close to 20


class TestSpreadNormalizerNormalize:
    """Tests for normalize() method."""

    def test_uninitialized_returns_defaults(self):
        """Uninitialized normalizer returns ratio=1, not wide."""
        sn = SpreadNormalizer()
        result = sn.normalize(5.0)
        assert result.spread_ratio == 1.0
        assert result.is_wide is False
        assert result.penalty == 0.0

    def test_normal_spread_not_wide(self):
        """Spread at EMA level is not wide."""
        sn = SpreadNormalizer()
        sn.update(10.0)
        result = sn.normalize(10.0)
        assert result.spread_ratio == pytest.approx(1.0)
        assert result.is_wide is False
        assert result.penalty == 0.0

    def test_wide_spread_detected(self):
        """Spread 1.5x EMA triggers wide detection."""
        sn = SpreadNormalizer(wide_threshold=1.5)
        sn.update(10.0)
        result = sn.normalize(20.0)  # 2x EMA
        assert result.spread_ratio == pytest.approx(2.0)
        assert result.is_wide is True

    def test_wide_spread_penalty(self):
        """Wide spread gets penalty proportional to excess."""
        sn = SpreadNormalizer(wide_threshold=1.5)
        sn.update(10.0)
        result = sn.normalize(30.0)  # 3x EMA
        assert result.is_wide is True
        assert result.penalty > 0.0
        assert result.penalty <= 0.5

    def test_penalty_capped_at_half(self):
        """Penalty never exceeds 0.5."""
        sn = SpreadNormalizer(wide_threshold=1.5)
        sn.update(10.0)
        result = sn.normalize(100.0)  # 10x EMA
        assert result.penalty == 0.5

    def test_below_threshold_no_penalty(self):
        """Spread just below threshold has no penalty."""
        sn = SpreadNormalizer(wide_threshold=1.5)
        sn.update(10.0)
        result = sn.normalize(14.0)  # 1.4x EMA
        assert result.is_wide is False
        assert result.penalty == 0.0


class TestSpreadNormalizerHelpers:
    """Tests for convenience methods."""

    def test_is_wide_spread(self):
        """is_wide_spread returns bool."""
        sn = SpreadNormalizer(wide_threshold=1.5)
        sn.update(10.0)
        assert sn.is_wide_spread(10.0) is False
        assert sn.is_wide_spread(20.0) is True

    def test_get_penalty(self):
        """get_penalty returns penalty value."""
        sn = SpreadNormalizer(wide_threshold=1.5)
        sn.update(10.0)
        assert sn.get_penalty(10.0) == 0.0
        assert sn.get_penalty(20.0) > 0.0

    def test_reset_clears_state(self):
        """Reset returns to uninitialized state."""
        sn = SpreadNormalizer()
        sn.update(10.0)
        sn.reset()
        assert sn._initialized is False
        assert sn._ema_spread == 0.0
        result = sn.normalize(10.0)
        assert result.spread_ratio == 1.0


class TestSpreadNormalizationResult:
    """Tests for result dataclass."""

    def test_result_fields(self):
        """Result has all expected fields."""
        result = SpreadNormalizationResult(
            current_spread=10.0,
            ema_spread=8.0,
            spread_ratio=1.25,
            is_wide=False,
            penalty=0.0
        )
        assert result.current_spread == 10.0
        assert result.ema_spread == 8.0
        assert result.spread_ratio == 1.25
        assert result.is_wide is False
        assert result.penalty == 0.0
