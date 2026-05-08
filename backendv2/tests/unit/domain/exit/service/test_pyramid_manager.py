"""Tests for PyramidManager — pyramid add logic and guards."""

from __future__ import annotations

import pytest

from app.domain.exit.service.pyramid_manager import PyramidManager


class TestPyramidManager:
    def setup_method(self):
        self.manager = PyramidManager()

    def test_allows_first_add_when_in_profit(self):
        """First add (add_count=0) with price in profit and aggression >= 3.0."""
        signal = self.manager.check_pyramid(
            entry_price=100.0,
            current_price=101.0,
            is_long=True,
            aggression_score=3.5,
            add_count=0,
            entry_lvns=[99.5],
            current_lvn=100.5,
            current_sl=99.0,
        )
        assert signal is not None
        assert signal.size_multiplier == 1.0

    def test_allows_second_add_with_half_size(self):
        """Second add (add_count=1) should use size_multiplier=0.5."""
        signal = self.manager.check_pyramid(
            entry_price=100.0,
            current_price=102.0,
            is_long=True,
            aggression_score=4.0,
            add_count=1,
            entry_lvns=[99.5, 101.0],
            current_lvn=101.5,
            current_sl=100.0,
        )
        assert signal is not None
        assert signal.size_multiplier == 0.5

    def test_max_adds_guard_blocks_third_add(self):
        """Third add (add_count=2) should be blocked by MAX_ADDS=2."""
        signal = self.manager.check_pyramid(
            entry_price=100.0,
            current_price=103.0,
            is_long=True,
            aggression_score=5.0,
            add_count=2,
            entry_lvns=[99.5, 101.0, 102.0],
            current_lvn=102.5,
            current_sl=101.0,
        )
        assert signal is None

    def test_blocks_add_when_not_in_profit_long(self):
        """LONG position with current_price <= entry_price should block."""
        signal = self.manager.check_pyramid(
            entry_price=100.0,
            current_price=99.0,
            is_long=True,
            aggression_score=4.0,
            add_count=0,
            entry_lvns=[99.5],
            current_lvn=100.0,
            current_sl=98.0,
        )
        assert signal is None

    def test_blocks_add_when_not_in_profit_short(self):
        """SHORT position with current_price >= entry_price should block."""
        signal = self.manager.check_pyramid(
            entry_price=100.0,
            current_price=101.0,
            is_long=False,
            aggression_score=4.0,
            add_count=0,
            entry_lvns=[100.5],
            current_lvn=99.5,
            current_sl=102.0,
        )
        assert signal is None

    def test_blocks_add_when_low_aggression(self):
        """Aggression score < 3.0 should block."""
        signal = self.manager.check_pyramid(
            entry_price=100.0,
            current_price=101.0,
            is_long=True,
            aggression_score=2.5,
            add_count=0,
            entry_lvns=[99.5],
            current_lvn=100.5,
            current_sl=99.0,
        )
        assert signal is None

    def test_blocks_add_when_lvn_too_close(self):
        """Current LVN within 0.3% of previous LVN should block."""
        signal = self.manager.check_pyramid(
            entry_price=100.0,
            current_price=101.0,
            is_long=True,
            aggression_score=4.0,
            add_count=0,
            entry_lvns=[99.5, 100.95],  # Very close to current_lvn=101.0
            current_lvn=101.0,
            current_sl=99.0,
        )
        assert signal is None

    def test_short_position_proper_pyramid(self):
        """SHORT position pyramids when price drops below entry."""
        signal = self.manager.check_pyramid(
            entry_price=100.0,
            current_price=98.0,
            is_long=False,
            aggression_score=3.5,
            add_count=0,
            entry_lvns=[100.5],
            current_lvn=99.0,
            current_sl=101.0,
        )
        assert signal is not None
        assert signal.size_multiplier == 1.0
        # SL should be min(101.0, 98.0 * 1.005) = 98.49
        assert signal.unified_sl < 100.0

    def test_serialize_deserialize_position_state_roundtrip(self):
        """Serialization and deserialization should preserve state."""
        original = self.manager.serialize_position_state(
            position_id="pos-123",
            add_count=1,
            entry_lvns=[99.5, 101.0],
        )
        position_id, add_count, entry_lvns = self.manager.deserialize_position_state(original)
        assert position_id == "pos-123"
        assert add_count == 1
        assert entry_lvns == [99.5, 101.0]

    def test_deserialize_handles_missing_fields_gracefully(self):
        """Deserialization should handle missing fields with defaults."""
        data = {"position_id": "pos-456"}
        position_id, add_count, entry_lvns = self.manager.deserialize_position_state(data)
        assert position_id == "pos-456"
        assert add_count == 0
        assert entry_lvns == []
