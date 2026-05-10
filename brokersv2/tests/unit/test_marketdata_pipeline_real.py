"""
Tests for MarketDataPipeline with real API integration.
"""

import pytest
import asyncio
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from brokersv2.marketdata.pipeline import MarketDataPipeline
from brokersv2.domain.market.models import Quote, Candle, Tick
from brokersv2.domain.instrument.models import CanonicalInstrument
from brokersv2.core.types import Exchange, Segment, InstrumentType


@pytest.fixture
def mock_client():
    """Create a mock DhanHttpClient."""
    client = MagicMock()
    client.get_quote = AsyncMock(return_value=Quote(
        instrument=MagicMock(),
        ltp=Decimal("150.50"),
        bid=Decimal("150.40"),
        ask=Decimal("150.60"),
        volume=5000,
        open=Decimal("149.00"),
        high=Decimal("151.00"),
        low=Decimal("148.50"),
        close=Decimal("150.00"),
    ))
    client.get_historical = AsyncMock(return_value=[
        Candle(
            instrument=MagicMock(),
            timeframe="1d",
            timestamp=datetime.now(),
            open=Decimal("100.0"),
            high=Decimal("105.0"),
            low=Decimal("98.0"),
            close=Decimal("102.0"),
            volume=Decimal("10000"),
        )
    ])
    return client


@pytest.fixture
def test_instrument():
    """Create a test instrument."""
    return CanonicalInstrument(
        internal_uid="test-1",
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        segment=Segment.EQUITY,
        instrument_type=InstrumentType.EQUITY,
        lot_size=1,
        tick_size=Decimal("0.05"),
    )


class TestMarketDataPipeline:
    """Test MarketDataPipeline with mocked client."""
    
    @pytest.mark.asyncio
    async def test_get_quote_with_client(self, mock_client, test_instrument):
        """Should call client.get_quote and return real data."""
        pipeline = MarketDataPipeline(client=mock_client)
        
        quote = await pipeline.get_quote(test_instrument)
        
        assert isinstance(quote, Quote)
        assert quote.ltp == Decimal("150.50")
        assert quote.bid == Decimal("150.40")
        assert quote.ask == Decimal("150.60")
        assert quote.volume == 5000
        mock_client.get_quote.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_quote_without_client_raises(self, test_instrument):
        """Should raise RuntimeError when no client configured."""
        pipeline = MarketDataPipeline(client=None)
        
        with pytest.raises(RuntimeError, match="No broker client configured"):
            await pipeline.get_quote(test_instrument)
    
    @pytest.mark.asyncio
    async def test_get_historical_with_client(self, mock_client, test_instrument):
        """Should call client.get_historical and return candles."""
        pipeline = MarketDataPipeline(client=mock_client)
        
        candles = await pipeline.get_historical(
            test_instrument,
            from_date="2024-01-01",
            to_date="2024-01-31",
            interval="1d",
        )
        
        assert len(candles) == 1
        assert isinstance(candles[0], Candle)
        assert candles[0].close == Decimal("102.0")
        mock_client.get_historical.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_historical_without_client_raises(self, test_instrument):
        """Should raise RuntimeError when no client configured."""
        pipeline = MarketDataPipeline(client=None)
        
        with pytest.raises(RuntimeError, match="No broker client configured"):
            await pipeline.get_historical(
                test_instrument,
                from_date="2024-01-01",
                to_date="2024-01-31",
            )
    
    @pytest.mark.asyncio
    async def test_stream_simulation(self, test_instrument):
        """Should generate simulated ticks."""
        pipeline = MarketDataPipeline()
        await pipeline.start()
        
        ticks = []
        async for tick in pipeline._stream_simulation([test_instrument]):
            ticks.append(tick)
            if len(ticks) >= 3:
                break
        
        await pipeline.stop()
        
        assert len(ticks) == 3
        for tick in ticks:
            assert isinstance(tick, Tick)
            assert tick.instrument == test_instrument
            assert tick.price > 0
    
    @pytest.mark.asyncio
    async def test_stream_replay_with_client(self, mock_client, test_instrument):
        """Should replay historical data as ticks."""
        pipeline = MarketDataPipeline(client=mock_client)
        
        ticks = []
        async for tick in pipeline._stream_replay([test_instrument]):
            ticks.append(tick)
            if len(ticks) >= 1:
                break
        
        assert len(ticks) >= 1
        assert isinstance(ticks[0], Tick)
        mock_client.get_historical.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_stream_live_without_client_raises(self, test_instrument):
        """Should raise RuntimeError when no client for live stream."""
        pipeline = MarketDataPipeline(client=None)
        
        with pytest.raises(RuntimeError, match="Live streaming requires"):
            async for _ in pipeline._stream_live([test_instrument]):
                pass
    
    def test_set_replay_speed(self):
        """Should set replay speed."""
        pipeline = MarketDataPipeline()
        
        pipeline.set_replay_speed(2.0)
        
        assert pipeline._replay_speed == 2.0
    
    @pytest.mark.asyncio
    async def test_start_stop(self):
        """Should start and stop pipeline."""
        pipeline = MarketDataPipeline()
        
        await pipeline.start()
        assert pipeline._running is True
        
        await pipeline.stop()
        assert pipeline._running is False
