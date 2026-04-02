"""Tests for GapAnalyzer — P0-4 implementation."""

from __future__ import annotations

import pytest

from app.domain.fabio_ai.services.gap_analyzer import (
    analyze_gap,
    GapAnalysis,
    _classify_gap_type,
    _estimate_fill_probability,
    _gap_entry_filter,
)


class TestAnalyzeGap:
    """Tests for the main analyze_gap() function."""

    def test_no_gap(self):
        """When open equals prior close, no gap detected."""
        result = analyze_gap(
            open_price=24800.0,
            prior_close=24800.0,
            prior_vah=24900.0,
            prior_val=24700.0,
            prior_range=200.0,
        )
        assert result.gap_type == "INSIDE_VA"
        assert result.direction == ""
        assert result.gap_size_label == "NONE"
        assert result.entry_filter == "FADE"

    def test_small_gap_inside_va(self):
        """Small gap opening inside prior value area."""
        result = analyze_gap(
            open_price=24820.0,
            prior_close=24800.0,
            prior_vah=24900.0,
            prior_val=24700.0,
            prior_range=200.0,
        )
        assert result.gap_type == "INSIDE_VA"
        assert result.direction == "UP"
        assert result.gap_size_label == "SMALL"
        assert result.fill_probability > 0.7
        assert result.entry_filter == "FADE"

    def test_medium_gap_outside_va_above(self):
        """Medium gap opening above prior VA."""
        result = analyze_gap(
            open_price=24960.0,
            prior_close=24800.0,
            prior_vah=24900.0,
            prior_val=24700.0,
            prior_range=200.0,
        )
        assert result.gap_type == "OUTSIDE_VA_ABOVE"
        assert result.direction == "UP"
        assert result.gap_size_label in (
            "MEDIUM",
            "LARGE",
        )  # 80% of range = LARGE boundary
        assert result.fill_probability < 0.6
        assert result.entry_filter in ("CONTINUE", "WAIT")

    def test_large_gap_outside_va_below(self):
        """Large gap opening below prior VA."""
        result = analyze_gap(
            open_price=24600.0,
            prior_close=24800.0,
            prior_vah=24900.0,
            prior_val=24700.0,
            prior_range=200.0,
        )
        assert result.gap_type == "OUTSIDE_VA_BELOW"
        assert result.direction == "DOWN"
        assert result.gap_size_label == "LARGE"
        assert result.entry_filter == "WAIT"

    def test_extreme_gap(self):
        """Extreme gap (>2x prior range) — new value discovery."""
        result = analyze_gap(
            open_price=25400.0,
            prior_close=24800.0,
            prior_vah=24900.0,
            prior_val=24700.0,
            prior_range=200.0,
        )
        assert result.gap_type == "EXTREME"
        assert result.gap_size_label == "EXTREME"
        assert result.fill_probability < 0.30
        assert result.entry_filter == "WAIT"

    def test_gap_inside_ib(self):
        """Gap opening inside prior initial balance."""
        result = analyze_gap(
            open_price=24810.0,
            prior_close=24800.0,
            prior_vah=24900.0,
            prior_val=24700.0,
            prior_ib_high=24850.0,
            prior_ib_low=24750.0,
            prior_range=200.0,
        )
        assert result.gap_type == "INSIDE_IB"
        assert result.entry_filter == "FADE"

    def test_invalid_inputs(self):
        """Invalid inputs return empty analysis."""
        result = analyze_gap(
            open_price=0.0,
            prior_close=24800.0,
            prior_vah=24900.0,
            prior_val=24700.0,
            prior_range=200.0,
        )
        assert result.gap_type == ""
        assert result.direction == ""
        assert result.entry_filter == "NONE"

    def test_gap_pct_calculation(self):
        """Gap percentage is correctly calculated."""
        result = analyze_gap(
            open_price=24830.0,
            prior_close=24800.0,
            prior_vah=24900.0,
            prior_val=24700.0,
            prior_range=200.0,
        )
        assert result.gap_pct == pytest.approx(0.15, abs=0.01)

    def test_thesis_generated(self):
        """Human-readable thesis is generated."""
        result = analyze_gap(
            open_price=24820.0,
            prior_close=24800.0,
            prior_vah=24900.0,
            prior_val=24700.0,
            prior_range=200.0,
        )
        assert len(result.thesis) > 0
        assert "SMALL" in result.thesis


class TestClassifyGapType:
    """Tests for gap type classification logic."""

    def test_inside_va(self):
        assert (
            _classify_gap_type(24850.0, 24900.0, 24700.0, 0.0, 0.0, 200.0)
            == "INSIDE_VA"
        )

    def test_outside_va_above(self):
        assert (
            _classify_gap_type(24950.0, 24900.0, 24700.0, 0.0, 0.0, 200.0)
            == "OUTSIDE_VA_ABOVE"
        )

    def test_outside_va_below(self):
        assert (
            _classify_gap_type(24650.0, 24900.0, 24700.0, 0.0, 0.0, 200.0)
            == "OUTSIDE_VA_BELOW"
        )

    def test_extreme_gap_above(self):
        assert (
            _classify_gap_type(25500.0, 24900.0, 24700.0, 0.0, 0.0, 200.0) == "EXTREME"
        )

    def test_extreme_gap_below(self):
        assert (
            _classify_gap_type(24100.0, 24900.0, 24700.0, 0.0, 0.0, 200.0) == "EXTREME"
        )

    def test_inside_ib_takes_priority_over_va(self):
        assert (
            _classify_gap_type(24810.0, 24900.0, 24700.0, 24850.0, 24750.0, 200.0)
            == "INSIDE_IB"
        )

    def test_no_prior_data(self):
        assert _classify_gap_type(24800.0, 0.0, 0.0, 0.0, 0.0, 0.0) == ""


class TestEstimateFillProbability:
    """Tests for fill probability estimation."""

    def test_inside_va_high_fill(self):
        prob = _estimate_fill_probability("INSIDE_VA", 0.10, "UP", 24900.0, 24700.0)
        assert prob > 0.70

    def test_extreme_gap_low_fill(self):
        prob = _estimate_fill_probability("EXTREME", 1.50, "UP", 24900.0, 24700.0)
        assert prob < 0.30

    def test_outside_va_moderate_fill(self):
        prob = _estimate_fill_probability(
            "OUTSIDE_VA_ABOVE", 0.30, "UP", 24900.0, 24700.0
        )
        assert 0.20 < prob < 0.60

    def test_no_gap_zero_probability(self):
        prob = _estimate_fill_probability("", 0.0, "", 24900.0, 24700.0)
        assert prob == 0.0

    def test_small_gap_higher_fill(self):
        """Small gaps fill more often than large gaps."""
        small = _estimate_fill_probability("INSIDE_VA", 0.05, "UP", 24900.0, 24700.0)
        large = _estimate_fill_probability("INSIDE_VA", 0.80, "UP", 24900.0, 24700.0)
        assert small > large


class TestGapEntryFilter:
    """Tests for entry filter recommendations."""

    def test_inside_va_fade(self):
        assert _gap_entry_filter("INSIDE_VA", 0.10, "UP") == "FADE"

    def test_inside_ib_fade(self):
        assert _gap_entry_filter("INSIDE_IB", 0.05, "DOWN") == "FADE"

    def test_small_outside_continue(self):
        assert _gap_entry_filter("OUTSIDE_VA_ABOVE", 0.20, "UP") == "CONTINUE"

    def test_large_outside_wait(self):
        assert _gap_entry_filter("OUTSIDE_VA_ABOVE", 0.60, "UP") == "WAIT"

    def test_extreme_wait(self):
        assert _gap_entry_filter("EXTREME", 2.0, "UP") == "WAIT"

    def test_no_gap_none(self):
        assert _gap_entry_filter("", 0.0, "") == "NONE"
