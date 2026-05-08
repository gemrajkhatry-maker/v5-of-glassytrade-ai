"""
Tests for Order Book Analytics - Liquidity Metrics.

Tests cover:
- Bid/ask volume aggregation
- Liquidity concentration
- Volume-at-price analysis
- Depth-of-book metrics
- Liquidity imbalance
"""

import pytest

from brokersv2.analytics.order_book.engine import OrderBookEngine, Side
from brokersv2.analytics.order_book.liquidity import LiquidityMetricsEngine


class TestLiquidityMetricsInitialization:
    """Test engine initialization."""

    def test_create_engine(self):
        """Create liquidity metrics engine."""
        engine = OrderBookEngine(symbol="RELIANCE")
        metrics = LiquidityMetricsEngine(engine)

        assert metrics.order_book == engine

    def test_empty_book_metrics(self):
        """Metrics on empty book return zeros."""
        engine = OrderBookEngine(symbol="TCS")
        metrics = LiquidityMetricsEngine(engine)

        assert metrics.get_total_bid_volume() == 0
        assert metrics.get_total_ask_volume() == 0


class TestBidAskVolume:
    """Test bid/ask volume calculations."""

    def test_total_bid_volume(self):
        """Calculate total bid volume."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="2", price=2490.0, quantity=200, side=Side.BID)

        metrics = LiquidityMetricsEngine(engine)

        assert metrics.get_total_bid_volume() == 300

    def test_total_ask_volume(self):
        """Calculate total ask volume."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2510.0, quantity=150, side=Side.ASK)
        engine.add_order(order_id="2", price=2520.0, quantity=250, side=Side.ASK)

        metrics = LiquidityMetricsEngine(engine)

        assert metrics.get_total_ask_volume() == 400

    def test_total_volume(self):
        """Calculate total book volume."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=150, side=Side.ASK)

        metrics = LiquidityMetricsEngine(engine)

        assert metrics.get_total_volume() == 250


class TestLiquidityConcentration:
    """Test liquidity concentration metrics."""

    def test_top_level_concentration(self):
        """Calculate concentration at top price level."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=500, side=Side.BID)
        engine.add_order(order_id="2", price=2490.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="3", price=2480.0, quantity=100, side=Side.BID)

        metrics = LiquidityMetricsEngine(engine)
        concentration = metrics.get_bid_concentration(top_n=1)

        # Top level: 500 / 700 = 71.4%
        assert concentration == pytest.approx(0.714, rel=0.01)

    def test_multi_level_concentration(self):
        """Calculate concentration across multiple levels."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=300, side=Side.BID)
        engine.add_order(order_id="2", price=2490.0, quantity=300, side=Side.BID)
        engine.add_order(order_id="3", price=2480.0, quantity=400, side=Side.BID)

        metrics = LiquidityMetricsEngine(engine)
        concentration = metrics.get_bid_concentration(top_n=2)

        # Top 2 levels: 600 / 1000 = 60%
        assert concentration == pytest.approx(0.60, rel=0.01)


class TestVolumeAtPrice:
    """Test volume-at-price analysis."""

    def test_get_volume_at_price(self):
        """Get volume at specific price level."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="2", price=2500.0, quantity=150, side=Side.BID)

        metrics = LiquidityMetricsEngine(engine)

        assert metrics.get_volume_at_price(2500.0, side=Side.BID) == 250

    def test_get_volume_at_nonexistent_price(self):
        """Volume is zero at prices without orders."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)

        metrics = LiquidityMetricsEngine(engine)

        assert metrics.get_volume_at_price(2510.0, side=Side.BID) == 0


class TestDepthMetrics:
    """Test depth-of-book metrics."""

    def test_bid_levels_count(self):
        """Count number of bid price levels."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="2", price=2490.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="3", price=2480.0, quantity=100, side=Side.BID)

        metrics = LiquidityMetricsEngine(engine)

        assert metrics.get_bid_levels() == 3

    def test_ask_levels_count(self):
        """Count number of ask price levels."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2510.0, quantity=100, side=Side.ASK)
        engine.add_order(order_id="2", price=2520.0, quantity=100, side=Side.ASK)

        metrics = LiquidityMetricsEngine(engine)

        assert metrics.get_ask_levels() == 2

    def test_weighted_average_price(self):
        """Calculate volume-weighted average price."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="2", price=2400.0, quantity=200, side=Side.BID)

        metrics = LiquidityMetricsEngine(engine)
        vwap = metrics.get_weighted_average_price(side=Side.BID)

        # (2500*100 + 2400*200) / 300 = 2433.33
        assert vwap == pytest.approx(2433.33, rel=0.01)


class TestLiquidityImbalance:
    """Test liquidity imbalance calculations."""

    def test_balanced_book(self):
        """Balanced book has zero imbalance."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=500, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=500, side=Side.ASK)

        metrics = LiquidityMetricsEngine(engine)
        imbalance = metrics.get_liquidity_imbalance()

        assert imbalance == 0.0

    def test_bid_heavy_book(self):
        """Bid-heavy book has positive imbalance."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=800, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=200, side=Side.ASK)

        metrics = LiquidityMetricsEngine(engine)
        imbalance = metrics.get_liquidity_imbalance()

        # (800 - 200) / 1000 = 0.6
        assert imbalance == pytest.approx(0.6)

    def test_ask_heavy_book(self):
        """Ask-heavy book has negative imbalance."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=200, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=800, side=Side.ASK)

        metrics = LiquidityMetricsEngine(engine)
        imbalance = metrics.get_liquidity_imbalance()

        # (200 - 800) / 1000 = -0.6
        assert imbalance == pytest.approx(-0.6)

    def test_empty_book_imbalance(self):
        """Empty book has zero imbalance."""
        engine = OrderBookEngine(symbol="RELIANCE")
        metrics = LiquidityMetricsEngine(engine)

        assert metrics.get_liquidity_imbalance() == 0.0


class TestLiquiditySnapshots:
    """Test liquidity snapshot generation."""

    def test_snapshot_contains_all_metrics(self):
        """Snapshot includes all liquidity metrics."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=150, side=Side.ASK)

        metrics = LiquidityMetricsEngine(engine)
        snapshot = metrics.get_snapshot()

        assert snapshot.bid_volume == 100
        assert snapshot.ask_volume == 150
        assert snapshot.bid_levels == 1
        assert snapshot.ask_levels == 1

    def test_snapshot_timestamp(self):
        """Snapshot includes timestamp."""
        engine = OrderBookEngine(symbol="RELIANCE")
        metrics = LiquidityMetricsEngine(engine)
        snapshot = metrics.get_snapshot()

        assert snapshot.timestamp is not None


class TestLiquidityEdgeCases:
    """Test edge cases."""

    def test_single_sided_book(self):
        """Metrics work with only bids or asks."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)

        metrics = LiquidityMetricsEngine(engine)

        assert metrics.get_total_bid_volume() == 100
        assert metrics.get_total_ask_volume() == 0
        assert metrics.get_liquidity_imbalance() == 1.0  # All bids

    def test_concentration_single_level(self):
        """Single level has 100% concentration."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)

        metrics = LiquidityMetricsEngine(engine)
        concentration = metrics.get_bid_concentration(top_n=1)

        assert concentration == 1.0

    def test_clear_book_resets_metrics(self):
        """Clear book resets all metrics to zero."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)

        metrics = LiquidityMetricsEngine(engine)
        engine.clear()

        assert metrics.get_total_bid_volume() == 0
        assert metrics.get_total_ask_volume() == 0
        assert metrics.get_liquidity_imbalance() == 0.0
