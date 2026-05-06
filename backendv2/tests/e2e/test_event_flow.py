"""Integration tests for complete event flow."""
import pytest
from unittest.mock import Mock
from app.application.handlers.update_tick_handler import UpdateTickHandler
from app.application.handlers.evaluate_entry_handler import EvaluateEntryHandler
from app.domain.shared.port.signal import ISignalService
from app.application.commands.trading_commands import UpdateTick, EvaluateEntry
from app.domain.shared.event.domain_events import TickReceived, AMTAnalyzed, SignalGenerated
from app.infrastructure.messaging.event_bus import EventBus


class TestIntegration:
    """Integration tests for full event flow."""
    
    def test_tick_to_signal_flow(self):
        """Test complete flow from tick update to signal generation."""
        # Setup
        event_bus = EventBus()
        amt_service = Mock()
        signal_service = Mock()
        
        # Mock AMT analysis result with absorption
        amt_service.analyze.return_value = {
            "phase1": {"high": 50100, "low": 49900},
            "phase2": {"accepted_above": True},
            "phase3": {"direction": "UP", "type": "INITIATIVE"},
            "phase4": {"poc_signal": "RISING"},
            "absorptions_count": 1,
            "vwap": 50000.0,
            "absorptions": [{"side": "BUY", "strength": 0.8}]
        }
        
        # Mock signal service
        signal_service.generate.return_value = {
            "type": "LONG",
            "entry": 50050.0,
            "sl": 49950.0,
            "tp": 50250.0,
            "rr": 2.0,
            "confidence": 0.8,
            "reason": "Triple-A BUY absorption above VWAP"
        }
        
        update_handler = UpdateTickHandler(
            event_bus=event_bus,
            amt_service=amt_service
        )
        
        evaluate_handler = EvaluateEntryHandler(
            event_bus=event_bus,
            signal_service=signal_service
        )
        
        # Track events
        events = []
        
        def track_event(event):
            events.append(event)
        
        # Subscribe to events
        event_bus.subscribe(TickReceived, track_event)
        event_bus.subscribe(AMTAnalyzed, track_event)
        event_bus.subscribe(SignalGenerated, track_event)
        
        # 1. Process tick
        tick_cmd = UpdateTick(
            symbol="BTCUSDT",
            timestamp=1234567890.0,
            price=50050.0,
            volume=1.5
        )
        update_handler.handle(tick_cmd)
        
        # Verify TickReceived published
        assert len(events) == 2  # TickReceived + AMTAnalyzed
        assert isinstance(events[0], TickReceived)
        assert isinstance(events[1], AMTAnalyzed)
        
        # 2. Evaluate entry with same data (simulating the flow)
        entry_cmd = EvaluateEntry(
            symbol="BTCUSDT",
            phase1_result={"high": 50100},
            phase2_result={"accepted_above": True},
            phase3_result={"direction": "UP"},
            phase4_result={"poc_signal": "RISING"},
            absorptions=[{"side": "BUY", "strength": 0.8}],
            current_price=50050.0,
            vwap=50000.0
        )
        evaluate_handler.handle(entry_cmd)
        
        # Verify SignalGenerated published
        assert len(events) == 3  # + SignalGenerated
        assert isinstance(events[2], SignalGenerated)
        assert events[2].direction == "LONG"
        assert events[2].entry_price == 50050.0