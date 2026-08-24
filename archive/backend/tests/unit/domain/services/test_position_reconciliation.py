"""Tests for Position Reconciliation Engine."""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from app.domain.ops.position_reconciliation import (
    PositionReconciliationEngine,
    ReconciliationIssue,
    ReconciliationResult,
)


class TestReconciliationIssue:
    """Tests for ReconciliationIssue enum."""

    def test_ghost_position(self):
        assert ReconciliationIssue.GHOST_POSITION.value == "GHOST_POSITION"

    def test_missing_position(self):
        assert ReconciliationIssue.MISSING_POSITION.value == "MISSING_POSITION"

    def test_quantity_mismatch(self):
        assert ReconciliationIssue.QUANTITY_MISMATCH.value == "QUANTITY_MISMATCH"


class TestReconciliationResult:
    """Tests for ReconciliationResult dataclass."""

    def test_create_result(self):
        """Test creating a ReconciliationResult."""
        result = ReconciliationResult(
            issue=ReconciliationIssue.GHOST_POSITION,
            internal_id="INT1",
            broker_id="BR1",
            internal_qty=100.0,
            broker_qty=0.0,
            internal_symbol="NIFTY",
            broker_symbol="",
            resolution="Mark as closed",
            severity="CRITICAL",
        )
        assert result.issue == ReconciliationIssue.GHOST_POSITION
        assert result.internal_id == "INT1"
        assert result.severity == "CRITICAL"

    def test_frozen(self):
        """Test that ReconciliationResult is frozen (immutable)."""
        result = ReconciliationResult(
            issue=ReconciliationIssue.OK,
            internal_id="",
            broker_id="",
            internal_qty=0.0,
            broker_qty=0.0,
            internal_symbol="",
            broker_symbol="",
            resolution="",
            severity="OK",
        )
        try:
            result.severity = "CHANGED"
            assert False, "Should have raised"
        except AttributeError:
            pass  # Expected - frozen dataclass


class TestPositionReconciliationEngine:
    """Tests for PositionReconciliationEngine."""

    def setup_method(self):
        """Set up test engine."""
        self.engine = PositionReconciliationEngine(broker_adapter=None)

    def test_init(self):
        """Test engine initialization."""
        assert self.engine._broker is None
        assert self.engine._issues_found == 0
        assert self.engine._ghost_positions == 0
        assert self.engine._mismatches == 0

    def test_init_with_broker(self):
        """Test engine with broker adapter."""
        mock_broker = MagicMock()
        engine = PositionReconciliationEngine(broker_adapter=mock_broker)
        assert engine._broker == mock_broker

    def test_reconcile_no_issues(self):
        """Test reconciliation with no issues."""
        internal = {
            "POS1": MagicMock(
                symbol="NIFTY",
                size=100.0,
                spec=["trading_symbol", "NIFTY"],
            )
        }
        internal["POS1"].symbol = "NIFTY"
        internal["POS1"].size = 100.0

        broker = [
            {"trading_symbol": "NIFTY", "netQty": 100.0, "orderId": "BR1"},
        ]

        results = self.engine.reconcile(internal, broker)
        assert len(results) == 0  # No issues
        assert self.engine._issues_found == 0

    def test_reconcile_ghost_position(self):
        """Test detecting ghost positions (in system, not in broker)."""
        internal = {
            "POS1": MagicMock(symbol="NIFTY", size=100.0),
        }
        internal["POS1"].symbol = "NIFTY"
        internal["POS1"].size = 100.0

        broker = []  # No positions in broker

        results = self.engine.reconcile(internal, broker)
        assert len(results) == 1
        assert results[0].issue == ReconciliationIssue.GHOST_POSITION
        assert results[0].internal_id == "POS1"
        assert results[0].severity == "CRITICAL"
        assert self.engine._issues_found == 1
        assert self.engine._ghost_positions == 1

    def test_reconcile_missing_position(self):
        """Test detecting missing positions (in broker, not in system)."""
        internal = {}  # No positions in system

        broker = [
            {"trading_symbol": "NIFTY", "netQty": 50.0, "orderId": "BR1"},
        ]

        results = self.engine.reconcile(internal, broker)
        assert len(results) == 1
        assert results[0].issue == ReconciliationIssue.MISSING_POSITION
        assert results[0].broker_id == "BR1"
        assert results[0].severity == "WARNING"
        assert self.engine._issues_found == 1

    def test_reconcile_quantity_mismatch(self):
        """Test detecting quantity mismatches."""
        internal = {
            "POS1": MagicMock(symbol="NIFTY", size=100.0),
        }
        internal["POS1"].symbol = "NIFTY"
        internal["POS1"].size = 100.0

        broker = [
            {"trading_symbol": "NIFTY", "netQty": 50.0, "orderId": "BR1"},
        ]

        results = self.engine.reconcile(internal, broker)
        assert len(results) == 1
        assert results[0].issue == ReconciliationIssue.QUANTITY_MISMATCH
        assert results[0].internal_qty == 100.0
        assert results[0].broker_qty == 50.0
        assert results[0].severity == "WARNING"
        assert self.engine._mismatches == 1

    def test_reconcile_multiple_issues(self):
        """Test reconciliation with multiple issues."""
        internal = {
            "POS1": MagicMock(symbol="NIFTY", size=100.0),
            "POS2": MagicMock(symbol="BANKNIFTY", size=200.0),
        }
        internal["POS1"].symbol = "NIFTY"
        internal["POS1"].size = 100.0
        internal["POS2"].symbol = "BANKNIFTY"
        internal["POS2"].size = 200.0

        broker = [
            {"trading_symbol": "NIFTY", "netQty": 100.0, "orderId": "BR1"},
            # POS2 is ghost (not in broker)
            {"trading_symbol": "STOCK", "netQty": 50.0, "orderId": "BR2"},
            # STOCK is missing (not in system)
        ]

        results = self.engine.reconcile(internal, broker)
        issues = {r.issue for r in results}
        assert ReconciliationIssue.GHOST_POSITION in issues
        assert ReconciliationIssue.MISSING_POSITION in issues
        assert self.engine._issues_found == 2
        assert self.engine._ghost_positions == 1

    def test_get_stats(self):
        """Test getting statistics."""
        self.engine._issues_found = 5
        self.engine._ghost_positions = 2
        self.engine._mismatches = 3

        stats = self.engine.get_stats()
        assert stats["issues_found"] == 5
        assert stats["ghost_positions"] == 2
        assert stats["mismatches"] == 3

    def test_reset_stats(self):
        """Test resetting statistics."""
        self.engine._issues_found = 10
        self.engine._ghost_positions = 4
        self.engine._mismatches = 6

        self.engine.reset_stats()
        assert self.engine._issues_found == 0
        assert self.engine._ghost_positions == 0
        assert self.engine._mismatches == 0
