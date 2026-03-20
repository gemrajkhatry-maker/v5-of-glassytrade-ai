"""Unit tests for PyramidManager — structured add-on to winning positions per FR-09."""

import pytest
from app.domain.fabio_ai.services.pyramid_manager import PyramidManager


class TestPyramidEligibility:
    """FR-09: Pyramid eligibility checks."""

    def test_max_adds_reached(self):
        """2 previous adds → None (max reached)."""
        pm = PyramidManager()
        result = pm.check_pyramid(
            entry_price=100.0, current_price=101.0, is_long=True,
            aggression_score=3.5, add_count=2, entry_lvns=[99.0],
            current_lvn=101.0, current_sl=99.0,
        )
        assert result is None

    def test_not_in_profit(self):
        """Position not in profit → None."""
        pm = PyramidManager()
        result = pm.check_pyramid(
            entry_price=100.0, current_price=99.5, is_long=True,
            aggression_score=3.5, add_count=0, entry_lvns=[],
            current_lvn=99.5, current_sl=99.0,
        )
        assert result is None

    def test_low_aggression(self):
        """Aggression < 3.0 → None."""
        pm = PyramidManager()
        result = pm.check_pyramid(
            entry_price=100.0, current_price=101.0, is_long=True,
            aggression_score=2.5, add_count=0, entry_lvns=[],
            current_lvn=101.0, current_sl=99.0,
        )
        assert result is None

    def test_same_lvn_rejected(self):
        """Same LVN as previous entry → None."""
        pm = PyramidManager()
        result = pm.check_pyramid(
            entry_price=100.0, current_price=101.0, is_long=True,
            aggression_score=3.5, add_count=0, entry_lvns=[101.0],
            current_lvn=101.0, current_sl=99.0,
        )
        assert result is None


class TestPyramidAdd1:
    """First pyramid add (100% size)."""

    def test_add1_valid(self):
        """Valid add 1 → 100% size."""
        pm = PyramidManager()
        result = pm.check_pyramid(
            entry_price=100.0, current_price=101.0, is_long=True,
            aggression_score=3.5, add_count=0, entry_lvns=[99.0],
            current_lvn=101.0, current_sl=99.0,
        )
        assert result is not None
        assert result.size_multiplier == 1.0

    def test_add1_unified_sl(self):
        """Add 1 computes unified SL."""
        pm = PyramidManager()
        result = pm.check_pyramid(
            entry_price=100.0, current_price=101.0, is_long=True,
            aggression_score=3.5, add_count=0, entry_lvns=[99.0],
            current_lvn=101.0, current_sl=99.0,
        )
        assert result is not None
        assert result.unified_sl > 0


class TestPyramidAdd2:
    """Second pyramid add (50% size)."""

    def test_add2_valid(self):
        """Valid add 2 → 50% size."""
        pm = PyramidManager()
        result = pm.check_pyramid(
            entry_price=100.0, current_price=102.0, is_long=True,
            aggression_score=3.5, add_count=1, entry_lvns=[99.0, 101.0],
            current_lvn=102.0, current_sl=100.5,
        )
        assert result is not None
        assert result.size_multiplier == 0.5


class TestPyramidShort:
    """Pyramid for SHORT positions."""

    def test_short_in_profit(self):
        """SHORT position in profit → eligible."""
        pm = PyramidManager()
        result = pm.check_pyramid(
            entry_price=100.0, current_price=99.0, is_long=False,
            aggression_score=3.5, add_count=0, entry_lvns=[101.0],
            current_lvn=99.0, current_sl=101.0,
        )
        assert result is not None
        assert result.size_multiplier == 1.0