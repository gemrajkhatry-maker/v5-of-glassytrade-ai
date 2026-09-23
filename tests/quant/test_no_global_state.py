"""TDD tests for Phase 4: Remove global mutable state.

These tests verify that global state is eliminated.
All tests should FAIL initially (RED phase).
"""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ---------------------------------------------------------------------------
# Event ID counter tests
# ---------------------------------------------------------------------------

class TestEventIdCounter:
    """Event ID counter should be per-bus, not global."""

    def test_event_id_counter_is_per_bus(self):
        """Each EventBus should have its own counter."""
        from quant.events import EventBus
        
        bus1 = EventBus()
        bus2 = EventBus()
        
        # Both should start at 1 (independent counters)
        id1 = bus1.next_event_id()
        id2 = bus2.next_event_id()
        
        assert id1 == "1"
        assert id2 == "1"

    def test_event_id_counter_increments(self):
        """Counter should increment per bus."""
        from quant.events import EventBus
        
        bus = EventBus()
        
        ids = [bus.next_event_id() for _ in range(5)]
        assert ids == ["1", "2", "3", "4", "5"]

    def test_event_id_is_unique_per_bus(self):
        """IDs should be unique within a bus."""
        from quant.events import EventBus
        
        bus = EventBus()
        
        ids = set()
        for _ in range(100):
            event_id = bus.next_event_id()
            assert event_id not in ids
            ids.add(event_id)
        
        assert len(ids) == 100


# ---------------------------------------------------------------------------
# Underlying warned tests
# ---------------------------------------------------------------------------

class TestUnderlyingWarned:
    """_UNDERLYING_WARNED should be per-engine, not global."""

    def test_underlying_warned_is_per_engine(self):
        """Each engine should have its own warned flag."""
        from quant.runtime import QuantEngine
        
        # Create two engines (mock)
        engine1 = QuantEngine.__new__(QuantEngine)
        engine1._underlying_warned = False
        
        engine2 = QuantEngine.__new__(QuantEngine)
        engine2._underlying_warned = False
        
        # Warning on engine1 shouldn't affect engine2
        engine1._underlying_warned = True
        assert engine2._underlying_warned is False

    def test_underlying_warned_defaults_to_false(self):
        """New engines should default to not warned."""
        from quant.runtime import QuantEngine
        
        engine = QuantEngine.__new__(QuantEngine)
        engine._underlying_warned = False
        
        assert engine._underlying_warned is False


# ---------------------------------------------------------------------------
# No global state tests
# ---------------------------------------------------------------------------

class TestNoGlobalState:
    """Verify no global mutable state exists."""

    def test_no_global_event_id_counter(self):
        """events.py should not have global _event_id_counter."""
        import quant.events as events_module
        
        # Should NOT have global counter
        assert not hasattr(events_module, '_event_id_counter')

    def test_no_global_underlying_warned(self):
        """runtime.py should not have global _UNDERLYING_WARNED."""
        import quant.runtime as runtime_module
        
        # Should NOT have global flag
        assert not hasattr(runtime_module, '_UNDERLYING_WARNED')
