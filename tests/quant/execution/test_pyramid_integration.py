"""Tests for pyramid integration."""

import pytest
from decimal import Decimal
from unittest.mock import MagicMock

from quant.execution.pyramid import PyramidManager, PyramidSignal
from quant.contracts.entities import Position, Side, PositionStatus


class TestPyramidIntegration:
    """Test pyramid add-on logic."""

    @pytest.fixture
    def pyramid_manager(self):
        return PyramidManager()

    def test_pyramid_not_triggered_without_aggression(self, pyramid_manager):
        """Pyramid requires aggression ≥ 3.0."""
        result = pyramid_manager.check_pyramid(
            entry_price=100.0,
            current_price=102.0,  # In profit
            is_long=True,
            aggression_score=2.5,  # Below threshold
            add_count=0,
            entry_lvns=[],
            current_lvn=101.0,
            current_sl=99.0,
        )
        assert result is None

    def test_pyramid_not_triggered_not_in_profit(self, pyramid_manager):
        """Pyramid requires position in profit."""
        result = pyramid_manager.check_pyramid(
            entry_price=100.0,
            current_price=99.0,  # Not in profit
            is_long=True,
            aggression_score=3.5,
            add_count=0,
            entry_lvns=[],
            current_lvn=101.0,
            current_sl=99.0,
        )
        assert result is None

    def test_pyramid_triggered_with_valid_conditions(self, pyramid_manager):
        """Pyramid triggers with valid conditions."""
        result = pyramid_manager.check_pyramid(
            entry_price=100.0,
            current_price=102.0,  # In profit
            is_long=True,
            aggression_score=3.5,
            add_count=0,
            entry_lvns=[],
            current_lvn=101.0,
            current_sl=99.0,
        )
        assert result is not None
        assert result.size_multiplier == 1.0  # First add = 100%

    def test_pyramid_second_add_half_size(self, pyramid_manager):
        """Second pyramid add is 50% size."""
        result = pyramid_manager.check_pyramid(
            entry_price=100.0,
            current_price=103.0,  # In profit
            is_long=True,
            aggression_score=3.5,
            add_count=1,  # Already one add
            entry_lvns=[101.0],
            current_lvn=102.0,  # Different LVN
            current_sl=100.0,
        )
        assert result is not None
        assert result.size_multiplier == 0.5  # Second add = 50%

    def test_pyramid_max_two_adds(self, pyramid_manager):
        """Pyramid max 2 adds (3 entries total)."""
        # First add
        result1 = pyramid_manager.check_pyramid(
            entry_price=100.0, current_price=102.0, is_long=True,
            aggression_score=3.5, add_count=0, entry_lvns=[],
            current_lvn=101.0, current_sl=99.0,
        )
        assert result1 is not None

        # Second add
        result2 = pyramid_manager.check_pyramid(
            entry_price=100.0, current_price=103.0, is_long=True,
            aggression_score=3.5, add_count=1, entry_lvns=[101.0],
            current_lvn=102.0, current_sl=100.0,
        )
        assert result2 is not None

        # Third add should fail (max reached)
        result3 = pyramid_manager.check_pyramid(
            entry_price=100.0, current_price=104.0, is_long=True,
            aggression_score=3.5, add_count=2, entry_lvns=[101.0, 102.0],
            current_lvn=103.0, current_sl=101.0,
        )
        assert result3 is None

    def test_portfolio_add_to_position(self):
        """Portfolio.add_to_position scales into winning position."""
        from app.domain.trading.models.aggregates import Portfolio
        
        portfolio = Portfolio.create_default()
        
        # Create a mock signal
        from app.domain.trading.models.entities import Signal, SignalType, Source, SetupType
        import time
        
        signal = Signal.create(
            type=SignalType.BUY,
            price=100.0,
            reason="Test",
            stop_loss=98.0,
            take_profit=104.0,
            timestamp=str(time.time()),
            setup=SetupType.MEAN_REVERSION,
            source=Source.AMT,
        )
        
        # Open position with 40% scale (first entry)
        position = portfolio.open_position(signal, "NIFTY", scale_fraction=0.4)
        assert position is not None
        assert position.size > 0
        
        # Add 30% (second entry)
        success = portfolio.add_to_position(position.id, 0.3, 101.0)
        assert success
        
        # Add 30% (third entry)
        success = portfolio.add_to_position(position.id, 0.3, 102.0)
        assert success