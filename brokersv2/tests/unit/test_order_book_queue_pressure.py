"""
Tests for Order Book Analytics - Queue Pressure.

Tests cover:
- Queue position tracking
- Queue depletion rate
- Queue replenishment patterns
- Pressure indicator (0-100 scale)
"""

import pytest

from brokersv2.analytics.order_book.engine import OrderBookEngine, Side
from brokersv2.analytics.order_book.queue_pressure import QueuePressureAnalyzer


class TestQueuePressureInit:
    """Test initialization."""

    def test_create_analyzer(self):
        """Create queue pressure analyzer."""
        engine = OrderBookEngine(symbol="RELIANCE")
        analyzer = QueuePressureAnalyzer(engine)

        assert analyzer.order_book == engine

    def test_initial_pressure_zero(self):
        """Initial pressure is zero for empty book."""
        engine = OrderBookEngine(symbol="TCS")
        analyzer = QueuePressureAnalyzer(engine)

        assert analyzer.get_pressure_score() == 0


class TestQueuePositionTracking:
    """Test queue position analysis."""

    def test_bid_queue_depth(self):
        """Calculate total queue depth for bids."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="2", price=2490.0, quantity=200, side=Side.BID)

        analyzer = QueuePressureAnalyzer(engine)

        assert analyzer.get_bid_queue_depth() == 300

    def test_ask_queue_depth(self):
        """Calculate total queue depth for asks."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2510.0, quantity=150, side=Side.ASK)
        engine.add_order(order_id="2", price=2520.0, quantity=250, side=Side.ASK)

        analyzer = QueuePressureAnalyzer(engine)

        assert analyzer.get_ask_queue_depth() == 400

    def test_queue_depth_at_price(self):
        """Get queue depth at specific price."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="2", price=2500.0, quantity=150, side=Side.BID)

        analyzer = QueuePressureAnalyzer(engine)

        assert analyzer.get_queue_depth_at_price(2500.0, Side.BID) == 250


class TestQueueDepletion:
    """Test queue depletion rate analysis."""

    def test_depletion_rate_calculation(self):
        """Calculate queue depletion rate."""
        engine = OrderBookEngine(symbol="RELIANCE")
        analyzer = QueuePressureAnalyzer(engine)

        # Simulate queue changes
        analyzer._record_queue_depth(1000)
        analyzer._record_queue_depth(800)
        analyzer._record_queue_depth(600)

        rate = analyzer.get_depletion_rate()

        # Should be negative (decreasing)
        assert rate < 0

    def test_depletion_rate_empty(self):
        """Depletion rate is zero with no history."""
        engine = OrderBookEngine(symbol="RELIANCE")
        analyzer = QueuePressureAnalyzer(engine)

        assert analyzer.get_depletion_rate() == 0


class TestQueueReplenishment:
    """Test queue replenishment detection."""

    def test_detect_replenishment(self):
        """Detect when queue is being replenished."""
        engine = OrderBookEngine(symbol="RELIANCE")
        analyzer = QueuePressureAnalyzer(engine)

        # Queue increasing
        analyzer._record_queue_depth(500)
        analyzer._record_queue_depth(600)
        analyzer._record_queue_depth(700)

        is_replenishing = analyzer.is_queue_replenishing()

        assert is_replenishing is True

    def test_detect_depletion(self):
        """Detect when queue is depleting."""
        engine = OrderBookEngine(symbol="RELIANCE")
        analyzer = QueuePressureAnalyzer(engine)

        # Queue decreasing
        analyzer._record_queue_depth(700)
        analyzer._record_queue_depth(600)
        analyzer._record_queue_depth(500)

        is_replenishing = analyzer.is_queue_replenishing()

        assert is_replenishing is False


class TestPressureScore:
    """Test pressure score calculation (0-100 scale)."""

    def test_high_bid_pressure(self):
        """High pressure when bid queue dominates."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=900, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=100, side=Side.ASK)

        analyzer = QueuePressureAnalyzer(engine)
        pressure = analyzer.get_pressure_score()

        # High bid pressure should be > 70
        assert pressure > 70

    def test_high_ask_pressure(self):
        """High ask pressure when ask queue dominates."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=900, side=Side.ASK)

        analyzer = QueuePressureAnalyzer(engine)
        pressure = analyzer.get_pressure_score()

        # High ask pressure should be < 30
        assert pressure < 30

    def test_balanced_pressure(self):
        """Balanced queues give mid-range pressure."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=500, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=500, side=Side.ASK)

        analyzer = QueuePressureAnalyzer(engine)
        pressure = analyzer.get_pressure_score()

        # Balanced should be around 50
        assert 40 <= pressure <= 60

    def test_empty_book_pressure(self):
        """Empty book has zero pressure."""
        engine = OrderBookEngine(symbol="RELIANCE")
        analyzer = QueuePressureAnalyzer(engine)

        assert analyzer.get_pressure_score() == 0


class TestPressureTrend:
    """Test pressure trend analysis."""

    def test_increasing_pressure(self):
        """Detect increasing pressure trend."""
        engine = OrderBookEngine(symbol="RELIANCE")
        analyzer = QueuePressureAnalyzer(engine)

        # Record increasing bid pressure
        engine.add_order(order_id="1", price=2500.0, quantity=300, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=700, side=Side.ASK)
        analyzer.record_snapshot()

        engine.clear()
        engine.add_order(order_id="3", price=2500.0, quantity=500, side=Side.BID)
        engine.add_order(order_id="4", price=2510.0, quantity=500, side=Side.ASK)
        analyzer.record_snapshot()

        trend = analyzer.get_pressure_trend()

        assert trend == "increasing"

    def test_decreasing_pressure(self):
        """Detect decreasing pressure trend."""
        engine = OrderBookEngine(symbol="RELIANCE")
        analyzer = QueuePressureAnalyzer(engine)

        # Record decreasing bid pressure
        engine.add_order(order_id="1", price=2500.0, quantity=700, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=300, side=Side.ASK)
        analyzer.record_snapshot()

        engine.clear()
        engine.add_order(order_id="3", price=2500.0, quantity=300, side=Side.BID)
        engine.add_order(order_id="4", price=2510.0, quantity=700, side=Side.ASK)
        analyzer.record_snapshot()

        trend = analyzer.get_pressure_trend()

        assert trend == "decreasing"

    def test_stable_pressure(self):
        """Detect stable pressure."""
        engine = OrderBookEngine(symbol="RELIANCE")
        analyzer = QueuePressureAnalyzer(engine)

        # Record stable pressure
        engine.add_order(order_id="1", price=2500.0, quantity=500, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=500, side=Side.ASK)
        analyzer.record_snapshot()
        analyzer.record_snapshot()

        trend = analyzer.get_pressure_trend()

        assert trend == "stable"


class TestPressureEdgeCases:
    """Test edge cases."""

    def test_single_sided_book_pressure(self):
        """Single-sided book has extreme pressure."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)

        analyzer = QueuePressureAnalyzer(engine)
        pressure = analyzer.get_pressure_score()

        # All bids = maximum pressure
        assert pressure == 100

    def test_clear_resets_pressure(self):
        """Clear book resets pressure to zero."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)

        analyzer = QueuePressureAnalyzer(engine)
        engine.clear()

        assert analyzer.get_pressure_score() == 0

    def test_snapshot_history_trimmed(self):
        """History is trimmed to max size."""
        engine = OrderBookEngine(symbol="RELIANCE")
        analyzer = QueuePressureAnalyzer(engine, history_size=5)

        for _ in range(10):
            analyzer.record_snapshot()

        assert len(analyzer.history) == 5
