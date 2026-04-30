"""Tests for P2-12: Precise 40/30/30 scale-in conditions.

Tests for ScaleManager scale-in logic based on confirmation/breakout prices.
"""

from __future__ import annotations

import pytest
from decimal import Decimal

from app.domain.fabio_ai.services.scale_manager import ScaleManager
from app.domain.trading.models.entities import Position
from app.domain.trading.models.enums import Side


class TestScaleInConditions:
    """Tests for Fabio-compliant 40/30/30 scale-in logic."""

    def setup_method(self):
        self.scale_manager = ScaleManager()

    def test_no_scale_in_when_max_step_reached(self):
        """After step 3 = no more scale-in."""
        pos = Position(
            id="test_max",
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("24800"),
            stop_loss=Decimal("24700"),
            take_profit=Decimal("24900"),
        )
        pos.scale_step = 3
        pos.scale_confirm_price = Decimal("24850")
        pos.scale_breakout_price = Decimal("24900")
        
        result = self.scale_manager.check_scale_in(pos, 24950.0)
        assert result == 0.0

    def test_no_scale_in_in_loss_territory_long(self):
        """Don't scale in when price is below entry."""
        pos = Position(
            id="test_loss",
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("24800"),
            stop_loss=Decimal("24700"),
            take_profit=Decimal("24900"),
        )
        pos.scale_step = 1
        pos.scale_confirm_price = Decimal("24850")
        pos.scale_breakout_price = Decimal("24900")
        
        # Price below entry
        result = self.scale_manager.check_scale_in(pos, 24750.0)
        assert result == 0.0

    def test_no_scale_in_in_loss_territory_short(self):
        """Don't scale in when price is above entry for shorts."""
        pos = Position(
            id="test_loss_short",
            symbol="NIFTY",
            side=Side.SHORT,
            entry_price=Decimal("24800"),
            stop_loss=Decimal("24900"),
            take_profit=Decimal("24700"),
        )
        pos.scale_step = 1
        pos.scale_confirm_price = Decimal("24750")
        pos.scale_breakout_price = Decimal("24700")
        
        # Price above entry for short
        result = self.scale_manager.check_scale_in(pos, 24850.0)
        assert result == 0.0

    def test_step1_to_step2_long(self):
        """Step 1 to Step 2 triggers with 0.3 for longs."""
        pos = Position(
            id="test_step2_long",
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("24800"),
            stop_loss=Decimal("24700"),
            take_profit=Decimal("24900"),
        )
        pos.scale_step = 1
        pos.scale_confirm_price = Decimal("24850")
        pos.scale_breakout_price = Decimal("24900")
        
        result = self.scale_manager.check_scale_in(pos, 24850.0)
        assert result == 0.3
        assert pos.scale_step == 2

    def test_step1_to_step2_short(self):
        """Step 1 to Step 2 triggers with 0.3 for shorts."""
        pos = Position(
            id="test_step2_short",
            symbol="NIFTY",
            side=Side.SHORT,
            entry_price=Decimal("24800"),
            stop_loss=Decimal("24900"),
            take_profit=Decimal("24700"),
        )
        pos.scale_step = 1
        pos.scale_confirm_price = Decimal("24750")
        pos.scale_breakout_price = Decimal("24700")
        
        result = self.scale_manager.check_scale_in(pos, 24750.0)
        assert result == 0.3
        assert pos.scale_step == 2

    def test_step2_to_step3_long(self):
        """Step 2 to Step 3 triggers with 0.3 for longs."""
        pos = Position(
            id="test_step3_long",
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("24800"),
            stop_loss=Decimal("24700"),
            take_profit=Decimal("24900"),
        )
        pos.scale_step = 2
        pos.scale_confirm_price = Decimal("24850")
        pos.scale_breakout_price = Decimal("24900")
        
        result = self.scale_manager.check_scale_in(pos, 24900.0)
        assert result == 0.3
        assert pos.scale_step == 3

    def test_step2_to_step3_short(self):
        """Step 2 to Step 3 triggers with 0.3 for shorts."""
        pos = Position(
            id="test_step3_short",
            symbol="NIFTY",
            side=Side.SHORT,
            entry_price=Decimal("24800"),
            stop_loss=Decimal("24900"),
            take_profit=Decimal("24700"),
        )
        pos.scale_step = 2
        pos.scale_confirm_price = Decimal("24750")
        pos.scale_breakout_price = Decimal("24700")
        
        result = self.scale_manager.check_scale_in(pos, 24700.0)
        assert result == 0.3
        assert pos.scale_step == 3

    def test_no_trigger_below_confirm_price(self):
        """No scale-in when price below confirmation level."""
        pos = Position(
            id="test_no_trigger",
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("24800"),
            stop_loss=Decimal("24700"),
            take_profit=Decimal("24900"),
        )
        pos.scale_step = 1
        pos.scale_confirm_price = Decimal("24850")
        pos.scale_breakout_price = Decimal("24900")
        
        result = self.scale_manager.check_scale_in(pos, 24840.0)
        assert result == 0.0
        assert pos.scale_step == 1

    def test_zero_prices_do_not_trigger(self):
        """Zero confirmation/breakout prices don't trigger scale-in."""
        pos = Position(
            id="test_zero",
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("24800"),
            stop_loss=Decimal("24700"),
            take_profit=Decimal("24900"),
        )
        pos.scale_step = 1
        pos.scale_confirm_price = Decimal("0")
        pos.scale_breakout_price = Decimal("0")
        
        result = self.scale_manager.check_scale_in(pos, 25000.0)
        assert result == 0.0

    def test_get_scale_status(self):
        """get_scale_status returns correct info."""
        pos = Position(
            id="test_status",
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("24800"),
            stop_loss=Decimal("24700"),
            take_profit=Decimal("24900"),
        )
        pos.scale_step = 2
        pos.scale_confirm_price = Decimal("24850")
        pos.scale_breakout_price = Decimal("24900")
        
        status = self.scale_manager.get_scale_status(pos)
        assert status["scale_step"] == 2
        assert status["remaining_fraction"] == 0.3

    def test_initialize_scale_prices(self):
        """initialize_scale_prices sets correct values."""
        pos = Position(
            id="test_init",
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("24800"),
            stop_loss=Decimal("24700"),
            take_profit=Decimal("24900"),
        )
        
        self.scale_manager.initialize_scale_prices(pos, 24850.0, 24900.0)
        
        assert pos.scale_step == 1
        assert float(pos.scale_confirm_price) == 24850.0
        assert float(pos.scale_breakout_price) == 24900.0

    def test_reset_scale_state(self):
        """reset_scale_state clears all scale values."""
        pos = Position(
            id="test_reset",
            symbol="NIFTY",
            side=Side.LONG,
            entry_price=Decimal("24800"),
            stop_loss=Decimal("24700"),
            take_profit=Decimal("24900"),
        )
        pos.scale_step = 2
        pos.scale_confirm_price = Decimal("24850")
        pos.scale_breakout_price = Decimal("24900")
        
        self.scale_manager.reset_scale_state(pos)
        
        assert pos.scale_step == 1
        assert float(pos.scale_confirm_price) == 0.0
        assert float(pos.scale_breakout_price) == 0.0