"""Tests for position sizing (Kelly criterion and SL/TP adjustments)."""
from __future__ import annotations

import pytest

from app.domain.probability.sizing import adjust_sl_tp, kelly_size


class TestKellySize:
    """Test Kelly criterion position sizing."""

    def test_positive_edge_returns_size(self):
        """kelly_size() returns positive fraction for positive edge."""
        # p=0.55, r=1.5 -> K = 0.55 - 0.45/1.5 = 0.55 - 0.30 = 0.25
        size = kelly_size(probability=0.55, win_loss_ratio=1.5)
        assert size == pytest.approx(0.25, abs=0.001)

    def test_negative_edge_returns_zero(self):
        """kelly_size() returns ~0 when edge is zero or negative."""
        # p=0.40, r=1.5 -> K = 0.40 - 0.60/1.5 = 0.40 - 0.40 = 0.0 (floating point)
        size = kelly_size(probability=0.40, win_loss_ratio=1.5)
        assert size < 0.01  # effectively zero (may be ~5.5e-17)

    def test_very_bad_edge_returns_zero(self):
        """kelly_size() returns 0 for very low probability."""
        size = kelly_size(probability=0.20, win_loss_ratio=1.5)
        assert size == 0.0

    def test_capped_at_25_percent(self):
        """kelly_size() is capped at 25% for safety."""
        # p=0.80, r=1.5 -> K = 0.80 - 0.20/1.5 = 0.80 - 0.133 = 0.667 -> capped to 0.25
        size = kelly_size(probability=0.80, win_loss_ratio=1.5)
        assert size == pytest.approx(0.25)

    def test_half_kelly_reduction(self):
        """Half-Kelly: caller can halve the result for more conservative sizing."""
        size = kelly_size(probability=0.55, win_loss_ratio=1.5)
        half = size / 2.0
        assert half == pytest.approx(0.125, abs=0.001)
        assert half < size

    def test_edge_case_zero_probability(self):
        """kelly_size() returns 0 for probability=0."""
        assert kelly_size(probability=0.0) == 0.0

    def test_edge_case_probability_one(self):
        """kelly_size() returns 0 for probability=1 (capped)."""
        assert kelly_size(probability=1.0) == 0.0

    def test_negative_win_loss_ratio_defaults(self):
        """kelly_size() defaults win_loss_ratio to 1.0 when non-positive."""
        # p=0.55, r=1.0 (defaulted) -> K = 0.55 - 0.45/1.0 = 0.10
        size = kelly_size(probability=0.55, win_loss_ratio=-1.0)
        assert size == pytest.approx(0.10, abs=0.001)

    def test_various_probabilities(self):
        """Kelly size increases with probability (below cap)."""
        s1 = kelly_size(probability=0.51, win_loss_ratio=1.5)
        s2 = kelly_size(probability=0.53, win_loss_ratio=1.5)
        s3 = kelly_size(probability=0.55, win_loss_ratio=1.5)
        assert s1 < s2 < s3


class TestAdjustSlTp:
    """Test volatility-based SL/TP adjustment."""

    def test_volatility_expands_sl(self):
        """High volatility expands stop-loss distance."""
        entry = 100.0
        sl_dist = 1.0
        tp_dist = 2.0

        # Low volatility (0.5) -> vol_mult = max(1.0, 1.0) = 1.0
        sl_lo, tp_lo, _, _ = adjust_sl_tp(entry, "LONG", sl_dist, tp_dist, volatility=0.5)

        # High volatility (2.0) -> vol_mult = max(1.0, 4.0) = 4.0
        sl_hi, tp_hi, _, _ = adjust_sl_tp(entry, "LONG", sl_dist, tp_dist, volatility=2.0)

        assert abs(sl_lo - entry) < abs(sl_hi - entry)

    def test_volatility_compresses_tp(self):
        """High volatility compresses take-profit distance."""
        entry = 100.0
        sl_dist = 1.0
        tp_dist = 2.0

        _, tp_lo, _, _ = adjust_sl_tp(entry, "LONG", sl_dist, tp_dist, volatility=0.5)
        _, tp_hi, _, _ = adjust_sl_tp(entry, "LONG", sl_dist, tp_dist, volatility=2.0)

        assert abs(tp_hi - entry) < abs(tp_lo - entry)

    def test_long_direction(self):
        """LONG: SL below entry, TP above entry."""
        sl, tp, _, _ = adjust_sl_tp(100.0, "LONG", 1.0, 2.0, volatility=0.5)
        assert sl < 100.0
        assert tp > 100.0

    def test_short_direction(self):
        """SHORT: SL above entry, TP below entry."""
        sl, tp, _, _ = adjust_sl_tp(100.0, "SHORT", 1.0, 2.0, volatility=0.5)
        assert sl > 100.0
        assert tp < 100.0

    def test_returns_adjust_factors(self):
        """adjust_sl_tp() returns (sl_adjust, tp_adjust) multipliers."""
        _, _, sl_mult, tp_mult = adjust_sl_tp(100.0, "LONG", 1.0, 2.0, volatility=1.0)
        assert sl_mult > 1.0
        assert tp_mult < 1.0
        assert sl_mult * tp_mult == pytest.approx(1.0, abs=0.001)

    def test_conservative_cap_for_small_accounts(self):
        """With high volatility, SL adjustment is bounded (vol_mult >= 1)."""
        sl, tp, sl_mult, tp_mult = adjust_sl_tp(100.0, "LONG", 1.0, 2.0, volatility=10.0)
        assert sl_mult >= 1.0
        assert tp_mult <= 1.0
        # SL price is still reasonable
        assert sl > 0

    def test_zero_volatility_uses_base(self):
        """Zero volatility uses base distances (vol_mult=1.0)."""
        sl, tp, sl_mult, tp_mult = adjust_sl_tp(100.0, "LONG", 1.0, 2.0, volatility=0.0)
        assert sl_mult == 1.0
        assert tp_mult == 1.0
        assert sl == 99.0
        assert tp == 102.0
