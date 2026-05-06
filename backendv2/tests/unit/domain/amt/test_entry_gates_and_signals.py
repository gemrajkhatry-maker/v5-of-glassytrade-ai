"""Tests for entry gates, signal generation, and RR validation."""

import pytest
from app.domain.amt.service.entry_gates import calculate_position_size, run_entry_gates
from app.domain.amt.service.signal_generator import (
    _evaluate_rr,
    _is_near_level,
    _current_phase,
    WAITING,
    ABSORBING,
    ACCUMULATING,
)
from app.domain.amt.service.rr_validator import RRValidator, RRValidationResult
from app.domain.amt.model.amt_models import Absorption


class TestPositionSizing:
    """Tests for entry gate position sizing."""

    def test_calculates_standard_position(self):
        """Should calculate standard position size."""
        lots, risk, valid = calculate_position_size(
            equity=1_000_000.0,
            entry_price=100.0,
            stop_loss=99.0,
            point_value=50.0,
            risk_pct=0.005,
        )
        
        assert valid is True
        assert lots >= 1
        assert risk > 0

    def test_applies_velocity_scaling(self):
        """Should reduce size when velocity is high."""
        lots_normal, _, _ = calculate_position_size(
            equity=1_000_000.0,
            entry_price=100.0,
            stop_loss=99.0,
            point_value=50.0,
            price_velocity=0.0,
        )
        lots_fast, _, _ = calculate_position_size(
            equity=1_000_000.0,
            entry_price=100.0,
            stop_loss=99.0,
            point_value=50.0,
            price_velocity=0.15,  # High velocity
        )
        
        assert lots_fast < lots_normal

    def test_rejects_invalid_position(self):
        """Should reject when position sizing fails."""
        lots, risk, valid = calculate_position_size(
            equity=0.0,  # Zero equity
            entry_price=100.0,
            stop_loss=99.0,
            point_value=50.0,
        )
        
        assert valid is False
        assert lots == 0
        assert risk == 0.0


class TestEntryGates:
    """Tests for entry gate pipeline."""

    def test_run_entry_gates_returns_tuple(self):
        """Should return tuple with gate result."""
        # Minimal test - just verify it runs without error
        result = run_entry_gates(
            data=[],
            amt_result=None,
            tick={},
        )
        
        assert isinstance(result, tuple)
        assert len(result) == 5  # (passed, side, reason, lots, risk)


class TestSignalHelpers:
    """Tests for signal generation helper functions."""

    def test_evaluate_rr_calculates_ratio(self):
        """Should calculate R:R ratio correctly."""
        rr = _evaluate_rr(entry=100.0, stop=99.0, take_profit=102.0)
        
        # Risk = 1, Reward = 2, RR = 2.0
        assert rr == pytest.approx(2.0, rel=0.01)

    def test_evaluate_rr_zero_risk(self):
        """Should return 0 when risk is zero."""
        rr = _evaluate_rr(entry=100.0, stop=100.0, take_profit=102.0)
        
        assert rr == 0.0

    def test_is_near_level_true(self):
        """Should return True when price near level."""
        result = _is_near_level(price=100.5, level=100.0, step=1.0)
        
        # Tolerance = max(1.0 * 2.5, 1.0) = 2.5
        # |100.5 - 100.0| = 0.5 <= 2.5
        assert result is True

    def test_is_near_level_false(self):
        """Should return False when price far from level."""
        result = _is_near_level(price=105.0, level=100.0, step=1.0)
        
        # |105.0 - 100.0| = 5.0 > 2.5
        assert result is False

    def test_current_phase_waiting_no_absorptions(self):
        """Should return WAITING when no absorptions."""
        bars = [{"close": 100.0}]
        phase, bars_since, idx = _current_phase(bars, [], min_accumulation_bars=3)
        
        assert phase == WAITING
        assert bars_since == 0
        assert idx == -1

    def test_current_phase_absorbing_recent_absorption(self):
        """Should return ABSORBING when absorption is recent."""
        bars = [{"close": 100.0}] * 10
        absorptions = [Absorption(bar_index=8, price=100.0, volume=1000, side="BUY", strength=0.8)]
        
        phase, bars_since, idx = _current_phase(bars, absorptions, min_accumulation_bars=3)
        
        # Last bar is index 9, absorption at 8, bars_since = 9 - 8 = 1
        assert phase == ABSORBING
        assert bars_since == 1

    def test_current_phase_accumulating_enough_bars(self):
        """Should return ACCUMULATING when enough bars since absorption."""
        bars = [{"close": 100.0}] * 10
        absorptions = [Absorption(bar_index=5, price=100.0, volume=1000, side="BUY", strength=0.8)]
        
        phase, bars_since, idx = _current_phase(bars, absorptions, min_accumulation_bars=3)
        
        # Last bar is index 9, absorption at 5, bars_since = 9 - 5 = 4
        assert phase == ACCUMULATING
        assert bars_since == 4


class TestRRValidator:
    """Tests for dynamic R:R validation with live Ask price."""

    def test_validates_good_rr_long(self):
        """Should validate good R:R for long position."""
        validator = RRValidator(min_rr=1.5)
        
        result = validator.validate_live_ask(
            entry_ltp=100.0,
            stop_loss=99.0,
            take_profit=103.0,
            live_ask=100.5,
            is_long=True,
        )
        
        # Risk = 100.5 - 99.0 = 1.5
        # Reward = 103.0 - 100.5 = 2.5
        # RR = 2.5 / 1.5 = 1.67 >= 1.5
        assert result.valid is True
        assert result.rr_ratio == pytest.approx(1.67, rel=0.01)
        assert result.live_risk == 1.5
        assert result.live_reward == 2.5

    def test_validates_good_rr_short(self):
        """Should validate good R:R for short position."""
        validator = RRValidator(min_rr=1.5)
        
        result = validator.validate_live_ask(
            entry_ltp=100.0,
            stop_loss=101.0,
            take_profit=97.0,
            live_ask=99.5,
            is_long=False,
        )
        
        # Risk = 101.0 - 99.5 = 1.5
        # Reward = 99.5 - 97.0 = 2.5
        # RR = 2.5 / 1.5 = 1.67
        assert result.valid is True
        assert result.rr_ratio == pytest.approx(1.67, rel=0.01)

    def test_rejects_bad_rr(self):
        """Should reject when R:R below minimum."""
        validator = RRValidator(min_rr=1.5)
        
        result = validator.validate_live_ask(
            entry_ltp=100.0,
            stop_loss=99.0,
            take_profit=100.5,  # Small reward
            live_ask=100.2,
            is_long=True,
        )
        
        # Risk = 100.2 - 99.0 = 1.2
        # Reward = 100.5 - 100.2 = 0.3
        # RR = 0.3 / 1.2 = 0.25 < 1.5
        assert result.valid is False
        assert result.rr_ratio == pytest.approx(0.25, rel=0.01)

    def test_rejects_ask_beyond_stop(self):
        """Should reject when live Ask beyond stop loss."""
        validator = RRValidator(min_rr=1.5)
        
        result = validator.validate_live_ask(
            entry_ltp=100.0,
            stop_loss=99.0,
            take_profit=103.0,
            live_ask=98.0,  # Below stop
            is_long=True,
        )
        
        assert result.valid is False
        assert "beyond stop" in result.reason.lower()

    def test_rejects_invalid_prices(self):
        """Should reject invalid prices."""
        validator = RRValidator()
        
        result = validator.validate_live_ask(
            entry_ltp=100.0,
            stop_loss=0.0,  # Invalid
            take_profit=103.0,
            live_ask=100.5,
            is_long=True,
        )
        
        assert result.valid is False
        assert "Invalid" in result.reason

    def test_accounts_for_slippage(self):
        """Should show reduced R:R with slippage."""
        validator = RRValidator(min_rr=1.5)
        
        # Perfect entry
        perfect = validator.validate_live_ask(
            entry_ltp=100.0,
            stop_loss=99.0,
            take_profit=103.0,
            live_ask=100.0,
            is_long=True,
        )
        
        # Slippage of 0.5
        slippage = validator.validate_live_ask(
            entry_ltp=100.0,
            stop_loss=99.0,
            take_profit=103.0,
            live_ask=100.5,
            is_long=True,
        )
        
        # Slippage should reduce R:R
        assert slippage.rr_ratio < perfect.rr_ratio

    def test_returns_complete_result(self):
        """Should return complete RRValidationResult."""
        validator = RRValidator()
        
        result = validator.validate_live_ask(
            entry_ltp=100.0,
            stop_loss=99.0,
            take_profit=103.0,
            live_ask=100.5,
            is_long=True,
        )
        
        assert isinstance(result, RRValidationResult)
        assert isinstance(result.valid, bool)
        assert result.rr_ratio >= 0.0
        assert result.live_ask == 100.5
        assert result.live_risk > 0.0
        assert result.live_reward > 0.0
        assert isinstance(result.reason, str)

    def test_default_min_rr_is_1_5(self):
        """Should use 1.5 as default minimum R:R."""
        validator = RRValidator()
        
        # R:R = 1.4 should fail
        result = validator.validate_live_ask(
            entry_ltp=100.0,
            stop_loss=99.0,
            take_profit=101.4,
            live_ask=100.0,
            is_long=True,
        )
        
        # RR = 1.4 / 1.0 = 1.4 < 1.5
        assert result.valid is False

    def test_custom_min_rr(self):
        """Should accept custom minimum R:R."""
        validator = RRValidator(min_rr=2.0)
        
        result = validator.validate_live_ask(
            entry_ltp=100.0,
            stop_loss=99.0,
            take_profit=102.5,
            live_ask=100.0,
            is_long=True,
        )
        
        # RR = 2.5 / 1.0 = 2.5 >= 2.0
        assert result.valid is True

    def test_attractive_rr_remains_valid(self):
        """Should keep attractive trades valid."""
        validator = RRValidator(min_rr=1.5)
        
        result = validator.validate_live_ask(
            entry_ltp=100.0,
            stop_loss=99.0,
            take_profit=105.0,  # 5:1 R:R
            live_ask=100.3,  # Small slippage
            is_long=True,
        )
        
        # Risk = 1.3, Reward = 4.7, RR = 3.62
        assert result.valid is True
        assert result.rr_ratio >= 3.0
