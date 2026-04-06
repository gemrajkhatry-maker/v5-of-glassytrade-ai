"""
WebSocket publisher — broadcast signals to connected clients.

Manages WebSocket connections and broadcasts signals.
"""

import asyncio
from typing import Dict, List, Set

import orjson
import structlog
from fastapi import WebSocket

logger = structlog.get_logger()


class WSPublisher:
    """
    WebSocket publisher for real-time signal broadcasting.

    Features:
    - Multiple client connections
    - Broadcast to all connected clients
    - Connection management
    """

    def __init__(self):
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """
        Accept and register a new WebSocket connection.

        Args:
            websocket: FastAPI WebSocket instance
        """
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        logger.info("ws_client_connected", total=len(self._connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        """
        Remove a WebSocket connection.

        Args:
            websocket: FastAPI WebSocket instance
        """
        async with self._lock:
            self._connections.discard(websocket)
        logger.info("ws_client_disconnected", total=len(self._connections))

    async def broadcast(self, message: Dict) -> None:
        """
        Broadcast a message to all connected clients.

        Args:
            message: Message dict to broadcast
        """
        if not self._connections:
            return

        data = orjson.dumps(message)

        async with self._lock:
            disconnected = set()
            for ws in self._connections:
                try:
                    await ws.send_bytes(data)
                except Exception:
                    disconnected.add(ws)

            # Remove disconnected clients
            for ws in disconnected:
                self._connections.discard(ws)

    async def broadcast_signal(self, signal: Dict) -> None:
        """
        Broadcast a signal to all connected clients.

        Args:
            signal: Signal dict from OutputSchema
        """
        message = {
            "type": "SIGNAL",
            "data": signal,
        }
        await self.broadcast(message)

    async def broadcast_trade_update(self, trade_id: str, action: str, details: Dict) -> None:
        """
        Broadcast a trade update.

        Args:
            trade_id: Trade identifier
            action: Action type (ENTRY, EXIT, PYRAMID, etc.)
            details: Additional details
        """
        message = {
            "type": "TRADE_UPDATE",
            "data": {
                "trade_id": trade_id,
                "action": action,
                **details,
            },
        }
        await self.broadcast(message)

    async def broadcast_risk_event(self, event_type: str, details: Dict) -> None:
        """
        Broadcast a risk event.

        Args:
            event_type: Event type (DAILY_LOSS, DRAWDOWN, etc.)
            details: Additional details
        """
        message = {
            "type": "RISK_EVENT",
            "data": {
                "event_type": event_type,
                **details,
            },
        }
        await self.broadcast(message)

    async def broadcast_heartbeat(self) -> None:
        """Broadcast heartbeat to keep connections alive."""
        message = {
            "type": "HEARTBEAT",
            "data": {
                "timestamp": asyncio.get_event_loop().time(),
                "clients": len(self._connections),
            },
        }
        await self.broadcast(message)

    @property
    def connection_count(self) -> int:
        """Get number of connected clients."""
        return len(self._connections)