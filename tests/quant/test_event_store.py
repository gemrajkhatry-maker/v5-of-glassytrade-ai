"""TDD tests for Phase 3: Event sourcing foundation.

These tests define the contract for the EventStore.
All tests should FAIL initially (RED phase).
"""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

class MockBar:
    def __init__(self, close=100.0):
        self.time = "t0"
        self.open = 100.0
        self.high = 101.0
        self.low = 99.0
        self.close = close
        self.volume = 100.0
        self.vwap = 100.0
        self.buy_volume = 50.0
        self.sell_volume = 50.0
        self.oi = 1000.0


class MockSignal:
    def __init__(self):
        self.type = "LONG"
        self.reason = "test"
        self.entry = 100.0
        self.sl = 95.0
        self.tp = 110.0
        self.rr = 2.0
        self.model_label = "Triple-A"
        self.symbol = "NIFTY"
        self.timestamp = "t0"


class MockOrder:
    def __init__(self):
        self.signal = MockSignal()
        self.quantity = 100.0


class MockPosition:
    def __init__(self, pos_id="abc-123"):
        self._id = pos_id
        self.order = MockOrder()
        self.open_price = 100.0
        self.open_time = "t0"
        self.size = 100.0
        self.realized_pnl = 0.0
        self.pyramid_level = 0
        self.is_pyramid = False


class MockFill:
    def __init__(self, pos_id="abc-123"):
        self.position = MockPosition(pos_id=pos_id)
        self.close_price = 95.0
        self.close_time = "t1"
        self.reason = "SL"
        self.pnl = -500.0


class MockRisk:
    def __init__(self):
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.halted = False
        self.halt_reason = ""


# ---------------------------------------------------------------------------
# EventStore tests
# ---------------------------------------------------------------------------

class TestEventStore:
    """EventStore is an append-only log of events."""

    def test_event_store_append_only(self):
        """Events can only be appended, never modified or deleted."""
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar
        
        store = EventStore()
        bar = Bar(time="t0", close=100.0)
        event = BarClosed(symbol="NIFTY", time="t0", bar=bar)
        
        seq = store.append(event)
        
        assert seq == 1
        events = store.get_all()
        assert len(events) == 1
        assert events[0] is event

    def test_event_store_sequence_numbers(self):
        """Sequence numbers are monotonic and gap-free."""
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar
        
        store = EventStore()
        
        for i in range(5):
            bar = Bar(time=f"t{i}", close=100.0 + i)
            event = BarClosed(symbol="NIFTY", time=f"t{i}", bar=bar)
            seq = store.append(event)
            assert seq == i + 1

    def test_event_store_get_all(self):
        """get_all returns all events in insertion order."""
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar
        
        store = EventStore()
        events = []
        
        for i in range(3):
            bar = Bar(time=f"t{i}", close=100.0 + i)
            event = BarClosed(symbol="NIFTY", time=f"t{i}", bar=bar)
            store.append(event)
            events.append(event)
        
        result = store.get_all()
        assert result == events

    def test_event_store_get_since(self):
        """get_since returns events from a sequence number onward."""
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar
        
        store = EventStore()
        
        for i in range(5):
            bar = Bar(time=f"t{i}", close=100.0 + i)
            event = BarClosed(symbol="NIFTY", time=f"t{i}", bar=bar)
            store.append(event)
        
        # Get events from sequence 3 onward
        result = store.get_since(3)
        assert len(result) == 3  # Events 3, 4, 5

    def test_event_store_get_last(self):
        """get_last returns the most recent event."""
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar
        
        store = EventStore()
        
        for i in range(3):
            bar = Bar(time=f"t{i}", close=100.0 + i)
            event = BarClosed(symbol="NIFTY", time=f"t{i}", bar=bar)
            store.append(event)
        
        last = store.get_last()
        assert last is not None
        assert last.bar.close == 102.0

    def test_event_store_is_empty_initially(self):
        """New event store is empty."""
        from quant.event_store import EventStore
        
        store = EventStore()
        
        assert store.get_all() == []
        assert store.get_last() is None


# ---------------------------------------------------------------------------
# EventStore.fold tests
# ---------------------------------------------------------------------------

class TestEventStoreFold:
    """fold() derives state from event log."""

    def test_fold_empty_store(self):
        """Folding empty store returns initial state."""
        from quant.event_store import EventStore
        from quant.state_machine import EngineState
        
        store = EventStore()
        state = store.fold()
        
        assert isinstance(state, EngineState)
        assert state.sequence == 0
        assert state.position is None

    def test_fold_single_bar(self):
        """Folding a single BarClosed event updates last_bar."""
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar, EngineState
        
        store = EventStore()
        bar = Bar(time="t0", close=100.0)
        store.append(BarClosed(symbol="NIFTY", time="t0", bar=bar))
        
        state = store.fold()
        
        assert isinstance(state, EngineState)
        assert state.last_bar is not None
        assert state.last_bar.close == 100.0
        assert state.sequence == 1

    def test_fold_entry_exit_cycle(self):
        """Folding entry then exit produces correct final state."""
        from quant.event_store import EventStore
        from quant.events import PositionOpened, PositionClosed
        from quant.state_machine import PositionState
        
        store = EventStore()
        
        # Entry
        pos = PositionState(
            id="abc-123",
            entry=100.0,
            size=100.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        store.append(PositionOpened(symbol="NIFTY", time="t0", position=pos))
        
        # Exit
        fill = MockFill()
        store.append(PositionClosed(symbol="NIFTY", time="t1", fill=fill))
        
        state = store.fold()
        
        assert state.position is None  # Position closed
        assert state.sequence == 2

    def test_fold_is_deterministic(self):
        """Folding the same events produces the same state."""
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar
        
        store = EventStore()
        for i in range(10):
            bar = Bar(time=f"t{i}", close=100.0 + i)
            store.append(BarClosed(symbol="NIFTY", time=f"t{i}", bar=bar))
        
        state1 = store.fold()
        state2 = store.fold()
        
        assert state1 == state2

    def test_fold_is_replayable(self):
        """Folding can be replayed from any point."""
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar
        
        store = EventStore()
        for i in range(10):
            bar = Bar(time=f"t{i}", close=100.0 + i)
            store.append(BarClosed(symbol="NIFTY", time=f"t{i}", bar=bar))
        
        # Fold all events
        full_state = store.fold()
        
        # Fold from sequence 5 onward
        partial_events = store.get_since(5)
        partial_store = EventStore()
        for event in partial_events:
            partial_store.append(event)
        partial_state = partial_store.fold()
        
        # Partial state should have fewer events
        assert partial_state.sequence < full_state.sequence


# ---------------------------------------------------------------------------
# EventStore persistence tests
# ---------------------------------------------------------------------------

class TestEventStorePersistence:
    """EventStore can be persisted and restored."""

    def test_event_store_can_export_events(self):
        """Events can be exported for persistence."""
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar
        
        store = EventStore()
        bar = Bar(time="t0", close=100.0)
        store.append(BarClosed(symbol="NIFTY", time="t0", bar=bar))
        
        exported = store.export()
        
        assert len(exported) == 1
        assert exported[0]["symbol"] == "NIFTY"
        assert exported[0]["event_type"] == "BarClosed"

    def test_event_store_can_import_events(self):
        """Events can be imported to restore state."""
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar
        
        # Create and export
        store1 = EventStore()
        bar = Bar(time="t0", close=100.0)
        store1.append(BarClosed(symbol="NIFTY", time="t0", bar=bar))
        exported = store1.export()
        
        # Import into new store
        store2 = EventStore()
        store2.import_(exported)
        
        # Both stores should have same number of events
        assert len(store1.get_all()) == len(store2.get_all())
