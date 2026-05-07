"""Tests for gap analysis utilities."""
import pytest
from app.domain.fabio_ai.services.gap_analyzer import (
    analyze_gap, classify_gap_enhanced, GapAnalysis
)


class TestAnalyzeGap:
    """Tests for analyze_gap() function."""

    def test_gap_up_inside_va(self):
        """Up gap opening inside prior value area."""
        result = analyze_gap(
            open_price=100.5, prior_close=100.0,
            prior_vah=102.0, prior_val=98.0
        )
        assert result.direction == "UP"
        assert result.gap_type == "INSIDE_VA"
        assert result.gap_size_label == "SMALL"
        assert result.entry_filter == "FADE"
        assert 0.7 < result.fill_probability < 0.9

    def test_gap_down_inside_va(self):
        """Down gap opening inside prior value area."""
        result = analyze_gap(
            open_price=99.5, prior_close=100.0,
            prior_vah=102.0, prior_val=98.0
        )
        assert result.direction == "DOWN"
        assert result.gap_type == "INSIDE_VA"

    def test_gap_outside_va_above(self):
        """Gap opening above prior value area."""
        result = analyze_gap(
            open_price=105.0, prior_close=100.0,
            prior_vah=102.0, prior_val=98.0,
            prior_range=4.0
        )
        assert result.direction == "UP"
        assert result.gap_type == "OUTSIDE_VA_ABOVE"
        assert result.entry_filter == "WAIT"  # gap_pct >= 0.30 → WAIT

    def test_gap_outside_va_below(self):
        """Gap opening below prior value area."""
        result = analyze_gap(
            open_price=95.0, prior_close=100.0,
            prior_vah=102.0, prior_val=98.0
        )
        assert result.direction == "DOWN"
        assert result.gap_type == "OUTSIDE_VA_BELOW"

    def test_gap_inside_ib(self):
        """Gap opening inside prior initial balance."""
        result = analyze_gap(
            open_price=100.5, prior_close=100.0,
            prior_vah=102.0, prior_val=98.0,
            prior_ib_high=101.0, prior_ib_low=99.5
        )
        assert result.gap_type == "INSIDE_IB"
        assert result.entry_filter == "FADE"

    def test_extreme_gap(self):
        """Extreme gap beyond 2x prior range."""
        result = analyze_gap(
            open_price=120.0, prior_close=100.0,
            prior_vah=102.0, prior_val=98.0,
            prior_range=4.0
        )
        assert result.gap_type == "EXTREME"
        assert result.gap_size_label == "EXTREME"
        assert result.entry_filter == "WAIT"
        assert result.fill_probability < 0.3

    def test_no_gap(self):
        """No gap when open equals prior close."""
        result = analyze_gap(
            open_price=100.0, prior_close=100.0,
            prior_vah=102.0, prior_val=98.0
        )
        assert result.direction == ""
        assert result.gap_size_label == "NONE"

    def test_invalid_inputs(self):
        """Invalid inputs return empty analysis."""
        result = analyze_gap(open_price=0, prior_close=100.0, prior_vah=102.0, prior_val=98.0)
        assert result.gap_size == 0.0
        assert result.gap_type == ""

        result = analyze_gap(open_price=100.0, prior_close=0, prior_vah=102.0, prior_val=98.0)
        assert result.gap_size == 0.0

    def test_small_gap_label(self):
        """Small gap between 0.5-15% of prior range."""
        result = analyze_gap(
            open_price=100.5, prior_close=100.0,
            prior_vah=102.0, prior_val=98.0
        )
        # gap=0.5, prior_range=4.0, gap_pct=0.125 → SMALL
        assert result.gap_size_label == "SMALL"

    def test_medium_gap_label(self):
        """Medium gap between 15-50% of prior range."""
        result = analyze_gap(
            open_price=101.0, prior_close=100.0,
            prior_vah=102.0, prior_val=98.0
        )
        assert result.gap_size_label == "MEDIUM"

    def test_large_gap_label(self):
        """Large gap between 50-200% of prior range."""
        result = analyze_gap(
            open_price=108.0, prior_close=100.0,
            prior_vah=102.0, prior_val=98.0,
            prior_range=4.0
        )
        # gap=8, prior_range=4, gap_pct=2.0 → EXTREME (>=2.0)
        assert result.gap_size_label == "EXTREME"


class TestClassifyGapEnhanced:
    """Tests for classify_gap_enhanced() wrapper."""

    def test_with_prior_range(self):
        """Enhanced classification using prior range."""
        result = classify_gap_enhanced(
            open_price=105.0, prior_close=100.0,
            prior_range=4.0
        )
        assert result.direction == "UP"
        assert result.gap_type == "OUTSIDE_VA_ABOVE"

    def test_with_explicit_va(self):
        """Enhanced classification with explicit VA levels."""
        result = classify_gap_enhanced(
            open_price=99.0, prior_close=100.0,
            prior_range=4.0,
            prior_vah=102.0, prior_val=98.0
        )
        assert result.gap_type == "INSIDE_VA"


class TestGapFillProbability:
    """Tests for fill probability calculations."""

    def test_inside_va_high_fill_prob(self):
        """Inside VA gaps have high fill probability."""
        result = analyze_gap(
            open_price=100.5, prior_close=100.0,
            prior_vah=102.0, prior_val=98.0
        )
        assert result.fill_probability >= 0.7

    def test_extreme_gap_low_fill_prob(self):
        """Extreme gaps have low fill probability."""
        result = analyze_gap(
            open_price=150.0, prior_close=100.0,
            prior_vah=102.0, prior_val=98.0,
            prior_range=4.0
        )
        assert result.fill_probability < 0.3

    def test_small_gap_bonus(self):
        """Very small gaps get fill probability bonus."""
        result = analyze_gap(
            open_price=100.05, prior_close=100.0,
            prior_vah=102.0, prior_val=98.0
        )
        # gap_pct < 0.10 gets +0.10 bonus
        assert result.fill_probability > 0.75

    def test_large_gap_penalty(self):
        """Very large gaps get fill probability penalty."""
        result = analyze_gap(
            open_price=200.0, prior_close=100.0,
            prior_vah=102.0, prior_val=98.0
        )
        # gap_pct > 1.0 gets -0.15 penalty
        assert result.fill_probability < 0.5


class TestGapThesis:
    """Tests for gap thesis generation."""

    def test_inside_va_thesis(self):
        """Inside VA gap thesis mentions rotation."""
        result = analyze_gap(
            open_price=100.5, prior_close=100.0,
            prior_vah=102.0, prior_val=98.0
        )
        assert "rotation" in result.thesis.lower()

    def test_extreme_gap_thesis(self):
        """Extreme gap thesis mentions value discovery."""
        result = analyze_gap(
            open_price=150.0, prior_close=100.0,
            prior_vah=102.0, prior_val=98.0,
            prior_range=4.0
        )
        assert "value discovery" in result.thesis.lower()

    def test_outside_va_above_thesis(self):
        """Outside VA above thesis mentions continuation."""
        result = analyze_gap(
            open_price=105.0, prior_close=100.0,
            prior_vah=102.0, prior_val=98.0
        )
        assert "continuation" in result.thesis.lower()
