"""
Tests for WebSocket integration and DhanWebSocketManager.

Tests cover:
- Instrument batching
- Reconnection logic
- Tick normalization
- Depth event parsing
- Heartbeat monitoring
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from decimal import Decimal

from brokersv2.infrastructure.dhan_adapter.websocket import (
    DhanWebSocketManager,
    MAX_INSTRUMENTS_PER_SUBSCRIBE,
    MAX_RECONNECT_ATTEMPTS,
    HEARTBEAT_TIMEOUT,
)
from brokersv2.infrastructure.dhan_adapter.client import DhanConfig
from brokersv2.infrastructure.dhan_adapter.mapper import InstrumentMapper
from brokersv2.core.errors import BrokerConnectionError
from brokersv2.domain.market.models import Tick


class TestDhanWebSocketManagerInitialization:
    """Test WebSocket manager initialization."""
    
    def test_init_creates_queues(self):
        """Should create tick and depth queues with proper sizes."""
        config = Mock(spec=DhanConfig)
        mapper = Mock(spec=InstrumentMapper)
        
        manager = DhanWebSocketManager(config=config, mapper=mapper)
        
        assert manager._tick_queue.maxsize == 10000
        assert manager._depth_queue.maxsize == 5000
        assert manager._running is False
        assert manager._reconnect_attempts == 0
        assert manager._ws_client is None
    
    def test_init_initializes_state(self):
        """Should initialize all state variables."""
        config = Mock(spec=DhanConfig)
        mapper = Mock(spec=InstrumentMapper)
        
        manager = DhanWebSocketManager(config=config, mapper=mapper)
        
        assert manager._subscriptions == {}
        assert manager._receive_task is None
        assert manager._heartbeat_task is None
        assert manager._last_heartbeat is not None


class TestInstrumentBatching:
    """Test instrument batching for subscriptions."""
    
    def test_batch_instruments_under_limit(self):
        """Should return single batch if under limit."""
        config = Mock(spec=DhanConfig)
        mapper = Mock(spec=InstrumentMapper)
        manager = DhanWebSocketManager(config=config, mapper=mapper)
        
        instruments = [Mock() for _ in range(50)]
        
        batches = manager._batch_instruments(instruments)
        
        assert len(batches) == 1
        assert len(batches[0]) == 50
    
    def test_batch_instruments_exact_limit(self):
        """Should return single batch at exact limit."""
        config = Mock(spec=DhanConfig)
        mapper = Mock(spec=InstrumentMapper)
        manager = DhanWebSocketManager(config=config, mapper=mapper)
        
        instruments = [Mock() for _ in range(MAX_INSTRUMENTS_PER_SUBSCRIBE)]
        
        batches = manager._batch_instruments(instruments)
        
        assert len(batches) == 1
        assert len(batches[0]) == MAX_INSTRUMENTS_PER_SUBSCRIBE
    
    def test_batch_instruments_over_limit(self):
        """Should split into multiple batches."""
        config = Mock(spec=DhanConfig)
        mapper = Mock(spec=InstrumentMapper)
        manager = DhanWebSocketManager(config=config, mapper=mapper)
        
        instruments = [Mock() for _ in range(250)]
        
        batches = manager._batch_instruments(instruments)
        
        assert len(batches) == 3  # 100 + 100 + 50
        assert len(batches[0]) == 100
        assert len(batches[1]) == 100
        assert len(batches[2]) == 50
    
    def test_batch_instruments_empty(self):
        """Should return empty list for no instruments."""
        config = Mock(spec=DhanConfig)
        mapper = Mock(spec=InstrumentMapper)
        manager = DhanWebSocketManager(config=config, mapper=mapper)
        
        batches = manager._batch_instruments([])
        
        assert batches == []


class TestTickNormalization:
    """Test tick data parsing and normalization."""
    
    def test_parse_valid_tick(self):
        """Should parse valid tick data."""
        config = Mock(spec=DhanConfig)
        mapper = Mock(spec=InstrumentMapper)
        
        instrument = Mock()
        instrument.symbol = "RELIANCE"
        mapper.security_id_to_canonical.return_value = instrument
        
        manager = DhanWebSocketManager(config=config, mapper=mapper)
        
        raw_data = {
            "security_id": "NSE_EQ_1",
            "last_traded_price": 1500.50,
            "volume": 10000,
        }
        
        tick = manager._parse_tick(raw_data)
        
        assert tick is not None
        assert isinstance(tick, Tick)
        assert tick.price == 1500.50
        assert tick.volume == 10000
        assert tick.instrument == instrument
    
    def test_parse_tick_zero_price(self):
        """Should reject tick with zero price."""
        config = Mock(spec=DhanConfig)
        mapper = Mock(spec=InstrumentMapper)
        
        instrument = Mock()
        instrument.symbol = "RELIANCE"
        mapper.security_id_to_canonical.return_value = instrument
        
        manager = DhanWebSocketManager(config=config, mapper=mapper)
        
        raw_data = {
            "security_id": "NSE_EQ_1",
            "last_traded_price": 0.0,
            "volume": 10000,
        }
        
        tick = manager._parse_tick(raw_data)
        
        assert tick is None
    
    def test_parse_tick_unknown_security(self):
        """Should return None for unknown security ID."""
        config = Mock(spec=DhanConfig)
        mapper = Mock(spec=InstrumentMapper)
        mapper.security_id_to_canonical.return_value = None
        
        manager = DhanWebSocketManager(config=config, mapper=mapper)
        
        raw_data = {
            "security_id": "UNKNOWN",
            "last_traded_price": 1500.50,
            "volume": 10000,
        }
        
        tick = manager._parse_tick(raw_data)
        
        assert tick is None
    
    def test_parse_tick_updates_heartbeat(self):
        """Should update heartbeat timestamp on successful parse."""
        config = Mock(spec=DhanConfig)
        mapper = Mock(spec=InstrumentMapper)
        
        instrument = Mock()
        instrument.symbol = "RELIANCE"
        mapper.security_id_to_canonical.return_value = instrument
        
        manager = DhanWebSocketManager(config=config, mapper=mapper)
        old_heartbeat = manager._last_heartbeat
        
        raw_data = {
            "security_id": "NSE_EQ_1",
            "last_traded_price": 1500.50,
            "volume": 10000,
        }
        
        tick = manager._parse_tick(raw_data)
        
        assert tick is not None
        assert manager._last_heartbeat >= old_heartbeat


class TestDepthEventParsing:
    """Test depth event parsing."""
    
    def test_parse_depth_event(self):
        """Should parse depth event with bids and asks."""
        config = Mock(spec=DhanConfig)
        mapper = Mock(spec=InstrumentMapper)
        manager = DhanWebSocketManager(config=config, mapper=mapper)
        
        raw_data = {
            "security_id": "NSE_EQ_1",
            "symbol": "RELIANCE",
            "bids": [
                {"price": 2500.0, "quantity": 100, "orders": 5},
                {"price": 2499.0, "quantity": 200, "orders": 3},
            ],
            "asks": [
                {"price": 2501.0, "quantity": 150, "orders": 4},
                {"price": 2502.0, "quantity": 250, "orders": 2},
            ],
            "sequence": 123,
            "is_snapshot": True,
        }
        
        depth_event = manager._parse_depth_event(raw_data)
        
        assert depth_event is not None
        assert depth_event.symbol == "RELIANCE"
        assert depth_event.security_id == "NSE_EQ_1"
        assert depth_event.sequence == 123
        assert depth_event.is_snapshot is True
        assert len(depth_event.bids) == 2
        assert len(depth_event.asks) == 2
        
        # Check first bid
        assert depth_event.bids[0].price == 2500.0
        assert depth_event.bids[0].quantity == 100
    
    def test_parse_depth_event_limits_to_5_levels(self):
        """Should limit to top 5 levels per side."""
        config = Mock(spec=DhanConfig)
        mapper = Mock(spec=InstrumentMapper)
        manager = DhanWebSocketManager(config=config, mapper=mapper)
        
        # Create 10 levels
        bids = [{"price": 2500.0 - i, "quantity": 100, "orders": 1} for i in range(10)]
        asks = [{"price": 2501.0 + i, "quantity": 100, "orders": 1} for i in range(10)]
        
        raw_data = {
            "security_id": "NSE_EQ_1",
            "symbol": "RELIANCE",
            "bids": bids,
            "asks": asks,
            "sequence": 1,
            "is_snapshot": True,
        }
        
        depth_event = manager._parse_depth_event(raw_data)
        
        assert len(depth_event.bids) == 5
        assert len(depth_event.asks) == 5


class TestConnectionManagement:
    """Test WebSocket connection lifecycle."""
    
    @pytest.mark.asyncio
    async def test_start_creates_client(self):
        """Should create DhanFeed client and connect."""
        config = Mock(spec=DhanConfig)
        config.client_id = "test_client"
        config.access_token = "test_token"
        
        mapper = Mock(spec=InstrumentMapper)
        
        with patch('brokersv2.infrastructure.dhan_adapter.websocket.marketfeed') as mock_marketfeed:
            mock_client = AsyncMock()
            mock_client.connect = AsyncMock()
            mock_marketfeed.DhanFeed.return_value = mock_client
            
            manager = DhanWebSocketManager(config=config, mapper=mapper)
            
            # Mock create_task to avoid actual task creation
            with patch('asyncio.create_task'):
                await manager.start()
            
            mock_marketfeed.DhanFeed.assert_called_once_with(
                client_id="test_client",
                access_token="test_token",
                default_symbols=[],
            )
            mock_client.connect.assert_called_once()
            assert manager._running is True
            assert manager._reconnect_attempts == 0
    
    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self):
        """Should cancel background tasks and disconnect."""
        config = Mock(spec=DhanConfig)
        mapper = Mock(spec=InstrumentMapper)
        
        manager = DhanWebSocketManager(config=config, mapper=mapper)
        manager._running = True
        
        # Create mock tasks that can be awaited
        async def mock_task_coro():
            try:
                await asyncio.sleep(100)  # Long sleep
            except asyncio.CancelledError:
                raise asyncio.CancelledError()
        
        mock_receive_task = asyncio.create_task(mock_task_coro())
        mock_heartbeat_task = asyncio.create_task(mock_task_coro())
        
        # Store original cancel for verification
        original_receive_cancel = mock_receive_task.cancel
        original_heartbeat_cancel = mock_heartbeat_task.cancel
        
        manager._receive_task = mock_receive_task
        manager._heartbeat_task = mock_heartbeat_task
        
        # Mock WS client
        mock_ws_client = AsyncMock()
        mock_ws_client.disconnect = AsyncMock()
        manager._ws_client = mock_ws_client
        
        await manager.stop()
        
        # Verify running is False and ws_client is None
        assert manager._running is False
        assert manager._ws_client is None
        
        # Verify tasks were cancelled (they should be done now)
        assert mock_receive_task.done()
        assert mock_heartbeat_task.done()
    
    @pytest.mark.asyncio
    async def test_subscribe_batches_instruments(self):
        """Should batch instruments during subscription."""
        config = Mock(spec=DhanConfig)
        mapper = Mock(spec=InstrumentMapper)
        
        manager = DhanWebSocketManager(config=config, mapper=mapper)
        manager._running = True
        manager._ws_client = AsyncMock()
        manager._ws_client.subscribe = AsyncMock()
        
        # Create 250 instruments
        instruments = []
        for i in range(250):
            inst = Mock()
            inst.internal_uid = f"inst_{i}"
            instruments.append(inst)
        
        # Configure mapper.canonical_to_broker_mapping to return different values
        def mock_canonical_to_broker_mapping(inst):
            return {'broker_symbol': f"broker_{inst.internal_uid}"}
        
        mapper.canonical_to_broker_mapping.side_effect = mock_canonical_to_broker_mapping
        
        await manager.subscribe(instruments)
        
        # Should be called 3 times (100 + 100 + 50)
        assert manager._ws_client.subscribe.call_count == 3
        assert len(manager._subscriptions) == 250
    
    @pytest.mark.asyncio
    async def test_subscribe_empty_list(self):
        """Should handle empty instrument list gracefully."""
        config = Mock(spec=DhanConfig)
        mapper = Mock(spec=InstrumentMapper)
        
        manager = DhanWebSocketManager(config=config, mapper=mapper)
        manager._running = True
        manager._ws_client = AsyncMock()
        
        await manager.subscribe([])
        
        # Should not call subscribe
        manager._ws_client.subscribe.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_subscribe_without_connection(self):
        """Should raise error if not connected."""
        config = Mock(spec=DhanConfig)
        mapper = Mock(spec=InstrumentMapper)
        
        manager = DhanWebSocketManager(config=config, mapper=mapper)
        manager._ws_client = None
        
        with pytest.raises(BrokerConnectionError, match="WebSocket not connected"):
            await manager.subscribe([Mock()])


class TestHealthMonitoring:
    """Test heartbeat and health monitoring."""
    
    def test_is_connected_true(self):
        """Should return True when connected."""
        config = Mock(spec=DhanConfig)
        mapper = Mock(spec=InstrumentMapper)
        
        manager = DhanWebSocketManager(config=config, mapper=mapper)
        manager._running = True
        manager._ws_client = Mock()
        
        assert manager.is_connected is True
    
    def test_is_connected_false_not_running(self):
        """Should return False when not running."""
        config = Mock(spec=DhanConfig)
        mapper = Mock(spec=InstrumentMapper)
        
        manager = DhanWebSocketManager(config=config, mapper=mapper)
        manager._running = False
        manager._ws_client = Mock()
        
        assert manager.is_connected is False
    
    def test_is_connected_false_no_client(self):
        """Should return False when no client."""
        config = Mock(spec=DhanConfig)
        mapper = Mock(spec=InstrumentMapper)
        
        manager = DhanWebSocketManager(config=config, mapper=mapper)
        manager._running = True
        manager._ws_client = None
        
        assert manager.is_connected is False


class TestQueueManagement:
    """Test tick and depth queue management."""
    
    @pytest.mark.asyncio
    async def test_tick_queue_full_drops_tick(self):
        """Should drop tick when queue is full."""
        config = Mock(spec=DhanConfig)
        mapper = Mock(spec=InstrumentMapper)
        
        instrument = Mock()
        instrument.symbol = "RELIANCE"
        mapper.security_id_to_canonical.return_value = instrument
        
        manager = DhanWebSocketManager(config=config, mapper=mapper)
        
        # Fill the queue
        for _ in range(10000):
            manager._tick_queue.put_nowait(Mock())
        
        # Try to add another (should not raise)
        raw_data = {
            "security_id": "NSE_EQ_1",
            "last_traded_price": 1500.50,
            "volume": 10000,
        }
        
        # Should not raise QueueFull
        manager._handle_tick(raw_data)
        
        # Queue should still be at maxsize
        assert manager._tick_queue.qsize() == 10000
    
    def test_subscription_count(self):
        """Should track subscription count."""
        config = Mock(spec=DhanConfig)
        mapper = Mock(spec=InstrumentMapper)
        
        manager = DhanWebSocketManager(config=config, mapper=mapper)
        
        # Add subscriptions
        inst1 = Mock()
        inst1.internal_uid = "inst_1"
        inst2 = Mock()
        inst2.internal_uid = "inst_2"
        
        manager._subscriptions["inst_1"] = inst1
        manager._subscriptions["inst_2"] = inst2
        
        assert manager.subscription_count == 2
