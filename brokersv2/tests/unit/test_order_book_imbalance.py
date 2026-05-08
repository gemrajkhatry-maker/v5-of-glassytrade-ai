"""
Tests for Order Book Analytics - Imbalance Calculator.

Tests cover:
- Order book imbalance calculation
- Price-weighted imbalance
- Volume delta tracking
- Cumulative imbalance
- Divergence detection
"""

import pytest

from brokersv2.analytics.order_book.engine import OrderBookEngine, Side
from brokersv2.analytics.order_book.imbalance import ImbalanceCalculator


class TestImbalanceCalculatorInit:
    """Test initialization."""

    def test_create_calculator(self):
        """Create imbalance calculator."""
        engine = OrderBookEngine(symbol="RELIANCE")
        calc = ImbalanceCalculator(engine)

        assert calc.order_book == engine

    def test_initial_imbalance_zero(self):
        """Initial imbalance is zero."""
        engine = OrderBookEngine(symbol="TCS")
        calc = ImbalanceCalculator(engine)

        assert calc.get_imbalance() == 0.0


class TestBasicImbalance:
    """Test basic imbalance calculations."""

    def test_bid_heavy_imbalance(self):
        """Bid-heavy book has positive imbalance."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=700, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=300, side=Side.ASK)

        calc = ImbalanceCalculator(engine)
        imbalance = calc.get_imbalance()

        assert imbalance == pytest.approx(0.4)  # (700-300)/1000

    def test_ask_heavy_imbalance(self):
        """Ask-heavy book has negative imbalance."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=300, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=700, side=Side.ASK)

        calc = ImbalanceCalculator(engine)
        imbalance = calc.get_imbalance()

        assert imbalance == pytest.approx(-0.4)  # (300-700)/1000

    def test_balanced_imbalance(self):
        """Balanced book has zero imbalance."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=500, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=500, side=Side.ASK)

        calc = ImbalanceCalculator(engine)

        assert calc.get_imbalance() == 0.0


class TestPriceWeightedImbalance:
    """Test price-weighted imbalance."""

    def test_price_weighted_favors_near_spread(self):
        """Volume near spread has more weight."""
        engine = OrderBookEngine(symbol="RELIANCE")
        # Large volume far from spread
        engine.add_order(order_id="1", price=2400.0, quantity=1000, side=Side.BID)
        # Small volume at spread
        engine.add_order(order_id="2", price=2500.0, quantity=100, side=Side.BID)
        engine.add_order(order_id="3", price=2510.0, quantity=100, side=Side.ASK)

        calc = ImbalanceCalculator(engine)
        weighted = calc.get_price_weighted_imbalance()

        # Price weighting should reduce impact of far orders
        assert abs(weighted) < abs(calc.get_imbalance())


class TestVolumeDelta:
    """Test volume delta calculations."""

    def test_volume_delta_positive(self):
        """Positive delta when bids dominate."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=600, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=400, side=Side.ASK)

        calc = ImbalanceCalculator(engine)

        assert calc.get_volume_delta() == 200  # 600 - 400

    def test_volume_delta_negative(self):
        """Negative delta when asks dominate."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=400, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=600, side=Side.ASK)

        calc = ImbalanceCalculator(engine)

        assert calc.get_volume_delta() == -200  # 400 - 600


class TestCumulativeImbalance:
    """Test cumulative imbalance tracking."""

    def test_cumulative_tracks_history(self):
        """Cumulative imbalance tracks over time."""
        engine = OrderBookEngine(symbol="RELIANCE")
        calc = ImbalanceCalculator(engine)

        # Add first snapshot
        engine.add_order(order_id="1", price=2500.0, quantity=600, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=400, side=Side.ASK)
        calc.record_snapshot()

        assert len(calc.history) == 1

    def test_cumulative_average(self):
        """Calculate average cumulative imbalance."""
        engine = OrderBookEngine(symbol="RELIANCE")
        calc = ImbalanceCalculator(engine)

        # Record multiple snapshots
        engine.add_order(order_id="1", price=2500.0, quantity=600, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=400, side=Side.ASK)
        calc.record_snapshot()

        engine.clear()
        engine.add_order(order_id="3", price=2500.0, quantity=400, side=Side.BID)
        engine.add_order(order_id="4", price=2510.0, quantity=600, side=Side.ASK)
        calc.record_snapshot()

        avg = calc.get_cumulative_imbalance()
        # Average of 0.2 and -0.2
        assert avg == pytest.approx(0.0, abs=0.01)


class TestDivergenceDetection:
    """Test imbalance divergence detection."""

    def test_detect_divergence(self):
        """Detect when imbalance diverges from threshold."""
        engine = OrderBookEngine(symbol="RELIANCE")
        calc = ImbalanceCalculator(engine, divergence_threshold=0.5)

        # Add extreme imbalance
        engine.add_order(order_id="1", price=2500.0, quantity=900, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=100, side=Side.ASK)

        has_divergence, current_imbalance = calc.check_divergence()

        assert has_divergence is True
        assert current_imbalance == pytest.approx(0.8)

    def test_no_divergence(self):
        """No divergence when within threshold."""
        engine = OrderBookEngine(symbol="RELIANCE")
        calc = ImbalanceCalculator(engine, divergence_threshold=0.5)

        engine.add_order(order_id="1", price=2500.0, quantity=550, side=Side.BID)
        engine.add_order(order_id="2", price=2510.0, quantity=450, side=Side.ASK)

        has_divergence, _ = calc.check_divergence()

        assert has_divergence is False


class TestImbalanceEdgeCases:
    """Test edge cases."""

    def test_empty_book_imbalance(self):
        """Empty book has zero imbalance."""
        engine = OrderBookEngine(symbol="RELIANCE")
        calc = ImbalanceCalculator(engine)

        assert calc.get_imbalance() == 0.0
        assert calc.get_volume_delta() == 0

    def test_single_sided_book(self):
        """Single-sided book has extreme imbalance."""
        engine = OrderBookEngine(symbol="RELIANCE")
        engine.add_order(order_id="1", price=2500.0, quantity=100, side=Side.BID)

        calc = ImbalanceCalculator(engine)

        assert calc.get_imbalance() == 1.0  # All bids

    def test_clear_history(self):
        """Clear resets cumulative history."""
        engine = OrderBookEngine(symbol="RELIANCE")
        calc = ImbalanceCalculator(engine)

        calc.record_snapshot()
        calc.clear_history()

        assert len(calc.history) == 0
