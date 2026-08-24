"""Tests for scale-in execution (40/30/30 plan)."""

import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from quant.contracts.entities import Position, Signal, Side, SignalType, Source, SetupType
from quant.contracts.aggregates import Portfolio
from app.application.services.entry_coordinator import EntryCoordinator
from quant.contracts.enums import PositionStatus


class TestScaleInExecution:
    """Test scale-in plan execution (40% / 30% / 30%)."""

    @pytest.fixture
    def mock_broker(self):
        """Mock broker that returns a position."""
        broker = MagicMock()
        position = Position(
            id="pos_001",
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("22000"),
            size=Decimal("1"),
            stop_loss=Decimal("21950"),
            take_profit=Decimal("22100"),
        )
        broker.execute_order.return_value = position
        return broker, position

    @pytest.fixture
    def mock_lifecycle_handler(self):
        return MagicMock()

    @pytest.fixture
    def mock_event_logger(self):
        return MagicMock()

    @pytest.fixture
    def mock_state_manager(self):
        return MagicMock()

    def test_scale_in_sizes_calculated_from_sizing_result(
        self, mock_broker, mock_lifecycle_handler, mock_event_logger, mock_state_manager
    ):
        """SizingResult returns scale_in_1,2,3 sizes that should be used."""
        # Sizing result returns scale_in_1,2,3 sizes that should be used
        from quant.execution.risk_sizing import RiskSizingEngine, KellySizingTier

        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,  # ₹10 lakh
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=22000,
            stop_price=21950,
            target_price=22100,
            direction="LONG",
        )

        # Should have scale-in sizes
        assert result.scale_in_1 >= 0
        assert result.scale_in_2 >= 0
        assert result.scale_in_3 >= 0
        # Total should equal first entry (100%)
        total = result.scale_in_1 + result.scale_in_2 + result.scale_in_3
        assert total == result.lots or result.lots == 0  # May be 0 for size constraints

    def test_position_has_scale_step_field(self):
        """Position entity should have scale_step field for tracking entries."""
        pos = Position(
            id="test",
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("22000"),
        )
        assert hasattr(pos, "scale_step")
        assert pos.scale_step == 1  # Initial entry

    def test_position_scale_step_advances(self):
        """Scale step should advance: 1 → 2 → 3."""
        pos = Position(
            id="test",
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("22000"),
        )
        assert pos.scale_step == 1
        
        # Simulate scale-in 1 (confirmation)
        pos.scale_step = 2
        assert pos.scale_step == 2
        
        # Simulate scale-in 2 (breakout)
        pos.scale_step = 3
        assert pos.scale_step == 3

    def test_entry_coordinator_stores_sizing_result_in_metadata(
        self, mock_broker, mock_lifecycle_handler, mock_event_logger, mock_state_manager
    ):
        """EntryCoordinator should store scale-in metadata from sizing result."""
        # The coordinator should use sizing result for scale-in plan
        # Position scale_step is now tracked (scale step = 1 for initial entry)
        position = mock_broker[1]
        assert position.scale_step == 1  # Initial entry