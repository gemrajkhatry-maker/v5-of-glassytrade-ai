"""Tests for PartitionExitManager.

Covers:
- PartitionState field naming consistency with PartitionExitManager
- Partition 1 exit (balanced vs imbalanced market)
- Partition 2 exit
- Partition 3 exit (trail and momentum weak)
- Counter-aggression override
- Breakeven tracking
- Trailing stop logic
"""

from __future__ import annotations

import pytest

from app.domain.exit.model.exit_models import ExitSignal, PartitionState
from app.domain.exit.service.partition_exit_manager import PartitionExitManager


def _manager() -> PartitionExitManager:
    return PartitionExitManager()


def _state(**kwargs) -> PartitionState:
    return PartitionState(**kwargs)


# ---------------------------------------------------------------------------
# 1. PartitionState field naming consistency
# ---------------------------------------------------------------------------

class TestPartitionStateFields:
    def test_state_has_p1_taken_field(self):
        """PartitionState must have p1_taken field used by manager."""
        state = _state()
        assert hasattr(state, "p1_taken")
        assert state.p1_taken is False

    def test_state_has_p2_taken_field(self):
        state = _state()
        assert hasattr(state, "p2_taken")
        assert state.p2_taken is False

    def test_state_has_p3_taken_field(self):
        state = _state()
        assert hasattr(state, "p3_taken")
        assert state.p3_taken is False

    def test_state_has_breakeven_set_field(self):
        state = _state()
        assert hasattr(state, "breakeven_set")
        assert state.breakeven_set is False

    def test_state_has_trail_sl_field(self):
        state = _state()
        assert hasattr(state, "trail_sl")
        assert state.trail_sl == 0.0

    def test_state_has_counter_aggression_count_field(self):
        state = _state()
        assert hasattr(state, "counter_aggression_count")
        assert state.counter_aggression_count == 0

    def test_manager_uses_correct_field_names(self):
        """PartitionExitManager.check_exits must use state field names that exist."""
        manager = _manager()
        state = _state()
        # Should not raise AttributeError
        manager.check_exits(
            entry_price=100.0,
            initial_stop=95.0,
            take_profit=110.0,
            current_price=105.0,
            is_long=True,
            cvd_slope=0.6,
            state=state,
            market_state="IMBALANCED",
        )


# ---------------------------------------------------------------------------
# 2. Partition 1 exit
# ---------------------------------------------------------------------------

class TestPartition1Exit:
    def test_p1_exit_at_1r_balanced_market(self):
        """In balanced market, P1 exits at 1.0R without CVD requirement."""
        manager = _manager()
        state = _state()
        risk = 5.0  # 100 - 95
        signals = manager.check_exits(
            entry_price=100.0,
            initial_stop=95.0,
            take_profit=110.0,
            current_price=100.0 + risk,  # exactly 1R
            is_long=True,
            cvd_slope=0.0,  # CVD doesn't matter in balanced
            state=state,
            market_state="BALANCED",
        )
        p1_signals = [s for s in signals if s.exit_type == "PARTITION_1"]
        assert len(p1_signals) == 1
        assert p1_signals[0].size_pct == 0.30
        assert state.p1_taken is True

    def test_p1_exit_requires_cvd_in_imbalanced_market(self):
        """In imbalanced market, P1 requires CVD confirmation."""
        manager = _manager()
        state = _state()
        risk = 5.0
        # CVD confirms (slope >= 0.5 for long)
        signals = manager.check_exits(
            entry_price=100.0,
            initial_stop=95.0,
            take_profit=110.0,
            current_price=100.0 + risk,
            is_long=True,
            cvd_slope=0.6,
            state=state,
            market_state="IMBALANCED",
        )
        p1_signals = [s for s in signals if s.exit_type == "PARTITION_1"]
        assert len(p1_signals) == 1
        assert state.p1_taken is True

    def test_p1_blocked_without_cvd_in_imbalanced(self):
        """In imbalanced market, P1 is blocked if CVD doesn't confirm."""
        manager = _manager()
        state = _state()
        risk = 5.0
        signals = manager.check_exits(
            entry_price=100.0,
            initial_stop=95.0,
            take_profit=110.0,
            current_price=100.0 + risk,
            is_long=True,
            cvd_slope=0.2,  # Below CVD_STRONG_SLOPE
            state=state,
            market_state="IMBALANCED",
        )
        p1_signals = [s for s in signals if s.exit_type == "PARTITION_1"]
        assert len(p1_signals) == 0
        assert state.p1_taken is False

    def test_p1_not_taken_below_1r(self):
        """P1 does not trigger below 1.0R."""
        manager = _manager()
        state = _state()
        signals = manager.check_exits(
            entry_price=100.0,
            initial_stop=95.0,
            take_profit=110.0,
            current_price=103.0,  # 0.6R
            is_long=True,
            cvd_slope=0.6,
            state=state,
            market_state="BALANCED",
        )
        assert all(s.exit_type != "PARTITION_1" for s in signals)
        assert state.p1_taken is False

    def test_p1_only_taken_once(self):
        """P1 is not triggered again after p1_taken=True."""
        manager = _manager()
        state = _state(p1_taken=True)
        signals = manager.check_exits(
            entry_price=100.0,
            initial_stop=95.0,
            take_profit=110.0,
            current_price=105.0,
            is_long=True,
            cvd_slope=0.6,
            state=state,
            market_state="BALANCED",
        )
        assert all(s.exit_type != "PARTITION_1" for s in signals)


# ---------------------------------------------------------------------------
# 3. Partition 2 exit
# ---------------------------------------------------------------------------

class TestPartition2Exit:
    def test_p2_exit_at_2r(self):
        """P2 exits at 2.0R."""
        manager = _manager()
        state = _state()
        risk = 5.0
        signals = manager.check_exits(
            entry_price=100.0,
            initial_stop=95.0,
            take_profit=110.0,
            current_price=100.0 + 2 * risk,  # 2R
            is_long=True,
            cvd_slope=0.0,
            state=state,
            market_state="BALANCED",
        )
        p2_signals = [s for s in signals if s.exit_type == "PARTITION_2"]
        assert len(p2_signals) == 1
        assert p2_signals[0].size_pct == 0.40
        assert state.p2_taken is True

    def test_p2_sets_trailing_stop(self):
        """P2 sets trail_sl to current price."""
        manager = _manager()
        state = _state()
        risk = 5.0
        manager.check_exits(
            entry_price=100.0,
            initial_stop=95.0,
            take_profit=110.0,
            current_price=100.0 + 2 * risk,
            is_long=True,
            cvd_slope=0.0,
            state=state,
            market_state="BALANCED",
        )
        assert state.trail_sl == 110.0  # current price at 2R

    def test_p2_not_taken_below_2r(self):
        manager = _manager()
        state = _state()
        signals = manager.check_exits(
            entry_price=100.0,
            initial_stop=95.0,
            take_profit=110.0,
            current_price=108.0,  # 1.6R
            is_long=True,
            cvd_slope=0.0,
            state=state,
            market_state="BALANCED",
        )
        assert all(s.exit_type != "PARTITION_2" for s in signals)
        assert state.p2_taken is False


# ---------------------------------------------------------------------------
# 4. Partition 3 exit
# ---------------------------------------------------------------------------

class TestPartition3Exit:
    def test_p3_exits_when_momentum_weak_after_p2(self):
        """After P2, if CVD is weak, P3 closes the runner."""
        manager = _manager()
        state = _state(p2_taken=True)
        signals = manager.check_exits(
            entry_price=100.0,
            initial_stop=95.0,
            take_profit=110.0,
            current_price=108.0,
            is_long=True,
            cvd_slope=0.0,  # Weak momentum
            state=state,
            market_state="BALANCED",
        )
        p3_signals = [s for s in signals if s.exit_type == "PARTITION_3"]
        assert len(p3_signals) == 1
        assert p3_signals[0].size_pct == 0.30
        assert state.p3_taken is True

    def test_p3_not_taken_if_cvd_strong_and_remaining(self):
        """After P2, strong CVD keeps the runner open (no P3)."""
        manager = _manager()
        state = _state(p2_taken=True, trail_sl=0.0)
        signals = manager.check_exits(
            entry_price=100.0,
            initial_stop=95.0,
            take_profit=110.0,
            current_price=108.0,
            is_long=True,
            cvd_slope=0.6,  # Strong momentum
            state=state,
            market_state="BALANCED",
        )
        # With strong CVD and remaining > 0, it should trail, not exit P3
        p3_signals = [s for s in signals if s.exit_type == "PARTITION_3"]
        assert len(p3_signals) == 0
        # But trail_sl should have been updated
        assert state.trail_sl > 0.0

    def test_p3_trail_sl_hit(self):
        """After P2, if price hits trail_sl, P3 exits with TRAIL type."""
        manager = _manager()
        state = _state(p1_taken=True, p2_taken=True, breakeven_set=True, trail_sl=107.0)
        signals = manager.check_exits(
            entry_price=100.0,
            initial_stop=95.0,
            take_profit=110.0,
            current_price=106.0,  # Below trail_sl
            is_long=True,
            cvd_slope=0.6,  # Strong CVD so momentum-weak path is skipped
            state=state,
            market_state="BALANCED",
        )
        trail_signals = [s for s in signals if s.exit_type == "TRAIL"]
        assert len(trail_signals) == 1
        assert state.p3_taken is True


# ---------------------------------------------------------------------------
# 5. Breakeven tracking
# ---------------------------------------------------------------------------

class TestBreakevenTracking:
    def test_breakeven_set_at_1r_toward_target(self):
        """Breakeven is set when price moves 1R toward target."""
        manager = _manager()
        state = _state(breakeven_set=False)
        risk = 5.0
        manager.check_exits(
            entry_price=100.0,
            initial_stop=95.0,
            take_profit=110.0,
            current_price=100.0 + risk,  # 1R toward target
            is_long=True,
            cvd_slope=0.0,
            state=state,
            market_state="BALANCED",
        )
        assert state.breakeven_set is True
        assert state.trail_sl == 100.0  # entry price = breakeven

    def test_breakeven_not_set_below_1r(self):
        manager = _manager()
        state = _state(breakeven_set=False)
        manager.check_exits(
            entry_price=100.0,
            initial_stop=95.0,
            take_profit=110.0,
            current_price=103.0,  # 0.6R
            is_long=True,
            cvd_slope=0.0,
            state=state,
            market_state="BALANCED",
        )
        assert state.breakeven_set is False


# ---------------------------------------------------------------------------
# 6. Counter-aggression override
# ---------------------------------------------------------------------------

class TestCounterAggression:
    def test_counter_aggression_full_exit_at_2(self):
        """When counter_aggression_count >= 2, full exit."""
        manager = _manager()
        state = _state(counter_aggression_count=2)
        signals = manager.check_exits(
            entry_price=100.0,
            initial_stop=95.0,
            take_profit=110.0,
            current_price=105.0,
            is_long=True,
            cvd_slope=0.0,
            state=state,
            market_state="BALANCED",
        )
        counter_signals = [s for s in signals if s.exit_type == "COUNTER_AGGRESSION"]
        assert len(counter_signals) == 1
        assert counter_signals[0].size_pct == 1.0  # Full exit

    def test_counter_aggression_increments_on_opposite_direction(self):
        """Counter-aggression count increments when signal opposes position."""
        manager = _manager()
        state = _state(counter_aggression_count=0)
        manager.record_counter_aggression(state, "SHORT", "LONG")
        assert state.counter_aggression_count == 1

    def test_counter_aggression_no_increment_on_same_direction(self):
        manager = _manager()
        state = _state(counter_aggression_count=0)
        manager.record_counter_aggression(state, "LONG", "LONG")
        assert state.counter_aggression_count == 0


# ---------------------------------------------------------------------------
# 7. Short position tests
# ---------------------------------------------------------------------------

class TestShortPosition:
    def test_p1_exit_short_balanced(self):
        """P1 exit works for SHORT positions in balanced market."""
        manager = _manager()
        state = _state()
        risk = 5.0  # 105 - 100
        signals = manager.check_exits(
            entry_price=100.0,
            initial_stop=105.0,
            take_profit=90.0,
            current_price=100.0 - risk,  # 1R profit
            is_long=False,
            cvd_slope=-0.6,
            state=state,
            market_state="BALANCED",
        )
        p1_signals = [s for s in signals if s.exit_type == "PARTITION_1"]
        assert len(p1_signals) == 1
        assert state.p1_taken is True

    def test_p2_exit_short_at_2r(self):
        manager = _manager()
        state = _state()
        risk = 5.0
        signals = manager.check_exits(
            entry_price=100.0,
            initial_stop=105.0,
            take_profit=90.0,
            current_price=100.0 - 2 * risk,
            is_long=False,
            cvd_slope=0.0,
            state=state,
            market_state="BALANCED",
        )
        p2_signals = [s for s in signals if s.exit_type == "PARTITION_2"]
        assert len(p2_signals) == 1
        assert state.p2_taken is True

    def test_breakeven_set_short(self):
        """Breakeven is set for SHORT at 1R toward target."""
        manager = _manager()
        state = _state(breakeven_set=False)
        risk = 5.0
        manager.check_exits(
            entry_price=100.0,
            initial_stop=105.0,
            take_profit=90.0,
            current_price=100.0 - risk,
            is_long=False,
            cvd_slope=0.0,
            state=state,
            market_state="BALANCED",
        )
        assert state.breakeven_set is True
        assert state.trail_sl == 100.0


# ---------------------------------------------------------------------------
# 8. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_zero_risk_returns_empty(self):
        """When entry == stop (zero risk), no exit signals."""
        manager = _manager()
        state = _state()
        signals = manager.check_exits(
            entry_price=100.0,
            initial_stop=100.0,
            take_profit=110.0,
            current_price=105.0,
            is_long=True,
            cvd_slope=0.0,
            state=state,
        )
        assert signals == []

    def test_negative_risk_returns_empty(self):
        manager = _manager()
        state = _state()
        signals = manager.check_exits(
            entry_price=100.0,
            initial_stop=105.0,
            take_profit=110.0,
            current_price=102.0,
            is_long=True,  # stop above entry for long = invalid
            cvd_slope=0.0,
            state=state,
        )
        assert signals == []
