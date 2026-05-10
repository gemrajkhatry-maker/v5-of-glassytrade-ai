"""
Tests for Risk Control - Kill Switch Engine.

Tests cover:
- Kill switch activation/deactivation
- P&L limit enforcement
- Position limit checks
- Order rate limiting
- Emergency shutdown
- State persistence
"""

import pytest
from datetime import datetime, timezone

from brokersv2.risk.kill_switch import (
    KillSwitchEngine,
    KillSwitchState,
    KillSwitchConfig,
    KillSwitchReason,
    RiskLimit,
    RiskLimitType,
)


class TestKillSwitchConfig:
    """Test KillSwitchConfig."""

    def test_default_config(self):
        """Create default config."""
        config = KillSwitchConfig()

        assert config.max_daily_loss == 10000.0
        assert config.max_position_size == 100000
        assert config.max_order_rate == 100

    def test_custom_config(self):
        """Create custom config."""
        config = KillSwitchConfig(
            max_daily_loss=5000.0,
            max_position_size=50000,
            max_order_rate=50,
        )

        assert config.max_daily_loss == 5000.0
        assert config.max_position_size == 50000
        assert config.max_order_rate == 50


class TestKillSwitchEngine:
    """Test KillSwitchEngine functionality."""

    def test_create_engine(self):
        """Create kill switch engine."""
        engine = KillSwitchEngine()

        assert engine.state == KillSwitchState.INACTIVE
        assert engine.is_active is False

    def test_activate_kill_switch(self):
        """Activate kill switch."""
        engine = KillSwitchEngine()
        engine.activate(KillSwitchReason.MAX_LOSS_EXCEEDED)

        assert engine.state == KillSwitchState.ACTIVE
        assert engine.is_active is True
        assert engine.activation_reason == KillSwitchReason.MAX_LOSS_EXCEEDED

    def test_deactivate_kill_switch(self):
        """Deactivate kill switch."""
        engine = KillSwitchEngine()
        engine.activate(KillSwitchReason.MAX_LOSS_EXCEEDED)
        engine.deactivate()

        assert engine.state == KillSwitchState.INACTIVE
        assert engine.is_active is False

    def test_cannot_submit_orders_when_active(self):
        """Cannot submit orders when kill switch is active."""
        engine = KillSwitchEngine()
        engine.activate(KillSwitchReason.MAX_LOSS_EXCEEDED)

        with pytest.raises(Exception, match="Kill switch active"):
            engine.check_order_allowed("RELIANCE", 100, 2500.0)

    def test_can_submit_orders_when_inactive(self):
        """Can submit orders when kill switch is inactive."""
        engine = KillSwitchEngine()

        # Should not raise
        engine.check_order_allowed("RELIANCE", 100, 2500.0)


class TestRiskLimits:
    """Test risk limit enforcement."""

    def test_daily_loss_limit(self):
        """Activate on max daily loss."""
        config = KillSwitchConfig(max_daily_loss=1000.0)
        engine = KillSwitchEngine(config)

        engine.update_pnl(-500.0)
        assert engine.state == KillSwitchState.INACTIVE

        engine.update_pnl(-600.0)  # Total: -1100
        assert engine.state == KillSwitchState.ACTIVE
        assert engine.activation_reason == KillSwitchReason.MAX_LOSS_EXCEEDED

    def test_position_size_limit(self):
        """Activate on max position size."""
        config = KillSwitchConfig(max_position_size=50000)
        engine = KillSwitchEngine(config)

        engine.update_position("RELIANCE", 30000)
        assert engine.state == KillSwitchState.INACTIVE

        engine.update_position("TCS", 25000)  # Total: 55000
        assert engine.state == KillSwitchState.ACTIVE
        assert engine.activation_reason == KillSwitchReason.MAX_POSITION_EXCEEDED

    def test_order_rate_limit(self):
        """Activate on max order rate."""
        config = KillSwitchConfig(max_order_rate=10)
        engine = KillSwitchEngine(config)

        for i in range(9):
            engine.record_order()
        
        assert engine.state == KillSwitchState.INACTIVE

        engine.record_order()  # 10th order
        assert engine.state == KillSwitchState.ACTIVE
        assert engine.activation_reason == KillSwitchReason.MAX_ORDER_RATE_EXCEEDED


class TestEmergencyShutdown:
    """Test emergency shutdown functionality."""

    def test_emergency_shutdown(self):
        """Emergency shutdown activates immediately."""
        engine = KillSwitchEngine()
        engine.emergency_shutdown("Manual trigger")

        assert engine.state == KillSwitchState.ACTIVE
        assert engine.activation_reason == KillSwitchReason.MANUAL_TRIGGER

    def test_emergency_shutdown_logs_reason(self):
        """Emergency shutdown captures reason."""
        engine = KillSwitchEngine()
        reason = "System malfunction detected"
        engine.emergency_shutdown(reason)

        assert engine.last_reason == reason


class TestKillSwitchState:
    """Test kill switch state management."""

    def test_serialize_state(self):
        """Serialize kill switch state."""
        engine = KillSwitchEngine()
        engine.activate(KillSwitchReason.MAX_LOSS_EXCEEDED)

        state = engine.serialize_state()

        assert state["state"] == "active"
        assert state["reason"] == "max_loss_exceeded"

    def test_deserialize_state(self):
        """Deserialize kill switch state."""
        engine = KillSwitchEngine()
        serialized = {
            "state": "active",
            "reason": "max_loss_exceeded",
            "activated_at": datetime.now(timezone.utc).isoformat(),
        }

        engine.deserialize_state(serialized)

        assert engine.state == KillSwitchState.ACTIVE

    def test_state_preserves_timestamps(self):
        """State preserves activation timestamp."""
        engine = KillSwitchEngine()
        engine.activate(KillSwitchReason.MAX_LOSS_EXCEEDED)

        state = engine.serialize_state()
        assert "activated_at" in state


class TestKillSwitchAlerts:
    """Test kill switch alert system."""

    def test_alert_on_activation(self):
        """Alert generated on activation."""
        engine = KillSwitchEngine()
        engine.activate(KillSwitchReason.MAX_LOSS_EXCEEDED)

        alerts = engine.get_alerts()

        assert len(alerts) > 0
        assert "max_loss_exceeded" in alerts[0]

    def test_alert_on_limit_warning(self):
        """Alert generated when approaching limit."""
        config = KillSwitchConfig(max_daily_loss=1000.0)
        engine = KillSwitchEngine(config)

        engine.update_pnl(-900.0)  # 90% of limit

        alerts = engine.get_alerts()

        assert len(alerts) > 0


class TestKillSwitchEdgeCases:
    """Test edge cases."""

    def test_reset_clears_state(self):
        """Reset clears all state."""
        engine = KillSwitchEngine()
        engine.update_pnl(-500.0)
        engine.record_order()
        engine.reset()

        assert engine.current_pnl == 0.0
        assert engine.order_count == 0

    def test_multiple_activations(self):
        """Multiple activations use latest reason."""
        engine = KillSwitchEngine()
        engine.activate(KillSwitchReason.MAX_LOSS_EXCEEDED)
        engine.deactivate()
        engine.activate(KillSwitchReason.MANUAL_TRIGGER)

        assert engine.activation_reason == KillSwitchReason.MANUAL_TRIGGER

    def test_position_reduction_does_not_deactivate(self):
        """Position reduction does not auto-deactivate."""
        config = KillSwitchConfig(max_position_size=50000)
        engine = KillSwitchEngine(config)

        engine.update_position("RELIANCE", 60000)
        assert engine.state == KillSwitchState.ACTIVE

        # Reduce position
        engine.update_position("RELIANCE", -20000)

        # Still active - manual deactivation required
        assert engine.state == KillSwitchState.ACTIVE
