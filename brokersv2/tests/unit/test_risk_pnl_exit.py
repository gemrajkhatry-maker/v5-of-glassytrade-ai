"""
Tests for Risk Control - P&L Exit Manager.

Tests cover:
- Profit target exits
- Stop loss exits
- Trailing stop management
- Daily loss limits
- Position-specific exits
"""

import pytest

from brokersv2.risk.pnl_exit import (
    PnLExitManager,
    PnLExitConfig,
    PnLExitRule,
    ExitType,
    ExitEvent,
)


class TestPnLExitConfig:
    """Test PnLExitConfig."""

    def test_default_config(self):
        """Create default config."""
        config = PnLExitConfig()

        assert config.daily_profit_target == 5000.0
        assert config.daily_loss_limit == 3000.0
        assert config.position_stop_loss == 1000.0

    def test_custom_config(self):
        """Create custom config."""
        config = PnLExitConfig(
            daily_profit_target=10000.0,
            daily_loss_limit=5000.0,
        )

        assert config.daily_profit_target == 10000.0


class TestPnLExitManager:
    """Test PnLExitManager functionality."""

    def test_create_manager(self):
        """Create P&L exit manager."""
        manager = PnLExitManager()

        assert manager.daily_pnl == 0.0

    def test_update_daily_pnl(self):
        """Update daily P&L."""
        manager = PnLExitManager()
        manager.update_daily_pnl(500.0)

        assert manager.daily_pnl == 500.0

    def test_profit_target_exit(self):
        """Exit on profit target reached."""
        config = PnLExitConfig(daily_profit_target=1000.0)
        manager = PnLExitManager(config)

        manager.update_daily_pnl(1100.0)
        exits = manager.check_exits()

        assert len(exits) > 0
        assert exits[0].exit_type == ExitType.PROFIT_TARGET

    def test_loss_limit_exit(self):
        """Exit on daily loss limit."""
        config = PnLExitConfig(daily_loss_limit=1000.0)
        manager = PnLExitManager(config)

        manager.update_daily_pnl(-1100.0)
        exits = manager.check_exits()

        assert len(exits) > 0
        assert exits[0].exit_type == ExitType.DAILY_LOSS_LIMIT


class TestPositionExits:
    """Test position-specific exits."""

    def test_position_stop_loss(self):
        """Exit position on stop loss."""
        manager = PnLExitManager()
        manager.open_position("RELIANCE", 100, 2500.0)

        # Simulate price drop
        manager.update_position_price("RELIANCE", 2480.0)  # -2000 loss

        exits = manager.check_exits()

        # Should trigger if loss exceeds stop loss
        assert len(exits) > 0

    def test_position_profit_target(self):
        """Exit position on profit target."""
        manager = PnLExitManager()
        manager.open_position("RELIANCE", 100, 2500.0)

        # Simulate price increase
        manager.update_position_price("RELIANCE", 2550.0)  # +5000 profit

        exits = manager.check_exits()

        assert len(exits) > 0

    def test_close_position(self):
        """Close position manually."""
        manager = PnLExitManager()
        manager.open_position("RELIANCE", 100, 2500.0)
        manager.close_position("RELIANCE", 2520.0)

        assert "RELIANCE" not in manager.positions


class TestTrailingStop:
    """Test trailing stop management."""

    def test_trailing_stop_moves_up(self):
        """Trailing stop moves up with profit."""
        manager = PnLExitManager()
        manager.open_position("RELIANCE", 100, 2500.0, use_trailing_stop=True)

        # Price moves up
        manager.update_position_price("RELIANCE", 2520.0)
        
        stop = manager.get_trailing_stop("RELIANCE")
        assert stop > 2480.0  # Should have moved up from initial

    def test_trailing_stop_does_not_move_down(self):
        """Trailing stop does not move down."""
        manager = PnLExitManager()
        manager.open_position("RELIANCE", 100, 2500.0, use_trailing_stop=True)

        # Price moves up then down
        manager.update_position_price("RELIANCE", 2520.0)
        stop_after_up = manager.get_trailing_stop("RELIANCE")
        
        manager.update_position_price("RELIANCE", 2510.0)
        stop_after_down = manager.get_trailing_stop("RELIANCE")

        assert stop_after_down == stop_after_up  # Should not move down


class TestExitEvents:
    """Test exit event generation."""

    def test_exit_event_has_details(self):
        """Exit event contains all details."""
        config = PnLExitConfig(daily_profit_target=1000.0)
        manager = PnLExitManager(config)

        manager.update_daily_pnl(1100.0)
        exits = manager.check_exits()

        event = exits[0]
        assert event.timestamp is not None
        assert event.exit_type == ExitType.PROFIT_TARGET
        assert event.pnl == 1100.0

    def test_multiple_exit_events(self):
        """Multiple exit events for different reasons."""
        manager = PnLExitManager()
        manager.open_position("RELIANCE", 100, 2500.0)
        manager.open_position("TCS", 50, 3500.0)

        # Move both to profit target
        manager.update_position_price("RELIANCE", 2550.0)
        manager.update_position_price("TCS", 3600.0)

        exits = manager.check_exits()

        assert len(exits) >= 1


class TestPnLExitEdgeCases:
    """Test edge cases."""

    def test_reset_daily_pnl(self):
        """Reset daily P&L."""
        manager = PnLExitManager()
        manager.update_daily_pnl(500.0)
        manager.reset_daily()

        assert manager.daily_pnl == 0.0

    def test_no_exits_when_within_limits(self):
        """No exits when within limits."""
        config = PnLExitConfig(daily_profit_target=5000.0, daily_loss_limit=3000.0)
        manager = PnLExitManager(config)

        manager.update_daily_pnl(1000.0)
        exits = manager.check_exits()

        assert len(exits) == 0

    def test_position_pnl_calculation(self):
        """Calculate position P&L correctly."""
        manager = PnLExitManager()
        manager.open_position("RELIANCE", 100, 2500.0)
        manager.update_position_price("RELIANCE", 2520.0)

        pnl = manager.get_position_pnl("RELIANCE")

        assert pnl == 2000.0  # 100 * (2520 - 2500)
