"""Tests for alerts module."""

import pytest
from app.core.alerts import (
    send_alert,
    alert_circuit_breaker,
    alert_drawdown,
    alert_loss_streak,
    subscribe_alerts,
    unsubscribe_alerts,
    AlertSeverity,
    AlertType,
)


class TestAlerts:
    def test_send_alert(self):
        """Test basic alert sending."""
        received = []
        def callback(alert):
            received.append(alert)
        
        subscribe_alerts(callback)
        result = send_alert("system", "info", "test message", symbol="TEST", data={"key": "value"})
        unsubscribe_alerts(callback)
        
        assert result["type"] == "system"
        assert result["severity"] == "info"
        assert result["message"] == "test message"
        assert result["symbol"] == "TEST"
        assert received[0]["type"] == "system"

    def test_alert_circuit_breaker(self):
        """Test circuit breaker alert helper."""
        result = alert_circuit_breaker("open", "TEST", 5)
        assert result["type"] == "circuit_breaker"
        assert result["severity"] == "critical"
        assert "open" in result["message"]

    def test_alert_drawdown(self):
        """Test drawdown alert helper."""
        result = alert_drawdown("TEST", 0.03, 0.02)
        assert result["type"] == "drawdown"
        assert result["severity"] == "warning"  # 3% > 2% but < 3% threshold for critical

    def test_alert_loss_streak(self):
        """Test loss streak alert helper."""
        result = alert_loss_streak("TEST", 4, 3)
        assert result["type"] == "loss_streak"
        assert result["severity"] == "critical"

    def test_alert_loss_streak_warning(self):
        """Test loss streak warning level."""
        result = alert_loss_streak("TEST", 2, 3)
        assert result["severity"] == "warning"