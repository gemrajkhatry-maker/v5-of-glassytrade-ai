"""
Unit tests for aggression scorer.
"""

import pytest
from src.strategy.aggression_scorer import AggressionScorer


class TestAggressionScorer:
    """Test aggression scoring logic."""

    def test_max_score(self):
        """Test maximum score with all signals."""
        result = AggressionScorer.score(
            footprint_confirmed=True,
            cvd_confirmed=True,
            big_trade_confirmed=True,
            absorption_detected=True,
            ofi_aligned=True,
            confluence_bonus=True,
            volume_bubble_near=True,
        )
        assert result.score == 5.0  # Max is 5.0 (1+1+1+0.5+0.5+0.5+0.5)
        assert result.confidence == "HIGH"
        assert result.pyramid_eligible == True

    def test_min_trade_score(self):
        """Test minimum trade score (2.0)."""
        result = AggressionScorer.score(
            footprint_confirmed=True,
            cvd_confirmed=True,
        )
        assert result.score == 2.0
        assert result.confirmed == True
        assert result.confidence == "MEDIUM"

    def test_below_min_score(self):
        """Test below minimum score."""
        result = AggressionScorer.score(
            footprint_confirmed=True,
        )
        assert result.score == 1.0
        assert result.confirmed == False
        assert result.confidence == "LOW"

    def test_pyramid_threshold(self):
        """Test pyramid threshold (3.0)."""
        result = AggressionScorer.score(
            footprint_confirmed=True,
            cvd_confirmed=True,
            big_trade_confirmed=True,
        )
        assert result.score == 3.0
        assert result.pyramid_eligible == True

    def test_breakdown(self):
        """Test breakdown contains all components."""
        result = AggressionScorer.score(
            footprint_confirmed=True,
            cvd_confirmed=False,
            big_trade_confirmed=False,
        )
        assert "footprint" in result.breakdown
        assert result.breakdown["footprint"] == 1.0
        assert result.breakdown["cvd"] == 0.0