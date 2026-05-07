"""Tests for OHLC candle builder with multi-timeframe support."""
import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from brokersv2.domain.market.events import TickEvent
from brokersv2.marketdata.candle_builder import (
    CandleBuilder,
    Candle,
    Timeframe,
    CandleBuilderError,
    InvalidTickError,
    CandleClosedError,
)


@pytest.fixture
def now():
    return datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


@pytest.fixture
def sample_ticks(now):
    """Create sample tick events spanning multiple minutes."""
    return [
        # Minute 0 (10:30:00 - 10:30:59)
        TickEvent(
            timestamp=now,
            security_id="NSE_EQ_SYMBOL1",
            symbol="RELIANCE",
            exchange="NSE",
            ltp=Decimal("100.00"),
            open=Decimal("99.50"),
            high=Decimal("101.00"),
            low=Decimal("99.00"),
            close=Decimal("99.50"),
            volume=1000,
            oi=5000,
        ),
        TickEvent(
            timestamp=now + timedelta(seconds=30),
            security_id="NSE_EQ_SYMBOL1",
            symbol="RELIANCE",
            exchange="NSE",
            ltp=Decimal("100.50"),
            open=Decimal("100.00"),
            high=Decimal("101.00"),
            low=Decimal("99.50"),
            close=Decimal("100.00"),
            volume=500,
            oi=5100,
        ),
        # Minute 1 (10:31:00 - 10:31:59)
        TickEvent(
            timestamp=now + timedelta(minutes=1),
            security_id="NSE_EQ_SYMBOL1",
            symbol="RELIANCE",
            exchange="NSE",
            ltp=Decimal("101.00"),
            open=Decimal("100.50"),
            high=Decimal("101.50"),
            low=Decimal("100.00"),
            close=Decimal("100.50"),
            volume=800,
            oi=5200,
        ),
        TickEvent(
            timestamp=now + timedelta(minutes=1, seconds=30),
            security_id="NSE_EQ_SYMBOL1",
            symbol="RELIANCE",
            exchange="NSE",
            ltp=Decimal("101.50"),
            open=Decimal("101.00"),
            high=Decimal("102.00"),
            low=Decimal("100.50"),
            close=Decimal("101.00"),
            volume=600,
            oi=5300,
        ),
        # Minute 2 (10:32:00 - 10:32:59)
        TickEvent(
            timestamp=now + timedelta(minutes=2),
            security_id="NSE_EQ_SYMBOL1",
            symbol="RELIANCE",
            exchange="NSE",
            ltp=Decimal("101.00"),
            open=Decimal("101.50"),
            high=Decimal("101.50"),
            low=Decimal("100.50"),
            close=Decimal("101.50"),
            volume=700,
            oi=5200,
        ),
    ]


class TestCandle:
    """Test Candle value object."""

    def test_candle_creation(self, now):
        """Test basic candle creation."""
        candle = Candle(
            timestamp=now,
            security_id="TEST",
            symbol="TEST",
            exchange="NSE",
            timeframe=Timeframe.MINUTE_1,
            open=Decimal("100.00"),
            high=Decimal("102.00"),
            low=Decimal("99.00"),
            close=Decimal("101.00"),
            volume=1000,
            oi=5000,
            is_complete=True,
        )

        assert candle.open == Decimal("100.00")
        assert candle.high == Decimal("102.00")
        assert candle.low == Decimal("99.00")
        assert candle.close == Decimal("101.00")
        assert candle.volume == 1000
        assert candle.is_complete is True

    def test_candle_range(self, now):
        """Test candle range calculation."""
        candle = Candle(
            timestamp=now,
            security_id="TEST",
            symbol="TEST",
            exchange="NSE",
            timeframe=Timeframe.MINUTE_1,
            open=Decimal("100.00"),
            high=Decimal("102.00"),
            low=Decimal("99.00"),
            close=Decimal("101.00"),
            volume=1000,
            oi=5000,
            is_complete=True,
        )

        assert candle.range == Decimal("3.00")  # 102.00 - 99.00

    def test_candle_body(self, now):
        """Test candle body calculation."""
        candle = Candle(
            timestamp=now,
            security_id="TEST",
            symbol="TEST",
            exchange="NSE",
            timeframe=Timeframe.MINUTE_1,
            open=Decimal("100.00"),
            high=Decimal("102.00"),
            low=Decimal("99.00"),
            close=Decimal("101.00"),
            volume=1000,
            oi=5000,
            is_complete=True,
        )

        assert candle.body == Decimal("1.00")  # |101.00 - 100.00|

    def test_candle_is_bullish(self, now):
        """Test bullish candle detection."""
        candle = Candle(
            timestamp=now,
            security_id="TEST",
            symbol="TEST",
            exchange="NSE",
            timeframe=Timeframe.MINUTE_1,
            open=Decimal("100.00"),
            high=Decimal("102.00"),
            low=Decimal("99.00"),
            close=Decimal("101.00"),
            volume=1000,
            oi=5000,
            is_complete=True,
        )

        assert candle.is_bullish is True  # close > open

    def test_candle_is_bearish(self, now):
        """Test bearish candle detection."""
        candle = Candle(
            timestamp=now,
            security_id="TEST",
            symbol="TEST",
            exchange="NSE",
            timeframe=Timeframe.MINUTE_1,
            open=Decimal("101.00"),
            high=Decimal("102.00"),
            low=Decimal("99.00"),
            close=Decimal("100.00"),
            volume=1000,
            oi=5000,
            is_complete=True,
        )

        assert candle.is_bearish is True  # close < open

    def test_candle_is_doji(self, now):
        """Test doji candle detection."""
        candle = Candle(
            timestamp=now,
            security_id="TEST",
            symbol="TEST",
            exchange="NSE",
            timeframe=Timeframe.MINUTE_1,
            open=Decimal("100.00"),
            high=Decimal("100.50"),
            low=Decimal("99.50"),
            close=Decimal("100.00"),
            volume=1000,
            oi=5000,
            is_complete=True,
        )

        assert candle.is_doji is True  # close == open

    def test_candle_vwap(self, now):
        """Test candle VWAP calculation."""
        candle = Candle(
            timestamp=now,
            security_id="TEST",
            symbol="TEST",
            exchange="NSE",
            timeframe=Timeframe.MINUTE_1,
            open=Decimal("100.00"),
            high=Decimal("102.00"),
            low=Decimal("99.00"),
            close=Decimal("101.00"),
            volume=1000,
            oi=5000,
            is_complete=True,
        )

        # Typical price = (high + low + close) / 3 = (102 + 99 + 101) / 3 = 100.667
        # VWAP ≈ typical_price for single candle
        assert candle.vwap == pytest.approx(Decimal("100.667"), abs=Decimal("0.1"))


class TestCandleBuilder:
    """Test candle builder with real-time aggregation."""

    def test_build_1min_candle(self, sample_ticks, now):
        """Test building 1-minute candles."""
        builder = CandleBuilder(
            security_id="NSE_EQ_SYMBOL1",
            timeframe=Timeframe.MINUTE_1,
        )

        candles = []
        for tick in sample_ticks:
            candle = builder.process_tick(tick)
            if candle is not None:
                candles.append(candle)

        # Should complete candles when minute boundary crossed
        assert len(candles) >= 2  # At least 2 completed candles

        # Check first candle
        first_candle = candles[0]
        assert first_candle.timeframe == Timeframe.MINUTE_1
        assert first_candle.security_id == "NSE_EQ_SYMBOL1"
        assert first_candle.is_complete is True

    def test_build_5min_candle(self, sample_ticks, now):
        """Test building 5-minute candles."""
        builder = CandleBuilder(
            security_id="NSE_EQ_SYMBOL1",
            timeframe=Timeframe.MINUTE_5,
        )

        candles = []
        for tick in sample_ticks:
            candle = builder.process_tick(tick)
            if candle is not None:
                candles.append(candle)

        # All ticks within 5 minutes, might not complete yet
        # But we should have partial candle state
        current = builder.get_current_candle()
        assert current is not None

    def test_wrong_security_rejected(self, now):
        """Test that ticks with wrong security_id are rejected."""
        builder = CandleBuilder(security_id="TEST1", timeframe=Timeframe.MINUTE_1)
        tick = TickEvent(
            timestamp=now,
            security_id="TEST2",  # Wrong!
            symbol="OTHER",
            exchange="NSE",
            ltp=Decimal("100.00"),
            open=Decimal("99.50"),
            high=Decimal("100.50"),
            low=Decimal("99.00"),
            close=Decimal("99.50"),
            volume=1000,
            oi=0,
        )

        with pytest.raises(InvalidTickError, match="security_id mismatch"):
            builder.process_tick(tick)

    def test_ohl_aggregation(self, sample_ticks, now):
        """Test OHLC price aggregation."""
        builder = CandleBuilder(
            security_id="NSE_EQ_SYMBOL1",
            timeframe=Timeframe.MINUTE_1,
        )

        # Process first two ticks (same minute)
        builder.process_tick(sample_ticks[0])
        builder.process_tick(sample_ticks[1])

        current = builder.get_current_candle()

        assert current is not None
        # Open should be from first tick
        assert current.open == Decimal("100.00")
        # High should be max of LTP from all ticks (100.00, 100.50)
        assert current.high == Decimal("100.50")
        # Low should be min of LTP from all ticks
        assert current.low == Decimal("100.00")
        # Close should be from latest tick
        assert current.close == Decimal("100.50")

    def test_volume_aggregation(self, sample_ticks):
        """Test volume aggregation."""
        builder = CandleBuilder(
            security_id="NSE_EQ_SYMBOL1",
            timeframe=Timeframe.MINUTE_1,
        )

        # Process first two ticks
        builder.process_tick(sample_ticks[0])
        builder.process_tick(sample_ticks[1])

        current = builder.get_current_candle()

        assert current is not None
        assert current.volume == 1500  # 1000 + 500

    def test_oi_update(self, sample_ticks):
        """Test open interest tracking."""
        builder = CandleBuilder(
            security_id="NSE_EQ_SYMBOL1",
            timeframe=Timeframe.MINUTE_1,
        )

        builder.process_tick(sample_ticks[0])
        builder.process_tick(sample_ticks[1])

        current = builder.get_current_candle()

        assert current is not None
        # OI should be from latest tick
        assert current.oi == 5100

    def test_get_completed_candles(self, sample_ticks):
        """Test retrieving completed candles."""
        builder = CandleBuilder(
            security_id="NSE_EQ_SYMBOL1",
            timeframe=Timeframe.MINUTE_1,
        )

        for tick in sample_ticks:
            builder.process_tick(tick)

        completed = builder.get_completed_candles()

        assert len(completed) >= 2
        # All should be complete
        assert all(c.is_complete for c in completed)
        # Should be ordered by timestamp
        for i in range(len(completed) - 1):
            assert completed[i].timestamp <= completed[i + 1].timestamp

    def test_candle_history_limit(self, now):
        """Test candle history size limit."""
        builder = CandleBuilder(
            security_id="TEST",
            timeframe=Timeframe.MINUTE_1,
            history_size=3,
        )

        # Create ticks that complete many candles
        for i in range(10):
            tick = TickEvent(
                timestamp=now + timedelta(minutes=i),
                security_id="TEST",
                symbol="TEST",
                exchange="NSE",
                ltp=Decimal("100.00"),
                open=Decimal("99.50"),
                high=Decimal("100.50"),
                low=Decimal("99.00"),
                close=Decimal("99.50"),
                volume=1000,
                oi=5000,
            )
            builder.process_tick(tick)

        completed = builder.get_completed_candles()

        # Should only keep last 3 candles
        assert len(completed) <= 3

    def test_timeframe_minute_1(self, now):
        """Test 1-minute timeframe."""
        builder = CandleBuilder(
            security_id="TEST",
            timeframe=Timeframe.MINUTE_1,
        )

        tick = TickEvent(
            timestamp=now,
            security_id="TEST",
            symbol="TEST",
            exchange="NSE",
            ltp=Decimal("100.00"),
            open=Decimal("99.50"),
            high=Decimal("100.50"),
            low=Decimal("99.00"),
            close=Decimal("99.50"),
            volume=1000,
            oi=0,
        )

        candle = builder.process_tick(tick)
        # First tick starts candle, no completion yet
        # But get_current_candle should return partial
        current = builder.get_current_candle()
        assert current is not None
        assert current.timeframe == Timeframe.MINUTE_1

    def test_timeframe_minute_5(self, now):
        """Test 5-minute timeframe."""
        builder = CandleBuilder(
            security_id="TEST",
            timeframe=Timeframe.MINUTE_5,
        )

        tick = TickEvent(
            timestamp=now,
            security_id="TEST",
            symbol="TEST",
            exchange="NSE",
            ltp=Decimal("100.00"),
            open=Decimal("99.50"),
            high=Decimal("100.50"),
            low=Decimal("99.00"),
            close=Decimal("99.50"),
            volume=1000,
            oi=0,
        )

        builder.process_tick(tick)

        current = builder.get_current_candle()
        assert current is not None
        assert current.timeframe == Timeframe.MINUTE_5

    def test_timeframe_minute_15(self, now):
        """Test 15-minute timeframe."""
        builder = CandleBuilder(
            security_id="TEST",
            timeframe=Timeframe.MINUTE_15,
        )

        tick = TickEvent(
            timestamp=now,
            security_id="TEST",
            symbol="TEST",
            exchange="NSE",
            ltp=Decimal("100.00"),
            open=Decimal("99.50"),
            high=Decimal("100.50"),
            low=Decimal("99.00"),
            close=Decimal("99.50"),
            volume=1000,
            oi=0,
        )

        builder.process_tick(tick)

        current = builder.get_current_candle()
        assert current is not None
        assert current.timeframe == Timeframe.MINUTE_15

    def test_timeframe_hour_1(self, now):
        """Test 1-hour timeframe."""
        builder = CandleBuilder(
            security_id="TEST",
            timeframe=Timeframe.HOUR_1,
        )

        tick = TickEvent(
            timestamp=now,
            security_id="TEST",
            symbol="TEST",
            exchange="NSE",
            ltp=Decimal("100.00"),
            open=Decimal("99.50"),
            high=Decimal("100.50"),
            low=Decimal("99.00"),
            close=Decimal("99.50"),
            volume=1000,
            oi=0,
        )

        builder.process_tick(tick)

        current = builder.get_current_candle()
        assert current is not None
        assert current.timeframe == Timeframe.HOUR_1

    def test_reset_builder(self, sample_ticks):
        """Test resetting candle builder."""
        builder = CandleBuilder(
            security_id="NSE_EQ_SYMBOL1",
            timeframe=Timeframe.MINUTE_1,
        )

        for tick in sample_ticks:
            builder.process_tick(tick)

        builder.reset()

        current = builder.get_current_candle()
        assert current is None

        completed = builder.get_completed_candles()
        assert len(completed) == 0

    def test_out_of_order_tick(self, now):
        """Test handling out-of-order ticks."""
        builder = CandleBuilder(
            security_id="TEST",
            timeframe=Timeframe.MINUTE_1,
        )

        # Process tick at 10:31
        tick1 = TickEvent(
            timestamp=now + timedelta(minutes=1),
            security_id="TEST",
            symbol="TEST",
            exchange="NSE",
            ltp=Decimal("101.00"),
            open=Decimal("100.00"),
            high=Decimal("101.00"),
            low=Decimal("100.00"),
            close=Decimal("100.00"),
            volume=1000,
            oi=0,
        )
        builder.process_tick(tick1)

        # Try to process older tick at 10:30
        tick2 = TickEvent(
            timestamp=now,
            security_id="TEST",
            symbol="TEST",
            exchange="NSE",
            ltp=Decimal("100.00"),
            open=Decimal("99.50"),
            high=Decimal("100.50"),
            low=Decimal("99.00"),
            close=Decimal("99.50"),
            volume=1000,
            oi=0,
        )

        # Should still process (might go into previous candle or be rejected)
        # Implementation decision: allow or reject
        # For now, let's allow it
        try:
            builder.process_tick(tick2)
        except CandleClosedError:
            # This is also acceptable - candle already closed
            pass

    def test_candle_metrics(self, sample_ticks):
        """Test candle metrics calculation."""
        builder = CandleBuilder(
            security_id="NSE_EQ_SYMBOL1",
            timeframe=Timeframe.MINUTE_1,
        )

        for tick in sample_ticks:
            builder.process_tick(tick)

        metrics = builder.get_metrics()

        assert metrics["security_id"] == "NSE_EQ_SYMBOL1"
        assert metrics["timeframe"] == Timeframe.MINUTE_1
        assert metrics["total_ticks_processed"] > 0
        assert metrics["completed_candles"] >= 2
        assert "current_candle" in metrics
