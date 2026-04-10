"""Stream Manager — WebSocket tick ingestion with auto-reconnect.

Wraps the existing brokers/ library StreamingService for live data.
Features:
- Auto-reconnect with exponential backoff
- Tick demultiplexing by symbol
- Health tracking
- Emergency pause/resume
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Awaitable
from appv2.domain.models.tick import Tick

logger = logging.getLogger(__name__)


@dataclass
class StreamHealth:
    connected: bool
    symbols_subscribed: list[str]
    ticks_received: int
    last_tick_time: float
    reconnect_count: int
    is_paused: bool


class StreamManager:
    """Manages WebSocket connection to Dhan market data feed.

    Usage:
        mgr = StreamManager(broker=broker_adapter)
        mgr.on_tick = my_tick_handler
        await mgr.start()
        await mgr.subscribe(["NIFTY", "CRUDEOIL"])
    """

    def __init__(self, broker=None):
        """
        Args:
            broker: DhanMarketDataAdapter instance (from infrastructure)
        """
        self._broker = broker
        self._symbols: list[str] = []
        self._on_tick: Callable[[str, Tick], Awaitable[None]] | None = None
        self._running = False
        self._paused = False

        # Health tracking
        self._health = StreamHealth(
            connected=False,
            symbols_subscribed=[],
            ticks_received=0,
            last_tick_time=0.0,
            reconnect_count=0,
            is_paused=False,
        )

        # Reconnect tracking
        self._reconnect_task: asyncio.Task | None = None
        self._stream_task: asyncio.Task | None = None

    @property
    def on_tick(self) -> Callable[[str, Tick], Awaitable[None]] | None:
        return self._on_tick

    @on_tick.setter
    def on_tick(self, handler: Callable[[str, Tick], Awaitable[None]]) -> None:
        self._on_tick = handler

    async def start(self) -> None:
        """Start the WebSocket stream."""
        if self._running:
            logger.warning("StreamManager already running")
            return

        self._running = True
        self._paused = False

        if self._broker:
            try:
                await self._broker.start_stream(self._handle_tick)
                self._health.connected = True
                logger.info("StreamManager started — connected to Dhan WebSocket")
            except Exception as e:
                logger.error("Failed to start stream: %s", e)
                self._health.connected = False
                self._schedule_reconnect()
        else:
            logger.warning("StreamManager: no broker adapter — running in offline mode")

    async def stop(self) -> None:
        """Stop the WebSocket stream."""
        self._running = False

        if self._stream_task:
            self._stream_task.cancel()
        if self._reconnect_task:
            self._reconnect_task.cancel()

        if self._broker:
            try:
                await self._broker.stop_stream()
            except Exception as e:
                logger.error("Error stopping stream: %s", e)

        self._health.connected = False
        logger.info("StreamManager stopped")

    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to symbols."""
        if self._broker:
            await self._broker.subscribe(symbols)
        self._symbols = list(set(self._symbols + symbols))
        self._health.symbols_subscribed = list(self._symbols)
        logger.info("Subscribed to: %s", symbols)

    async def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe from symbols."""
        if self._broker:
            await self._broker.unsubscribe(symbols)
        for sym in symbols:
            if sym in self._symbols:
                self._symbols.remove(sym)
        self._health.symbols_subscribed = list(self._symbols)
        logger.info("Unsubscribed from: %s", symbols)

    def pause(self) -> None:
        """Pause tick processing (keeps WebSocket connected)."""
        self._paused = True
        self._health.is_paused = True
        logger.info("StreamManager paused")

    def resume(self) -> None:
        """Resume tick processing."""
        self._paused = False
        self._health.is_paused = False
        logger.info("StreamManager resumed")

    async def _handle_tick(self, symbol: str, tick: Tick) -> None:
        """Handle incoming tick from WebSocket."""
        if not self._running or self._paused:
            return

        self._health.ticks_received += 1
        self._health.last_tick_time = time.time()

        if self._on_tick:
            try:
                await self._on_tick(symbol, tick)
            except Exception as e:
                logger.error("Tick handler error for %s: %s", symbol, e)

    def _schedule_reconnect(self) -> None:
        """Schedule reconnection attempt."""
        if self._reconnect_task and not self._reconnect_task.done():
            return

        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Reconnect with exponential backoff."""
        backoff = 1.0
        max_backoff = 30.0

        while self._running and not self._health.connected:
            self._health.reconnect_count += 1
            logger.info(
                "Reconnecting (attempt %d, backoff=%.1fs)...",
                self._health.reconnect_count, backoff,
            )

            await asyncio.sleep(backoff)

            if self._broker:
                try:
                    await self._broker.start_stream(self._handle_tick)
                    self._health.connected = True
                    logger.info("Reconnected successfully")
                    break
                except Exception as e:
                    logger.warning("Reconnect failed: %s", e)

            backoff = min(backoff * 2, max_backoff)

    def get_health(self) -> StreamHealth:
        return self._health

    @property
    def is_connected(self) -> bool:
        return self._health.connected and not self._paused

    @property
    def ticks_received(self) -> int:
        return self._health.ticks_received

    @property
    def symbols(self) -> list[str]:
        return list(self._symbols)
