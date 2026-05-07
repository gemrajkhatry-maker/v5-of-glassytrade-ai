"""Tests for SessionContextEngine — Session context analysis."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.amt.service.session_context import (
    GapSize,
    OpeningBias,
    SessionContextEngine,
    SessionPhase,
)


def _make_time(hour, minute=0):
    return datetime(2024, 1, 1, hour, minute, 0, tzinfo=timezone.utc)


class TestNSESessionPhase:
    """Tests for NSE session phase detection."""

    def test_morning_phase_before_noon(self):
        """Hour < 12 => MORNING phase."""
        engine = SessionContextEngine()
        ctx = engine.analyze(
            open_price=100.0, prior_close=100.0, prior_poc=100.0,
            timestamp=_make_time(9, 30),
        )
        assert ctx.session_phase == SessionPhase.MORNING

    def test_afternoon_phase_at_noon_or_later(self):
        """Hour >= 12 => AFTERNOON phase."""
        engine = SessionContextEngine()
        ctx = engine.analyze(
            open_price=100.0, prior_close=100.0, prior_poc=100.0,
            timestamp=_make_time(12, 0),
        )
        assert ctx.session_phase == SessionPhase.AFTERNOON

    def test_afternoon_phase_afternoon(self):
        """Afternoon hours => AFTERNOON phase."""
        engine = SessionContextEngine()
        ctx = engine.analyze(
            open_price=100.0, prior_close=100.0, prior_poc=100.0,
            timestamp=_make_time(15, 30),
        )
        assert ctx.session_phase == SessionPhase.AFTERNOON


class TestMCXSessionPhase:
    """Tests for MCX session phase detection (same logic, different hours)."""

    def test_mcx_morning_session(self):
        """MCX morning session still uses hour-based detection."""
        engine = SessionContextEngine()
        ctx = engine.analyze(
            open_price=100.0, prior_close=100.0, prior_poc=100.0,
            timestamp=_make_time(10, 0),
        )
        assert ctx.session_phase == SessionPhase.MORNING

    def test_mcx_evening_session(self):
        """MCX evening session (after noon) => AFTERNOON."""
        engine = SessionContextEngine()
        ctx = engine.analyze(
            open_price=100.0, prior_close=100.0, prior_poc=100.0,
            timestamp=_make_time(20, 0),
        )
        assert ctx.session_phase == SessionPhase.AFTERNOON

    def test_no_timestamp_defaults_to_morning(self):
        """No timestamp provided defaults to MORNING."""
        engine = SessionContextEngine()
        ctx = engine.analyze(
            open_price=100.0, prior_close=100.0, prior_poc=100.0,
            timestamp=None,
        )
        assert ctx.session_phase == SessionPhase.MORNING


class TestGapClassification:
    """Tests for gap size classification."""

    def test_small_gap(self):
        """Gap < 0.5% => SMALL."""
        engine = SessionContextEngine(gap_medium_pct=0.5, gap_large_pct=1.0)
        ctx = engine.analyze(
            open_price=100.1, prior_close=100.0, prior_poc=100.0,
        )
        assert ctx.gap_size == GapSize.SMALL
        assert ctx.gap_pct == pytest.approx(0.1, rel=0.01)

    def test_medium_gap(self):
        """Gap >= 0.5% and < 1.0% => MEDIUM."""
        engine = SessionContextEngine(gap_medium_pct=0.5, gap_large_pct=1.0)
        ctx = engine.analyze(
            open_price=100.7, prior_close=100.0, prior_poc=100.0,
        )
        assert ctx.gap_size == GapSize.MEDIUM

    def test_large_gap(self):
        """Gap >= 1.0% => LARGE."""
        engine = SessionContextEngine(gap_medium_pct=0.5, gap_large_pct=1.0)
        ctx = engine.analyze(
            open_price=101.5, prior_close=100.0, prior_poc=100.0,
        )
        assert ctx.gap_size == GapSize.LARGE


class TestOpeningBias:
    """Tests for opening bias detection."""

    def test_long_bias_open_above_prior_poc(self):
        """Open > prior_poc * 1.01 => LONG_BIAS."""
        engine = SessionContextEngine()
        ctx = engine.analyze(
            open_price=102.0, prior_close=100.0, prior_poc=100.0,
        )
        assert ctx.opening_bias == OpeningBias.LONG_BIAS

    def test_short_bias_open_below_prior_poc(self):
        """Open < prior_poc * 0.99 => SHORT_BIAS."""
        engine = SessionContextEngine()
        ctx = engine.analyze(
            open_price=98.0, prior_close=100.0, prior_poc=100.0,
        )
        assert ctx.opening_bias == OpeningBias.SHORT_BIAS

    def test_neutral_bias_near_prior_poc(self):
        """Open within 1% of prior_poc => NEUTRAL."""
        engine = SessionContextEngine()
        ctx = engine.analyze(
            open_price=100.5, prior_close=100.0, prior_poc=100.0,
        )
        assert ctx.opening_bias == OpeningBias.NEUTRAL

    def test_zero_prior_poc_returns_neutral(self):
        """Zero prior_poc => NEUTRAL."""
        engine = SessionContextEngine()
        ctx = engine.analyze(
            open_price=102.0, prior_close=100.0, prior_poc=0.0,
        )
        assert ctx.opening_bias == OpeningBias.NEUTRAL

    def test_zero_prior_close_returns_zero_gap(self):
        """Zero prior_close => 0% gap."""
        engine = SessionContextEngine()
        ctx = engine.analyze(
            open_price=100.0, prior_close=0.0, prior_poc=100.0,
        )
        assert ctx.gap_pct == 0.0
        assert ctx.gap_size == GapSize.SMALL
