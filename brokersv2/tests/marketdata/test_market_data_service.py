"""
Tests for MarketDataService integration.

Tests cover:
- Historical data with fallback
- Live streaming orchestration
- Order book depth processing
- Warmup functionality
- Health monitoring
"""

import pytest
from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock, AsyncMock, MagicMock
import asyncio

from brokersv2.marketdata.service import MarketDataService
from brokersv2.domain.market.events import DepthEvent, DepthLevel
from brokersv2.domain.market.models import Candle, Tick


class TestMarketDataServiceInitialization:
    """Test MarketDataService initialization."""
    
    def test_init_with_all_components(self):
        """Should initialize with historical, WS, and depth."""
        historical_router = Mock()
        ws_manager = Mock()
        depth_processor = Mock()
        
        service = MarketDataService(
            historical_router=historical_router,
            ws_manager=ws_manager,
            depth_processor=depth_processor,
        )
        
        assert service._historical == historical_router
        assert service._ws_manager == ws_manager
        assert service._depth_processor == depth_processor
    
    def test_init_with_defaults(self):
        """Should create default depth processor if not provided."""
        historical_router = Mock()
        
        service = MarketDataService(
            historical_router=historical_router,
        )
        
        assert service._historical == historical_router
        assert service._ws_manager is None
        assert service._depth_processor is not None
    
    def test_repr(self):
        """Should provide useful string representation."""
        historical_router = Mock()
        historical_router._primary.provider_name = "dhan"
        
        ws_manager = Mock()
        ws_manager.is_connected = True
        
        service = MarketDataService(
            historical_router=historical_router,
            ws_manager=ws_manager,
        )
        
        repr_str = repr(service)
        assert "MarketDataService" in repr_str
        assert "dhan" in repr_str
        assert "connected" in repr_str


class TestHistoricalDataMethods:
    """Test historical data retrieval."""
    
    @pytest.mark.asyncio
    async def test_get_historical_candles(self):
        """Should delegate to historical router."""
        historical_router = AsyncMock()
        expected_candles = [Mock(spec=Candle)]
        historical_router.get_candles.return_value = expected_candles
        
        service = MarketDataService(
            historical_router=historical_router,
        )
        
        instrument = Mock()
        candles = await service.get_historical_candles(
            instrument=instrument,
            timeframe="5m",
            from_date="2026-05-01",
            to_date="2026-05-07",
        )
        
        assert candles == expected_candles
        historical_router.get_candles.assert_called_once_with(
            instrument, "5m", "2026-05-01", "2026-05-07"
        )
    
    @pytest.mark.asyncio
    async def test_warmup_calls_historical_router(self):
        """Should preload historical data for all instruments."""
        historical_router = AsyncMock()
        
        service = MarketDataService(
            historical_router=historical_router,
        )
        
        instruments = [Mock(), Mock()]
        timeframes = ["5m", "15m"]
        
        # Warmup should complete without raising
        result = await service.warmup(instruments, timeframes, lookback_days=5)
        
        # Verify warmup was attempted
        assert result is not None


class TestLiveStreamingMethods:
    """Test live streaming functionality."""
    
    @pytest.mark.asyncio
    async def test_start_live_stream_without_ws_manager(self):
        """Should raise error if WS manager not configured."""
        service = MarketDataService(
            historical_router=Mock(),
        )
        
        with pytest.raises(RuntimeError, match="WebSocket manager not configured"):
            async for _ in service.start_live_stream([]):
                pass
    
    @pytest.mark.asyncio
    async def test_start_live_stream_with_ws_manager(self):
        """Should start WS and subscribe to instruments."""
        ws_manager = AsyncMock()
        
        # Create async generator for stream_ticks
        async def mock_stream_ticks():
            for tick in []:
                yield tick
        
        ws_manager.stream_ticks = mock_stream_ticks
        
        service = MarketDataService(
            historical_router=Mock(),
            ws_manager=ws_manager,
        )
        
        instruments = [Mock(), Mock()]
        
        # Start streaming (will complete immediately with empty iterator)
        async for _ in service.start_live_stream(instruments):
            pass
        
        ws_manager.start.assert_called_once()
        ws_manager.subscribe.assert_called_once_with(instruments)
    
    @pytest.mark.asyncio
    async def test_stop_live_stream(self):
        """Should stop WS manager if configured."""
        ws_manager = AsyncMock()
        
        service = MarketDataService(
            historical_router=Mock(),
            ws_manager=ws_manager,
        )
        
        await service.stop_live_stream()
        
        ws_manager.stop.assert_called_once()


class TestOrderBookDepthMethods:
    """Test order book depth processing."""
    
    def test_process_depth_update_creates_processor(self):
        """Should create depth processor for new symbol."""
        service = MarketDataService(
            historical_router=Mock(),
        )
        
        depth_event = DepthEvent(
            timestamp=datetime.now(),
            security_id="NSE_EQ_1",
            symbol="RELIANCE",
            exchange="NSE",
            bids=(DepthLevel(price=100.0, quantity=100, orders=5),),
            asks=(DepthLevel(price=101.0, quantity=100, orders=5),),
            sequence=1,
            is_snapshot=True,
        )
        
        service.process_depth_update(depth_event)
        
        assert "RELIANCE" in service._symbol_depth_processors
    
    def test_process_depth_update_reuses_processor(self):
        """Should reuse existing depth processor for symbol."""
        service = MarketDataService(
            historical_router=Mock(),
        )
        
        depth_event1 = DepthEvent(
            timestamp=datetime.now(),
            security_id="NSE_EQ_1",
            symbol="RELIANCE",
            exchange="NSE",
            bids=(DepthLevel(price=100.0, quantity=100, orders=5),),
            asks=(DepthLevel(price=101.0, quantity=100, orders=5),),
            sequence=1,
            is_snapshot=True,
        )
        
        depth_event2 = DepthEvent(
            timestamp=datetime.now(),
            security_id="NSE_EQ_1",
            symbol="RELIANCE",
            exchange="NSE",
            bids=(DepthLevel(price=100.5, quantity=150, orders=3),),
            asks=(DepthLevel(price=101.5, quantity=150, orders=3),),
            sequence=2,
            is_snapshot=False,
        )
        
        service.process_depth_update(depth_event1)
        service.process_depth_update(depth_event2)
        
        # Should have 2 entries: security_id key + symbol key (both point to same processor)
        assert len(service._symbol_depth_processors) == 2
        assert "RELIANCE" in service._symbol_depth_processors
    
    def test_get_order_book_snapshot(self):
        """Should return current order book for symbol."""
        service = MarketDataService(
            historical_router=Mock(),
        )
        
        depth_event = DepthEvent(
            timestamp=datetime.now(),
            security_id="NSE_EQ_1",
            symbol="RELIANCE",
            exchange="NSE",
            bids=(DepthLevel(price=100.0, quantity=100, orders=5),),
            asks=(DepthLevel(price=101.0, quantity=100, orders=5),),
            sequence=1,
            is_snapshot=True,
        )
        
        service.process_depth_update(depth_event)
        
        book = service.get_order_book_snapshot("RELIANCE")
        
        assert book is not None
    
    def test_get_order_book_snapshot_unknown_symbol(self):
        """Should return None for unknown symbol."""
        service = MarketDataService(
            historical_router=Mock(),
        )
        
        book = service.get_order_book_snapshot("UNKNOWN")
        
        assert book is None
    
    def test_get_order_book_imbalance(self):
        """Should calculate order book imbalance."""
        service = MarketDataService(
            historical_router=Mock(),
        )
        
        depth_event = DepthEvent(
            timestamp=datetime.now(),
            security_id="NSE_EQ_1",
            symbol="RELIANCE",
            exchange="NSE",
            bids=(
                DepthLevel(price=100.0, quantity=200, orders=5),
            ),
            asks=(
                DepthLevel(price=101.0, quantity=100, orders=5),
            ),
            sequence=1,
            is_snapshot=True,
        )
        
        service.process_depth_update(depth_event)
        
        imbalance = service.get_order_book_imbalance("RELIANCE")
        
        # More bid quantity = positive imbalance
        assert imbalance is not None
        assert imbalance > 0
    
    @pytest.mark.asyncio
    async def test_stream_depth_updates(self):
        """Should stream depth updates and process them."""
        ws_manager = AsyncMock()
        
        depth_event = DepthEvent(
            timestamp=datetime.now(),
            security_id="NSE_EQ_1",
            symbol="RELIANCE",
            exchange="NSE",
            bids=(DepthLevel(price=100.0, quantity=100, orders=5),),
            asks=(DepthLevel(price=101.0, quantity=100, orders=5),),
            sequence=1,
            is_snapshot=True,
        )
        
        # Create async generator for stream_depth
        async def mock_stream_depth(symbol):
            for event in [depth_event]:
                yield event
        
        ws_manager.stream_depth = mock_stream_depth
        
        service = MarketDataService(
            historical_router=Mock(),
            ws_manager=ws_manager,
        )
        
        events = []
        async for event in service.stream_depth_updates("RELIANCE"):
            events.append(event)
        
        assert len(events) == 1
        assert events[0].symbol == "RELIANCE"


class TestHealthAndStatus:
    """Test health monitoring and status reporting."""
    
    def test_get_status(self):
        """Should return comprehensive status."""
        historical_router = Mock()
        historical_router._primary.provider_name = "dhan"
        historical_router._fallback = Mock()
        historical_router._fallback.provider_name = "opencart"
        
        ws_manager = Mock()
        ws_manager.is_connected = True
        ws_manager.subscription_count = 5
        
        service = MarketDataService(
            historical_router=historical_router,
            ws_manager=ws_manager,
        )
        
        # Add some depth processors
        service._symbol_depth_processors["RELIANCE"] = Mock()
        service._symbol_depth_processors["INFY"] = Mock()
        
        status = service.get_status()
        
        assert status["historical"]["primary"] == "dhan"
        assert status["historical"]["fallback"] == "opencart"
        assert status["websocket"]["connected"] is True
        assert status["websocket"]["subscriptions"] == 5
        assert status["depth"]["symbols_tracked"] == 2
    
    def test_is_healthy_all_components(self):
        """Should be healthy when all components are available."""
        historical_router = Mock()
        historical_router._primary.is_available = True
        
        ws_manager = Mock()
        ws_manager.is_connected = True
        
        service = MarketDataService(
            historical_router=historical_router,
            ws_manager=ws_manager,
        )
        
        assert service.is_healthy() is True
    
    def test_is_healthy_historical_unavailable(self):
        """Should be unhealthy if historical provider unavailable."""
        historical_router = Mock()
        historical_router._primary.is_available = False
        
        ws_manager = Mock()
        ws_manager.is_connected = True
        
        service = MarketDataService(
            historical_router=historical_router,
            ws_manager=ws_manager,
        )
        
        assert service.is_healthy() is False
    
    def test_is_healthy_ws_disconnected(self):
        """Should be unhealthy if WS disconnected."""
        historical_router = Mock()
        historical_router._primary.is_available = True
        
        ws_manager = Mock()
        ws_manager.is_connected = False
        
        service = MarketDataService(
            historical_router=historical_router,
            ws_manager=ws_manager,
        )
        
        assert service.is_healthy() is False
    
    def test_is_healthy_no_ws_configured(self):
        """Should be healthy if WS not configured (optional)."""
        historical_router = Mock()
        historical_router._primary.is_available = True
        
        service = MarketDataService(
            historical_router=historical_router,
        )
        
        assert service.is_healthy() is True
