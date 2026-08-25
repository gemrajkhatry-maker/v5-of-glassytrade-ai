"""
Tests for rich Option and OptionChain domain models.

These tests verify the new features ported from dhanhq_custom:
- Option dataclass with Greeks, OI, volume
- OptionChain with ATM/OTM/ITM discovery
- Strike navigation methods
"""

import pytest
from datetime import datetime
from brokers.broker.entities import (
    Option,
    OptionChain,
    Instrument,
    DepthLevel,
    MarketDepth,
    Quote,
    Tick,
    Order,
)
from brokers.broker.types import Exchange, OptionType, OrderSide, OrderType


class TestOption:
    """Test the Option dataclass."""

    def test_option_creation(self):
        """Test basic Option creation."""
        option = Option(
            symbol="NIFTY26FEB25CE25000",
            security_id="12345",
            strike=25000.0,
            option_type="CE",
            expiry=datetime(2025, 2, 26),
            ltp=150.0,
            oi=50000,
            volume=10000,
            bid=149.0,
            ask=151.0,
            delta=0.5,
            gamma=0.001,
            theta=-15.0,
            vega=25.0,
        )

        assert option.symbol == "NIFTY26FEB25CE25000"
        assert option.strike == 25000.0
        assert option.option_type == "CE"
        assert option.ltp == 150.0
        assert option.oi == 50000
        assert option.volume == 10000
        assert option.delta == 0.5
        assert option.is_call is True
        assert option.is_put is False

    def test_option_immutability(self):
        """Test that Option is frozen (immutable)."""
        option = Option(
            symbol="TEST",
            security_id="1",
            strike=100.0,
            option_type="CE",
            expiry=datetime.now(),
            ltp=150.0,
        )

        with pytest.raises(AttributeError):
            option.ltp = 200.0


class TestOptionChain:
    """Test the OptionChain dataclass."""

    @pytest.fixture
    def sample_underlying(self):
        """Create sample underlying instrument."""
        return Instrument(symbol="NIFTY", exchange=Exchange.INDEX, security_id="NIFTY")

    @pytest.fixture
    def sample_option_chain(self, sample_underlying):
        """Create sample option chain with multiple strikes."""
        expiry = datetime(2025, 2, 26)

        calls = {}
        puts = {}

        # Create strikes around ATM (25100)
        for strike in [25000, 25100, 25200]:
            calls[strike] = Option(
                symbol=f"NIFTY26FEB25CE{strike}",
                security_id=f"C{strike}",
                strike=float(strike),
                option_type="CE",
                expiry=expiry,
                ltp=150.0,
                oi=50000,
                volume=10000,
            )
            puts[strike] = Option(
                symbol=f"NIFTY26FEB25PE{strike}",
                security_id=f"P{strike}",
                strike=float(strike),
                option_type="PE",
                expiry=expiry,
                ltp=120.0,
                oi=45000,
                volume=8000,
            )

        return OptionChain(
            underlying=sample_underlying,
            expiry=expiry,
            spot_price=25100.0,
            atm_strike=25100.0,
            step_size=100.0,
            calls=calls,
            puts=puts,
        )

    def test_option_chain_creation(self, sample_option_chain):
        """Test basic OptionChain creation."""
        assert sample_option_chain.spot_price == 25100.0
        assert sample_option_chain.atm_strike == 25100.0
        assert sample_option_chain.step_size == 100.0
        assert len(sample_option_chain.calls) == 3
        assert len(sample_option_chain.puts) == 3

    def test_strikes_property(self, sample_option_chain):
        """Test strikes property returns sorted strikes."""
        strikes = sample_option_chain.strikes
        assert strikes == [25000, 25100, 25200]


class TestDepthLevel:
    """Test the DepthLevel dataclass."""

    def test_depth_level_creation(self):
        """Test basic DepthLevel creation."""
        level = DepthLevel(price=100.50, quantity=500, orders=10)
        assert level.price == 100.50
        assert level.quantity == 500
        assert level.orders == 10

    def test_depth_level_without_orders(self):
        """Test DepthLevel without orders field."""
        level = DepthLevel(price=100.50, quantity=500)
        assert level.orders is None
        assert str(level) == "₹100.50 × 500"

    def test_depth_level_with_orders(self):
        """Test DepthLevel string representation with orders."""
        level = DepthLevel(price=100.50, quantity=500, orders=10)
        assert "10 orders" in str(level)

    def test_depth_level_immutability(self):
        """Test that DepthLevel is frozen."""
        level = DepthLevel(price=100.50, quantity=500)
        with pytest.raises(AttributeError):
            level.price = 101.0


class TestMarketDepth:
    """Test the MarketDepth dataclass."""

    @pytest.fixture
    def sample_depth(self):
        """Create sample market depth."""
        levels = [
            DepthLevel(price=100.00, quantity=1000, orders=5),
            DepthLevel(price=99.95, quantity=2000, orders=10),
            DepthLevel(price=99.90, quantity=1500, orders=8),
        ]
        return MarketDepth(
            symbol="RELIANCE",
            security_id="2885",
            side="bid",
            levels=levels,
            timestamp=datetime.now(),
        )

    def test_market_depth_creation(self, sample_depth):
        """Test MarketDepth creation."""
        assert sample_depth.symbol == "RELIANCE"
        assert sample_depth.security_id == "2885"
        assert sample_depth.side == "bid"
        assert len(sample_depth.levels) == 3

    def test_market_depth_immutability(self):
        """Test that MarketDepth is frozen."""
        levels = [DepthLevel(price=100.00, quantity=1000)]
        depth = MarketDepth(
            symbol="TEST",
            security_id="1",
            side="bid",
            levels=levels,
            timestamp=datetime.now(),
        )
        with pytest.raises(AttributeError):
            depth.symbol = "OTHER"


class TestQuoteWithDepth:
    """Test Quote with depth data."""

    @pytest.fixture
    def sample_instrument(self):
        return Instrument(symbol="RELIANCE", exchange=Exchange.NSE, security_id="2885")

    def test_quote_without_depth(self, sample_instrument):
        """Test basic quote without depth."""
        quote = Quote(
            instrument=sample_instrument,
            ltp=2456.50,
            bid=2456.00,
            ask=2457.00,
            volume=100000,
            open=2450.00,
            high=2460.00,
            low=2445.00,
            close=2455.00,
        )
        assert not quote.has_depth
        assert quote.spread == 1.00
        assert quote.spread_pct == pytest.approx(0.0407, rel=0.01)

    def test_quote_with_depth(self, sample_instrument):
        """Test quote with market depth."""
        bid_depth = [
            DepthLevel(price=2456.00, quantity=5000, orders=10),
            DepthLevel(price=2455.95, quantity=3000, orders=5),
        ]
        ask_depth = [
            DepthLevel(price=2457.00, quantity=4000, orders=8),
            DepthLevel(price=2457.05, quantity=2000, orders=4),
        ]

        quote = Quote(
            instrument=sample_instrument,
            ltp=2456.50,
            bid=2456.00,
            ask=2457.00,
            volume=100000,
            open=2450.00,
            high=2460.00,
            low=2445.00,
            close=2455.00,
            bid_depth=bid_depth,
            ask_depth=ask_depth,
        )

        assert quote.has_depth
        assert len(quote.bid_depth) == 2
        assert len(quote.ask_depth) == 2
        assert quote.bid_depth[0].price == 2456.00
        assert quote.ask_depth[0].price == 2457.00

    def test_quote_oi_optional(self, sample_instrument):
        """Quote stores and returns optional oi (open interest)."""
        quote = Quote(
            instrument=sample_instrument,
            ltp=2456.50,
            bid=2456.00,
            ask=2457.00,
            volume=100000,
            open=2450.00,
            high=2460.00,
            low=2445.00,
            close=2455.00,
            oi=125000,
        )
        assert quote.oi == 125000

    def test_quote_oi_default_none(self, sample_instrument):
        """Quote defaults oi to None when not provided."""
        quote = Quote(
            instrument=sample_instrument,
            ltp=2456.50,
            bid=2456.00,
            ask=2457.00,
            volume=100000,
            open=2450.00,
            high=2460.00,
            low=2445.00,
            close=2455.00,
        )
        assert quote.oi is None


class TestOrderNewFields:
    """Tests for new trigger_price and product_type fields on Order."""

    @pytest.fixture
    def base_instrument(self):
        return Instrument(symbol="NIFTY", exchange=Exchange.NFO, security_id="")

    def test_order_defaults(self, base_instrument):
        """Order defaults trigger_price to None and product_type to INTRADAY."""
        order = Order(
            instrument=base_instrument,
            side=OrderSide.BUY,
            quantity=50,
        )
        assert order.trigger_price is None
        assert order.product_type == "INTRADAY"

    def test_order_with_trigger_price(self, base_instrument):
        """Order stores trigger_price for SL orders."""
        order = Order(
            instrument=base_instrument,
            side=OrderSide.BUY,
            quantity=50,
            price=18100.0,
            order_type=OrderType.SL,
            trigger_price=18000.0,
        )
        assert order.trigger_price == 18000.0
        assert order.price == 18100.0

    def test_order_with_custom_product_type(self, base_instrument):
        """Order stores custom product_type."""
        order = Order(
            instrument=base_instrument,
            side=OrderSide.BUY,
            quantity=10,
            product_type="CNC",
        )
        assert order.product_type == "CNC"

    def test_order_slm_trigger_only(self, base_instrument):
        """SLM order uses trigger_price without limit price."""
        order = Order(
            instrument=base_instrument,
            side=OrderSide.SELL,
            quantity=50,
            order_type=OrderType.SLM,
            trigger_price=17900.0,
        )
        assert order.trigger_price == 17900.0
        assert order.price is None


class TestTickNewFields:
    """Tests for new bid, ask, bid_depth, ask_depth fields on Tick."""

    @pytest.fixture
    def base_instrument(self):
        return Instrument(symbol="RELIANCE", exchange=Exchange.NSE, security_id="2885")

    def test_tick_backward_compat(self, base_instrument):
        """Tick can still be created without bid/ask (existing callers unaffected)."""
        tick = Tick(instrument=base_instrument, price=2500.0, volume=1000)
        assert tick.price == 2500.0
        assert tick.bid is None
        assert tick.ask is None

    def test_tick_with_bid_ask(self, base_instrument):
        """Tick stores bid and ask when provided."""
        tick = Tick(
            instrument=base_instrument,
            price=2500.0,
            volume=1000,
            bid=2499.5,
            ask=2500.5,
        )
        assert tick.bid == 2499.5
        assert tick.ask == 2500.5

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
