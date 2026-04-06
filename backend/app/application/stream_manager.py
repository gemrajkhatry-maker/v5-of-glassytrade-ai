"""Stream Manager — Handles market data streaming with reconnection.

Responsibilities:
- Market data streaming from broker
- WebSocket reconnection logic
- Polling fallback for MCX options
- Stream health monitoring
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

from app.config import settings
from app.application.utils import is_market_open

if TYPE_CHECKING:
    from app.domain.ports.market_data import MarketDataPort

logger = logging.getLogger(__name__)

from app.shared.timezones import IST

_DHAN_CONNECT_COOLDOWN: float = 5.0
_MAX_STREAM_RETRIES = 10


class StreamManager:
    """Manages market data streaming with reconnection and fallback.

    This module encapsulates all streaming logic, providing a single
    source of truth for market data streaming across the codebase.
    """

    def __init__(self, market_data: MarketDataPort):
        self._market_data = market_data
        self._polling_mode: bool = False
        self._last_any_tick_time: float = time.time()
        self._engine_start_time: float = time.time()
        self._tick_counts: dict[str, int] = {}
        self._active_symbols: list[str] = []
        self._running: bool = False

    def set_active_symbols(self, symbols: list[str]) -> None:
        """Set active symbols for streaming.

        Args:
            symbols: List of symbols to stream
        """
        self._active_symbols = symbols
        for sym in symbols:
            self._tick_counts[sym] = 0

    def set_running(self, running: bool) -> None:
        """Set running state.

        Args:
            running: Whether streaming is running
        """
        self._running = running

    def update_tick_time(self, symbol: str) -> None:
        """Update last tick time for a symbol.

        Args:
            symbol: Trading symbol
        """
        self._last_any_tick_time = time.time()
        self._tick_counts[symbol] = self._tick_counts.get(symbol, 0) + 1

    def get_tick_count(self, symbol: str) -> int:
        """Get tick count for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Tick count
        """
        return self._tick_counts.get(symbol, 0)

    def should_switch_to_polling(self) -> bool:
        """Check if should switch to polling fallback.

        Returns:
            True if should switch to polling
        """
        if self._polling_mode:
            return False

        uptime = time.time() - self._engine_start_time
        if uptime <= 60.0:  # Give WS 60s to deliver first tick
            return False

        # Check if any symbols have received ticks
        return all(self._tick_counts.get(s, 0) == 0 for s in self._active_symbols)

    def switch_to_polling(self) -> None:
        """Switch to polling mode."""
        self._polling_mode = True
        self._last_any_tick_time = time.time()
        logger.warning(
            "Stream: WS produced ZERO ticks after %.0fs — "
            "switching permanently to REST polling fallback",
            time.time() - self._engine_start_time,
        )

    def is_polling_mode(self) -> bool:
        """Check if in polling mode.

        Returns:
            True if in polling mode
        """
        return self._polling_mode

    def is_stale(self, threshold_seconds: float = 300.0) -> bool:
        """Check if stream is stale.

        Args:
            threshold_seconds: Staleness threshold

        Returns:
            True if stream is stale
        """
        return time.time() - self._last_any_tick_time > threshold_seconds

    def reset_staleness(self) -> None:
        """Reset staleness timer."""
        self._last_any_tick_time = time.time()

    async def stream_with_reconnect(self, connect_state: list[float]):
        """Stream ticks with reconnection logic.

        Args:
            connect_state: Connection state tracking

        Yields:
            Tick packets
        """
        consecutive_failures = 0
        from app.config import settings

        _latest_depth = {}

        async def _depth_worker():
            try:
                logger.info("StreamManager: Depth WS connection starting (Depth 20)...")
                # Using hasattr to gracefully fall back if port implementation skips it
                if not hasattr(self._market_data, "stream_depth_20"):
                    logger.warning(
                        "StreamManager: stream_depth_20 not supported by adapter"
                    )
                    return

                async for depth in self._market_data.stream_depth_20(
                    self._active_symbols
                ):
                    sym = getattr(depth, "symbol", "")
                    if not sym:
                        continue
                    side = getattr(depth, "side", "bid").lower()
                    if sym not in _latest_depth:
                        _latest_depth[sym] = {"bid": [], "ask": []}

                    levels = getattr(depth, "levels", [])
                    _latest_depth[sym][side] = [
                        {"price": lvl.price, "qty": lvl.quantity} for lvl in levels
                    ]
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning("StreamManager: Depth stream error: %s", e)

        depth_task = None
        poll_task = None

        if settings.DEFAULT_EXCHANGE == "NSE" and not self._polling_mode:
            logger.info("StreamManager: Dual-Stream enabled (Full + Depth 20)")
            depth_task = asyncio.create_task(_depth_worker())

        # Polling task for symbols unresolved by WebSocket (GOLD/SILVER MCX options)
        async def _poll_unresolved_worker(queue: asyncio.Queue):
            """Poll symbols that receive no WebSocket data."""
            await asyncio.sleep(30)  # Wait 30s to see which symbols get WS data
            while self._running:
                unresolved = [
                    s for s in self._active_symbols if self._tick_counts.get(s, 0) == 0
                ]
                if not unresolved:
                    await asyncio.sleep(30)
                    continue
                logger.info(
                    "Stream: starting REST polling for %d unresolved symbols: %s",
                    len(unresolved),
                    unresolved[:3],
                )
                try:
                    async for pkt in self._market_data.stream_poll(
                        unresolved, poll_interval=5.0
                    ):
                        if not self._running:
                            break
                        await queue.put(pkt)
                except Exception as e:
                    logger.debug("Polling error for unresolved symbols: %s", e)
                    await asyncio.sleep(5)

        try:
            # Start polling task for unresolved symbols (GOLD/SILVER MCX options)
            _poll_queue: asyncio.Queue = asyncio.Queue()
            poll_task = asyncio.create_task(
                self._run_poll_worker(_poll_unresolved_worker, _poll_queue)
            )

            while self._running:
                # Drain polling queue first (non-blocking)
                while not _poll_queue.empty():
                    try:
                        pkt = _poll_queue.get_nowait()
                        yield pkt
                    except Exception:
                        break

                # Polling fallback path
                if self._polling_mode:
                    logger.info(
                        "Stream: using REST polling fallback (polling_mode=True)"
                    )
                    try:
                        async for pkt in self._market_data.stream_poll(
                            self._active_symbols, poll_interval=3.0
                        ):
                            consecutive_failures = 0
                            yield pkt
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.warning("Stream: polling error, retrying in 5s: %s", e)
                        await asyncio.sleep(5)
                    continue

                # Normal WS streaming path
                now = asyncio.get_event_loop().time()
                since_last = now - connect_state[0]
                if since_last < _DHAN_CONNECT_COOLDOWN:
                    await asyncio.sleep(_DHAN_CONNECT_COOLDOWN - since_last)
                connect_state[0] = asyncio.get_event_loop().time()

                try:
                    async for pkt in self._market_data.stream_full(
                        self._active_symbols
                    ):
                        consecutive_failures = 0

                        # Handle Dual stream merge
                        sym = pkt.get("symbol", "")
                        if sym and sym in _latest_depth:
                            cached = _latest_depth[sym]
                            if "bid" in cached and len(cached["bid"]) > 0:
                                pkt["depth_bids"] = cached["bid"]
                            if "ask" in cached and len(cached["ask"]) > 0:
                                pkt["depth_asks"] = cached["ask"]

                        yield pkt
                    logger.info("Stream: ended cleanly, reconnecting...")
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    consecutive_failures += 1
                    if consecutive_failures >= _MAX_STREAM_RETRIES:
                        logger.error(
                            "Stream: failed %d times — giving up", consecutive_failures
                        )
                        yield {"_stream_dead": True}
                        return
                    wait = min(5 * (2 ** (consecutive_failures - 1)), 60)
                    logger.warning(
                        "Stream: disconnected (attempt %d/%d), retry in %ds: %s",
                        consecutive_failures,
                        _MAX_STREAM_RETRIES,
                        wait,
                        e,
                    )
                    await asyncio.sleep(wait)
        finally:
            if depth_task:
                depth_task.cancel()
            if poll_task:
                poll_task.cancel()

    async def _run_poll_worker(self, worker_fn, queue: asyncio.Queue):
        """Run the polling worker and put results into the queue."""
        try:
            async for pkt in worker_fn(queue):
                await queue.put(pkt)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("Poll worker ended: %s", e)
