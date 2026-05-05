"""Unit tests for EvaluateEntryHandler - Phase 3 TDD."""
import pytest
from unittest.mock import Mock
from app.application.handlers.evaluate_entry_handler import EvaluateEntryHandler
from app.application.commands.trading_commands import EvaluateEntry
from app.domain.shared.event.domain_events import SignalGenerated


class TestEvaluateEntryHandler:
    """Tests for EvaluateEntryHandler following TDD."""
    
    def setup_method(self):
        self.event_bus = Mock()
        self.signal_service = Mock()
        self.handler = EvaluateEntryHandler(
            event_bus=self.event_bus,
            signal_service=self.signal_service
        )
    
    def test_handles_valid_entry_evaluation(self):
        """Test that handler processes entry evaluation."""
        cmd = EvaluateEntry(
            symbol="BTCUSDT",
            phase1_result={"high": 50100, "low": 49900, "complete": True},
            phase2_result={"accepted_above": True},
            phase3_result={"direction": "UP", "type": "INITIATIVE"},
            phase4_result={"poc_signal": "RISING"},
            absorptions=[{"side": "BUY", "strength": 0.8}],
            current_price=50050.0,
            vwap=50000.0
        )
        
        self.handler.handle(cmd)
        
        # Should publish SignalGenerated event
        self.event_bus.publish.assert_called_once()
        
    def test_generates_long_signal_from_absorption(self):
        """Test that LONG signal is generated for BUY absorption above VWAP."""
        self.signal_service.generate.return_value = {
            "type": "LONG",
            "entry": 50050.0,
            "sl": 49950.0,
            "tp": 50250.0,
            "rr": 2.0,
            "confidence": 0.8,
            "reason": "Triple-A BUY absorption above VWAP"
        }
        
        cmd = EvaluateEntry(
            symbol="BTCUSDT",
            phase1_result={"high": 50100},
            phase2_result={"accepted_above": True},
            phase3_result={"direction": "UP"},
            phase4_result={"poc_signal": "RISING"},
            absorptions=[{"side": "BUY", "strength": 0.8}],
            current_price=50050.0,
            vwap=50000.0
        )
        
        self.handler.handle(cmd)
        
        # Verify signal event was published
        call_args = self.event_bus.publish.call_args
        event = call_args[0][0]
        
        assert isinstance(event, SignalGenerated)
        assert event.direction == "LONG"
        assert event.entry_price == 50050.0
        
    def test_generates_no_trade_without_absorption(self):
        """Test that NO_TRADE signal when no absorption detected."""
        self.signal_service.generate.return_value = {
            "type": "NO_TRADE",
            "entry": 0.0,
            "sl": 0.0,
            "tp": 0.0,
            "rr": 0.0,
            "confidence": 0.0,
            "reason": "No absorption"
        }
        
        cmd = EvaluateEntry(
            symbol="BTCUSDT",
            phase1_result={},
            phase2_result={},
            phase3_result={},
            phase4_result={},
            absorptions=[],  # No absorptions
            current_price=50000.0,
            vwap=50000.0
        )
        
        self.handler.handle(cmd)
        
        self.signal_service.generate.assert_called_once()
        
    def test_validates_risk_state(self):
        """Test that risk check is performed before signal generation."""
        # Mock risk check to fail
        self.handler._check_risk = Mock(return_value=False)
        
        cmd = EvaluateEntry(
            symbol="BTCUSDT",
            phase1_result={},
            phase2_result={},
            phase3_result={},
            phase4_result={},
            absorptions=[{"side": "BUY"}],
            current_price=50000.0,
            vwap=50000.0
        )
        
        self.handler.handle(cmd)
        
        # Should not generate signal if risk check fails
        self.signal_service.generate.assert_not_called()