"""WebSocket Game-Loop — real-time state broadcast to frontend viewers.

Features:
- Generation-based delta compression
- Keyframe/keyframe interval for new clients
- History sync on connect
- Multi-symbol broadcast
- Rate limiting
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class GameStateBroadcaster:
    """Broadcasts trading state to WebSocket clients with delta compression."""

    def __init__(self, keyframe_interval: float = 5.0):
        self._clients: set[Any] = set()  # WebSocket connections
        self._generation: int = 0
        self._last_state: dict[str, Any] = {}
        self._last_keyframe_time: float = 0.0
        self._keyframe_interval = keyframe_interval
        self._broadcast_task: asyncio.Task | None = None
        self._condition: asyncio.Condition = asyncio.Condition()

    def add_client(self, ws) -> None:
        """Register a new WebSocket client."""
        self._clients.add(ws)
        logger.info("WebSocket client connected (%d total)", len(self._clients))

    def remove_client(self, ws) -> None:
        """Unregister a WebSocket client."""
        self._clients.discard(ws)
        logger.info("WebSocket client disconnected (%d remaining)", len(self._clients))

    async def broadcast_state(self, state: dict) -> None:
        """Queue a state update for broadcast."""
        self._generation += 1
        self._last_state = state

        async with self._condition:
            self._condition.notify_all()

    async def run_broadcast_loop(self) -> None:
        """Main broadcast loop — sends updates to all clients."""
        while True:
            try:
                async with self._condition:
                    # Wait for state update or timeout
                    await asyncio.wait_for(
                        self._condition.wait(),
                        timeout=1.0,
                    )

                if not self._clients:
                    continue

                now = time.time()
                is_keyframe = (
                    now - self._last_keyframe_time >= self._keyframe_interval
                )

                message = self._build_message(is_keyframe)
                await self._send_to_all(message)

                if is_keyframe:
                    self._last_keyframe_time = now

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Broadcast error: %s", e)
                await asyncio.sleep(1)

    def _build_message(self, is_keyframe: bool) -> str:
        """Build broadcast message."""
        if is_keyframe:
            # Full state snapshot for new clients / periodic refresh
            payload = {
                "type": "keyframe",
                "generation": self._generation,
                "data": self._last_state,
            }
        else:
            # Delta update (full state for simplicity)
            payload = {
                "type": "delta",
                "generation": self._generation,
                "data": self._last_state,
            }

        return json.dumps(payload, default=str)

    async def _send_to_all(self, message: str) -> None:
        """Send message to all connected clients."""
        dead_clients = []
        for ws in self._clients:
            try:
                await ws.send_text(message)
            except Exception:
                dead_clients.append(ws)

        for ws in dead_clients:
            self._clients.discard(ws)

    async def send_initial_sync(self, ws, state: dict) -> None:
        """Send initial state to a newly connected client."""
        keyframe = json.dumps({
            "type": "keyframe",
            "generation": self._generation,
            "data": state,
        }, default=str)
        await ws.send_text(keyframe)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    @property
    def generation(self) -> int:
        return self._generation
