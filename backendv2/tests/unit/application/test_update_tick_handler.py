"""Unit tests for UpdateTickHandler - Phase 3 TDD."""
import pytest
from unittest.mock import Mock, MagicMock
from app.application.handlers.update_tick_handler import UpdateTickHandler
from app.application.commands.trading_commands import UpdateTick
from app.domain.shared.event.domain_events import TickReceived, AMTAnalyzed
from app.infrastructure.messaging.event_bus import EventBus


class TestUpdateTickHandler:
    """Tests for UpdateTickHandler following TDD."""
    
    def setup_method(self):
        self.event_bus = Mock(spec=EventBus)
        self.amt_service = Mock()
        self.handler = UpdateTickHandler(
            event_bus=self.event_bus,
            amt_service=self.amt_service
        )
    
    def test_handles_valid_tick_command(self):
        """Test that handler processes valid tick command."""
        cmd = UpdateTick(
            symbol="BTCUSDT",
            timestamp=1234567890.0,
            price=50000.0,
            volume=1.5
        )
        
        self.handler.handle(cmd)
        
        # Should publish events (TickReceived + AMTAnalyzed)
        assert self.event_bus.publish.call_count >= 1
        
    def test_publishes_tick_received_event(self):
        """Test that TickReceived event is published with correct data."""
        cmd = UpdateTick(
            symbol="BTCUSDT",
            timestamp=1234567890.0,
            price=50000.0,
            volume=1.5
        )
        
        self.handler.handle(cmd)
        
        # Get the FIRST published event (TickReceived)
        first_call = self.event_bus.publish.call_args_list[0]
        event = first_call[0][0]
        
        assert isinstance(event, TickReceived)
        assert event.symbol == "BTCUSDT"
        assert event.price == 50000.0
        assert event.volume == 1.5
        
    def test_triggers_amt_analysis(self):
        """Test that AMT analysis is triggered for the symbol."""
        cmd = UpdateTick(
            symbol="BTCUSDT",
            timestamp=1234567890.0,
            price=50000.0,
            volume=1.5
        )
        
        self.handler.handle(cmd)
        
        # Should call AMT service
        self.amt_service.analyze.assert_called_once()
        call_kwargs = self.amt_service.analyze.call_args.kwargs
        assert call_kwargs.get('symbol') == "BTCUSDT"
        
    def test_publishes_amt_analyzed_event(self):
        """Test that AMTAnalyzed event is published after analysis."""
        # Mock AMT analysis result
        self.amt_service.analyze.return_value = {
            "phase1": {"high": 50100},
            "phase2": {},
            "phase3": {},
            "phase4": {},
            "absorptions_count": 1,
            "vwap": 50000.0
        }
        
        cmd = UpdateTick(
            symbol="BTCUSDT",
            timestamp=1234567890.0,
            price=50000.0,
            volume=1.5
        )
        
        self.handler.handle(cmd)
        
        # Should publish both TickReceived and AMTAnalyzed
        assert self.event_bus.publish.call_count == 2