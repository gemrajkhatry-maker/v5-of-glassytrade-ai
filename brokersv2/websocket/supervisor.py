"""
WebSocket connection supervisor for health monitoring and auto-reconnects.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from brokersv2.core.constants import WebSocket as WSConstants

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """WebSocket connection states."""
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    ERROR = "ERROR"


@dataclass
class HealthCheckResult:
    """Health check result."""
    healthy: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None


class ConnectionSupervisor:
    """
    WebSocket connection supervisor for health monitoring and reconnects.
    
    Handles:
    - Heartbeat ping/pong every 10 seconds
    - Auto-reconnect with exponential backoff
    - Connection state management
    """
    
    HEARTBEAT_INTERVAL = WSConstants.HEARTBEAT_INTERVAL
    MAX_RECONNECT_ATTEMPTS = WSConstants.MAX_RECONNECT_ATTEMPTS
    INITIAL_BACKOFF = WSConstants.INITIAL_BACKOFF
    MAX_BACKOFF = WSConstants.MAX_BACKOFF
    
    def __init__(
        self,
        websocket_url: str,
        client_id: str,
        access_token: str,
        on_connect=None,
        on_disconnect=None,
        on_error=None,
    ):
        self.websocket_url = websocket_url
        self.client_id = client_id
        self.access_token = access_token
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.on_error = on_error
        
        self._state = ConnectionState.DISCONNECTED
        self._websockets = []  # Multiple connections
        self._reconnect_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._reconnect_attempts = 0
        self._last_pong = 0.0
        self._connection_id = str(uuid.uuid4())
    
    @property
    def state(self) -> ConnectionState:
        """Current connection state."""
        return self._state
    
    @property
    def is_connected(self) -> bool:
        """Check if connected."""
        return self._state == ConnectionState.CONNECTED
    
    async def connect(self) -> bool:
        """Establish WebSocket connection."""
        if self._state in (ConnectionState.CONNECTING, ConnectionState.CONNECTED):
            return False
        
        self._state = ConnectionState.CONNECTING
        
        try:
            import websockets
            from websockets.asyncio.client import connect
            
            headers = {
                "access-token": self.access_token,
                "client-id": self.client_id,
            }
            
            websocket = await connect(
                self.websocket_url,
                additional_headers=headers,
            )
            
            self._websockets.append(websocket)
            self._state = ConnectionState.CONNECTED
            self._reconnect_attempts = 0
            self._last_pong = time.monotonic()
            
            if self.on_connect:
                await self.on_connect()
            
            # Start heartbeat
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(websocket))
            
            logger.info(f"WebSocket connected: {self._connection_id}")
            return True
            
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            self._state = ConnectionState.ERROR
            if self.on_error:
                await self.on_error(e)
            return False
    
    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        self._state = ConnectionState.DISCONNECTED
        
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        
        for ws in self._websockets:
            try:
                await ws.close()
            except Exception:
                pass
        
        self._websockets.clear()
        
        if self.on_disconnect:
            await self.on_disconnect()
        
        logger.info(f"WebSocket disconnected: {self._connection_id}")
    
    async def _heartbeat_loop(self, websocket) -> None:
        """Send periodic ping messages."""
        try:
            while self._state == ConnectionState.CONNECTED:
                await asyncio.sleep(self.HEARTBEAT_INTERVAL)
                
                try:
                    await websocket.ping()
                    self._last_pong = time.monotonic()
                except Exception as e:
                    logger.warning(f"Heartbeat failed: {e}")
                    # Check if connection is dead
                    if time.monotonic() - self._last_pong > self.HEARTBEAT_INTERVAL * 2:
                        await self._reconnect()
        except asyncio.CancelledError:
            pass
    
    async def health_check(self) -> HealthCheckResult:
        """Perform health check on connection."""
        if not self._websockets:
            return HealthCheckResult(healthy=False, error="No active connections")
        
        start = time.monotonic()
        try:
            for ws in self._websockets:
                await ws.ping()
            latency = (time.monotonic() - start) * 1000
            return HealthCheckResult(healthy=True, latency_ms=latency)
        except Exception as e:
            return HealthCheckResult(healthy=False, error=str(e))
    
    async def _reconnect(self) -> bool:
        """Attempt to reconnect with exponential backoff."""
        if self._reconnect_attempts >= self.MAX_RECONNECT_ATTEMPTS:
            logger.error("Max reconnect attempts reached")
            return False
        
        self._state = ConnectionState.RECONNECTING
        self._reconnect_attempts += 1
        
        backoff = min(
            self.INITIAL_BACKOFF * (2 ** (self._reconnect_attempts - 1)),
            self.MAX_BACKOFF,
        )
        
        logger.info(f"Reconnecting in {backoff}s (attempt {self._reconnect_attempts})")
        await asyncio.sleep(backoff)
        
        return await self.connect()