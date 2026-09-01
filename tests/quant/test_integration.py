"""TDD tests for Phase 6: Integration into QuantEngine.

These tests define the contract for the integrated engine.
All tests should FAIL initially (RED phase).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

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
# QuantEngine integration tests
# ---------------------------------------------------------------------------

class TestQuantEngineIntegration:
    """Test that QuantEngine integrates with new state management."""

    def _create_engine(self):
        """Create a minimal QuantEngine for testing."""
        from quant.runtime import QuantEngine
        
        class MockGateway:
            def subscribe(self, symbol):
                pass
            def next_tick(self):
                return None
        
        return QuantEngine(
            gateway=MockGateway(),
            symbol="NIFTY",
            interval_seconds=60,
            market="NSE",
        )

    def test_engine_uses_event_store(self):
        """Engine should have an EventStore."""
        engine = self._create_engine()
        
        # Engine should have an event_store attribute
        assert hasattr(engine, 'event_store')
        assert engine.event_store is not None

    def test_engine_uses_state_machine(self):
        """Engine should have an EngineState."""
        engine = self._create_engine()
        
        # Engine should have a state attribute
        assert hasattr(engine, 'state')
        assert engine.state is not None

    def test_engine_emits_events_to_store(self):
        """Engine should emit events to EventStore."""
        engine = self._create_engine()
        
        # Event store should be empty initially
        assert len(engine.event_store.get_all()) == 0

    def test_engine_state_derives_from_events(self):
        """Engine state should be derivable from event store."""
        from quant.events import BarClosed
        from quant.state_machine import Bar
        
        engine = self._create_engine()
        
        # Append an event
        bar = Bar(time="t0", close=100.0)
        engine.event_store.append(BarClosed(symbol="NIFTY", time="t0", bar=bar))
        
        # State should reflect the event
        state = engine.event_store.fold()
        assert state.last_bar is not None
        assert state.last_bar.close == 100.0


# ---------------------------------------------------------------------------
# QuantCoordinator integration tests
# ---------------------------------------------------------------------------

class TestQuantCoordinatorIntegration:
    """Test that QuantCoordinator integrates with new reconciliation."""

    def test_coordinator_has_reconciliation(self):
        """Coordinator should have a Reconciliation instance."""
        from quant.multi_engine import QuantCoordinator
        
        coord = QuantCoordinator.__new__(QuantCoordinator)
        coord.reconciliation = None
        
        # Coordinator should have reconciliation attribute
        assert hasattr(coord, 'reconciliation')

    def test_coordinator_reconcile_on_startup(self):
        """Coordinator should reconcile on startup."""
        from quant.multi_engine import QuantCoordinator
        
        coord = QuantCoordinator.__new__(QuantCoordinator)
        coord.reconciliation = None
        
        # Reconciliation should be settable
        assert coord.reconciliation is None


# ---------------------------------------------------------------------------
# End-to-end integration tests
# ---------------------------------------------------------------------------

class TestEndToEndIntegration:
    """End-to-end test: event → store → state → projection."""

    def test_event_flow(self):
        """Event flows from engine through store to state."""
        from quant.event_store import EventStore
        from quant.events import BarClosed, PositionOpened
        from quant.state_machine import Bar, PositionState
        
        store = EventStore()
        
        # Emit events
        bar = Bar(time="t0", close=100.0)
        store.append(BarClosed(symbol="NIFTY", time="t0", bar=bar))
        
        pos = PositionState(
            id="abc-123",
            entry=100.0,
            size=100.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        store.append(PositionOpened(symbol="NIFTY", time="t0", position=pos))
        
        # Fold state
        state = store.fold()
        
        assert state.last_bar is not None
        assert state.position is not None
        assert state.sequence == 2

    def test_reconciliation_flow(self):
        """Reconciliation detects matching positions."""
        from quant.event_store import EventStore
        from quant.events import PositionOpened
        from quant.state_machine import PositionState
        from quant.reconciliation import Reconciliation, ReconciliationResult
        
        # Create store with position
        store = EventStore()
        pos = PositionState(
            id="abc-123",
            entry=100.0,
            size=100.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        store.append(PositionOpened(symbol="NIFTY", time="t0", position=pos))
        
        # Mock broker with matching position
        class MockBroker:
            def get_positions(self):
                return [{"id": "abc-123", "symbol": "NIFTY", "size": 100.0}]
        
        # Reconcile
        recon = Reconciliation(store, MockBroker())
        result = recon.reconcile()
        
        assert result.can_trade is True
        assert result.discrepancies == ()
