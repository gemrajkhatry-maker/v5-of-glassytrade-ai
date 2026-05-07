"""Dhan broker feed source - streams live ticks from DhanAdapter.

This feed wraps the DhanAdapter broker connection and yields normalized
Tick objects for the pipeline to process.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
import logging
import queue
import threading
import time
from typing import Any

from app.runtime.feeds import FeedSource
from app.runtime.pipeline.events import Tick

logger = logging.getLogger(__name__)


class DhanFeedSource(FeedSource):
    """Live feed source for Dhan broker.
    
    Wraps DhanAdapter and yields normalized Tick objects.
    Handles broker disconnections gracefully by skipping invalid ticks.
    """
    
    def __init__(self, market_data: Any, symbols: list[str] | None = None):
        """Initialize Dhan feed source.
        
        Args:
            market_data: DhanAdapter instance
            symbols: List of symbols to stream (optional, auto-detected if None)
        """
        self._market_data = market_data
        self._symbols = symbols or []
        self._running = False
        self._state = "stopped"
        self._queue: queue.Queue[dict | None] = queue.Queue(maxsize=4096)
        self._producer: threading.Thread | None = None
        self._producer_error: str = ""
        self._last_error_at = 0.0
        self._dropped_ticks = 0
        self._ticks_seen = 0
        self._last_tick_monotonic = 0.0
        self._last_tick_timestamp = 0.0
        self._first_tick_monotonic = 0.0
    
    def name(self) -> str:
        """Return human-readable feed name."""
        return "DhanLiveFeed"
    
    def start(self) -> None:
        """Start feed streaming."""
        self._running = True
        self._state = "running"
        if self._uses_stream_full() and (self._producer is None or not self._producer.is_alive()):
            self._producer = threading.Thread(
                target=self._run_stream_full_producer,
                name="dhan-feed-producer",
                daemon=True,
            )
            self._producer.start()
        logger.info("DhanFeedSource started")
    
    def stop(self) -> None:
        """Stop feed streaming."""
        self._running = False
        self._state = "stopped"
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        logger.info("DhanFeedSource stopped")
    
    def stream(self):
        """Yield normalized Tick objects from DhanAdapter.
        
        Continuously polls adapter for new ticks and yields them.
        Skips None/invalid ticks to handle broker disconnections gracefully.
        """
        while self._running:
            if self._state in {"drained", "failed"}:
                break
            try:
                raw = self._next_raw_tick()
                
                # Skip None ticks (no data available)
                if raw is None:
                    time.sleep(0.1)
                    continue
                
                # Validate required fields
                if not isinstance(raw, dict):
                    logger.warning("Invalid tick format: expected dict, got %s", type(raw))
                    time.sleep(0.1)
                    continue
                
                raw_price = raw.get("price", raw.get("ltp"))
                try:
                    price = float(raw_price)
                except (TypeError, ValueError):
                    price = 0.0
                if price <= 0:
                    logger.debug("Skipping tick with invalid price: %s", price)
                    time.sleep(0.1)
                    continue
                
                # Convert to normalized Tick
                tick = self._to_tick(raw, price)
                self._last_tick_monotonic = time.monotonic()
                self._ticks_seen += 1
                if self._first_tick_monotonic == 0.0:
                    self._first_tick_monotonic = self._last_tick_monotonic
                self._last_tick_timestamp = tick.timestamp
                
                yield tick
                
            except Exception as exc:
                logger.warning("Error processing tick from Dhan: %s", exc, exc_info=True)
                self._producer_error = str(exc)
                self._last_error_at = time.time()
                time.sleep(0.1)
                continue
    
    @property
    def symbols(self) -> list[str]:
        """Return symbols handled by this feed."""
        return list(self._symbols)

    def _uses_stream_full(self) -> bool:
        has_declared_stream = any(
            "stream_full" in getattr(cls, "__dict__", {})
            for cls in type(self._market_data).mro()
        ) or "stream_full" in getattr(self._market_data, "__dict__", {})
        return bool(self._symbols) and has_declared_stream and callable(
            getattr(self._market_data, "stream_full", None)
        )

    def _next_raw_tick(self) -> dict | None:
        if self._uses_stream_full():
            try:
                return self._queue.get(timeout=0.5)
            except queue.Empty:
                return None
        legacy_next = getattr(self._market_data, "get_next_tick", None)
        if callable(legacy_next):
            return legacy_next()
        raise AttributeError("market_data adapter must expose stream_full(symbols) or get_next_tick()")

    def _run_stream_full_producer(self) -> None:
        self._state = "running"
        async def _produce() -> None:
            async for raw in self._market_data.stream_full(self._symbols):
                if not self._running:
                    break
                if not isinstance(raw, dict):
                    self._dropped_ticks += 1
                    continue
                try:
                    self._queue.put(raw, timeout=0.5)
                except queue.Full:
                    self._dropped_ticks += 1
                    self._producer_error = "queue_full"

        while self._running:
            try:
                asyncio.run(_produce())
                if self._state != "running":
                    break
                self._state = "drained"
                break
            except Exception as exc:
                self._producer_error = str(exc)
                self._last_error_at = time.time()
                self._state = "failed"
                logger.warning("Dhan stream_full producer failed: %s", exc, exc_info=True)
                time.sleep(1.0)

    def _to_tick(self, raw: dict, price: float) -> Tick:
        depth_bids = tuple(
            (float(item.get("price", 0.0)), float(item.get("quantity", item.get("qty", 0.0))))
            for item in raw.get("depth_bids", raw.get("bids", [])) or []
            if isinstance(item, dict)
        )
        depth_asks = tuple(
            (float(item.get("price", 0.0)), float(item.get("quantity", item.get("qty", 0.0))))
            for item in raw.get("depth_asks", raw.get("asks", [])) or []
            if isinstance(item, dict)
        )
        return Tick(
            symbol=str(raw.get("symbol", "")),
            price=price,
            volume=float(raw.get("volume", raw.get("ltq", 0)) or 0),
            timestamp=self._to_nanoseconds(raw.get("timestamp", time.time())),
            bid=float(raw.get("bid", depth_bids[0][0] if depth_bids else 0) or 0),
            ask=float(raw.get("ask", depth_asks[0][0] if depth_asks else 0) or 0),
            bid_volume=float(raw.get("bid_volume", raw.get("total_buy_qty", 0)) or 0),
            ask_volume=float(raw.get("ask_volume", raw.get("total_sell_qty", 0)) or 0),
            exchange=str(raw.get("exchange", "")),
            depth_bids=depth_bids,
            depth_asks=depth_asks,
            is_depth=bool(depth_bids or depth_asks),
        )

    @staticmethod
    def _to_nanoseconds(timestamp: object) -> float:
        if isinstance(timestamp, str):
            try:
                return datetime.fromisoformat(timestamp).timestamp() * 1_000_000_000
            except ValueError:
                return time.time() * 1_000_000_000
        try:
            value = float(timestamp)
        except (TypeError, ValueError):
            return time.time() * 1_000_000_000
        if value > 1_000_000_000_000:
            return value
        return value * 1_000_000_000
    
    def snapshot(self) -> dict:
        """Capture feed metadata for observability."""
        return {
            "name": self.name(),
            "state": self._state,
            "running": self._running,
            "symbols": self.symbols,
            "uses_stream_full": self._uses_stream_full(),
            "ticks_seen": self._ticks_seen,
            "queue_depth": self._queue.qsize(),
            "dropped_ticks": self._dropped_ticks,
            "last_tick_timestamp": self._last_tick_timestamp,
            "first_tick_age_sec": (
                time.monotonic() - self._first_tick_monotonic
                if self._first_tick_monotonic > 0
                else None
            ),
            "last_tick_age_sec": (
                time.monotonic() - self._last_tick_monotonic
                if self._last_tick_monotonic > 0
                else None
            ),
            "producer_error": self._producer_error,
            "last_error_at": (
                time.time() - self._last_error_at
                if self._last_error_at > 0
                else None
            ),
        }
