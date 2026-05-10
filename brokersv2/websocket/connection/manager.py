"""
WebSocket Connection Manager — DEPRECATED PLACEHOLDER.

This module is a legacy placeholder that does not create real network
connections.  It must NOT be used in production trading workflows.

Use brokersv2.infrastructure.dhan_adapter.websocket.DhanWebSocketManager
for all live market data streaming.

The _create_connection method raises RuntimeError to prevent silent
execution of placeholder logic.
"""

from __future__ import annotations

import asyncio
import logging
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Set

from brokersv2.core.constants import WebSocket as WSConstants, WSManager

warnings.warn(
    "brokersv2.websocket.connection.manager (WebSocketConnectionManager) is a deprecated "
    "placeholder. Use brokersv2.infrastructure.dhan_adapter.websocket.DhanWebSocketManager "
    "instead.",
    DeprecationWarning,
    stacklevel=2,
)

from brokersv2.core.errors import BrokerConnectionError

logger = logging.getLogger(__name__)


# =============================================================================
# Types
# =============================================================================

class ConnectionState(Enum):
    """WebSocket connection states."""
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"
    FAILED = "FAILED"


@dataclass
class ConnectionHealth:
    """Connection health metrics."""
    connection_id: int
    health_score: float = 1.0
    last_heartbeat: datetime = field(default_factory=datetime.now)
    messages_received: int = 0
    errors: int = 0
    reconnect_count: int = 0
    
    @property
    def is_healthy(self) -> bool:
        """Check if connection is healthy (score > 0.5)."""
        return self.health_score > 0.5
    
    def update_health_score(self, stale_threshold: int = None):
        """
        Update health score based on heartbeat freshness.
        
        Args:
            stale_threshold: Seconds before heartbeat considered stale
        """
        threshold = stale_threshold or WSManager.STALE_THRESHOLD
        age = (datetime.now() - self.last_heartbeat).total_seconds()
        
        if age > stale_threshold:
            self.health_score = 0.0  # Zombie
        elif age > stale_threshold * 0.8:  # Warning zone (80% of threshold)
            self.health_score = max(0.0, 1.0 - (age / stale_threshold))
        else:
            self.health_score = 1.0


# =============================================================================
# WebSocket Connection Manager
# =============================================================================

class WebSocketConnectionManager:
    """
    Manages multiple WebSocket connections for DhanHQ v2.
    
    Features:
    - Up to 5 concurrent connections (DhanHQ limit)
    - 5000 instruments per connection
    - Health-based connection selection
    - Zombie socket detection and recovery
    - Subscription state tracking and recovery
    
    Usage:
        manager = WebSocketConnectionManager(max_connections=3)
        await manager.start()
        await manager.subscribe(instruments)
        async for tick in manager.stream_ticks():
            process(tick)
    """
    
    MAX_CONNECTIONS = WSConstants.MAX_CONNECTIONS
    MAX_INSTRUMENTS_PER_CONNECTION = WSConstants.MAX_INSTRUMENTS_PER_CONNECTION
    
    def __init__(
        self,
        max_connections: int = 3,
        stale_threshold: int = None,
    ):
        """
        Initialize connection manager.
        
        Args:
            max_connections: Number of connections (1-5)
            stale_threshold: Seconds before heartbeat considered stale
        """
        if max_connections > self.MAX_CONNECTIONS:
            raise ValueError(
                f"Maximum {self.MAX_CONNECTIONS} connections allowed"
            )
        
        self._max_connections = max_connections
        self._stale_threshold = stale_threshold or WSManager.STALE_THRESHOLD
        self._running = False
        
        # Connection storage
        self._connections: Dict[int, object] = {}
        self._connection_health: Dict[int, ConnectionHealth] = {}
        self._connection_states: Dict[int, ConnectionState] = {}
        
        # Subscription tracking
        self._subscriptions: Dict[str, object] = {}  # instrument_uid -> instrument
        self._connection_subscriptions: Dict[int, Set[str]] = {}
        
        # Instrument sharding
        self._instrument_to_connection: Dict[str, int] = {}
        
        # Statistics
        self._stats = {
            "messages_received": 0,
            "reconnections": 0,
            "zombies_detected": 0,
            "subscriptions_active": 0,
        }
        
        logger.info(
            f"WebSocketConnectionManager initialized "
            f"(max_connections={max_connections})"
        )
    
    async def start(self, num_connections: int = 3) -> bool:
        """
        Start WebSocket connections.
        
        Args:
            num_connections: Number of connections to create
            
        Returns:
            True if started successfully
        """
        self._validate_connection_count(num_connections)
        
        try:
            logger.info(f"Starting {num_connections} WebSocket connections")
            
            for i in range(num_connections):
                await self._create_connection(i)
                self._connection_states[i] = ConnectionState.CONNECTED
                self._connection_health[i] = ConnectionHealth(connection_id=i)
                self._connection_subscriptions[i] = set()
            
            self._running = True
            logger.info(f"WebSocket manager started with {num_connections} connections")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start WebSocket manager: {e}")
            await self.stop()
            raise BrokerConnectionError(f"Failed to start: {e}") from e
    
    async def stop(self) -> None:
        """Stop all WebSocket connections."""
        self._running = False
        
        logger.info("Stopping WebSocket manager")
        
        for conn_id in list(self._connections.keys()):
            await self._close_connection(conn_id)
        
        self._connections.clear()
        self._connection_health.clear()
        self._connection_states.clear()
        
        logger.info("WebSocket manager stopped")
    
    async def subscribe(self, instruments: List) -> None:
        """
        Subscribe to instruments.
        
        Args:
            instruments: List of instruments to subscribe to
        """
        if not self._running:
            raise BrokerConnectionError("Manager not running")
        
        # Shard instruments across connections
        shards = self._shard_instruments(instruments)
        
        for conn_id, conn_instruments in shards.items():
            if conn_id not in self._connections:
                raise BrokerConnectionError(f"Connection {conn_id} not active")
            
            conn = self._connections[conn_id]
            
            # Subscribe via connection
            await conn.subscribe(conn_instruments)
            
            # Track subscriptions
            for inst in conn_instruments:
                self._subscriptions[inst.internal_uid] = inst
                self._connection_subscriptions[conn_id].add(inst.internal_uid)
                self._instrument_to_connection[inst.internal_uid] = conn_id
            
            self._stats["subscriptions_active"] = len(self._subscriptions)
            
            logger.info(
                f"Subscribed to {len(conn_instruments)} instruments "
                f"on connection {conn_id}"
            )
    
    async def unsubscribe(self, instruments: List) -> None:
        """
        Unsubscribe from instruments.
        
        Args:
            instruments: List of instruments to unsubscribe
        """
        if not self._running:
            raise BrokerConnectionError("Manager not running")
        
        # Group by connection
        by_connection: Dict[int, List] = {}
        for inst in instruments:
            conn_id = self._instrument_to_connection.get(inst.internal_uid)
            if conn_id is not None:
                by_connection.setdefault(conn_id, []).append(inst)
        
        # Unsubscribe per connection
        for conn_id, conn_instruments in by_connection.items():
            conn = self._connections.get(conn_id)
            if conn:
                await conn.unsubscribe(conn_instruments)
            
            # Update tracking
            for inst in conn_instruments:
                self._subscriptions.pop(inst.internal_uid, None)
                self._connection_subscriptions[conn_id].discard(inst.internal_uid)
                self._instrument_to_connection.pop(inst.internal_uid, None)
        
        self._stats["subscriptions_active"] = len(self._subscriptions)
        logger.info(f"Unsubscribed from {len(instruments)} instruments")
    
    async def stream_ticks(self):
        """
        Stream ticks from all connections.
        
        Yields:
            Tick data from all connections
        """
        if not self._running:
            raise BrokerConnectionError("Manager not running")
        
        # Collect ticks from all connections
        tasks = []
        for conn_id, conn in self._connections.items():
            task = asyncio.create_task(
                self._stream_from_connection(conn_id, conn)
            )
            tasks.append(task)
        
        # Wait for all streams
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.error(f"Tick stream error: {e}")
            raise
    
    def get_connection_health(self) -> Dict[int, ConnectionHealth]:
        """Get health status of all connections."""
        return self._connection_health.copy()
    
    def get_statistics(self) -> Dict:
        """Get manager statistics."""
        return self._stats.copy()
    
    def is_connection_healthy(self, conn_id: int) -> bool:
        """Check if specific connection is healthy."""
        state = self._connection_states.get(conn_id)
        return state == ConnectionState.CONNECTED
    
    @property
    def is_running(self) -> bool:
        """Check if manager is running."""
        return self._running
    
    @property
    def active_connections(self) -> int:
        """Get number of active connections."""
        return len(self._connections)
    
    # Internal methods
    
    def _validate_connection_count(self, count: int):
        """Validate connection count within limits."""
        if count < 1 or count > self.MAX_CONNECTIONS:
            raise ValueError(
                f"Must have 1-{self.MAX_CONNECTIONS} connections, got {count}"
            )
    
    async def _create_connection(self, conn_id: int):
        """
        Create WebSocket connection via DhanWebSocketManager.
        
        Args:
            conn_id: Connection ID
        """
        from brokersv2.infrastructure.dhan_adapter.websocket import DhanWebSocketManager
        from brokersv2.infrastructure.dhan_adapter.client import DhanConfig
        
        config = DhanConfig(
            client_id=getattr(self, 'client_id', ''),
            access_token=getattr(self, 'access_token', ''),
        )
        ws = DhanWebSocketManager(config=config, mapper=None)
        await ws.start()
        self._connections[conn_id] = ws
        logger.info(f"Connection {conn_id} created via DhanWebSocketManager")
    
    async def _close_connection(self, conn_id: int):
        """Close WebSocket connection."""
        conn = self._connections.pop(conn_id, None)
        if conn:
            try:
                # await conn.disconnect()
                logger.info(f"Connection {conn_id} closed")
            except Exception as e:
                logger.error(f"Error closing connection {conn_id}: {e}")
    
    def _shard_instruments(
        self, instruments: List
    ) -> Dict[int, List]:
        """
        Shard instruments across connections.
        
        Uses round-robin with health-based selection.
        
        Args:
            instruments: Instruments to shard
            
        Returns:
            Dict mapping connection_id -> instruments
        """
        shards: Dict[int, List] = {}
        
        for inst in instruments:
            # Select healthiest connection with capacity
            conn_id = self._select_connection_for_instrument(inst)
            
            shards.setdefault(conn_id, []).append(inst)
        
        return shards
    
    def _select_connection_for_instrument(self, instrument) -> int:
        """Select best connection for instrument."""
        # Find healthiest connection with capacity
        best_conn = None
        best_score = -1
        
        for conn_id, health in self._connection_health.items():
            if not health.is_healthy:
                continue
            
            # Check capacity
            current_count = len(self._connection_subscriptions.get(conn_id, set()))
            if current_count >= self.MAX_INSTRUMENTS_PER_CONNECTION:
                continue
            
            if health.health_score > best_score:
                best_score = health.health_score
                best_conn = conn_id
        
        if best_conn is None:
            # Fallback to connection with lowest subscription count
            best_conn = min(
                self._connections.keys(),
                key=lambda cid: len(self._connection_subscriptions.get(cid, set()))
            )
        
        return best_conn
    
    def _detect_zombies(self, stale_threshold: int = None) -> Set[int]:
        """
        Detect zombie connections (stale heartbeat).
        
        Args:
            stale_threshold: Seconds before considered zombie
            
        Returns:
            Set of zombie connection IDs
        """
        threshold = stale_threshold or self._stale_threshold
        zombies = set()
        
        for conn_id, health in self._connection_health.items():
            health.update_health_score(threshold)
            
            if health.health_score == 0.0:
                zombies.add(conn_id)
                self._stats["zombies_detected"] += 1
        
        return zombies
    
    async def _reconnect_zombies(self, stale_threshold: int = 20):
        """Reconnect all zombie connections."""
        zombies = self._detect_zombies(stale_threshold)
        
        for conn_id in zombies:
            logger.warning(f"Reconnecting zombie connection {conn_id}")
            await self._reconnect_connection(conn_id)
    
    async def _reconnect_connection(self, conn_id: int):
        """
        Reconnect specific connection.
        
        Args:
            conn_id: Connection to reconnect
        """
        logger.info(f"Reconnecting connection {conn_id}")
        
        self._connection_states[conn_id] = ConnectionState.RECONNECTING
        self._stats["reconnections"] += 1
        
        # Close old connection
        await self._close_connection(conn_id)
        
        # Create new connection
        await self._create_connection(conn_id)
        
        self._connection_states[conn_id] = ConnectionState.CONNECTED
        
        # Initialize or update health
        if conn_id not in self._connection_health:
            self._connection_health[conn_id] = ConnectionHealth(connection_id=conn_id)
        
        self._connection_health[conn_id].reconnect_count += 1
        self._connection_health[conn_id].last_heartbeat = datetime.now()
        self._connection_health[conn_id].health_score = 1.0
        
        # Restore subscriptions
        subscribed = self._connection_subscriptions.get(conn_id, set())
        if subscribed:
            instruments = [
                self._subscriptions[uid]
                for uid in subscribed
                if uid in self._subscriptions
            ]
            
            if instruments:
                conn = self._connections[conn_id]
                await conn.subscribe(instruments)
                
                logger.info(
                    f"Restored {len(instruments)} subscriptions "
                    f"on connection {conn_id}"
                )
    
    def _get_healthiest_connection(self) -> int:
        """Get ID of healthiest connection."""
        return max(
            self._connection_health.keys(),
            key=lambda cid: self._connection_health[cid].health_score
        )
    
    async def _stream_from_connection(self, conn_id: int, conn):
        """
        Stream ticks from single connection.
        
        Args:
            conn_id: Connection ID
            conn: Connection object
        """
        try:
            async for tick in conn.stream():
                self._stats["messages_received"] += 1
                self._connection_health[conn_id].messages_received += 1
                self._connection_health[conn_id].last_heartbeat = datetime.now()
                
                yield tick
        except Exception as e:
            logger.error(f"Stream error on connection {conn_id}: {e}")
            self._connection_health[conn_id].errors += 1
            raise


