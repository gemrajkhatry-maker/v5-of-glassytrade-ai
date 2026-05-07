"""Tests for AggressionScorer — Multi-signal additive scoring per Fabio AMT spec."""

from __future__ import annotations

import pytest

from app.domain.amt.service.aggression_scorer import (
    AggressionScorer,
    PersistentAggressionScorer,
    calculate_aggression_score,
)


class TestFootprintComponent:
    """Tests for footprint scoring component."""

    def test_footprint_ratio_above_threshold_scores_1(self):
        """Footprint ratio >= 40% adds +1.0."""
        scorer = AggressionScorer()
        result = scorer.score(footprint_ratio=0.45)
        assert result.breakdown.get("footprint") == 1.0

    def test_footprint_ratio_below_threshold_scores_0(self):
        """Footprint ratio < 40% adds 0."""
        scorer = AggressionScorer()
        result = scorer.score(footprint_ratio=0.30)
        assert "footprint" not in result.breakdown


class TestCVDComponent:
    """Tests for CVD confirmation component."""

    def test_cvd_confirms_adds_1(self):
        """CVD confirmation adds +1.0."""
        scorer = AggressionScorer()
        result = scorer.score(cvd_confirms=True)
        assert result.breakdown.get("cvd") == 1.0

    def test_cvd_no_confirm_adds_0(self):
        """No CVD confirmation adds 0."""
        scorer = AggressionScorer()
        result = scorer.score(cvd_confirms=False)
        assert "cvd" not in result.breakdown


class TestBigTradeComponent:
    """Tests for big trade cluster component."""

    def test_big_trade_cluster_adds_1(self):
        """Big trade cluster adds +1.0."""
        scorer = AggressionScorer()
        result = scorer.score(big_trade_cluster=True)
        assert result.breakdown.get("big_trade") == 1.0


class TestAbsorptionComponent:
    """Tests for absorption component."""

    def test_absorption_adds_half(self):
        """Absorption pattern adds +0.5."""
        scorer = AggressionScorer()
        result = scorer.score(absorption=True)
        assert result.breakdown.get("absorption") == 0.5


class TestOFIComponent:
    """Tests for Order Flow Imbalance component."""

    def test_ofi_aligned_long_adds_half(self):
        """OFI > 0.10 for LONG adds +0.5."""
        scorer = AggressionScorer()
        result = scorer.score(ofi=0.15, side="LONG")
        assert result.breakdown.get("ofi") == 0.5

    def test_ofi_aligned_short_adds_half(self):
        """OFI < -0.10 for SHORT adds +0.5."""
        scorer = AggressionScorer()
        result = scorer.score(ofi=-0.15, side="SHORT")
        assert result.breakdown.get("ofi") == 0.5

    def test_ofi_not_aligned_adds_0(self):
        """OFI not aligned with side adds 0."""
        scorer = AggressionScorer()
        result = scorer.score(ofi=0.05, side="LONG")
        assert "ofi" not in result.breakdown


class TestCompositeScore:
    """Tests for composite score calculation."""

    def test_high_confidence_score(self):
        """Score >= 3.0 yields HIGH confidence."""
        scorer = AggressionScorer()
        result = scorer.score(
            footprint_ratio=0.50, cvd_confirms=True, big_trade_cluster=True,
        )
        assert result.score == pytest.approx(3.0)
        assert result.confidence == "HIGH"
        assert result.confirmed is True
        assert result.pyramid_eligible is True

    def test_medium_confidence_score(self):
        """Score >= 2.0 yields MEDIUM confidence."""
        scorer = AggressionScorer()
        result = scorer.score(
            footprint_ratio=0.50, cvd_confirms=True,
        )
        assert result.score == pytest.approx(2.0)
        assert result.confidence == "MEDIUM"
        assert result.confirmed is True
        assert result.pyramid_eligible is False

    def test_low_confidence_score(self):
        """Score < 2.0 yields LOW confidence."""
        scorer = AggressionScorer()
        result = scorer.score(absorption=True)
        assert result.score == pytest.approx(0.5)
        assert result.confidence == "LOW"
        assert result.confirmed is False

    def test_all_components_max_score(self):
        """All components active yields maximum score of 5.0."""
        scorer = AggressionScorer()
        result = scorer.score(
            footprint_ratio=0.50, cvd_confirms=True, big_trade_cluster=True,
            absorption=True, ofi=0.15, lvn_near_level=True, volume_bubble=True,
            side="LONG",
        )
        # 1.0 + 1.0 + 1.0 + 0.5 + 0.5 + 0.5 + 0.5 = 5.0
        assert result.score == pytest.approx(5.0)


class TestLegacyUpdate:
    """Tests for legacy sigma-based update API."""

    def test_update_returns_sigma_score(self):
        """Update returns sigma-based aggression score."""
        scorer = AggressionScorer()
        # Feed some data
        scorer.update(10.0)
        scorer.update(12.0)
        result = scorer.update(30.0)  # Outlier
        assert result is not None
        assert "score" in result

    def test_update_insufficient_data(self):
        """First update returns score 0 (insufficient data)."""
        scorer = AggressionScorer()
        result = scorer.update(10.0)
        assert result is not None
        assert result["score"] == 0.0


class TestReset:
    """Tests for scorer reset."""

    def test_reset_clears_state(self):
        """Reset clears all accumulated state."""
        scorer = AggressionScorer()
        scorer.update(10.0)
        scorer.update(12.0)
        scorer.reset()
        assert scorer.count == 0
        assert scorer.sum == 0.0
        assert scorer._score == 0.0
