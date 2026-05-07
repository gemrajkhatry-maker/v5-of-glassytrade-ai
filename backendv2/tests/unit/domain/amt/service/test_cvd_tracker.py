"""Tests for CVDTracker — Cumulative Volume Delta tracking with slope & divergence."""

from __future__ import annotations

import pytest

from app.domain.amt.service.cvd_tracker import CVDTracker


class TestCVDUpdate:
    """Tests for CVD cumulative delta accumulation."""

    def test_cumulative_delta_accumulates(self):
        """CVD accumulates delta across bars."""
        tracker = CVDTracker()
        tracker.update(bar_index=0, bid_volume=100, ask_volume=50, price=100.0)
        tracker.update(bar_index=1, bid_volume=80, ask_volume=60, price=101.0)
        tracker.update(bar_index=2, bid_volume=120, ask_volume=40, price=102.0)
        # Deltas: +50, +20, +80 => cumulative = 150
        assert tracker.cumulative_delta == pytest.approx(150.0)

    def test_negative_delta_decreases_cvd(self):
        """More ask volume than bid decreases CVD."""
        tracker = CVDTracker()
        tracker.update(bar_index=0, bid_volume=30, ask_volume=70, price=100.0)
        tracker.update(bar_index=1, bid_volume=20, ask_volume=80, price=99.0)
        # Deltas: -40, -60 => cumulative = -100
        assert tracker.cumulative_delta == pytest.approx(-100.0)

    def test_initial_cumulative_delta_is_zero(self):
        """Empty tracker returns 0 cumulative delta."""
        tracker = CVDTracker()
        assert tracker.cumulative_delta == 0.0


class TestCVDSlope:
    """Tests for CVD slope calculation."""

    def test_positive_slope(self):
        """Upward CVD trend yields positive slope."""
        tracker = CVDTracker()
        for i in range(10):
            tracker.update(bar_index=i, bid_volume=100, ask_volume=50, price=100.0 + i)
        state = tracker.state()
        assert state.slope > 0

    def test_negative_slope(self):
        """Downward CVD trend yields negative slope."""
        tracker = CVDTracker()
        for i in range(10):
            tracker.update(bar_index=i, bid_volume=30, ask_volume=80, price=100.0 - i)
        state = tracker.state()
        assert state.slope < 0

    def test_slope_zero_with_insufficient_data(self):
        """Single bar returns zero slope."""
        tracker = CVDTracker()
        tracker.update(bar_index=0, bid_volume=50, ask_volume=50, price=100.0)
        state = tracker.state()
        assert state.slope == 0.0


class TestCVDReset:
    """Tests for session reset."""

    def test_reset_clears_history(self):
        """Reset clears all accumulated CVD data."""
        tracker = CVDTracker()
        tracker.update(bar_index=0, bid_volume=100, ask_volume=50, price=100.0)
        tracker.update(bar_index=1, bid_volume=80, ask_volume=60, price=101.0)
        tracker.reset()
        assert tracker.cumulative_delta == 0.0
        state = tracker.state()
        assert state.value == 0.0
        assert state.slope == 0.0

    def test_session_boundary_auto_reset(self):
        """Time going backwards triggers auto-reset via update_bar."""
        tracker = CVDTracker()
        tracker.update_bar({
            "bar_index": 0, "buyVolume": 100, "sellVolume": 50,
            "close": 100.0, "time": "2024-01-01T10:00:00",
        })
        assert tracker.cumulative_delta != 0.0
        # New session (time goes backwards)
        tracker.update_bar({
            "bar_index": 0, "buyVolume": 80, "sellVolume": 40,
            "close": 100.0, "time": "2024-01-01T09:00:00",
        })
        # CVD should restart from new session's delta
        assert tracker.cumulative_delta == pytest.approx(40.0)


class TestCVDDivergence:
    """Tests for price vs CVD divergence detection."""

    def test_bullish_divergence(self):
        """Price down + CVD up = bullish divergence."""
        tracker = CVDTracker()
        # Build history: price going down but CVD going up
        prices = [105.0, 104.0, 103.0, 102.0, 101.0]
        for i, p in enumerate(prices):
            # High bid volume => positive delta => CVD rising
            tracker.update(bar_index=i, bid_volume=100, ask_volume=30, price=p)
        state = tracker.state()
        assert state.has_divergence is True
        assert state.divergence_type == "BULLISH_DIV"

    def test_bearish_divergence(self):
        """Price up + CVD down = bearish divergence."""
        tracker = CVDTracker()
        # Build history: price going up but CVD going down
        prices = [100.0, 101.0, 102.0, 103.0, 104.0]
        for i, p in enumerate(prices):
            # High ask volume => negative delta => CVD falling
            tracker.update(bar_index=i, bid_volume=30, ask_volume=100, price=p)
        state = tracker.state()
        assert state.has_divergence is True
        assert state.divergence_type == "BEARISH_DIV"

    def test_no_divergence_with_insufficient_data(self):
        """Less than 5 bars returns no divergence."""
        tracker = CVDTracker()
        for i in range(3):
            tracker.update(bar_index=i, bid_volume=50, ask_volume=50, price=100.0 + i)
        state = tracker.state()
        assert state.has_divergence is False
        assert state.divergence_type == "NONE"
