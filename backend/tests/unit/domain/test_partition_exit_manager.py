"""Unit tests for PartitionExitManager — P1/P2/P3 exits per Fabio AMT spec (FR-08).

Fabio spec partition sizes: P1=30% @ 1R, P2=40% @ 2R, P3=30% trail
"""

import pytest
from app.domain.fabio_ai.services.partition_exit_manager import (
    PartitionExitManager,
    PartitionState,
)


class TestPartitionExitP1:
    """FR-08-01: P1 exit at 1R — first unit of risk locked."""

    def test_p1_fires_at_1r(self):
        """P1 exits when price reaches 1.0R in BALANCED regime."""
        manager = PartitionExitManager()
        state = PartitionState()
        # LONG: entry=100, SL=99, R=1, 1R = 101.00
        signals = manager.check_exits(
            entry_price=100.0, initial_stop=99.0, take_profit=102.0,
            current_price=101.0, is_long=True, cvd_slope=1.0, state=state,
        )
        assert any(s.exit_type == "PARTITION_1" for s in signals)
        assert state.p1_taken is True

    def test_p1_does_not_fire_before_1r(self):
        """P1 must NOT fire at 0.25R, 0.33R, or 0.5R — only at 1R+."""
        manager = PartitionExitManager()
        state = PartitionState()
        # 0.33R = 100.33 — should NOT fire
        signals = manager.check_exits(
            entry_price=100.0, initial_stop=99.0, take_profit=102.0,
            current_price=100.34, is_long=True, cvd_slope=1.0, state=state,
        )
        assert not any(s.exit_type == "PARTITION_1" for s in signals)
        assert state.p1_taken is False

        # 0.5R = 100.50 — still too early
        state2 = PartitionState()
        signals2 = manager.check_exits(
            entry_price=100.0, initial_stop=99.0, take_profit=102.0,
            current_price=100.50, is_long=True, cvd_slope=1.0, state=state2,
        )
        assert not any(s.exit_type == "PARTITION_1" for s in signals2)
        assert state2.p1_taken is False

    def test_p1_balanced_fires_at_1r(self):
        """BALANCED: P1 fires at 1R regardless of CVD slope (mean reversion)."""
        manager = PartitionExitManager()
        state = PartitionState()
        signals = manager.check_exits(
            entry_price=100.0, initial_stop=99.0, take_profit=102.0,
            current_price=101.0, is_long=True, cvd_slope=0.0, state=state,
            market_state="BALANCED",
        )
        assert any(s.exit_type == "PARTITION_1" for s in signals)
        assert state.p1_taken is True

    def test_p1_imbalanced_requires_cvd_confirmation(self):
        """IMBALANCED: P1 fires at 1R only if CVD confirms direction."""
        manager = PartitionExitManager()
        # CVD too weak — no fire
        state_weak = PartitionState()
        signals = manager.check_exits(
            entry_price=100.0, initial_stop=99.0, take_profit=102.0,
            current_price=101.0, is_long=True, cvd_slope=0.1, state=state_weak,
            market_state="IMBALANCED",
        )
        assert not any(s.exit_type == "PARTITION_1" for s in signals)
        assert state_weak.p1_taken is False

        # CVD strong enough — fire
        state_confirm = PartitionState()
        signals2 = manager.check_exits(
            entry_price=100.0, initial_stop=99.0, take_profit=102.0,
            current_price=101.0, is_long=True, cvd_slope=0.6, state=state_confirm,
            market_state="IMBALANCED",
        )
        assert any(s.exit_type == "PARTITION_1" for s in signals2)
        assert state_confirm.p1_taken is True

    def test_p1_imbalanced_skipped_below_1r(self):
        """IMBALANCED: P1 never fires below 1R regardless of CVD."""
        manager = PartitionExitManager()
        state = PartitionState()
        signals = manager.check_exits(
            entry_price=100.0, initial_stop=99.0, take_profit=102.0,
            current_price=100.33, is_long=True, cvd_slope=1.0, state=state,
            market_state="IMBALANCED",
        )
        assert not any(s.exit_type == "PARTITION_1" for s in signals)
        assert state.p1_taken is False


class TestPartitionExitP2:
    """FR-08-03: P2 exit at 2R — second unit of risk locked."""

    def test_p2_fires_at_2r(self):
        """P2 exits when price reaches 2.0R."""
        manager = PartitionExitManager()
        # LONG: entry=100, SL=99, R=1, 2R = 102.00
        state = PartitionState()
        signals = manager.check_exits(
            entry_price=100.0, initial_stop=99.0, take_profit=102.0,
            current_price=102.0, is_long=True, cvd_slope=1.0, state=state,
        )
        assert any(s.exit_type == "PARTITION_2" for s in signals)
        assert state.p2_taken is True

    def test_p2_does_not_fire_before_2r(self):
        """P2 must NOT fire below 2R, even at signal target."""
        manager = PartitionExitManager()
        state = PartitionState()
        # 1.5R — not yet 2R
        signals = manager.check_exits(
            entry_price=100.0, initial_stop=99.0, take_profit=101.50,
            current_price=101.50, is_long=True, cvd_slope=1.0, state=state,
        )
        assert not any(s.exit_type == "PARTITION_2" for s in signals)
        assert state.p2_taken is False

    def test_p2_at_2r_even_if_target_higher(self):
        """P2 fires at 2R even if signal TP is further out."""
        manager = PartitionExitManager()
        state = PartitionState()
        # Signal TP = 105 (5R), but we are at 2R
        signals = manager.check_exits(
            entry_price=100.0, initial_stop=99.0, take_profit=105.0,
            current_price=102.0, is_long=True, cvd_slope=1.0, state=state,
        )
        assert any(s.exit_type == "PARTITION_2" for s in signals)
        assert state.p2_taken is True


class TestPartitionExitP3:
    """FR-08-04: P3 trail if CVD slope > 2.0, else exit."""

    def test_p3_trail_strong_cvd(self):
        """P3 trail active when CVD slope > 2.0 (no exit)."""
        manager = PartitionExitManager()
        state = PartitionState(p1_taken=True, p2_taken=True)
        # entry=100, SL=99, R=1, 2R=102
        signals = manager.check_exits(
            entry_price=100.0, initial_stop=99.0, take_profit=105.0,
            current_price=102.5, is_long=True, cvd_slope=3.0, state=state,
        )
        # P3 should trail, not exit
        assert not any(s.exit_type == "PARTITION_3" for s in signals)
        assert state.trail_sl > 0  # trail SL was set

    def test_p3_exit_weak_cvd(self):
        """P3 exits when CVD slope weak (below CVD_STRONG_SLOPE=2.0)."""
        manager = PartitionExitManager()
        state = PartitionState(p1_taken=True, p2_taken=True)
        signals = manager.check_exits(
            entry_price=100.0, initial_stop=99.0, take_profit=105.0,
            current_price=102.5, is_long=True, cvd_slope=1.0, state=state,
        )
        assert any(s.exit_type == "PARTITION_3" for s in signals)
        assert state.p3_taken is True

    def test_p3_partition_size_is_30_percent(self):
        """P3 partition size must be 30% per Fabio spec."""
        manager = PartitionExitManager()
        assert manager.P3_SIZE == 0.30


class TestPartitionSizes:
    """Fr-08: Partition sizes must sum to 100% and match Fabio spec."""

    def test_partition_sizes_sum_to_one(self):
        """30% + 40% + 30% = 100%."""
        manager = PartitionExitManager()
        assert pytest.approx(manager.P1_SIZE + manager.P2_SIZE + manager.P3_SIZE) == 1.0

    def test_p1_size(self):
        assert PartitionExitManager.P1_SIZE == 0.30

    def test_p2_size(self):
        assert PartitionExitManager.P2_SIZE == 0.40

    def test_p3_size(self):
        assert PartitionExitManager.P3_SIZE == 0.30


class TestBreakEven:
    """Break-even should fire at 1R toward target (CVD-based BE handled by TradeManager)."""

    def test_be_fires_at_1r(self):
        """Break-even sets at 1.0R toward target."""
        manager = PartitionExitManager()
        state = PartitionState()
        # entry=100, SL=99, R=1, TP=102 — 1R toward target = 101.00
        signals = manager.check_exits(
            entry_price=100.0, initial_stop=99.0, take_profit=102.0,
            current_price=101.0, is_long=True, cvd_slope=1.0, state=state,
        )
        assert state.breakeven_set is True
        assert state.trail_sl == 100.0  # entry price

    def test_be_does_not_fire_below_1r(self):
        """Break-even must NOT fire at 0.35R."""
        manager = PartitionExitManager()
        state = PartitionState()
        signals = manager.check_exits(
            entry_price=100.0, initial_stop=99.0, take_profit=102.0,
            current_price=100.35, is_long=True, cvd_slope=1.0, state=state,
        )
        assert state.breakeven_set is False


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
