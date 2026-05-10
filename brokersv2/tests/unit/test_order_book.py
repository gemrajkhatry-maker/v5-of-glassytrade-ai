"""Tests for Order Book Engine - TDD Red-Green-Refactor."""

import pytest
from datetime import datetime, timezone
from brokersv2.analytics.order_book.engine import OrderBookEngine
from brokersv2.analytics.order_book.events import (
    PriceLevel,
    OrderBookSnapshot,
    OrderBookEvent,
    OrderBookEventType,
)


class TestOrderBookCore:
    """Test core order book functionality."""

    def test_order_book_starts_empty(self):
        """Test new order book has no levels."""
        engine = OrderBookEngine("NSE:RELIANCE")
        assert engine.bid_levels == 0
        assert engine.ask_levels == 0

    def test_order_book_symbol(self):
        """Test order book tracks symbol."""
        engine = OrderBookEngine("NSE:RELIANCE")
        assert engine.symbol == "NSE:RELIANCE"

    def test_update_bid_level(self):
        """Test adding bid level to order book."""
        engine = OrderBookEngine("NSE:RELIANCE")
        level = PriceLevel(price=2500.0, quantity=100, order_count=5)
        
        engine.update_bid(level)
        
        assert engine.bid_levels == 1
        assert engine.best_bid.price == 2500.0
        assert engine.best_bid.quantity == 100

    def test_update_ask_level(self):
        """Test adding ask level to order book."""
        engine = OrderBookEngine("NSE:RELIANCE")
        level = PriceLevel(price=2505.0, quantity=150, order_count=8)
        
        engine.update_ask(level)
        
        assert engine.ask_levels == 1
        assert engine.best_ask.price == 2505.0
        assert engine.best_ask.quantity == 150

    def test_multiple_bid_levels_sorted(self):
        """Test bid levels are sorted descending by price."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        engine.update_bid(PriceLevel(price=2502.0, quantity=150))
        engine.update_bid(PriceLevel(price=2498.0, quantity=200))
        
        assert engine.bid_levels == 3
        # Bids should be sorted: highest price first (use ladder API)
        ladder = engine.get_bid_ladder(depth=3)
        assert ladder[0].price == 2502.0
        assert ladder[1].price == 2500.0
        assert ladder[2].price == 2498.0

    def test_multiple_ask_levels_sorted(self):
        """Test ask levels are sorted ascending by price."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_ask(PriceLevel(price=2505.0, quantity=100))
        engine.update_ask(PriceLevel(price=2503.0, quantity=150))
        engine.update_ask(PriceLevel(price=2507.0, quantity=200))
        
        assert engine.ask_levels == 3
        # Asks should be sorted: lowest price first (use ladder API)
        ladder = engine.get_ask_ladder(depth=3)
        assert ladder[0].price == 2503.0
        assert ladder[1].price == 2505.0
        assert ladder[2].price == 2507.0

    def test_update_existing_level(self):
        """Test updating existing price level replaces quantity."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        engine.update_bid(PriceLevel(price=2500.0, quantity=250))
        
        assert engine.bid_levels == 1
        assert engine.best_bid.quantity == 250

    def test_remove_level_with_zero_quantity(self):
        """Test setting quantity to zero removes level."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        engine.update_bid(PriceLevel(price=2500.0, quantity=0))
        
        assert engine.bid_levels == 0

    def test_spread_calculation(self):
        """Test bid-ask spread calculation."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        engine.update_ask(PriceLevel(price=2505.0, quantity=150))
        
        assert engine.spread == 5.0

    def test_mid_price_calculation(self):
        """Test mid price calculation."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        engine.update_ask(PriceLevel(price=2510.0, quantity=150))
        
        assert engine.mid_price == 2505.0


class TestOrderBookSnapshot:
    """Test order book snapshot functionality."""

    def test_take_snapshot(self):
        """Test taking order book snapshot."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        engine.update_bid(PriceLevel(price=2498.0, quantity=200))
        engine.update_ask(PriceLevel(price=2505.0, quantity=150))
        engine.update_ask(PriceLevel(price=2507.0, quantity=250))
        
        snapshot = engine.take_snapshot()
        
        assert isinstance(snapshot, OrderBookSnapshot)
        assert snapshot.symbol == "NSE:RELIANCE"
        assert snapshot.bid_levels == 2
        assert snapshot.ask_levels == 2
        assert snapshot.best_bid.price == 2500.0
        assert snapshot.best_ask.price == 2505.0

    def test_snapshot_is_immutable(self):
        """Test snapshot is frozen dataclass."""
        engine = OrderBookEngine("NSE:RELIANCE")
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        engine.update_ask(PriceLevel(price=2505.0, quantity=150))
        
        snapshot = engine.take_snapshot()
        
        # Should raise error when trying to modify
        with pytest.raises((AttributeError, TypeError)):
            snapshot.symbol = "NSE:TCS"


class TestOrderBookEvents:
    """Test order book event generation."""

    def test_update_generates_event(self):
        """Test that updates generate events."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        
        assert len(engine.events) == 1
        event = engine.events[0]
        assert isinstance(event, OrderBookEvent)
        assert event.event_type == OrderBookEventType.BID_UPDATE
        assert event.symbol == "NSE:RELIANCE"

    def test_sequence_numbering(self):
        """Test events have sequential numbering."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        engine.update_ask(PriceLevel(price=2505.0, quantity=150))
        engine.update_bid(PriceLevel(price=2502.0, quantity=200))
        
        assert engine.events[0].sequence == 1
        assert engine.events[1].sequence == 2
        assert engine.events[2].sequence == 3

    def test_event_has_timestamp(self):
        """Test events have UTC timestamps."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        
        event = engine.events[0]
        assert event.timestamp is not None
        assert event.timestamp.tzinfo == timezone.utc


class TestPriceLadder:
    """Test price ladder functionality."""

    def test_get_ladder_depth(self):
        """Test getting ladder at specific depth."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        # Add 5 bid levels
        for i in range(5):
            engine.update_bid(PriceLevel(price=2500.0 - i, quantity=100))
        
        ladder = engine.get_bid_ladder(depth=3)
        assert len(ladder) == 3
        assert ladder[0].price == 2500.0
        assert ladder[1].price == 2499.0
        assert ladder[2].price == 2498.0

    def test_get_ladder_less_than_available(self):
        """Test requesting more depth than available returns all."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        engine.update_bid(PriceLevel(price=2499.0, quantity=150))
        
        ladder = engine.get_bid_ladder(depth=10)
        assert len(ladder) == 2

    def test_get_ask_ladder(self):
        """Test getting ask ladder."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        for i in range(5):
            engine.update_ask(PriceLevel(price=2505.0 + i, quantity=100))
        
        ladder = engine.get_ask_ladder(depth=3)
        assert len(ladder) == 3
        assert ladder[0].price == 2505.0

    def test_ladder_cumulative_quantity(self):
        """Test cumulative quantity calculation."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        engine.update_bid(PriceLevel(price=2499.0, quantity=200))
        engine.update_bid(PriceLevel(price=2498.0, quantity=300))
        
        cumulative = engine.get_cumulative_bid_quantity(depth=3)
        assert cumulative == 600  # 100 + 200 + 300

    def test_ladder_cumulative_notional(self):
        """Test cumulative notional calculation."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        engine.update_bid(PriceLevel(price=2499.0, quantity=200))
        
        notional = engine.get_cumulative_bid_notional(depth=2)
        expected = (2500.0 * 100) + (2499.0 * 200)
        assert notional == expected


class TestLiquidityMetrics:
    """Test liquidity metrics calculations."""

    def test_total_bid_quantity(self):
        """Test total bid quantity across all levels."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        engine.update_bid(PriceLevel(price=2499.0, quantity=200))
        
        assert engine.total_bid_quantity == 300

    def test_total_ask_quantity(self):
        """Test total ask quantity across all levels."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_ask(PriceLevel(price=2505.0, quantity=150))
        engine.update_ask(PriceLevel(price=2506.0, quantity=250))
        
        assert engine.total_ask_quantity == 400

    def test_total_bid_notional(self):
        """Test total bid notional value."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        engine.update_bid(PriceLevel(price=2499.0, quantity=200))
        
        expected = (2500.0 * 100) + (2499.0 * 200)
        assert engine.total_bid_notional == expected

    def test_spread_percentage(self):
        """Test spread as percentage of mid price."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        engine.update_ask(PriceLevel(price=2510.0, quantity=150))
        
        # Spread = 10, Mid = 2505, Spread% = 10/2505 * 100
        expected = (10.0 / 2505.0) * 100
        assert abs(engine.spread_percentage - expected) < 0.01

    def test_no_spread_when_empty(self):
        """Test spread is None when book is empty."""
        engine = OrderBookEngine("NSE:RELIANCE")
        assert engine.spread is None
        assert engine.spread_percentage is None


class TestImbalanceCalculations:
    """Test order book imbalance calculations."""

    def test_bid_imbalance(self):
        """Test bid-side imbalance calculation."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2500.0, quantity=300))
        engine.update_ask(PriceLevel(price=2505.0, quantity=100))
        
        # Imbalance = (bid_qty - ask_qty) / (bid_qty + ask_qty)
        # = (300 - 100) / (300 + 100) = 200/400 = 0.5
        assert abs(engine.quantity_imbalance - 0.5) < 0.01

    def test_ask_imbalance(self):
        """Test ask-side imbalance calculation."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        engine.update_ask(PriceLevel(price=2505.0, quantity=300))
        
        # Imbalance = (100 - 300) / (100 + 300) = -200/400 = -0.5
        assert abs(engine.quantity_imbalance - (-0.5)) < 0.01

    def test_balanced_book(self):
        """Test balanced book has zero imbalance."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2500.0, quantity=200))
        engine.update_ask(PriceLevel(price=2505.0, quantity=200))
        
        assert abs(engine.quantity_imbalance) < 0.01

    def test_imbalance_empty_book(self):
        """Test empty book has zero imbalance."""
        engine = OrderBookEngine("NSE:RELIANCE")
        assert engine.quantity_imbalance == 0.0

    def test_notional_imbalance(self):
        """Test notional-weighted imbalance."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        engine.update_ask(PriceLevel(price=2505.0, quantity=100))
        
        # Bid notional = 250000, Ask notional = 250500
        # Imbalance = (250000 - 250500) / (250000 + 250500) = -500/500500 ≈ -0.001
        expected = (250000.0 - 250500.0) / (250000.0 + 250500.0)
        assert abs(engine.notional_imbalance - expected) < 0.01


class TestSweepDetection:
    """Test sweep detection primitives."""

    def test_detect_sweep_event(self):
        """Test detecting large order sweep."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        # Setup order book
        engine.update_ask(PriceLevel(price=2505.0, quantity=100))
        engine.update_ask(PriceLevel(price=2506.0, quantity=150))
        
        # Large trade that sweeps multiple levels
        is_sweep = engine.check_sweep(quantity=200, side="BUY")
        assert is_sweep is True

    def test_no_sweep_small_order(self):
        """Test small order doesn't trigger sweep."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_ask(PriceLevel(price=2505.0, quantity=100))
        
        is_sweep = engine.check_sweep(quantity=50, side="BUY")
        assert is_sweep is False

    def test_sweep_multiple_levels(self):
        """Test sweep that crosses multiple levels."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_ask(PriceLevel(price=2505.0, quantity=50))
        engine.update_ask(PriceLevel(price=2506.0, quantity=50))
        engine.update_ask(PriceLevel(price=2507.0, quantity=50))
        
        # Order that sweeps all 3 levels
        is_sweep = engine.check_sweep(quantity=150, side="BUY")
        assert is_sweep is True

    def test_sweep_levels_crossed(self):
        """Test getting number of levels a sweep would cross."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_ask(PriceLevel(price=2505.0, quantity=100))
        engine.update_ask(PriceLevel(price=2506.0, quantity=100))
        engine.update_ask(PriceLevel(price=2507.0, quantity=100))
        
        levels_crossed = engine.get_sweep_levels_crossed(quantity=250, side="BUY")
        assert levels_crossed == 3

    def test_bid_side_sweep(self):
        """Test sweep detection on bid side."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        engine.update_bid(PriceLevel(price=2499.0, quantity=100))
        
        is_sweep = engine.check_sweep(quantity=150, side="SELL")
        assert is_sweep is True


class TestOrderBookEdgeCases:
    """Test edge cases and error handling."""

    def test_update_negative_price_accepted(self):
        """Test negative prices are accepted (validation done elsewhere)."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        # Engine accepts negative prices (validation is upstream)
        engine.update_bid(PriceLevel(price=-100.0, quantity=100))
        assert engine.bid_levels == 1

    def test_update_negative_quantity_accepted(self):
        """Test negative quantities are stored as-is."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        # Engine accepts negative quantities (stores as-is)
        engine.update_bid(PriceLevel(price=2500.0, quantity=-100))
        # Level is stored with negative quantity
        assert engine.bid_levels == 1
        assert engine.best_bid.quantity == -100

    def test_crossed_market_detected(self):
        """Test when bid > ask (crossed market)."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2510.0, quantity=100))
        engine.update_ask(PriceLevel(price=2505.0, quantity=150))
        
        # Spread should be negative (crossed)
        assert engine.spread == -5.0

    def test_clear_order_book(self):
        """Test clearing entire order book."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        engine.update_ask(PriceLevel(price=2505.0, quantity=150))
        
        engine.clear()
        
        assert engine.bid_levels == 0
        assert engine.ask_levels == 0
        assert len(engine.events) == 0

    def test_event_history_limit(self):
        """Test event history can be limited."""
        engine = OrderBookEngine("NSE:RELIANCE", max_events=5)
        
        for i in range(10):
            engine.update_bid(PriceLevel(price=2500.0 + i, quantity=100))
        
        # Should only keep last 5 events
        assert len(engine.events) == 5

    def test_sequence_number_wraps(self):
        """Test sequence number handling for large values."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        # Simulate many updates
        for i in range(1000):
            engine.update_bid(PriceLevel(price=2500.0 + i, quantity=100))
        
        # Sequence should keep incrementing
        assert engine.events[-1].sequence == 1000


class TestOrderBookDepthMetrics:
    """Test advanced depth metrics."""

    def test_book_depth_asymmetry(self):
        """Test book with different bid/ask depths."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        for i in range(10):
            engine.update_bid(PriceLevel(price=2500.0 - i, quantity=100))
        
        for i in range(5):
            engine.update_ask(PriceLevel(price=2505.0 + i, quantity=100))
        
        assert engine.bid_levels == 10
        assert engine.ask_levels == 5

    def test_top_of_book_pressure(self):
        """Test pressure at top of book."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        # Strong bid support at top
        engine.update_bid(PriceLevel(price=2500.0, quantity=1000))
        engine.update_bid(PriceLevel(price=2499.0, quantity=50))
        
        # Weak ask liquidity
        engine.update_ask(PriceLevel(price=2505.0, quantity=100))
        engine.update_ask(PriceLevel(price=2506.0, quantity=150))
        
        # Top-of-book ratio (best_bid_qty / best_ask_qty)
        ratio = engine.top_of_book_ratio()
        assert ratio == 10.0  # 1000 / 100

    def test_weighted_mid_price(self):
        """Test volume-weighted mid price."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2500.0, quantity=300))
        engine.update_ask(PriceLevel(price=2510.0, quantity=100))
        
        # More weight on bid side (3:1 ratio)
        # Weighted mid should be closer to bid
        weighted_mid = engine.weighted_mid_price()
        assert 2500.0 < weighted_mid < 2505.0  # Closer to bid than regular mid

    def test_volume_weighted_average_price(self):
        """Test VWAP calculation for book."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        engine.update_bid(PriceLevel(price=2490.0, quantity=200))
        
        vwap = engine.bid_vwap()
        expected = (2500.0 * 100 + 2490.0 * 200) / 300
        assert abs(vwap - expected) < 0.01

    def test_price_impact_estimate(self):
        """Test estimating price impact of market order."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        engine.update_ask(PriceLevel(price=2505.0, quantity=100))
        engine.update_ask(PriceLevel(price=2506.0, quantity=100))
        engine.update_ask(PriceLevel(price=2507.0, quantity=100))
        
        # Market buy of 250 shares
        impact = engine.estimate_market_impact(quantity=250, side="BUY")
        
        # Should execute at multiple levels
        # 100 @ 2505, 100 @ 2506, 50 @ 2507
        expected_avg = (100*2505 + 100*2506 + 50*2507) / 250
        assert abs(impact - expected_avg) < 0.01


class TestOrderBookEventGeneration:
    """Test event generation patterns."""

    def test_snapshot_event_type(self):
        """Test snapshot events have correct type."""
        engine = OrderBookEngine("NSE:RELIANCE")
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        
        snapshot = engine.take_snapshot()
        
        # Last event should be snapshot
        assert engine.events[-1].event_type == OrderBookEventType.SNAPSHOT
        assert engine.events[-1].snapshot is not None

    def test_clear_removes_all_events(self):
        """Test clearing book removes all events."""
        engine = OrderBookEngine("NSE:RELIANCE")
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        
        event_count_before = len(engine.events)
        engine.clear()
        
        # Clear removes all events
        assert len(engine.events) == 0
        assert event_count_before > 0

    def test_events_are_immutable(self):
        """Test events cannot be modified."""
        engine = OrderBookEngine("NSE:RELIANCE")
        engine.update_bid(PriceLevel(price=2500.0, quantity=100))
        
        event = engine.events[0]
        
        with pytest.raises((AttributeError, TypeError)):
            event.symbol = "NSE:TCS"

    def test_sequence_numbers_monotonic(self):
        """Test sequence numbers always increase."""
        engine = OrderBookEngine("NSE:RELIANCE")
        
        for i in range(20):
            if i % 2 == 0:
                engine.update_bid(PriceLevel(price=2500.0 + i, quantity=100))
            else:
                engine.update_ask(PriceLevel(price=2510.0 + i, quantity=100))
        
        sequences = [e.sequence for e in engine.events]
        assert sequences == sorted(sequences)

    def test_event_symbol_matches_book(self):
        """Test all events have correct symbol."""
        engine = OrderBookEngine("NSE:TCS")
        
        engine.update_bid(PriceLevel(price=3500.0, quantity=100))
        engine.update_ask(PriceLevel(price=3505.0, quantity=150))
        engine.take_snapshot()
        
        for event in engine.events:
            assert event.symbol == "NSE:TCS"
