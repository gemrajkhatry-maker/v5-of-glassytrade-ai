"""
Tests for Order Book Engine - Core.

Tests cover:
- Bid/ask price level management
- Order tracking by ID
- Book updates (add, modify, cancel)
- Snapshot generation
- Depth management
- Edge cases
"""

from datetime import datetime, timezone

import pytest

from brokersv2.analytics.order_book.engine import OrderBookEngine, Side, OrderAction


class TestOrderBookEngineInitialization:
    """Test engine initialization."""

    def test_create_engine(self):
        """Create order book engine."""
        engine = OrderBookEngine(symbol="RELIANCE")

        assert engine.symbol == "RELIANCE"
        assert len(engine.bids) == 0
        assert len(engine.asks) == 0

    def test_empty_book_snapshot(self):
        """Snapshot of empty book has no levels."""
        engine = OrderBookEngine(symbol="TCS")
        snapshot = engine.get_snapshot()

        assert snapshot.symbol == "TCS"
        assert len(snapshot.bids) == 0
        assert len(snapshot.asks) == 0


class TestOrderBookAddOrders:
    """Test adding orders to book."""

    def test_add_bid_order(self):
        """Add bid order to book."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)

        assert 2500.0 in engine.bids
        assert engine.bids[2500.0] == (100, 1)

    def test_add_ask_order(self):
        """Add ask order to book."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2510.0, quantity=100, side=Side.ASK)

        assert 2510.0 in engine.asks
        assert engine.asks[2510.0] == (100, 1)

    def test_add_multiple_orders_same_price(self):
        """Multiple orders at same price aggregate quantity."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="2", price=2500.0, quantity=150, side=Side.BID)

        # Should aggregate
        assert engine.bids[2500.0] == (250, 2)

    def test_add_orders_different_prices(self):
        """Orders at different prices create separate levels."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="2", price=2490.0, quantity=200, side=Side.BID)

        assert len(engine.bids) == 2
        assert engine.bids[2500.0] == (100, 1)
        assert engine.bids[2490.0] == (200, 1)


class TestOrderBookModifyOrders:
    """Test modifying existing orders."""

    def test_modify_order_quantity(self):
        """Modify order quantity."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)
        engine.modify_order(order_id="1", quantity=150)

        assert engine.bids[2500.0] == (150, 1)

    def test_modify_order_price(self):
        """Modify order price moves to new level."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)
        engine.modify_order(order_id="1", price=2510.0)

        # Old level removed
        assert 2500.0 not in engine.bids
        # New level created
        assert 2510.0 in engine.bids
        assert engine.bids[2510.0] == (100, 1)

    def test_modify_nonexistent_order(self):
        """Modify nonexistent order is ignored."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.modify_order(order_id="999", quantity=100)  # Should not raise

        assert len(engine.bids) == 0


class TestOrderBookCancelOrders:
    """Test canceling orders."""

    def test_cancel_order(self):
        """Cancel order removes from book."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)
        engine.cancel_order(order_id="1")

        assert len(engine.bids) == 0

    def test_cancel_removes_price_level(self):
        """Cancel last order at price removes level."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="2", price=2500.0, quantity=150, side=Side.BID)
        engine.cancel_order(order_id="1")
        engine.cancel_order(order_id="2")

        assert 2500.0 not in engine.bids

    def test_cancel_partial_keeps_level(self):
        """Cancel one order keeps price level if others remain."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="2", price=2500.0, quantity=150, side=Side.BID)
        engine.cancel_order(order_id="1")

        # Level should still exist with remaining order
        assert 2500.0 in engine.bids
        assert engine.bids[2500.0] == (150, 1)

    def test_cancel_nonexistent_order(self):
        """Cancel nonexistent order is ignored."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.cancel_order(order_id="999")  # Should not raise


class TestOrderBookSnapshot:
    """Test snapshot generation."""

    def test_snapshot_with_orders(self):
        """Snapshot includes all price levels."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="2", price=2490.0, quantity=200, side=Side.BID)
        engine.add_order(order_id="3", price=2510.0, quantity=150, side=Side.ASK)

        snapshot = engine.get_snapshot()

        assert len(snapshot.bids) == 2
        assert len(snapshot.asks) == 1
        assert snapshot.bids[0].price == 2500.0
        assert snapshot.bids[1].price == 2490.0
        assert snapshot.asks[0].price == 2510.0

    def test_snapshot_sorted_by_price(self):
        """Bids sorted descending, asks sorted ascending."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2490.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="2", price=2500.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="3", price=2480.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="4", price=2510.0, quantity=100, side=Side.ASK)
        engine.add_order(order_id="5", price=2520.0, quantity=100, side=Side.ASK)
        engine.add_order(order_id="6", price=2500.0, quantity=100, side=Side.ASK)

        snapshot = engine.get_snapshot()

        # Bids: highest first
        assert snapshot.bids[0].price == 2500.0
        assert snapshot.bids[1].price == 2490.0
        assert snapshot.bids[2].price == 2480.0

        # Asks: lowest first
        assert snapshot.asks[0].price == 2500.0
        assert snapshot.asks[1].price == 2510.0
        assert snapshot.asks[2].price == 2520.0

    def test_snapshot_timestamp(self):
        """Snapshot includes timestamp."""
        engine = OrderBookEngine(symbol="RELIANCE")
        snapshot = engine.get_snapshot()

        assert snapshot.timestamp is not None


class TestOrderBookDepthLimit:
    """Test depth level management."""

    def test_depth_limit_applied(self):
        """Book respects max depth levels."""
        engine = OrderBookEngine(symbol="RELIANCE", max_depth=3)

        # Add 5 price levels
        for i in range(5):
            engine.add_order(
                order_id=str(i),
                price=2500.0 - i * 10,
                quantity=100,
                side=Side.BID
            )

        snapshot = engine.get_snapshot()
        assert len(snapshot.bids) <= 3

    def test_default_depth_limit(self):
        """Default max depth is 20."""
        engine = OrderBookEngine(symbol="RELIANCE")

        assert engine.max_depth == 20


class TestOrderBookTrades:
    """Test trade execution."""

    def test_record_trade(self):
        """Record trade at specific price."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)

        engine.record_trade(price=2500.0, quantity=50)

        assert len(engine.trades) == 1
        assert engine.trades[0].price == 2500.0
        assert engine.trades[0].quantity == 50

    def test_trade_reduces_quantity(self):
        """Trade reduces order quantity."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)

        engine.record_trade(price=2500.0, quantity=50)

        assert engine.bids[2500.0][0] == 50


class TestOrderBookEdgeCases:
    """Test edge cases."""

    def test_clear_book(self):
        """Clear removes all orders."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=100, side=Side.ASK)

        engine.clear()

        assert len(engine.bids) == 0
        assert len(engine.asks) == 0
        assert len(engine.trades) == 0

    def test_order_count_tracking(self):
        """Track total order count."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=100, side=Side.ASK)

        assert engine.order_count == 2

    def test_spread_calculation(self):
        """Calculate bid-ask spread."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=100, side=Side.ASK)

        spread = engine.get_spread()

        assert spread == 10.0

    def test_spread_empty_book(self):
        """Spread is None for empty book."""
        engine = OrderBookEngine(symbol="RELIANCE")

        spread = engine.get_spread()

        assert spread is None

    def test_mid_price(self):
        """Calculate mid price."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=100, side=Side.ASK)

        mid = engine.get_mid_price()

        assert mid == 2505.0

    def test_mid_price_empty_book(self):
        """Mid price is None for empty book."""
        engine = OrderBookEngine(symbol="RELIANCE")

        mid = engine.get_mid_price()

        assert mid is None
