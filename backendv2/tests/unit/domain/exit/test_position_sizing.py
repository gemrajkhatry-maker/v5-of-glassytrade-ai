"""Tests for position sizing and pyramid management."""

import pytest
from app.domain.exit.service.position_sizer import PositionSizer, PositionSize
from app.domain.exit.service.pyramid_manager import PyramidManager, PyramidSignal


class TestPositionSizer:
    """Tests for fixed-fractional position sizing."""

    def test_calculates_standard_position(self):
        """Should calculate standard position size."""
        size = PositionSizer.calculate(
            equity=1_000_000.0,
            entry_price=100.0,
            stop_loss=99.0,  # 1 point risk
            point_value=50.0,
            risk_pct=0.005,  # 0.5%
        )
        
        assert size.valid is True
        assert size.lots >= 1
        assert size.risk_amount == pytest.approx(5_000.0, rel=0.1)  # 0.5% of 1M
        assert size.risk_pct == pytest.approx(0.005, rel=0.1)

    def test_rejects_zero_equity(self):
        """Should reject zero equity."""
        size = PositionSizer.calculate(
            equity=0.0,
            entry_price=100.0,
            stop_loss=99.0,
            point_value=50.0,
        )
        
        assert size.valid is False
        assert "Equity" in size.reason

    def test_rejects_negative_equity(self):
        """Should reject negative equity."""
        size = PositionSizer.calculate(
            equity=-1000.0,
            entry_price=100.0,
            stop_loss=99.0,
            point_value=50.0,
        )
        
        assert size.valid is False
        assert "Equity" in size.reason

    def test_rejects_stop_equals_entry(self):
        """Should reject when stop loss equals entry."""
        size = PositionSizer.calculate(
            equity=1_000_000.0,
            entry_price=100.0,
            stop_loss=100.0,
            point_value=50.0,
        )
        
        assert size.valid is False
        assert "Stop loss" in size.reason

    def test_rejects_zero_point_value(self):
        """Should reject zero point value."""
        size = PositionSizer.calculate(
            equity=1_000_000.0,
            entry_price=100.0,
            stop_loss=99.0,
            point_value=0.0,
        )
        
        assert size.valid is False
        assert "Point value" in size.reason

    def test_respects_absolute_ceiling(self):
        """Should cap risk at 1% of equity."""
        size = PositionSizer.calculate(
            equity=1_000_000.0,
            entry_price=100.0,
            stop_loss=99.9,  # Very tight stop = many lots
            point_value=50.0,
            risk_pct=0.005,
        )
        
        # Risk should not exceed 1% (10,000)
        assert size.risk_amount <= 10_000.0 + 1.0  # Small tolerance

    def test_returns_zero_lots_when_insufficient_equity(self):
        """Should return zero lots when equity insufficient for 1 lot."""
        size = PositionSizer.calculate(
            equity=100.0,  # Very small
            entry_price=100.0,
            stop_loss=90.0,  # 10 points risk
            point_value=50.0,  # 500 per lot risk
        )
        
        # 0.5% of 100 = 0.5, need 500 per lot, can't afford
        assert size.valid is False
        assert "Insufficient" in size.reason

    def test_calculates_correct_risk_amount(self):
        """Should calculate actual risk amount correctly."""
        size = PositionSizer.calculate(
            equity=500_000.0,
            entry_price=200.0,
            stop_loss=198.0,  # 2 points
            point_value=25.0,  # 50 per lot
        )
        
        # Risk amount = 0.5% of 500K = 2500
        # Per lot = 2 * 25 = 50
        # Lots = 2500 / 50 = 50
        # Actual risk = 50 * 50 = 2500
        assert size.valid is True
        assert size.lots == 50
        assert size.risk_amount == pytest.approx(2500.0, rel=0.01)

    def test_increases_lots_with_higher_equity(self):
        """Should allow more lots with higher equity."""
        size_low = PositionSizer.calculate(
            equity=500_000.0,
            entry_price=100.0,
            stop_loss=99.0,
            point_value=50.0,
        )
        size_high = PositionSizer.calculate(
            equity=2_000_000.0,
            entry_price=100.0,
            stop_loss=99.0,
            point_value=50.0,
        )
        
        assert size_high.lots > size_low.lots

    def test_decreases_lots_with_wider_stop(self):
        """Should reduce lots when stop is wider."""
        size_tight = PositionSizer.calculate(
            equity=1_000_000.0,
            entry_price=100.0,
            stop_loss=99.5,  # 0.5 points
            point_value=50.0,
        )
        size_wide = PositionSizer.calculate(
            equity=1_000_000.0,
            entry_price=100.0,
            stop_loss=98.0,  # 2 points
            point_value=50.0,
        )
        
        assert size_tight.lots > size_wide.lots


class TestVelocityScaling:
    """Tests for velocity-based position scaling."""

    def test_no_scaling_for_zero_velocity(self):
        """Should not scale when velocity is zero."""
        adjusted, reason = PositionSizer.apply_velocity_scaling(10, 0.0)
        
        assert adjusted == 10
        # Returns empty string when velocity is 0
        assert reason == ""

    def test_reduces_for_high_velocity(self):
        """Should reduce size 70% for high velocity."""
        adjusted, reason = PositionSizer.apply_velocity_scaling(10, 0.15)
        
        assert adjusted == 7  # 70% of 10
        assert "70% scale" in reason

    def test_moderate_scaling_for_medium_velocity(self):
        """Should reduce size 85% for moderate velocity."""
        adjusted, reason = PositionSizer.apply_velocity_scaling(10, 0.05)
        
        assert adjusted == 8  # 85% of 10
        assert "85% scale" in reason

    def test_full_size_for_low_velocity(self):
        """Should keep full size for low velocity."""
        adjusted, reason = PositionSizer.apply_velocity_scaling(10, 0.01)
        
        assert adjusted == 10
        assert "full size" in reason

    def test_minimum_one_lot(self):
        """Should never go below 1 lot."""
        adjusted, reason = PositionSizer.apply_velocity_scaling(1, 0.2)
        
        assert adjusted >= 1


class TestPyramidManager:
    """Tests for pyramid add-on logic."""

    def test_allows_first_add_when_conditions_met(self):
        """Should allow first add when in profit with aggression."""
        manager = PyramidManager()
        
        signal = manager.check_pyramid(
            entry_price=100.0,
            current_price=102.0,  # In profit
            is_long=True,
            aggression_score=3.5,  # Above 3.0 threshold
            add_count=0,  # First add
            entry_lvns=[99.0],
            current_lvn=101.0,  # Different LVN
            current_sl=99.0,
        )
        
        assert signal is not None
        assert signal.size_multiplier == 1.0  # 100% of base

    def test_allows_second_add_with_half_size(self):
        """Should allow second add with 50% size."""
        manager = PyramidManager()
        
        signal = manager.check_pyramid(
            entry_price=100.0,
            current_price=104.0,
            is_long=True,
            aggression_score=4.0,
            add_count=1,  # Second add
            entry_lvns=[99.0, 101.0],
            current_lvn=103.0,
            current_sl=100.0,
        )
        
        assert signal is not None
        assert signal.size_multiplier == 0.5  # 50% of base

    def test_blocks_after_max_adds(self):
        """Should block after 2 adds."""
        manager = PyramidManager()
        
        signal = manager.check_pyramid(
            entry_price=100.0,
            current_price=106.0,
            is_long=True,
            aggression_score=4.0,
            add_count=2,  # Already at max
            entry_lvns=[99.0, 101.0, 103.0],
            current_lvn=105.0,
            current_sl=102.0,
        )
        
        assert signal is None

    def test_requires_profit_for_long(self):
        """Should require profit for long positions."""
        manager = PyramidManager()
        
        signal = manager.check_pyramid(
            entry_price=100.0,
            current_price=99.0,  # Not in profit
            is_long=True,
            aggression_score=3.5,
            add_count=0,
            entry_lvns=[99.0],
            current_lvn=98.0,
            current_sl=97.0,
        )
        
        assert signal is None

    def test_requires_profit_for_short(self):
        """Should require profit for short positions."""
        manager = PyramidManager()
        
        signal = manager.check_pyramid(
            entry_price=100.0,
            current_price=101.0,  # Not in profit for short
            is_long=False,
            aggression_score=3.5,
            add_count=0,
            entry_lvns=[101.0],
            current_lvn=102.0,
            current_sl=103.0,
        )
        
        assert signal is None

    def test_requires_minimum_aggression(self):
        """Should require aggression ≥ 3.0."""
        manager = PyramidManager()
        
        signal = manager.check_pyramid(
            entry_price=100.0,
            current_price=102.0,
            is_long=True,
            aggression_score=2.5,  # Below threshold
            add_count=0,
            entry_lvns=[99.0],
            current_lvn=101.0,
            current_sl=99.0,
        )
        
        assert signal is None

    def test_requires_different_lvn(self):
        """Should require different LVN from previous entries."""
        manager = PyramidManager()
        
        signal = manager.check_pyramid(
            entry_price=100.0,
            current_price=102.0,
            is_long=True,
            aggression_score=3.5,
            add_count=0,
            entry_lvns=[101.0],  # Same LVN
            current_lvn=101.0,
            current_sl=99.0,
        )
        
        assert signal is None

    def test_sets_unified_stop_loss(self):
        """Should set unified stop loss for all entries."""
        manager = PyramidManager()
        
        signal = manager.check_pyramid(
            entry_price=100.0,
            current_price=102.0,
            is_long=True,
            aggression_score=3.5,
            add_count=0,
            entry_lvns=[99.0],
            current_lvn=101.0,
            current_sl=99.0,
        )
        
        assert signal is not None
        # SL should be moved up (for long)
        assert signal.unified_sl >= 99.0

    def test_works_for_short_positions(self):
        """Should work for short positions."""
        manager = PyramidManager()
        
        signal = manager.check_pyramid(
            entry_price=100.0,
            current_price=98.0,  # In profit for short
            is_long=False,
            aggression_score=3.5,
            add_count=0,
            entry_lvns=[101.0],
            current_lvn=99.0,
            current_sl=103.0,
        )
        
        assert signal is not None
        assert signal.size_multiplier == 1.0

    def test_calculates_level_as_current_price(self):
        """Should use current price as add level."""
        manager = PyramidManager()
        
        signal = manager.check_pyramid(
            entry_price=100.0,
            current_price=103.5,
            is_long=True,
            aggression_score=3.5,
            add_count=0,
            entry_lvns=[99.0],
            current_lvn=102.0,
            current_sl=99.0,
        )
        
        assert signal is not None
        assert signal.level == 103.5
