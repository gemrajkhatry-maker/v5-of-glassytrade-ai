"""Tests for WebSocket Connection Manager."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta

from brokersv2.websocket.connection.manager import (
    WebSocketConnectionManager,
    ConnectionHealth,
    ConnectionState,
)
from brokersv2.core.errors import BrokerConnectionError


class TestConnectionHealth:
    """Tests for ConnectionHealth dataclass."""

    def test_initial_health(self):
        """Test initial health state."""
        health = ConnectionHealth(connection_id=1)
        
        assert health.health_score == 1.0
        assert health.is_healthy is True
        assert health.last_heartbeat is not None

    def test_health_degrades_on_stale_heartbeat(self):
        """Test health score decreases with stale heartbeat."""
        health = ConnectionHealth(connection_id=1)
        
        # Set heartbeat to 15 seconds ago
        health.last_heartbeat = datetime.now() - timedelta(seconds=15)
        health.update_health_score(stale_threshold=20)
        
        # Should still be healthy (< 20s)
        assert health.is_healthy is True

    def test_health_zombie_detection(self):
        """Test zombie socket detection (> 20s stale)."""
        health = ConnectionHealth(connection_id=1)
        
        # Set heartbeat to 25 seconds ago (zombie!)
        health.last_heartbeat = datetime.now() - timedelta(seconds=25)
        health.update_health_score(stale_threshold=20)
        
        assert health.is_healthy is False
        assert health.health_score < 0.5

    def test_health_recovery(self):
        """Test health recovers after fresh heartbeat."""
        health = ConnectionHealth(connection_id=1)
        health.last_heartbeat = datetime.now() - timedelta(seconds=25)
        health.update_health_score(stale_threshold=20)
        
        # Fresh heartbeat
        health.last_heartbeat = datetime.now()
        health.update_health_score(stale_threshold=20)
        
        assert health.is_healthy is True
        assert health.health_score == 1.0


class TestWebSocketConnectionManager:
    """Tests for WebSocketConnectionManager."""

    @pytest.fixture
    def manager(self):
        """Create connection manager."""
        return WebSocketConnectionManager(max_connections=5)

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        reason="WebSocketConnectionManager is a deprecated placeholder — "
               "_create_connection raises RuntimeError instead of using AsyncMock. "
               "Use DhanWebSocketManager for real connections.",
        strict=True,
    )
    async def test_start_manager(self, manager):
        """Placeholder: start() now raises BrokerConnectionError (deprecated manager)."""
        await manager.start(num_connections=3)
        assert manager.is_running is True
        assert manager.active_connections == 3

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        reason="WebSocketConnectionManager is a deprecated placeholder.",
        strict=True,
    )
    async def test_stop_manager(self, manager):
        """Placeholder: start() now raises BrokerConnectionError (deprecated manager)."""
        await manager.start(num_connections=2)
        await manager.stop()
        assert manager.is_running is False
        assert manager.active_connections == 0

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        reason="WebSocketConnectionManager is a deprecated placeholder.",
        strict=True,
    )
    async def test_subscribe_instruments(self, manager):
        """Placeholder: start() now raises BrokerConnectionError (deprecated manager)."""
        await manager.start(num_connections=1)
        instruments = [
            Mock(internal_uid="inst_1", symbol="RELIANCE"),
            Mock(internal_uid="inst_2", symbol="TCS"),
        ]
        await manager.subscribe(instruments)
        assert len(manager._subscriptions) == 2

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        reason="WebSocketConnectionManager is a deprecated placeholder.",
        strict=True,
    )
    async def test_unsubscribe_instruments(self, manager):
        """Placeholder: start() now raises BrokerConnectionError (deprecated manager)."""
        await manager.start(num_connections=1)
        instruments = [Mock(internal_uid="inst_1", symbol="RELIANCE")]
        await manager.subscribe(instruments)
        await manager.unsubscribe(instruments)
        assert len(manager._subscriptions) == 0

    def test_max_connections_enforcement(self):
        """Test max connections limit (5)."""
        manager = WebSocketConnectionManager(max_connections=5)
        
        # Should reject > 5 connections
        with pytest.raises(ValueError, match="Must have 1-5 connections"):
            manager._validate_connection_count(6)

    def test_connection_health_tracking(self, manager):
        """Test health score tracking."""
        health = ConnectionHealth(connection_id=1)
        manager._connection_health[1] = health
        
        scores = manager.get_connection_health()
        
        assert 1 in scores
        assert scores[1].health_score == 1.0

    def test_instrument_sharding(self, manager):
        """Test instrument sharding across connections."""
        manager._running = True
        
        # Add 2 connections
        manager._connections[0] = AsyncMock()
        manager._connections[1] = AsyncMock()
        manager._connection_health[0] = ConnectionHealth(connection_id=0)
        manager._connection_health[1] = ConnectionHealth(connection_id=1)
        
        # Create 150 instruments
        instruments = [
            Mock(internal_uid=f"inst_{i}")
            for i in range(150)
        ]
        
        shards = manager._shard_instruments(instruments)
        
        # All instruments should be assigned to a connection
        total = sum(len(insts) for insts in shards.values())
        assert total == 150
        # Should use at least 1 connection
        assert len(shards) >= 1

    def test_zombie_socket_detection(self, manager):
        """Test zombie socket detection."""
        # Add healthy connection
        health1 = ConnectionHealth(connection_id=0)
        health1.last_heartbeat = datetime.now()
        manager._connection_health[0] = health1
        manager._connections[0] = AsyncMock()
        
        # Add zombie connection (25s stale)
        health2 = ConnectionHealth(connection_id=1)
        health2.last_heartbeat = datetime.now() - timedelta(seconds=25)
        manager._connection_health[1] = health2
        manager._connections[1] = AsyncMock()
        
        zombies = manager._detect_zombies(stale_threshold=20)
        
        assert len(zombies) == 1
        assert 1 in zombies

    @pytest.mark.asyncio
    async def test_reconnect_zombie_connections(self, manager):
        """Test reconnecting zombie connections."""
        manager._running = True
        
        # Add zombie connection
        health = ConnectionHealth(connection_id=1)
        health.last_heartbeat = datetime.now() - timedelta(seconds=25)
        manager._connection_health[1] = health
        manager._connections[1] = AsyncMock()
        
        with patch.object(manager, '_reconnect_connection', new_callable=AsyncMock) as mock_reconnect:
            await manager._reconnect_zombies(stale_threshold=20)
            
            mock_reconnect.assert_called_once_with(1)

    def test_get_healthiest_connection(self, manager):
        """Test selecting healthiest connection."""
        health1 = ConnectionHealth(connection_id=0)
        health1.health_score = 0.8
        manager._connection_health[0] = health1
        
        health2 = ConnectionHealth(connection_id=1)
        health2.health_score = 0.95
        manager._connection_health[1] = health2
        
        best = manager._get_healthiest_connection()
        
        assert best == 1

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        reason="WebSocketConnectionManager is a deprecated placeholder.",
        strict=True,
    )
    async def test_subscription_recovery_on_reconnect(self, manager):
        """Placeholder: start() now raises BrokerConnectionError (deprecated manager)."""
        await manager.start(num_connections=1)
        inst = Mock(internal_uid="inst_1", symbol="RELIANCE")
        await manager.subscribe([inst])
        await manager._reconnect_connection(0)
        assert manager.is_running is True
        assert manager.active_connections == 1

    def test_connection_state_tracking(self, manager):
        """Test connection state management."""
        manager._connection_states[0] = ConnectionState.CONNECTED
        
        assert manager.is_connection_healthy(0) is True
        
        manager._connection_states[0] = ConnectionState.DISCONNECTED
        assert manager.is_connection_healthy(0) is False

    @pytest.mark.asyncio
    async def test_graceful_shutdown(self, manager):
        """Test graceful shutdown with cleanup."""
        manager._running = True
        manager._connections[0] = AsyncMock()
        
        await manager.stop()
        
        assert manager.is_running is False
        assert len(manager._connections) == 0

    def test_manager_not_running_raises_error(self, manager):
        """Test operations fail when manager not running."""
        instruments = [Mock(internal_uid="inst_1")]
        
        with pytest.raises(BrokerConnectionError, match="Manager not running"):
            import asyncio
            asyncio.run(manager.subscribe(instruments))

    def test_statistics_tracking(self, manager):
        """Test statistics collection."""
        manager._stats["messages_received"] = 100
        manager._stats["reconnections"] = 2
        
        stats = manager.get_statistics()
        
        assert stats["messages_received"] == 100
        assert stats["reconnections"] == 2
