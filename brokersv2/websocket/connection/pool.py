"""
WebSocket Connection Pool.

Manages a pool of WebSocket connections with:
- Health-based allocation
- Automatic pruning of unhealthy connections
- Connection lifecycle management
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from brokersv2.core.constants import WebSocket as WSConstants, WSManager
from brokersv2.websocket.connection.manager import ConnectionHealth, ConnectionState

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """WebSocket connection states."""
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"
    FAILED = "FAILED"


@dataclass
class PoolConnection:
    """Represents a pooled WebSocket connection."""
    connection_id: int
    health: ConnectionHealth
    state: ConnectionState = ConnectionState.DISCONNECTED
    subscription_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    last_used: datetime = field(default_factory=datetime.now)
    
    @property
    def is_available(self) -> bool:
        """Check if connection is available for use."""
        return (
            self.state == ConnectionState.CONNECTED
            and self.health.is_healthy
        )


class ConnectionPool:
    """
    Pool of WebSocket connections with health-based allocation.
    
    Features:
    - Fixed-size pool (max 5 for DhanHQ)
    - Health-score based connection selection
    - Automatic pruning of unhealthy connections
    - Subscription count tracking
    
    Usage:
        pool = ConnectionPool(max_size=3)
        conn = pool.acquire()
        # use connection
        pool.release(conn)
    """
    
    def __init__(self, max_size: int = None):
        """
        Initialize connection pool.
        
        Args:
            max_size: Maximum pool size (1-5), defaults to WSConstants.MAX_CONNECTIONS
        """
        self._max_size = max_size or WSConstants.MAX_CONNECTIONS
        if self._max_size > WSConstants.MAX_CONNECTIONS:
            raise ValueError("Maximum 5 connections allowed for DhanHQ")
        
        self._max_size = max_size
        self._pool: Dict[int, PoolConnection] = {}
        self._available: set = set()
        
        logger.info(f"ConnectionPool created (max_size={max_size})")
    
    def add_connection(self, conn_id: int) -> PoolConnection:
        """
        Add connection to pool.
        
        Args:
            conn_id: Connection ID
            
        Returns:
            PoolConnection instance
        """
        if len(self._pool) >= self._max_size:
            raise ValueError(f"Pool full (max {self._max_size})")
        
        health = ConnectionHealth(connection_id=conn_id)
        conn = PoolConnection(
            connection_id=conn_id,
            health=health,
            state=State.DISCONNECTED,
        )
        
        self._pool[conn_id] = conn
        logger.info(f"Added connection {conn_id} to pool")
        
        return conn
    
    def remove_connection(self, conn_id: int) -> bool:
        """
        Remove connection from pool.
        
        Args:
            conn_id: Connection ID
            
        Returns:
            True if removed
        """
        if conn_id in self._pool:
            del self._pool[conn_id]
            self._available.discard(conn_id)
            logger.info(f"Removed connection {conn_id} from pool")
            return True
        
        return False
    
    def acquire(self) -> Optional[PoolConnection]:
        """
        Acquire healthiest available connection.
        
        Returns:
            Healthiest connection or None
        """
        available_conns = [
            conn for conn in self._pool.values()
            if conn.is_available
        ]
        
        if not available_conns:
            return None
        
        # Select healthiest
        best = max(available_conns, key=lambda c: c.health.health_score)
        best.last_used = datetime.now()
        
        logger.debug(f"Acquired connection {best.connection_id} (health={best.health.health_score:.2f})")
        
        return best
    
    def release(self, conn_id: int):
        """
        Release connection back to pool.
        
        Args:
            conn_id: Connection ID
        """
        if conn_id in self._pool:
            self._pool[conn_id].last_used = datetime.now()
            logger.debug(f"Released connection {conn_id}")
    
    def update_health(self, conn_id: int, stale_threshold: int = 20):
        """
        Update connection health score.
        
        Args:
            conn_id: Connection ID
            stale_threshold: Stale heartbeat threshold
        """
        conn = self._pool.get(conn_id)
        if conn:
            conn.health.update_health_score(stale_threshold)
    
    def prune_unhealthy(self) -> List[int]:
        """
        Remove unhealthy connections from pool.
        
        Returns:
            List of removed connection IDs
        """
        unhealthy = [
            conn_id for conn_id, conn in self._pool.items()
            if not conn.health.is_healthy
        ]
        
        for conn_id in unhealthy:
            self.remove_connection(conn_id)
        
        if unhealthy:
            logger.info(f"Pruned {len(unhealthy)} unhealthy connections")
        
        return unhealthy
    
    def get_statistics(self) -> Dict:
        """Get pool statistics."""
        total = len(self._pool)
        healthy = sum(1 for c in self._pool.values() if c.health.is_healthy)
        available = sum(1 for c in self._pool.values() if c.is_available)
        
        return {
            "total": total,
            "healthy": healthy,
            "available": available,
            "unhealthy": total - healthy,
            "max_size": self._max_size,
        }
    
    @property
    def size(self) -> int:
        """Current pool size."""
        return len(self._pool)
    
    @property
    def max_size(self) -> int:
        """Maximum pool size."""
        return self._max_size
