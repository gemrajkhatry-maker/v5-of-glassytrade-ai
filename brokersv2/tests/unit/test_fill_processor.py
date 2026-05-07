"""Tests for Fill Processor - partial fills, average price, execution stats."""
import pytest
from datetime import datetime, timezone
from decimal import Decimal
from brokersv2.oms.fill_processor import (
    FillProcessor,
    FillRecord,
    FillStats,
    FillProcessorError,
    InvalidFillError,
)


@pytest.fixture
def now():
    return datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


class TestFillRecord:
    """Test FillRecord value object."""

    def test_create_fill(self, now):
        """Test creating fill record."""
        fill = FillRecord(
            order_id="ORD001",
            fill_id="FILL001",
            timestamp=now,
            quantity=100,
            price=Decimal("100.50"),
            commission=Decimal("10.00"),
            exchange_order_id="EXCH123",
        )

        assert fill.order_id == "ORD001"
        assert fill.fill_id == "FILL001"
        assert fill.quantity == 100
        assert fill.price == Decimal("100.50")
        assert fill.commission == Decimal("10.00")
        assert fill.exchange_order_id == "EXCH123"

    def test_fill_value(self, now):
        """Test fill value calculation."""
        fill = FillRecord(
            order_id="ORD001",
            fill_id="FILL001",
            timestamp=now,
            quantity=100,
            price=Decimal("100.50"),
            commission=Decimal("10.00"),
            exchange_order_id="EXCH123",
        )

        assert fill.value == Decimal("10050.00")  # 100 * 100.50

    def test_fill_net_value(self, now):
        """Test fill net value (value + commission)."""
        fill = FillRecord(
            order_id="ORD001",
            fill_id="FILL001",
            timestamp=now,
            quantity=100,
            price=Decimal("100.50"),
            commission=Decimal("10.00"),
            exchange_order_id="EXCH123",
        )

        assert fill.net_value == Decimal("10060.00")  # 10050 + 10


class TestFillStats:
    """Test FillStats value object."""

    def test_empty_stats(self, now):
        """Test stats with no fills."""
        stats = FillStats(order_id="ORD001", ordered_quantity=100)

        assert stats.total_filled == 0
        assert stats.avg_fill_price == Decimal("0")
        assert stats.total_commission == Decimal("0")
        assert stats.fill_count == 0
        assert stats.is_complete is False

    def test_single_fill_stats(self, now):
        """Test stats with single fill."""
        fill = FillRecord(
            order_id="ORD001",
            fill_id="FILL001",
            timestamp=now,
            quantity=100,
            price=Decimal("100.00"),
            commission=Decimal("5.00"),
            exchange_order_id="EXCH123",
        )

        stats = FillStats(order_id="ORD001", fills=[fill], ordered_quantity=100)

        assert stats.total_filled == 100
        assert stats.avg_fill_price == Decimal("100.00")
        assert stats.total_commission == Decimal("5.00")
        assert stats.fill_count == 1
        assert stats.is_complete is True  # 100/100 filled

    def test_multiple_fills_stats(self, now):
        """Test stats with multiple fills."""
        fills = [
            FillRecord(
                order_id="ORD001",
                fill_id="FILL001",
                timestamp=now,
                quantity=50,
                price=Decimal("100.00"),
                commission=Decimal("2.50"),
                exchange_order_id="EXCH123",
            ),
            FillRecord(
                order_id="ORD001",
                fill_id="FILL002",
                timestamp=now,
                quantity=50,
                price=Decimal("101.00"),
                commission=Decimal("2.50"),
                exchange_order_id="EXCH123",
            ),
        ]

        stats = FillStats(order_id="ORD001", fills=fills, ordered_quantity=100)

        assert stats.total_filled == 100
        # Average: (50*100 + 50*101) / 100 = 100.50
        assert stats.avg_fill_price == Decimal("100.50")
        assert stats.total_commission == Decimal("5.00")
        assert stats.fill_count == 2
        assert stats.is_complete is True

    def test_partial_fill_stats(self, now):
        """Test stats with partial fill."""
        fill = FillRecord(
            order_id="ORD001",
            fill_id="FILL001",
            timestamp=now,
            quantity=50,
            price=Decimal("100.00"),
            commission=Decimal("2.50"),
            exchange_order_id="EXCH123",
        )

        stats = FillStats(order_id="ORD001", fills=[fill], ordered_quantity=100)

        assert stats.total_filled == 50
        assert stats.avg_fill_price == Decimal("100.00")
        assert stats.fill_count == 1
        assert stats.is_complete is False  # Only 50/100 filled
        assert stats.fill_percentage == pytest.approx(50.0)

    def test_fill_percentage(self, now):
        """Test fill percentage calculation."""
        fill = FillRecord(
            order_id="ORD001",
            fill_id="FILL001",
            timestamp=now,
            quantity=75,
            price=Decimal("100.00"),
            commission=Decimal("0"),
            exchange_order_id="EXCH123",
        )

        stats = FillStats(order_id="ORD001", fills=[fill], ordered_quantity=100)

        assert stats.fill_percentage == pytest.approx(75.0)


class TestFillProcessor:
    """Test fill processing logic."""

    def test_process_single_fill(self, now):
        """Test processing single fill."""
        processor = FillProcessor(order_id="ORD001", ordered_quantity=100)

        fill = processor.process_fill(
            fill_id="FILL001",
            quantity=100,
            price=Decimal("100.50"),
            timestamp=now,
            exchange_order_id="EXCH123",
        )

        assert fill is not None
        assert fill.quantity == 100
        assert fill.price == Decimal("100.50")

    def test_process_partial_fills(self, now):
        """Test processing multiple partial fills."""
        processor = FillProcessor(order_id="ORD001", ordered_quantity=100)

        fill1 = processor.process_fill(
            fill_id="FILL001",
            quantity=50,
            price=Decimal("100.00"),
            timestamp=now,
            exchange_order_id="EXCH123",
        )

        fill2 = processor.process_fill(
            fill_id="FILL002",
            quantity=50,
            price=Decimal("101.00"),
            timestamp=now,
            exchange_order_id="EXCH123",
        )

        assert fill1 is not None
        assert fill2 is not None

        stats = processor.get_stats()
        assert stats.total_filled == 100
        assert stats.avg_fill_price == Decimal("100.50")
        assert stats.is_complete is True

    def test_overfill_rejected(self, now):
        """Test that overfill is rejected."""
        processor = FillProcessor(order_id="ORD001", ordered_quantity=100)

        processor.process_fill(
            fill_id="FILL001",
            quantity=100,
            price=Decimal("100.00"),
            timestamp=now,
            exchange_order_id="EXCH123",
        )

        # Try to overfill
        with pytest.raises(InvalidFillError, match="exceed"):
            processor.process_fill(
                fill_id="FILL002",
                quantity=10,  # Would exceed 100
                price=Decimal("100.00"),
                timestamp=now,
                exchange_order_id="EXCH123",
            )

    def test_zero_quantity_rejected(self, now):
        """Test that zero quantity fill is rejected."""
        processor = FillProcessor(order_id="ORD001", ordered_quantity=100)

        with pytest.raises(InvalidFillError, match="quantity"):
            processor.process_fill(
                fill_id="FILL001",
                quantity=0,
                price=Decimal("100.00"),
                timestamp=now,
                exchange_order_id="EXCH123",
            )

    def test_negative_quantity_rejected(self, now):
        """Test that negative quantity fill is rejected."""
        processor = FillProcessor(order_id="ORD001", ordered_quantity=100)

        with pytest.raises(InvalidFillError, match="quantity"):
            processor.process_fill(
                fill_id="FILL001",
                quantity=-10,
                price=Decimal("100.00"),
                timestamp=now,
                exchange_order_id="EXCH123",
            )

    def test_get_fills(self, now):
        """Test retrieving all fills."""
        processor = FillProcessor(order_id="ORD001", ordered_quantity=100)

        processor.process_fill(
            fill_id="FILL001",
            quantity=50,
            price=Decimal("100.00"),
            timestamp=now,
            exchange_order_id="EXCH123",
        )

        processor.process_fill(
            fill_id="FILL002",
            quantity=50,
            price=Decimal("101.00"),
            timestamp=now,
            exchange_order_id="EXCH123",
        )

        fills = processor.get_fills()

        assert len(fills) == 2
        assert fills[0].fill_id == "FILL001"
        assert fills[1].fill_id == "FILL002"

    def test_remaining_quantity(self, now):
        """Test remaining quantity calculation."""
        processor = FillProcessor(order_id="ORD001", ordered_quantity=100)

        processor.process_fill(
            fill_id="FILL001",
            quantity=30,
            price=Decimal("100.00"),
            timestamp=now,
            exchange_order_id="EXCH123",
        )

        assert processor.remaining_quantity == 70  # 100 - 30

    def test_is_filled(self, now):
        """Test order completion detection."""
        processor = FillProcessor(order_id="ORD001", ordered_quantity=100)

        assert processor.is_filled is False

        processor.process_fill(
            fill_id="FILL001",
            quantity=100,
            price=Decimal("100.00"),
            timestamp=now,
            exchange_order_id="EXCH123",
        )

        assert processor.is_filled is True

    def test_get_stats(self, now):
        """Test getting fill statistics."""
        processor = FillProcessor(order_id="ORD001", ordered_quantity=100)

        processor.process_fill(
            fill_id="FILL001",
            quantity=50,
            price=Decimal("100.00"),
            timestamp=now,
            commission=Decimal("2.50"),
            exchange_order_id="EXCH123",
        )

        stats = processor.get_stats()

        assert stats.order_id == "ORD001"
        assert stats.total_filled == 50
        assert stats.avg_fill_price == Decimal("100.00")
        assert stats.total_commission == Decimal("2.50")
        assert stats.fill_count == 1

    def test_reset_processor(self, now):
        """Test resetting fill processor."""
        processor = FillProcessor(order_id="ORD001", ordered_quantity=100)

        processor.process_fill(
            fill_id="FILL001",
            quantity=100,
            price=Decimal("100.00"),
            timestamp=now,
            exchange_order_id="EXCH123",
        )

        processor.reset()

        assert processor.total_filled == 0
        assert processor.remaining_quantity == 100
        assert processor.is_filled is False
        assert len(processor.get_fills()) == 0

    def test_fill_with_commission(self, now):
        """Test fill with commission."""
        processor = FillProcessor(order_id="ORD001", ordered_quantity=100)

        processor.process_fill(
            fill_id="FILL001",
            quantity=100,
            price=Decimal("100.00"),
            timestamp=now,
            commission=Decimal("5.00"),
            exchange_order_id="EXCH123",
        )

        stats = processor.get_stats()
        assert stats.total_commission == Decimal("5.00")

    def test_fill_sequence_tracking(self, now):
        """Test fill sequence number tracking."""
        processor = FillProcessor(order_id="ORD001", ordered_quantity=100)

        fill1 = processor.process_fill(
            fill_id="FILL001",
            quantity=50,
            price=Decimal("100.00"),
            timestamp=now,
            exchange_order_id="EXCH123",
        )

        fill2 = processor.process_fill(
            fill_id="FILL002",
            quantity=50,
            price=Decimal("101.00"),
            timestamp=now,
            exchange_order_id="EXCH123",
        )

        assert fill1.sequence == 1
        assert fill2.sequence == 2

    def test_avg_price_calculation(self, now):
        """Test weighted average price calculation."""
        processor = FillProcessor(order_id="ORD001", ordered_quantity=100)

        # Fill 1: 30 shares @ 100
        processor.process_fill(
            fill_id="FILL001",
            quantity=30,
            price=Decimal("100.00"),
            timestamp=now,
            exchange_order_id="EXCH123",
        )

        # Fill 2: 70 shares @ 110
        processor.process_fill(
            fill_id="FILL002",
            quantity=70,
            price=Decimal("110.00"),
            timestamp=now,
            exchange_order_id="EXCH123",
        )

        stats = processor.get_stats()
        # Weighted avg: (30*100 + 70*110) / 100 = (3000 + 7700) / 100 = 107
        assert stats.avg_fill_price == Decimal("107.00")

    def test_duplicate_fill_id_rejected(self, now):
        """Test that duplicate fill IDs are rejected."""
        processor = FillProcessor(order_id="ORD001", ordered_quantity=100)

        processor.process_fill(
            fill_id="FILL001",
            quantity=50,
            price=Decimal("100.00"),
            timestamp=now,
            exchange_order_id="EXCH123",
        )

        # Try to use same fill_id
        with pytest.raises(InvalidFillError, match="Duplicate"):
            processor.process_fill(
                fill_id="FILL001",  # Same ID
                quantity=50,
                price=Decimal("100.00"),
                timestamp=now,
                exchange_order_id="EXCH123",
            )
