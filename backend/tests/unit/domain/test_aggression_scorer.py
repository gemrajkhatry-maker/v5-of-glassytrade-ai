"""Unit tests for AggressionScorer — multi-signal additive scoring per Fabio FR-06."""

import pytest
from app.domain.fabio_ai.services.aggression_scorer import AggressionScorer, AggressionResult


class TestAggressionScorerBasic:
    """FR-06: Additive scoring with 7 components, max 4.5."""

    def test_all_signals_max_score(self):
        """All 7 signals confirmed → score = 4.5 (max)."""
        result = AggressionScorer.score(
            footprint_confirmed=True,
            cvd_confirmed=True,
            big_trade_confirmed=True,
            absorption_detected=True,
            ofi_aligned=True,
            confluence_bonus=True,
            volume_bubble_near=True,
        )
        assert result.score == pytest.approx(4.5)
        assert result.confidence == "HIGH"
        assert result.pyramid_eligible is True
        assert result.confirmed is True

    def test_no_signals_zero_score(self):
        """No signals → score = 0."""
        result = AggressionScorer.score()
        assert result.score == 0.0
        assert result.confidence == "LOW"
        assert result.pyramid_eligible is False
        assert result.confirmed is False

    def test_footprint_only(self):
        """Only footprint confirmed → score = 1.0."""
        result = AggressionScorer.score(footprint_confirmed=True)
        assert result.score == pytest.approx(1.0)
        assert result.confidence == "LOW"
        assert result.breakdown["footprint"] == 1.0

    def test_cvd_only(self):
        """Only CVD confirmed → score = 1.0."""
        result = AggressionScorer.score(cvd_confirmed=True)
        assert result.score == pytest.approx(1.0)
        assert result.breakdown["cvd"] == 1.0

    def test_big_trade_only(self):
        """Only big trade confirmed → score = 1.0."""
        result = AggressionScorer.score(big_trade_confirmed=True)
        assert result.score == pytest.approx(1.0)
        assert result.breakdown["big_trade"] == 1.0

    def test_absorption_only(self):
        """Only absorption detected → score = 0.5."""
        result = AggressionScorer.score(absorption_detected=True)
        assert result.score == pytest.approx(0.5)
        assert result.breakdown["absorption"] == 0.5

    def test_ofi_only(self):
        """Only OFI aligned → score = 0.5."""
        result = AggressionScorer.score(ofi_aligned=True)
        assert result.score == pytest.approx(0.5)
        assert result.breakdown["ofi"] == 0.5

    def test_confluence_only(self):
        """Only confluence bonus → score = 0.5."""
        result = AggressionScorer.score(confluence_bonus=True)
        assert result.score == pytest.approx(0.5)
        assert result.breakdown["confluence"] == 0.5

    def test_bubble_only(self):
        """Only volume bubble near → score = 0.5."""
        result = AggressionScorer.score(volume_bubble_near=True)
        assert result.score == pytest.approx(0.5)
        assert result.breakdown["bubble"] == 0.5


class TestAggressionScorerThresholds:
    """FR-06-08/09/10: Confidence and threshold logic."""

    def test_min_trade_score_2_0(self):
        """Score 2.0 → confirmed=True, confidence=MEDIUM."""
        result = AggressionScorer.score(
            footprint_confirmed=True,
            cvd_confirmed=True,
        )
        assert result.score == pytest.approx(2.0)
        assert result.confirmed is True
        assert result.confidence == "MEDIUM"
        assert result.pyramid_eligible is False

    def test_below_min_trade_score(self):
        """Score 1.5 → confirmed=False."""
        result = AggressionScorer.score(
            footprint_confirmed=True,
            absorption_detected=True,
        )
        assert result.score == pytest.approx(1.5)
        assert result.confirmed is False
        assert result.confidence == "LOW"

    def test_pyramid_score_3_0(self):
        """Score 3.0 → pyramid_eligible=True, confidence=HIGH."""
        result = AggressionScorer.score(
            footprint_confirmed=True,
            cvd_confirmed=True,
            big_trade_confirmed=True,
        )
        assert result.score == pytest.approx(3.0)
        assert result.pyramid_eligible is True
        assert result.confidence == "HIGH"

    def test_below_pyramid_score(self):
        """Score 2.5 → pyramid_eligible=False."""
        result = AggressionScorer.score(
            footprint_confirmed=True,
            cvd_confirmed=True,
            absorption_detected=True,
        )
        assert result.score == pytest.approx(2.5)
        assert result.pyramid_eligible is False

    def test_score_cap_at_4_5(self):
        """Score capped at 4.5 even if more signals available."""
        result = AggressionScorer.score(
            footprint_confirmed=True,
            cvd_confirmed=True,
            big_trade_confirmed=True,
            absorption_detected=True,
            ofi_aligned=True,
            confluence_bonus=True,
            volume_bubble_near=True,
        )
        assert result.score == pytest.approx(4.5)


class TestAggressionScorerBreakdown:
    """Verify breakdown dict matches individual signal contributions."""

    def test_breakdown_reflects_signals(self):
        result = AggressionScorer.score(
            footprint_confirmed=True,
            cvd_confirmed=True,
            absorption_detected=True,
        )
        assert result.breakdown["footprint"] == 1.0
        assert result.breakdown["cvd"] == 1.0
        assert result.breakdown["absorption"] == 0.5
        assert result.breakdown["big_trade"] == 0.0
        assert result.breakdown["ofi"] == 0.0
        assert result.breakdown["confluence"] == 0.0
        assert result.breakdown["bubble"] == 0.0

    def test_empty_breakdown_when_no_signals(self):
        result = AggressionScorer.score()
        assert all(v == 0.0 for v in result.breakdown.values())


class TestAggressionScorerSummary:
    """Human-readable summary output."""

    def test_summary_shows_active_signals(self):
        result = AggressionScorer.score(
            footprint_confirmed=True,
            cvd_confirmed=True,
        )
        summary = AggressionScorer.summary(result)
        assert "footprint" in summary
        assert "cvd" in summary
        assert "2.0" in summary

    def test_summary_empty_for_no_signals(self):
        result = AggressionScorer.score()
        summary = AggressionScorer.summary(result)
        assert "0.0" in summary