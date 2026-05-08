"""Tests for EventBus subscriber wiring.

Covers:
- All 6 domain event types have subscribers registered
- Handlers execute without errors
- Handlers log appropriate messages
- wire_event_bus_subscribers is idempotent
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from app.application.event_subscribers import (
    _on_amt_analyzed,
    _on_position_closed,
    _on_position_opened,
    _on_risk_state_changed,
    _on_signal_generated,
    _on_tick_received,
    wire_event_bus_subscribers,
)
from app.domain.shared.event.domain_events import (
    AMTAnalyzed,
    PositionClosed,
    PositionOpened,
    RiskStateChanged,
    SignalGenerated,
    TickReceived,
)
from app.infrastructure.messaging.event_bus import EventBus


# ---------------------------------------------------------------------------
# 1. Subscriber registration
# ---------------------------------------------------------------------------

class TestSubscriberRegistration:
    def test_wiring_registers_tick_received_handler(self):
        bus = EventBus()
        wire_event_bus_subscribers(bus)
        assert len(bus.get_subscribers(TickReceived)) >= 1

    def test_wiring_registers_amt_analyzed_handler(self):
        bus = EventBus()
        wire_event_bus_subscribers(bus)
        assert len(bus.get_subscribers(AMTAnalyzed)) >= 1

    def test_wiring_registers_signal_generated_handler(self):
        bus = EventBus()
        wire_event_bus_subscribers(bus)
        assert len(bus.get_subscribers(SignalGenerated)) >= 1

    def test_wiring_registers_position_opened_handler(self):
        bus = EventBus()
        wire_event_bus_subscribers(bus)
        assert len(bus.get_subscribers(PositionOpened)) >= 1

    def test_wiring_registers_position_closed_handler(self):
        bus = EventBus()
        wire_event_bus_subscribers(bus)
        assert len(bus.get_subscribers(PositionClosed)) >= 1

    def test_wiring_registers_risk_state_changed_handler(self):
        bus = EventBus()
        wire_event_bus_subscribers(bus)
        assert len(bus.get_subscribers(RiskStateChanged)) >= 1

    def test_wiring_is_idempotent(self):
        """Calling wire_event_bus_subscribers twice should not double-register."""
        bus = EventBus()
        wire_event_bus_subscribers(bus)
        wire_event_bus_subscribers(bus)
        # Each event type should still have exactly 1 handler
        assert len(bus.get_subscribers(TickReceived)) == 1
        assert len(bus.get_subscribers(SignalGenerated)) == 1


# ---------------------------------------------------------------------------
# 2. Handler execution
# ---------------------------------------------------------------------------

class TestHandlerExecution:
    def test_tick_received_handler_executes(self):
        event = TickReceived(symbol="NIFTY", price=22000.0, volume=500.0)
        with patch("app.application.event_subscribers.logger.debug") as mock_debug:
            _on_tick_received(event)
            mock_debug.assert_called_once()

    def test_amt_analyzed_handler_executes(self):
        event = AMTAnalyzed(symbol="NIFTY", phase1_result={"setup": "trend"})
        with patch("app.application.event_subscribers.logger.debug") as mock_debug:
            _on_amt_analyzed(event)
            mock_debug.assert_called_once()

    def test_signal_generated_handler_executes(self):
        event = SignalGenerated(
            symbol="NIFTY", direction="LONG", entry_price=22000.0,
            stop_loss=21950.0, take_profit=22100.0,
            risk_reward=2.0, confidence=0.7, reason="trend_model",
        )
        with patch("app.application.event_subscribers.logger.info") as mock_info:
            _on_signal_generated(event)
            mock_info.assert_called_once()

    def test_signal_no_trade_is_ignored(self):
        """NO_TRADE signals should not log."""
        event = SignalGenerated(direction="NO_TRADE")
        with patch.object(logging.getLogger("app.application.event_subscribers"), "info") as mock_info:
            _on_signal_generated(event)
            assert mock_info.call_count == 0

    def test_position_opened_handler_executes(self):
        event = PositionOpened(
            position_id="P1", symbol="NIFTY", side="LONG",
            entry_price=22000.0, size=1.0,
        )
        with patch("app.application.event_subscribers.logger.info") as mock_info:
            _on_position_opened(event)
            mock_info.assert_called_once()

    def test_position_closed_handler_executes(self):
        event = PositionClosed(
            position_id="P1", exit_price=22050.0, pnl=50.0, reason="take_profit",
        )
        with patch("app.application.event_subscribers.logger.info") as mock_info:
            _on_position_closed(event)
            mock_info.assert_called_once()

    def test_risk_halt_handler_logs_warning(self):
        event = RiskStateChanged(
            halted=True, reason="daily_loss_limit", daily_pnl=-5000.0,
            consecutive_losses=5,
        )
        with patch("app.application.event_subscribers.logger.warning") as mock_warning:
            _on_risk_state_changed(event)
            mock_warning.assert_called_once()

    def test_risk_resume_handler_logs_info(self):
        event = RiskStateChanged(halted=False)
        with patch("app.application.event_subscribers.logger.info") as mock_info:
            _on_risk_state_changed(event)
            mock_info.assert_called_once()


# ---------------------------------------------------------------------------
# 3. End-to-end: publish events and verify handlers are called
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_publishing_tick_triggers_handler(self):
        bus = EventBus()
        wire_event_bus_subscribers(bus)
        event = TickReceived(symbol="NIFTY", price=22000.0)
        handled = bus.publish(event)
        assert handled >= 1

    def test_publishing_signal_triggers_handler(self):
        bus = EventBus()
        wire_event_bus_subscribers(bus)
        event = SignalGenerated(symbol="NIFTY", direction="LONG")
        handled = bus.publish(event)
        assert handled >= 1

    def test_stats_show_registered_handlers(self):
        bus = EventBus()
        wire_event_bus_subscribers(bus)
        stats = bus.get_stats()
        assert stats["total_event_types"] == 6
        assert stats["total_handlers"] == 6
