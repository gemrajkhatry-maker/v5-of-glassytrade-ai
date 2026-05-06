"""Max drawdown tracker - TDD cycle 1.1 (RED phase)."""
import pytest
from app.domain.risk.service.max_drawdown_tracker import MaxDrawdownTracker


class TestMaxDrawdownTracker:
    """Test max drawdown tracking and circuit breaker functionality."""

    def test_tracks_peak_equity(self):
        """Should track highest equity seen."""
        tracker = MaxDrawdownTracker(max_drawdown_pct=0.02)

        tracker.update(100000.0)
        tracker.update(105000.0)

        assert tracker.peak_equity == 105000.0

    def test_calculates_drawdown_correctly(self):
        """Should calculate drawdown percentage from peak."""
        tracker = MaxDrawdownTracker(max_drawdown_pct=0.02)
        tracker.update(100000.0)
        tracker.update(105000.0)  # Peak
        tracker.update(100000.0)  # Drop

        # Drawdown = (105000 - 100000) / 105000 = 0.0476
        assert tracker.current_drawdown_pct == pytest.approx(0.0476, rel=0.01)

    def test_halts_trading_at_max_drawdown(self):
        """Should halt when drawdown >= max threshold."""
        tracker = MaxDrawdownTracker(max_drawdown_pct=0.02)
        tracker.update(100000.0)
        tracker.update(105000.0)  # Peak
        tracker.update(102900.0)  # 2% drop from peak: (105000-102900)/105000 = 0.02

        assert tracker.halted is True
        assert tracker.can_trade is False

    def test_allows_trading_below_threshold(self):
        """Should allow trading when drawdown < threshold."""
        tracker = MaxDrawdownTracker(max_drawdown_pct=0.02)
        tracker.update(100000.0)
        tracker.update(101000.0)  # Peak
        tracker.update(99500.0)  # 1.48% drop: (101000-99500)/101000 = 0.0148

        assert tracker.halted is False
        assert tracker.can_trade is True

    def test_resets_on_new_session(self):
        """Should reset peak and halt flag on session reset."""
        tracker = MaxDrawdownTracker(max_drawdown_pct=0.02)
        tracker.update(100000.0)
        tracker.update(97000.0)  # Halted (3% drop)
        assert tracker.halted is True

        tracker.reset()

        assert tracker.halted is False
        assert tracker.peak_equity == 0.0

    def test_serializes_state(self):
        """Should support to_dict/load_from_dict for persistence."""
        tracker = MaxDrawdownTracker(max_drawdown_pct=0.02)
        tracker.update(100000.0)
        tracker.update(105000.0)

        state = tracker.to_dict()

        new_tracker = MaxDrawdownTracker(max_drawdown_pct=0.02)
        new_tracker.load_from_dict(state)

        assert new_tracker.peak_equity == 105000.0

    def test_handles_zero_equity_gracefully(self):
        """Should not crash on zero equity."""
        tracker = MaxDrawdownTracker(max_drawdown_pct=0.02)

        result = tracker.update(0.0)

        assert result is False
        assert tracker.halted is True

    def test_handles_negative_equity_gracefully(self):
        """Should not crash on negative equity."""
        tracker = MaxDrawdownTracker(max_drawdown_pct=0.02)

        result = tracker.update(-1000.0)

        assert result is False
        assert tracker.halted is True

    def test_current_equity_property(self):
        """Should track current equity (last update)."""
        tracker = MaxDrawdownTracker(max_drawdown_pct=0.02)
        tracker.update(100000.0)
        tracker.update(105000.0)
        tracker.update(103000.0)

        assert tracker.current_equity == 103000.0

    def test_drawdown_zero_when_at_peak(self):
        """Should report 0% drawdown when at peak equity."""
        tracker = MaxDrawdownTracker(max_drawdown_pct=0.02)
        tracker.update(100000.0)
        tracker.update(105000.0)  # Peak
        tracker.update(105000.0)  # Still at peak

        assert tracker.current_drawdown_pct == 0.0

    def test_halt_reason_provided(self):
        """Should provide reason for halt."""
        tracker = MaxDrawdownTracker(max_drawdown_pct=0.02)
        tracker.update(100000.0)
        tracker.update(105000.0)
        tracker.update(102000.0)  # Halted (2.86% drawdown)

        assert "drawdown" in tracker.halt_reason
        assert "105000.00" in tracker.halt_reason
