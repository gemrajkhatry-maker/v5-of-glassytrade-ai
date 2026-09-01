"""TDD tests for Phase 5: Reconciliation after restart.

These tests define the contract for the Reconciliation service.
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
# Reconciliation tests
# ---------------------------------------------------------------------------

class TestReconciliation:
    """Reconciliation rebuilds state from journal and compares with broker."""

    def test_reconcile_no_positions(self):
        """No positions in journal or broker → can trade."""
        from quant.reconciliation import Reconciliation, ReconciliationResult
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar
        
        # Empty journal
        store = EventStore()
        store.append(BarClosed(symbol="NIFTY", time="t0", bar=Bar(close=100.0)))
        
        # Mock broker with no positions
        class MockBroker:
            def get_positions(self):
                return []
        
        recon = Reconciliation(store, MockBroker())
        result = recon.reconcile()
        
        assert isinstance(result, ReconciliationResult)
        assert result.can_trade is True
        assert result.discrepancies == ()

    def test_reconcile_matching_positions(self):
        """Position in journal matches broker → can trade."""
        from quant.reconciliation import Reconciliation, ReconciliationResult
        from quant.event_store import EventStore
        from quant.events import PositionOpened
        from quant.state_machine import PositionState
        
        pos = PositionState(
            id="abc-123",
            entry=100.0,
            size=100.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        
        store = EventStore()
        store.append(PositionOpened(symbol="NIFTY", time="t0", position=pos))
        
        # Mock broker with matching position
        class MockBroker:
            def get_positions(self):
                return [{"id": "abc-123", "symbol": "NIFTY", "size": 100.0}]
        
        recon = Reconciliation(store, MockBroker())
        result = recon.reconcile()
        
        assert result.can_trade is True
        assert result.discrepancies == ()

    def test_reconcile_stale_position(self):
        """Position in journal but not in broker → stale, can trade after removal."""
        from quant.reconciliation import Reconciliation, ReconciliationResult
        from quant.event_store import EventStore
        from quant.events import PositionOpened
        from quant.state_machine import PositionState
        
        pos = PositionState(
            id="abc-123",
            entry=100.0,
            size=100.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        
        store = EventStore()
        store.append(PositionOpened(symbol="NIFTY", time="t0", position=pos))
        
        # Mock broker with no positions (stale)
        class MockBroker:
            def get_positions(self):
                return []
        
        recon = Reconciliation(store, MockBroker())
        result = recon.reconcile()
        
        # Stale position detected, but can trade after acknowledging
        assert result.can_trade is True
        assert len(result.discrepancies) == 1
        assert "abc-123" in result.discrepancies[0]

    def test_reconcile_orphaned_position(self):
        """Position in broker but not in journal → orphaned, cannot trade."""
        from quant.reconciliation import Reconciliation, ReconciliationResult
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar
        
        # Empty journal (no positions)
        store = EventStore()
        store.append(BarClosed(symbol="NIFTY", time="t0", bar=Bar(close=100.0)))
        
        # Mock broker with orphaned position
        class MockBroker:
            def get_positions(self):
                return [{"id": "abc-123", "symbol": "NIFTY", "size": 100.0}]
        
        recon = Reconciliation(store, MockBroker())
        result = recon.reconcile()
        
        # Orphaned position → cannot trade until resolved
        assert result.can_trade is False
        assert len(result.discrepancies) == 1
        assert "abc-123" in result.discrepancies[0]

    def test_reconcile_size_mismatch(self):
        """Position size mismatch between journal and broker → cannot trade."""
        from quant.reconciliation import Reconciliation, ReconciliationResult
        from quant.event_store import EventStore
        from quant.events import PositionOpened
        from quant.state_machine import PositionState
        
        pos = PositionState(
            id="abc-123",
            entry=100.0,
            size=100.0,  # Journal says 100
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        
        store = EventStore()
        store.append(PositionOpened(symbol="NIFTY", time="t0", position=pos))
        
        # Mock broker with different size
        class MockBroker:
            def get_positions(self):
                return [{"id": "abc-123", "symbol": "NIFTY", "size": 50.0}]  # Broker says 50
        
        recon = Reconciliation(store, MockBroker())
        result = recon.reconcile()
        
        # Size mismatch → cannot trade
        assert result.can_trade is False
        assert len(result.discrepancies) == 1


# ---------------------------------------------------------------------------
# ReconciliationResult tests
# ---------------------------------------------------------------------------

class TestReconciliationResult:
    """ReconciliationResult is a frozen dataclass."""

    def test_result_creation(self):
        """ReconciliationResult can be created."""
        from quant.reconciliation import ReconciliationResult
        
        result = ReconciliationResult(
            can_trade=True,
            discrepancies=(),
        )
        
        assert result.can_trade is True
        assert result.discrepancies == ()

    def test_result_is_immutable(self):
        """ReconciliationResult is frozen."""
        from quant.reconciliation import ReconciliationResult
        
        result = ReconciliationResult(
            can_trade=True,
            discrepancies=(),
        )
        
        with pytest.raises(AttributeError):
            result.can_trade = False

    def test_result_with_discrepancies(self):
        """Result with discrepancies cannot trade."""
        from quant.reconciliation import ReconciliationResult
        
        result = ReconciliationResult(
            can_trade=False,
            discrepancies=("Position abc-123: stale",),
        )
        
        assert result.can_trade is False
        assert len(result.discrepancies) == 1
