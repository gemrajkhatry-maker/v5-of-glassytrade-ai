"""Breakeven engine with 1R and CVD-based logic - TDD cycle 1.2 (RED phase)."""
import pytest
from app.domain.exit.service.breakeven_engine import BreakevenEngine, BreakevenResult


class TestBreakevenAt1R:
    """Test breakeven logic: 1R profit OR CVD confirmation (whichever first)."""

    def test_moves_to_be_at_1r_profit_long(self):
        """Should move to breakeven when LONG profit >= risk distance (1R)."""
        engine = BreakevenEngine()

        # Entry: 100, SL: 98, Risk = 2 points
        result = engine.check_breakeven(
            entry_price=100.0,
            stop_loss=98.0,
            current_price=102.0,  # +2 points = 1R
            side="LONG",
        )

        assert result.should_move_to_be is True
        assert result.new_stop_loss == 100.0  # Breakeven
        assert result.reason == "1R profit reached"

    def test_moves_to_be_at_1r_profit_short(self):
        """Should move to breakeven when SHORT profit >= risk distance (1R)."""
        engine = BreakevenEngine()

        # Entry: 100, SL: 102, Risk = 2 points
        result = engine.check_breakeven(
            entry_price=100.0,
            stop_loss=102.0,
            current_price=98.0,  # -2 points = 1R profit
            side="SHORT",
        )

        assert result.should_move_to_be is True
        assert result.new_stop_loss == 100.0
        assert result.reason == "1R profit reached"

    def test_does_not_move_before_1r(self):
        """Should NOT move to BE before 1R profit."""
        engine = BreakevenEngine()

        result = engine.check_breakeven(
            entry_price=100.0,
            stop_loss=98.0,
            current_price=101.0,  # +1 point = 0.5R
            side="LONG",
        )

        assert result.should_move_to_be is False
        assert result.reason == "Not yet at breakeven threshold"

    def test_cvd_confirms_faster_be_long(self):
        """Should move to BE faster if CVD confirms LONG direction."""
        engine = BreakevenEngine()

        result = engine.check_breakeven(
            entry_price=100.0,
            stop_loss=98.0,
            current_price=101.0,  # Only 0.5R
            side="LONG",
            cvd_confirms=True,
            bars_held=2,
        )

        # CVD confirmation after 2 bars = faster BE at 0.5R
        assert result.should_move_to_be is True
        assert result.new_stop_loss == 100.0
        assert result.reason == "CVD confirms direction"

    def test_cvd_confirms_faster_be_short(self):
        """Should move to BE faster if CVD confirms SHORT direction."""
        engine = BreakevenEngine()

        result = engine.check_breakeven(
            entry_price=100.0,
            stop_loss=102.0,
            current_price=99.0,  # Only 0.5R profit
            side="SHORT",
            cvd_confirms=True,
            bars_held=3,
        )

        assert result.should_move_to_be is True
        assert result.new_stop_loss == 100.0
        assert result.reason == "CVD confirms direction"

    def test_cvd_requires_minimum_bars(self):
        """Should NOT move to BE on CVD if held < 2 bars."""
        engine = BreakevenEngine()

        result = engine.check_breakeven(
            entry_price=100.0,
            stop_loss=98.0,
            current_price=101.0,  # 0.5R
            side="LONG",
            cvd_confirms=True,
            bars_held=1,  # Too early
        )

        assert result.should_move_to_be is False

    def test_cvd_requires_minimum_profit(self):
        """Should NOT move to BE on CVD if profit < 0.5R."""
        engine = BreakevenEngine()

        result = engine.check_breakeven(
            entry_price=100.0,
            stop_loss=98.0,
            current_price=100.5,  # Only 0.25R
            side="LONG",
            cvd_confirms=True,
            bars_held=3,
        )

        assert result.should_move_to_be is False

    def test_legacy_50_percent_tp_mode(self):
        """Should support legacy 50% TP partial in legacy mode."""
        engine = BreakevenEngine(legacy_mode=True)

        # Entry: 100, SL: 98, TP would be 104 (3R)
        # At 101 = 50% of TP distance (from 100 to 104)
        result = engine.check_breakeven(
            entry_price=100.0,
            stop_loss=98.0,
            current_price=101.0,  # 50% toward TP
            side="LONG",
        )

        # In legacy mode, should suggest partial at 50% TP
        assert result.should_take_partial is True
        assert result.partial_pct == 0.5
        assert result.reason == "50% TP partial (legacy)"

    def test_1r_takes_priority_over_cvd(self):
        """Should use 1R BE (not CVD) when both conditions met."""
        engine = BreakevenEngine()

        result = engine.check_breakeven(
            entry_price=100.0,
            stop_loss=98.0,
            current_price=102.0,  # 1R profit
            side="LONG",
            cvd_confirms=True,
            bars_held=3,
        )

        # 1R should be the reason (higher priority)
        assert result.should_move_to_be is True
        assert result.reason == "1R profit reached"

    def test_invalid_stop_loss_returns_false(self):
        """Should return False if stop loss equals entry."""
        engine = BreakevenEngine()

        result = engine.check_breakeven(
            entry_price=100.0,
            stop_loss=100.0,  # Invalid
            current_price=101.0,
            side="LONG",
        )

        assert result.should_move_to_be is False
        assert "Invalid" in result.reason

    def test_exact_1r_threshold(self):
        """Should trigger BE at exactly 1R (not just above)."""
        engine = BreakevenEngine()

        result = engine.check_breakeven(
            entry_price=100.0,
            stop_loss=98.0,
            current_price=102.0,  # Exactly 1R: (102-100)/(100-98) = 1.0
            side="LONG",
        )

        assert result.should_move_to_be is True

    def test_just_below_1r_threshold(self):
        """Should NOT trigger BE at 0.99R."""
        engine = BreakevenEngine()

        result = engine.check_breakeven(
            entry_price=100.0,
            stop_loss=98.0,
            current_price=101.98,  # 0.99R
            side="LONG",
        )

        assert result.should_move_to_be is False

    def test_frozen_result_dataclass(self):
        """Should return frozen dataclass (immutable)."""
        engine = BreakevenEngine()

        result = engine.check_breakeven(
            entry_price=100.0,
            stop_loss=98.0,
            current_price=102.0,
            side="LONG",
        )

        # Should be frozen (cannot modify)
        with pytest.raises(Exception):  # dataclass.FrozenInstanceError or similar
            result.should_move_to_be = False
