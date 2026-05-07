"""Tests for Reconciliation Engine - internal vs broker state comparison."""
import pytest
from datetime import datetime, timezone
from decimal import Decimal
from brokersv2.oms.reconciliation import (
    ReconciliationEngine,
    OrderSnapshot,
    ReconciliationResult,
    Discrepancy,
    DiscrepancyType,
    ReconciliationError,
)


@pytest.fixture
def now():
    return datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


class TestOrderSnapshot:
    """Test OrderSnapshot value object."""

    def test_create_snapshot(self, now):
        """Test creating order snapshot."""
        snapshot = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="FILLED",
            filled_quantity=100,
            average_price=Decimal("100.50"),
            broker_order_id="BROKER123",
        )

        assert snapshot.order_id == "ORD001"
        assert snapshot.state == "FILLED"
        assert snapshot.filled_quantity == 100
        assert snapshot.average_price == Decimal("100.50")

    def test_snapshot_equality(self, now):
        """Test snapshot equality check."""
        snapshot1 = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="FILLED",
            filled_quantity=100,
            average_price=Decimal("100.50"),
            broker_order_id="BROKER123",
        )

        snapshot2 = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="FILLED",
            filled_quantity=100,
            average_price=Decimal("100.50"),
            broker_order_id="BROKER123",
        )

        assert snapshot1 == snapshot2

    def test_snapshot_inequality(self, now):
        """Test snapshot inequality."""
        snapshot1 = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="FILLED",
            filled_quantity=100,
            average_price=Decimal("100.50"),
            broker_order_id="BROKER123",
        )

        snapshot2 = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="PARTIAL",
            filled_quantity=50,
            average_price=Decimal("100.00"),
            broker_order_id="BROKER123",
        )

        assert snapshot1 != snapshot2


class TestDiscrepancy:
    """Test Discrepancy value object."""

    def test_state_mismatch(self, now):
        """Test state mismatch discrepancy."""
        internal = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="FILLED",
            filled_quantity=100,
            average_price=Decimal("100.50"),
        )

        broker = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="PARTIAL",
            filled_quantity=50,
            average_price=Decimal("100.00"),
        )

        discrepancy = Discrepancy(
            order_id="ORD001",
            discrepancy_type=DiscrepancyType.STATE_MISMATCH,
            internal_snapshot=internal,
            broker_snapshot=broker,
            severity="HIGH",
        )

        assert discrepancy.order_id == "ORD001"
        assert discrepancy.discrepancy_type == DiscrepancyType.STATE_MISMATCH
        assert discrepancy.severity == "HIGH"

    def test_quantity_mismatch(self, now):
        """Test quantity mismatch discrepancy."""
        discrepancy = Discrepancy(
            order_id="ORD001",
            discrepancy_type=DiscrepancyType.QUANTITY_MISMATCH,
            internal_snapshot=None,
            broker_snapshot=None,
            severity="MEDIUM",
        )

        assert discrepancy.discrepancy_type == DiscrepancyType.QUANTITY_MISMATCH


class TestDiscrepancyType:
    """Test discrepancy type enum."""

    def test_type_values(self):
        """Test enum values."""
        assert DiscrepancyType.STATE_MISMATCH.value == "STATE_MISMATCH"
        assert DiscrepancyType.QUANTITY_MISMATCH.value == "QUANTITY_MISMATCH"
        assert DiscrepancyType.PRICE_MISMATCH.value == "PRICE_MISMATCH"
        assert DiscrepancyType.MISSING_IN_BROKER.value == "MISSING_IN_BROKER"
        assert DiscrepancyType.MISSING_IN_INTERNAL.value == "MISSING_IN_INTERNAL"


class TestReconciliationEngine:
    """Test reconciliation logic."""

    def test_reconcile_matching_orders(self, now):
        """Test reconciliation when orders match."""
        engine = ReconciliationEngine()

        internal = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="FILLED",
            filled_quantity=100,
            average_price=Decimal("100.50"),
            broker_order_id="BROKER123",
        )

        broker = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="FILLED",
            filled_quantity=100,
            average_price=Decimal("100.50"),
            broker_order_id="BROKER123",
        )

        result = engine.reconcile_order("ORD001", internal, broker)

        assert result is not None
        assert result.is_reconciled is True
        assert len(result.discrepancies) == 0

    def test_reconcile_state_mismatch(self, now):
        """Test reconciliation with state mismatch."""
        engine = ReconciliationEngine()

        internal = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="FILLED",
            filled_quantity=100,
            average_price=Decimal("100.50"),
            broker_order_id="BROKER123",
        )

        broker = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="PARTIAL",
            filled_quantity=50,
            average_price=Decimal("100.00"),
            broker_order_id="BROKER123",
        )

        result = engine.reconcile_order("ORD001", internal, broker)

        assert result is not None
        assert result.is_reconciled is False
        # State mismatch also causes quantity and price mismatches
        assert len(result.discrepancies) == 3
        assert result.discrepancies[0].discrepancy_type == DiscrepancyType.STATE_MISMATCH

    def test_reconcile_quantity_mismatch(self, now):
        """Test reconciliation with quantity mismatch."""
        engine = ReconciliationEngine()

        internal = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="FILLED",
            filled_quantity=100,
            average_price=Decimal("100.50"),
            broker_order_id="BROKER123",
        )

        broker = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="FILLED",
            filled_quantity=90,
            average_price=Decimal("100.50"),
            broker_order_id="BROKER123",
        )

        result = engine.reconcile_order("ORD001", internal, broker)

        assert result is not None
        assert result.is_reconciled is False
        assert len(result.discrepancies) == 1
        assert result.discrepancies[0].discrepancy_type == DiscrepancyType.QUANTITY_MISMATCH

    def test_reconcile_price_mismatch(self, now):
        """Test reconciliation with price mismatch."""
        engine = ReconciliationEngine(tolerance=Decimal("0.01"))

        internal = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="FILLED",
            filled_quantity=100,
            average_price=Decimal("100.50"),
            broker_order_id="BROKER123",
        )

        broker = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="FILLED",
            filled_quantity=100,
            average_price=Decimal("101.00"),
            broker_order_id="BROKER123",
        )

        result = engine.reconcile_order("ORD001", internal, broker)

        assert result is not None
        assert result.is_reconciled is False
        assert len(result.discrepancies) == 1
        assert result.discrepancies[0].discrepancy_type == DiscrepancyType.PRICE_MISMATCH

    def test_reconcile_price_within_tolerance(self, now):
        """Test reconciliation with price within tolerance."""
        engine = ReconciliationEngine(tolerance=Decimal("1.00"))

        internal = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="FILLED",
            filled_quantity=100,
            average_price=Decimal("100.50"),
            broker_order_id="BROKER123",
        )

        broker = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="FILLED",
            filled_quantity=100,
            average_price=Decimal("100.75"),
            broker_order_id="BROKER123",
        )

        result = engine.reconcile_order("ORD001", internal, broker)

        assert result is not None
        assert result.is_reconciled is True  # Within tolerance

    def test_reconcile_missing_in_broker(self, now):
        """Test reconciliation when order missing in broker."""
        engine = ReconciliationEngine()

        internal = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="FILLED",
            filled_quantity=100,
            average_price=Decimal("100.50"),
            broker_order_id="BROKER123",
        )

        result = engine.reconcile_order("ORD001", internal, None)

        assert result is not None
        assert result.is_reconciled is False
        assert len(result.discrepancies) == 1
        assert result.discrepancies[0].discrepancy_type == DiscrepancyType.MISSING_IN_BROKER

    def test_reconcile_missing_in_internal(self, now):
        """Test reconciliation when order missing in internal."""
        engine = ReconciliationEngine()

        broker = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="FILLED",
            filled_quantity=100,
            average_price=Decimal("100.50"),
            broker_order_id="BROKER123",
        )

        result = engine.reconcile_order("ORD001", None, broker)

        assert result is not None
        assert result.is_reconciled is False
        assert len(result.discrepancies) == 1
        assert result.discrepancies[0].discrepancy_type == DiscrepancyType.MISSING_IN_INTERNAL

    def test_batch_reconciliation(self, now):
        """Test batch reconciliation."""
        engine = ReconciliationEngine()

        internal_orders = {
            "ORD001": OrderSnapshot(
                order_id="ORD001",
                timestamp=now,
                state="FILLED",
                filled_quantity=100,
                average_price=Decimal("100.50"),
            ),
            "ORD002": OrderSnapshot(
                order_id="ORD002",
                timestamp=now,
                state="PARTIAL",
                filled_quantity=50,
                average_price=Decimal("100.00"),
            ),
        }

        broker_orders = {
            "ORD001": OrderSnapshot(
                order_id="ORD001",
                timestamp=now,
                state="FILLED",
                filled_quantity=100,
                average_price=Decimal("100.50"),
            ),
            "ORD002": OrderSnapshot(
                order_id="ORD002",
                timestamp=now,
                state="FILLED",  # Mismatch
                filled_quantity=100,
                average_price=Decimal("100.00"),
            ),
        }

        results = engine.reconcile_batch(internal_orders, broker_orders)

        assert len(results) == 2
        assert results["ORD001"].is_reconciled is True
        assert results["ORD002"].is_reconciled is False

    def test_get_discrepancy_summary(self, now):
        """Test discrepancy summary statistics."""
        engine = ReconciliationEngine()

        internal = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="FILLED",
            filled_quantity=100,
            average_price=Decimal("100.50"),
        )

        broker = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="PARTIAL",
            filled_quantity=50,
            average_price=Decimal("100.00"),
        )

        result = engine.reconcile_order("ORD001", internal, broker)
        summary = engine.get_discrepancy_summary([result])

        assert summary.total_orders == 1
        assert summary.reconciled == 0
        assert summary.discrepancies == 3  # State, quantity, price
        assert summary.reconciliation_rate == pytest.approx(0.0)

    def test_auto_resolve_state_mismatch(self, now):
        """Test auto-resolving state mismatch (prefer broker state)."""
        engine = ReconciliationEngine(auto_resolve=True)

        internal = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="FILLED",
            filled_quantity=100,
            average_price=Decimal("100.50"),
        )

        broker = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="PARTIAL",
            filled_quantity=50,
            average_price=Decimal("100.00"),
        )

        result = engine.reconcile_order("ORD001", internal, broker)

        assert result is not None
        assert result.was_auto_resolved is True
        assert result.resolved_state == "PARTIAL"  # Broker state preferred

    def test_reconciliation_result_metadata(self, now):
        """Test reconciliation result metadata."""
        engine = ReconciliationEngine()

        internal = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="FILLED",
            filled_quantity=100,
            average_price=Decimal("100.50"),
        )

        broker = OrderSnapshot(
            order_id="ORD001",
            timestamp=now,
            state="FILLED",
            filled_quantity=100,
            average_price=Decimal("100.50"),
        )

        result = engine.reconcile_order("ORD001", internal, broker)

        assert result.order_id == "ORD001"
        assert result.timestamp is not None
        assert result.is_reconciled is True

    def test_reconcile_empty_orders(self, now):
        """Test reconciliation with empty order sets."""
        engine = ReconciliationEngine()

        results = engine.reconcile_batch({}, {})

        assert len(results) == 0

    def test_tolerance_configuration(self):
        """Test tolerance configuration."""
        engine_strict = ReconciliationEngine(tolerance=Decimal("0.01"))
        assert engine_strict.tolerance == Decimal("0.01")

        engine_loose = ReconciliationEngine(tolerance=Decimal("1.00"))
        assert engine_loose.tolerance == Decimal("1.00")
