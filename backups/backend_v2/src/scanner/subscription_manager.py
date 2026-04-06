"""
Subscription manager — dynamic WebSocket subscriptions.

Manages instrument subscriptions with periodic rebalancing.
"""

import asyncio
from typing import Callable, Dict, List, Optional

import structlog

from src.config.instruments import INSTRUMENTS, InstrumentConfig

logger = structlog.get_logger()


class SubscriptionManager:
    """
    Manage dynamic WebSocket subscriptions.

    Features:
    - Add/remove symbols
    - Periodic rebalancing (5 minutes)
    - Subscription callbacks
    """

    def __init__(
        self,
        subscribe_callback: Callable[[List[Dict]], None],
        rebalance_interval: int = 300,  # 5 minutes
    ):
        self._subscribe_callback = subscribe_callback
        self._rebalance_interval = rebalance_interval
        self._active_symbols: Dict[str, InstrumentConfig] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def add_symbol(self, symbol: str) -> None:
        """
        Add a symbol to subscription list.

        Args:
            symbol: Trading symbol
        """
        if symbol in INSTRUMENTS:
            self._active_symbols[symbol] = INSTRUMENTS[symbol]
            logger.info("subscription_added", symbol=symbol)

    def remove_symbol(self, symbol: str) -> None:
        """
        Remove a symbol from subscription list.

        Args:
            symbol: Trading symbol
        """
        if symbol in self._active_symbols:
            del self._active_symbols[symbol]
            logger.info("subscription_removed", symbol=symbol)

    def get_instruments(self) -> List[Dict]:
        """
        Get instrument list for WebSocket subscription.

        Returns:
            List of instrument dicts for Dhan API.
        """
        instruments = []
        for symbol, config in self._active_symbols.items():
            instruments.append({
                "ExchangeSegment": f"{config.exchange}_COMM" if config.exchange == "MCX" else f"{config.exchange}_FO",
                "SecurityId": config.security_id,
            })
        return instruments

    async def start(self) -> None:
        """Start periodic rebalancing."""
        self._running = True
        self._task = asyncio.create_task(self._rebalance_loop())
        logger.info("subscription_manager_started")

    async def stop(self) -> None:
        """Stop periodic rebalancing."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("subscription_manager_stopped")

    async def _rebalance_loop(self) -> None:
        """Periodic rebalancing loop."""
        while self._running:
            try:
                instruments = self.get_instruments()
                if instruments:
                    self._subscribe_callback(instruments)
                    logger.info("subscriptions_rebalanced", count=len(instruments))
            except Exception as e:
                logger.error("rebalance_error", error=str(e))

            await asyncio.sleep(self._rebalance_interval)

    def get_active_symbols(self) -> List[str]:
        """Get list of active symbols."""
        return list(self._active_symbols.keys())