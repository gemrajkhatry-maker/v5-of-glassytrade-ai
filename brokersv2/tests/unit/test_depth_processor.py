"""Tests for L2/L3 depth processor with orderbook reconstruction."""
import pytest
from datetime import datetime, timezone
from decimal import Decimal
from brokersv2.domain.market.events import DepthEvent, DepthLevel, TickEvent
from brokersv2.marketdata.depth_processor import (
    DepthProcessor,
    OrderBook,
    OrderBookLevel,
    OrderBookSnapshot,
    BookState,
    DepthProcessorError,
    StaleDepthError,
    InvalidDepthEvent,
)


@pytest.fixture
def now():
    return datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


@pytest.fixture
def sample_depth(now):
    """Create a sample depth event."""
    bids = (
        DepthLevel(price=Decimal("100.00"), quantity=500, orders=5),
        DepthLevel(price=Decimal("99.95"), quantity=300, orders=3),
        DepthLevel(price=Decimal("99.90"), quantity=200, orders=2),
    )
    asks = (
        DepthLevel(price=Decimal("100.05"), quantity=400, orders=4),
        DepthLevel(price=Decimal("100.10"), quantity=250, orders=2),
        DepthLevel(price=Decimal("100.15"), quantity=150, orders=1),
    )
    return DepthEvent(
        timestamp=now,
        security_id="NSE_EQ_SYMBOL1",
        symbol="RELIANCE",
        exchange="NSE",
        bids=bids,
        asks=asks,
        sequence=1,
        is_snapshot=True,
    )


class TestOrderBook:
    """Test OrderBook value object."""

    def test_create_from_depth_event(self, sample_depth, now):
        """Test creating OrderBook from depth event."""
        book = OrderBook.from_depth_event(sample_depth)

        assert book.security_id == "NSE_EQ_SYMBOL1"
        assert book.symbol == "RELIANCE"
        assert book.exchange == "NSE"
        assert book.timestamp == now
        assert book.sequence == 1
        assert len(book.bids) == 3
        assert len(book.asks) == 3

    def test_best_bid(self, sample_depth):
        """Test best bid retrieval."""
        book = OrderBook.from_depth_event(sample_depth)
        best = book.best_bid

        assert best is not None
        assert best.price == Decimal("100.00")
        assert best.quantity == 500
        assert best.orders == 5

    def test_best_ask(self, sample_depth):
        """Test best ask retrieval."""
        book = OrderBook.from_depth_event(sample_depth)
        best = book.best_ask

        assert best is not None
        assert best.price == Decimal("100.05")
        assert best.quantity == 400
        assert best.orders == 4

    def test_mid_price(self, sample_depth):
        """Test mid price calculation."""
        book = OrderBook.from_depth_event(sample_depth)
        mid = book.mid_price

        assert mid == Decimal("100.025")  # (100.00 + 100.05) / 2

    def test_spread(self, sample_depth):
        """Test spread calculation."""
        book = OrderBook.from_depth_event(sample_depth)
        spread = book.spread

        assert spread == Decimal("0.05")  # 100.05 - 100.00

    def test_spread_bps(self, sample_depth):
        """Test spread in basis points."""
        book = OrderBook.from_depth_event(sample_depth)
        spread_bps = book.spread_bps

        assert spread_bps == pytest.approx(5.0, abs=0.1)  # ~5 bps

    def test_imbalance(self, sample_depth):
        """Test book imbalance calculation."""
        book = OrderBook.from_depth_event(sample_depth)
        imbalance = book.imbalance

        # bids: 500+300+200 = 1000
        # asks: 400+250+150 = 800
        # imbalance: (1000-800)/(1000+800) = 200/1800 = 0.111
        assert imbalance == pytest.approx(0.111, abs=0.01)

    def test_empty_book_no_bids(self, now):
        """Test book with no bids."""
        book = OrderBook(
            security_id="TEST",
            symbol="TEST",
            exchange="NSE",
            timestamp=now,
            sequence=1,
            bids=(),
            asks=(DepthLevel(price=Decimal("100.00"), quantity=100, orders=1),),
        )

        assert book.best_bid is None
        assert book.mid_price is None
        assert book.spread is None
        assert book.spread_bps is None

    def test_empty_book_no_asks(self, now):
        """Test book with no asks."""
        book = OrderBook(
            security_id="TEST",
            symbol="TEST",
            exchange="NSE",
            timestamp=now,
            sequence=1,
            bids=(DepthLevel(price=Decimal("100.00"), quantity=100, orders=1),),
            asks=(),
        )

        assert book.best_ask is None
        assert book.mid_price is None
        assert book.spread is None

    def test_book_state_buy_pressure(self, sample_depth):
        """Test book state detection with buy pressure."""
        book = OrderBook.from_depth_event(sample_depth)
        state = book.book_state

        assert state == BookState.BUY_PRESSURE  # More bids than asks

    def test_book_state_sell_pressure(self, now):
        """Test book state detection with sell pressure."""
        bids = (DepthLevel(price=Decimal("100.00"), quantity=100, orders=1),)
        asks = (
            DepthLevel(price=Decimal("100.05"), quantity=500, orders=5),
            DepthLevel(price=Decimal("100.10"), quantity=400, orders=4),
        )
        book = OrderBook(
            security_id="TEST",
            symbol="TEST",
            exchange="NSE",
            timestamp=now,
            sequence=1,
            bids=bids,
            asks=asks,
        )

        state = book.book_state
        assert state == BookState.SELL_PRESSURE

    def test_book_state_balanced(self, now):
        """Test book state detection when balanced."""
        bids = (DepthLevel(price=Decimal("100.00"), quantity=300, orders=3),)
        asks = (DepthLevel(price=Decimal("100.05"), quantity=300, orders=3),)
        book = OrderBook(
            security_id="TEST",
            symbol="TEST",
            exchange="NSE",
            timestamp=now,
            sequence=1,
            bids=bids,
            asks=asks,
        )

        state = book.book_state
        assert state == BookState.BALANCED

    def test_total_bid_quantity(self, sample_depth):
        """Test total bid quantity."""
        book = OrderBook.from_depth_event(sample_depth)
        total = book.total_bid_quantity

        assert total == 1000  # 500+300+200

    def test_total_ask_quantity(self, sample_depth):
        """Test total ask quantity."""
        book = OrderBook.from_depth_event(sample_depth)
        total = book.total_ask_quantity

        assert total == 800  # 400+250+150

    def test_weighted_mid_price(self, sample_depth):
        """Test volume-weighted mid price."""
        book = OrderBook.from_depth_event(sample_depth)
        wmid = book.weighted_mid_price

        # best bid: 100.00 x 500, best ask: 100.05 x 400
        # wmid = (100.00*400 + 100.05*500) / (400+500) = (40000 + 50025) / 900 = 100.0278
        assert wmid == pytest.approx(Decimal("100.0278"), abs=Decimal("0.001"))


class TestDepthProcessor:
    """Test depth processor with real-time orderbook management."""

    def test_process_snapshot(self, sample_depth):
        """Test processing initial snapshot."""
        processor = DepthProcessor(security_id="NSE_EQ_SYMBOL1")
        snapshot = processor.process_depth(sample_depth)

        assert snapshot is not None
        assert snapshot.security_id == "NSE_EQ_SYMBOL1"
        assert snapshot.sequence == 1
        assert snapshot.is_snapshot is True
        assert len(snapshot.book.bids) == 3
        assert len(snapshot.book.asks) == 3

    def test_process_update_after_snapshot(self, sample_depth, now):
        """Test processing incremental update."""
        processor = DepthProcessor(security_id="NSE_EQ_SYMBOL1")
        processor.process_depth(sample_depth)

        # Process update
        bids = (
            DepthLevel(price=Decimal("100.02"), quantity=600, orders=6),
            DepthLevel(price=Decimal("99.95"), quantity=300, orders=3),
        )
        asks = (
            DepthLevel(price=Decimal("100.07"), quantity=350, orders=3),
            DepthLevel(price=Decimal("100.10"), quantity=250, orders=2),
        )
        update = DepthEvent(
            timestamp=now,
            security_id="NSE_EQ_SYMBOL1",
            symbol="RELIANCE",
            exchange="NSE",
            bids=bids,
            asks=asks,
            sequence=2,
            is_snapshot=False,
        )

        result = processor.process_depth(update)

        assert result is not None
        assert result.sequence == 2
        assert result.is_snapshot is False
        assert result.book.best_bid.price == Decimal("100.02")
        assert result.book.best_ask.price == Decimal("100.07")

    def test_out_of_order_update_rejected(self, sample_depth):
        """Test that out-of-order updates are rejected."""
        processor = DepthProcessor(security_id="NSE_EQ_SYMBOL1")
        processor.process_depth(sample_depth)

        # Try to process older sequence
        older = DepthEvent(
            timestamp=sample_depth.timestamp,
            security_id="NSE_EQ_SYMBOL1",
            symbol="RELIANCE",
            exchange="NSE",
            bids=sample_depth.bids,
            asks=sample_depth.asks,
            sequence=0,  # Older than snapshot (sequence=1)
            is_snapshot=False,
        )

        with pytest.raises(InvalidDepthEvent, match="Out of order"):
            processor.process_depth(older)

    def test_stale_depth_detection(self, now):
        """Test detection of stale depth events."""
        processor = DepthProcessor(
            security_id="NSE_EQ_SYMBOL1",
            stale_threshold_seconds=5.0,
        )

        # Process initial snapshot
        bids = (DepthLevel(price=Decimal("100.00"), quantity=500, orders=5),)
        asks = (DepthLevel(price=Decimal("100.05"), quantity=400, orders=4),)
        snapshot = DepthEvent(
            timestamp=now,
            security_id="NSE_EQ_SYMBOL1",
            symbol="RELIANCE",
            exchange="NSE",
            bids=bids,
            asks=asks,
            sequence=1,
            is_snapshot=True,
        )
        processor.process_depth(snapshot)

        # Process update 10 seconds later (stale)
        from datetime import timedelta
        stale_time = now + timedelta(seconds=10)
        stale_update = DepthEvent(
            timestamp=stale_time,
            security_id="NSE_EQ_SYMBOL1",
            symbol="RELIANCE",
            exchange="NSE",
            bids=bids,
            asks=asks,
            sequence=2,
            is_snapshot=False,
        )

        with pytest.raises(StaleDepthError, match="Stale"):
            processor.process_depth(stale_update)

    def test_wrong_security_id_rejected(self, sample_depth):
        """Test that updates with wrong security_id are rejected."""
        processor = DepthProcessor(security_id="NSE_EQ_SYMBOL1")

        # Try to process update for different security
        wrong_update = DepthEvent(
            timestamp=sample_depth.timestamp,
            security_id="NSE_EQ_SYMBOL2",  # Wrong!
            symbol="INFY",
            exchange="NSE",
            bids=sample_depth.bids,
            asks=sample_depth.asks,
            sequence=2,
            is_snapshot=False,
        )

        with pytest.raises(DepthProcessorError, match="security_id mismatch"):
            processor.process_depth(wrong_update)

    def test_sequence_gap_detection(self, sample_depth, now):
        """Test detection of sequence gaps."""
        processor = DepthProcessor(
            security_id="NSE_EQ_SYMBOL1",
            max_sequence_gap=10,
        )
        processor.process_depth(sample_depth)

        # Process update with large gap (sequence 1 -> 20, gap=19 > max=10)
        bids = (DepthLevel(price=Decimal("100.00"), quantity=500, orders=5),)
        asks = (DepthLevel(price=Decimal("100.05"), quantity=400, orders=4),)
        gap_update = DepthEvent(
            timestamp=now,
            security_id="NSE_EQ_SYMBOL1",
            symbol="RELIANCE",
            exchange="NSE",
            bids=bids,
            asks=asks,
            sequence=20,  # Gap from 1 to 20
            is_snapshot=False,
        )

        with pytest.raises(InvalidDepthEvent, match="Sequence gap"):
            processor.process_depth(gap_update)

    def test_get_current_book(self, sample_depth):
        """Test retrieving current orderbook."""
        processor = DepthProcessor(security_id="NSE_EQ_SYMBOL1")
        processor.process_depth(sample_depth)

        book = processor.get_current_book()

        assert book is not None
        assert book.security_id == "NSE_EQ_SYMBOL1"
        assert book.best_bid.price == Decimal("100.00")
        assert book.best_ask.price == Decimal("100.05")

    def test_get_current_book_none_before_snapshot(self):
        """Test that no book is returned before snapshot."""
        processor = DepthProcessor(security_id="NSE_EQ_SYMBOL1")

        book = processor.get_current_book()

        assert book is None

    def test_get_book_history(self, sample_depth, now):
        """Test retrieving book history."""
        processor = DepthProcessor(security_id="NSE_EQ_SYMBOL1", history_size=5)
        processor.process_depth(sample_depth)

        # Process some updates
        for i in range(2, 5):
            bids = (DepthLevel(price=Decimal("100.00"), quantity=500+i*10, orders=5),)
            asks = (DepthLevel(price=Decimal("100.05"), quantity=400+i*10, orders=4),)
            update = DepthEvent(
                timestamp=now,
                security_id="NSE_EQ_SYMBOL1",
                symbol="RELIANCE",
                exchange="NSE",
                bids=bids,
                asks=asks,
                sequence=i,
                is_snapshot=False,
            )
            processor.process_depth(update)

        history = processor.get_book_history()

        assert len(history) == 4  # snapshot + 3 updates
        assert history[0].sequence == 1
        assert history[-1].sequence == 4

    def test_book_state_changes(self, sample_depth, now):
        """Test tracking book state changes over time."""
        processor = DepthProcessor(security_id="NSE_EQ_SYMBOL1")
        processor.process_depth(sample_depth)

        initial_state = processor.get_current_book().book_state
        assert initial_state == BookState.BUY_PRESSURE

        # Create sell pressure update
        bids = (DepthLevel(price=Decimal("100.00"), quantity=100, orders=1),)
        asks = (
            DepthLevel(price=Decimal("100.05"), quantity=500, orders=5),
            DepthLevel(price=Decimal("100.10"), quantity=400, orders=4),
        )
        update = DepthEvent(
            timestamp=now,
            security_id="NSE_EQ_SYMBOL1",
            symbol="RELIANCE",
            exchange="NSE",
            bids=bids,
            asks=asks,
            sequence=2,
            is_snapshot=False,
        )
        processor.process_depth(update)

        new_state = processor.get_current_book().book_state
        assert new_state == BookState.SELL_PRESSURE

    def test_depth_metrics(self, sample_depth):
        """Test depth metrics calculation."""
        processor = DepthProcessor(security_id="NSE_EQ_SYMBOL1")
        processor.process_depth(sample_depth)

        metrics = processor.get_metrics()

        assert metrics["security_id"] == "NSE_EQ_SYMBOL1"
        assert metrics["total_updates"] == 1
        assert metrics["current_sequence"] == 1
        assert "best_bid" in metrics
        assert "best_ask" in metrics
        assert "spread" in metrics
        assert "imbalance" in metrics
