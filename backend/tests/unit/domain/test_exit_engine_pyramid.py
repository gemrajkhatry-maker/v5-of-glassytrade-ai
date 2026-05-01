"""Tests for ExitEngine pyramid integration."""

import pytest
from decimal import Decimal

from app.domain.fabio_ai.services.exit_engine import ExitEngine
from app.domain.trading.models.entities import Position, Side, PositionStatus


class TestExitEnginePyramid:
    """Test ExitEngine pyramid add-on logic."""

    @pytest.fixture
    def exit_engine(self):
        return ExitEngine()

    @pytest.fixture
    def long_position(self):
        """A winning long position for pyramid testing."""
        pos = Position(
            id="test-pos-1",
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("100.0"),
            stop_loss=Decimal("98.0"),
            take_profit=Decimal("105.0"),
            size=Decimal("1.0"),
        )
        pos.scale_step = 1  # Starting at first entry
        return pos

    def test_pyramid_returns_none_without_aggression(self, exit_engine, long_position):
        """Pyramid requires aggression ≥ 3.0."""
        result = exit_engine.check_pyramid(
            position=long_position,
            current_price=102.0,  # In profit
            aggression_score=2.5,  # Below threshold
            entry_lvns=[],
            current_lvn=101.0,
        )
        assert result is None

    def test_pyramid_returns_none_not_in_profit(self, exit_engine, long_position):
        """Pyramid requires position in profit."""
        result = exit_engine.check_pyramid(
            position=long_position,
            current_price=99.0,  # Not in profit
            aggression_score=3.5,
            entry_lvns=[],
            current_lvn=101.0,
        )
        assert result is None

    def test_pyramid_triggers_with_valid_conditions(self, exit_engine, long_position):
        """Pyramid triggers with valid aggression and LVN."""
        result = exit_engine.check_pyramid(
            position=long_position,
            current_price=102.0,  # In profit
            aggression_score=3.5,
            entry_lvns=[100.0],  # Previous entry LVN
            current_lvn=103.0,  # Different LVN
        )
        assert result is not None
        size_mult, new_sl = result
        assert size_mult == 1.0  # First add is 100% of base
        assert new_sl > 0  # Unified SL computed

    def test_pyramid_second_add_half_size(self, exit_engine, long_position):
        """Second pyramid add is 50% of base."""
        long_position.scale_step = 2  # After first add

        result = exit_engine.check_pyramid(
            position=long_position,
            current_price=104.0,
            aggression_score=3.5,
            entry_lvns=[100.0, 103.0],
            current_lvn=106.0,
        )
        assert result is not None
        size_mult, _ = result
        assert size_mult == 0.5  # Second add is 50%

    def test_pyramid_no_add_same_lvn(self, exit_engine, long_position):
        """Pyramid requires different LVN from previous entries."""
        result = exit_engine.check_pyramid(
            position=long_position,
            current_price=102.0,
            aggression_score=3.5,
            entry_lvns=[103.0],  # Same as current_lvn (within 0.3%)
            current_lvn=103.0,
        )
        assert result is None  # Same LVN blocked