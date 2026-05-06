"""Dhan broker feed source - streams live ticks from DhanAdapter.

This feed wraps the DhanAdapter broker connection and yields normalized
Tick objects for the pipeline to process.
"""
from __future__ import annotations

import logging
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
    
    def name(self) -> str:
        """Return human-readable feed name."""
        return "DhanLiveFeed"
    
    def start(self) -> None:
        """Start feed streaming."""
        self._running = True
        logger.info("DhanFeedSource started")
    
    def stop(self) -> None:
        """Stop feed streaming."""
        self._running = False
        logger.info("DhanFeedSource stopped")
    
    def stream(self):
        """Yield normalized Tick objects from DhanAdapter.
        
        Continuously polls adapter for new ticks and yields them.
        Skips None/invalid ticks to handle broker disconnections gracefully.
        """
        while self._running:
            try:
                raw = self._market_data.get_next_tick()
                
                # Skip None ticks (no data available)
                if raw is None:
                    time.sleep(0.1)
                    continue
                
                # Validate required fields
                if not isinstance(raw, dict):
                    logger.warning("Invalid tick format: expected dict, got %s", type(raw))
                    time.sleep(0.1)
                    continue
                
                price = raw.get("price")
                if price is None or price <= 0:
                    logger.debug("Skipping tick with invalid price: %s", price)
                    time.sleep(0.1)
                    continue
                
                # Convert to normalized Tick
                tick = Tick(
                    symbol=raw.get("symbol", ""),
                    price=float(price),
                    volume=float(raw.get("volume", 0)),
                    timestamp=float(raw.get("timestamp", time.time())) * 1_000_000_000,  # Convert to nanoseconds
                    bid=float(raw.get("bid", 0)),
                    ask=float(raw.get("ask", 0)),
                    bid_volume=float(raw.get("bid_volume", 0)),
                    ask_volume=float(raw.get("ask_volume", 0)),
                    exchange=raw.get("exchange", ""),
                )
                
                yield tick
                
            except Exception as exc:
                logger.warning("Error processing tick from Dhan: %s", exc, exc_info=True)
                time.sleep(0.1)
                continue
    
    @property
    def symbols(self) -> list[str]:
        """Return symbols handled by this feed."""
        return list(self._symbols)
    
    def snapshot(self) -> dict:
        """Capture feed metadata for observability."""
        return {
            "name": self.name(),
            "running": self._running,
            "symbols": self.symbols,
        }
