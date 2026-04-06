"""Unit tests for PartitionExitManager — P1/P2/P3 exits per Fabio FR-08."""

import pytest
from app.domain.fabio_ai.services.partition_exit_manager import (
    PartitionExitManager,
    PartitionState,
)


class TestPartitionExitP1:
    """FR-08-01: P1 exit at 33% of R if momentum weak."""

    def test_p1_exit_weak_momentum(self):
        """P1 exits when price reaches 33% R and CVD slope weak."""
        manager = PartitionExitManager()
        state = PartitionState()
        # LONG: entry=100, SL=99, R=1, 33%R = 0.33
        # Use 100.34 to ensure r_multiple > 0.33
        signals = manager.check_exits(
            entry_price=100.0, initial_stop=99.0, take_profit=102.0,
            current_price=100.34, is_long=True, cvd_slope=1.0, state=state,
        )
        assert any(s.exit_type == "PARTITION_1" for s in signals)
        assert state.p1_taken is True

    def test_p1_balanced_fires_unconditionally(self):
        """BALANCED: P1 fires at 0.25R regardless of CVD slope (mean reversion)."""
        manager = PartitionExitManager()
        state = PartitionState()
        # 0.33R profit, CVD strong — but BALANCED ignores CVD
        signals = manager.check_exits(
            entry_price=100.0, initial_stop=99.0, take_profit=102.0,
            current_price=100.33, is_long=True, cvd_slope=3.0, state=state,
            market_state="BALANCED",
        )
        assert any(s.exit_type == "PARTITION_1" for s in signals)
        assert state.p1_taken is True

    def test_p1_imbalanced_skipped(self):
        """IMBALANCED: P1 is skipped to let trend run."""
        manager = PartitionExitManager()
        state = PartitionState()
        signals = manager.check_exits(
            entry_price=100.0, initial_stop=99.0, take_profit=102.0,
            current_price=100.33, is_long=True, cvd_slope=0.1, state=state,
            market_state="IMBALANCED",
        )
        assert not any(s.exit_type == "PARTITION_1" for s in signals)
        assert state.p1_taken is False


class TestPartitionExitP2:
    """FR-08-03: P2 exit at target (always)."""

    def test_p2_exit_at_target(self):
        """P2 always exits at target."""
        manager = PartitionExitManager()
        state = PartitionState(p1_taken=True)
        signals = manager.check_exits(
            entry_price=100.0, initial_stop=99.0, take_profit=102.0,
            current_price=102.0, is_long=True, cvd_slope=1.0, state=state,
        )
        assert any(s.exit_type == "PARTITION_2" for s in signals)
        assert state.p2_taken is True


class TestPartitionExitP3:
    """FR-08-04: P3 trail if CVD slope > 2.0."""

    def test_p3_trail_strong_cvd(self):
        """P3 trail active when CVD slope > 2.0."""
        manager = PartitionExitManager()
        state = PartitionState(p1_taken=True, p2_taken=True)
        signals = manager.check_exits(
            entry_price=100.0, initial_stop=99.0, take_profit=103.0,
            current_price=102.5, is_long=True, cvd_slope=3.0, state=state,
        )
        # P3 should trail, not exit
        assert not any(s.exit_type == "PARTITION_3" for s in signals)

    def test_p3_exit_weak_cvd(self):
        """P3 exits when CVD slope weak."""
        manager = PartitionExitManager()
        state = PartitionState(p1_taken=True, p2_taken=True)
        signals = manager.check_exits(
            entry_price=100.0, initial_stop=99.0, take_profit=103.0,
            current_price=102.5, is_long=True, cvd_slope=1.0, state=state,
        )
        assert any(s.exit_type == "PARTITION_3" for s in signals)


class TestPartitionCounterAggression:
    """FR-08-06: Counter-aggression hard exit."""

    def test_counter_aggression_exit(self):
        """2+ opposite signals → exit ALL."""
        manager = PartitionExitManager()
        state = PartitionState(p1_taken=True, counter_aggression_count=2)
        signals = manager.check_exits(
            entry_price=100.0, initial_stop=99.0, take_profit=102.0,
            current_price=101.0, is_long=True, cvd_slope=1.0, state=state,
        )
        assert any(s.exit_type == "COUNTER_AGGRESSION" for s in signals)
