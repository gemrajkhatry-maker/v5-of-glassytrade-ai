"""Tests for ScaleManager."""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.domain.fabio_ai.services.scale_manager import ScaleManager
from app.domain.trading.model.enums import Side


class TestScaleManager:
    """Test ScaleManager scale-in logic."""

    def _make_position(self, side: str = "LONG", entry_price: float = 100.0,
                       initial_stop: float = 95.0, scale_step: int = 1,
                       scale_confirm_price: float = 0.0,
                       scale_breakout_price: float = 0.0) -> SimpleNamespace:
        """Create a minimal position object."""
        return SimpleNamespace(
            side=side,
            entry_price=Decimal(str(entry_price)),
            initial_stop=Decimal(str(initial_stop)),
            scale_step=scale_step,
            scale_confirm_price=Decimal(str(scale_confirm_price)),
            scale_breakout_price=Decimal(str(scale_breakout_price)),
        )

    def test_scale_in_at_step_one_long(self):
        """check_scale_in() allows scale-in at step 1 for LONG when price >= confirm."""
        mgr = ScaleManager()
        pos = self._make_position(
            side="LONG", entry_price=100.0, initial_stop=95.0,
            scale_step=1, scale_confirm_price=102.0, scale_breakout_price=105.0,
        )

        fraction = mgr.check_scale_in(pos, current_price=103.0)

        assert fraction == pytest.approx(0.30)
        assert pos.scale_step == 2

    def test_scale_in_at_step_two_long(self):
        """check_scale_in() allows scale-in at step 2 for LONG when price >= breakout."""
        mgr = ScaleManager()
        pos = self._make_position(
            side="LONG", entry_price=100.0, initial_stop=95.0,
            scale_step=2, scale_confirm_price=102.0, scale_breakout_price=105.0,
        )

        fraction = mgr.check_scale_in(pos, current_price=106.0)

        assert fraction == pytest.approx(0.30)
        assert pos.scale_step == 3

    def test_scale_in_blocked_at_step_three(self):
        """check_scale_in() returns 0 when scale_step >= 3."""
        mgr = ScaleManager()
        pos = self._make_position(
            side="LONG", entry_price=100.0, initial_stop=95.0,
            scale_step=3, scale_confirm_price=102.0, scale_breakout_price=105.0,
        )

        fraction = mgr.check_scale_in(pos, current_price=106.0)

        assert fraction == 0.0
        assert pos.scale_step == 3

    def test_scale_in_requires_price_above_entry_for_long(self):
        """check_scale_in() returns 0 when current_price < entry for LONG."""
        mgr = ScaleManager()
        pos = self._make_position(
            side="LONG", entry_price=100.0, initial_stop=95.0,
            scale_step=1, scale_confirm_price=102.0, scale_breakout_price=105.0,
        )

        fraction = mgr.check_scale_in(pos, current_price=98.0)

        assert fraction == 0.0

    def test_scale_in_short_direction(self):
        """check_scale_in() works for SHORT positions (price must fall)."""
        mgr = ScaleManager()
        pos = self._make_position(
            side="SHORT", entry_price=100.0, initial_stop=105.0,
            scale_step=1, scale_confirm_price=98.0, scale_breakout_price=95.0,
        )

        fraction = mgr.check_scale_in(pos, current_price=97.0)

        assert fraction == pytest.approx(0.30)
        assert pos.scale_step == 2

    def test_scale_in_short_step_two(self):
        """check_scale_in() allows SHORT scale-in at step 2."""
        mgr = ScaleManager()
        pos = self._make_position(
            side="SHORT", entry_price=100.0, initial_stop=105.0,
            scale_step=2, scale_confirm_price=98.0, scale_breakout_price=95.0,
        )

        fraction = mgr.check_scale_in(pos, current_price=94.0)

        assert fraction == pytest.approx(0.30)
        assert pos.scale_step == 3

    def test_reset_scale_state_clears_history(self):
        """reset_scale_state() clears all scale-related fields."""
        mgr = ScaleManager()
        pos = self._make_position(
            side="LONG", entry_price=100.0, initial_stop=95.0,
            scale_step=3, scale_confirm_price=102.0, scale_breakout_price=105.0,
        )

        mgr.reset_scale_state(pos)

        assert pos.scale_step == 1
        assert pos.scale_confirm_price == Decimal("0")
        assert pos.scale_breakout_price == Decimal("0")

    def test_initialize_scale_prices(self):
        """initialize_scale_prices() sets scale prices and resets step to 1."""
        mgr = ScaleManager()
        pos = self._make_position(side="LONG", entry_price=100.0, initial_stop=95.0)

        mgr.initialize_scale_prices(pos, confirm_price=102.0, breakout_price=105.0)

        assert pos.scale_step == 1
        assert float(pos.scale_confirm_price) == 102.0
        assert float(pos.scale_breakout_price) == 105.0

    def test_get_scale_status(self):
        """get_scale_status() returns correct scale information."""
        mgr = ScaleManager()
        pos = self._make_position(
            side="LONG", entry_price=100.0, initial_stop=95.0,
            scale_step=1, scale_confirm_price=102.0, scale_breakout_price=105.0,
        )

        status = mgr.get_scale_status(pos)

        assert status["scale_step"] == 1
        assert status["scale_confirm_price"] == 102.0
        assert status["scale_breakout_price"] == 105.0
        assert status["remaining_fraction"] == pytest.approx(0.60)

    def test_price_boundary_not_reached(self):
        """check_scale_in() returns 0 when price boundary not reached."""
        mgr = ScaleManager()
        pos = self._make_position(
            side="LONG", entry_price=100.0, initial_stop=95.0,
            scale_step=1, scale_confirm_price=102.0, scale_breakout_price=105.0,
        )

        fraction = mgr.check_scale_in(pos, current_price=101.0)

        assert fraction == 0.0
        assert pos.scale_step == 1  # step unchanged
