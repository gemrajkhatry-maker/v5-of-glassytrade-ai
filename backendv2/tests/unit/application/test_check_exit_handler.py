"""Unit tests for CheckExitHandler - Phase 3 TDD."""
import pytest
from unittest.mock import Mock
from app.application.handlers.check_exit_handler import CheckExitHandler
from app.application.commands.trading_commands import CheckExit
from app.domain.trading.model.entities import Position
from app.domain.trading.model.enums import Side
from app.domain.shared.event.domain_events import PositionClosed


class TestCheckExitHandler:
    """Tests for CheckExitHandler following TDD."""
    
    def setup_method(self):
        self.event_bus = Mock()
        self.position_repo = Mock()
        self.handler = CheckExitHandler(
            event_bus=self.event_bus,
            position_repo=self.position_repo
        )
    
    def test_handles_valid_exit_check(self):
        """Test that handler processes exit check for position."""
        position = Position.open(
            symbol="BTCUSDT",
            side=Side.LONG,
            entry_price=50000.0,
            size=0.1,
            stop_loss=49500.0,
            take_profit=51000.0
        )
        
        self.position_repo.get_by_id.return_value = position
        
        cmd = CheckExit(
            position_id=position.id,
            current_price=50050.0
        )
        
        self.handler.handle(cmd)
        
        # Should fetch position from repo
        self.position_repo.get_by_id.assert_called_once_with(position.id)
        
    def test_publishes_position_closed_on_stop_loss(self):
        """Test that PositionClosed event is published when SL hit."""
        position = Position.open(
            symbol="BTCUSDT",
            side=Side.LONG,
            entry_price=50000.0,
            size=0.1,
            stop_loss=49500.0,
            take_profit=51000.0
        )
        
        self.position_repo.get_by_id.return_value = position
        
        # Current price hits stop loss
        cmd = CheckExit(
            position_id=position.id,
            current_price=49400.0  # Below SL
        )
        
        self.handler.handle(cmd)
        
        # Should publish PositionClosed
        call_args = self.event_bus.publish.call_args
        event = call_args[0][0]
        
        assert isinstance(event, PositionClosed)
        assert event.exit_price == 49400.0
        assert event.realized_pnl < 0  # Loss
        
    def test_publishes_position_closed_on_take_profit(self):
        """Test that PositionClosed event is published when TP hit."""
        position = Position.open(
            symbol="BTCUSDT",
            side=Side.LONG,
            entry_price=50000.0,
            size=0.1,
            stop_loss=49500.0,
            take_profit=51000.0
        )
        
        self.position_repo.get_by_id.return_value = position
        
        # Current price hits take profit
        cmd = CheckExit(
            position_id=position.id,
            current_price=51100.0  # Above TP
        )
        
        self.handler.handle(cmd)
        
        # Should publish PositionClosed
        call_args = self.event_bus.publish.call_args
        event = call_args[0][0]
        
        assert isinstance(event, PositionClosed)
        assert event.exit_price == 51100.0
        assert event.realized_pnl > 0  # Profit
        
    def test_no_exit_when_within_bounds(self):
        """Test that no exit when price is within SL/TP range."""
        position = Position.open(
            symbol="BTCUSDT",
            side=Side.LONG,
            entry_price=50000.0,
            size=0.1,
            stop_loss=49500.0,
            take_profit=51000.0
        )
        
        self.position_repo.get_by_id.return_value = position
        
        # Price within range
        cmd = CheckExit(
            position_id=position.id,
            current_price=50250.0  # Within range
        )
        
        self.handler.handle(cmd)
        
        # Should NOT publish PositionClosed
        self.event_bus.publish.assert_not_called()
        
    def test_calculates_pnl_correctly(self):
        """Test PNL calculation for LONG position at TP."""
        position = Position.open(
            symbol="BTCUSDT",
            side=Side.LONG,
            entry_price=50000.0,
            size=0.1,
            stop_loss=49500.0,
            take_profit=51000.0
        )
        
        self.position_repo.get_by_id.return_value = position
        
        cmd = CheckExit(
            position_id=position.id,
            current_price=51000.0  # At TP
        )
        
        self.handler.handle(cmd)
        
        call_args = self.event_bus.publish.call_args
        event = call_args[0][0]
        
        # PNL = (exit - entry) * size = (51000 - 50000) * 0.1 = 100
        assert event.realized_pnl == pytest.approx(100.0, rel=0.01)