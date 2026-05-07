"""
Tests for market data events.
"""

import pytest
from decimal import Decimal
from datetime import datetime

from brokersv2.domain.market.events import (
    TickEvent,
    DepthEvent,
    DepthLevel,
    QuoteEvent,
    CandleEvent,
    Exchange,
    MarketDataCodec,
)


class TestTickEvent:
    """Tests for TickEvent."""

    def test_create_tick(self):
        """Test creating a tick event."""
        tick = TickEvent(
            timestamp=datetime.now(),
            security_id="12345",
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            ltp=Decimal("2500.50"),
            open=Decimal("2480"),
            high=Decimal("2520"),
            low=Decimal("2475"),
            close=Decimal("2490"),
            volume=100000,
        )
        
        assert tick.ltp == Decimal("2500.50")
        assert tick.volume == 100000

    def test_tick_change(self):
        """Test price change calculation."""
        tick = TickEvent(
            timestamp=datetime.now(),
            security_id="12345",
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            ltp=Decimal("2500"),
            open=Decimal("2480"),
            high=Decimal("2520"),
            low=Decimal("2475"),
            close=Decimal("2490"),
            volume=100000,
        )
        
        assert tick.change == Decimal("10")
        assert tick.change_pct > 0

    def test_tick_immutability(self):
        """Test that tick events are immutable."""
        tick = TickEvent(
            timestamp=datetime.now(),
            security_id="12345",
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            ltp=Decimal("2500"),
            open=Decimal("2480"),
            high=Decimal("2520"),
            low=Decimal("2475"),
            close=Decimal("2490"),
            volume=100000,
        )
        
        with pytest.raises(AttributeError):
            tick.ltp = Decimal("2600")


class TestDepthEvent:
    """Tests for DepthEvent."""

    def test_create_depth(self):
        """Test creating a depth event."""
        depth = DepthEvent(
            timestamp=datetime.now(),
            security_id="12345",
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            bids=(
                DepthLevel(price=Decimal("2500"), quantity=100),
                DepthLevel(price=Decimal("2499"), quantity=200),
            ),
            asks=(
                DepthLevel(price=Decimal("2501"), quantity=150),
                DepthLevel(price=Decimal("2502"), quantity=250),
            ),
        )
        
        assert len(depth.bids) == 2
        assert len(depth.asks) == 2

    def test_best_bid_ask(self):
        """Test best bid/ask extraction."""
        depth = DepthEvent(
            timestamp=datetime.now(),
            security_id="12345",
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            bids=(
                DepthLevel(price=Decimal("2500"), quantity=100),
                DepthLevel(price=Decimal("2499"), quantity=200),
            ),
            asks=(
                DepthLevel(price=Decimal("2501"), quantity=150),
                DepthLevel(price=Decimal("2502"), quantity=250),
            ),
        )
        
        assert depth.best_bid.price == Decimal("2500")
        assert depth.best_ask.price == Decimal("2501")

    def test_spread_calculation(self):
        """Test bid-ask spread calculation."""
        depth = DepthEvent(
            timestamp=datetime.now(),
            security_id="12345",
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            bids=(DepthLevel(price=Decimal("2500"), quantity=100),),
            asks=(DepthLevel(price=Decimal("2502"), quantity=150),),
        )
        
        assert depth.spread == Decimal("2")

    def test_mid_price(self):
        """Test mid price calculation."""
        depth = DepthEvent(
            timestamp=datetime.now(),
            security_id="12345",
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            bids=(DepthLevel(price=Decimal("2500"), quantity=100),),
            asks=(DepthLevel(price=Decimal("2502"), quantity=150),),
        )
        
        assert depth.mid_price == Decimal("2501")

    def test_imbalance_calculation(self):
        """Test order book imbalance."""
        # Buying pressure
        depth_buy = DepthEvent(
            timestamp=datetime.now(),
            security_id="12345",
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            bids=(DepthLevel(price=Decimal("2500"), quantity=300),),
            asks=(DepthLevel(price=Decimal("2502"), quantity=100),),
        )
        
        assert depth_buy.imbalance > 0
        
        # Selling pressure
        depth_sell = DepthEvent(
            timestamp=datetime.now(),
            security_id="12345",
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            bids=(DepthLevel(price=Decimal("2500"), quantity=100),),
            asks=(DepthLevel(price=Decimal("2502"), quantity=300),),
        )
        
        assert depth_sell.imbalance < 0


class TestMarketDataCodec:
    """Tests for MarketDataCodec (msgspec serialization)."""

    def test_tick_encode_decode(self):
        """Test TickEvent serialization roundtrip."""
        codec = MarketDataCodec()
        
        original = TickEvent(
            timestamp=datetime.now(),
            security_id="12345",
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            ltp=Decimal("2500.50"),
            open=Decimal("2480"),
            high=Decimal("2520"),
            low=Decimal("2475"),
            close=Decimal("2490"),
            volume=100000,
        )
        
        encoded = codec.encode_tick(original)
        decoded = codec.decode_tick(encoded)
        
        assert decoded.ltp == original.ltp
        assert decoded.symbol == original.symbol
        assert decoded.volume == original.volume

    def test_depth_encode_decode(self):
        """Test DepthEvent serialization roundtrip."""
        codec = MarketDataCodec()
        
        original = DepthEvent(
            timestamp=datetime.now(),
            security_id="12345",
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            bids=(
                DepthLevel(price=Decimal("2500"), quantity=100),
                DepthLevel(price=Decimal("2499"), quantity=200),
            ),
            asks=(
                DepthLevel(price=Decimal("2501"), quantity=150),
                DepthLevel(price=Decimal("2502"), quantity=250),
            ),
        )
        
        encoded = codec.encode_depth(original)
        decoded = codec.decode_depth(encoded)
        
        assert len(decoded.bids) == len(original.bids)
        assert decoded.best_bid.price == original.best_bid.price
        assert decoded.spread == original.spread
