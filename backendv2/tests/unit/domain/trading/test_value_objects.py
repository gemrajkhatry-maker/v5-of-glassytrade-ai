"""Unit tests for trading domain value objects."""

import pytest
from decimal import Decimal
from app.domain.trading.model.value_objects import (
    OHLC,
    OrderBook,
    OrderBookLevel,
    AMTResult,
    StrategyStats,
    VolumeProfileLevel,
    AggressivePrint,
)


class TestOHLC:
    """Tests for OHLC value object."""

    def test_create_with_floats(self):
        ohlc = OHLC.create(
            time="2026-01-01T00:00:00",
            open=100.0, high=105.0, low=99.0, close=102.0,
            volume=1000.0,
        )
        assert ohlc.open == Decimal("100")
        assert ohlc.high == Decimal("105")
        assert ohlc.low == Decimal("99")
        assert ohlc.close == Decimal("102")
        assert ohlc.volume == Decimal("1000")

    def test_create_with_decimals(self):
        ohlc = OHLC.create(
            time="2026-01-01T00:00:00",
            open=Decimal("100.5"), high=Decimal("105.5"),
            low=Decimal("99.5"), close=Decimal("102.5"),
            volume=Decimal("1000"),
        )
        assert ohlc.open == Decimal("100.5")

    def test_default_vwap_and_delta(self):
        ohlc = OHLC.create(
            time="2026-01-01T00:00:00",
            open=100, high=105, low=99, close=102, volume=1000,
        )
        assert ohlc.vwap == Decimal("0")
        assert ohlc.taker_buy_volume == Decimal("0")
        assert ohlc.delta == Decimal("0")

    def test_is_frozen(self):
        ohlc = OHLC.create(
            time="2026-01-01T00:00:00",
            open=100, high=105, low=99, close=102, volume=1000,
        )
        with pytest.raises(AttributeError):
            ohlc.close = Decimal("200")


class TestOrderBook:
    """Tests for OrderBook value object."""

    def test_empty_book(self):
        book = OrderBook()
        assert book.bids == ()
        assert book.asks == ()

    def test_book_with_levels(self):
        book = OrderBook(
            bids=(
                OrderBookLevel(price=49999.0, quantity=1.0),
                OrderBookLevel(price=49998.0, quantity=2.0),
            ),
            asks=(
                OrderBookLevel(price=50001.0, quantity=1.0),
                OrderBookLevel(price=50002.0, quantity=2.0),
            ),
        )
        assert len(book.bids) == 2
        assert book.bids[0].price == 49999.0
        assert book.asks[0].price == 50001.0


class TestAMTResult:
    """Tests for AMTResult value object."""

    def test_default_values(self):
        amt = AMTResult()
        assert amt.market_state == "BALANCED"
        assert amt.poc == 0.0
        assert amt.value_area_high == 0.0
        assert amt.value_area_low == 0.0
        assert amt.lvns == ()
        assert amt.hvns == ()
        assert amt.aggression == 0.0
        assert amt.has_displacement is False

    def test_with_values(self):
        amt = AMTResult(
            market_state="IMBALANCED",
            poc=50000.0,
            value_area_high=50200.0,
            value_area_low=49800.0,
            lvns=(49700.0, 49600.0),
            hvns=(50100.0, 50050.0),
            aggression=3.5,
            has_displacement=True,
        )
        assert amt.market_state == "IMBALANCED"
        assert amt.poc == 50000.0
        assert len(amt.lvns) == 2
        assert len(amt.hvns) == 2

    def test_replace(self):
        amt = AMTResult(poc=50000.0, market_state="BALANCED")
        amt2 = amt.__replace__(poc=50100.0)
        assert amt.poc == 50000.0  # original unchanged
        assert amt2.poc == 50100.0
        assert amt2.market_state == "BALANCED"  # other fields preserved

    def test_is_frozen(self):
        amt = AMTResult()
        with pytest.raises(AttributeError):
            amt.poc = 999.0


class TestStrategyStats:
    """Tests for StrategyStats value object."""

    def test_default_values(self):
        stats = StrategyStats()
        assert stats.total_trades == 0
        assert stats.wins == 0
        assert stats.losses == 0
        assert stats.win_rate == 0.0
        assert stats.net_profit == 0.0

    def test_with_values(self):
        stats = StrategyStats(
            total_trades=10, wins=6, losses=4,
            win_rate=60.0, net_profit=5000.0,
            avg_profit=500.0, largest_win=2000.0, largest_loss=-500.0,
        )
        assert stats.total_trades == 10
        assert stats.win_rate == 60.0


class TestVolumeProfileLevel:
    """Tests for VolumeProfileLevel value object."""

    def test_default_values(self):
        level = VolumeProfileLevel(price=50000.0)
        assert level.price == 50000.0
        assert level.volume == 0.0
        assert level.buy_volume == 0.0
        assert level.sell_volume == 0.0

    def test_with_values(self):
        level = VolumeProfileLevel(
            price=50000.0, volume=1000.0,
            buy_volume=600.0, sell_volume=400.0,
        )
        assert level.delta == 200.0

    def test_is_mutable(self):
        """VolumeProfileLevel is mutable during construction."""
        level = VolumeProfileLevel(price=50000.0)
        level.volume = 500.0
        assert level.volume == 500.0


class TestAggressivePrint:
    """Tests for AggressivePrint value object."""

    def test_create(self):
        ap = AggressivePrint(
            price=50000.0, time="09:30:00",
            side="BUY", volume=500.0, delta=300.0,
        )
        assert ap.price == 50000.0
        assert ap.side == "BUY"
        assert ap.delta == 300.0

    def test_is_frozen(self):
        ap = AggressivePrint(
            price=50000.0, time="09:30:00",
            side="BUY", volume=500.0, delta=300.0,
        )
        with pytest.raises(AttributeError):
            ap.price = 99999.0
